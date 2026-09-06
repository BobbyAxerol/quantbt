"""R3B candidate-batch selection orchestration for reactive WFO.

The public reactive runtime owns the prepared market, strategy adapter, and
run lifecycle.  This mixin owns only the explicit ``throughput_batch_v1``
schedule: fixed/adaptive candidate construction, native batch scoring, and
selection-ledger assembly.  Keeping this contract separate prevents the
optional high-throughput schedule from expanding the lifecycle facade.
"""

from __future__ import annotations

from time import perf_counter
from typing import Any, Mapping, Optional, Sequence

import numpy as np
import pandas as pd

from ..optimization.space import stable_params_key
from ..walkforward import (
    WalkForwardFold,
    WalkForwardTrialRecord,
    _select_is_candidate_records,
    _select_oos_candidate_record,
    _sample_params,
    _split_index_into_subperiods,
    _with_selection_metadata,
    validate_param_ranges,
)
from .reactive_wfo_batch import ReactiveWfoCandidateBatchSchedulerV1, reactive_wfo_marker_key
from .reactive_wfo_support import (
    ReactiveWalkForwardUnsupported,
    ReactiveWfoScoreMarkerV1,
    _ReactiveSelectionEngine,
    _normalize_fixed_candidate_matrix,
    _resolve_candidate_matrix_ranges,
)


class ReactiveWfoBatchSelectionMixinV1:
    """Implement the opt-in R3B batched selection schedule.

    The host runtime supplies immutable prepared-market ownership, native
    candidate runner construction, cancellation, and score telemetry.  This
    mixin deliberately has no public constructor or standalone lifecycle.
    """

    def _select_fixed_candidate_matrix(
        self,
        *,
        engine: _ReactiveSelectionEngine,
        folds: Sequence[WalkForwardFold],
        params: Optional[Mapping[str, Any]],
        param_ranges: Optional[Mapping[str, Any]],
        candidate_matrix: Optional[Sequence[Mapping[str, Any]]],
    ):
        """Evaluate one declared matrix through the ordinary two-stage WFO math."""

        self._require_r3b_global_schedule()
        if params is not None:
            raise ValueError("throughput_batch_v1 fixed-matrix route requires candidate_matrix, not one params mapping")
        candidates = _normalize_fixed_candidate_matrix(candidate_matrix)
        resolved_ranges, ranges_source = _resolve_candidate_matrix_ranges(candidates, param_ranges)
        validate_param_ranges(resolved_ranges, context="reactive WFO fixed candidate matrix")
        scheduler = self._new_candidate_scheduler()
        self._active_candidate_scheduler = scheduler
        mode = str(self.config.optimization_mode).lower().strip()
        try:
            self._score_r3b_stage(
                engine=engine,
                scheduler=scheduler,
                folds=folds,
                candidates=candidates,
                stage_kind="is_search",
            )
            records = []
            for trial_id, candidate in enumerate(candidates):
                record = engine.evaluate_params_is(self.data, folds, dict(candidate), trial_id=trial_id)
                record = engine.mark_precomputed_failure(record, params=candidate)
                records.append(
                    _with_selection_metadata(
                        record,
                        {
                            **dict(record.selection_metadata),
                            "sampling_contract": "fixed_candidate_matrix_r3b_v1",
                            "optimizer_schedule": "throughput_batch_v1",
                            "fixed_matrix_trial_id": int(trial_id),
                            "candidate_sequence_equivalent_to_sequential": False,
                        },
                    )
                )
            selected, trials, candidate_records = self._select_r3b_records(
                engine=engine,
                scheduler=scheduler,
                folds=folds,
                records=records,
                param_ranges=resolved_ranges,
                mode=mode,
                sampling_contract="fixed_candidate_matrix_r3b_v1",
            )
        finally:
            self._candidate_batch_metadata = {
                **scheduler.telemetry.as_dict(),
                "optimizer_schedule": "throughput_batch_v1",
                "sampling_contract": "fixed_candidate_matrix_r3b_v1",
                "sequential_equivalent": False,
                "candidate_matrix_size": len(candidates),
                "param_ranges_source": ranges_source,
                "max_wall_time_ms": self.runtime_config.runtime_budget.max_wall_time_ms,
            }
            try:
                scheduler.close()
            finally:
                self._active_candidate_scheduler = None
        self._sampling_contract = "fixed_candidate_matrix_r3b_v1"
        return selected, trials, candidate_records, {}, [], []

    def _select_adaptive_candidate_batches(
        self,
        *,
        engine: _ReactiveSelectionEngine,
        folds: Sequence[WalkForwardFold],
        params: Optional[Mapping[str, Any]],
        param_ranges: Optional[Mapping[str, Any]],
        candidate_matrix: Optional[Sequence[Mapping[str, Any]]],
    ):
        """Run explicit ask-B/evaluate-B/tell-B R3B optimization.

        This is intentionally a different sampler contract from sequential
        TPE. Every batch is asked before any result in that batch is told; the
        seed and batch size are recorded so result quality is never compared
        as if both schedules had the same candidate sequence.
        """

        self._require_r3b_global_schedule()
        if params is not None or candidate_matrix is not None:
            raise ValueError("adaptive throughput_batch_v1 requires param_ranges and no fixed params/candidate_matrix")
        if not param_ranges:
            raise ValueError("adaptive throughput_batch_v1 requires param_ranges")
        validate_param_ranges(dict(param_ranges), context="reactive WFO throughput batch")
        if int(self.config.optuna_trials) <= 0:
            raise ValueError("adaptive throughput_batch_v1 requires walkforward_config.optuna_trials > 0")
        try:
            import optuna
        except ImportError as exc:  # pragma: no cover - package dependency guard
            raise ImportError("reactive throughput_batch_v1 requires optuna") from exc

        scheduler = self._new_candidate_scheduler()
        self._active_candidate_scheduler = scheduler
        sampler = optuna.samplers.TPESampler(seed=int(self.config.random_seed))
        study = optuna.create_study(direction="maximize", sampler=sampler, pruner=optuna.pruners.NopPruner())
        records: list[WalkForwardTrialRecord] = []
        seen: set[str] = set()
        remaining = int(self.config.optuna_trials)
        batch_id = 0
        no_improvement = 0
        best_value = -np.inf
        mode = str(self.config.optimization_mode).lower().strip()
        try:
            stop_requested = False
            while remaining > 0 and not stop_requested:
                self._check_canceled()
                count = min(int(self.runtime_config.candidate_batch_size), remaining)
                trials = [study.ask() for _ in range(count)]
                pending: list[tuple[object, dict[str, Any]]] = []
                for trial in trials:
                    candidate = _sample_params(trial, dict(param_ranges))
                    key = stable_params_key(candidate)
                    if key in seen:
                        duplicate = WalkForwardTrialRecord(
                            trial_id=int(trial.number),
                            params=dict(candidate),
                            objective=-np.inf,
                            mean_is_sharpe=0.0,
                            mean_oos_sharpe=0.0,
                            mean_decay=0.0,
                            std_decay=0.0,
                            fold_metrics=[],
                            pruned=True,
                            selection_metadata={
                                "stage": "duplicate_pruned",
                                "sampling_contract": "adaptive_optuna_batch_r3b_v1",
                                "optimizer_schedule": "throughput_batch_v1",
                                "batch_id": int(batch_id),
                            },
                        )
                        records.append(duplicate)
                        study.tell(trial, state=optuna.trial.TrialState.PRUNED)
                        continue
                    seen.add(key)
                    pending.append((trial, candidate))
                if pending:
                    candidates = [candidate for _trial, candidate in pending]
                    self._score_r3b_stage(
                        engine=engine,
                        scheduler=scheduler,
                        folds=folds,
                        candidates=candidates,
                        stage_kind="is_search",
                    )
                    for trial, candidate in pending:
                        record = engine.evaluate_params_is(
                            self.data,
                            folds,
                            dict(candidate),
                            trial_id=int(trial.number),
                        )
                        record = engine.mark_precomputed_failure(record, params=candidate)
                        record = _with_selection_metadata(
                            record,
                            {
                                **dict(record.selection_metadata),
                                "sampling_contract": "adaptive_optuna_batch_r3b_v1",
                                "optimizer_schedule": "throughput_batch_v1",
                                "batch_id": int(batch_id),
                                "candidate_sequence_equivalent_to_sequential": False,
                            },
                        )
                        records.append(record)
                        if record.pruned or not np.isfinite(float(record.objective)):
                            study.tell(trial, state=optuna.trial.TrialState.PRUNED)
                        else:
                            study.tell(trial, float(record.objective))
                        if float(record.objective) > best_value:
                            best_value = float(record.objective)
                            no_improvement = 0
                        else:
                            no_improvement += 1
                        patience = self.config.optuna_early_stopping
                        if patience is not None and no_improvement >= int(patience):
                            # Finish this already-asked batch so no Optuna
                            # trial is left RUNNING; stop before the next ask.
                            stop_requested = True
                remaining -= count
                batch_id += 1
            selected, trials, candidate_records = self._select_r3b_records(
                engine=engine,
                scheduler=scheduler,
                folds=folds,
                records=records,
                param_ranges=dict(param_ranges),
                mode=mode,
                sampling_contract="adaptive_optuna_batch_r3b_v1",
            )
            reference = self.runtime_config.reference_best_objective
            regret = None if reference is None else max(0.0, float(reference) - float(selected.objective))
            if regret is not None and regret > float(self.runtime_config.max_quality_regret):
                raise ReactiveWalkForwardUnsupported(
                    "adaptive throughput_batch_v1 exceeded its declared quality regret gate: "
                    f"observed={regret:.12g}, allowed={float(self.runtime_config.max_quality_regret):.12g}"
                )
        finally:
            self._candidate_batch_metadata = {
                **scheduler.telemetry.as_dict(),
                "optimizer_schedule": "throughput_batch_v1",
                "sampling_contract": "adaptive_optuna_batch_r3b_v1",
                "sequential_equivalent": False,
                "candidate_matrix_size": 0,
                "asked_trials": int(sum(1 for _record in records)),
                "batch_count": int(batch_id),
                "seed": int(self.config.random_seed),
                "batch_size": int(self.runtime_config.candidate_batch_size),
                "quality_reference_status": (
                    "not_evaluated_without_explicit_reference"
                    if self.runtime_config.reference_best_objective is None
                    else "evaluated_against_explicit_reference"
                ),
                "quality_regret_vs_reference": regret if "regret" in locals() else None,
                "quality_max_regret": self.runtime_config.max_quality_regret,
                "max_wall_time_ms": self.runtime_config.runtime_budget.max_wall_time_ms,
            }
            try:
                scheduler.close()
            finally:
                self._active_candidate_scheduler = None
        self._sampling_contract = "adaptive_optuna_batch_r3b_v1"
        return selected, trials, candidate_records, {}, [], []

    def _require_r3b_global_schedule(self) -> None:
        if self.runtime_config.worker_mode != "inprocess":
            raise ReactiveWalkForwardUnsupported(
                "throughput_batch_v1 owns one in-process R3B callback boundary; "
                "worker_mode='process' is certified for sequential scalar scoring only"
            )
        if str(self.config.optimization_schedule).lower().strip() != "global":
            raise ReactiveWalkForwardUnsupported(
                "throughput_batch_v1 currently certifies the global WFO selection schedule only; "
                "per-fold studies preserve sequential ask/evaluate/tell"
            )

    def _new_candidate_scheduler(self) -> ReactiveWfoCandidateBatchSchedulerV1:
        if self._adapter is None:
            raise RuntimeError("reactive WFO strategy adapter is not prepared")
        return ReactiveWfoCandidateBatchSchedulerV1(
            adapter=self._adapter,
            prepared_runner=self._prepared_runner,
            trading_days=int(self.config.scoring_trading_days),
            batch_size=int(self.runtime_config.candidate_batch_size),
            max_wall_time_ms=self.runtime_config.runtime_budget.max_wall_time_ms,
        )

    def _score_r3b_stage(
        self,
        *,
        engine: _ReactiveSelectionEngine,
        scheduler: ReactiveWfoCandidateBatchSchedulerV1,
        folds: Sequence[WalkForwardFold],
        candidates: Sequence[Mapping[str, Any]],
        stage_kind: str,
    ) -> None:
        markers = self._candidate_markers(
            engine=engine,
            folds=folds,
            candidates=candidates,
            stage_kind=stage_kind,
        )
        if not markers:
            return
        started = perf_counter()
        rows = scheduler.score_markers(markers)
        engine.merge_precomputed_score_rows(rows)
        engine.merge_precomputed_failures(scheduler.failures)
        self._score_calls += len(markers)
        self._score_bars += sum(int(marker.task.bars) for marker in markers)
        self._score_seconds += perf_counter() - started

    def _candidate_markers(
        self,
        *,
        engine: _ReactiveSelectionEngine,
        folds: Sequence[WalkForwardFold],
        candidates: Sequence[Mapping[str, Any]],
        stage_kind: str,
    ) -> list[ReactiveWfoScoreMarkerV1]:
        """Materialize exactly one WFO selection stage over absolute windows."""

        mode = str(self.config.optimization_mode).lower().strip()
        markers: list[ReactiveWfoScoreMarkerV1] = []
        seen: set[tuple[str, int, str, int, int]] = set()

        def add(*, candidate, fold, evaluation_index, stage: str) -> None:
            marker = engine._call_strategy_for_indices(
                data=self.data,
                params=dict(candidate),
                train_index=fold.train_index,
                test_index=pd.DatetimeIndex(evaluation_index),
                fold=fold,
                context=stage,
            )
            key = reactive_wfo_marker_key(marker)
            if key in seen:
                raise ReactiveWalkForwardUnsupported(
                    "reactive WFO fixed candidate matrix generated a duplicate candidate/fold/window binding"
                )
            seen.add(key)
            markers.append(marker)

        if stage_kind not in {"is_search", "oos_selection"}:
            raise ValueError("reactive R3B marker stage_kind must be is_search or oos_selection")
        if stage_kind == "oos_selection" and mode in {"mode_4_is_only_robust", "mode_5_full_robust"}:
            return markers
        for candidate in candidates:
            for fold in folds:
                if stage_kind == "is_search":
                    add(
                        candidate=candidate,
                        fold=fold,
                        evaluation_index=fold.train_index,
                        stage="anti-leakage in-sample search",
                    )
                    if mode in {"mode_4_is_only_robust", "mode_5_full_robust"}:
                        for shard_id, shard_index in enumerate(
                            _split_index_into_subperiods(fold.train_index, int(self.config.is_subperiods))
                        ):
                            if len(shard_index) >= 2:
                                add(
                                    candidate=candidate,
                                    fold=fold,
                                    evaluation_index=shard_index,
                                    stage=f"is-only robustness subperiod {shard_id}",
                                )
                else:
                    add(
                        candidate=candidate,
                        fold=fold,
                        evaluation_index=fold.train_index,
                        stage="in-sample scoring",
                    )
                    add(
                        candidate=candidate,
                        fold=fold,
                        evaluation_index=fold.test_index,
                        stage="out-of-sample scoring",
                    )
        return markers

    def _select_r3b_records(
        self,
        *,
        engine: _ReactiveSelectionEngine,
        scheduler: ReactiveWfoCandidateBatchSchedulerV1,
        folds: Sequence[WalkForwardFold],
        records: Sequence[WalkForwardTrialRecord],
        param_ranges: Mapping[str, Any],
        mode: str,
        sampling_contract: str,
    ) -> tuple[WalkForwardTrialRecord, list[WalkForwardTrialRecord], list[WalkForwardTrialRecord]]:
        """Reuse selectors after native IS rows, then score only eligible OOS rows."""

        is_candidates = _select_is_candidate_records(records, dict(param_ranges), self.config)
        if mode == "mode_5_full_robust":
            selected = _with_selection_metadata(
                is_candidates[0],
                {
                    **dict(is_candidates[0].selection_metadata),
                    "stage": "full_sample_candidate_selection",
                    "candidate_selection_complete": True,
                    "oos_seen_by_optuna": False,
                    "oos_used_for_selection": False,
                    "full_sample_used_for_selection": True,
                    "validation_claim": "none_full_sample_calibration",
                    "sampling_contract": sampling_contract,
                },
            )
            all_records = [*records, *is_candidates]
            return (
                selected,
                engine._compact_trial_records(all_records),
                engine._compact_trial_records(is_candidates),
            )
        if mode == "mode_4_is_only_robust":
            selected = _with_selection_metadata(
                is_candidates[0],
                {
                    **dict(is_candidates[0].selection_metadata),
                    "stage": "is_only_candidate_selection",
                    "candidate_selection_complete": True,
                    "oos_seen_by_optuna": False,
                    "oos_used_for_selection": False,
                    "sampling_contract": sampling_contract,
                },
            )
            return (
                selected,
                engine._compact_trial_records(records),
                engine._compact_trial_records(is_candidates),
            )

        unique_candidates: list[WalkForwardTrialRecord] = []
        seen: set[str] = set()
        for candidate in is_candidates:
            key = stable_params_key(candidate.params)
            if key not in seen:
                seen.add(key)
                unique_candidates.append(candidate)
        self._score_r3b_stage(
            engine=engine,
            scheduler=scheduler,
            folds=folds,
            candidates=[candidate.params for candidate in unique_candidates],
            stage_kind="oos_selection",
        )
        candidate_records: list[WalkForwardTrialRecord] = []
        for candidate_id, candidate in enumerate(unique_candidates):
            evaluated = engine.evaluate_params(
                self.data,
                folds,
                dict(candidate.params),
                trial_id=int(candidate.trial_id),
            )
            evaluated = engine.mark_precomputed_failure(evaluated, params=candidate.params)
            candidate_records.append(
                _with_selection_metadata(
                    evaluated,
                    {
                        **dict(candidate.selection_metadata),
                        "stage": "oos_candidate_selection",
                        "candidate_id": int(candidate_id),
                        "source_trial_id": int(candidate.trial_id),
                        "source_is_objective": float(candidate.objective),
                        "oos_seen_by_optuna": False,
                        "sampling_contract": sampling_contract,
                        "optimizer_schedule": "throughput_batch_v1",
                    },
                )
            )
        selectable_candidates = [record for record in candidate_records if not record.pruned]
        if not selectable_candidates:
            raise ValueError("reactive R3B WFO produced no OOS candidates")
        selected = _select_oos_candidate_record(selectable_candidates, self.config)
        return (
            selected,
            engine._compact_trial_records([*records, *candidate_records]),
            engine._compact_trial_records(candidate_records),
        )


__all__ = ["ReactiveWfoBatchSelectionMixinV1"]
