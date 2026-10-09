from copy import deepcopy
from dataclasses import replace
import pickle

import numpy as np
import pytest

from tools.mode5_diagnostics.identity import digest
from tools.mode5_geometry import EffectiveGeometry, active_neighbors, representative
from tools.mode5_selection import AdvisoryDossier, ParetoPreference, Probe, evaluate, select
from tools.mode5_selection.geometry import from_geometry
from tools.mode5_selection.pareto import nondominated
from tests.mode5.selection_fixtures import panel, plan
from tests.mode5.test_selection_objectives import local_plan
from tests.mode5 import selection_oracle as oracle


def preference(p, *, ideal=None, worst=None, directions=None, weights=None, extrapolation="allow_and_report_v1"):
    n = len(p.reference.values)
    return ParetoPreference("dev-bounds-1", p.reference.environment_ids, p.channel.identity,
        tuple(ideal or [1.]*n), tuple(worst or [0.]*n), tuple(directions or [1]*n), tuple(weights or [1.]*n), extrapolation)


def pareto_plan(p, pref, **kwargs):
    return plan(p, "pareto_chebyshev_v1", (("rho", .01),), "full_pareto_chebyshev",
                pareto_preference_identity=pref.identity, **kwargs)


def test_M5T068_directions_missing_zero_range_and_dominated_outlier():
    p = panel(((.9, .5, 4.), (.7, .8, 4.), (.1, .9, 9.), (None, .1, 4.)))
    pref = preference(p, ideal=[1, 0, 4], worst=[0, 1, 4], directions=[1, -1, 1])
    d = select(p, pareto_plan(p, pref), pareto_preference=pref).metadata
    assert d["pareto_candidate_ids"] == ["c0"]
    assert d["chosen_candidate"] == "c0"
    assert d["component_rows"][3]["score"] is None
    assert d["component_rows"][0]["components"]["non_discriminative"] == [False, False, True]
    assert d["component_rows"][2]["components"]["extrapolated"] == [False, False, True]
    assert select(replace(p, candidates=p.candidates[:2]), pareto_plan(p, pref), pareto_preference=pref).metadata["chosen_candidate"] == "c0"


def test_frozen_pareto_references_not_renormalized_by_outlier():
    p = panel(((.8, .4), (.5, .8), (-500., -900.)))
    pref = preference(p)
    d = select(p, pareto_plan(p, pref), pareto_preference=pref)
    smaller = select(replace(p, candidates=p.candidates[:2]), pareto_plan(p, pref), pareto_preference=pref)
    assert d.metadata["chosen_candidate"] == smaller.metadata["chosen_candidate"]
    assert d.metadata["component_rows"][:2] == smaller.metadata["component_rows"]
    with pytest.raises(ValueError):
        select(p, pareto_plan(p, pref), pareto_preference=replace(pref, ideal=(2., 2.)))


def test_extrapolation_policy_and_zero_range_no_division():
    p = panel(((1.2, .9), (.5, .5)))
    allowed = preference(p)
    rejected = preference(p, extrapolation="reject_v1")
    assert select(p, pareto_plan(p, allowed), pareto_preference=allowed).metadata["chosen_candidate"] == "c0"
    d = select(p, pareto_plan(p, rejected), pareto_preference=rejected).metadata
    assert d["chosen_candidate"] == "c1"
    assert d["component_rows"][0]["reasons"] == ["REFERENCE_EXTRAPOLATION"]
    zero = preference(p, ideal=[.5, .5], worst=[.5, .5])
    assert select(p, pareto_plan(p, zero), pareto_preference=zero).metadata["chosen_candidate"] == "c0"


@pytest.mark.parametrize("directions", [(1, 1, 1), (-1, 1, -1), (-1, -1, -1)])
def test_numpy_front_chebyshev_against_scalar_oracle(directions):
    matrix = np.random.default_rng(731).uniform(-.2, 1.2, (51, 3))
    assert nondominated(matrix, directions) == tuple(oracle.nondominated(matrix.tolist(), directions))
    ideal = tuple(1. if d == 1 else 0. for d in directions)
    worst = tuple(0. if d == 1 else 1. for d in directions)
    weights = (.7, 1.1, 1.3)
    p = panel(tuple(tuple(r) for r in matrix))
    pref = preference(p, ideal=ideal, worst=worst, directions=directions, weights=weights)
    rows = select(p, pareto_plan(p, pref), pareto_preference=pref).metadata["component_rows"]
    for row, values in zip(rows, matrix, strict=True):
        expected = oracle.chebyshev(values, ideal, worst, directions, weights, .01)
        assert -row["score"] == pytest.approx(expected, abs=1e-12)


def test_M5T069_generation_not_relabelled_by_pareto_selector():
    p = panel(((.8, .4), (.5, .8)))
    pref = preference(p)
    d = select(p, pareto_plan(p, pref), pareto_preference=pref).metadata
    assert d["candidate_generation"] == "qmc"
    assert d["selector_algorithm"] == "pareto_post_selection_chebyshev"
    assert d["front_metric_claim"] == "not_selected_point_performance"
    evolutionary = replace(p, generation="nsga_ii", generation_evidence="actual-evolutionary-run-receipt")
    assert select(evolutionary, pareto_plan(evolutionary, pref), pareto_preference=pref).metadata["candidate_generation"] == "nsga_ii"


def test_pareto_gates_apply_before_nondomination():
    p = panel(((.8, .4), (.5, .8), (1., 1.)))
    p = replace(p, candidates=(*p.candidates[:2], replace(p.candidates[2], risk_pass=False)))
    pref = preference(p)
    d = select(p, pareto_plan(p, pref), pareto_preference=pref).metadata
    assert d["pareto_candidate_ids"] == ["c0", "c1"]
    assert d["chosen_candidate"] != "c2"


def test_M5T070_medoid_nearest_mean_and_unexecuted_centroid():
    g = EffectiveGeometry.from_ranges({"x": (0., 100.)})
    points = tuple(g.resolve(dict(x=x)) for x in (0., 1., 2., 3., 100.))
    medoid = representative(g, points, kind="medoid")
    centroid = representative(g, points, kind="centroid")
    assert medoid["point"].params["x"] == 2.
    assert min(points, key=lambda p: abs(p.params["x"]-21.2)).params["x"] == 3.
    assert centroid["actual_evaluation_required"] and centroid["point"].params["x"] == pytest.approx(21.2)
    p = panel(((.2, .2), (.9, .9)), ids=["medoid", "new-centroid"])
    p = replace(p, candidates=(replace(p.candidates[0], representative_kind="medoid"),
        replace(p.candidates[1], representative_kind="centroid", evaluated=False)))
    assert select(p, plan(p)).metadata["chosen_candidate"] == "medoid"


def dossier(p, q, *, recipes=None):
    return AdvisoryDossier("mode5.advisory.v1", "synthetic-dossier", p.context_id,
        ("synthetic-battery-support",), tuple(recipes or [("full_dro_cvar", q.formula.identity)]), p.candidates[0].witnesses[0])


def test_adaptive_advisory_needs_explicit_researcher_decision():
    p = panel()
    q = replace(plan(p), requested_selector="full_alpha_adaptive_invariant")
    record = dossier(p, q)
    pending = select(p, q, dossier=record).metadata
    assert pending["reason"] == "RESEARCHER_DECISION_REQUIRED"
    assert not pending["deployment_authorized"]
    actual = select(p, q, dossier=record, researcher_choice="full_dro_cvar", override_reason="registered reference choice").metadata
    assert actual["resolved_selector"] == "full_dro_cvar"
    assert actual["advisory"]["routing_evidence_status"] == "ADVISORY_ONLY"
    assert actual["chosen_candidate"] == select(p, plan(p)).metadata["chosen_candidate"]


def test_adaptive_override_audited_no_alpha_name_or_radar_input():
    p = panel()
    q = replace(plan(p), requested_selector="full_alpha_adaptive_invariant")
    record = dossier(p, q, recipes=[("full_sam_basin", "unselected-formula"), ("full_dro_cvar", q.formula.identity)])
    d = select(p, q, dossier=record, researcher_choice="full_dro_cvar", override_reason="researcher-reviewed floor mandate")
    assert d.metadata["advisory"]["overrode_first_advice"]
    with pytest.raises(ValueError):
        select(p, q, dossier=record, researcher_choice="full_dro_cvar")
    with pytest.raises(ValueError):
        select(p, q, dossier=record, researcher_choice="full_sam_basin", override_reason="not that formula")
    with pytest.raises(ValueError):
        replace(record, routing_evidence_status="AUTO_FROM_ALPHA_LABEL")


def test_advisory_context_and_temporal_access_not_bypassed():
    p = panel()
    q = replace(plan(p), requested_selector="full_alpha_adaptive_invariant")
    record = dossier(p, q)
    with pytest.raises(ValueError):
        select(p, q, dossier=replace(record, context_id="other-alpha-economics"))
    for witness in (replace(record.witness, ready_ns=11), replace(record.witness, role="holdout")):
        with pytest.raises(PermissionError):
            select(p, q, dossier=replace(record, witness=witness))
    assert select(p, q, dossier=record).identity == select(p, q, dossier=record).identity


def test_advisory_identity_is_part_of_selection_key_not_only_text():
    p = panel()
    q = replace(plan(p), requested_selector="full_alpha_adaptive_invariant")
    record = dossier(p, q)
    a = select(p, q, dossier=record, researcher_choice="full_dro_cvar", override_reason="choice")
    b = select(p, q, dossier=replace(record, dossier_id="revision-2"), researcher_choice="full_dro_cvar", override_reason="choice")
    assert a.identity != b.identity
    assert a.metadata["selection_key"] != b.metadata["selection_key"]


def test_geometry_bridge_reuses_schema_union_probes_and_shared_downside():
    g = EffectiveGeometry.from_ranges({"x": (-1., 1.), "y": (-.5, .5)})
    center = g.resolve(dict(x=0., y=0.))
    cloud = tuple(g.resolve(dict(x=x, y=0.)) for x in np.linspace(-.1, .1, 7))
    neighbors = active_neighbors(g, center, radius=.01, minimum_radius=.005, seed=1731, role="selection_probe", cloud=cloud)
    p = panel(((1., 1.),))
    c = p.candidates[0]
    results = {r.point.identity: Probe(r.point.identity, 1-r.point.params["x"]**2-10000*r.point.params["y"]**2,
        "COMPLETE", c.analyses[0], c.witnesses[0]) for r in neighbors.rows if r.status == "READY"}
    e = from_geometry(p, c, neighbors, results, reference_id="local-dev-IQR", reference_scale=.5, validation_ref="held-proof")
    assert e.covariance_status == "SCHEMA_ONLY_INSUFFICIENT"
    d = select(p, local_plan(p), local_evidence=(e,)).metadata
    assert d["component_rows"][0]["components"]["fragility"] == pytest.approx(1.)
    assert d["component_rows"][0]["score"] == pytest.approx(0.)
    with pytest.raises(ValueError):
        from_geometry(p, c, replace(neighbors, role="local_validation"), results,
                      reference_id="local-dev-IQR", reference_scale=.5, validation_ref="held-proof")


def test_decision_pickle_components_and_source_inputs_immutable():
    p = panel()
    d = select(p, plan(p))
    for copy in (deepcopy(d), pickle.loads(pickle.dumps(d))):
        assert copy.identity == d.identity
        copy.metadata["chosen_candidate"] = "fake"
        assert copy.identity == d.identity


def test_fingerprint_reuse_all_slots_byte_identical_to_uncached_reference(monkeypatch):
    from tools.mode5_selection.contracts import Channel, Decision, Formula, LocalEvidence, Panel, SelectionPlan
    from tools.mode5_selection.migration import StageLedger
    from tools.mode5_statistics.tails import FrozenReference
    from tests.mode5.test_selection_objectives import local
    p = panel()
    q = plan(p)
    ls = tuple(local(p, c, (.1, .2)) for c in p.candidates)
    lp = local_plan(p)
    pp = preference(p)
    pq = pareto_plan(p, pp)
    aq = replace(q, requested_selector="full_alpha_adaptive_invariant")
    record = dossier(p, aq)
    functions = (lambda: select(p, q), lambda: select(p, lp, local_evidence=ls),
        lambda: select(p, pq, pareto_preference=pp), lambda: select(p, aq, dossier=record,
            researcher_choice="full_dro_cvar", override_reason="fixed comparison"))
    before = tuple((f().metadata_json, f().identity) for f in functions)
    with monkeypatch.context() as patch:
        for cls in (Channel, Decision, Formula, LocalEvidence, Panel, SelectionPlan,
                    StageLedger, AdvisoryDossier, ParetoPreference, FrozenReference):
            patch.setattr(cls, "identity", property(cls.__dict__["identity"].func))
        after = tuple((f().metadata_json, f().identity) for f in functions)
    assert before == after


@pytest.mark.parametrize("resolved", ["full_sam_basin", "full_pareto_chebyshev"])
def test_adaptive_resolves_other_explicit_qualified_slots(resolved):
    from tests.mode5.test_selection_objectives import local
    p = panel()
    pref = preference(p)
    ls = tuple(local(p, c, (.1, .2)) for c in p.candidates)
    q = local_plan(p) if resolved == "full_sam_basin" else pareto_plan(p, pref)
    aq = replace(q, requested_selector="full_alpha_adaptive_invariant")
    record = dossier(p, aq, recipes=[(resolved, q.formula.identity)])
    kwargs = dict(local_evidence=ls) if resolved == "full_sam_basin" else dict(pareto_preference=pref)
    a = select(p, q, **kwargs).metadata
    b = select(p, aq, dossier=record, researcher_choice=resolved, override_reason="predeclared choice", **kwargs).metadata
    assert a["chosen_candidate"] == b["chosen_candidate"]
    assert a["plan_identity"] != b["plan_identity"]
    for x, y in zip(a["component_rows"], b["component_rows"], strict=True):
        assert {k: v for k, v in x.items() if k != "plan_identity"} == {k: v for k, v in y.items() if k != "plan_identity"}
