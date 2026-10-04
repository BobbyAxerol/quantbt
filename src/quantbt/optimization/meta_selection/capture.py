"""Internal full-pool tap; public active/shadow integration belongs to QMS-05."""

from __future__ import annotations

from dataclasses import dataclass, replace
import math

from .common import MetaRecordError, digest, utc
from .descriptors import DescriptorSchema
from .persistence import observation_from_payload
from .records import CandidateISRecord


@dataclass(frozen=True, slots=True)
class CapturedISPool:
    study_id: int
    fold_id: int
    seed: int
    schema: DescriptorSchema
    candidates: tuple[CandidateISRecord, ...]
    anchor_evaluation_id: str
    selected_params_digest: str
    auxiliary_is_evaluations: int


class ISPoolCapture:
    """Collect compact records while the original evaluator is still owned."""

    def __init__(self, *, resolved_at, max_pools=256):
        if type(max_pools) is not int or max_pools <= 0:
            raise MetaRecordError("capture requires bounded pool capacity")
        self.resolved_at = resolved_at
        self.max_pools = max_pools
        self.pools = []

    def validate(self, config, scorer):
        if (
            config.optimization_mode != "mode_4_is_only_robust"
            or config.optimization_schedule != "per_fold_causal"
            or config.scoring_backend != "endpoint"
            or not getattr(scorer, "meta_metric_support", False)
        ):
            raise MetaRecordError(
                "QMS-03 capture requires Mode 4 causal original-result scorer support"
            )

    def capture(
        self, *, engine, data, folds, param_ranges, selected, records, study_id, seed
    ):
        if len(folds) != 1 or len(self.pools) >= self.max_pools:
            raise MetaRecordError("capture window/capacity invalid")
        fold = folds[0]
        resolved = utc(self.resolved_at(fold))
        if resolved < utc(fold.train_index[-1]):
            raise MetaRecordError("IS completion precedes information cutoff")
        schema = DescriptorSchema(param_ranges)
        eligible = [
            r
            for r in records
            if not r.pruned
            and math.isfinite(r.objective)
            and r.selection_metadata.get("feasible", True)
        ]
        auxiliary = int(
            bool(selected.selection_metadata.get("requires_evaluation", False))
        )
        anchor = None
        if auxiliary:
            anchor = engine.evaluate_params_is(
                data=data,
                folds=folds,
                params=dict(selected.params),
                trial_id=-1,
                execution_seed=seed,
                study_id=study_id,
            )
            eligible.append(anchor)
        else:
            anchor = next(
                (
                    r
                    for r in eligible
                    if r.trial_id == selected.trial_id
                    and digest(r.params) == digest(selected.params)
                ),
                None,
            )
        if anchor is None:
            raise MetaRecordError(
                "native anchor is not an exact authoritative IS evaluation"
            )
        candidates = []
        anchor_id = None
        from ...core.wfo_contracts import strategy_fingerprint

        strategy_id = strategy_fingerprint(engine.strategy)
        for ordinal, record in enumerate(eligible):
            if (
                len(record.fold_metrics) != 1
                or "meta_observation" not in record.fold_metrics[0]
            ):
                raise MetaRecordError(
                    "META_METRIC_SUPPORT_MISSING: full IS observation required"
                )
            observation = observation_from_payload(
                record.fold_metrics[0]["meta_observation"]
            )
            metadata = record.selection_metadata
            effective = schema.space.effective(record.params)
            candidate_id = schema.space.candidate_key(
                effective, strategy_identity=strategy_id
            )
            evaluation_id = digest(
                {
                    "study": study_id,
                    "fold": fold.fold_id,
                    "seed": seed,
                    "origin": fold.train_index[-1].isoformat(),
                    "trial": record.trial_id,
                    "ordinal": ordinal,
                    "candidate": candidate_id,
                    "output": observation.output_ref,
                }
            )
            if record is anchor:
                anchor_id = evaluation_id
            candidates.append(
                CandidateISRecord(
                    evaluation_id,
                    candidate_id,
                    int(record.trial_id),
                    metadata.get("requested_params", record.params),
                    effective,
                    float(record.objective),
                    observation,
                    resolved,
                    {},
                )
            )
        self.pools.append(
            CapturedISPool(
                study_id,
                fold.fold_id,
                seed,
                schema,
                tuple(candidates),
                anchor_id,
                digest(selected.params),
                auxiliary,
            )
        )

    @staticmethod
    def strip_support(record):
        return replace(
            record,
            fold_metrics=[
                {k: v for k, v in row.items() if k != "meta_observation"}
                for row in record.fold_metrics
            ],
        )
