"""Independent mixed-space geometry and exact support-witness review."""

from dataclasses import replace
from types import SimpleNamespace

import numpy as np
import pytest

from quantbt.optimization.meta_selection.descriptors import DescriptorSchema
from quantbt.optimization.parameter_space import NormalizedSearchSpace
from tools.qms_c05_latent import digest
from tools.qms_c05_representative import (
    BINDINGS, EvaluatedPoint, parameter_geometry, representative,
)

SPACE = {
    "filter": {"kind": "boolean"},
    "length": {"kind": "integer", "low": 2, "high": 10, "step": 2,
               "active_if": {"filter": True}},
    "kind": {"kind": "categorical", "choices": ["a", "b", "c"]},
    "rate": {"kind": "float", "low": 1, "high": 100, "log": True},
    "child": {"kind": "categorical", "choices": [None, "on"],
              "active_if": {"filter": True}},
    "degree": 2,
}


def expected_bindings(ranges):
    return {**{key: f"own-{key}" for key in BINDINGS},
            "space": NormalizedSearchSpace(ranges).identity, "strategy": "alpha"}


def point(ranges, params, evaluation="e0", **kwargs):
    space = NormalizedSearchSpace(ranges)
    effective = space.effective(params)
    return EvaluatedPoint(evaluation, space.candidate_key(effective, strategy_identity="alpha"),
        effective, expected_bindings(ranges), 1.7, "own-output-" + evaluation, **kwargs)


def select(ranges, points):
    return representative(ranges, points, strategy_id="alpha", bindings=expected_bindings(ranges))


def mixed_params(**kwargs):
    return dict(filter=False, kind="a", rate=1, degree=2, **kwargs)


def test_c05_t03_independent_logical_blocks_match_hand_calculation():
    space = NormalizedSearchSpace(SPACE)
    inactive = space.effective(mixed_params())
    active = space.effective(dict(filter=True, length=10, kind="b", rate=10, child=None))
    # boolean mismatch1 + conditional numeric1 + category mismatch1 + log0.25
    # + nullable conditional category activity1 = 4.25, not enum arithmetic.
    za, zb = parameter_geometry(space, inactive), parameter_geometry(space, active)
    assert float(np.dot(za - zb, za - zb)) == pytest.approx(4.25, abs=1e-12)
    active_low = space.effective(dict(filter=True, length=2, kind="a", rate=1, child=None))
    zc = parameter_geometry(space, active_low)
    assert float(np.dot(za - zc, za - zc)) == pytest.approx(2.5, abs=1e-12)


def test_c05_t03_reference_matches_current_descriptor_geometry():
    params = [mixed_params(), dict(filter=True, length=2, kind="b", rate=10, child=None),
              dict(filter=True, length=10, kind="c", rate=100, child="on")]
    points = [point(SPACE, p, f"e{i}") for i, p in enumerate(params)]
    actual = DescriptorSchema(SPACE).parameter_geometry(
        [SimpleNamespace(effective_params=p.params) for p in points])
    independent = np.array([parameter_geometry(NormalizedSearchSpace(SPACE), p.params) for p in points])
    np.testing.assert_allclose(actual, independent, atol=1e-15, rtol=0)


def test_c05_t03_nearest_center_is_not_silently_called_medoid():
    ranges = {"x": (0.0, 1.0)}
    support = [point(ranges, {"x": x}, str(i)) for i, x in enumerate([0, 0.1, 0.2, 0.4, 1])]
    actual = select(ranges, support)
    assert actual["center"] == pytest.approx([0.34])
    assert actual["selected"].params["x"] == 0.4
    distance_sums = [sum(abs(p.params["x"] - q.params["x"]) for q in support) for p in support]
    assert support[int(np.argmin(distance_sums))].params["x"] == 0.2
    assert actual["selected"] in support and actual["auxiliary_is_evaluations"] == 0


def test_c05_t03_duplicates_do_not_move_center_or_merge_attempts():
    ranges = {"x": (0.0, 1.0)}
    support = [point(ranges, {"x": x}, f"e{i}") for i, x in enumerate([0, 0.1, 0.2, 0.4, 1])]
    before = select(ranges, support)
    duplicated = support + [replace(support[-1], evaluation_id=f"repeat{i}") for i in range(10)]
    after = select(ranges, duplicated)
    np.testing.assert_array_equal(before["center"], after["center"])
    assert before["candidate_id"] == after["candidate_id"]
    assert len(after["evaluation_ids"]) == 15 and len(after["support_ids"]) == 5


@pytest.mark.parametrize("exclusion", ["infeasible", "undefined"])
def test_c05_t03_ineligible_point_cannot_move_center(exclusion):
    ranges = {"x": (0.0, 1.0)}
    base = [point(ranges, {"x": 0.1}, "a"), point(ranges, {"x": 0.2}, "b")]
    outlier = point(ranges, {"x": 1.0}, "c")
    outlier = replace(outlier, **({"feasible": False} if exclusion == "infeasible" else {"raw_is_sharpe": np.nan}))
    before, after = select(ranges, base), select(ranges, [*base, outlier])
    np.testing.assert_array_equal(before["center"], after["center"])
    assert before["candidate_id"] == after["candidate_id"] and after["excluded"] == ("c",)


def test_c05_t03_category_permutation_preserves_distances_and_tied_semantic_winner():
    alternative = {**SPACE, "kind": {**SPACE["kind"], "choices": ["c", "a", "b"]}}
    raw = [dict(filter=False, kind=k, rate=10) for k in ("a", "b", "c")]
    a = select(SPACE, [point(SPACE, p, str(i)) for i, p in enumerate(raw)])
    b = select(alternative, [point(alternative, p, str(i)) for i, p in enumerate(raw)])
    assert len(a["tie_ids"]) == len(b["tie_ids"]) == 3
    assert dict(a["selected"].params) == dict(b["selected"].params)
    assert sorted(a["distances"].values()) == pytest.approx(sorted(b["distances"].values()))
    assert a["space_identity"] != b["space_identity"]


def test_c05_t03_exact_ties_use_total_digest_order_not_input_order():
    ranges = {"x": (0.0, 1.0)}
    points = [point(ranges, {"x": 0.0}, "a"), point(ranges, {"x": 1.0}, "b")]
    result = select(ranges, points)
    expected = min(points, key=lambda p: digest(dict(strategy="alpha", effective=dict(p.params))))
    assert len(result["tie_ids"]) == 2 and result["selected"] == expected
    assert select(ranges, list(reversed(points)))["selected"] == expected


def test_c05_t03_nontied_support_permutation_preserves_center_and_selection():
    ranges = {"x": (0.0, 1.0)}
    points = [point(ranges, {"x": x}, str(i)) for i, x in enumerate([0, 0.1, 0.2, 0.4, 1])]
    before, after = select(ranges, points), select(ranges, list(reversed(points)))
    np.testing.assert_array_equal(before["center"], after["center"])
    assert before["distances"] == after["distances"]
    assert before["selected"] is after["selected"]
    with pytest.raises(ValueError):
        after["center"][0] = 999


def test_c05_t03_tie_band_is_from_minimum_not_nontransitive_pair_comparator():
    ranges = {"x": (0.0, 1.0)}
    points = [point(ranges, {"x": x}, str(i)) for i, x in enumerate([0.2, 0.200000000001, 0.9])]
    result = select(ranges, points)
    minimum = min(result["distances"].values())
    assert set(result["tie_ids"]) == {c for c, d in result["distances"].items() if d <= minimum + 1e-12}


def test_c05_t03_singleton_and_fixed_only_support_are_valid():
    for ranges, params in [({"x": (0, 10)}, {"x": 4}), ({"degree": 2}, {})]:
        own = point(ranges, params)
        actual = select(ranges, [own])
        assert actual["selected"] is own and all(d == 0 for d in actual["distances"].values())


@pytest.mark.parametrize("points", [[], [point({"x": (0, 1)}, {"x": 0}, feasible=False)]])
def test_c05_t03_empty_admissible_support_fails(points):
    with pytest.raises(ValueError, match="no admissible"):
        select({"x": (0, 1)}, points)


def test_c05_t04_selected_metrics_are_own_not_cluster_averages():
    ranges = {"x": (0.0, 1.0)}
    points = [replace(point(ranges, {"x": x}, str(i)), raw_is_sharpe=sr)
              for i, (x, sr) in enumerate([(0, 1), (0.4, 5), (1, 2)])]
    selected = select(ranges, points)["selected"]
    assert selected is points[1] and selected.raw_is_sharpe == 5
    assert selected.raw_is_sharpe != np.mean([p.raw_is_sharpe for p in points])


@pytest.mark.parametrize("binding", sorted(BINDINGS))
def test_c05_t04_wrong_original_is_binding_is_never_reused(binding):
    ranges = {"x": (0.0, 1.0)}
    own = point(ranges, {"x": 0.4})
    wrong = replace(own, bindings={**own.bindings, binding: "another"})
    with pytest.raises(ValueError, match="witness"):
        select(ranges, [wrong])


@pytest.mark.parametrize("mutation", ["role", "averaged", "candidate", "params", "missing_output",
                                     "duplicate_id", "inactive_extra", "invalid_target", "bool_feasible"])
def test_c05_t04_invalid_anchor_is_not_advertised_original(mutation):
    ranges = SPACE
    own = point(ranges, mixed_params())
    kwargs = {}
    if mutation == "role":
        kwargs["role"] = "FWD"
    elif mutation == "averaged":
        kwargs["verification"] = "cluster_average"
    elif mutation == "candidate":
        kwargs["candidate_id"] = "different"
    elif mutation == "params":
        kwargs["params"] = {**own.params, "rate": 2.0}
    elif mutation == "missing_output":
        kwargs["output_ref"] = ""
    elif mutation == "inactive_extra":
        kwargs["params"] = {**own.params, "length": 4}
    elif mutation == "invalid_target":
        kwargs["params"] = {**own.params, "rate": 500}
    elif mutation == "bool_feasible":
        kwargs["feasible"] = 1
    points = [own, own] if mutation == "duplicate_id" else [replace(own, **kwargs)]
    with pytest.raises(ValueError):
        select(ranges, points)


def test_c05_t04_review_witness_is_frozen_and_cannot_mutate_original_params():
    params, bindings = {"x": 0.4}, expected_bindings({"x": (0.0, 1.0)})
    own = point({"x": (0.0, 1.0)}, params)
    params["x"] = 1.0
    bindings["market"] = "other"
    assert own.params["x"] == 0.4 and own.bindings["market"] == "own-market"
    with pytest.raises(TypeError):
        own.params["x"] = 1.0
