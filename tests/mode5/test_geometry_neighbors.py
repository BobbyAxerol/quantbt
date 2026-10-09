import numpy as np
import pytest

from tools.mode5_geometry import EffectiveGeometry, OrderedConstraint, active_neighbors, basin_catalog, local_summary, representative
from tools.mode5_geometry.basins import held_support


def neighborhood(g, center, **kwargs):
    return active_neighbors(g, center, radius=.01, minimum_radius=.005, seed=1731,
        role="selection_probe", **kwargs)


def evaluate(neighbors, f):
    return {r.point.identity: dict(status="COMPLETE", utility=f(r.point.params))
        for r in neighbors.rows if r.status == "READY"}


def test_m5t_059_schema_transverse_axis_catches_covariance_blind_spot():
    g = EffectiveGeometry.from_ranges({"x": (-1., 1.), "y": (-.5, .5)})
    center = g.resolve(dict(x=0., y=0.))
    cloud = tuple(g.resolve(dict(x=x, y=0.)) for x in np.linspace(-.1, .1, 7))
    n = neighborhood(g, center, cloud=cloud)
    f = lambda p: 1-p["x"]**2-10000*p["y"]**2
    out = local_summary(1., n, evaluate(n, f), quality_floor=.1, reference_scale=1., reference_id="fixed-unit")
    assert n.covariance_status == "SCHEMA_ONLY_SINGULAR_CLOUD"
    assert out["max_downside"] == pytest.approx(1.) and not n.coverage["uncovered_axes"]
    assert out["status"] == "FRAGILE_CENTER"


def test_m5t_060_sparse_clipping_collisions_cannot_certify_flatness():
    g = EffectiveGeometry.from_ranges({"period": (1, 100)})
    center = g.resolve(dict(period=1))
    n = active_neighbors(g, center, radius=.001, minimum_radius=.0001, seed=1731,
        role="selection_probe", cloud=(center,))
    assert n.covariance_status == "SCHEMA_ONLY_SPARSE_CLOUD" and n.coverage["clipped_rows"] > 0
    assert n.coverage["effective_center_collisions"] > 0
    assert n.coverage["collisions"] > 0 and any(r.status == "INFEASIBLE" for r in n.rows)
    assert all(r.point.identity != center.identity for r in n.rows if r.status == "READY")


def test_missing_runtime_probe_is_not_filtered_into_success():
    g = EffectiveGeometry.from_ranges({"x": (-1., 1.)})
    n = neighborhood(g, g.resolve(dict(x=0.)))
    values = evaluate(n, lambda p: 1.)
    values[next(iter(values))] = dict(status="FAILED", utility=None)
    out = local_summary(1., n, values, quality_floor=0., reference_scale=1., reference_id="fixed")
    assert out["status"] == "INSUFFICIENT_COVERAGE" and out["failed_probe_ids"]


def test_positive_broad_basin_and_flat_negative_counterworld():
    g = EffectiveGeometry.from_ranges({"x": (-1., 1.), "y": (-1., 1.)})
    center = g.resolve(dict(x=0., y=0.))
    n = neighborhood(g, center, joint_groups=(("x", "y"),))
    good = local_summary(1., n, evaluate(n, lambda p: 1-.1*(p["x"]**2+p["y"]**2)),
        quality_floor=.5, reference_scale=.1, reference_id="fixed")
    bad = local_summary(-1., n, evaluate(n, lambda p: -1.), quality_floor=.5, reference_scale=.1, reference_id="fixed")
    assert good["status"] == "OBSERVED_QUALITY_BASIN" and good["quality_survival_fraction"] == 1.
    assert bad["status"] == "QUALITY_FAIL" and bad["max_downside"] == 0.


def test_reference_roughness_shift_invariant_and_units_positive():
    g = EffectiveGeometry.from_ranges({"x": (-1., 1.)})
    n = neighborhood(g, g.resolve(dict(x=0.)))
    a = local_summary(1., n, evaluate(n, lambda p: .5), quality_floor=0., reference_scale=2., reference_id="fixed")
    b = local_summary(1001., n, evaluate(n, lambda p: 1000.5), quality_floor=1000., reference_scale=2., reference_id="fixed")
    assert a["reference_normalized_downside"] == b["reference_normalized_downside"] == .25


def test_validation_design_separate_effective_probes_and_roles():
    g = EffectiveGeometry.from_ranges({"x": (-1., 1.)})
    center = g.resolve(dict(x=0.))
    selection = neighborhood(g, center)
    validation = active_neighbors(g, center, radius=.075, minimum_radius=.05, seed=2731, role="local_validation")
    assert held_support(selection, validation)["held_distinct"] == 2
    with pytest.raises(ValueError):
        held_support(selection, selection)


def test_covariance_never_combines_far_basins_or_categorical_labels():
    g = EffectiveGeometry.from_ranges({"x": (-1., 1.), "category": ["a", "b"]})
    center = g.resolve(dict(x=0., category="a"))
    with pytest.raises(ValueError, match="radius"):
        neighborhood(g, center, cloud=(g.resolve(dict(x=1., category="a")),), cloud_radius=.2)
    with pytest.raises(ValueError, match="branch"):
        neighborhood(g, center, cloud=(g.resolve(dict(x=0., category="b")),))


def test_regularized_covariance_is_an_addition_not_schema_replacement():
    g = EffectiveGeometry.from_ranges({"x": (-1., 1.), "y": (-1., 1.)})
    center = g.resolve(dict(x=0., y=0.))
    cloud = tuple(g.resolve(dict(x=x, y=y)) for x, y in ((-.1, -.1), (-.1, .1), (.1, -.1), (.1, .1), (0., 0.)))
    n = neighborhood(g, center, cloud=cloud)
    assert n.covariance_status == "REGULARIZED_PROPOSALS_NOT_HESSIAN"
    assert any(r.direction.startswith("axis:y") for r in n.rows)
    assert any(r.direction.startswith("covariance:") for r in n.rows)


def test_multi_basins_and_medoid_centroid_are_distinct():
    g = EffectiveGeometry.from_ranges({"x": (0., 100.)})
    points = tuple(g.resolve(dict(x=x)) for x in (0., 1., 2., 3., 100.))
    assert representative(g, points, kind="medoid")["point"].params["x"] == 2.
    c = representative(g, points, kind="centroid")
    assert c["point"].params["x"] == pytest.approx(21.2) and c["actual_evaluation_required"]
    groups = basin_catalog(g, points, linkage_radius=.02, minimum_members=3)
    assert len(groups) == 2 and groups[1]["status"] == "INSUFFICIENT_MEMBERS"


def test_categorical_centroid_and_infeasible_coupled_centroid_rejected():
    g = EffectiveGeometry.from_ranges({"branch": ["a", "b"], "x": (1, 10)})
    with pytest.raises(ValueError, match="medoid"):
        representative(g, (g.resolve(dict(branch="a", x=2)), g.resolve(dict(branch="a", x=4))), kind="centroid")


def test_coupled_joint_moves_keep_invalid_ledger_rows():
    g = EffectiveGeometry.from_ranges({"min": (1, 10), "max": (1, 10)}, constraints=(OrderedConstraint(("min", "max")),))
    n = neighborhood(g, g.resolve(dict(min=4, max=5)), joint_groups=(("min", "max"),))
    assert any(r.status == "INFEASIBLE" for r in n.rows)
    assert any(r.direction.startswith("joint:") for r in n.rows)


def test_unmoved_joint_group_and_single_effective_probe_are_insufficient():
    g = EffectiveGeometry.from_ranges({"x": (1, 100), "y": (1, 100)})
    center = g.resolve(dict(x=50, y=50))
    n = active_neighbors(g, center, radius=.0001, minimum_radius=.00001, seed=1731,
        role="selection_probe", joint_groups=(("x", "y"),))
    assert n.coverage["uncovered_groups"] == ["x,y"]
    out = local_summary(1., n, evaluate(n, lambda p: 1.), quality_floor=0., reference_scale=1., reference_id="fixed")
    assert out["status"] == "INSUFFICIENT_COVERAGE"
    single = EffectiveGeometry.from_ranges({"x": (1, 2)})
    small = active_neighbors(single, single.resolve(dict(x=1)), radius=.05, minimum_radius=.01,
        seed=1731, role="selection_probe")
    assert small.coverage["unique_effective"] == 1 and small.coverage["status"] == "INSUFFICIENT_COVERAGE"
