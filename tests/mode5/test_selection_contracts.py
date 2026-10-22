from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
import pickle

import pytest

from tools.mode5_diagnostics.access import AccessPolicy, AccessWitness
from tools.mode5_selection.contracts import Channel, Formula, Panel
from tools.mode5_statistics.contracts import MetricValue
from tests.mode5.selection_fixtures import panel, plan


@pytest.mark.parametrize("name,unit", [("PSR_EVIDENCE_V1", "dollars"),
    ("ECONOMIC_UTILITY_V1", "probability"), ("LEGACY_SHARPE_UTILITY_REPLAY", "annual_ratio")])
def test_channels_reject_mixed_units(name, unit):
    with pytest.raises(ValueError):
        Channel(name, "mode5.test", unit)


@pytest.mark.parametrize("values", [(), (("mean", .1), ("mean", .2)), (("mean", float("nan")),),
                                   (("mean", -.1),), (("extra", 1.),)])
def test_coefficients_explicit_and_finite(values):
    with pytest.raises(ValueError):
        Formula("environment_floor_mean_v1", panel().channel, values)


def test_stage_rejects_moving_reference_and_channel():
    p = panel()
    frozen = plan(p)
    frozen.require(p)
    new = panel(benchmark=[.7, .8])
    with pytest.raises(ValueError, match="revision"):
        frozen.require(new)
    with pytest.raises(ValueError):
        replace(p, reference=replace(p.reference, channel="raw_sharpe"))


def test_metric_contract_and_roster_not_just_units():
    p = panel()
    c = p.candidates[0]
    with pytest.raises(ValueError):
        replace(p, candidates=(replace(c, metrics=(replace(c.metrics[0], metric_id="mode5.other"), c.metrics[1])),))
    with pytest.raises(ValueError):
        replace(p, candidates=(replace(c, metrics=c.metrics[:1], analyses=c.analyses[:1], witnesses=c.witnesses[:1]),))


def test_holdout_future_and_immature_evidence_fail_closed():
    p = panel()
    for role, end, ready in [("holdout", 5, 5), ("synthetic", 11, 11), ("synthetic", 5, 11)]:
        c = replace(p.candidates[0], witnesses=(AccessWitness("synthetic-panel", role, 0, end, ready),)*2)
        with pytest.raises(PermissionError):
            replace(p, candidates=(c,))
    with pytest.raises(ValueError):
        replace(p, access=AccessPolicy("held", ("holdout",), ("synthetic-panel",), 10, "independent_validation"))


def test_immutable_pickle_and_list_inputs():
    p = panel()
    for copy in (deepcopy(p), pickle.loads(pickle.dumps(p))):
        assert copy.identity == p.identity
        with pytest.raises(FrozenInstanceError):
            copy.revision = "mutable"
        with pytest.raises(TypeError):
            copy.reference.values[0] = 1.
    coefficients = [["mean", .25]]
    f = Formula("environment_floor_mean_v1", p.channel, coefficients)
    before = f.identity
    coefficients[0][1] = .9
    assert f.identity == before


def test_legacy_slot_is_not_current_public_selector():
    p = panel()
    with pytest.raises(ValueError):
        plan(p, "legacy_spec_1_1_quantile", (("floor", 1.), ("tail", .5), ("dispersion", .2), ("alpha", .25)))
    with pytest.raises(ValueError):
        plan(p, selector="full_sam_basin")


def test_unknown_results_preserved_but_probability_checked():
    assert panel(((None, .2),)).candidates[0].metrics[0].status == "UNDEFINED"
    probability = Channel("PSR_EVIDENCE_V1", "mode5.classical_psr_plugin_v1", "probability")
    with pytest.raises(ValueError):
        panel(((1.1, .2),), channel=probability)
    with pytest.raises(ValueError):
        panel(weights=[0., 1.])


def test_penalty_units_and_minimax_utility_restricted():
    p = panel()
    with pytest.raises(ValueError, match="penalty"):
        replace(p, candidates=(replace(p.candidates[0], activity_penalty_unit="dollars"),))
    ch = Channel("PSR_EVIDENCE_V1", "mode5.classical_psr_plugin_v1", "probability")
    with pytest.raises(ValueError):
        Formula("finite_panel_minimax_regret_v1", ch, ())


def test_registry_is_versioned_and_caller_mutation_cannot_change_rules():
    from tools.mode5_selection.contracts import FORMULAS
    from tools.mode5_selection.registry import formula_registry
    before = formula_registry()
    changed = formula_registry()
    changed["formulas"]["local_downside_v1"]["definition"] = "not-the-formula"
    assert formula_registry() == before
    with pytest.raises(TypeError):
        FORMULAS["other"] = ("local", ())


def test_fingerprint_reuse_survives_copy_but_replace_invalidates():
    p = panel()
    q = plan(p)
    before = p.identity, q.identity, q.formula.identity, p.reference.identity
    for obj in (p, q, q.formula, p.reference):
        assert "identity" in obj.__dict__
        for copy in (deepcopy(obj), pickle.loads(pickle.dumps(obj))):
            assert copy.identity == obj.identity
    assert replace(p, revision="new").identity != before[0]
    assert replace(q, stage_id="new-stage").identity != before[1]
    assert replace(q.formula, coefficients=(("mean", .5),)).identity != before[2]
    assert replace(p.reference, values=(.9, .9)).identity != before[3]


def test_plan_permission_cannot_be_rebound_to_later_cutoff():
    p = panel()
    q = plan(p)
    future = replace(p, access=replace(p.access, cutoff_ns=20))
    with pytest.raises(ValueError, match="frozen"):
        q.require(future)
    assert plan(future).identity != q.identity


def test_mutable_metric_components_rejected_before_fingerprint_reuse():
    p = panel()
    c = p.candidates[0]
    injected = replace(c.metrics[0], components=(("mutable", {"value": 1}),))
    with pytest.raises(ValueError, match="immutable scalar"):
        replace(p, candidates=(replace(c, metrics=(injected, c.metrics[1])),))


def test_decision_exposes_reference_units_inputs_and_null_reasons():
    from tools.mode5_selection import select
    p = panel(((None, .2), (.1, .2)))
    d = select(p, plan(p)).metadata
    assert d["reference"]["environment_ids"] == ["e0", "e1"]
    assert d["formula_coefficients"] == [["mean", .25]]
    assert d["evidence_refs"][0]["environment_values"] == [None, .2]
    assert d["evidence_refs"][0]["environment_null_reasons"][0] == "missing environment"
    assert d["evidence_refs"][0]["environment_sample_counts"] == [100, 100]
    assert d["channel"]["unit"] == "decimal_return"
    assert d["access_cutoff_ns"] == 10
