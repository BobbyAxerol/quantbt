"""Project a declared cluster onto its own evaluated admissible IS support."""

from dataclasses import replace
import math

import numpy as np

from .meta_selection.common import digest, wire, utc
from .meta_selection.descriptors import DescriptorSchema
from .meta_selection.persistence import observation_from_payload
from .meta_selection.records import OutcomeStatus

POLICY = "feasible_support_projection_v1"
VERSION = "qms-feasible-support-projection-v1"


def validate_scope(config, folds):
    if config.flat_selector != POLICY:
        return
    from .meta_selection.domains.scalar_contract import SCALAR_ROUTES, canonical_scalar_route
    scalar = canonical_scalar_route(config.target_mode) in SCALAR_ROUTES
    causal = config.optimization_mode == "mode_4_is_only_robust" and config.optimization_schedule == "per_fold_causal"
    full = scalar and config.optimization_mode == "mode_5_full_robust"
    if (not (causal or full) or len(folds) != 1 or config.scoring_backend != "endpoint"
            or (not scalar and config.target_mode != "native_event_strategy")):
        raise ValueError("SAMPLER_SPACE_UNSUPPORTED: support projection requires one qualified original IS window")
    if full and config.candidate_selection_metric not in {"full_plateau_robust", "full_robust"}:
        raise ValueError("SAMPLER_SPACE_UNSUPPORTED: support projection requires a plateau selector")


def bind_is_record(engine, data, folds, record, execution_seed, study_id=0):
    if engine.config.flat_selector != POLICY:
        return record
    validate_scope(engine.config, folds)
    if len(record.fold_metrics) != 1 or "meta_observation" not in record.fold_metrics[0]:
        raise ValueError("REPRESENTATIVE_WITNESS_MISSING: original current-IS result required")
    from ..core.wfo_contracts import strategy_fingerprint
    from ..walkforward import _config_hash
    from .meta_selection.observer import market_signature
    scorer, index = engine.scorer, folds[0].train_index
    bridge = (getattr(engine, "_sampler_bridges", None) or {}).get(study_id)
    if bridge is None:
        raise ValueError("REPRESENTATIVE_WITNESS_MISSING: exact current normalized study required")
    observation = observation_from_payload(record.fold_metrics[0]["meta_observation"])
    witness = getattr(scorer, "_meta_witness", None)
    signature = (witness.market_signature(data, index) if witness is not None
                 else market_signature(data, index, config=scorer.score_config))
    context = dict(market=signature, calendar=digest(list(index)),
        accounting=scorer._meta_economics_id, metric=scorer._meta_adapter.contract.metric_id,
        objective=_config_hash(engine.config),
        execution_seed=str(bridge.seed if execution_seed is None else execution_seed),
        is_cutoff=utc(index[-1]).isoformat(), strategy=strategy_fingerprint(engine.strategy),
        is_start=utc(index[0]).isoformat(), space=bridge.space.identity)
    _check_observation(observation, context)
    return replace(record, selection_metadata={**record.selection_metadata,
        "representative_context": context,
        "representative_evaluation_id": digest(dict(context=context, trial=record.trial_id,
            params=record.params, output=digest(observation)))})


def _check_observation(observation, context):
    if (observation.verification not in {"original_result", "original_native_score"}
            or observation.input_signature != context["market"]
            or observation.economics_id != context["accounting"]
            or observation.metric_contract_id != context["metric"]
            or observation.window_start != utc(context["is_start"])
            or observation.window_end != utc(context["is_cutoff"])
            or observation.input_frontier > utc(context["is_cutoff"])):
        raise ValueError("REPRESENTATIVE_WITNESS_MISMATCH: own original current-IS binding required")


class EvaluatedSupport:
    def __init__(self, records, ranges):
        self.schema = DescriptorSchema(ranges, include_activity=False)
        self.rows = {}
        self.context = None
        ids = set()
        for record in records:
            context = record.selection_metadata.get("representative_context")
            if not context or (self.context is not None and context != self.context):
                raise ValueError("REPRESENTATIVE_WITNESS_MISMATCH: context differs across support")
            self.context = context
            if context["space"] != self.schema.space.identity:
                raise ValueError("REPRESENTATIVE_WITNESS_MISMATCH: current schema changed")
            if len(record.fold_metrics) != 1 or "meta_observation" not in record.fold_metrics[0]:
                raise ValueError("REPRESENTATIVE_WITNESS_MISSING: no averaged/stale/forward scores")
            observation = observation_from_payload(record.fold_metrics[0]["meta_observation"])
            _check_observation(observation, context)
            evaluation = digest(dict(context=context, trial=record.trial_id, params=record.params, output=digest(observation)))
            if record.selection_metadata.get("representative_evaluation_id") != evaluation:
                raise ValueError("REPRESENTATIVE_WITNESS_MISMATCH: evaluation/candidate identity changed")
            if evaluation in ids:
                raise ValueError("REPRESENTATIVE_WITNESS_MISMATCH: duplicate evaluation ID")
            ids.add(evaluation)
            if type(record.selection_metadata.get("feasible", True)) is not bool:
                raise ValueError("REPRESENTATIVE_WITNESS_MISMATCH: explicit boolean feasibility required")
            effective = self.schema.space.effective(record.params)
            if effective != record.params:
                raise ValueError("REPRESENTATIVE_WITNESS_MISMATCH: noncanonical effective params")
            if (record.pruned or not record.selection_metadata.get("feasible", True)
                    or not math.isfinite(record.objective) or observation.status != OutcomeStatus.VALID):
                continue
            candidate = self.schema.space.candidate_key(effective, strategy_identity=context["strategy"])
            semantic = digest(dict(strategy=context["strategy"], effective=effective))
            self.rows[id(record)] = (record, candidate, evaluation, semantic, observation)
        if not self.rows:
            raise ValueError("no admissible original-IS support")

    def select(self, members, *, details):
        support = {}
        attempts = []
        for record in members:
            row = self.rows.get(id(record))
            if row is None:
                continue
            _, candidate, evaluation, semantic, _ = row
            attempts.append(evaluation)
            if candidate not in support or evaluation < support[candidate][2]:
                support[candidate] = row
        if not support:
            raise ValueError("no admissible original-IS support in selected cluster")
        ordered = sorted(support.values(), key=lambda r: (r[3], r[1], r[2]))
        from types import SimpleNamespace
        matrix = self.schema.parameter_geometry(SimpleNamespace(effective_params=r[0].params) for r in ordered)
        center = np.mean(matrix, axis=0)
        distances = [math.fsum(float(v)*float(v) for v in x-center) for x in matrix]
        minimum = min(distances)
        chosen = next(i for i, d in enumerate(distances) if d <= minimum+1e-12)
        record, candidate, evaluation, _, observation = ordered[chosen]
        return replace(record, selection_metadata={**record.selection_metadata, **details,
            "selector": POLICY, "representative_policy": VERSION, "requires_evaluation": False,
            "selected_trial_id": record.trial_id, "representative_candidate_id": candidate,
            "representative_evaluation_id": evaluation, "representative_observation": wire(observation),
            "representative_space_identity": self.schema.space.identity,
            "representative_center": center.tolist(), "representative_distances_squared": distances,
            "representative_support": [r[1] for r in ordered], "representative_evaluations": sorted(attempts),
            "auxiliary_is_evaluations": 0, "oos_used_for_selection": False})
