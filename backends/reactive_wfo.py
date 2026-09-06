"""Public W3 reactive walk-forward runtime lifecycle and orchestration."""

from __future__ import annotations

import hashlib
from time import perf_counter
from typing import Any, Mapping, Optional, Sequence

import pandas as pd

from ..core.runtime_governance import (
    ParallelismPlanV1,
    RuntimeBudgetError,
    RuntimeCanceledError,
    RuntimeCancellationV1,
)
from ..strategies.reactive_wfo import (
    PreparedReactiveWfoStrategyAdapterV1,
    ReactiveWfoTaskV1,
    prepare_reactive_wfo_strategy,
)
from ..walkforward import (
    WalkForwardConfig,
    WalkForwardFold,
    WalkForwardTrialRecord,
    _build_inner_folds,
    _derive_fold_seed,
    _inner_fold_audit_rows,
)
from .reactive_wfo_batch_selection import ReactiveWfoBatchSelectionMixinV1
from .reactive_wfo_support import (
    ReactiveWalkForwardResultV1,
    ReactiveWalkForwardUnsupported,
    ReactiveWfoFoldResultV1,
    ReactiveWfoRuntimeConfigV1,
    ReactiveWfoScoreMarkerV1,
    _ReactiveSelectionEngine,
    _SUPPORTED_MODES,
    _SUPPORTED_SCHEDULES,
    _fold_table_with_segments,
    _records_frame,
    _trial_to_dict,
    run_cold_oos_segments,
)
from .reactive_wfo_workers import (
    ForkReactiveWfoWorkerV1,
    ReactiveScalarSessionPoolV1,
    fork_reactive_wfo_worker_safe,
    fork_reactive_wfo_worker_supported,
)


class ReactivePreparedWfoRuntimeV1(ReactiveWfoBatchSelectionMixinV1):
    """One prepared native market plus isolated reactive strategy builders."""

    def __init__(
        self,
        *,
        endpoint,
        data: pd.DataFrame,
        strategy_factory: object,
        walkforward_config: WalkForwardConfig,
        runtime_config: ReactiveWfoRuntimeConfigV1 | None = None,
        symbols: Sequence[str] | None = None,
    ) -> None:
        if not isinstance(data, pd.DataFrame):
            raise ReactiveWalkForwardUnsupported("public reactive WFO currently requires one canonical OHLCV DataFrame")
        if str(endpoint.config.mode).lower().strip() != "native_event_strategy":
            raise ReactiveWalkForwardUnsupported(
                "prepare_reactive_walk_forward requires QuantBTEndpoint.native_event_strategy(...)"
            )
        if str(endpoint.config.native_backend).lower().strip() != "rust":
            raise ReactiveWalkForwardUnsupported(
                "reactive WFO requires native_backend='rust'; it never silently changes lifecycle semantics"
            )
        mode = str(walkforward_config.optimization_mode).lower().strip()
        if mode == "mode_2_sbb":
            raise ReactiveWalkForwardUnsupported(
                "mode_2_sbb needs a causal return-path contract and is not certified for reactive WFO; "
                "use mode_1_decay, mode_3_flat_minima, mode_4_is_only_robust, or mode_5_full_robust"
            )
        if mode not in _SUPPORTED_MODES:
            raise ReactiveWalkForwardUnsupported(
                "reactive WFO supports mode_1_decay, mode_3_flat_minima, mode_4_is_only_robust, and mode_5_full_robust"
            )
        schedule = str(walkforward_config.optimization_schedule).lower().strip()
        if schedule not in _SUPPORTED_SCHEDULES:
            raise ReactiveWalkForwardUnsupported("unsupported reactive WFO optimization schedule")
        if str(walkforward_config.fold_account_policy).lower().strip() != "reset_flat":
            raise ReactiveWalkForwardUnsupported(
                "reactive WFO is certified only with fold_account_policy='reset_flat'; "
                "continuous carry/replay needs an explicit dynamic order-tape contract"
            )
        self.endpoint = endpoint
        self.data = data.copy(deep=True)
        self.strategy_factory = strategy_factory
        self.config = walkforward_config
        self.runtime_config = runtime_config or ReactiveWfoRuntimeConfigV1()
        self.symbols = tuple(symbols or endpoint.config.symbols or ("asset",))
        if len(self.symbols) != 1:
            raise ReactiveWalkForwardUnsupported("public reactive WFO is single-symbol in this release")
        self._prepared_runner = endpoint.prepare_native_event_strategy(data=self.data, symbols=self.symbols)
        self._adapter: PreparedReactiveWfoStrategyAdapterV1 | None = None
        self._cancel = RuntimeCancellationV1()
        self._closed = False
        self._score_calls = 0
        self._score_bars = 0
        self._score_seconds = 0.0
        self._worker_errors: list[dict[str, object]] = []
        self._process_worker: ForkReactiveWfoWorkerV1 | None = None
        self._last_worker_metadata: dict[str, object] = {}
        self._scalar_sessions: ReactiveScalarSessionPoolV1 | None = None
        self._last_scalar_session_metadata: dict[str, object] = {}
        self._active_candidate_scheduler: object | None = None
        self._candidate_batch_metadata: dict[str, object] = {}
        self._sampling_contract = "optuna_certified_sequential_v1"
        requested_processes = 1
        self._parallelism_plan = self.runtime_config.parallelism_plan or ParallelismPlanV1.resolve(
            python_processes=requested_processes,
            rust_workers=1,
            blas_threads=1,
            openmp_threads=1,
            numba_threads=1,
            max_rust_workers=self.runtime_config.runtime_budget.max_workers,
        )
        if self._parallelism_plan.python_processes != 1 or self._parallelism_plan.rust_workers != 1:
            raise ReactiveWalkForwardUnsupported(
                "reactive WFO v1 certifies one persistent Python process and one Rust worker; "
                "parallel candidate scheduling is not silently enabled"
            )
        self._runtime_id = hashlib.sha256(
            f"reactive-wfo:{self._prepared_runner.metadata['market_signature']}:{id(self)}".encode("utf-8")
        ).hexdigest()

    def cancel(self, reason: str = "requested") -> None:
        """Request cancellation at the next certified native/task boundary."""

        self._cancel.cancel(reason)
        if self._scalar_sessions is not None:
            self._scalar_sessions.cancel_active()
        if self._active_candidate_scheduler is not None:
            self._active_candidate_scheduler.cancel_active()

    def close(self) -> None:
        if self._closed:
            return
        self._shutdown_process_worker()
        self._shutdown_scalar_sessions()
        if self._adapter is not None:
            self._adapter.close()
            self._adapter = None
        self._closed = True

    def make_task(
        self,
        *,
        params: Mapping[str, Any],
        fold: WalkForwardFold,
        evaluation_index: pd.DatetimeIndex,
        stage: str,
    ) -> ReactiveWfoTaskV1:
        if self._adapter is None:
            raise RuntimeError("reactive WFO strategy adapter is not prepared")
        return self._adapter.task(
            params=params,
            fold=fold,
            evaluation_index=evaluation_index,
            stage=stage,
        )

    def score_markers(self, markers: Sequence[ReactiveWfoScoreMarkerV1]) -> list[dict[str, float]]:
        if self._adapter is None:
            raise RuntimeError("reactive WFO strategy adapter is not prepared")
        self._check_canceled()
        budget = self.runtime_config.runtime_budget
        workers = 1
        budget.require_preflight(
            bars=sum(marker.task.bars for marker in markers),
            workers=workers,
            native_memory_bytes=0,
            metric_rows=len(markers),
        )
        started = perf_counter()
        rows: list[dict[str, float]] = []
        for marker in markers:
            self._check_canceled()
            try:
                if self.runtime_config.worker_mode == "process":
                    worker = self._ensure_process_worker()
                    rows.append(worker.score(marker, canceled=lambda: self._cancel.canceled))
                else:
                    scalar_sessions = self._ensure_scalar_sessions()
                    row, _fingerprint = scalar_sessions.score(marker)
                    rows.append(row)
            except (RuntimeCanceledError, RuntimeBudgetError) as exc:
                self._worker_errors.append(
                    {
                        "candidate_id": marker.task.candidate_id,
                        "fold_id": int(marker.task.fold_id),
                        "stage": marker.task.stage,
                        "error_type": type(exc).__name__,
                        "message": str(exc),
                    }
                )
                raise
            except Exception as exc:
                self._worker_errors.append(
                    {
                        "candidate_id": marker.task.candidate_id,
                        "fold_id": int(marker.task.fold_id),
                        "stage": marker.task.stage,
                        "error_type": type(exc).__name__,
                        "message": str(exc),
                    }
                )
                raise RuntimeError(
                    "reactive WFO candidate failed: "
                    f"fold_id={marker.task.fold_id}, stage={marker.task.stage}, "
                    f"candidate_id={marker.task.candidate_id}: {exc}"
                ) from exc
            self._score_calls += 1
            self._score_bars += int(marker.task.bars)
        self._score_seconds += perf_counter() - started
        return rows

    def _ensure_process_worker(self) -> ForkReactiveWfoWorkerV1:
        if self.runtime_config.worker_mode != "process":
            raise AssertionError("process worker requested for an in-process runtime")
        if not fork_reactive_wfo_worker_supported():
            raise ReactiveWalkForwardUnsupported(
                "reactive WFO worker_mode='process' requires Linux/POSIX fork copy-on-write transport; "
                "use worker_mode='inprocess' on this platform"
            )
        if not fork_reactive_wfo_worker_safe():
            raise ReactiveWalkForwardUnsupported(
                "reactive WFO worker_mode='process' requires a single-thread POSIX parent before fork; "
                "use worker_mode='inprocess' or launch a dedicated constrained worker process"
            )
        if self._adapter is None:
            raise RuntimeError("reactive WFO strategy adapter is not prepared")
        if self._process_worker is None:
            self._process_worker = ForkReactiveWfoWorkerV1(
                adapter=self._adapter,
                prepared_runner=self._prepared_runner,
                trading_days=int(self.config.scoring_trading_days),
                parallelism_plan=self._parallelism_plan,
                max_inflight_tasks=int(self.runtime_config.max_inflight_tasks),
                max_wall_time_ms=self.runtime_config.runtime_budget.max_wall_time_ms,
            )
        return self._process_worker

    def _shutdown_process_worker(self) -> None:
        if self._process_worker is None:
            return
        try:
            self._process_worker.close()
        finally:
            self._last_worker_metadata = dict(self._process_worker.metadata())
            self._process_worker = None

    def _ensure_scalar_sessions(self) -> ReactiveScalarSessionPoolV1:
        if self.runtime_config.worker_mode != "inprocess":
            raise AssertionError("in-process scalar sessions requested for a process runtime")
        if self._adapter is None:
            raise RuntimeError("reactive WFO strategy adapter is not prepared")
        if self._scalar_sessions is None:
            self._scalar_sessions = ReactiveScalarSessionPoolV1(
                adapter=self._adapter,
                prepared_runner=self._prepared_runner,
                trading_days=int(self.config.scoring_trading_days),
                max_wall_time_ms=self.runtime_config.runtime_budget.max_wall_time_ms,
            )
        return self._scalar_sessions

    def _shutdown_scalar_sessions(self) -> None:
        if self._scalar_sessions is None:
            return
        try:
            self._scalar_sessions.close()
        finally:
            self._last_scalar_session_metadata = dict(self._scalar_sessions.metadata())
            self._scalar_sessions = None

    def backtest(
        self,
        *,
        params: Optional[Mapping[str, Any]] = None,
        param_ranges: Optional[Mapping[str, Any]] = None,
        candidate_matrix: Optional[Sequence[Mapping[str, Any]]] = None,
    ) -> ReactiveWalkForwardResultV1:
        """Run selection and cold selected-fold OOS segments.

        Every score account and every final OOS account starts flat.  The
        returned object deliberately does not present a compounded synthetic
        account because that would be a different boundary policy.
        """

        if self._closed:
            raise RuntimeError("reactive WFO runtime is closed")
        self._check_canceled()
        engine = _ReactiveSelectionEngine(runtime=self, config=self.config)
        index = self._prepared_runner.idx
        folds = engine.build_folds(index)
        self.runtime_config.runtime_budget.require_preflight(
            bars=len(index),
            workers=1,
            native_memory_bytes=0,
            metric_rows=max(1, len(folds)),
        )
        static_config = {
            "schema": "quantbt-reactive-wfo-static-v1",
            "market_signature": self._prepared_runner.metadata["market_signature"],
            "symbols": self.symbols,
            "walkforward_config": self.config,
            "runtime_config": self.runtime_config,
        }
        self._adapter = prepare_reactive_wfo_strategy(
            strategy_factory=self.strategy_factory,
            data=self.data,
            datetime_index=index,
            folds=folds,
            random_seed=int(self.config.random_seed),
            static_config=static_config,
        )
        reactive_result: ReactiveWalkForwardResultV1 | None = None
        try:
            if self.runtime_config.worker_mode == "process":
                # Create exactly one child per logical WFO run before Optuna
                # begins.  It remains lazy with respect to native session
                # scratch but inherits the immutable market by COW once.
                self._ensure_process_worker()
            if self.runtime_config.optimizer_schedule == "throughput_batch_v1":
                selector = (
                    self._select_fixed_candidate_matrix
                    if candidate_matrix is not None
                    else self._select_adaptive_candidate_batches
                )
                selected, trial_records, candidate_records, params_by_fold, selection_rows, inner_rows = selector(
                    engine=engine,
                    folds=folds,
                    params=params,
                    param_ranges=param_ranges,
                    candidate_matrix=candidate_matrix,
                )
            else:
                if candidate_matrix is not None:
                    raise ValueError(
                        "candidate_matrix requires optimizer_schedule='throughput_batch_v1'; "
                        "certified_sequential_v1 preserves Optuna ask/evaluate/tell"
                    )
                selected, trial_records, candidate_records, params_by_fold, selection_rows, inner_rows = (
                    self._select(engine=engine, folds=folds, params=params, param_ranges=param_ranges)
                )
            final_rows = self._run_cold_oos_segments(
                folds=folds,
                selected=selected,
                params_by_fold=params_by_fold,
            )
            fold_table = _fold_table_with_segments(folds, final_rows)
            reactive_result = ReactiveWalkForwardResultV1(
                folds=tuple(folds),
                params=dict(selected.params),
                params_by_fold={key: dict(value) for key, value in params_by_fold.items()},
                fold_results=tuple(final_rows),
                fold_table=fold_table,
                trial_table=_records_frame(trial_records),
                candidate_table=_records_frame(candidate_records),
                best_trial=_trial_to_dict(selected),
                metadata={
                    "schema": "quantbt-reactive-wfo-result-v1",
                    "engine": "reactive_wfo_w3",
                    "optimization_mode": self.config.optimization_mode,
                    "optimization_schedule": self.config.optimization_schedule,
                    "candidate_selection_metric": self.config.candidate_selection_metric,
                    "fold_account_policy": "reset_flat",
                    "account_execution": "segmented_reset_flat",
                    "continuous_equity_available": False,
                    "oos_output_kind": "dynamic_order_lifecycle",
                    "mode_2_sbb": "unsupported_no_return_path_proxy",
                    "sampling_contract": self._sampling_contract,
                    "prepared_market": self._prepared_runner.metadata,
                    "prepared_strategy": self._adapter.metadata(),
                    "runtime": self.runtime_metadata(),
                    "fold_selection_table": pd.DataFrame(selection_rows),
                    "inner_fold_table": pd.DataFrame(inner_rows),
                    "worker_errors": tuple(self._worker_errors),
                    "candidate_batch": dict(self._candidate_batch_metadata),
                },
            )
            return reactive_result
        finally:
            self._shutdown_process_worker()
            self._shutdown_scalar_sessions()
            if self._adapter is not None:
                self._adapter.close()
                self._adapter = None
            if reactive_result is not None:
                # The result is returned after the ``finally`` block.  Refresh
                # runtime provenance so callers see the actual deterministic
                # post-run ownership state rather than a mid-run snapshot.
                reactive_result.metadata["runtime"] = self.runtime_metadata()

    def runtime_metadata(self) -> dict[str, object]:
        worker_metadata = (
            dict(self._process_worker.metadata())
            if self._process_worker is not None
            else dict(self._last_worker_metadata)
        )
        return {
            "schema": "quantbt-reactive-wfo-runtime-v1",
            "runtime_id": self._runtime_id,
            "worker_mode_requested": self.runtime_config.worker_mode,
            "worker_mode_resolved": self.runtime_config.worker_mode,
            "optimizer_schedule": self.runtime_config.optimizer_schedule,
            "candidate_batch_size": int(self.runtime_config.candidate_batch_size),
            "max_inflight_tasks": int(self.runtime_config.max_inflight_tasks),
            "score_calls": int(self._score_calls),
            "score_bars": int(self._score_bars),
            "score_seconds": float(self._score_seconds),
            "prepared_market_allocations": 1,
            "fold_market_copies_per_score": 0,
            "candidate_market_copies_per_score": 0,
            "parallelism": {
                "python_processes": int(self._parallelism_plan.python_processes),
                "rust_workers": int(self._parallelism_plan.rust_workers),
                "blas_threads": int(self._parallelism_plan.blas_threads),
                "openmp_threads": int(self._parallelism_plan.openmp_threads),
                "numba_threads": int(self._parallelism_plan.numba_threads),
                "constrained_by": tuple(self._parallelism_plan.constrained_by),
            },
            "worker": worker_metadata,
            "scalar_sessions": (
                dict(self._scalar_sessions.metadata())
                if self._scalar_sessions is not None
                else dict(self._last_scalar_session_metadata)
            ),
            "candidate_batch": dict(self._candidate_batch_metadata),
            "runtime_budget": self.runtime_config.runtime_budget.as_native_kwargs(),
            "native_deadline_enforcement": {
                "enabled": self.runtime_config.runtime_budget.max_wall_time_ms is not None,
                "safe_point": "completed_account_bar_v1",
                "interval_bars": 64,
            },
            "canceled": bool(self._cancel.canceled),
            "cancel_reason": self._cancel.reason,
        }


    def _select(self, *, engine: _ReactiveSelectionEngine, folds, params, param_ranges):
        mode = str(self.config.optimization_mode).lower().strip()
        schedule = str(self.config.optimization_schedule).lower().strip()
        if schedule == "global":
            if params is not None:
                chosen = dict(params)
                record = (
                    engine.evaluate_params_is(self.data, folds, chosen, trial_id=0)
                    if mode in {"mode_4_is_only_robust", "mode_5_full_robust"}
                    else engine.evaluate_params(self.data, folds, chosen, trial_id=0)
                )
                return record, [record], [], {}, [], []
            if not param_ranges:
                raise ValueError("reactive WFO optimization requires param_ranges when params is omitted")
            selected, trials, candidates = engine.optimize_params(
                data=self.data,
                folds=folds,
                param_ranges=dict(param_ranges),
            )
            return selected, trials, candidates, {}, [], []
        if params is not None:
            raise ValueError("per-fold reactive WFO requires param_ranges, not one fixed params mapping")
        if not param_ranges:
            raise ValueError("per-fold reactive WFO optimization requires param_ranges")
        selected_records: list[WalkForwardTrialRecord] = []
        trial_records: list[WalkForwardTrialRecord] = []
        candidate_records: list[WalkForwardTrialRecord] = []
        params_by_fold: dict[int, dict[str, Any]] = {}
        selection_rows: list[dict[str, object]] = []
        inner_rows: list[dict[str, object]] = []
        for fold in folds:
            self._check_canceled()
            fold_seed = _derive_fold_seed(int(self.config.random_seed), int(fold.fold_id))
            nested_mode1 = schedule == "per_fold_causal" and mode == "mode_1_decay"
            inner_folds = _build_inner_folds(fold, self.config) if nested_mode1 else []
            selected, fold_trials, fold_candidates = engine.optimize_params(
                data=self.data,
                folds=inner_folds if nested_mode1 else [fold],
                param_ranges=dict(param_ranges),
                random_seed=fold_seed,
                evaluate_oos_candidates=schedule == "per_fold_decay" or nested_mode1,
            )
            # Outer OOS is always a cold realization with the already frozen
            # candidate.  In per_fold_decay it reproduces the same declared
            # measure used for candidate selection; in causal schedules it is
            # observability only and never changes selected params.
            outer = engine.evaluate_params(
                data=self.data,
                folds=[fold],
                params=dict(selected.params),
                trial_id=int(selected.trial_id),
            )
            selected = WalkForwardTrialRecord(
                trial_id=int(selected.trial_id),
                params=dict(selected.params),
                objective=float(selected.objective),
                mean_is_sharpe=float(selected.mean_is_sharpe),
                mean_oos_sharpe=float(outer.mean_oos_sharpe),
                mean_decay=float(outer.mean_decay),
                std_decay=float(outer.std_decay),
                fold_metrics=list(outer.fold_metrics),
                pruned=bool(selected.pruned),
                selection_metadata={
                    **dict(selected.selection_metadata),
                    "optimization_schedule": schedule,
                    "schedule_fold_id": int(fold.fold_id),
                    "study_id": int(fold.fold_id),
                    "fold_seed": int(fold_seed),
                    "outer_oos_used_for_selection": schedule == "per_fold_decay",
                    "outer_oos_realized_after_selection": schedule != "per_fold_decay",
                    "reactive_wfo": True,
                },
            )
            selected_records.append(selected)
            trial_records.extend(fold_trials)
            candidate_records.extend(fold_candidates)
            params_by_fold[int(fold.fold_id)] = dict(selected.params)
            selection_rows.append(
                {
                    "fold_id": int(fold.fold_id),
                    "study_id": int(fold.fold_id),
                    "fold_seed": int(fold_seed),
                    "train_start": fold.train_start,
                    "train_end": fold.train_end,
                    "test_start": fold.test_start,
                    "test_end": fold.test_end,
                    "selected_trial_id": int(selected.trial_id),
                    "selected_params": dict(selected.params),
                    "candidate_is_metric": float(selected.mean_is_sharpe),
                    "candidate_oos_metric": float(outer.mean_oos_sharpe),
                    "candidate_decay": float(outer.mean_decay),
                    "outer_oos_used_for_selection": schedule == "per_fold_decay",
                    "causality_claim": (
                        "fold_local_decay_calibration"
                        if schedule == "per_fold_decay"
                        else (
                            "strict_nested_fold_local_retraining"
                            if nested_mode1
                            else "strict_fold_local_retraining"
                        )
                    ),
                }
            )
            if nested_mode1:
                inner_rows.extend(_inner_fold_audit_rows(outer_fold=fold, inner_folds=inner_folds))
        return (
            selected_records[-1],
            trial_records,
            candidate_records,
            params_by_fold,
            selection_rows,
            inner_rows,
        )

    def _run_cold_oos_segments(self, *, folds, selected, params_by_fold):
        return run_cold_oos_segments(
            self,
            folds=folds,
            selected=selected,
            params_by_fold=params_by_fold,
        )

    def _check_canceled(self) -> None:
        if self._cancel.canceled:
            raise RuntimeCanceledError(f"reactive WFO canceled: {self._cancel.reason or 'requested'}")



__all__ = [
    "ReactivePreparedWfoRuntimeV1",
    "ReactiveWalkForwardResultV1",
    "ReactiveWalkForwardUnsupported",
    "ReactiveWfoFoldResultV1",
    "ReactiveWfoRuntimeConfigV1",
]
