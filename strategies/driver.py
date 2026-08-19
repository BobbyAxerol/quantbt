"""Prepared Python callback adapter outside execution-engine ownership."""

from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter_ns

from ..core.reactive import NativeEventStrategyError
from .commands import CommandWriter
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
    context_projection_bytes: int = 0
    callback_ns: int = 0

    @classmethod
    def prepare(cls, strategy, *, writer_capacity: int = 8, writer_hard_limit: int = 65_536):
        requirements = resolve_strategy_requirements(strategy)
        strategy_id = getattr(strategy, "strategy_id", strategy.__class__.__qualname__)
        return cls(
            strategy=strategy,
            requirements=requirements,
            writer=CommandWriter(writer_capacity, writer_hard_limit),
            strategy_id=str(strategy_id),
        )

    def should_callback(self, session, bar: int) -> bool:
        schedule = self.requirements.callback
        fills = bool(session.fills_by_bar.get(int(bar)))
        events = bool(session.events_by_bar.get(int(bar)))
        return schedule.should_callback(
            int(bar), has_fill=fills, has_order_event=events, liquidated=bool(session.liquidated)
        )

    def call(self, session, callback: str, bar: int):
        fn = getattr(self.strategy, callback, None)
        if fn is None:
            return ()
        if callback == "on_bar_close" and not self.should_callback(session, bar):
            self.skipped_callback_count += 1
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
                commands = batch.to_order_commands(timestamp=session.idx[int(bar)], symbols=session.symbols)
                self.writer_command_rows += len(commands)
                self.context_projection_bytes += sum(
                    int(getattr(view, f"{name}_values").nbytes) for name in self.requirements.market
                )
                return commands
            except Exception as exc:
                if hasattr(session, "poisoned"):
                    session.poisoned = True
                if isinstance(exc, NativeEventStrategyError):
                    raise
                raise NativeEventStrategyError(callback, bar, session.idx[int(bar)], exc) from exc
            finally:
                view.invalidate()
        context = session.context(bar)
        try:
            started = perf_counter_ns()
            result = fn(context)
            self.callback_ns += perf_counter_ns() - started
        except Exception as exc:
            if hasattr(session, "poisoned"):
                session.poisoned = True
            raise NativeEventStrategyError(callback, bar, context.timestamp, exc) from exc
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
            "command_buffer_grows": int(self.writer.growth_count),
            "command_buffer_high_water": int(self.writer.high_water_mark),
            "callback_projection_bytes": int(self.context_projection_bytes),
            "callback_ns": int(self.callback_ns),
        }


__all__ = ["PreparedStrategyAdapter"]
