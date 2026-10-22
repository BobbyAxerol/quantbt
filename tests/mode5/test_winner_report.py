"""Pure winner-report controls: retained metadata only, never financial runs."""

from copy import copy, deepcopy
from dataclasses import FrozenInstanceError, asdict, replace
import html
import json
from pathlib import Path
import pickle
import random
import runpy

import numpy as np
import pytest

from quantbt import QuantBTEndpoint
from quantbt.core.results import BacktestResultV2, BacktestScalarScoreResult, NativeEventScoreResult
from quantbt.core.types import BacktestResult
from quantbt.diagnostics import AccessPolicy, AccessWitness, ResearchDecisionReport
from quantbt.diagnostics.winner import (
    WinnerBaseline, WinnerEvidence, WinnerQualificationReport, WinnerQualificationRequest, winner_subject,
)
from quantbt.mode5.artifacts import file_identity, write_json
from quantbt.mode5.decision_report import DecisionReport
from quantbt.mode5.diagnostics.identity import digest
from quantbt.mode5.dossier.evidence import EvidenceCatalog, Source
from quantbt.mode5.dossier.records import Record
from test_decision_report import SECRET, runtime_metadata

PRIVATE_SOURCE = "PRIVATE-WINNER-<script>alert(1)</script>|source"


def metadata(*, tied=False, **options):
    value, params = runtime_metadata(continuous=True, **options)
    rows = value["trial_ledger"]
    for i, row in enumerate(rows[:4]):
        for j, observation in enumerate(row["observations"]):
            observation["metric_contract"] = f"original-annual-contract-{j}"
        whole = row["whole_observation"]
        whole.update(environment_id="whole_path", account_policy="CONTINUOUS_PATH_ATTRIBUTION",
            start_ns=10, stop_ns=20, metric_contract="original-whole-contract", initial_capital=100.,
            raw_sharpe=(2., 1., 99., None)[i], net_return=(.30, .10, .90, None)[i],
            max_drawdown=(.40, .10, .80, None)[i], daily_loss_es=(.10, .03, .30, None)[i],
            final_equity=(130., 110., 190., 100.)[i], closed_records=(12, 4, 30, 0)[i])
        row["raw_sharpe"] = row["raw_whole_sharpe"] = whole["raw_sharpe"]
    if tied:
        # Identical utility observations give an exact objective tie. Keep the
        # original lexicographic rule, component evidence and selected audit.
        first, second = rows[:2]
        for a, b in zip(first["observations"], second["observations"], strict=True):
            a["utility"] = deepcopy(b["utility"])
        first["objective"] = second["objective"]
        for key in ("score", "components"):
            first["components"][key] = deepcopy(second["components"][key])
        choice = value["decision"]
        component = next(r for r in choice["component_rows"] if r["candidate_id"] == first["candidate_id"])
        for key in ("score", "components"):
            component[key] = deepcopy(second["components"][key])
        evidence = {r["candidate_id"]: r for r in choice["evidence_refs"]}
        for key in ("environment_values", "environment_statuses", "environment_null_reasons", "environment_sample_counts"):
            evidence[first["candidate_id"]][key] = deepcopy(evidence[second["candidate_id"]][key])
        chosen = min(first["candidate_id"], second["candidate_id"])
        choice.update(chosen_candidate=chosen, chosen_params_digest=chosen,
            pre_incumbent_candidate=chosen, post_incumbent_candidate=chosen,
            component_hash=digest(choice["component_rows"]))
        value["selection_decision_id"] = digest(choice)
        value["selected_params_digest"] = chosen
        value["sampler"]["rows"][0]["objective"] = [first["objective"]]
        params = deepcopy(next(r["effective_params"] for r in rows[:2] if r["candidate_id"] == chosen))
    for row in rows[:4]:
        row["evaluation_ref"] = digest(row["observations"])
    rows[4]["evaluation_ref"] = rows[1]["evaluation_ref"]
    if params is not None:
        chosen = value["decision"]["chosen_candidate"]
        value["selected_audit"] = deepcopy(next(r["observations"] for r in rows[:4] if r["candidate_id"] == chosen))
    return value, params


@pytest.fixture
def retained():
    value, params = metadata()
    witness = AccessWitness("run", "synthetic", 10, 20, 30)
    access = AccessPolicy("winner-review", ("synthetic",), ("run", "evidence"), 40, "diagnostic")
    return dict(metadata=value, params=params, decision=DecisionReport.read(value, selected_params=params),
        kwargs=dict(access=access, witness=witness, source_ref=PRIVATE_SOURCE))


def build(retained, request=None):
    return WinnerQualificationReport.build(retained["decision"], **retained["kwargs"],
        request=WinnerQualificationRequest(include_account=False) if request is None else request)


def measurements(comparison):
    return {row["metric"]: row for row in comparison["whole"]}


def evidence_value(decision, *, kind="local_probes"):
    subject = winner_subject(decision)
    design = dict(center_candidate_id=subject["candidate_id"], role="held_validation_probes",
        requested_radius=.1, observed_radius=.05)
    support = dict(expected_probes=3, observed_probes=2)
    if kind == "execution_stress":
        design = dict(center_candidate_id=subject["candidate_id"], execution_ref="original-execution", scenario="fee_x2")
        support = dict(expected_scenarios=1, observed_scenarios=1)
    return dict(schema="quantbt.mode5.winner_evidence.v1", subject=subject, kind=kind,
        measurements=[dict(metric="retained.net_return", unit="decimal_return", value=.08, sample_count=2, reason=None),
                      dict(metric="unmeasured.tail", unit="decimal_return", value=None, sample_count=0,
                           reason="Not retained in this synthetic control")],
        support=support, design=design, limitations=[PRIVATE_SOURCE, "Finite synthetic scope; no basin certificate"])


def catalog_for(tmp_path, retained, *, values=None, witness=None):
    values = values if values is not None else [evidence_value(retained["decision"])]
    witness = witness or AccessWitness("evidence", "synthetic", 10, 20, 30)
    path = tmp_path / "winner-checks.json"
    write_json(path, dict(checks=values, private_source=PRIVATE_SOURCE))
    pin = file_identity(path)
    policy = AccessPolicy("source-creation", (witness.role,), (witness.manifest_id,), max(40, witness.ready_ns), "diagnostic")
    catalog = EvidenceCatalog((Source("winner-checks", str(path), pin["sha256"], pin["bytes"], witness),), policy)
    refs = tuple(WinnerEvidence.at(catalog.ref("winner-checks", f"/checks/{i}")) for i in range(len(values)))
    request = WinnerQualificationRequest(include_account=False, catalog=catalog, evidence=refs)
    return catalog, request, path


def test_numeric_runnerup_and_raw_best_expose_return_risk_and_activity_tradeoffs(retained):
    report = build(retained)
    data = report.to_dict(private=True)
    comparisons = {r["name"]: r for r in data["explanation"]["comparisons"]}
    runner = comparisons["recorded_score_runner_up"]
    raw = comparisons["same_pool_eligible_raw_sharpe_best"]
    assert runner["candidate_id"] == raw["candidate_id"] == retained["metadata"]["trial_ledger"][0]["candidate_id"]
    # The declared floor + .25 * mean objective: .075 - (-.275) = .35.
    assert runner["objective_delta"] == pytest.approx(.35)
    whole = measurements(runner)
    assert whole["raw_sharpe"]["delta"] == -1.
    assert whole["net_return"]["delta"] == pytest.approx(-.2)
    assert whole["max_drawdown"]["delta"] == pytest.approx(-.3)
    assert whole["daily_loss_es"]["delta"] == pytest.approx(-.07)
    assert whole["final_equity"]["delta"] == -20.
    assert whole["closed_records"]["delta"] == -8
    assert whole["closed_records"]["unit"] == "engine_closed_records"
    assert len(runner["annual"]) == 2 and runner["components"]["winner"]
    assert data["explanation"]["sampler_effect"] == "NOT_IDENTIFIED"
    assert data["explanation"]["risk_allocation_effect"] == "NOT_IDENTIFIED"
    assert data["account"]["status"] == "NOT_SUPPLIED"
    assert data["subject"] == winner_subject(retained["decision"])
    annual = data["annual_summary"]
    assert annual["environments"] == 2 and annual["independent_replications"] is None
    assert annual["measures"]["net_return"]["minimum"] == .05
    assert annual["measures"]["net_return"]["maximum"] == .15


def test_missing_and_mismatched_metric_contracts_never_make_numeric_deltas(retained):
    for contract in (None, "another-contract"):
        value, params = metadata()
        value["trial_ledger"][0]["whole_observation"]["metric_contract"] = contract
        if contract is None:
            value["trial_ledger"][1]["whole_observation"].pop("metric_contract")
            value["trial_ledger"][0]["whole_observation"].pop("metric_contract")
        decision = DecisionReport.read(value, selected_params=params)
        report = WinnerQualificationReport.build(decision, **retained["kwargs"],
            request=WinnerQualificationRequest(include_account=False))
        for comparison in report.to_dict(private=True)["explanation"]["comparisons"]:
            assert all(row["delta"] is None and row["reason"] for row in comparison["whole"])


def test_incumbent_guard_explains_actual_post_guard_winner_without_reranking(retained):
    value, params = metadata(incumbent=True)
    decision = DecisionReport.read(value, selected_params=params)
    report = WinnerQualificationReport.build(decision, **retained["kwargs"], request=WinnerQualificationRequest(include_account=False))
    data = report.to_dict(private=True)
    choice = data["explanation"]["original_decision"]
    assert choice["incumbent_guard"] == "INCUMBENT_RETAINED_BY_DECLARED_MARGIN"
    assert choice["pre_incumbent_candidate"] != choice["chosen_candidate"]
    assert data["subject"]["candidate_id"] == choice["post_incumbent_candidate"]
    runner, raw = data["explanation"]["comparisons"]
    assert runner["candidate_id"] == choice["pre_incumbent_candidate"]
    assert runner["objective_delta"] == pytest.approx(-.35)
    assert raw["same_candidate"] is True and raw["objective_delta"] == 0.


def test_objective_ties_keep_original_lexicographic_winner(retained):
    value, params = metadata(tied=True)
    decision = DecisionReport.read(value, selected_params=params)
    report = WinnerQualificationReport.build(decision, **retained["kwargs"], request=WinnerQualificationRequest(include_account=False))
    data = report.to_dict(private=True)
    assert data["subject"]["candidate_id"] == min(r["candidate_id"] for r in value["trial_ledger"][:2])
    assert data["explanation"]["original_decision"]["tie_break"] == "candidate_id_lexicographic_v1"
    assert data["explanation"]["comparisons"][0]["objective_delta"] == 0.


def test_no_selection_retains_original_gates_without_fabricating_a_subject(retained):
    value, _ = metadata(no_selection=True)
    decision = DecisionReport.read(value)
    report = WinnerQualificationReport.build(decision, **retained["kwargs"], request=WinnerQualificationRequest(include_account=False))
    data = report.to_dict(private=True)
    assert data["subject"] is None and data["explanation"]["status"] == "NO_SELECTION"
    assert data["explanation"]["comparisons"] == []
    assert data["explanation"]["original_decision"] == decision.record.data["runtime"]["decision"]
    assert data["annual_summary"]["status"] == "NO_SELECTION"
    assert all(r["status"] == "NOT_SUPPLIED" for r in data["coverage"])
    assert report.to_markdown() and report.to_markdown(private=True)
    with pytest.raises(ValueError, match="NO_SELECTION"):
        winner_subject(decision)


def test_predecision_failure_has_no_phantom_decision_or_keyerror(retained):
    value, _ = runtime_metadata(continuous=True, no_selection=True)
    value.pop("decision")
    value.pop("selection_decision_id")
    value["trial_ledger"] = []
    value["sampler"].update(rows=[], attempts=0, states={}, duplicate_attempts=0)
    decision = DecisionReport.read(value)
    report = WinnerQualificationReport.build(decision, **retained["kwargs"], request=WinnerQualificationRequest(include_account=False))
    assert report.to_dict(private=True)["subject"] is None
    assert report.to_dict(private=True)["explanation"]["comparisons"] == []
    assert report.to_dict(private=True)["explanation"]["original_decision"] is None


def test_exact_winner_checks_keep_source_scope_support_and_missing_values(retained, tmp_path):
    values = [evidence_value(retained["decision"]), evidence_value(retained["decision"], kind="execution_stress")]
    catalog, request, _ = catalog_for(tmp_path, retained, values=values)
    report = build(retained, request)
    data = report.to_dict(private=True)
    assert len(data["checks"]) == 2
    for check, expected in zip(data["checks"], values, strict=True):
        assert check["evidence"] == expected and check["basin_certified"] is False
        assert check["source_witness"]["manifest_id"] == "evidence"
        assert check["ref"]["sha256"] == catalog.manifest.data["sources"][0]["sha256"]
        assert check["evidence"]["measurements"][1]["value"] is None
    coverage = {r["section"]: r for r in data["coverage"]}
    assert coverage["local_probes"]["status"] == coverage["execution_stress"]["status"] == "RECORDED"
    assert coverage["activity_exposure"]["status"] == coverage["regime"]["status"] == "NOT_SUPPLIED"


@pytest.mark.parametrize("field", ("candidate_id", "params_digest", "decision_id", "dossier_id", "plan_id",
    "binding_id", "whole_observation_id", "annual_observations_id", "account_scope"))
def test_another_candidate_run_scope_or_original_observation_cannot_certify_winner(retained, tmp_path, field):
    value = evidence_value(retained["decision"])
    value["subject"][field] = "mismatched-original-subject"
    _, request, _ = catalog_for(tmp_path, retained, values=[value])
    with pytest.raises(ValueError, match="subject"):
        build(retained, request)


@pytest.mark.parametrize("change", ("center", "role", "budget", "radius", "measurement", "unit", "sample_count", "missing_reason"))
def test_invalid_design_or_measurement_is_not_promoted(retained, tmp_path, change):
    value = evidence_value(retained["decision"])
    if change == "center":
        value["design"]["center_candidate_id"] = "another-center"
    elif change == "role":
        value["design"]["role"] = "undeclared-fit"
    elif change == "budget":
        value["support"]["observed_probes"] = 4
    elif change == "radius":
        value["design"]["observed_radius"] = -1.
    elif change == "measurement":
        value["measurements"][0]["value"] = True
    elif change == "unit":
        value["measurements"][0]["unit"] = ""
    elif change == "sample_count":
        value["measurements"][0]["sample_count"] = True
    else:
        value["measurements"][1]["reason"] = None
    _, request, _ = catalog_for(tmp_path, retained, values=[value])
    with pytest.raises(ValueError):
        build(retained, request)


@pytest.mark.parametrize("change", ("future", "wrong_manifest", "immature"))
def test_current_access_is_rechecked_for_each_evidence_source(retained, tmp_path, change):
    witness = AccessWitness("evidence", "synthetic", 10, 20, 30)
    if change == "future":
        witness = replace(witness, end_ns=50, ready_ns=50)
    elif change == "wrong_manifest":
        witness = replace(witness, manifest_id="not-authorized")
    else:
        witness = replace(witness, ready_ns=50)
    _, request, _ = catalog_for(tmp_path, retained, witness=witness)
    with pytest.raises(PermissionError):
        build(retained, request)


def test_ref_digest_duplicates_and_live_catalog_mutations_are_rejected(retained, tmp_path):
    catalog, request, path = catalog_for(tmp_path, retained)
    original = build(retained, request)
    wrong = dict(request.evidence[0].ref.data, sha256="0" * 64)
    with pytest.raises(ValueError, match="digest"):
        build(retained, replace(request, evidence=(WinnerEvidence.at(wrong),)))
    with pytest.raises(ValueError, match="duplicate"):
        build(retained, replace(request, evidence=request.evidence * 2))
    path.write_text(json.dumps(dict(changed=True)), encoding="ascii")
    with pytest.raises(ValueError, match="source changed"):
        build(retained, request)
    with pytest.raises(ValueError, match="source changed"):
        original.verify(retained["decision"], **retained["kwargs"], request=request)
    assert catalog.read("winner-checks")["checks"]  # Snapshot survives, but cannot renew rights.


def test_default_public_views_redact_identifiers_params_sources_and_measurements(retained, tmp_path):
    _, request, _ = catalog_for(tmp_path, retained)
    report = build(retained, request)
    for rendered in (report.to_json(), report.to_markdown(), json.dumps(report.to_dict())):
        for private in (SECRET, PRIVATE_SOURCE, str(tmp_path), winner_subject(retained["decision"])["candidate_id"]):
            assert private not in rendered
        assert "retained.net_return" not in rendered
    private = report.to_markdown(private=True)
    assert "<script>" not in private
    assert html.escape(PRIVATE_SOURCE) in private
    assert SECRET in report.to_json(private=True) and PRIVATE_SOURCE in report.to_json(private=True)
    assert "Numeric Decision Comparisons" in private and "Exact Winner Probe And Stress Evidence" in private
    for disclosure in ("yes", 1, None):
        with pytest.raises(ValueError, match="boolean"):
            report.to_dict(private=disclosure)
        with pytest.raises(ValueError, match="boolean"):
            report.to_markdown(private=disclosure)


def test_frozen_copy_detached_exports_and_expected_identity_roundtrip(retained):
    report = build(retained)
    assert copy(report) == deepcopy(report) == pickle.loads(pickle.dumps(report)) == report
    with pytest.raises(FrozenInstanceError):
        report.record = Record.of({})
    detached = report.to_dict(private=True)
    detached["explanation"]["comparisons"].clear()
    assert build(retained) == report
    payload = report.to_json(private=True)
    assert WinnerQualificationReport.from_json(payload, expected_identity=report.identity) == report
    with pytest.raises(TypeError):
        WinnerQualificationReport.from_json(payload)
    with pytest.raises(ValueError, match="identity"):
        WinnerQualificationReport.from_json(payload, expected_identity="0" * 64)
    changed = json.loads(payload)
    changed["source_ref"] = "another-original-result"
    with pytest.raises(ValueError, match="identity"):
        WinnerQualificationReport.from_json(json.dumps(changed), expected_identity=report.identity)
    with pytest.raises(ValueError):
        WinnerQualificationReport.from_json(report.to_json(), expected_identity=report.identity)
    with pytest.raises(ValueError, match="duplicate"):
        WinnerQualificationReport.from_json('{"schema":1,"schema":2}', expected_identity=report.identity)
    assert report.verify(retained["decision"], **retained["kwargs"], request=WinnerQualificationRequest(include_account=False)) is report


def test_byte_limits_reject_without_truncation_or_changing_exact_boundary(retained):
    report = build(retained)
    size = len(report.to_json(private=True).encode())
    assert build(retained, WinnerQualificationRequest(include_account=False, max_report_bytes=size)) == report
    with pytest.raises(ValueError, match="byte budget"):
        build(retained, WinnerQualificationRequest(include_account=False, max_report_bytes=size - 1))
    for limit in (0, True, 16 * 1024**2 + 1):
        with pytest.raises(ValueError):
            WinnerQualificationRequest(include_account=False, max_report_bytes=limit)
    with pytest.raises(ValueError, match="bounded"):
        WinnerQualificationReport.from_json(" " * (16 * 1024**2 + 1), expected_identity=report.identity)


@pytest.mark.parametrize("invalid_request", (False, {}, [], "winner"))
def test_only_none_means_default_request_not_arbitrary_falsey_values(retained, invalid_request):
    with pytest.raises(TypeError):
        WinnerQualificationReport.build(retained["decision"], **retained["kwargs"], request=invalid_request)


@pytest.mark.parametrize("kind", (BacktestResult, BacktestResultV2, BacktestScalarScoreResult, NativeEventScoreResult))
def test_endpoint_result_and_reader_dispatch_are_cold_and_preserve_default_metadata_rng(retained, monkeypatch, kind):
    from quantbt.diagnostics.winner import report as owner
    from quantbt.mode5 import runtime
    from quantbt.mode5.evaluation import Mode5MetricPolicy
    from quantbt.mode5.selection import objectives, selectors

    result = object.__new__(kind)
    object.__setattr__(result, "metadata", dict(walk_forward=dict(optimization_mode="mode_5_full_robust",
        mode5_diagnostics_first=retained["metadata"], best_trial=dict(params=retained["params"]))))
    endpoint = object.__new__(QuantBTEndpoint)
    endpoint.result = result
    options = dict(retained["kwargs"], role="synthetic")
    before = pickle.dumps(result.metadata)
    rng = pickle.dumps((random.getstate(), np.random.get_state()))

    def forbidden(*args, **kwargs):
        raise AssertionError("cold reporting cannot execute strategy/finance/search/selection/RNG")

    monkeypatch.setattr(QuantBTEndpoint, "backtest", forbidden)
    monkeypatch.setattr(owner, "profile_selected_account", forbidden)
    monkeypatch.setattr(runtime.PublicMode5Runtime, "optimize", forbidden)
    monkeypatch.setattr(runtime.PublicMode5Runtime, "_observe_point", forbidden)
    monkeypatch.setattr(runtime, "run_ordered_study", forbidden)
    monkeypatch.setattr(Mode5MetricPolicy, "observe", forbidden)
    monkeypatch.setattr(selectors, "select", forbidden)
    monkeypatch.setattr(objectives, "evaluate", forbidden)
    monkeypatch.setattr(random, "random", forbidden)
    monkeypatch.setattr(np.random, "random", forbidden)
    default = result.research_report(**options)
    expected = build(retained)
    request = WinnerQualificationRequest(include_account=False)
    for actual in (result.research_report(**options, qualification=request),
                   endpoint.research_report(**options, qualification=request),
                   ResearchDecisionReport.from_result(result, **options, qualification=request)):
        assert isinstance(actual, WinnerQualificationReport) and actual == expected
        assert actual.to_json() and actual.to_markdown()
    assert result.research_report(**options).identity == endpoint.research_report(**options).identity == default.identity
    assert result.research_report(**options).to_json(private=True, detail=True) == default.to_json(private=True, detail=True)
    assert pickle.dumps(result.metadata) == before
    assert pickle.dumps((random.getstate(), np.random.get_state())) == rng
    assert set(endpoint.__dict__) == {"result"}


def test_qualification_rejects_unsupported_mode_and_mismatched_selected_dictionary(retained):
    result = object.__new__(BacktestResult)
    result.metadata = dict(walk_forward=dict(optimization_mode="mode_4_is_only_robust"))
    options = dict(retained["kwargs"], role="synthetic", qualification=WinnerQualificationRequest(include_account=False))
    with pytest.raises(ValueError, match="Mode5"):
        result.research_report(**options)
    result.metadata["walk_forward"] = dict(optimization_mode="mode_5_full_robust",
        mode5_diagnostics_first=retained["metadata"], best_trial=dict(params={"another": 1}))
    with pytest.raises(ValueError, match="dictionary"):
        result.research_report(**options)


def test_new_winner_report_rejects_reset_accounts_but_default_reader_remains_available(retained):
    value, params = runtime_metadata(continuous=False)
    decision = DecisionReport.read(value, selected_params=params)
    request = WinnerQualificationRequest(include_account=False)
    with pytest.raises(ValueError, match="continuous|CONTINUOUS"):
        WinnerQualificationReport.build(decision, **retained["kwargs"], request=request)
    result = object.__new__(BacktestResult)
    result.metadata = dict(walk_forward=dict(optimization_mode="mode_5_full_robust",
        mode5_diagnostics_first=value, best_trial=dict(params=params)))
    options = dict(retained["kwargs"], role="synthetic")
    before = pickle.dumps(result.metadata)
    default = result.research_report(**options)
    assert isinstance(default, ResearchDecisionReport)
    with pytest.raises(ValueError, match="continuous|CONTINUOUS"):
        result.research_report(**options, qualification=request)
    assert result.research_report(**options).identity == default.identity
    assert pickle.dumps(result.metadata) == before


def test_baseline_requires_current_pack_and_rechecks_real_pack_sources_without_finance(retained, tmp_path, monkeypatch):
    from quantbt.diagnostics import Mode5RunPack

    def forbidden(*args, **kwargs):
        raise AssertionError("baseline fixture may register/compile, never run finance")

    monkeypatch.setattr(QuantBTEndpoint, "backtest", forbidden)
    example = runpy.run_path(str(Path(__file__).resolve().parents[2] / "examples/mode5_diagnostic_handoff.py"))
    inputs = example["build_inputs"](tmp_path / "pack-inputs")
    chosen = inputs["worksheet"].choose(example["OPTION_ID"], researcher="synthetic-review", reason="Pure source-binding control")
    pack = Mode5RunPack.compile(chosen, dossier=inputs["dossier"], catalog=inputs["catalog"], access=inputs["access"])
    baseline = WinnerBaseline(retained["decision"], pack, inputs["dossier"], inputs["catalog"], inputs["access"], "original-baseline")
    with pytest.raises(ValueError, match="current"):
        WinnerQualificationRequest(include_account=False, baseline=baseline)
    with pytest.raises(ValueError, match="original source-bound pack"):
        baseline.verify()
    source = Path(inputs["catalog"].manifest.data["sources"][0]["path"])
    source.write_text(json.dumps(dict(changed=True)), encoding="ascii")
    with pytest.raises(ValueError, match="source changed"):
        baseline.verify()


def compiled_rights_bundle(tmp_path, monkeypatch, *, extra_source=None, archive=False, selection_only=False):
    """Real source/pack boundary around literal runtime controls, not finance."""
    from examples import mode5_diagnostic_handoff as example
    from quantbt.diagnostics import CalibrationRecipe, CalibrationWorksheet, Mode5RunPack
    from quantbt.mode5.dossier.dossier import Dossier

    def forbidden(*args, **kwargs):
        raise AssertionError("rights regression must never execute finance")

    monkeypatch.setattr(QuantBTEndpoint, "backtest", forbidden)
    if selection_only:
        original = example._missing_archive

        def restricted(*args, **kwargs):
            evidence = original(*args, **kwargs)
            return replace(evidence, nodes=tuple(replace(node, purposes=("selection",)) for node in evidence.nodes))

        monkeypatch.setattr(example, "_missing_archive", restricted)
    inputs = example.build_inputs(tmp_path / "rights-inputs", optional_archive=archive)
    card = next(c for c in inputs["worksheet"].record.data["cards"] if c["recipe"]["option_id"] == example.OPTION_ID)
    recipe_data = card["recipe"]
    access, catalog, dossier = inputs["access"], inputs["catalog"], inputs["dossier"]
    witness = AccessWitness(**recipe_data["binding"]["continuous"]["witness"])
    if extra_source is not None:
        dependency = replace(witness,
            manifest_id="extra-dependency" if extra_source == "manifest" else witness.manifest_id,
            ready_ns=witness.ready_ns + 1)
        access = replace(access, manifests=tuple(dict.fromkeys((*access.manifests, dependency.manifest_id))))
        recipe_data["spec"]["reuse"]["selection_policy"] = asdict(access)
        path = inputs["workdir"] / "extra-dependency.json"
        write_json(path, dict(status="SYNTHETIC_CONTROL", value=None))
        pin = file_identity(path)
        sources = tuple(Source(**{**s, "witness": AccessWitness(**s["witness"])})
            for s in catalog.manifest.data["sources"])
        catalog = EvidenceCatalog((*sources, Source("extra-dependency", str(path), pin["sha256"], pin["bytes"], dependency)),
            replace(access, purpose="diagnostic"))
        data = dossier.record.data
        data["source_manifest"] = catalog.manifest.data
        dossier = Dossier(Record.of(data))
        dossier.verify(catalog)
    recipe = CalibrationRecipe(Record.of(recipe_data))
    worksheet = CalibrationWorksheet.create(dossier=dossier, catalog=catalog, options=(recipe,),
        archive=inputs["archive"], archive_access=inputs["archive_access"])
    chosen = worksheet.choose(example.OPTION_ID, researcher="rights-regression", reason="Literal cold contract control")
    pack = Mode5RunPack.compile(chosen, dossier=dossier, catalog=catalog, access=access,
        archive_access=inputs["archive_access"])
    value, params = metadata()
    value.update(calibration_plan_id=pack.record.data["plan_id"], runtime_binding_identity=pack.record.data["binding_id"],
        dossier_id=dossier.record.identity)
    continuous = pack.record.data["binding"]["continuous"]
    step = pack.record.data["binding"]["metrics"]["bar_interval_ns"]
    bars = (continuous["stop_ns"] - continuous["start_ns"]) // step
    value["account_scope"].update(scored_start_ns=continuous["start_ns"], scored_stop_ns=continuous["stop_ns"],
        full_bars=bars, scored_bars=bars, preload_bars=0, scored_positions=[0, bars])
    for row in value["trial_ledger"]:
        if "whole_observation" in row:
            row["whole_observation"].update(start_ns=continuous["start_ns"], stop_ns=continuous["stop_ns"])
    decision = DecisionReport.read(value, selected_params=params)
    bundle = WinnerBaseline(decision, pack, dossier, catalog, access, "source-bound-literal-control",
        archive_access=inputs["archive_access"])
    assert bundle.verify() is bundle
    diagnostic = replace(access, policy_id="current-diagnostic-readback", purpose="diagnostic")
    return bundle, diagnostic, witness


@pytest.mark.parametrize("dependency", ("manifest", "future"))
@pytest.mark.parametrize("supplied_as", ("current", "baseline"))
def test_report_reauthorizes_real_pack_catalog_sources_under_current_diagnostic_rights(
        tmp_path, monkeypatch, dependency, supplied_as):
    bundle, authorized, witness = compiled_rights_bundle(tmp_path, monkeypatch, extra_source=dependency)
    before = bundle.pack.record
    current = bundle
    if supplied_as == "baseline":
        current, _, _ = compiled_rights_bundle(tmp_path / "separate-current", monkeypatch)
    inputs = dict(access=authorized, witness=witness, source_ref="current-catalog-readback")
    request = WinnerQualificationRequest(include_account=False, current=current,
        baseline=bundle if supplied_as == "baseline" else None)
    WinnerQualificationReport.build(current.decision, **inputs, request=request)
    if dependency == "manifest":
        narrowed = replace(authorized, manifests=(witness.manifest_id,))
    else:
        narrowed = replace(authorized, cutoff_ns=witness.ready_ns)
    narrowed.require(witness)  # Only a dependency, not the account, is forbidden.
    if supplied_as == "baseline":
        assert current.authorize(narrowed) is current
    with pytest.raises(PermissionError):
        bundle.authorize(narrowed)
    with pytest.raises(PermissionError):
        WinnerQualificationReport.build(current.decision, **dict(inputs, access=narrowed), request=request)
    assert bundle.pack.record == before
    assert bundle.access.purpose == "selection" and bundle.verify() is bundle


def test_archive_readback_rechecks_dag_clocks_without_replacing_original_selection_seal(tmp_path, monkeypatch):
    bundle, authorized, witness = compiled_rights_bundle(tmp_path, monkeypatch, archive=True)
    before = bundle.pack.record
    assert bundle.authorize(authorized) is bundle
    narrowed = replace(authorized, cutoff_ns=witness.ready_ns)
    narrowed.require(witness)
    for source in bundle.catalog.manifest.data["sources"]:
        narrowed.require(AccessWitness(**source["witness"]))
    # Source/mark readiness passes. Original DAG publication at the cutoff
    # still lacks the ordering witness required for retrospective readback.
    with pytest.raises(PermissionError):
        bundle.authorize(narrowed)
    with pytest.raises(PermissionError):
        WinnerQualificationReport.build(bundle.decision, access=narrowed, witness=witness, source_ref="archive-readback",
            request=WinnerQualificationRequest(include_account=False, current=bundle))
    assert bundle.pack.record == before and bundle.verify() is bundle


def test_selection_only_archive_nodes_cannot_borrow_diagnostic_readback_purpose(tmp_path, monkeypatch):
    bundle, diagnostic, witness = compiled_rights_bundle(tmp_path, monkeypatch, archive=True, selection_only=True)
    before = bundle.pack.record
    diagnostic.require(witness)
    assert bundle.verify() is bundle  # Original selection permission remains valid.
    with pytest.raises(PermissionError):
        bundle.authorize(diagnostic)
    with pytest.raises(PermissionError):
        WinnerQualificationReport.build(bundle.decision, access=diagnostic, witness=witness, source_ref="selection-only-archive",
            request=WinnerQualificationRequest(include_account=False, current=bundle))
    assert bundle.pack.record == before


@pytest.mark.parametrize("mismatch", ("run", "winner"))
def test_direct_builder_rejects_other_completed_decision_even_for_identical_finance_and_no_account_request(
        retained, monkeypatch, mismatch):
    import pandas as pd
    from quantbt.diagnostics.winner import report as owner
    from quantbt.mode5.evaluation import array_identity

    def forbidden(*args, **kwargs):
        raise AssertionError("include_account=False must not profile or execute an account")

    monkeypatch.setattr(owner, "profile_selected_account", forbidden)
    index = pd.date_range("1970-01-01", periods=6, freq="D", tz="UTC")
    equity = pd.Series(100., index=index)
    positions = pd.DataFrame(0., index=index, columns=["CONTROL"])
    finance = dict(equity=array_identity(equity.to_numpy()), positions=array_identity(positions.to_numpy()))
    stop = int(index[-1].value) + 86_400_000_000_000
    runtimes = [metadata(), metadata(incumbent=mismatch == "winner")]
    for value, _ in runtimes:
        value["account_scope"].update(scored_start_ns=0, scored_stop_ns=stop,
            full_bars=6, scored_bars=6, preload_bars=0, scored_positions=[0, 6])
        for row in value["trial_ledger"]:
            if "whole_observation" in row:
                row["whole_observation"].update(finance=finance, initial_capital=100., final_equity=100., start_ns=0, stop_ns=stop)
    original, params = runtimes[0]
    other, other_params = runtimes[1]
    if mismatch == "run":
        other["dossier_id"] = "another-completed-run"
    decision = DecisionReport.read(original, selected_params=params)
    other_decision = DecisionReport.read(other, selected_params=other_params)
    assert decision != other_decision
    result = BacktestResult(equity=equity, returns=pd.Series(0., index=index), positions=positions,
        closes=pd.DataFrame(1., index=index, columns=["CONTROL"]), symbols=["CONTROL"], initial_capital=100., leverage=1.,
        metadata=dict(walk_forward=dict(optimization_mode="mode_5_full_robust",
            mode5_diagnostics_first=original, best_trial=dict(params=params))))
    stale = deepcopy(result)
    stale.metadata["walk_forward"].update(mode5_diagnostics_first=other, best_trial=dict(params=other_params))
    assert array_identity(stale.equity.to_numpy()) == finance["equity"]
    assert array_identity(stale.positions.to_numpy()) == finance["positions"]
    witness = AccessWitness("run", "synthetic", 0, stop, stop + 1)
    options = dict(retained["kwargs"], witness=witness,
        access=replace(retained["kwargs"]["access"], cutoff_ns=stop + 2))
    request = WinnerQualificationRequest(include_account=False)
    before = pickle.dumps((result.metadata, stale.metadata))
    WinnerQualificationReport.build(decision, **options, request=request, result=result)
    with pytest.raises(ValueError, match="result|decision"):
        WinnerQualificationReport.build(decision, **options, request=request, result=stale)
    assert pickle.dumps((result.metadata, stale.metadata)) == before
