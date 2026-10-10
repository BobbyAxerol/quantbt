from copy import deepcopy
from dataclasses import replace
import json
import pickle

import pytest

from tools.mode5_diagnostics.access import AccessPolicy
from tools.mode5_dossier.records import Record
from tools.mode5_dossier.evidence import EvidenceCatalog, Source, Matrix, reconcile_rosters
from tools.mode5_dossier.dossier import Dossier, ordered_advice, invalidation, DEPENDENCIES, radar_point
from tools.mode5_dossier.plans import CalibrationPlan
from tools.mode5_dossier.governance import GovernanceLog, require_formal_chronology
from tests.mode5.dossier_fixtures import fixture, spec


def search_access():
    return AccessPolicy("selection-1", ("synthetic",), ("development-1",), 10, "selection")


def test_M5T081_unsealed_missing_deferred_and_legacy_scope(tmp_path):
    d, cat, _ = fixture(tmp_path)
    plan = CalibrationPlan.search(d, spec(d), "explicit synthetic choice")
    log = GovernanceLog(tmp_path / "journal")
    with pytest.raises(PermissionError):
        log.seal_plan(d, plan, cat, researcher="synthetic researcher", reason="not sealed")
    with pytest.raises(PermissionError):
        log.begin_search(d, plan, cat, search_access(), "trial-0")
    log.seal_dossier(d, cat)
    deferred = CalibrationPlan.defer(d, "insufficient independent evidence; no recipe chosen")
    log.seal_plan(d, deferred, cat, researcher="research assembly", reason="defer")
    with pytest.raises(PermissionError):
        log.begin_search(d, deferred, cat, search_access(), "trial-0")
    assert deferred.record.data["validation_claim"] == "none_full_sample_calibration"


def test_M5T082_human_cannot_certify_invalid_content(tmp_path):
    d, cat, kwargs = fixture(tmp_path)
    raw = d.record.data
    raw["validity"]["technical"] = "HUMAN_CERTIFIED"
    with pytest.raises(ValueError):
        GovernanceLog(tmp_path / "journal").seal_dossier(Dossier(Record.of(raw)), cat)
    matrix = kwargs["matrices"][0].record.data
    matrix["rows"][0]["value"]["utility"] = 99
    bad = Matrix(Record.of(matrix))
    with pytest.raises(ValueError):
        Dossier.create(**{**kwargs, "matrices": (bad, *kwargs["matrices"][1:])})


def test_M5T083_stable_best_low_rank_not_excluded():
    from tests.mode5.selection_fixtures import panel, plan
    from tools.mode5_selection import select
    p = panel(((.9, .9, .9), (.8, .1, .5), (.1, .8, .4), (.4, .4, .1)))
    assert select(p, plan(p)).metadata["chosen_candidate"] == "c0"
    advice = ordered_advice([dict(recipe_id="full_dro_cvar:environment_floor_mean_v1",
        status="CONSIDER_FINITE_PANEL", refs=[{"low_rank": -0.3}], reasons=["stable best observed"],
        selected_decisions=1)])
    assert advice["status"] == "NO_CLEAR_WINNER" and not advice["automatic_routing"]


@pytest.mark.parametrize("reason", ["all negative", "no closed campaigns", "wide confidence interval", "one origin"])
def test_M5T084_sparse_negative_is_not_technical_invalidity(tmp_path, reason):
    _, _, kwargs = fixture(tmp_path)
    assessments = [{**a, "status": "NO_SUPPORTED_CONFIGURATION_ON_REGISTERED_PANEL",
                    "selected_decisions": 0, "reasons": [reason]} for a in kwargs["assessments"]]
    d = Dossier.create(**{**kwargs, "assessments": assessments})
    assert d.record.data["validity"]["technical"] == "VERIFIED_SOURCE_RECONCILIATION"
    assert not d.record.data["deployment_authorized"]


def test_M5T085_omitted_adverse_rows_and_registered_roster(tmp_path):
    _, cat, kwargs = fixture(tmp_path)
    m = kwargs["matrices"][0].record.data
    m["rows"] = m["rows"][:1]
    with pytest.raises(ValueError):
        Matrix(Record.of(m)).verify(kwargs["rosters"][0], cat)
    r = kwargs["rosters"][0].data
    r["entries"] = r["entries"][:1]
    with pytest.raises(ValueError):
        reconcile_rosters((Record.of(r), *kwargs["rosters"][1:]), kwargs["inventory"])


def test_M5T086_null_reference_units_and_future_rescaling(tmp_path):
    d, cat, kwargs = fixture(tmp_path)
    old = deepcopy(d.record.data["radar"])
    point = old["geometry"][0]
    null = radar_point(**{k: v for k, v in point.items()
        if k not in {"normalized", "extrapolated", "rendering", "value", "reason"}},
        value=None, reason="not measured")
    assert null["normalized"] is None
    for field, value in (("unit", "percent"), ("upper", 2.), ("value", 3.)):
        radar = deepcopy(old)
        p = radar["geometry"][0]
        p[field] = value
        p = radar_point(**{k: v for k, v in p.items() if k not in {"normalized", "extrapolated", "rendering"}})
        radar["geometry"] = [p]
        with pytest.raises(ValueError):
            Dossier.create(**{**kwargs, "radar": radar})
    assert d.record.data["radar"] == old


def test_M5T087_override_history_unchanged_rights_budget(tmp_path):
    d, cat, _ = fixture(tmp_path)
    log = GovernanceLog(tmp_path / "journal")
    log.seal_dossier(d, cat)
    q1 = CalibrationPlan.search(d, spec(d), "floor recipe")
    q2 = CalibrationPlan.search(d, spec(d, "full_pareto_chebyshev"), "registered risk compromise")
    first = log.seal_plan(d, q1, cat, researcher="researcher", reason="first choice")
    second = log.seal_plan(d, q2, cat, researcher="researcher", reason="explicit override")
    assert second.data["payload"]["override_first_advice"]
    assert first.identity in [e.identity for e in log.history()]
    assert q1.record.data["search_budget"] == q2.record.data["search_budget"]
    with pytest.raises(PermissionError):
        log.begin_search(d, q1, cat, search_access(), "old-plan")
    log.begin_search(d, q2, cat, search_access(), "trial-0")
    altered = spec(d)
    altered["objective"]["version"] = "finite_panel_minimax_regret_v1"
    altered["objective"]["coefficients"] = {}
    with pytest.raises(ValueError):
        CalibrationPlan.search(d, altered, "unreviewed new recipe")


def test_M5T088_auto_route_denied(tmp_path):
    log = GovernanceLog(tmp_path / "journal")
    with pytest.raises(PermissionError):
        log.request_auto_route("radar winner")


@pytest.mark.parametrize("changed", DEPENDENCIES)
def test_M5T089_dependency_partial_reuse(tmp_path, changed):
    d, _, _ = fixture(tmp_path)
    old = Record.of(d.record.data["context"])
    new = Record.of({**old.data, changed: "revision-2"})
    result = invalidation(old, new)
    assert result["changed"] == [changed] and not result["plan_reusable"]
    assert result["execution_reusable"] == (changed not in {"alpha", "data", "economics", "schema", "scope"})
    assert result["reuse_requires_fresh_access_check"]
    assert invalidation(old, Record.of(old.data))["dossier_reusable"]


def test_M5T090_posthoc_clock_and_backdated_history(tmp_path):
    d, cat, _ = fixture(tmp_path)
    q = CalibrationPlan.search(d, spec(d), "explicit choice")
    log = GovernanceLog(tmp_path / "journal")
    a = log.seal_dossier(d, cat)
    b = log.seal_plan(d, q, cat, researcher="researcher", reason="approved")
    c = log.begin_search(d, q, cat, search_access(), "trial-0")
    assert a.data["sealed_at_ns"] < b.data["sealed_at_ns"] < c.data["sealed_at_ns"]
    with pytest.raises(PermissionError):
        log.seal_plan(d, q, cat, researcher="researcher", reason="cannot backfill")
    path = log.directory / "000001.json"
    data = json.loads(path.read_text())
    data["event"]["sealed_at_ns"] = 1
    # Mechanical tamper fixture only; phase evidence is never edited.
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        log.history()


@pytest.mark.parametrize("copy", [deepcopy, lambda x: pickle.loads(pickle.dumps(x))])
def test_immutable_copy_pickle_metadata(copy, tmp_path):
    d, cat, _ = fixture(tmp_path)
    cloned = copy(d)
    raw = cloned.record.data
    raw["matrices"]["candidate_environment"]["rows"][0]["value"]["utility"] = 99
    assert cloned == d and cloned.record.identity == d.record.identity
    cloned.verify(cat)
    q = CalibrationPlan.defer(d, "not approved")
    assert copy(q) == q


def test_json_roundtrip_and_no_nonfinite(tmp_path):
    d, cat, _ = fixture(tmp_path)
    Dossier(Record.of(json.loads(d.record.payload))).verify(cat)
    with pytest.raises(ValueError):
        Record.of({"bad": float("nan")})


@pytest.mark.parametrize("change", ["future", "holdout", "tamper", "wrong_ref"])
def test_source_maturity_access_tamper(tmp_path, change):
    _, cat, _ = fixture(tmp_path)
    source = cat._sources["registered"]
    if change == "future":
        source = replace(source, witness=replace(source.witness, ready_ns=11))
    if change == "holdout":
        source = replace(source, witness=replace(source.witness, role="holdout"))
    if change == "tamper":
        source = replace(source, sha256="0"*64)
    if change == "wrong_ref":
        ref = {**cat.ref("registered"), "sha256": "0"*64}
        with pytest.raises(ValueError):
            cat.require_ref(ref)
        return
    with pytest.raises((ValueError, PermissionError)):
        EvidenceCatalog([source], cat.policy)


@pytest.mark.parametrize("field", ["sampler", "objective", "selector", "domain", "probes", "constraints",
                                  "support", "validation", "incumbent", "retention", "reuse", "failure"])
def test_recipe_fields_cannot_be_implicit(tmp_path, field):
    d, _, _ = fixture(tmp_path)
    data = spec(d)
    data.pop(field)
    with pytest.raises(ValueError):
        CalibrationPlan.search(d, data, "not complete")


def test_independent_inventory_cannot_be_replaced(tmp_path):
    d, cat, _ = fixture(tmp_path)
    raw = d.record.data
    matrix = raw["matrices"]["candidate_environment"]
    matrix["rows"] = matrix["rows"][:1]
    matrix["roster"]["entries"] = matrix["roster"]["entries"][:1]
    with pytest.raises(ValueError):
        Dossier(Record.of(raw)).verify(cat)


def test_source_changes_after_load_are_denied_at_seal(tmp_path):
    d, cat, _ = fixture(tmp_path)
    source = tmp_path / "source.json"
    source.write_text('{"changed": true}')
    with pytest.raises(ValueError):
        GovernanceLog(tmp_path / "journal").seal_dossier(d, cat)


def test_catalog_returned_values_do_not_mutate_snapshot(tmp_path):
    _, cat, _ = fixture(tmp_path)
    value = cat.read("registered", "/cells")
    value[0]["utility"] = 99
    assert cat.read("registered", "/cells/0/utility") == .2


@pytest.mark.parametrize("change", ["channel", "reference", "schema", "budget", "deploy", "rng", "rights"])
def test_search_contract_overrides_cannot_bypass_gates(tmp_path, change):
    d, cat, _ = fixture(tmp_path)
    data = spec(d)
    if change == "channel": data["objective"]["channel"]["unit"] = "percent"
    if change == "reference": data["objective"]["reference_id"] = "future-autoscale"
    if change == "schema": data["domain"]["schema_id"] = "changed-schema"
    if change == "budget": data["search_budget"] = 0
    if change == "deploy": data["validation"]["no_auto_deploy"] = False
    if change == "rng": data["sampler"]["seeds"] = []
    if change == "rights": data["reuse"]["selection_policy"]["roles"] = ["holdout"]
    with pytest.raises(ValueError):
        CalibrationPlan.search(d, data, "cannot override scientific gate")


def test_governance_reload_preserves_exact_history_and_rights(tmp_path):
    d, cat, _ = fixture(tmp_path)
    q = CalibrationPlan.search(d, spec(d), "registered choice")
    log = GovernanceLog(tmp_path / "journal")
    log.seal_dossier(d, cat)
    log.seal_plan(d, q, cat, researcher="researcher", reason="approved")
    reloaded = GovernanceLog(log.directory)
    assert reloaded.history() == log.history()
    with pytest.raises(PermissionError):
        reloaded.begin_search(d, q, cat, replace(search_access(), cutoff_ns=8), "trial-0")


def test_external_formal_trial_before_profile_is_not_backfilled(tmp_path):
    d, cat, _ = fixture(tmp_path)
    q = CalibrationPlan.search(d, spec(d), "synthetic formal choice")
    log = GovernanceLog(tmp_path / "journal")
    dseal = log.seal_dossier(d, cat)
    qseal = log.seal_plan(d, q, cat, researcher="researcher", reason="approved")
    for first_trial in (1, dseal.data["sealed_at_ns"], qseal.data["sealed_at_ns"]):
        with pytest.raises(PermissionError):
            require_formal_chronology(log, d.record.identity, q.record.identity, first_trial)
    result = require_formal_chronology(log, d.record.identity, q.record.identity, qseal.data["sealed_at_ns"]+1)
    assert result.data["status"] == "PRE_SEARCH_ORDER_VERIFIED"


def test_null_measures_are_supported_without_neutral_imputation(tmp_path):
    d, cat, kwargs = fixture(tmp_path)
    raw = cat.read("registered")
    raw["cells"][0]["utility"] = None
    from tools.mode5_baseline.isolation import file_identity, write_json
    path = tmp_path / "source-null.json"
    write_json(path, raw)
    source = cat._sources["registered"]
    identity = file_identity(path)
    new_cat = EvidenceCatalog([replace(source, path=str(path), sha256=identity["sha256"], bytes=identity["bytes"])], cat.policy)
    for axis, points in kwargs["radar"].items():
        point = points[0]
        point["ref"] = new_cat.ref("registered", "/cells/0/utility")
        point["definition_ref"] = new_cat.ref("registered", "/definitions/"+axis)
        kwargs["radar"][axis] = [radar_point(**{k: v for k, v in point.items()
            if k not in {"normalized", "extrapolated", "rendering", "value", "reason"}}, value=None, reason="no-trade control")]
    # New dependencies and rosters are required, not a stale old dossier seal.
    assert all(p["normalized"] is None for points in kwargs["radar"].values() for p in points)
    with pytest.raises(ValueError):
        d.verify(new_cat)
