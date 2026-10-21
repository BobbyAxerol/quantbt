"""Cold synthetic contracts, plus one separately enabled actual financial smoke.

The COMPLETE records in the cold fixtures are explicitly literal contract
controls. Only test_actual_cross_mode_handoff_smoke qualifies real execution.
Enable it with QUANTBT_RUN_CROSS_MODE_SMOKE=1 under the parent's work budget.
"""

from dataclasses import asdict, replace
import json
import os
from types import SimpleNamespace

import pandas as pd
import pytest

from examples import mode5_cross_mode_qualification as demo
from quantbt import QuantBTEndpoint
from quantbt.diagnostics.access import AccessWitness
from quantbt.diagnostics.archive_contracts import ArchiveEvidence, ArchiveIdentity, DependencyNode, IntendedReuse
from quantbt.diagnostics.calibration.donor_binding import continuous_donor_target, verify_recipe_donors
from quantbt.diagnostics.calibration.donors import ArchiveDonorPlan
from quantbt.diagnostics.identity import AnalysisKey, ExecutionKey, digest
from quantbt.mode5.artifacts import file_identity, write_json
from quantbt.mode5.continuous_binding import restore_geometry
from quantbt.mode5.dossier.evidence import EvidenceCatalog, Source
from quantbt.mode5.dossier.records import Record
from quantbt.optimization.parameter_space import NormalizedSearchSpace


@pytest.fixture
def no_finance(monkeypatch):
    import optuna
    def forbidden(*args, **kwargs):
        raise AssertionError("cold contract test invoked finance or an optimizer")
    monkeypatch.setattr(QuantBTEndpoint, "backtest", forbidden)
    monkeypatch.setattr(QuantBTEndpoint, "_run_single", forbidden)
    monkeypatch.setattr(optuna, "create_study", forbidden)
    monkeypatch.setattr(optuna.study.Study, "ask", forbidden)


@pytest.fixture
def cold_archive(tmp_path, no_finance):
    inputs = demo.build_demo_inputs(tmp_path / "inputs")
    binding = Record.of(demo._base_recipe(inputs)["binding"])
    target = continuous_donor_target(inputs["dossier"], binding, seed=demo.SEED)
    witness = AccessWitness(**binding.data["continuous"]["witness"])
    now = witness.ready_ns
    nodes = tuple(DependencyNode(kind, kind, witness, witness.end_ns, now, now, now, now,
        dependencies, ("diagnostic", "selection"), "NOT_BACKDATABLE") for kind, dependencies in (
            ("source", ()), ("candidate", ("source",)),
            ("outcome", ("candidate",)), ("revision", ("outcome",))))
    points, evidence = ({"period": 6}, {"period": 12}), []
    for i, params in enumerate(points):
        execution = ExecutionKey(target.strategy_identity, digest(params), target.market_snapshot,
            "SYNTHETIC_CONTRACT_CONTROL_FLAT", target.clock, target.instrument, target.costs,
            target.funding, "SYNTHETIC_CONTRACT_CONTROL_RESET", "literal-terminal", target.warmup,
            target.scenario_seed, target.source_backend)
        identity = ArchiveIdentity(execution, AnalysisKey(execution.identity,
            "literal-membership", "literal-metric", "literal-reference"), target.space_identity,
            target.timeframe, target.route, witness.start_ns, witness.end_ns - demo.STEP_NS, "literal-unit")
        evidence.append(ArchiveEvidence("mode4-fold-" + str(i), identity, "literal-candidate-" + str(i),
            "LITERAL_NOT_AN_ACTUAL_EXECUTION_" + str(i), "literal-state", "a" * 64,
            ("revision",), nodes, "COMPLETE", None, (), ()))
    path = inputs["workdir"] / "literal-contract-archive.json"
    write_json(path, dict(status="SYNTHETIC_CONTRACT_CONTROL_NOT_ACTUAL_FINANCE",
        evidence=[asdict(e) for e in evidence], points=points))
    pin = file_identity(path)
    sources = [Source(**{**s, "witness": AccessWitness(**s["witness"])})
               for s in inputs["catalog"].manifest.data["sources"]]
    sources.append(Source("literal-archive", str(path), pin["sha256"], pin["bytes"], witness))
    catalog = EvidenceCatalog(tuple(sources), inputs["catalog"].policy)
    entries = tuple((e, IntendedReuse(e.identity, "MODE5_CALIBRATION"),
        catalog.ref("literal-archive", "/evidence/" + str(i))) for i, e in enumerate(evidence))
    choices = {e.evidence_id: catalog.ref("literal-archive", "/points/" + str(i))
               for i, e in enumerate(evidence)}
    return SimpleNamespace(inputs=inputs, binding=binding, target=target, catalog=catalog,
        entries=entries, choices=choices, points=points, path=path)


def _challenger(fixture):
    return demo.create_recipe_inputs(fixture.inputs, catalog=fixture.catalog,
        access=fixture.inputs["access"], entries=fixture.entries, donor_choices=fixture.choices)


def _verify(inputs, *, recipe=None, binding=None, **changes):
    return verify_recipe_donors(recipe or inputs["recipe"], dossier=inputs["dossier"],
        binding=binding or inputs["binding"], catalog=inputs["catalog"],
        access=changes.get("access", inputs["access"]))


def test_default_cli_and_build_are_zero_work_without_fabricated_archive(tmp_path, no_finance, capsys):
    root = tmp_path / "dry"
    demo.main(["--workdir", str(root)])
    protocol = json.loads(capsys.readouterr().out)
    assert protocol["status"] == "NOT_RUN"
    assert protocol["observed_proposals"] == protocol["observed_financial_invocations"] == 0
    assert protocol["proposal_slots"] == 12 and protocol["financial_invocation_ceiling"] == 23
    assert not (root / "mode4-archive.json").exists()
    with pytest.raises(SystemExit):
        demo.main(["--workdir", str(tmp_path / "no-roster"), "--run"])
    assert not (tmp_path / "no-roster").exists()


@pytest.mark.parametrize("folds", [(), (0, 0), (2,), (True,), [0]])
def test_explicit_invalid_rosters_fail_before_workdir_or_execution(tmp_path, no_finance, folds):
    root = tmp_path / "not-created"
    with pytest.raises(ValueError, match="explicit ordered"):
        demo.run_demo(root, donor_folds=folds)
    assert not root.exists()


def test_mode4_calendar_is_bounded_without_running_it(tmp_path, no_finance):
    inputs = demo.build_demo_inputs(tmp_path / "calendar")
    endpoint = demo.mode4_endpoint(inputs)
    assert endpoint.config.walkforward_config.optuna_trials == 2
    assert endpoint.config.walkforward_config.optimization_schedule == "per_fold_causal"


def test_actual_target_helper_binds_original_composite_economics_and_source(cold_archive):
    c = cold_archive
    context, continuous = c.inputs["dossier"].record.data["context"], c.binding.data["continuous"]
    assert c.target.costs == c.target.instrument == c.target.funding == context["economics"]
    assert c.target.source_backend == Record.of(continuous["source"]).identity
    assert c.target.strategy_identity == continuous["source"]["alpha"]
    assert c.target.clock == Record.of(continuous["execution"]["clock"]).identity
    assert c.target.route == continuous["execution"]["route"]
    assert c.target.space_identity == NormalizedSearchSpace(c.inputs["param_ranges"]).identity
    assert c.target.warmup == Record.of(dict(policy="full_original_prefix_no_external_history",
        history_start_ns=continuous["witness"]["start_ns"])).identity


def test_challenger_rebinds_scope_sources_and_exact_starts_without_new_diagnostic_metrics(cold_archive):
    c = cold_archive
    baseline = demo.create_recipe_inputs(c.inputs, catalog=c.catalog, entries=c.entries)
    challenger = _challenger(c)
    before = c.inputs["dossier"].record.data
    after = challenger["dossier"].record.data
    assert before["context"]["scope"] != after["context"]["scope"]
    assert after["context"]["scope"] == challenger["binding"].identity
    assert after["source_manifest"] == c.catalog.manifest.data
    for key in ("matrices", "axes", "radar", "batteries", "recommendations", "compute_bill"):
        assert after[key] == before[key]
    assert all(axis["status"] == "NOT_RUN" for axis in after["axes"].values())
    assert challenger["archive"].to_dict()["context_id"] == digest(after["context"])
    assert baseline["donors"] is None and baseline["binding"].data["warm_start"] == []
    assert challenger["binding"].data["warm_start"] == challenger["donors"].to_dict()["warm_start"]
    assert challenger["recipe"].record.data["spec"]["reuse"]["archive_donors"] == challenger["donors"].record.data
    assert baseline["binding"].data["continuous"] == challenger["binding"].data["continuous"]
    assert challenger["worksheet"].record.data["selection"] is None
    _verify(challenger)


def test_explicit_choice_compile_and_private_pack_roundtrip_are_cold(cold_archive):
    inputs = _challenger(cold_archive)
    pack = demo._compile(inputs, "cold-contract")
    assert pack.record.data["plan"]["recipe"]["reuse"]["archive_donors"] == inputs["donors"].record.data
    assert pack.record.data["binding"]["warm_start"] == inputs["donors"].to_dict()["warm_start"]
    assert pack.verify(dossier=inputs["dossier"], catalog=inputs["catalog"],
        access=inputs["access"], archive_access=inputs["archive_access"]) is pack
    assert pack.record.data["deployment_authorized"] is False
    assert not (inputs["workdir"] / "cold-contract-journal").exists()


@pytest.mark.parametrize("change", ["missing", "reverse", "extra-score", "changed-coordinate"])
def test_donor_binding_rejects_nonexact_current_warm_starts(cold_archive, change):
    inputs = _challenger(cold_archive)
    d = inputs["binding"].data
    if change == "missing":
        d["warm_start"] = []
    elif change == "reverse":
        d["warm_start"].reverse()
    elif change == "extra-score":
        d["warm_start"][0]["score"] = 999
    else:
        d["warm_start"][0]["params"]["period"] = 24
    with pytest.raises(ValueError, match="warm starts"):
        _verify(inputs, binding=Record.of(d))


@pytest.mark.parametrize("change", ["strategy", "clock", "route", "history"])
def test_target_is_derived_again_from_current_binding_not_embedded_plan(cold_archive, change):
    inputs = _challenger(cold_archive)
    d = inputs["binding"].data
    if change == "strategy":
        d["continuous"]["source"]["alpha"] = "other-alpha"
    elif change == "clock":
        d["continuous"]["execution"]["clock"]["equity_clock"] = "other-clock"
    elif change == "route":
        d["continuous"]["execution"]["route"] = "other-route"
    else:
        d["continuous"]["witness"]["start_ns"] += 1
    with pytest.raises(ValueError, match="destination|incompatible|differs"):
        _verify(inputs, binding=Record.of(d))


def test_donor_binding_rejects_changed_current_composite_economics(cold_archive):
    inputs = _challenger(cold_archive)
    d = inputs["dossier"].record.data
    d["context"]["economics"] = "different-actual-composite-economics"
    changed = type(inputs["dossier"])(Record.of(d))
    with pytest.raises(ValueError, match="destination|incompatible"):
        verify_recipe_donors(inputs["recipe"], dossier=changed, binding=inputs["binding"],
            catalog=inputs["catalog"], access=inputs["access"])


@pytest.mark.parametrize("field", ["seed", "budget"])
def test_donor_binding_rechecks_current_recipe_seed_and_budget(cold_archive, field):
    inputs = _challenger(cold_archive)
    d = inputs["recipe"].record.data
    if field == "seed":
        d["spec"]["sampler"]["seeds"] = [demo.SEED + 1]
    else:
        d["spec"]["search_budget"] = demo.MODE5_TRIALS + 1
    with pytest.raises(ValueError, match="destination|budget"):
        _verify(inputs, recipe=type(inputs["recipe"])(Record.of(d)))


def test_donor_sources_and_selection_policy_are_rechecked_at_compile(cold_archive):
    inputs = _challenger(cold_archive)
    with pytest.raises(PermissionError):
        _verify(inputs, access=replace(inputs["access"], policy_id="changed"))
    cold_archive.path.write_text(cold_archive.path.read_text() + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="source changed"):
        demo._compile(inputs, "changed-source")


def test_donor_plan_reload_rejects_prefix_relabel_and_narrowed_cutoff(cold_archive):
    inputs = _challenger(cold_archive)
    plan = inputs["donors"]
    current = dict(catalog=inputs["catalog"], access=inputs["access"],
        target=continuous_donor_target(inputs["dossier"], inputs["binding"], seed=demo.SEED),
        geometry=restore_geometry(inputs["binding"].data["continuous"]["geometry"]), budget=4)
    assert ArchiveDonorPlan.from_json(plan.to_json(), **current) == plan
    with pytest.raises(ValueError, match="destination"):
        ArchiveDonorPlan.from_json(plan.to_json(), **{**current, "target": replace(current["target"], mode="MODE4_PREFIX")})
    with pytest.raises((PermissionError, ValueError)):
        ArchiveDonorPlan.from_json(plan.to_json(), **{**current,
            "access": replace(inputs["access"], cutoff_ns=inputs["access"].cutoff_ns - demo.STEP_NS)})


def _literal_selected_metadata():
    space = NormalizedSearchSpace({"period": (6, 24, 1)})
    selections, studies = [], []
    for fold, period in enumerate((6, 12)):
        params = {"period": period}
        row = dict(trial_id=0, state="COMPLETE", effective_params=params,
            candidate_id=space.candidate_key(params, strategy_identity="literal-alpha"), objective=[1.])
        studies.append(dict(study_id=fold, attempts=2, seed=731 + fold * 1000003,
            rows=[row, dict(trial_id=1, state="PRUNED")], space_identity=space.identity,
            strategy_identity="literal-alpha"))
        selections.append(dict(fold_id=fold, study_id=fold, selected_trial_id=0,
            selected_params=params, selected_is_objective=1., train_start="2020-12-16T00:00:00Z",
            train_end="2021-01-02T23:00:00Z", test_start="2021-01-03T00:00:00Z",
            test_end="2021-01-09T23:00:00Z"))
    return dict(optimization_mode="mode_4_is_only_robust", optimization_schedule="per_fold_causal",
        n_folds=2, strategy_fingerprint="literal-alpha", sampler_studies=studies,
        fold_selection_table=pd.DataFrame(selections)), space


@pytest.mark.parametrize("corruption", [None, "noncomplete", "wrong-point", "wrong-candidate", "missing-study", "extra-attempt"])
def test_original_mode4_readback_requires_selected_complete_trial_without_reranking(corruption):
    metadata, space = _literal_selected_metadata()
    first = metadata["sampler_studies"][0]
    if corruption == "noncomplete":
        first["rows"][0]["state"] = "FAILED"
    elif corruption == "wrong-point":
        first["rows"][0]["effective_params"] = {"period": 24}
    elif corruption == "wrong-candidate":
        first["rows"][0]["candidate_id"] = "invented"
    elif corruption == "missing-study":
        metadata["sampler_studies"].pop()
    elif corruption == "extra-attempt":
        first["attempts"] = 3
    if corruption is not None:
        with pytest.raises(ValueError):
            demo.selected_fold_rows(metadata, space, "literal-alpha")
    else:
        rows = demo.selected_fold_rows(metadata, space, "literal-alpha")
        assert [r["params"] for r in rows] == [{"period": 6}, {"period": 12}]


@pytest.mark.skipif(os.environ.get("QUANTBT_RUN_CROSS_MODE_SMOKE") != "1",
    reason="Explicit parent budget required: 12 proposals, at most 23 financial invocations")
def test_actual_cross_mode_handoff_smoke(tmp_path):
    outcome = demo.run_demo(tmp_path / "actual", donor_folds=(0,))
    summary = outcome["summary"]
    assert summary["observed_proposals"] == 12
    assert 0 < summary["observed_financial_invocations"] <= 23
    assert summary["challenger_warm_start_attempts"] == 1 and summary["challenger_attempts"] == 4
    assert summary["sampler_cutoff_authority"] == "sealed_mode5_selection_policy"
    assert summary["baseline_winner_id"] and summary["challenger_winner_id"]
    assert summary["economic_superiority"] == "NOT_QUALIFIED"
    assert summary["deployment_authorized"] is False
    assert outcome["winner"].record.data["baseline"]["status"] == "SOURCE_BOUND_SELECTED_PATHS"
    archive = outcome["challenger"]["archive"].to_dict()
    assert all(r["declared_inputs"]["evidence"]["status"] == "COMPLETE" for r in archive["rows"])
    assert all(r['disposition'] == 'TARGETED_EXECUTION_REQUIRED' for r in archive['rows'])
    contract = outcome['challenger']['binding'].data['continuous']
    assert all(r['declared_inputs']['intended']['identity']['start_ns'] == contract['start_ns']
        and r['declared_inputs']['intended']['identity']['end_ns'] == contract['stop_ns'] for r in archive['rows'])
    starts = outcome["challenger"]["binding"].data["warm_start"]
    row = outcome["completed"]["challenger"]["metadata"]["trial_ledger"][0]
    assert row["state"] == "COMPLETE" and row["effective_params"] == starts[0]["params"]
    assert row["whole_observation"] and row["evaluation_ref"]
