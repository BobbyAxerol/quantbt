"""Finite evaluated support, not synthetic parameters or averaged metrics."""

from dataclasses import replace
from types import SimpleNamespace

import numpy as np
import pytest

from quantbt.optimization.meta_selection.common import digest, wire
from quantbt.optimization.meta_selection.records import MetricObservation, OutcomeStatus
from quantbt.optimization.parameter_space import NormalizedSearchSpace
from quantbt.optimization.representatives import EvaluatedSupport, POLICY, validate_scope
from quantbt.walkforward import WalkForwardTrialRecord
from tools.qms_c05_representative import BINDINGS, EvaluatedPoint, representative


def records(ranges, params):
    space = NormalizedSearchSpace(ranges)
    context = dict(market="market", calendar="calendar", accounting="account", objective="objective",
        metric="metric", execution_seed="731", is_start="2023-01-01T00:00:00+00:00",
        is_cutoff="2023-12-31T00:00:00+00:00", strategy="pre04", space=space.identity)
    rows = []
    for i, p in enumerate(params):
        p = space.effective(p)
        obs = MetricObservation(status=OutcomeStatus.VALID, raw_sharpe=1.+i/10., activity_count=4,
            sample_count=365, sample_std=.01, metric_contract_id="metric", economics_id="account",
            window_start=context["is_start"], window_end=context["is_cutoff"],
            input_frontier=context["is_cutoff"], initial_capital=20000., initial_mark_equity=20000.,
            output_ref="output-"+str(i), input_signature="market", verification="original_result")
        evaluation = digest(dict(context=context, trial=i, params=p, output=digest(obs)))
        rows.append(WalkForwardTrialRecord(i, p, 1.+i/10., obs.raw_sharpe, 0., 0., 0.,
            [dict(meta_observation=wire(obs))], selection_metadata=dict(representative_context=context,
            representative_evaluation_id=evaluation, feasible=True)))
    return rows, context


def compare(ranges, rows, context):
    bindings = {k: context[k] for k in BINDINGS}
    points = [EvaluatedPoint(r.selection_metadata["representative_evaluation_id"],
        NormalizedSearchSpace(ranges).candidate_key(r.params, strategy_identity=context["strategy"]),
        r.params, bindings, r.mean_is_sharpe, r.fold_metrics[0]["meta_observation"]["output_ref"],
        feasible=r.selection_metadata.get("feasible", True)) for r in rows]
    reference = representative(ranges, points, strategy_id=context["strategy"], bindings=bindings)
    actual = EvaluatedSupport(rows, ranges).select(rows, details={"cluster_size": len(rows)})
    assert actual.params == dict(reference["selected"].params)
    assert actual.mean_is_sharpe == reference["selected"].raw_is_sharpe
    assert actual.selection_metadata["representative_support"] == list(reference["support_ids"])
    np.testing.assert_array_equal(actual.selection_metadata["representative_center"], reference["center"])
    assert actual.selection_metadata["representative_distances_squared"] == list(reference["distances"].values())
    assert actual.selection_metadata["auxiliary_is_evaluations"] == 0
    assert actual.selection_metadata["requires_evaluation"] is False
    assert actual.fold_metrics == next(r.fold_metrics for r in rows if r.trial_id == actual.trial_id)
    return actual


def test_hand_center_projection_differs_from_medoid():
    ranges = {"x": {"kind": "float", "low": 0., "high": 1.}}
    rows, context = records(ranges, [{"x": x} for x in [0., .1, .2, .4, 1.]])
    result = compare(ranges, rows, context)
    assert result.params == {"x": .4}
    assert result.selection_metadata["representative_center"] == pytest.approx([.34], abs=1e-15)


@pytest.mark.parametrize("reverse_vocab", [False, True])
@pytest.mark.parametrize("reverse_rows", [False, True])
def test_conditional_geometry_permutation_ties_duplicates(reverse_vocab, reverse_rows):
    ranges = {"on": [True, False][::(-1 if reverse_vocab else 1)],
        "x": {"kind": "float", "low": .001, "high": 1., "log": True, "active_if": {"on": [True]}},
        "c": {"kind": "categorical", "choices": ["b", "a"] if reverse_vocab else ["a", "b"],
              "active_if": {"on": [True]}}, "fixed": 2}
    rows, context = records(ranges, [{"on": True, "x": .001, "c": "a"},
        {"on": True, "x": 1., "c": "b"}, {"on": False}, {"on": False}])
    if reverse_rows:
        rows.reverse()
    result = compare(ranges, rows, context)
    assert len(result.selection_metadata["representative_support"]) == 3
    assert len(result.selection_metadata["representative_evaluations"]) == 4
    original_ranges = {**ranges, "on": [True, False], "c": {**ranges["c"], "choices": ["a", "b"]}}
    original_rows, original_context = records(original_ranges, [r.params for r in rows])
    assert result.params == compare(original_ranges, original_rows, original_context).params


def test_singleton_feasibility_and_empty_support():
    ranges = {"x": (0., 1.)}
    rows, context = records(ranges, [{"x": .1}, {"x": .8}])
    rows[1] = replace(rows[1], selection_metadata={**rows[1].selection_metadata, "feasible": False})
    assert compare(ranges, rows, context).params == {"x": .1}
    rows[0] = replace(rows[0], selection_metadata={**rows[0].selection_metadata, "feasible": False})
    with pytest.raises(ValueError, match="no admissible"):
        EvaluatedSupport(rows, ranges)


@pytest.mark.parametrize("field", ["market", "calendar", "accounting", "objective", "metric",
    "execution_seed", "is_cutoff", "strategy", "space", "is_start"])
def test_context_corruption_rejected(field):
    ranges = {"x": (0., 1.)}
    rows, _ = records(ranges, [{"x": .1}, {"x": .8}])
    context = {**rows[1].selection_metadata["representative_context"], field: "corrupt"}
    rows[1] = replace(rows[1], selection_metadata={**rows[1].selection_metadata, "representative_context": context})
    with pytest.raises(ValueError):
        EvaluatedSupport(rows, ranges)


@pytest.mark.parametrize("field,value", [("verification", "reviewed_import"), ("input_signature", "other"),
    ("economics_id", "other"), ("metric_contract_id", "other"), ("raw_sharpe", 999.),
    ("output_ref", "other"), ("window_end", "2024-01-01T00:00:00+00:00"),
    ("input_frontier", "2024-01-01T00:00:00+00:00")])
def test_foreign_future_or_changed_own_metric_rejected(field, value):
    ranges = {"x": (0., 1.)}
    rows, _ = records(ranges, [{"x": .1}])
    metric = {**rows[0].fold_metrics[0]["meta_observation"], field: value}
    rows[0] = replace(rows[0], fold_metrics=[dict(meta_observation=metric)])
    with pytest.raises(ValueError):
        EvaluatedSupport(rows, ranges)


@pytest.mark.parametrize("change", ["params", "missing", "duplicate", "feasible_type"])
def test_candidate_witness_identity_and_feasibility(change):
    ranges = {"x": (0., 1.)}
    rows, _ = records(ranges, [{"x": .1}])
    if change == "params":
        rows[0] = replace(rows[0], params={"x": .8})
    elif change == "missing":
        rows[0] = replace(rows[0], fold_metrics=[])
    elif change == "duplicate":
        rows += rows
    else:
        rows[0] = replace(rows[0], selection_metadata={**rows[0].selection_metadata, "feasible": "false"})
    with pytest.raises(ValueError):
        EvaluatedSupport(rows, ranges)


@pytest.mark.parametrize("mode,schedule,scoring,windows", [("mode_1_decay", "per_fold_causal", "endpoint", 1),
    ("mode_4_is_only_robust", "global", "endpoint", 1),
    ("mode_4_is_only_robust", "per_fold_causal", "proxy", 1),
    ("mode_4_is_only_robust", "per_fold_causal", "endpoint", 2)])
def test_unqualified_scope_rejects_before_sampling(mode, schedule, scoring, windows):
    config = SimpleNamespace(flat_selector=POLICY, target_mode="pct_equity", optimization_mode=mode,
        optimization_schedule=schedule, scoring_backend=scoring)
    with pytest.raises(ValueError, match="SAMPLER_SPACE_UNSUPPORTED"):
        validate_scope(config, [None]*windows)
