"""Pure inference/proposal; public WFO activation belongs to QMS-05."""

from __future__ import annotations

from dataclasses import dataclass, replace
import math

import numpy as np

from .common import MetaRecordError, digest, freeze, utc
from .descriptors import OriginBalancedStandardizer
from .model import FitOutcome, schema_from_payload
from .numerics import NumericRuntime, solution_diagnostics
from .records import MetaTask, OutcomeStatus


@dataclass(frozen=True, slots=True)
class MetaSelectionDecision:
    task_id: str
    anchor_evaluation_id: str
    proposed_evaluation_id: str
    actual_evaluation_id: str | None
    proposed_params: dict
    raw_best_evaluation_id: str
    model_id: str | None
    training_snapshot_id: str | None
    information_as_of: object
    fit_completed_at: object
    decision_sealed_at: object
    ready_at: object
    clock_mode: str
    mode: str
    status: str
    predictions: tuple
    tie_set: tuple
    ranked_ids: tuple
    guard: dict
    numeric: dict

    def __post_init__(self):
        for name in ("proposed_params", "guard", "numeric"):
            object.__setattr__(self, name, freeze(getattr(self, name)))
        for name in ("predictions", "tie_set", "ranked_ids"):
            object.__setattr__(
                self, name, tuple(freeze(v) for v in getattr(self, name))
            )
        for name in ("information_as_of", "decision_sealed_at", "ready_at"):
            object.__setattr__(self, name, utc(getattr(self, name)))
        if self.fit_completed_at is not None:
            object.__setattr__(self, "fit_completed_at", utc(self.fit_completed_at))
        if self.mode not in {"proposal", "shadow"} or self.clock_mode not in {
            "observed_live",
            "historical_replay",
        }:
            raise MetaRecordError("META_DECISION_MODE_INVALID")
        if not (self.information_as_of <= self.decision_sealed_at <= self.ready_at) or (
            self.fit_completed_at is not None
            and self.fit_completed_at > self.decision_sealed_at
        ):
            raise MetaRecordError("META_DECISION_CLOCK_INVALID")
        if self.actual_evaluation_id != (
            self.anchor_evaluation_id if self.mode == "shadow" else None
        ):
            raise MetaRecordError(
                "QMS-04 does not activate or fabricate an executed winner"
            )
        ids = [p["evaluation_id"] for p in self.predictions]
        if len(ids) != len(set(ids)) or any(
            eid not in ids for eid in self.tie_set + self.ranked_ids
        ):
            raise MetaRecordError("META_DECISION_PREDICTION_IDS_INVALID")

    @property
    def decision_id(self):
        return digest({"schema": "qms-selection-decision-v1", "decision": self})


def select_indices(y, q, distances, candidate_keys, *, epsilon, tie_tolerance):
    """Two-pass winner. Reports sort only when asked; no fuzzy sort comparator."""
    y, q, distances = (np.asarray(a, dtype=float) for a in (y, q, distances))
    if (
        y.ndim != 1
        or not len(y)
        or q.shape != y.shape
        or distances.shape != y.shape
        or len(candidate_keys) != len(y)
        or not all(np.isfinite(a).all() for a in (y, q, distances))
    ):
        raise MetaRecordError("META_PREDICTION_INVALID")
    if (
        not math.isfinite(epsilon)
        or epsilon < 0
        or not math.isfinite(tie_tolerance)
        or tie_tolerance < 0
    ):
        raise MetaRecordError("META_GUARD_INVALID")
    safe = q >= -epsilon
    if not safe.any():
        raise MetaRecordError("META_EMPTY_SAFE_POOL: valid anchor must have Q=0")
    minimum = float(np.min(y[safe]))
    ties = np.flatnonzero(safe & (y <= minimum + tie_tolerance))
    winner = min(ties, key=lambda i: (float(distances[i]), candidate_keys[i]))
    return int(winner), tuple(int(i) for i in ties), safe


class MetaSelector:
    def __init__(self, *, runtime=None):
        self.runtime = runtime or NumericRuntime()

    def propose(
        self,
        task,
        fit: FitOutcome,
        *,
        schema=None,
        mode="proposal",
        full_ranking=False,
        ready_at=None,
    ):
        if not isinstance(task, MetaTask) or not isinstance(fit, FitOutcome):
            raise MetaRecordError("META_CURRENT_TASK_INVALID")
        if mode not in {"proposal", "shadow"}:
            raise MetaRecordError("META_DECISION_MODE_INVALID")
        candidates = tuple(
            sorted(task.candidates, key=lambda c: (c.candidate_id, c.evaluation_id))
        )
        anchor_index = next(
            i
            for i, c in enumerate(candidates)
            if c.evaluation_id == task.anchor_candidate_evaluation_id
        )
        anchor = candidates[anchor_index]
        valid = [
            c
            for c in candidates
            if c.observation.status == OutcomeStatus.VALID
            and c.observation.verification != "unverified"
        ]
        raw_best = (
            min(
                valid,
                key=lambda c: (
                    -c.observation.raw_sharpe,
                    c.candidate_id,
                    c.evaluation_id,
                ),
            )
            if valid
            else anchor
        )
        model = fit.model
        if model is not None:
            if (
                model.family_id != task.family.family_id
                or model.information_as_of > task.data_cutoff
                or model.fit_completed_at > task.decision_sealed_at
            ):
                raise MetaRecordError("META_MODEL_UNAVAILABLE_OR_INCOMPATIBLE")
            schema = schema_from_payload(model.schema)
        if schema is None or schema.schema_id != task.family.descriptor_schema_id:
            raise MetaRecordError("META_CURRENT_SCHEMA_INVALID")
        batch = schema.encode(candidates)
        batch = replace(
            batch,
            valid=batch.valid
            & np.array(
                [c.observation.verification != "unverified" for c in candidates]
            ),
        )
        predictions, ties, ranking, guard, numeric = (), (), (), {}, {}
        reason, winner = fit.reason, anchor
        if (
            not batch.valid[anchor_index]
            or anchor.observation.verification == "unverified"
        ):
            reason = "META_NOT_APPLICABLE_METRIC"
        elif model is not None:
            scaler = OriginBalancedStandardizer(**dict(model.scaler))
            values, unsupported = self.runtime.transform(batch, scaler)
            if (unsupported & batch.valid).any():
                reason = "META_OOD_NATIVE_FALLBACK"
                guard = {
                    "ood_policy": model.settings.ood_policy,
                    "unsupported_ids": tuple(
                        c.evaluation_id
                        for i, c in enumerate(candidates)
                        if unsupported[i] and batch.valid[i]
                    ),
                }
            else:
                selected_rows = np.flatnonzero(batch.valid)
                selected = tuple(candidates[i] for i in selected_rows)
                ai = next(
                    i
                    for i, c in enumerate(selected)
                    if c.evaluation_id == anchor.evaluation_id
                )
                v = np.ascontiguousarray(values[selected_rows] - values[anchor_index])
                delta_is = np.array(
                    [
                        c.observation.raw_sharpe - anchor.observation.raw_sharpe
                        for c in selected
                    ]
                )
                y, q = self.runtime.rank(v, np.asarray(model.coefficients), delta_is)
                y[ai], q[ai] = 0.0, 0.0
                geometry = schema.parameter_geometry(selected)
                distances = np.linalg.norm(geometry - geometry[ai], axis=1)
                keys = tuple((c.candidate_id, c.evaluation_id) for c in selected)
                settings, limits = model.settings, model.numeric_limits
                native_fit = (
                    model.backend["selected_backend_by_block"]["gram_solve"] == "rust"
                )
                near_floor = np.any(
                    np.abs(q + settings.epsilon) <= limits.boundary_band
                )
                safe = q >= -settings.epsilon
                minimum = np.min(y[safe]) if safe.any() else None
                first_min = int(np.argmin(np.where(safe, y, np.inf)))
                near_tie = minimum is not None and any(
                    i != first_min
                    and safe[i]
                    and abs(y[i] - minimum - settings.tie_tolerance)
                    <= limits.boundary_band
                    for i in range(len(y))
                )
                reference_fallback = (
                    native_fit or self.runtime.native is not None
                ) and (near_floor or near_tie)
                decision_verified = native_fit or self.runtime.native is not None
                if decision_verified:
                    # Whole-fit solve in the exact historical basis and whole pool rank.
                    # Until a tighter proven error bound is registered, certify the
                    # full decision, never just top-K or coefficient allclose.
                    g, b = (
                        np.asarray(model.reference_gram),
                        np.asarray(model.reference_b),
                    )
                    beta = np.linalg.solve(g, b)
                    solution_diagnostics(g, b, beta, limits)
                    rv, unsupported = scaler.transform(batch)
                    reference_v = rv[selected_rows] - rv[anchor_index]
                    ry = reference_v @ beta
                    rq = delta_is - ry
                    ry[ai], rq[ai] = 0.0, 0.0
                    if not np.allclose(
                        y, ry, rtol=limits.parity_rtol, atol=limits.parity_atol
                    ) or not np.allclose(
                        q, rq, rtol=limits.parity_rtol, atol=limits.parity_atol
                    ):
                        raise MetaRecordError(
                            "META_NATIVE_PARITY_FAILED: complete prediction pool"
                        )
                    native_winner, native_ties, native_safe = select_indices(
                        y,
                        q,
                        distances,
                        keys,
                        epsilon=settings.epsilon,
                        tie_tolerance=settings.tie_tolerance,
                    )
                    ref_winner, ref_ties, ref_safe = select_indices(
                        ry,
                        rq,
                        distances,
                        keys,
                        epsilon=settings.epsilon,
                        tie_tolerance=settings.tie_tolerance,
                    )
                    reference_fallback |= (
                        native_winner != ref_winner
                        or native_ties != ref_ties
                        or not np.array_equal(native_safe, ref_safe)
                    )
                    if reference_fallback:
                        y, q = ry, rq
                wi, ti, safe = select_indices(
                    y,
                    q,
                    distances,
                    keys,
                    epsilon=settings.epsilon,
                    tie_tolerance=settings.tie_tolerance,
                )
                winner, reason = selected[wi], "META_MODEL_PROPOSAL"
                minimum = float(np.min(y[safe]))
                ties = tuple(sorted(selected[i].evaluation_id for i in ti))
                predictions = tuple(
                    {
                        "evaluation_id": c.evaluation_id,
                        "candidate_id": c.candidate_id,
                        "raw_is": c.observation.raw_sharpe,
                        "yhat": float(y[i]),
                        "qhat": float(q[i]),
                        "distance": float(distances[i]),
                        "eligible": bool(safe[i]),
                        "exclusion": None if safe[i] else "PREDICTED_Q_FLOOR",
                    }
                    for i, c in enumerate(selected)
                )
                predictions += tuple(
                    {
                        "evaluation_id": c.evaluation_id,
                        "candidate_id": c.candidate_id,
                        "raw_is": c.observation.raw_sharpe,
                        "yhat": None,
                        "qhat": None,
                        "distance": None,
                        "eligible": False,
                        "exclusion": c.observation.status.value,
                    }
                    for i, c in enumerate(candidates)
                    if not batch.valid[i]
                )
                if full_ranking:
                    # Fixed absolute buckets anchored at the policy minimum form a
                    # total order. The winning tie set is exactly bucket zero.
                    def rank_key(i):
                        bucket = (
                            max(
                                0,
                                math.ceil(
                                    (float(y[i]) - float(minimum))
                                    / settings.tie_tolerance
                                )
                                - 1,
                            )
                            if settings.tie_tolerance
                            else float(y[i])
                        )
                        return (not bool(safe[i]), bucket, float(distances[i]), keys[i])

                    ranking = tuple(
                        selected[i].evaluation_id
                        for i in sorted(range(len(y)), key=rank_key)
                    )
                guard = {
                    "epsilon": settings.epsilon,
                    "tie_tolerance": settings.tie_tolerance,
                    "selection_policy": settings.selection_policy,
                    "ood_policy": settings.ood_policy,
                    "safe_count": int(safe.sum()),
                    "anchor_exact_zero": True,
                    "excluded_metric_ids": tuple(
                        c.evaluation_id
                        for i, c in enumerate(candidates)
                        if not batch.valid[i]
                    ),
                }
                numeric = {
                    "runtime": self.runtime.metadata,
                    "reference_boundary_fallback": reference_fallback,
                    "complete_reference_decision_verified": decision_verified,
                    "fallback_reason": "WHOLE_REFERENCE_FIT_AND_RANK_BOUNDARY"
                    if reference_fallback
                    else None,
                    "current_forward_inputs": False,
                    "full_ranking_materialized": full_ranking,
                }
        if reason != "META_MODEL_PROPOSAL":
            numeric = {
                "runtime": self.runtime.metadata,
                "current_forward_inputs": False,
                "fit_reason": fit.reason,
            }
        return MetaSelectionDecision(
            task.task_id,
            anchor.evaluation_id,
            winner.evaluation_id,
            anchor.evaluation_id if mode == "shadow" else None,
            dict(winner.effective_params),
            raw_best.evaluation_id,
            model.model_id if model else None,
            model.training_snapshot_id if model else None,
            task.data_cutoff,
            model.fit_completed_at if model else None,
            task.decision_sealed_at,
            utc(ready_at if ready_at is not None else task.decision_sealed_at),
            task.clock_mode,
            mode,
            reason,
            predictions,
            ties,
            ranking,
            guard,
            numeric,
        )
