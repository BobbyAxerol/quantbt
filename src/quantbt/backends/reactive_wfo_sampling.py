"""W3 sampler policy and versioned R3B ask/tell; no financial state ownership."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Mapping

import numpy as np

from ..core.wfo_contracts import strategy_fingerprint
from ..optimization.space import stable_params_key
from ..walkforward import (
    WalkForwardTrialRecord, _build_inner_folds, _derive_fold_seed, _with_selection_metadata,
)

BATCH_CONTRACT = "shared_sampler_batch_r3b_v2"


def prepare_sampler_studies(runtime, engine, folds, *, params, param_ranges, candidate_matrix):
    config = runtime.config
    explicit = (config.sampler_config is not None or bool(config.sampler_warm_start)
                or config.parameter_constraints is not None or config.result_constraints is not None)
    if candidate_matrix is not None and not explicit:
        return
    requested = explicit or any(isinstance(spec, Mapping) for spec in (param_ranges or {}).values())
    if not requested:
        return
    if candidate_matrix is not None:
        raise ValueError("SAMPLER_ROUTE_UNSUPPORTED: fixed candidate_matrix has no sampler; "
                         "remove sampler/warm-start/constraints and use legacy selector ranges")
    if params is not None or not param_ranges or int(config.optuna_trials) <= 0:
        raise ValueError("SAMPLER_ROUTE_UNSUPPORTED: W3 sampler policy requires an optimizing param_ranges study")
    if runtime.runtime_config.optimizer_schedule == "throughput_batch_v1":
        runtime._require_r3b_global_schedule()
    groups = [(0, folds)] if config.optimization_schedule == "global" else [
        (fold.fold_id, _build_inner_folds(fold, config) if config.optimization_mode == "mode_1_decay"
         and config.optimization_schedule == "per_fold_causal" else [fold]) for fold in folds]
    from ..optimization.wfo_study import prepare_wfo_studies

    engine._sampler_bridges = prepare_wfo_studies(config, param_ranges, groups,
        strategy_identity=strategy_fingerprint(runtime.strategy_factory), derive_seed=_derive_fold_seed)
    engine._sampler_studies = []


@dataclass(frozen=True, slots=True)
class BatchProposal:
    trial: Any
    params: dict
    requested: dict
    rejection: str | None


class ReactiveBatchStudy:
    """Own just Optuna state; existing R3B scheduler owns execution and reset."""

    def __init__(self, bridge, config, *, batch_size):
        import optuna

        self.bridge, self.config = bridge, config
        self.batch_size = int(batch_size)
        self.study = optuna.create_study(direction="maximize", sampler=bridge.observed,
                                        pruner=optuna.pruners.NopPruner())
        bridge.enqueue(self.study, config.sampler_warm_start)
        self.seen = set()
        self.batches = []

    def ask(self, count):
        trials = [self.study.ask() for _ in range(count)]
        self.batches.append([trial.number for trial in trials])
        proposals = []
        for trial in trials:
            requested, params = self.bridge.suggest(trial)
            key = stable_params_key(params)
            reason = "DUPLICATE_EFFECTIVE_PARAMS" if key in self.seen else None
            self.seen.add(key)
            if reason is None and self.config.parameter_constraints is not None:
                if not self.bridge.constraints(trial, self.config.parameter_constraints(dict(params))):
                    reason = "PARAMETER_CONSTRAINT"
            proposals.append(BatchProposal(trial, params, requested, reason))
        return proposals

    def finish(self, proposal, record, batch_id):
        import optuna

        trial, reason = proposal.trial, proposal.rejection
        feasible = True
        if record is None:
            record = WalkForwardTrialRecord(trial_id=trial.number, params=proposal.params,
                objective=-np.inf, mean_is_sharpe=0., mean_oos_sharpe=0., mean_decay=0.,
                std_decay=0., fold_metrics=[], pruned=True)
        if reason is None and (record.pruned or not np.isfinite(record.objective)):
            reason = "NATIVE_CANDIDATE_ERROR" if record.pruned else "NONFINITE_OBJECTIVE"
        if reason is not None:
            state = optuna.trial.TrialState.PRUNED
            record = replace(record, pruned=True)
            trial.set_user_attr("qms_rejection_reason", reason)
            self.study.tell(trial, state=state)
        else:
            state = optuna.trial.TrialState.COMPLETE
            if self.config.result_constraints is not None:
                feasible = self.bridge.constraints(trial, self.config.result_constraints(record))
                if not feasible:
                    trial.set_user_attr("qms_rejection_reason", "RESULT_CONSTRAINT")
            self.study.tell(trial, float(record.objective))
        return _with_selection_metadata(record, {**record.selection_metadata,
            "sampling_contract": BATCH_CONTRACT, "optimizer_schedule": "throughput_batch_v1",
            "batch_id": batch_id, "candidate_sequence_equivalent_to_sequential": False,
            "requested_params": proposal.requested, "effective_params": dict(proposal.params),
            "candidate_id": trial.user_attrs["qms_candidate_id"], "source": trial.user_attrs["qms_source"],
            "feasible": feasible and reason is None, "optuna_state": state.name,
            **({"reason": reason} if reason else {})})

    def abort_pending(self):
        import optuna

        for trial in self.study.get_trials(deepcopy=False, states=(optuna.trial.TrialState.RUNNING,)):
            self.study.tell(trial.number, state=optuna.trial.TrialState.FAIL)

    def metadata(self):
        return {**self.bridge.metadata(self.study), "study_id": 0,
            "sampling_contract": BATCH_CONTRACT, "optimizer_schedule": "throughput_batch_v1",
            "optimization_mode": self.config.optimization_mode, "optimization_schedule": "global",
            "ask_tell_order": "ask_all_suggest_all_score_unique_tell_trial_order_v2",
            "batch_size": self.batch_size, "batches": self.batches,
            "sequential_equivalent": False}


def select_shared_sampler_batches(runtime, *, engine, folds, param_ranges, bridge):
    from time import perf_counter
    from .reactive_wfo_support import ReactiveWalkForwardUnsupported

    owner = ReactiveBatchStudy(bridge, runtime.config, batch_size=runtime.runtime_config.candidate_batch_size)
    scheduler = runtime._new_candidate_scheduler()
    runtime._active_candidate_scheduler = scheduler
    records, remaining, batch_id = [], int(runtime.config.optuna_trials), 0
    best, no_improvement, stop = -np.inf, 0, False
    try:
        while remaining > 0 and not stop:
            runtime._check_canceled()
            count = min(owner.batch_size, remaining)
            proposals = owner.ask(count)
            pending = [p for p in proposals if p.rejection is None]
            if pending:
                runtime._score_r3b_stage(engine=engine, scheduler=scheduler, folds=folds,
                    candidates=[p.params for p in pending], stage_kind="is_search")
            for proposal in proposals:
                record = None
                if proposal.rejection is None:
                    record = engine.evaluate_params_is(runtime.data, folds, proposal.params,
                                                       trial_id=proposal.trial.number)
                    record = engine.mark_precomputed_failure(record, params=proposal.params)
                record = owner.finish(proposal, record, batch_id)
                records.append(record)
                if proposal.rejection is None:
                    if record.selection_metadata["feasible"] and record.objective > best:
                        best, no_improvement = record.objective, 0
                    else:
                        no_improvement += 1
                    patience = runtime.config.optuna_early_stopping
                    if patience is not None and no_improvement >= int(patience):
                        stop = True
            remaining -= count
            batch_id += 1
        selected, trials, candidates = runtime._select_r3b_records(engine=engine, scheduler=scheduler,
            folds=folds, records=records, param_ranges=param_ranges,
            mode=str(runtime.config.optimization_mode).lower().strip(), sampling_contract=BATCH_CONTRACT)
        reference = runtime.runtime_config.reference_best_objective
        regret = None if reference is None else max(0., float(reference) - float(selected.objective))
        if regret is not None and regret > runtime.runtime_config.max_quality_regret:
            raise ReactiveWalkForwardUnsupported("adaptive throughput_batch_v1 exceeded its declared quality regret gate")
    finally:
        owner.abort_pending()
        study = owner.metadata()
        engine._sampler_studies.append(study)
        runtime._candidate_batch_metadata = {**scheduler.telemetry.as_dict(),
            "optimizer_schedule": "throughput_batch_v1", "sampling_contract": BATCH_CONTRACT,
            "sequential_equivalent": False, "candidate_matrix_size": 0,
            "asked_trials": study["attempts"], "batch_count": len(owner.batches),
            "seed": bridge.seed, "batch_size": owner.batch_size, "sampler_study": study,
            "quality_regret_vs_reference": regret if "regret" in locals() else None,
            "quality_reference_status": "not_evaluated_without_explicit_reference" if
                runtime.runtime_config.reference_best_objective is None else "evaluated_against_explicit_reference",
            "quality_max_regret": runtime.runtime_config.max_quality_regret,
            "max_wall_time_ms": runtime.runtime_config.runtime_budget.max_wall_time_ms}
        started = perf_counter()
        try:
            scheduler.close()
        finally:
            runtime._active_candidate_scheduler = None
        runtime._candidate_batch_metadata["cleanup_seconds"] = perf_counter() - started
    runtime._sampling_contract = BATCH_CONTRACT
    return selected, trials, candidates, {}, [], []
