"""Bounded M5D-09 software coverage, not five-alpha financial qualification."""
from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
import json
import pickle
import random

import numpy as np
import pytest

from quantbt.mode5.artifacts import file_identity, write_json
from quantbt.mode5.dossier.dossier import Dossier, radar_point
from quantbt.mode5.dossier.evidence import EvidenceCatalog, KINDS, Matrix
from quantbt.mode5.dossier.records import Record
from quantbt.mode5.dossier.researcher_report import (
    Finding, MASKS, ReportView, ResearcherReport, TITLES, VIEWS,
)
from tests.mode5.dossier_fixtures import fixture

SECRET = "PRIVATE_ALPHA_<script>alert(1)</script>|[link](private)"
PARAM = "PRIVATE_PARAMETER"
PRIVATE_NUMBER = 987654321.1234567


@pytest.fixture
def retained(tmp_path):
    _, old_catalog, kwargs = fixture(tmp_path)
    raw = old_catalog.read("registered")
    raw["cells"] = [
        {"status": "OBSERVED", "utility": .2, "params": {PARAM: PRIVATE_NUMBER}},
        {"status": "NEGATIVE", "utility": -.3, "reason": "Adverse synthetic control"},
        {"status": "NO_TRADE", "utility": None, "trades": 0, "reason": "No closed campaigns"},
        {"status": "FAILED", "utility": None, "failure": SECRET},
        {"status": "MISSING", "utility": None, "reason": "Not retained", "interpolated": False},
    ]
    raw["inventory"] = {k: [f"{SECRET}/{k}/{i}" for i in range(5)] for k in KINDS}
    path = tmp_path / "private-evidence.json"
    write_json(path, raw)
    identity = file_identity(path)
    old_source = old_catalog._sources["registered"]
    source = replace(old_source, source_id=SECRET, path=str(path),
                     sha256=identity["sha256"], bytes=identity["bytes"])
    catalog = EvidenceCatalog([source], old_catalog.policy)
    def ref(pointer):
        return catalog.ref(SECRET, pointer)

    rosters = tuple(Record.of({"kind": k, "entries": [
        {"row_id": raw["inventory"][k][i], "ref": ref(f"/cells/{i}"),
         "coverage": "PARTIAL", "interpolated": False} for i in range(5)]}) for k in KINDS)
    kwargs.update(catalog=catalog, rosters=rosters,
        matrices=tuple(Matrix.assemble(k, r, catalog) for k, r in zip(KINDS, rosters)),
        inventory=Record.of(raw["inventory"]), inventory_ref=ref("/inventory"),
        context=Record.of({**kwargs["context"].data, "alpha": SECRET}),
        compute_bill={"executed": 2, "reused": 1, "failed": 1, "missing": 1,
                      "duration_seconds": .125, "peak_rss_mib": 64.5},
        batteries={"test_id": "synthetic-only", "status": "PARTIAL", "failure": SECRET},
        limitations=["Synthetic fixture only", SECRET])
    for axis in kwargs["axes"]:
        kwargs["axes"][axis]["refs"] = [ref("/cells")]
        point = kwargs["radar"][axis][0]
        point["ref"] = ref("/cells/0/utility")
        point["definition_ref"] = ref("/definitions/" + axis)
    for assessment in kwargs["assessments"]:
        assessment["refs"] = [ref("/cells")]
        assessment["reasons"] = [SECRET, "Finite panel is not method superiority"]
    return Dossier.create(**kwargs), catalog


def finding(catalog, *, index=1, **changes):
    ref = catalog.ref(SECRET, f"/cells/{index}/utility")
    status = catalog.read(SECRET, f"/cells/{index}")["status"]
    args = dict(row_id=f"{SECRET}/finding-{index}", label=SECRET, basis="MEASURED",
        status=status, value=catalog.require_ref(ref), unit="decimal_return",
        support={"days": 91, "episodes": 2},
        uncertainty={"value": None, "reason": "Not estimated on synthetic control"},
        evidence=[ref], value_ref=ref, interpretation="Adverse within this synthetic scope",
        rival_explanation="Sparse support may dominate this comparison",
        decision_implication="No empirical recipe winner inferred",
        next_test="Register a matched control before requesting additional work",
        reason="Explicit synthetic outcome", masks=dict(evaluated=status != "MISSING",
            interpolated=False, support="SPARSE", uncertainty="NOT_ESTIMATED", coverage="PARTIAL"))
    args.update(changes)
    return Finding.create(**args)


def views(catalog):
    details = {
        "scope_test_behavior": {"requested": ["2020-01-01", "2026-10-01"],
            "actual": ["2020-02-01", "2026-09-01"], "exclusive_end": True,
            "warmup_exclusion": "Unavailable prefix; not a full 2020 study",
            "snapshot": SECRET, "roles": ["synthetic"], "partial_years": [2020, 2026],
            "test": {"purpose": "synthetic reconciliation", "design": "finite retained panel",
                     "estimator": "none", "executed": 2, "reused": 1, "missing": 1,
                     "duration_seconds": .125, "peak_rss_mib": 64.5}},
        "parameter_profile": {"dimensions": [{"name": PARAM, "value": PRIVATE_NUMBER,
            "unit": "bars", "branch": "conditional", "cast": "integer", "ignored": False}],
            "constraints": SECRET, "effect_status": "MISSING", "proposal": None},
        "parameter_regions": {"evaluated_points": [SECRET], "uncovered": ["transverse axis"],
                              "interpolation_mask": [False], "basin_claim": None},
        "environment_profile": {"annual": {"2026": {"coverage": "PARTIAL", "days": 91}},
            "trend": "NOT_RUN", "activity": "MISSING", "rank_comparison": None,
            "namespace": "full-development-descriptive", "unknown_days": 3},
        "stress_profile": {"base": SECRET, "changed_contract": {"fee": PRIVATE_NUMBER},
                           "matched": False, "ranking_change": None, "untested": ["gap"]},
        "decision_worksheet": {"sampler": SECRET, "selector": "full_dro_cvar",
            "objective": "environment_floor_mean_v1", "compatibility": "not measured",
            "trade_off": "missing geometry", "counter_evidence": "sparse support",
            "missing_experiment": "matched registered control", "cost_estimate": None},
    }
    outcomes = tuple(finding(catalog, index=i) for i in range(5))
    return tuple(ReportView(name, Record.of(details[name]), outcomes if name == "environment_profile"
                           else (finding(catalog),)) for name in VIEWS)


def test_M5D09_numbers_rows_and_views_match_retained_records(retained):
    dossier, catalog = retained
    supplied = views(catalog)
    report = ResearcherReport.read(dossier, catalog, views=supplied)
    data = report.record.data
    assert data["dossier"] == dossier.record.data
    assert data["dossier_id"] == dossier.record.identity
    assert data["summary"]["matrix_rows"] == {k: 5 for k in KINDS}
    assert data["summary"]["finding_rows"] == {k: 5 if k == "environment_profile" else 1 for k in VIEWS}
    assert data["summary"]["status_counts"] == {
        "OBSERVED": 1, "NEGATIVE": 6, "NO_TRADE": 1, "FAILED": 1, "MISSING": 1}
    for view in supplied:
        assert data["views"][view.name]["details"] == view.details.data
        assert data["views"][view.name]["findings"] == [f.record.data for f in view.findings]
    text = report.to_markdown()
    assert all("## " + title in text for title in TITLES)
    assert "AlphaQualityRiskProfile" in text and "RecipeSuitabilityProfile" in text
    assert "-0.3" in text and "0.125" in text and "64.5" in text
    assert "NO\\_TRADE" in text and "FAILED" in text and "MISSING" in text
    assert "0 / 100" not in text and "PRODUCTION_INVARIANT" not in text
    for kind in KINDS:
        matrix = data["dossier"]["matrices"][kind]
        assert [r["value"] for r in matrix["rows"]] == catalog.read(SECRET, "/cells")
    assert data["dossier"]["recommendations"]["status"] == "NO_CLEAR_WINNER"
    assert data["authority"]["automatic_routing"] is False


def test_absent_views_are_explicit_not_zero_or_positive(retained):
    dossier, catalog = retained
    report = ResearcherReport.read(dossier, catalog)
    for name in VIEWS:
        view = report.record.data["views"][name]
        assert view["details"]["status"] == "MISSING"
        row, = view["findings"]
        assert row["value"] is None and row["reason"]
        assert row["masks"]["coverage"] == "MISSING"
        assert row["masks"]["evaluated"] is False
        assert row["uncertainty"]["value"] is None and row["uncertainty"]["reason"]
        assert row["evidence"] == []
    assert report.record.data["summary"]["status_counts"] == {"MISSING": 6}
    assert "No retained findings supplied" in report.to_markdown()
    assert "-0.3" in report.to_markdown()


def test_cold_example_defaults_to_redaction_and_preserves_snapshot_and_rng(retained):
    from examples.mode5_researcher_report_cold import render_snapshot

    dossier, catalog = retained
    report = ResearcherReport.read(dossier, catalog, views=views(catalog))
    payload = report.to_json()
    rng = random.getstate()
    public = render_snapshot(payload)
    assert public == report.to_markdown(public=True)
    assert SECRET not in public and PARAM not in public
    assert str(PRIVATE_NUMBER) not in public
    assert render_snapshot(payload, private=True) == report.to_markdown()
    assert render_snapshot(payload, output_format="json") == report.to_json(public=True)
    assert report.to_json() == payload and random.getstate() == rng


def test_cold_example_requires_explicit_known_output_policy(retained):
    from examples.mode5_researcher_report_cold import render_snapshot

    dossier, catalog = retained
    payload = ResearcherReport.read(dossier, catalog).to_json()
    with pytest.raises(ValueError, match="privacy policy"):
        render_snapshot(payload, private=1)
    with pytest.raises(ValueError, match="markdown/json"):
        render_snapshot(payload, output_format="pickle")


def test_immutable_input_determinism_and_cold_roundtrip(retained):
    dossier, catalog = retained
    supplied = views(catalog)
    before = (dossier.record.payload, catalog.manifest.payload, tuple(v.details.payload for v in supplied))
    reports = [ResearcherReport.read(dossier, catalog, views=supplied) for _ in range(3)]
    report = reports[0]
    assert all(r == report and r.to_markdown() == report.to_markdown() for r in reports)
    assert ResearcherReport.from_json(report.to_json()) == report
    for clone in (deepcopy(report), pickle.loads(pickle.dumps(report))):
        raw = clone.record.data
        raw["dossier"]["matrices"]["candidate_environment"]["rows"].clear()
        raw["views"]["environment_profile"]["findings"][0]["value"] = 999
        assert clone == report
        clone.verify(catalog)
    assert before == (dossier.record.payload, catalog.manifest.payload, tuple(v.details.payload for v in supplied))
    with pytest.raises(FrozenInstanceError):
        report.record = Record.of({})
    mutable = {"days": 91}
    row = finding(catalog, support=mutable)
    mutable["days"] = 0
    assert row.record.data["support"]["days"] == 91


@pytest.mark.parametrize("mask", list(MASKS))
def test_all_required_masks_must_be_explicit(retained, mask):
    _, catalog = retained
    masks = finding(catalog).record.data["masks"]
    masks.pop(mask)
    with pytest.raises(ValueError, match="all evaluation"):
        finding(catalog, masks=masks)


@pytest.mark.parametrize("changes", [
    {"evaluated": 1}, {"interpolated": "no"}, {"coverage": "winning"},
    {"interpolated": True}, {"evaluated": False}, {"evaluated": None},
    {"uncertainty": "QUANTIFIED"}, {"secret_mask": PARAM},
])
def test_invalid_or_contradictory_masks_rejected(retained, changes):
    _, catalog = retained
    masks = {**finding(catalog).record.data["masks"], **changes}
    with pytest.raises(ValueError):
        finding(catalog, masks=masks)


@pytest.mark.parametrize("field", ["interpretation", "rival_explanation", "decision_implication", "next_test", "unit"])
def test_every_finding_requires_researcher_context(retained, field):
    _, catalog = retained
    with pytest.raises(ValueError):
        finding(catalog, **{field: " "})


@pytest.mark.parametrize("changes", [
    {"support": {}}, {"uncertainty": {"value": None, "reason": None}},
    {"value": None, "reason": None}, {"value": float("nan")},
    {"value": float("inf")}, {"evidence": []}, {"value_ref": None},
    {"basis": "ALPHA_FAMILY"}, {"status": "PRODUCTION_INVARIANT"},
])
def test_null_invalid_and_unsupported_claims_are_not_imputed(retained, changes):
    _, catalog = retained
    with pytest.raises(ValueError):
        finding(catalog, **changes)


def test_measured_source_and_hypothesis_are_distinct(retained):
    dossier, catalog = retained
    ref = catalog.ref(SECRET, "/cells/0/params")
    source = finding(catalog, row_id="source", basis="SOURCE", status="OBSERVED",
                     value=catalog.require_ref(ref), evidence=[ref], value_ref=ref)
    proposal = finding(catalog, row_id="proposal", basis="HYPOTHESIS", status="OBSERVED",
        value={"bounded_test": "No measured superiority"}, value_ref=None)
    view = ReportView("decision_worksheet", Record.of({"compatibility": "unknown"}),
                      (finding(catalog), source, proposal))
    report = ResearcherReport.read(dossier, catalog, views=(view,))
    assert report.record.data["summary"]["basis_counts"] == {"MEASURED": 1, "SOURCE": 6, "HYPOTHESIS": 1}
    assert [f["basis"] for f in report.record.data["views"][view.name]["findings"]] == ["MEASURED", "SOURCE", "HYPOTHESIS"]
    with pytest.raises(ValueError, match="not a hypothesis"):
        finding(catalog, basis="HYPOTHESIS")


@pytest.mark.parametrize("value", [77, None, False, -.30000000001])
def test_numeric_and_null_binding_must_match_exact_source(retained, value):
    dossier, catalog = retained
    wrong = finding(catalog, value=value)
    with pytest.raises(ValueError, match="differs from retained source"):
        ResearcherReport.read(dossier, catalog, views=(ReportView("parameter_profile", Record.of({}), (wrong,)),))


def test_quantified_uncertainty_and_sparse_support_are_retained_not_reduced(retained):
    dossier, catalog = retained
    uncertainty = {"value": {"lower": -.8, "upper": .1, "confidence": .9},
                   "reason": None, "method": "synthetic registered interval"}
    masks = {**finding(catalog).record.data["masks"], "uncertainty": "QUANTIFIED"}
    f = finding(catalog, uncertainty=uncertainty, masks=masks,
                status="INSUFFICIENT_SUPPORT", support={"days": 2, "unknown_days": 3})
    report = ResearcherReport.read(dossier, catalog,
        views=(ReportView("environment_profile", Record.of({"partial_year": 2026}), (f,)),))
    row, = report.record.data["views"]["environment_profile"]["findings"]
    assert row["uncertainty"] == uncertainty
    assert row["status"] == "INSUFFICIENT_SUPPORT" and row["support"]["days"] == 2
    assert "-0.8" in report.to_markdown() and "0.9" in report.to_markdown()


def test_interpolation_cannot_earn_a_measured_claim(retained):
    _, catalog = retained
    masks = {**finding(catalog).record.data["masks"], "evaluated": False, "interpolated": True}
    with pytest.raises(ValueError, match="non-interpolated evidence"):
        finding(catalog, masks=masks)
    proposal = finding(catalog, basis="HYPOTHESIS", value_ref=None, masks=masks)
    assert proposal.record.data["masks"]["interpolated"] is True
    with pytest.raises(ValueError, match="cannot be evaluated"):
        finding(catalog, index=4, masks={**masks, "interpolated": False, "evaluated": True})


def test_bool_is_not_a_numeric_zero_in_source_binding(retained):
    _, catalog = retained
    ref = catalog.ref(SECRET, "/cells/2/trades")
    wrong = finding(catalog, index=2, value=False, value_ref=ref, evidence=[ref])
    with pytest.raises(ValueError, match="differs from retained source"):
        wrong.verify(catalog)


def test_privacy_allowlist_hides_names_params_prose_paths_and_hashes(retained):
    dossier, catalog = retained
    report = ResearcherReport.read(dossier, catalog, views=views(catalog))
    source = catalog._sources[SECRET]
    public = report.public_record().data
    assert public["summary"] == report.record.data["summary"]
    assert public["dossier_id"] is None
    for text in (report.to_json(public=True), report.to_markdown(public=True)):
        for private in ("PRIVATE_ALPHA", PARAM, str(PRIVATE_NUMBER), source.path, source.sha256,
                        dossier.record.identity, "Sparse support may dominate", "Not estimated on synthetic"):
            assert private not in text
        assert "Private content redacted." in text or "REDACTED" in text
    assert public["views"]["environment_profile"]["findings"][2]["status"] == "NO_TRADE"
    assert public["views"]["environment_profile"]["findings"][2]["value"] is None
    assert report.to_json(public=True) == report.to_json(public=True)
    assert report.to_markdown(public=True) == report.to_markdown(public=True)
    with pytest.raises(ValueError, match="versioned report"):
        ResearcherReport.from_json(report.to_json(public=True))
    assert report.record.data["dossier"] == dossier.record.data


def test_private_markdown_escapes_html_and_table_breaking_text(retained):
    dossier, catalog = retained
    f = finding(catalog, label="private|column\n<script>unsafe</script> ![x](bad) `code`")
    report = ResearcherReport.read(dossier, catalog,
        views=(ReportView("parameter_regions", Record.of({"note": "a\r\nb"}), (f,)),))
    text = report.to_markdown()
    assert "<script>" not in text and "&lt;script&gt;" in text
    assert "private\\|column<br>" in text
    assert "![x](bad)" not in text and "\\`code\\`" in text
    assert "a<br>b" in text
    assert json.loads(report.to_json())["views"]["parameter_regions"]["findings"][0]["label"] == f.record.data["label"]


@pytest.mark.parametrize("change", ["count", "mask", "omit_view", "omit_matrix", "mapping", "authority", "identity", "schema"])
def test_cold_reader_rejects_structural_tamper(retained, change):
    dossier, catalog = retained
    data = ResearcherReport.read(dossier, catalog).record.data
    if change == "count":
        data["summary"]["matrix_rows"][KINDS[0]] = 0
    if change == "mask":
        data["views"][VIEWS[0]]["findings"][0]["masks"].pop("interpolated")
    if change == "omit_view":
        data["views"].pop(VIEWS[0])
    if change == "omit_matrix":
        data["dossier"]["matrices"].pop(KINDS[0])
    if change == "mapping":
        data["views"][VIEWS[0]]["matrix_kinds"] = [KINDS[0]]
    if change == "authority":
        data["authority"]["automatic_routing"] = True
    if change == "identity":
        data["dossier_id"] = "0" * 64
    if change == "schema":
        data["schema"] = "unknown"
    with pytest.raises(ValueError):
        ResearcherReport.from_json(json.dumps(data))


def test_omitted_rows_bad_refs_and_changed_current_sources_fail(retained):
    dossier, catalog = retained
    raw = dossier.record.data
    raw["matrices"][KINDS[0]]["rows"].pop()
    with pytest.raises(ValueError, match="matrix row"):
        ResearcherReport.read(Dossier(Record.of(raw)), catalog)
    ref = {**catalog.ref(SECRET, "/cells/1/utility"), "sha256": "0" * 64}
    bad = finding(catalog, evidence=[ref], value_ref=ref)
    with pytest.raises(ValueError, match="digest mismatch"):
        ResearcherReport.read(dossier, catalog, views=(ReportView(VIEWS[0], Record.of({}), (bad,)),))
    source = catalog._sources[SECRET]
    with open(source.path, "a") as stream:
        stream.write(" ")
    with pytest.raises(ValueError, match="source changed"):
        ResearcherReport.read(dossier, catalog)


def test_duplicate_views_or_findings_cannot_overwrite_evidence(retained):
    dossier, catalog = retained
    f = finding(catalog)
    with pytest.raises(ValueError, match="distinct finding"):
        ReportView(VIEWS[0], Record.of({}), (f, f))
    view = ReportView(VIEWS[0], Record.of({}), (f,))
    with pytest.raises(ValueError, match="duplicate report view"):
        ResearcherReport.read(dossier, catalog, views=(view, view))


def test_zero_finance_search_rng_and_offline_render(retained, monkeypatch):
    dossier, catalog = retained
    supplied = views(catalog)
    from quantbt.endpoint import PreparedIntrabarRunner, PreparedNativeEventStrategyRunner
    from quantbt.mode5.dossier.plans import CalibrationPlan
    from quantbt.mode5.selection import selectors

    def forbidden(*args, **kwargs):
        raise AssertionError("Report must not execute finance, search, selection or RNG")

    for owner, name in ((PreparedIntrabarRunner, "run"), (PreparedNativeEventStrategyRunner, "run"),
                        (CalibrationPlan, "search"), (selectors, "select"),
                        (random, "random"), (random, "getrandbits"), (random, "seed"),
                        (np.random, "random"), (np.random, "default_rng"), (np.random, "seed")):
        monkeypatch.setattr(owner, name, forbidden)
    python_state = random.getstate()
    numpy_state = np.random.get_state()
    report = ResearcherReport.read(dossier, catalog, views=supplied)
    report.verify(catalog)
    monkeypatch.setattr(Dossier, "verify", forbidden)
    monkeypatch.setattr(EvidenceCatalog, "verify_current", forbidden)
    monkeypatch.setattr(EvidenceCatalog, "require_ref", forbidden)
    for public in (False, True):
        assert report.to_json(public=public)
        assert report.to_markdown(public=public)
    assert ResearcherReport.from_json(report.to_json()) == report
    assert random.getstate() == python_state
    after = np.random.get_state()
    assert numpy_state[0] == after[0] and numpy_state[2:] == after[2:]
    assert np.array_equal(numpy_state[1], after[1])


def test_existing_null_radar_keeps_raw_reason_and_no_neutral_score(retained):
    dossier, catalog = retained
    raw = dossier.record.data
    axis = "geometry"
    p = raw["radar"][axis][0]
    p = radar_point(**{k: v for k, v in p.items() if k not in {
        "value", "reason", "normalized", "extrapolated", "rendering", "ref"}},
        value=None, reason="No-trade control; undefined utility", ref=catalog.ref(SECRET, "/cells/2/utility"))
    raw["radar"][axis] = [p]
    dossier = Dossier(Record.of(raw))
    report = ResearcherReport.read(dossier, catalog)
    assert report.record.data["dossier"]["radar"][axis][0]["normalized"] is None
    assert "No-trade control; undefined utility" in report.to_markdown()
    assert "null" in report.to_markdown()
