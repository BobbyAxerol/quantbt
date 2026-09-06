"""Public walk-forward adapter for the shared prepared Rust evaluator.

This module deliberately lives below :class:`QuantBTEndpoint` and above the
specialized typed request runtime.  It does not own Optuna, fold construction,
strategy lifecycle, candidate selection, or the stitched final account.  Its
only responsibility is to score a compatible batch of already-generated
single-symbol WFO outputs through one Rust prepared-runtime boundary.

The public compatibility oracle remains the ordinary endpoint scorer.  The
adapter is opt-in and fail-closed when ``native_prepared_wfo='require'`` is
declared; ``'auto'`` records an explicit fallback reason instead of silently
changing a user's execution or accounting contract.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from time import perf_counter
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from ..core.constraints import build_quantity_constraints
from ..core.performance_contracts import ExclusiveWorkProfilerV1, RequiredComputationPlanV1
from ..core.preprocessor import make_funding_mask, prepare_funding
from ..preparation.native_execution import CachePolicy, NativeExecutionPreparationCache
from ..sizing.fast import scale_signal_notional_matrix
from ..sizing.modes import compute_target_units
from .native_prepared_evaluation import (
    NativeEvaluationMetricContractV1,
    NativePreparedEvaluationRuntimeV1,
    NativePreparedWorkloadV1,
)
from .native_vectorized import NativeVectorizedConfig


_POLICIES = frozenset({"off", "auto", "require"})
_SUPPORTED_TARGETS = frozenset(
    {"signal_notional", "single_signal", "notional", "unit", "pct_equity", "%_equity"}
)
_RUST_DIRECT_TIMING = "close_target_v2_same_close"


class NativePreparedPublicWfoUnsupported(NotImplementedError):
    """A public WFO score cannot use the certified prepared-native route."""


@dataclass(frozen=True, slots=True)
class _PreparedPublicWfoState:
    index: pd.DatetimeIndex
    symbol: str
    closes: np.ndarray
    cache: NativeExecutionPreparationCache
    template: Any
    runtime: NativePreparedEvaluationRuntimeV1
    qty_step: np.ndarray
    min_qty: np.ndarray
    min_notional: np.ndarray
    alloc: float


class NativePreparedPublicWfoScorerV1:
    """Batch compatible public WFO endpoint scores through Rust.

    Every candidate/fold/shard remains a fresh account.  The final public WFO
    account is intentionally *not* produced here: ``WalkForwardEngine`` still
    stitches OOS targets, and the endpoint runs that one continuous account
    exactly once after selection.
    """

    def __init__(self, *, config, target_mode: str, wf_config) -> None:
        metadata = dict(getattr(wf_config, "metadata", {}) or {})
        policy = str(metadata.get("native_prepared_wfo", "off")).lower().strip()
        if policy not in _POLICIES:
            valid = ", ".join(sorted(_POLICIES))
            raise ValueError(f"native_prepared_wfo must be one of: {valid}")
        workers = int(metadata.get("native_prepared_wfo_workers", 1))
        if workers <= 0:
            raise ValueError("native_prepared_wfo_workers must be >= 1")
        self.config = config
        self.target_mode = str(target_mode).lower().strip()
        self.wf_config = wf_config
        self.policy = policy
        self.workers = workers
        self._state: _PreparedPublicWfoState | None = None
        self._computation_plan: RequiredComputationPlanV1 | None = None
        self._perf01_profiler: ExclusiveWorkProfilerV1 | None = None
        self._resolved = "off" if policy == "off" else "pending"
        self._reason: str | None = None
        self._stats: dict[str, object] = {
            "phase": "74",
            "requested_policy": policy,
            "resolved_policy": self._resolved,
            "target_mode": self.target_mode,
            "workers": workers,
            "native_batches": 0,
            "native_rows": 0,
            "native_scored_bars": 0,
            "native_boundary_calls": 0,
            "native_score_seconds": 0.0,
            "fallback_batches": 0,
            "fallback_rows": 0,
            "fresh_account_policy": "fresh_account_per_evaluation",
            "final_account_policy": "endpoint_stitched_continuous_account",
            "execution_clock": _RUST_DIRECT_TIMING,
            "required_computation_plan": None,
        }

    @property
    def enabled(self) -> bool:
        return self._state is not None

    def bind_walkforward_context(self, context) -> None:
        """Prepare exactly one full market/template owner for this WFO run."""

        if self.policy == "off":
            return
        try:
            self._state = self._prepare_state(context)
        except NativePreparedPublicWfoUnsupported as exc:
            self._set_unavailable(str(exc))
            if self.policy == "require":
                raise
        except Exception:
            # A declared compatible native route must never be transformed into
            # an unobserved Python fallback when setup itself failed.
            self._resolved = "error"
            self._stats["resolved_policy"] = self._resolved
            raise
        else:
            self._resolved = "native_prepared"
            self._stats["resolved_policy"] = self._resolved
            self._stats["market_signature"] = self._state.template.market.signature
            self._stats["template_signature"] = self._state.template.signature

    def bind_computation_plan(self, plan: RequiredComputationPlanV1) -> None:
        """Attach the run-local plan before any score batch crosses into Rust."""

        if not isinstance(plan, RequiredComputationPlanV1):
            raise TypeError("native prepared WFO requires RequiredComputationPlanV1")
        self._computation_plan = plan
        self._stats["required_computation_plan"] = plan.metadata()

    def bind_performance_profiler(self, profiler: ExclusiveWorkProfilerV1) -> None:
        """Attach an opt-in outer profiler; it never controls scoring behavior."""

        if not isinstance(profiler, ExclusiveWorkProfilerV1):
            raise TypeError("native prepared WFO requires ExclusiveWorkProfilerV1")
        self._perf01_profiler = profiler

    def score_batch(self, tasks: Sequence[Mapping[str, Any]]) -> list[dict[str, float]] | None:
        """Return native scalar metrics or ``None`` for an explicit auto fallback."""

        entries = tuple(tasks)
        if not entries:
            return []
        state = self._state
        if state is None:
            self._record_fallback(len(entries))
            if self.policy == "require":  # defensive: bind normally raises first
                raise NativePreparedPublicWfoUnsupported(self._reason or "prepared WFO runtime is unavailable")
            return None
        plan = self._computation_plan
        if plan is not None:
            try:
                plan.require_native_score_eligibility()
            except ValueError as exc:
                message = str(exc)
                if self.policy == "require":
                    raise NativePreparedPublicWfoUnsupported(message) from exc
                self._set_unavailable(message)
                self._record_fallback(len(entries))
                return None
        try:
            bindings = self._bindings_for_tasks(state, entries)
        except NativePreparedPublicWfoUnsupported as exc:
            if self.policy == "require":
                raise
            self._set_unavailable(str(exc))
            self._record_fallback(len(entries))
            return None

        started = perf_counter()
        result = state.runtime.evaluate_score_columns(bindings)
        elapsed = perf_counter() - started
        self._stats["native_batches"] = int(self._stats["native_batches"]) + 1
        self._stats["native_rows"] = int(self._stats["native_rows"]) + len(entries)
        self._stats["native_scored_bars"] = int(self._stats["native_scored_bars"]) + sum(
            int(binding.evaluation_end) - int(binding.evaluation_start) for binding in bindings
        )
        self._stats["native_boundary_calls"] = int(self._stats["native_boundary_calls"]) + 1
        self._stats["native_score_seconds"] = float(self._stats["native_score_seconds"]) + elapsed
        profiler = self._perf01_profiler
        if profiler is not None and profiler.enabled:
            profiler.add_activity("native_outer_entries", 1)
            profiler.add_activity("command_ingest_batches", 1)

        by_scenario = result.index_by_scenario()
        metrics: list[dict[str, float]] = []
        for scenario_id in range(len(entries)):
            row_index = by_scenario.get(scenario_id)
            if row_index is None:
                raise RuntimeError("prepared native WFO batch omitted a requested scenario row")
            if int(result.status[row_index]) != 0:
                detail = "; ".join(result.errors) if result.errors else "unknown native prepared failure"
                raise RuntimeError(
                    "prepared native WFO scoring failed for "
                    f"fold_id={int(result.fold_id[row_index])}, scenario_id={scenario_id}: {detail}"
                )
            metrics.append(
                {
                    "sharpe": float(result.sharpe[row_index]),
                    # Historical WFO trade-frequency penalties consume the
                    # public report position-trace count, not fill count or
                    # quote turnover. Rust emits it without a Python replay.
                    "turnover": float(result.report_trade_count[row_index]),
                    "trade_count": float(result.report_trade_count[row_index]),
                    "mean_return": float(result.total_return[row_index]),
                    "volatility": 0.0,
                    "max_drawdown_pct": float(result.max_drawdown[row_index]) * 100.0,
                    "profit_factor": float(result.profit_factor[row_index]),
                }
            )
        self._stats["score_adapter"] = str(result.metadata["adapter"])
        self._stats["score_python_row_objects"] = int(result.metadata["python_row_objects"])
        return metrics

    def metadata(self) -> dict[str, object]:
        """Detached provenance suitable for public WFO result metadata."""

        payload = dict(self._stats)
        payload["reason"] = self._reason
        state = self._state
        if state is not None:
            payload["runtime"] = dict(state.runtime.diagnostics())
            payload["cache"] = dict(state.cache.diagnostics)
        return payload

    def close(self) -> None:
        """Release workers/cache after endpoint metadata has been detached."""

        state = self._state
        if state is None:
            return
        self._stats["runtime_before_close"] = dict(state.runtime.diagnostics())
        self._stats["cache_before_clear"] = dict(state.cache.diagnostics)
        state.runtime.close()
        self._stats["cache_clear"] = state.cache.clear(force=True)
        self._state = None

    def _prepare_state(self, context) -> _PreparedPublicWfoState:
        if self.target_mode not in _SUPPORTED_TARGETS:
            raise NativePreparedPublicWfoUnsupported(
                "prepared public WFO currently certifies target_mode="
                "'signal_notional'/'notional'/'unit' only, plus explicit pct_equity transition scoring"
            )
        if self.target_mode in {"pct_equity", "%_equity"} and self.policy != "require":
            raise NativePreparedPublicWfoUnsupported(
                "prepared target_mode='pct_equity' scoring is opt-in: set native_prepared_wfo='require' "
                "with target_runtime='rust'; auto preserves the legacy endpoint route"
            )
        if self.target_mode in {"pct_equity", "%_equity"}:
            legacy_one_way_fee = float(self.config.fee) / 2.0
            if not np.isclose(
                float(self.config.v2_fee_rate),
                legacy_one_way_fee,
                rtol=0.0,
                atol=1.0e-15,
            ):
                raise NativePreparedPublicWfoUnsupported(
                    "prepared target_mode='pct_equity' requires fee_rate to equal legacy fee / 2 "
                    "for exact compatibility"
                )
            configured_slippage = float(self.config.execution.slippage_rate)
            if configured_slippage != 0.0 and not np.isclose(
                configured_slippage,
                float(self.config.slippage),
                rtol=0.0,
                atol=1.0e-15,
            ):
                raise NativePreparedPublicWfoUnsupported(
                    "prepared target_mode='pct_equity' requires ExecutionConfig.slippage_bps "
                    "to equal legacy slippage for exact compatibility"
                )
        if str(getattr(self.config, "target_runtime", "numba")).lower().strip() != "rust":
            raise NativePreparedPublicWfoUnsupported(
                "prepared public WFO requires target_runtime='rust'; it never changes a Numba route"
            )
        if int(getattr(self.wf_config, "scoring_trading_days", 365)) != 365:
            raise NativePreparedPublicWfoUnsupported(
                "prepared public WFO currently certifies scoring_trading_days=365 only"
            )
        symbols = list(getattr(self.config, "symbols", None) or ["DEFAULT"])
        if len(symbols) != 1:
            raise NativePreparedPublicWfoUnsupported(
                "prepared public WFO is single-symbol; portfolio/package WFO retains its dedicated route"
            )
        symbol = str(symbols[0])
        # Reuse the native vectorized config's explicit close-target contract
        # guard, rather than duplicating supported execution policy checks.
        execution = self._pct_equity_execution_config()
        NativeVectorizedConfig(
            account=self.config.account,
            execution=execution,
            fee_rate=self.config.v2_fee_rate,
            use_funding=bool(self.config.use_funding),
            target_runtime="rust",
        )
        index = pd.DatetimeIndex(context.datetime_index)
        if index.tz is None:
            index = index.tz_localize("UTC")
        else:
            index = index.tz_convert("UTC")
        if not index.is_monotonic_increasing or index.has_duplicates:
            raise NativePreparedPublicWfoUnsupported("prepared public WFO requires a unique monotonic UTC clock")
        if not isinstance(context.data, pd.DataFrame):
            raise NativePreparedPublicWfoUnsupported(
                "prepared public WFO currently requires one canonical OHLCV DataFrame"
            )
        frame = context.data.reindex(index)
        closes = self._frame_column(frame, "close", required=True)
        opens = self._frame_column(frame, "open", fallback=closes)
        highs = self._frame_column(frame, "high", fallback=closes)
        lows = self._frame_column(frame, "low", fallback=closes)
        volumes = self._frame_column(frame, "volume", fallback=np.zeros(len(index), dtype=np.float64))
        funding_map = prepare_funding(
            self.config.funding_rate if bool(self.config.use_funding) else 0.0,
            [symbol],
            index,
        )
        funding = np.ascontiguousarray(
            funding_map[symbol].reindex(index).fillna(0.0).to_numpy(dtype=np.float64).reshape(-1, 1)
        )
        cache = NativeExecutionPreparationCache(CachePolicy())
        market = cache.prepare_market(
            timestamps_ns=np.ascontiguousarray(index.asi8, dtype=np.int64),
            opens=opens.reshape(-1, 1),
            highs=highs.reshape(-1, 1),
            lows=lows.reshape(-1, 1),
            closes=closes.reshape(-1, 1),
            volumes=volumes.reshape(-1, 1),
            funding=funding,
            funding_mask=make_funding_mask(index),
            symbols=[symbol],
        )
        contract_sizes = np.asarray([self._symbol_value(self.config.contract_size, symbol, 1.0)], dtype=np.float64)
        leverages = np.asarray([float(self.config.account.leverage)], dtype=np.float64)
        fee_rates = np.asarray([float(self.config.v2_fee_rate)], dtype=np.float64)
        template = cache.prepare_template(
            market,
            contract_sizes=contract_sizes,
            leverages=leverages,
            fee_rates=fee_rates,
            initial_capital=float(self.config.account.initial_capital),
            maintenance_ratio=float(self.config.account.maintenance_ratio),
            slippage_rate=float(execution.slippage_rate),
            use_funding=bool(self.config.use_funding),
            event_contract_code=2,
        )
        constraints = build_quantity_constraints(
            [symbol],
            instruments=self.config.instruments,
            qty_step=self.config.qty_step,
            lot_size=self.config.lot_size,
            slot_size=self.config.slot_size,
            min_qty=self.config.min_qty,
            min_notional=self.config.min_notional,
        )
        runtime = NativePreparedEvaluationRuntimeV1(
            cache,
            workers=self.workers,
            runtime_budget=self.config.runtime_budget,
        )
        return _PreparedPublicWfoState(
            index=index,
            symbol=symbol,
            closes=np.ascontiguousarray(closes.reshape(-1, 1), dtype=np.float64),
            cache=cache,
            template=template,
            runtime=runtime,
            qty_step=np.ascontiguousarray(constraints.qty_step, dtype=np.float64),
            min_qty=np.ascontiguousarray(constraints.min_qty, dtype=np.float64),
            min_notional=np.ascontiguousarray(constraints.min_notional, dtype=np.float64),
            alloc=(
                self._pct_equity_allocation(symbol)
                if self.target_mode in {"pct_equity", "%_equity"}
                else self._symbol_value(self.config.alloc_per_trade, symbol, 100_000.0)
            ),
        )

    def _bindings_for_tasks(
        self,
        state: _PreparedPublicWfoState,
        tasks: Sequence[Mapping[str, Any]],
    ):
        prepared: list[tuple[Any, int, int]] = []
        for scenario_id, task in enumerate(tasks):
            index = self._normalize_task_index(task.get("index"))
            start, end = self._window_bounds(state.index, index)
            output = task.get("output")
            if not isinstance(output, pd.Series):
                raise NativePreparedPublicWfoUnsupported(
                    "prepared public WFO supports a scalar Series output only"
                )
            raw = self._task_output_matrix(output, index)
            if not np.isfinite(raw).all():
                raise NativePreparedPublicWfoUnsupported(
                    "prepared public WFO refuses non-finite strategy output; use the ordinary endpoint route"
                )
            target_kind = "units"
            workload = NativePreparedWorkloadV1.TARGET_UNITS
            equity_fraction = None
            if self.target_mode in {"pct_equity", "%_equity"}:
                # Preserve the legacy processed-signal surface.  The Rust
                # request owns transition sizing/accounting; Python never
                # expands it to per-bar units or rebalances drifting equity.
                if not bool(self.config.use_pyramiding):
                    raw = np.sign(raw)
                targets = np.ascontiguousarray(raw, dtype=np.float64)
                target_kind = "pct_equity_transition"
                workload = NativePreparedWorkloadV1.PCT_EQUITY_TRANSITION
                equity_fraction = np.asarray([state.alloc], dtype=np.float64)
            else:
                targets = self._target_units(raw, state.closes[start:end], index, state.alloc)
            local_template = state.cache.window_template(state.template, start=start, end=end)
            request = state.cache.direct_target_request(
                local_template,
                targets=targets,
                target_kind=target_kind,
                timing=_RUST_DIRECT_TIMING,
                invalid_target_policy="reject_run",
                qty_step=state.qty_step,
                min_qty=state.min_qty,
                min_notional=state.min_notional,
                equity_fraction=equity_fraction,
                output_profile=0,
            )
            fold = task.get("fold")
            fold_id = int(getattr(fold, "fold_id", 0))
            prepared.append((request, fold_id, scenario_id))
        return tuple(
            state.runtime.bind_request(
                request,
                workload=workload,
                candidate_id=scenario_id,
                fold_id=fold_id,
                scenario_id=scenario_id,
                account_policy="fresh_account_per_evaluation",
                metric_contract=NativeEvaluationMetricContractV1(
                    trading_days=int(self.wf_config.scoring_trading_days),
                    scope="fold",
                ),
            )
            for request, fold_id, scenario_id in prepared
        )

    def _target_units(
        self,
        raw: np.ndarray,
        closes: np.ndarray,
        index: pd.DatetimeIndex,
        alloc: float,
    ) -> np.ndarray:
        if self.target_mode in {"signal_notional", "single_signal"}:
            return scale_signal_notional_matrix(
                signals=raw,
                closes=closes,
                allocs=np.asarray([alloc], dtype=np.float64),
                use_pyramiding=bool(self.config.use_pyramiding),
            )
        signal = pd.Series(raw[:, 0], index=index)
        close = pd.Series(closes[:, 0], index=index)
        units = compute_target_units(
            self.target_mode,
            signal,
            close,
            alloc,
            bool(self.config.use_pyramiding),
        )
        return np.ascontiguousarray(units.to_numpy(dtype=np.float64).reshape(-1, 1))

    @staticmethod
    def _task_output_matrix(output: pd.Series, index: pd.DatetimeIndex) -> np.ndarray:
        """Extract one scalar output without needless reindexing/copies."""

        normalized = pd.DatetimeIndex(output.index)
        if normalized.tz is None:
            normalized = normalized.tz_localize("UTC")
        else:
            normalized = normalized.tz_convert("UTC")
        if normalized.equals(index):
            values = output.to_numpy(dtype=np.float64, copy=False)
        else:
            values = output.reindex(index).fillna(0.0).to_numpy(dtype=np.float64)
        return np.ascontiguousarray(values.reshape(-1, 1), dtype=np.float64)

    def _pct_equity_allocation(self, symbol: str) -> float:
        allocation = self._symbol_value(self.config.alloc_per_trade, symbol, 1.0)
        if allocation < 0.0:
            raise NativePreparedPublicWfoUnsupported("pct_equity alloc_per_trade must be >= 0")
        return allocation / 100.0 if allocation > 1.0 else allocation

    def _pct_equity_execution_config(self):
        """Translate legacy pct-equity fractional slippage exactly once."""

        execution = self.config.execution
        if (
            self.target_mode in {"pct_equity", "%_equity"}
            and execution.slippage_rate == 0.0
            and float(self.config.slippage) != 0.0
        ):
            return replace(execution, slippage_bps=float(self.config.slippage) * 10_000.0)
        return execution

    @staticmethod
    def _frame_column(
        frame: pd.DataFrame,
        name: str,
        *,
        required: bool = False,
        fallback: np.ndarray | None = None,
    ) -> np.ndarray:
        lookup = {str(column).lower(): column for column in frame.columns}
        column = lookup.get(name)
        if column is None:
            if fallback is not None:
                return np.ascontiguousarray(fallback, dtype=np.float64)
            if required:
                raise NativePreparedPublicWfoUnsupported(
                    f"prepared public WFO requires market column {name!r}"
                )
            return np.zeros(len(frame), dtype=np.float64)
        values = pd.to_numeric(frame[column], errors="coerce").to_numpy(dtype=np.float64)
        if not np.isfinite(values).all():
            raise NativePreparedPublicWfoUnsupported(
                f"prepared public WFO requires finite {name!r} market values"
            )
        return np.ascontiguousarray(values, dtype=np.float64)

    @staticmethod
    def _symbol_value(value: object, symbol: str, default: float) -> float:
        if isinstance(value, Mapping):
            return float(value.get(symbol, default))
        return float(default if value is None else value)

    @staticmethod
    def _normalize_task_index(index: object) -> pd.DatetimeIndex:
        if index is None:
            raise NativePreparedPublicWfoUnsupported("prepared public WFO score task is missing its index")
        normalized = pd.DatetimeIndex(index)
        if normalized.tz is None:
            normalized = normalized.tz_localize("UTC")
        else:
            normalized = normalized.tz_convert("UTC")
        if len(normalized) < 2:
            raise NativePreparedPublicWfoUnsupported(
                "prepared public WFO requires at least two bars per scored task"
            )
        return normalized

    @staticmethod
    def _window_bounds(full_index: pd.DatetimeIndex, index: pd.DatetimeIndex) -> tuple[int, int]:
        locations = full_index.get_indexer(index)
        if np.any(locations < 0) or (len(locations) > 1 and not np.all(np.diff(locations) == 1)):
            raise NativePreparedPublicWfoUnsupported(
                "prepared public WFO requires each fold/shard score index to be a contiguous market window"
            )
        return int(locations[0]), int(locations[-1]) + 1

    def _set_unavailable(self, reason: str) -> None:
        self._state = None
        self._resolved = "fallback"
        self._reason = str(reason)
        self._stats["resolved_policy"] = self._resolved

    def _record_fallback(self, rows: int) -> None:
        self._stats["fallback_batches"] = int(self._stats["fallback_batches"]) + 1
        self._stats["fallback_rows"] = int(self._stats["fallback_rows"]) + int(rows)


__all__ = [
    "NativePreparedPublicWfoScorerV1",
    "NativePreparedPublicWfoUnsupported",
]
