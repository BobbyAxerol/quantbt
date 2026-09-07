"""Prepared Python callback adapter outside execution-engine ownership."""

from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter_ns
from typing import Callable

from ..core.reactive import NativeEventStrategyError
from .commands import CommandBatchView, CommandWriter
from .context import StrategyContextView
from .requirements import StrategyContextRequirements, resolve_strategy_requirements


@dataclass(slots=True)
class PreparedStrategyAdapter:
    strategy: object
    requirements: StrategyContextRequirements
    writer: CommandWriter
    strategy_id: str
    callback_count: int = 0
    skipped_callback_count: int = 0
    legacy_command_objects: int = 0
    writer_command_rows: int = 0
    writer_materialized_command_objects: int = 0
    context_projection_bytes: int = 0
    callback_ns: int = 0
    callback_binding_mode: str = "dynamic_compatibility_v1"
    callback_plan_compile_ns: int = 0
    callback_plan_compile_lookup_count: int = 0
    callback_lookup_ns: int = 0
    callback_dynamic_lookup_count: int = 0
    callback_schedule_check_count: int = 0
    callback_suppressed_without_lookup_count: int = 0
    _callback_every_bar: bool = True
    _callback_period: int | None = 1
    _callback_explicit_bars: frozenset[int] = frozenset()
    _callback_on_fill: bool = True
    _callback_on_order_event: bool = True
    _callback_on_liquidation: bool = True
    _callback_plan: dict[str, Callable | object | None] | None = None

    @classmethod
    def prepare(cls, strategy, *, writer_capacity: int = 8, writer_hard_limit: int = 65_536):
        requirements = resolve_strategy_requirements(strategy)
        strategy_id = getattr(strategy, "strategy_id", strategy.__class__.__qualname__)
        adapter = cls(
            strategy=strategy,
            requirements=requirements,
            writer=CommandWriter(writer_capacity, writer_hard_limit),
            strategy_id=str(strategy_id),
        )
        adapter._compile_callback_schedule()
        adapter._compile_callback_plan()
        return adapter

    def _compile_callback_schedule(self) -> None:
        """Resolve immutable wake predicates once for this strategy run.

        A declared sparse strategy must not pay a dynamic method lookup on a
        bar where its schedule proves that no callback can occur. The public
        ``CallbackSchedule`` remains the semantic oracle; these fields are its
        prepared representation only.
        """

        schedule = self.requirements.callback
        self._callback_every_bar = bool(schedule.is_every_bar)
        self._callback_period = schedule.every_n_bars
        self._callback_explicit_bars = frozenset(int(bar) for bar in schedule.explicit_bars)
        self._callback_on_fill = bool(schedule.on_fill)
        self._callback_on_order_event = bool(schedule.on_order_event)
        self._callback_on_liquidation = bool(schedule.on_liquidation)

    def _compile_callback_plan(self) -> None:
        """Pin callbacks only when a strategy explicitly declares them stable.

        Compatibility callbacks remain dynamic by default: a strategy which
        replaces a lifecycle method during a run continues to be observed on
        its next callback.  The opt-in mirrors the Rust numeric co-runtime
        marker so the two public strategy boundaries report the same policy.
        """

        started = perf_counter_ns()
        marker = getattr(self.strategy, "quantbt_reactive_callback_binding_v1", False)
        if isinstance(marker, bool):
            run_stable = marker
        elif isinstance(marker, str):
            normalized = marker.lower().strip()
            if normalized in {"run_stable", "pinned"}:
                run_stable = True
            elif normalized in {"dynamic", "compatibility"}:
                run_stable = False
            else:
                raise ValueError(
                    "quantbt_reactive_callback_binding_v1 must be bool, "
                    "'run_stable', or 'dynamic'"
                )
        else:
            raise ValueError(
                "quantbt_reactive_callback_binding_v1 must be bool, "
                "'run_stable', or 'dynamic'"
            )
        if run_stable:
            self._callback_plan = {
                callback: getattr(self.strategy, callback, None)
                for callback in ("initialize", "on_bar_close", "finalize")
            }
            self.callback_binding_mode = "run_stable_pinned_v1"
            self.callback_plan_compile_lookup_count = 3
        self.callback_plan_compile_ns = perf_counter_ns() - started

    def _callback(self, callback: str):
        if self.callback_binding_mode == "run_stable_pinned_v1":
            return (self._callback_plan or {}).get(callback)
        started = perf_counter_ns()
        callback_fn = getattr(self.strategy, callback, None)
        self.callback_lookup_ns += perf_counter_ns() - started
        self.callback_dynamic_lookup_count += 1
        return callback_fn

    def should_callback(self, session, bar: int) -> bool:
        if self._callback_every_bar:
            return True
        self.callback_schedule_check_count += 1
        current_bar = int(bar)
        if self._callback_period is not None and current_bar % self._callback_period == 0:
            return True
        if current_bar in self._callback_explicit_bars:
            return True
        if not (self._callback_on_fill or self._callback_on_order_event or self._callback_on_liquidation):
            self.callback_suppressed_without_lookup_count += 1
            return False
        if self._callback_on_fill and bool(session.fills_by_bar.get(current_bar)):
            return True
        if self._callback_on_order_event and bool(session.events_by_bar.get(current_bar)):
            return True
        if self._callback_on_liquidation and bool(session.liquidated):
            return True
        self.callback_suppressed_without_lookup_count += 1
        return False

    def call(
        self,
        session,
        callback: str,
        bar: int,
        *,
        context=None,
        callback_allowed: bool | None = None,
    ):
        """Invoke one strategy callback using an optional retained context.

        Compatibility strategies historically receive the same last-bar
        context in ``finalize`` rather than forcing another session projection.
        Keeping that behavior avoids a duplicate timestamp/context allocation
        and, more importantly, preserves the public lifecycle contract.
        Numeric strategies always receive a fresh guarded array view.
        """

        if callback == "on_bar_close":
            allowed = self.should_callback(session, bar) if callback_allowed is None else bool(callback_allowed)
            if not allowed:
                self.skipped_callback_count += 1
                return ()
        fn = self._callback(callback)
        if fn is None:
            return ()
        self.callback_count += 1
        if self.requirements.context_mode == "numeric":
            session.generation += 1
            view = StrategyContextView(session, bar, self.requirements, session.generation)
            self.writer.reset()
            try:
                started = perf_counter_ns()
                result = fn(view, self.writer)
                self.callback_ns += perf_counter_ns() - started
                if result is not None:
                    raise TypeError("numeric strategy callbacks must write to CommandWriter and return None")
                batch = self.writer.finish()
                self.writer_command_rows += len(batch)
                self.context_projection_bytes += sum(
                    int(getattr(view, f"{name}_values").nbytes) for name in self.requirements.market
                )
                return batch
            except Exception as exc:
                if hasattr(session, "poisoned"):
                    session.poisoned = True
                if isinstance(exc, NativeEventStrategyError):
                    raise
                raise NativeEventStrategyError(
                    callback,
                    bar,
                    session.idx[int(bar)],
                    exc,
                    strategy_id=self.strategy_id,
                ) from exc
            finally:
                view.invalidate()
        callback_context = context if context is not None else session.context(bar)
        try:
            started = perf_counter_ns()
            result = fn(callback_context)
            self.callback_ns += perf_counter_ns() - started
        except Exception as exc:
            if hasattr(session, "poisoned"):
                session.poisoned = True
            raise NativeEventStrategyError(
                callback,
                bar,
                callback_context.timestamp,
                exc,
                strategy_id=self.strategy_id,
            ) from exc
        if result is None:
            return ()
        commands = tuple(result)
        self.legacy_command_objects += len(commands)
        return commands

    @property
    def diagnostics(self) -> dict[str, object]:
        return {
            "strategy_id": self.strategy_id,
            "context_mode": self.requirements.context_mode,
            "projection_mask": int(self.requirements.projection_mask),
            "callback_schedule": {
                "every_n_bars": self.requirements.callback.every_n_bars,
                "explicit_bars": self.requirements.callback.explicit_bars,
                "on_fill": self.requirements.callback.on_fill,
                "on_order_event": self.requirements.callback.on_order_event,
                "on_liquidation": self.requirements.callback.on_liquidation,
            },
            "python_callbacks": int(self.callback_count),
            "skipped_callbacks": int(self.skipped_callback_count),
            "legacy_command_objects": int(self.legacy_command_objects),
            "writer_command_rows": int(self.writer_command_rows),
            "writer_materialized_command_objects": int(self.writer_materialized_command_objects),
            "command_buffer_grows": int(self.writer.growth_count),
            "command_buffer_high_water": int(self.writer.high_water_mark),
            "callback_projection_bytes": int(self.context_projection_bytes),
            "callback_ns": int(self.callback_ns),
            "callback_binding_mode": self.callback_binding_mode,
            "callback_plan_compile_ns": int(self.callback_plan_compile_ns),
            "callback_plan_compile_lookup_count": int(self.callback_plan_compile_lookup_count),
            "callback_lookup_ns": int(self.callback_lookup_ns),
            "callback_dynamic_lookup_count": int(self.callback_dynamic_lookup_count),
            "callback_schedule_check_count": int(self.callback_schedule_check_count),
            "callback_suppressed_without_lookup_count": int(
                self.callback_suppressed_without_lookup_count
            ),
        }

    def materialize_batch(self, batch: CommandBatchView, *, session, bar: int):
        """Materialize only for compatibility engines or requested reports."""

        commands = batch.to_order_commands(timestamp=session.idx[int(bar)], symbols=session.symbols)
        self.writer_materialized_command_objects += len(commands)
        return commands


__all__ = ["PreparedStrategyAdapter"]
