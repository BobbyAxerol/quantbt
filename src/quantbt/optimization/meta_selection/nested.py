"""C01 outer-IS witnesses; native inner optimization remains the authority."""

from dataclasses import dataclass, fields, replace
import math
from time import perf_counter

from .capture import CapturedISPool, ISPoolCapture
from .common import MetaRecordError, digest, wire

COHORT = "nested_anchor_outer_IS_real_forward_v1"


def is_nested(config):
    return (config.optimization_mode == "mode_1_decay"
            and config.optimization_schedule == "per_fold_causal")


def family_policy(config):
    return dict(cohort=COHORT,
        inner_policy={k: getattr(config, k) for k in (
            "inner_split_frequency", "inner_window_mode", "inner_train_window",
            "inner_min_folds", "min_train_bars", "min_test_bars")},
        decay_policy={k: getattr(config, k) for k in (
            "decay_lambda", "decay_gamma", "candidate_decay_lambda", "candidate_decay_gamma")},
        measurement="original_full_outer_IS_to_real_outer_forward_v1")


@dataclass(frozen=True, slots=True)
class NestedCapturedPool(CapturedISPool):
    inner_records: tuple
    native_search_completed_at: object
    outer_is_seconds: float


class NestedISPoolCapture(ISPoolCapture):
    def validate(self, config, scorer):
        from .domains.scalar_contract import SCALAR_ROUTES, canonical_scalar_route
        if (not is_nested(config) or canonical_scalar_route(config.target_mode) not in SCALAR_ROUTES
                or config.scoring_backend != "endpoint" or not getattr(scorer, "meta_metric_support", False)):
            raise MetaRecordError("META_ROUTE_UNSUPPORTED: nested scalar original-result support required")

    def bind_outer(self, fold):
        self.outer_fold = fold

    def capture(self, *, engine, data, folds, param_ranges, selected, records,
                study_id, seed, candidate_records):
        from .runtime import isolated_observer_rng
        from ...walkforward import trade_frequency_penalty

        outer = self.outer_fold
        if (outer.fold_id != study_id or len(folds) < engine.config.inner_min_folds
                or any(len(f.train_index.difference(outer.train_index))
                       or len(f.test_index.difference(outer.train_index)) for f in folds)):
            raise MetaRecordError("META_NESTED_WINDOW_MISMATCH: inner work must stay inside outer IS")
        eligible = [r for r in records if not r.pruned and math.isfinite(r.objective)
                    and r.selection_metadata.get("feasible", True)]
        if not any(r.trial_id == selected.trial_id and digest(r.params) == digest(selected.params)
                   for r in eligible):
            eligible.append(selected)
        completed = self.resolved_at(outer)
        started = perf_counter()
        observed = []
        # No auxiliary observation is told to Optuna or substituted for an
        # inner objective. Fresh strategy state and the prepared market are reused.
        with isolated_observer_rng(int(seed) + 104729):
            for record in eligible:
                output = engine._call_strategy_for_indices(data, dict(record.params),
                    outer.train_index, outer.train_index, outer, context="meta full outer-IS witness")
                metric = engine._score_strategy_outputs_with_scope(data,
                    [(output, outer.train_index, outer, record.params, "meta full outer-IS witness")],
                    trial_id=record.trial_id, params=record.params, stage="meta_outer_is_witness",
                    adaptive_optimizer=False, execution_seed=seed, study_id=study_id)[0]
                if "meta_observation" not in metric:
                    raise MetaRecordError("META_METRIC_SUPPORT_MISSING: original full outer-IS observation")
                penalty = trade_frequency_penalty(metric["trade_count"],
                    engine._required_trades(outer.train_index), engine.config.trade_penalty_factor)
                observed.append(replace(record, mean_is_sharpe=metric["sharpe"]-penalty,
                    fold_metrics=[{"meta_observation": metric["meta_observation"]}],
                    selection_metadata={**record.selection_metadata, "requires_evaluation": False}))
            anchor = next(r for r in observed if r.trial_id == selected.trial_id
                          and digest(r.params) == digest(selected.params))
            super().capture(engine=engine, data=data, folds=[outer], param_ranges=param_ranges,
                selected=anchor, records=observed, study_id=study_id, seed=seed)
        pool = self.pools[-1]
        self.pools[-1] = NestedCapturedPool(
            **{f.name: getattr(pool, f.name) for f in fields(CapturedISPool) if f.name != "auxiliary_is_evaluations"},
            auxiliary_is_evaluations=len(observed), inner_records=tuple(eligible)+tuple(candidate_records),
            native_search_completed_at=completed, outer_is_seconds=perf_counter()-started)


def inner_record(pool, chosen, *, validated):
    stage = "oos_candidate_selection" if validated else "is_search"
    return next((r for r in pool.inner_records if r.trial_id == chosen.native_trial_id
                 and digest(r.params) == digest(chosen.effective_params)
                 and r.selection_metadata.get("stage") == stage), None)


def selection_metadata(pool, chosen, native):
    search = inner_record(pool, chosen, validated=False)
    validation = inner_record(pool, chosen, validated=True)
    return dict(cohort=COHORT, native_selection_information_scope="inner_validation_within_outer_IS",
        native_inner_decay_objective=float(native.objective),
        native_inner_is_score=float(native.mean_is_sharpe),
        native_inner_validation_score=float(native.mean_oos_sharpe),
        native_inner_mean_decay=float(native.mean_decay), native_inner_std_decay=float(native.std_decay),
        native_search_completed_at=wire(pool.native_search_completed_at),
        outer_is_completed_at=wire(chosen.resolved_at),
        selected_inner_search_objective=None if search is None else float(search.objective),
        selected_inner_validation_evaluated=validation is not None,
        selected_inner_validation_objective=None if validation is None else float(validation.objective),
        selected_inner_validation_score=None if validation is None else float(validation.mean_oos_sharpe),
        selected_outer_is_raw_sharpe=chosen.observation.raw_sharpe,
        selected_outer_is_activity_count=chosen.observation.activity_count,
        selected_outer_is_observation=wire(chosen.observation),
        auxiliary_outer_is_evaluations=pool.auxiliary_is_evaluations,
        auxiliary_outer_is_seconds=pool.outer_is_seconds,
        native_inner_diagnostics=tuple(dict(trial_id=r.trial_id, params=wire(r.params),
            objective=r.objective, fold_metrics=ISPoolCapture.strip_support(r).fold_metrics)
            for r in pool.inner_records if r.selection_metadata.get("stage") == "oos_candidate_selection"))


def selected_record(native, chosen, pool):
    validation = inner_record(pool, chosen, validated=True)
    search = inner_record(pool, chosen, validated=False)
    source = validation or search
    if source is None:
        raise MetaRecordError("META_NATIVE_LINEAGE_MISSING: selected candidate has no native inner record")
    details = selection_metadata(pool, chosen, native)
    return replace(native, params=dict(chosen.effective_params), trial_id=chosen.native_trial_id,
        objective=source.objective, mean_is_sharpe=source.mean_is_sharpe,
        mean_oos_sharpe=math.nan if validation is None else validation.mean_oos_sharpe,
        mean_decay=math.nan if validation is None else validation.mean_decay,
        std_decay=math.nan if validation is None else validation.std_decay,
        fold_metrics=ISPoolCapture.strip_support(source).fold_metrics,
        selection_metadata={**native.selection_metadata, **source.selection_metadata, **details, "stage": "meta_actual_selection",
            "meta_actual_selection": True, "native_trial_id": native.trial_id,
            "native_objective": native.objective,
            "source_trial_id": source.trial_id,
            "source_is_objective": None if search is None else search.objective,
            "candidate_id": None if validation is None else validation.selection_metadata.get("candidate_id"),
            "requires_evaluation": False,
            "actual_objective_scope": "inner_decay_validation" if validation is not None else "inner_IS_adaptive_search"})
