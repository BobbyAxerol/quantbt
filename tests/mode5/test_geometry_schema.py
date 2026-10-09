import copy
import pickle

import pytest

from tools.mode5_geometry import EffectiveGeometry, OrderedConstraint, ProposalLedger, neutral_coverage


def test_m5t_051_fixed_and_source_inactive_do_not_change_active_distance():
    base = EffectiveGeometry.from_ranges({"x": (0., 10.)})
    extended = EffectiveGeometry.from_ranges({"x": (0., 10.), "fixed": 7, "ignored": (0, 100)},
        inactive=(("ignored", "reviewed source ignores this input"),))
    assert base.distance(base.resolve({"x": 2.}), base.resolve({"x": 8.})) == pytest.approx(.6)
    a, b = extended.resolve({"x": 2., "ignored": 1}), extended.resolve({"x": 8., "ignored": 100})
    assert extended.distance(a, b) == pytest.approx(.6) and a.active_names == ("x",)
    assert a.identity == extended.resolve({"x": 2., "ignored": 99}).identity


def test_m5t_052_outlier_does_not_refit_scale():
    g = EffectiveGeometry.from_ranges({"x": (-100., 100.)})
    a, b = g.resolve({"x": 0.}), g.resolve({"x": 1.})
    before = g.distance(a, b)
    g.resolve({"x": 100.})
    assert g.distance(a, b) == before == pytest.approx(.005)


def test_m5t_053_log_integer_category_and_boundary_units():
    g = EffectiveGeometry.from_ranges({"scale": {"kind": "float", "low": 1., "high": 100., "log": True},
        "period": (2, 12, 2), "branch": ["long", "short"]})
    a = g.resolve({"scale": 1., "period": 2, "branch": "long"})
    b = g.resolve({"scale": 10., "period": 4, "branch": "short"})
    assert g.distance(a, b) == pytest.approx((.5+.2+1)/3)
    assert g.decode("period", .15) == 4 and g.decode("scale", .5) == pytest.approx(10.)
    with pytest.raises(ValueError):
        g.resolve({"scale": 0., "period": 3, "branch": "long"})
    with pytest.raises(ValueError):
        g.coordinate("branch", "long")


def test_conditional_axis_inactive_collisions_and_branch_mismatch_are_explicit():
    g = EffectiveGeometry.from_ranges({"enabled": [False, True],
        "delay": {"kind": "integer", "low": 1, "high": 9, "active_if": {"enabled": True}}})
    a, b = g.resolve({"enabled": False, "delay": 1}), g.resolve({"enabled": True, "delay": 5})
    assert a.active_names == ("enabled",) and "delay" not in a.params
    assert g.distance(a, b) == 1.
    assert a.identity == g.resolve({"enabled": False, "delay": 9}).identity


@pytest.mark.parametrize("names", [("min", "max"), ("atr_fast", "atr_slow"), ("tp1", "tp2", "tp3")])
def test_m5t_054_ordered_manifold_rejects_without_sorting(names):
    g = EffectiveGeometry.from_ranges({name: (1, 10) for name in names},
        constraints=(OrderedConstraint(names),))
    params = dict(zip(names, range(2, 2+len(names))))
    assert g.resolve(params).params == params
    bad = params | {names[0]: 9}
    with pytest.raises(ValueError, match="MANIFOLD"):
        g.resolve(bad)


def test_m5t_055_raw_integer_cast_collisions_are_retained():
    g = EffectiveGeometry.from_ranges({"coeff": (1, 4)}, casts=(("coeff", "truncate_integer_v1"),))
    ledger = ProposalLedger(g, role="selection_probe")
    a = ledger.add({"coeff": 1.1}, direction="raw-left")
    b = ledger.add({"coeff": 1.9}, direction="raw-right")
    assert a.point.identity == b.point.identity and a.requested_json != b.requested_json
    assert b.status == "COLLISION" and b.duplicate_of == 0
    assert a.point.changes == (("coeff", "truncate_integer_v1"),)
    assert ledger.coverage()["unique_effective"] == 1 and len(ledger.rows) == 2


def test_neutral_coverage_seed_branch_allocation_and_duplicate_counts():
    g = EffectiveGeometry.from_ranges({"on": [False, True], "x": (1, 2),
        "delay": {"kind": "integer", "low": 1, "high": 2, "active_if": {"on": True}}})
    args = dict(branches=(({"on": False}, 8), ({"on": True}, 8)), seed=731)
    a, b = neutral_coverage(g, **args), neutral_coverage(g, **args)
    assert a.rows == b.rows and len(a.rows) == 16
    assert len([r for r in a.rows if r.point.params["on"]]) == 8
    assert a.coverage()["collisions"] > 0 and a.coverage()["unique_effective"] <= 6


def test_neutral_coverage_preserves_invalid_coupled_rows():
    g = EffectiveGeometry.from_ranges({"min": (1, 5), "max": (1, 5)},
        constraints=(OrderedConstraint(("min", "max")),))
    ledger = neutral_coverage(g, branches=(({}, 32),), seed=731)
    assert ledger.coverage()["infeasible"] > 0
    assert len(ledger.rows) == 32 and all(r.requested_json for r in ledger.rows)


def test_fixed_inactive_axes_do_not_consume_neutral_cube_dimensions():
    base = EffectiveGeometry.from_ranges({"x": (0., 10.)})
    extended = EffectiveGeometry.from_ranges({"fixed": 7, "ignored": (0., 100.), "x": (0., 10.)},
        inactive=(("ignored", "source proven inactive"),))
    args = dict(branches=(({}, 16),), seed=731)
    a, b = neutral_coverage(base, **args), neutral_coverage(extended, **args)
    assert [r.point.params["x"] for r in a.rows] == [r.point.params["x"] for r in b.rows]


def test_frozen_disabled_child_does_not_consume_neutral_cube_dimensions():
    base = EffectiveGeometry.from_ranges({"enabled": False, "x": (0., 10.)})
    extended = EffectiveGeometry.from_ranges({"enabled": False,
        "delay": {"kind": "integer", "low": 1, "high": 9, "active_if": {"enabled": True}}, "x": (0., 10.)})
    args = dict(branches=(({}, 16),), seed=731)
    a, b = neutral_coverage(base, **args), neutral_coverage(extended, **args)
    assert [r.point.params["x"] for r in a.rows] == [r.point.params["x"] for r in b.rows]


def test_all_fixed_neutral_design_retains_requested_collisions():
    g = EffectiveGeometry.from_ranges({"x": 1})
    ledger = neutral_coverage(g, branches=(({}, 8),), seed=731)
    assert ledger.coverage()["unique_effective"] == 1 and ledger.coverage()["collisions"] == 7


def test_impossible_branch_allocation_is_rejected_not_silently_ignored():
    g = EffectiveGeometry.from_ranges({"on": [False, True],
        "delay": {"kind": "integer", "low": 1, "high": 2, "active_if": {"on": True}}})
    with pytest.raises(ValueError, match="inactive"):
        neutral_coverage(g, branches=((dict(on=False, delay=1), 8),), seed=731)


@pytest.mark.parametrize("transport", [copy.deepcopy, lambda obj: pickle.loads(pickle.dumps(obj))])
def test_schema_transport_preserves_frozen_identity(transport):
    g = EffectiveGeometry.from_ranges({"x": (1., 10.)}, weights=(("x", 2.),))
    restored = transport(g)
    assert restored.identity == g.identity and restored.resolve({"x": 2.}) == g.resolve({"x": 2.})


@pytest.mark.parametrize("value", [float("nan"), float("inf"), True, "1"])
def test_nonfinite_or_non_numeric_source_cast_rejected(value):
    g = EffectiveGeometry.from_ranges({"x": (1, 10)}, casts=(("x", "truncate_integer_v1"),))
    with pytest.raises(ValueError):
        g.resolve({"x": value})
