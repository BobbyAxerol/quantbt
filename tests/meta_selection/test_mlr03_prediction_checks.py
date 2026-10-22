"""Trusted synthetic clocks, source records, geometry and fixed decision algebra."""

from copy import deepcopy
from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from quantbt.optimization.meta_selection.common import MetaRecordError
from quantbt.optimization.meta_selection.descriptors import DescriptorSchema
from quantbt.optimization.meta_selection.records import OutcomeStatus
from tests.meta_selection.test_mlr02_linear import supported_task
from tests.meta_selection.test_qms03_history import RANGES, make_task, revision_for
from tools.meta_model_research.prediction_checks import validate_bound_predictions


def make_data(*, n=7, invalid=None, schema=None):
    if schema is None:
        _, schema = make_task(n=n)
    task = supported_task(schema, n=n)
    if invalid is not None:
        eid, change = invalid
        candidates = tuple(
            replace(c, observation=replace(c.observation, **change))
            if c.evaluation_id == eid
            else c
            for c in task.candidates
        )
        task = replace(task, candidates=candidates)
    revision = revision_for(
        task,
        schema,
        status_by_id={
            c.evaluation_id: c.observation.status
            for c in task.candidates
            if c.observation.status != OutcomeStatus.VALID
        },
    )
    row = dict(
        status="META_MODEL_PROPOSAL",
        anchor=task.anchor_candidate_evaluation_id,
        cutoff=task.data_cutoff.isoformat(),
        label_available_at=max(
            o.label_available_at for o in revision.outcomes
        ).isoformat(),
        revision_available_at=revision.revision_available_at.isoformat(),
        winner=task.anchor_candidate_evaluation_id,
    )
    # Independent scalar Euclidean distances on schema-owned parameter geometry.
    batch = schema.encode(task.candidates)
    geometry = schema.parameter_geometry(task.candidates)
    predictions = []
    for c, coordinates, valid in zip(task.candidates, geometry, batch.valid):
        valid = bool(valid) and c.observation.verification != "unverified"
        predictions.append(
            dict(
                evaluation_id=c.evaluation_id,
                candidate_id=c.candidate_id,
                raw_is=c.observation.raw_sharpe,
                yhat=0.0 if valid else None,
                qhat=c.observation.raw_sharpe - task.anchor.observation.raw_sharpe
                if valid
                else None,
                distance=float(
                    sum((a - b) ** 2 for a, b in zip(coordinates, geometry[0])) ** 0.5
                )
                if valid
                else None,
                eligible=valid,
                exclusion=None if valid else c.observation.status.value,
            )
        )
    return row, predictions, revision, schema


@pytest.fixture
def data():
    return make_data()


def validate(data):
    return validate_bound_predictions(*data)


def set_y(prediction, yhat, anchor_raw=0.0):
    prediction["yhat"] = yhat
    prediction["qhat"] = prediction["raw_is"] - anchor_raw - yhat
    prediction["eligible"] = prediction["qhat"] >= -0.1
    prediction["exclusion"] = None if prediction["eligible"] else "PREDICTED_Q_FLOOR"


def test_full_pool_binding_returns_detached_eid_index_without_mutating_inputs(data):
    before = deepcopy(data[:2])
    bound = validate(data)
    assert len(bound) == 7
    assert set(bound) == {c.evaluation_id for c in data[2].task.candidates}
    assert data[:2] == before
    assert all(bound[p["evaluation_id"]] == p for p in data[1])
    bound[data[1][0]["evaluation_id"]]["raw_is"] = 999.0
    assert data[:2] == before


def test_clock_binding_uses_maximum_trusted_label_not_first_or_revision(data):
    row, predictions, revision, schema = data
    later = revision.revision_available_at + pd.Timedelta(days=2)
    outcomes = (revision.outcomes[0],) + tuple(
        replace(o, label_available_at=later) for o in revision.outcomes[1:]
    )
    revised = replace(
        revision, outcomes=outcomes, revision_available_at=later + pd.Timedelta(hours=1)
    )
    row["label_available_at"] = later.isoformat()
    row["revision_available_at"] = revised.revision_available_at.isoformat()
    assert validate_bound_predictions(row, predictions, revised, schema)
    row["label_available_at"] = revision.outcomes[0].label_available_at.isoformat()
    with pytest.raises(MetaRecordError, match="CLOCK_MISMATCH:label_available_at"):
        validate_bound_predictions(row, predictions, revised, schema)


@pytest.mark.parametrize(
    "field", ["cutoff", "label_available_at", "revision_available_at"]
)
@pytest.mark.parametrize("mutation", ["early", "late", "missing", "naive", "null"])
def test_each_timestamp_is_required_aware_and_exact(data, field, mutation):
    if mutation == "missing":
        del data[0][field]
    elif mutation == "naive":
        data[0][field] = "2020-01-01"
    elif mutation == "null":
        data[0][field] = None
    else:
        amount = -1 if mutation == "early" else 1
        data[0][field] = (
            pd.Timestamp(data[0][field]) + pd.Timedelta(nanoseconds=amount)
        ).isoformat()
    with pytest.raises(MetaRecordError, match="CLOCK_"):
        validate(data)


def test_equivalent_timezone_representation_is_same_instant(data):
    for field in ("cutoff", "label_available_at", "revision_available_at"):
        data[0][field] = (
            pd.Timestamp(data[0][field]).tz_convert("America/New_York").isoformat()
        )
    assert validate(data)


@pytest.mark.parametrize(
    "mutation",
    ["missing", "duplicate", "duplicate-replacing-missing", "unknown", "empty"],
)
def test_model_roster_is_full_unique_and_known(data, mutation):
    predictions = data[1]
    if mutation == "missing":
        predictions.pop()
    elif mutation == "duplicate":
        predictions.append(deepcopy(predictions[0]))
    elif mutation == "duplicate-replacing-missing":
        predictions[-1] = deepcopy(predictions[0])
    elif mutation == "unknown":
        predictions[-1]["evaluation_id"] = "untrusted-eid"
    else:
        predictions.clear()
    with pytest.raises(MetaRecordError, match="ROSTER|DUPLICATE_EID|UNKNOWN_EID"):
        validate(data)


@pytest.mark.parametrize(
    "field,value,error",
    [
        ("candidate_id", "wrong-candidate", "CANDIDATE_ID"),
        ("raw_is", 0.10000000000001, "RAW_IS"),
        ("raw_is", None, "RAW_IS"),
        ("raw_is", True, "RAW_IS"),
        ("distance", 999.0, "GEOMETRY"),
        ("distance", -1.0, "GEOMETRY"),
        ("qhat", 123.0, "Q_IDENTITY"),
        ("eligible", False, "Q_GUARD"),
        ("eligible", 1, "ELIGIBILITY"),
        ("exclusion", "PREDICTED_Q_FLOOR", "Q_GUARD"),
    ],
)
def test_every_trusted_source_and_guard_field_is_bound(data, field, value, error):
    data[1][1][field] = value
    with pytest.raises(MetaRecordError, match=error):
        validate(data)


def test_self_consistent_raw_is_forgery_cannot_change_guard(data):
    p = data[1][1]
    p["raw_is"] = -99.0
    set_y(p, 0.0)
    with pytest.raises(MetaRecordError, match="RAW_IS"):
        validate(data)


@pytest.mark.parametrize("field", ["yhat", "qhat", "distance"])
@pytest.mark.parametrize("bad", [None, float("nan"), float("inf"), True])
def test_scores_must_be_finite_real_values(data, field, bad):
    data[1][1][field] = bad
    with pytest.raises(MetaRecordError, match="SCORE_NONFINITE_OR_MISSING"):
        validate(data)


@pytest.mark.parametrize("field", ["yhat", "qhat", "distance"])
def test_anchor_zero_is_exact_even_inside_numeric_tolerance(data, field):
    data[1][0][field] = 1e-15
    with pytest.raises(MetaRecordError, match="ANCHOR_NOT_EXACT_ZERO"):
        validate(data)


def test_q_and_geometry_tolerances_are_frozen_at_one_e_minus_twelve(data):
    data[1][1]["distance"] += 1e-13
    data[1][1]["qhat"] += 1e-13
    assert validate(data)
    data[1][1]["distance"] += 1e-8
    with pytest.raises(MetaRecordError, match="GEOMETRY"):
        validate(data)
    data = make_data()
    data[1][1]["qhat"] += 1e-8
    with pytest.raises(MetaRecordError, match="Q_IDENTITY"):
        validate(data)


def test_q_floor_is_exact_not_tolerance_relaxed(data):
    p = data[1][1]
    p.update(raw_is=0.1, yhat=0.2, qhat=-0.1, eligible=True, exclusion=None)
    assert validate(data)
    p["qhat"] = float(np.nextafter(-0.1, -np.inf))
    p["eligible"], p["exclusion"] = False, "PREDICTED_Q_FLOOR"
    assert validate(data)
    p["eligible"] = True
    with pytest.raises(MetaRecordError, match="Q_GUARD"):
        validate(data)


def test_two_pass_ties_use_trusted_geometry_not_lowest_y_alone(data):
    a, b = data[1][1:3]
    set_y(a, -0.2)
    set_y(b, -0.2 + 5e-11)
    # Candidate 2 shares the anchor's inactive filter; it is geometrically closer.
    assert b["distance"] < a["distance"]
    data[0]["winner"] = b["evaluation_id"]
    data[0]["tie_set"] = [a["evaluation_id"], b["evaluation_id"]]
    assert validate(data)
    data[0]["winner"] = a["evaluation_id"]
    with pytest.raises(MetaRecordError, match="WINNER_MISMATCH"):
        validate(data)
    data[0]["winner"] = b["evaluation_id"]
    set_y(b, -0.2 + 2e-10)
    data[0].pop("tie_set")
    with pytest.raises(MetaRecordError, match="WINNER_MISMATCH"):
        validate(data)


def test_equal_geometry_ties_use_trusted_candidate_then_evaluation_id(data):
    task = data[2].task
    a, b = task.candidates[1:3]
    b = replace(
        b, requested_params=a.requested_params, effective_params=a.effective_params
    )
    task = replace(task, candidates=(task.anchor, a, b, *task.candidates[3:]))
    revision = revision_for(task, data[3])
    data = (data[0], data[1], revision, data[3])
    data[1][2]["distance"] = data[1][1]["distance"]
    set_y(data[1][1], -0.2)
    set_y(data[1][2], -0.2)
    data[0]["winner"] = a.evaluation_id
    assert validate(data)
    data[1][2]["candidate_id"] = "candidate-000"
    data[0]["winner"] = b.evaluation_id
    with pytest.raises(MetaRecordError, match="CANDIDATE_ID"):
        validate(data)


@pytest.mark.parametrize(
    "mutation",
    [
        "unknown-winner",
        "wrong-winner",
        "wrong-anchor",
        "unknown-status",
        "missing-field",
        "extra-field",
        "false-ties",
    ],
)
def test_row_bindings_and_prediction_format_fail_closed(data, mutation):
    if mutation == "unknown-winner":
        data[0]["winner"] = "unknown"
    elif mutation == "wrong-winner":
        data[0]["winner"] = data[1][1]["evaluation_id"]
    elif mutation == "wrong-anchor":
        data[0]["anchor"] = data[1][1]["evaluation_id"]
    elif mutation == "unknown-status":
        data[0]["status"] = "PASS_WHATEVER"
    elif mutation == "missing-field":
        del data[1][1]["exclusion"]
    elif mutation == "extra-field":
        data[1][1]["model_override"] = 0
    else:
        data[0]["tie_set"] = [data[0]["anchor"], data[0]["anchor"]]
    with pytest.raises(MetaRecordError):
        validate(data)


@pytest.mark.parametrize(
    "change",
    [
        dict(
            status=OutcomeStatus.NO_VARIANCE,
            raw_sharpe=None,
            sample_std=None,
            sample_count=0,
        ),
        dict(status=OutcomeStatus.UNVERIFIED, verification="unverified"),
        dict(activity_count=None),
    ],
)
def test_invalid_source_records_are_unscored_not_fabricated_as_eligible(change):
    data = make_data(invalid=("evaluation-2020-6", change))
    bound = validate(data)
    p = bound["evaluation-2020-6"]
    assert p["yhat"] is p["qhat"] is p["distance"] is None
    assert p["eligible"] is False
    assert p["exclusion"] == data[2].task.candidates[-1].observation.status.value
    for key, value in (
        ("yhat", 0.0),
        ("qhat", 0.0),
        ("distance", 0.0),
        ("eligible", True),
        ("exclusion", None),
    ):
        changed = deepcopy(data[:2])
        changed[1][-1][key] = value
        with pytest.raises(MetaRecordError, match="UNSCORED_GUARD"):
            validate_bound_predictions(*changed, data[2], data[3])


def test_model_proposal_cannot_have_source_invalid_anchor():
    data = make_data(invalid=("evaluation-2020-0", dict(activity_count=None)))
    with pytest.raises(MetaRecordError, match="ANCHOR_SOURCE_INVALID"):
        validate(data)


def test_activity_is_required_only_when_declared_in_the_bound_schema():
    schema = DescriptorSchema(RANGES, include_activity=False)
    data = make_data(
        schema=schema, invalid=("evaluation-2020-6", dict(activity_count=None))
    )
    assert validate(data)["evaluation-2020-6"]["yhat"] == 0.0


def test_different_schema_cannot_validate_a_task(data):
    schema = DescriptorSchema({"x": (1, 5, 1)}, include_activity=False)
    with pytest.raises(MetaRecordError, match="SCHEMA_MISMATCH"):
        validate_bound_predictions(data[0], data[1], data[2], schema)


@pytest.mark.parametrize(
    "status",
    [
        "META_SUPPORT_INSUFFICIENT",
        "META_NOT_APPLICABLE_METRIC",
        "META_OOD_NATIVE_FALLBACK",
    ],
)
def test_fallback_allows_empty_roster_but_never_a_new_winner(data, status):
    data[0]["status"] = status
    assert validate_bound_predictions(data[0], [], data[2], data[3]) == {}
    data[0]["winner"] = data[1][1]["evaluation_id"]
    with pytest.raises(MetaRecordError, match="FALLBACK_WINNER"):
        validate_bound_predictions(data[0], [], data[2], data[3])


def test_fallback_nonempty_records_are_bound_unscored_and_unknown_eids_rejected(data):
    data[0]["status"] = "META_SUPPORT_INSUFFICIENT"
    p = data[1][1]
    p.update(
        yhat=None,
        qhat=None,
        distance=None,
        eligible=False,
        exclusion="META_SUPPORT_INSUFFICIENT",
    )
    assert len(validate_bound_predictions(data[0], [p], data[2], data[3])) == 1
    p["evaluation_id"] = "unknown"
    with pytest.raises(MetaRecordError, match="UNKNOWN_EID"):
        validate_bound_predictions(data[0], [p], data[2], data[3])
    p["evaluation_id"] = data[2].task.candidates[1].evaluation_id
    p["yhat"] = 0.0
    with pytest.raises(MetaRecordError, match="UNSCORED_GUARD"):
        validate_bound_predictions(data[0], [p], data[2], data[3])


def test_row_and_task_permutations_do_not_change_validated_values(data):
    expected = validate(data)
    data[1].reverse()
    task = replace(data[2].task, candidates=tuple(reversed(data[2].task.candidates)))
    revision = replace(data[2], task=task)
    assert validate_bound_predictions(data[0], data[1], revision, data[3]) == expected
