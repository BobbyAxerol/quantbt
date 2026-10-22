"""Cold binding of saved predictions to trusted task geometry and label clocks.

No model, learned preprocessing, outcome values, IO or accounting is used.
Fallback validation checks representation and the anchor winner, not whether
the original fit/support/OOD diagnosis was itself warranted.
"""

from collections.abc import Mapping, Sequence
import math
from numbers import Real

import numpy as np

from quantbt.optimization.meta_selection.common import MetaRecordError, utc
from quantbt.optimization.meta_selection.descriptors import DescriptorSchema
from quantbt.optimization.meta_selection.history import SealedTaskRevision


MODEL_PROPOSAL = "META_MODEL_PROPOSAL"
FALLBACKS = frozenset(
    {
        "META_SUPPORT_INSUFFICIENT",
        "META_NOT_APPLICABLE_METRIC",
        "META_OOD_NATIVE_FALLBACK",
    }
)
FIELDS = frozenset(
    {
        "evaluation_id",
        "candidate_id",
        "raw_is",
        "yhat",
        "qhat",
        "distance",
        "eligible",
        "exclusion",
    }
)
RTOL = ATOL = 1e-12
Q_FLOOR = -0.1
TIE_TOLERANCE = 1e-10


def _reject(reason: str) -> None:
    raise MetaRecordError("MLR03_BOUND_PREDICTIONS_" + reason)


def _finite(value) -> bool:
    return (
        isinstance(value, Real)
        and not isinstance(value, (bool, np.bool_))
        and math.isfinite(value)
    )


def _close(actual, expected) -> bool:
    return (
        _finite(actual)
        and _finite(expected)
        and bool(np.isclose(actual, expected, rtol=RTOL, atol=ATOL))
    )


def validate_bound_predictions(
    row: Mapping,
    predictions: Sequence,
    revision: SealedTaskRevision,
    schema: DescriptorSchema,
) -> dict[str, dict]:
    """Return detached prediction records by EID, or raise MetaRecordError.

    MODEL_PROPOSAL requires every current candidate exactly once. Raw IS is
    copied evidence and must match exactly; geometry and Q use atol=rtol=1e-12.
    Fallback may have an empty or partial roster, but any supplied records must
    be unscored/ineligible with a source-invalid or declared fallback exclusion.
    """
    if (
        not isinstance(row, Mapping)
        or not isinstance(revision, SealedTaskRevision)
        or not isinstance(schema, DescriptorSchema)
        or not isinstance(predictions, (list, tuple))
    ):
        _reject("INPUT_INVALID")
    task = revision.task
    if schema.schema_id != task.family.descriptor_schema_id:
        _reject("SCHEMA_MISMATCH")
    clocks = dict(
        cutoff=task.data_cutoff,
        label_available_at=max(o.label_available_at for o in revision.outcomes),
        revision_available_at=revision.revision_available_at,
    )
    for name, trusted in clocks.items():
        try:
            actual = utc(row[name])
        except (KeyError, TypeError, ValueError, OverflowError) as exc:
            raise MetaRecordError(
                "MLR03_BOUND_PREDICTIONS_CLOCK_INVALID:" + name
            ) from exc
        if actual != trusted:
            _reject("CLOCK_MISMATCH:" + name)
    status = row.get("status")
    if not isinstance(status, str) or (
        status != MODEL_PROPOSAL and status not in FALLBACKS
    ):
        _reject("STATUS_INVALID")
    candidates = {c.evaluation_id: c for c in task.candidates}
    anchor_id = task.anchor_candidate_evaluation_id
    if row.get("anchor") != anchor_id:
        _reject("ANCHOR_BINDING_INVALID")
    winner_id = row.get("winner")
    if not isinstance(winner_id, str) or winner_id not in candidates:
        _reject("UNKNOWN_WINNER")
    if status != MODEL_PROPOSAL and winner_id != anchor_id:
        _reject("FALLBACK_WINNER_INVALID")

    by_id = {}
    for prediction in predictions:
        if not isinstance(prediction, Mapping) or set(prediction) != FIELDS:
            _reject("FIELDS_INVALID")
        eid = prediction["evaluation_id"]
        if not isinstance(eid, str) or eid not in candidates:
            _reject("UNKNOWN_EID")
        if eid in by_id:
            _reject("DUPLICATE_EID")
        candidate = candidates[eid]
        if prediction["candidate_id"] != candidate.candidate_id:
            _reject("CANDIDATE_ID_MISMATCH")
        raw_is = prediction["raw_is"]
        trusted_is = candidate.observation.raw_sharpe
        if (trusted_is is None and raw_is is not None) or (
            trusted_is is not None and (not _finite(raw_is) or raw_is != trusted_is)
        ):
            _reject("RAW_IS_MISMATCH")
        if type(prediction["eligible"]) is not bool:
            _reject("ELIGIBILITY_INVALID")
        by_id[eid] = dict(prediction)
    if status == MODEL_PROPOSAL and set(by_id) != set(candidates):
        _reject("FULL_POOL_ROSTER_INVALID")

    batch = schema.encode(task.candidates)
    source_valid = {
        c.evaluation_id: bool(valid) and c.observation.verification != "unverified"
        for c, valid in zip(task.candidates, batch.valid)
    }
    if status == MODEL_PROPOSAL and not source_valid[anchor_id]:
        _reject("ANCHOR_SOURCE_INVALID")
    if status == MODEL_PROPOSAL:
        valid_candidates = tuple(
            c for c in task.candidates if source_valid[c.evaluation_id]
        )
        geometry = schema.parameter_geometry(valid_candidates)
        ai = next(
            i for i, c in enumerate(valid_candidates) if c.evaluation_id == anchor_id
        )
        distances = {
            c.evaluation_id: float(d)
            for c, d in zip(
                valid_candidates, np.linalg.norm(geometry - geometry[ai], axis=1)
            )
        }
    else:
        distances = {}

    for eid, prediction in by_id.items():
        invalid_source = not source_valid[eid]
        if invalid_source or status != MODEL_PROPOSAL:
            exclusion = (
                candidates[eid].observation.status.value if invalid_source else status
            )
            if (
                any(prediction[k] is not None for k in ("yhat", "qhat", "distance"))
                or prediction["eligible"]
                or prediction["exclusion"] != exclusion
            ):
                _reject("UNSCORED_GUARD_INVALID")
            continue
        if not all(_finite(prediction[k]) for k in ("yhat", "qhat", "distance")):
            _reject("SCORE_NONFINITE_OR_MISSING")
        if prediction["distance"] < 0 or not _close(
            prediction["distance"], distances[eid]
        ):
            _reject("GEOMETRY_MISMATCH")
        expected_q = (
            candidates[eid].observation.raw_sharpe
            - candidates[anchor_id].observation.raw_sharpe
            - prediction["yhat"]
        )
        if not _close(prediction["qhat"], expected_q):
            _reject("Q_IDENTITY_INVALID")
        eligible = prediction["qhat"] >= Q_FLOOR
        if prediction["eligible"] != eligible or prediction["exclusion"] != (
            None if eligible else "PREDICTED_Q_FLOOR"
        ):
            _reject("Q_GUARD_INVALID")

    if status == MODEL_PROPOSAL:
        anchor = by_id[anchor_id]
        if any(anchor[k] != 0.0 for k in ("yhat", "qhat", "distance")):
            _reject("ANCHOR_NOT_EXACT_ZERO")
        safe = [p for p in by_id.values() if p["eligible"]]
        minimum = min(p["yhat"] for p in safe)
        ties = [p for p in safe if p["yhat"] <= minimum + TIE_TOLERANCE]
        # Reproduce the fixed two-pass rule independently, using trusted geometry/IDs.
        winner = min(
            ties,
            key=lambda p: (
                distances[p["evaluation_id"]],
                candidates[p["evaluation_id"]].candidate_id,
                p["evaluation_id"],
            ),
        )
        if winner["evaluation_id"] != winner_id:
            _reject("WINNER_MISMATCH")
        if "tie_set" in row:
            reported = row["tie_set"]
            expected = {p["evaluation_id"] for p in ties}
            if (
                not isinstance(reported, (tuple, list))
                or not all(isinstance(eid, str) for eid in reported)
                or len(reported) != len(set(reported))
                or set(reported) != expected
            ):
                _reject("TIE_SET_MISMATCH")
    return by_id
