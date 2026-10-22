from dataclasses import replace
import math

import numpy as np
import pytest

from tools.mode5_selection import Channel, LocalEvidence, Probe, StageLedger, economic_utility, evaluate, rescore_revision, select
from tools.mode5_statistics.contracts import MetricValue
from tools.mode5_statistics.tails import local_downside
from tests.mode5.selection_fixtures import panel, plan
from tests.mode5 import selection_oracle as oracle


def local(p, candidate, values, **kwargs):
    probes = tuple(Probe(f"probe-{i}", value, "COMPLETE" if value is not None else "FAILED",
                        candidate.analyses[0], candidate.witnesses[0]) for i, value in enumerate(values))
    return LocalEvidence(candidate.candidate_id, p.channel, "local-dev-IQR", .5, "weighted_environment_mean_v1",
        tuple(x.probe_id for x in probes), probes, kwargs.get("coverage", "OBSERVED_REQUIRED_RADII"),
        "SCHEMA_ONLY_INSUFFICIENT", "synthetic-geometry-proof", "synthetic-validation-proof")


def local_plan(p, version="local_downside_v1", coefficients=(("gamma", 1.),), **kwargs):
    return plan(p, version, coefficients, "full_sam_basin" if version == "local_downside_v1" else "full_dro_cvar",
                local_reference_id="local-dev-IQR", local_reference_scale=.5, **kwargs)


def test_M5T061_average_regret_is_floor_plus_mean_constant():
    p = panel(((1., 4., 2.), (3., 2., 1.), (2., 3., 3.)), weights=[1, 2, 3], benchmark=[3, 4, 3])
    old = evaluate(p, plan(p, "legacy_floor_mean_regret_v1"))
    new = evaluate(p, plan(p))
    const = .25 * oracle.weighted_tail(p.reference.values, p.reference.weights, 1)
    for a, b in zip(old, new, strict=True):
        assert a["score"] == pytest.approx(b["score"]-const, abs=1e-12)
    assert select(p, plan(p, "legacy_floor_mean_regret_v1")).metadata["chosen_candidate"] == select(p, plan(p)).metadata["chosen_candidate"]


def test_M5T062_moving_objective_blocked_and_full_panel_revision_kept():
    p = panel()
    frozen = plan(p)
    ledger = StageLedger(frozen.identity)
    for row in evaluate(p, frozen):
        ledger = ledger.append(frozen, row)
    original = ledger.identity
    newp = panel(benchmark=[.6, .9])
    newplan = plan(newp, "legacy_floor_mean_regret_v1")
    with pytest.raises(ValueError, match="moving"):
        ledger.append(newplan, evaluate(newp, newplan)[0])
    with pytest.raises(ValueError, match="different formula"):
        ledger.append(frozen, evaluate(newp, newplan)[0])
    revision = rescore_revision(ledger, newp, newplan)
    assert revision.parent_ledger == original and revision.identity != original and ledger.identity == original
    with pytest.raises(ValueError, match="all comparable"):
        rescore_revision(ledger, replace(newp, candidates=newp.candidates[:1]), newplan)
    with pytest.raises(ValueError, match="duplicate"):
        ledger.append(frozen, evaluate(p, frozen)[0])


def test_M5T063_true_max_regret_and_floor_choose_differently():
    p = panel(((2., 2.), (1., 8.)), benchmark=[2, 8])
    floor = plan(p, coefficients=(("mean", 0.),))
    minimax = plan(p, "finite_panel_minimax_regret_v1", ())
    assert select(p, floor).metadata["chosen_candidate"] == "c0"
    assert select(p, minimax).metadata["chosen_candidate"] == "c1"
    assert evaluate(p, minimax)[1]["components"]["max_regret"] == 1


def test_M5T064_quantile_is_not_tail_and_fractional_mass():
    ch = Channel("PSR_EVIDENCE_V1", "mode5.classical_psr_plugin_v1", "probability")
    p = panel(((.01, .90, .91, .92),), channel=ch)
    prefs = (("floor", 1.), ("tail", .5), ("dispersion", .2), ("alpha", .25))
    old = evaluate(p, plan(p, "legacy_spec_1_1_quantile", prefs))[0]
    new = evaluate(p, plan(p, "environment_lower_tail_v2", prefs))[0]
    assert old["components"]["tail"] == pytest.approx(.6775)
    assert not old["components"]["floor_tail_redundancy"]
    assert new["components"]["tail"] == .01
    assert new["components"]["floor_tail_redundancy"]
    p = panel(((0., 10.),), weights=[.2, .8])
    row = evaluate(p, plan(p, "environment_lower_tail_v2", (("floor", 0.), ("tail", 1.), ("dispersion", 0.), ("alpha", .5))))[0]
    assert row["score"] == pytest.approx(6.)


@pytest.mark.parametrize("values", [(1., -.2, 1.5), (2., 3., 4.), (-2., -1., 5.)])
def test_M5T065_gamma_one_is_observed_minimum(values):
    p = panel(((2., 2.),))
    q = local_plan(p)
    evidence = local(p, p.candidates[0], values)
    row = evaluate(p, q, local_evidence=(evidence,))[0]
    assert row["score"] == pytest.approx(min(2., *values))
    assert row["components"]["fragility"] == local_downside(2, values, unit=p.channel.unit).value


def test_M5T066_shift_preserves_downside_and_fixed_scale():
    p = panel(((2., 2.),))
    shifted = panel(((102., 102.),))
    a = evaluate(p, local_plan(p), local_evidence=(local(p, p.candidates[0], (1., -.2, 1.5)),))[0]
    b = evaluate(shifted, local_plan(shifted), local_evidence=(local(shifted, shifted.candidates[0], (101., 99.8, 101.5)),))[0]
    assert a["components"]["fragility"] == pytest.approx(b["components"]["fragility"], abs=1e-12)
    assert a["components"]["normalized_fragility"] == pytest.approx(b["components"]["normalized_fragility"])


@pytest.mark.parametrize("kwargs", [dict(coverage="INSUFFICIENT_COVERAGE"), {}])
def test_missing_and_failed_local_probes_not_filtered(kwargs):
    p = panel(((.1, .2),))
    e = local(p, p.candidates[0], (None, -.5), **kwargs)
    result = select(p, local_plan(p), local_evidence=(e,)).metadata
    assert result["status"] == "NO_SELECTION"
    assert result["component_rows"][0]["score"] is None
    assert result["component_rows"][0]["reasons"] == ["INCOMPLETE_LOCAL_PROBES"]
    with pytest.raises(ValueError):
        replace(e, probes=e.probes[:1])


def test_local_missing_coverage_reference_or_future_rejected():
    p = panel(((.1, .2),))
    e = local(p, p.candidates[0], (.1, .2))
    with pytest.raises(ValueError):
        evaluate(p, local_plan(p), local_evidence=(replace(e, reference_scale=.6),))
    with pytest.raises(PermissionError):
        probe = replace(e.probes[0], witness=replace(e.probes[0].witness, ready_ns=11))
        evaluate(p, local_plan(p), local_evidence=(replace(e, probes=(probe, e.probes[1])),))
    d = select(p, local_plan(p), local_evidence=(replace(e, coverage="INSUFFICIENT_COVERAGE"),))
    assert d.metadata["reason"] == "NO_SUPPORTED_CONFIGURATION"


def test_M5T067_same_channel_composite_and_no_double_cost():
    p = panel(((.1, .2),))
    prefs = (("floor", .35), ("mean", .35), ("dispersion", .15), ("fragility", .15))
    e = local(p, p.candidates[0], (-.1, .5))
    row = evaluate(p, local_plan(p, "unified_same_channel_v1", prefs), local_evidence=(e,))[0]
    assert row["score"] == pytest.approx(.35*.1+.35*.15-.15*.05-.15*.25)
    prob = Channel("PSR_EVIDENCE_V1", "mode5.classical_psr_plugin_v1", "probability")
    with pytest.raises(ValueError):
        evaluate(p, local_plan(p, "unified_same_channel_v1", prefs), local_evidence=(replace(e, channel=prob),))
    values = [MetricValue("mode5.test", "decimal_return", 100, v) for v in (.12, .1, .02)]
    utility = economic_utility(*values, dd_weight=.5, tail_weight=2, preference_id="dev-v1")
    assert utility.value == pytest.approx(.03)
    assert "no_second_fee" in dict(utility.components)["costs"]
    with pytest.raises(ValueError):
        economic_utility(values[0], values[1], replace(values[2], unit="dollars"), dd_weight=.5, tail_weight=2, preference_id="dev")


@pytest.mark.parametrize("version,coefficients", [
    ("environment_floor_mean_v1", (("mean", .25),)),
    ("legacy_floor_mean_regret_v1", (("mean", .25),)),
    ("finite_panel_minimax_regret_v1", ()),
    ("environment_lower_tail_v2", (("floor", .5), ("tail", .7), ("dispersion", .2), ("alpha", .3)))])
def test_numpy_components_against_independent_scalar_reference(version, coefficients):
    rng = np.random.default_rng(731)
    matrix = rng.normal(size=(19, 7))
    weights = rng.uniform(.1, 3, 7).tolist()
    benchmark = rng.uniform(2, 3, 7).tolist()
    p = panel(tuple(tuple(r) for r in matrix), weights=weights, benchmark=benchmark)
    rows = evaluate(p, plan(p, version, coefficients))
    for values, row in zip(matrix, rows, strict=True):
        expected = oracle.components(values, weights, benchmark)
        for key, value in expected.items():
            assert row["components"][key] == pytest.approx(value, rel=1e-12, abs=1e-12)
        if version == "environment_floor_mean_v1":
            score = expected["floor"]+.25*expected["mean"]
        elif version == "legacy_floor_mean_regret_v1":
            score = expected["floor"]-.25*expected["mean_regret"]
        elif version == "finite_panel_minimax_regret_v1":
            score = -expected["max_regret"]
        else:
            score = .5*expected["floor"]+.7*oracle.weighted_tail(values, weights, .3)-.2*expected["mad"]
        assert row["score"] == pytest.approx(score, rel=1e-12, abs=1e-12)


def test_legacy_replay_has_explicit_unequal_weight_error():
    ch = Channel("PSR_EVIDENCE_V1", "mode5.classical_psr_plugin_v1", "probability")
    p = panel(((.1, .2),), channel=ch, weights=[1, 2])
    with pytest.raises(ValueError, match="equal weights"):
        evaluate(p, plan(p, "legacy_spec_1_1_quantile", (("floor", 1.), ("tail", .5), ("dispersion", .2), ("alpha", .25))))


def test_legacy_linear_median_replay_is_not_new_weighted_lower_tie_mad():
    ch = Channel("PSR_EVIDENCE_V1", "mode5.classical_psr_plugin_v1", "probability")
    p = panel(((0., 1.),), channel=ch)
    prefs = (("floor", 1.), ("tail", .5), ("dispersion", .2), ("alpha", .25))
    before = p.identity
    old = select(p, plan(p, "legacy_spec_1_1_quantile", prefs))
    new = select(p, plan(p, "environment_lower_tail_v2", prefs))
    assert old.metadata["component_rows"][0]["components"]["mad"] == .5
    assert new.metadata["component_rows"][0]["components"]["mad"] == 0.
    assert old.identity != new.identity and old.metadata["selection_key"] != new.metadata["selection_key"]
    assert p.identity == before


def test_all_negative_regret_winner_never_claims_edge():
    p = panel(((-1., -3.), (-2., -1.)), benchmark=[-1, -1])
    d = select(p, plan(p, "finite_panel_minimax_regret_v1", ())).metadata
    assert d["chosen_candidate"] == "c1" and d["edge_claim"] == "NOT_ASSESSED"
    assert not d["deployment_authorized"]


def test_complete_extreme_values_fail_closed_when_regret_overflows():
    p = panel(((-1.e308, -1.e308),), benchmark=[1.e308, 1.e308])
    with np.errstate(over="ignore", invalid="ignore"):
        d = select(p, plan(p)).metadata
    assert d["chosen_candidate"] is None
    assert d["component_rows"][0]["reasons"] == ["ARITHMETIC_INVALID"]


def test_activity_cost_and_quantity_constraints_are_gate_inputs_not_rewritten():
    p = panel(((.8, .8), (.7, .7)))
    p = replace(p, candidates=(replace(p.candidates[0], activity_penalty=.5), p.candidates[1]))
    d = select(p, plan(p)).metadata
    assert d["chosen_candidate"] == "c1"
    assert d["component_rows"][0]["components"]["activity_penalty"] == .5
    failed = replace(p, candidates=tuple(replace(c, feasible=False, gate_ref="MIN_QTY_under_same_instrument") for c in p.candidates))
    assert select(failed, plan(p)).metadata["reason"] == "NO_SUPPORTED_CONFIGURATION"
    assert all(r["gate_ref"] == "MIN_QTY_under_same_instrument" for r in select(failed, plan(p)).metadata["component_rows"])


def test_no_supported_configuration_not_best_of_bad():
    p = panel(((-.5, -.1), (-.2, -.4)))
    p = replace(p, candidates=tuple(replace(c, quality_pass=False) for c in p.candidates))
    d = select(p, plan(p)).metadata
    assert d["status"] == "NO_SELECTION" and d["edge_claim"] == "NOT_ASSESSED"
    assert all(r["score"] is not None and r["reasons"] == ["QUALITY_FAIL"] for r in d["component_rows"])


def test_incumbent_has_same_gates_and_explicit_guard():
    p = panel(((.1, .1), (.2, .2)))
    q = replace(plan(p, incumbent_id="c0"), minimum_improvement=.2)
    d = select(p, q).metadata
    assert d["pre_incumbent_candidate"] == "c1" and d["chosen_candidate"] == "c0"
    failed = replace(p, candidates=(replace(p.candidates[0], risk_pass=False), p.candidates[1]))
    assert select(failed, q).metadata["chosen_candidate"] == "c1"
    assert select(failed, q).metadata["incumbent_guard"] == "INCUMBENT_INELIGIBLE"
    with pytest.raises(ValueError):
        select(p, replace(q, incumbent_id="not-evaluated"))


def test_ties_deterministic_components_immutable_and_unknown_not_zero():
    p = panel(((.1, .1), (.1, .1), (None, .9)), ids=["z", "a", "unknown"])
    d = select(p, plan(p))
    assert d.metadata["chosen_candidate"] == "a"
    before = d.identity
    d.metadata["component_rows"][0]["score"] = 900
    assert d.identity == before
    assert d.metadata["component_rows"][2]["score"] is None
    assert select(replace(p, candidates=p.candidates[::-1]), plan(p)).metadata["chosen_candidate"] == "a"


def test_never_selected_centroid_without_actual_evaluation():
    p = panel(((.1, .1), (.9, .9)))
    p = replace(p, candidates=(p.candidates[0], replace(p.candidates[1], evaluated=False, representative_kind="centroid")))
    assert select(p, plan(p)).metadata["chosen_candidate"] == "c0"


def test_large_finite_weight_scaling_preserves_tail_and_components():
    coefficients = (("floor", 1.), ("tail", .5), ("dispersion", .2), ("alpha", .25))
    a = panel(((.1, .2),), weights=[1., 1.])
    b = panel(((.1, .2),), weights=[1e308, 1e308])
    x = evaluate(a, plan(a, "environment_lower_tail_v2", coefficients))[0]
    y = evaluate(b, plan(b, "environment_lower_tail_v2", coefficients))[0]
    assert y["eligible"] and x["score"] == y["score"]
    assert x["components"] == y["components"]


def test_signed_drawdown_cannot_enter_new_economic_utility():
    values = [MetricValue("mode5.test", "decimal_return", 100, v) for v in (.12, -.1, .02)]
    with pytest.raises(ValueError, match="positive magnitude"):
        economic_utility(*values, dd_weight=.5, tail_weight=2., preference_id="dev-v1")
