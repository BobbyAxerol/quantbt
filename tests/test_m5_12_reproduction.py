"""Bounded source-only cold replay; main owns test execution and artifact proof.

All input figures are public synthetic records, not private alpha observations.
The explicit source bootstrap in the subprocess test is NOT an installed proof.
"""

from copy import deepcopy
from dataclasses import asdict, replace
from hashlib import sha256
import ast
import json
import os
from pathlib import Path
import random
import subprocess
import sys

import numpy as np
import pytest

from quantbt.diagnostics import AccessPolicy, AccessWitness, ResearchDecisionReport
from quantbt.diagnostics.winner import WinnerQualificationReport, WinnerQualificationRequest
from quantbt.mode5 import DecisionReport
from quantbt.optimization.parameter_space import NormalizedSearchSpace
from tools import m5_12_reproduction as reproduction


ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools/m5_12_reproduction.py"


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def encode(value):
    return reproduction._canonical(value).encode("utf-8")


def write_manifest(sample, manifest):
    raw = encode(manifest)
    sample["path"].write_bytes(raw)
    sample["pin"] = sha256(raw).hexdigest()


def change_input(sample, kind, change, *, repin=True):
    manifest = read(sample["path"])
    path = sample["path"].parent / manifest["entries"][kind]["file"]
    data = read(path)
    change(data)
    raw = encode(data)
    path.write_bytes(raw)
    if repin:
        manifest["entries"][kind].update(sha256=sha256(raw).hexdigest(), bytes=len(raw))
        write_manifest(sample, manifest)


@pytest.fixture
def inputs(monkeypatch):
    from examples.shared_decision_reporting import example_inputs
    from examples.shared_presearch_researcher import example_inputs as diagnostic_inputs

    # Reuse existing synthetic metadata, not a second sampler or selector.
    # These test-only modules contain adversarial privacy sentinels, not alphas.
    monkeypatch.syspath_prepend(str(ROOT / "tests/mode5"))
    from test_winner_report import metadata

    owner, observations, _, advice = diagnostic_inputs(count=12)
    diagnostic = owner.analyze(observations, advice=advice)
    raw_diagnostic = dict(schema="m512-diagnostic-inputs-v1",
        ranges=list(NormalizedSearchSpace({"window": (1, 12), "threshold": (0., 1.)}).portable_ranges().items()),
        context=asdict(owner.context), observations=[dict(evaluation_id=row.evaluation_id,
            context_id=row.context_id, params=row.point.params, metrics=row.metrics.data,
            witness=asdict(row.witness), source_ref=row.source_ref, status=row.status,
            activity_count=row.activity_count) for row in observations],
        advice=[asdict(row) for row in advice])
    folds, slots, access, cohorts = example_inputs(count=2)
    mode4 = ResearchDecisionReport.mode4(folds, roster=slots, access=access, cohorts=cohorts)
    runtime, params = metadata()
    mode5 = DecisionReport.read(runtime, selected_params=params)
    winner_access = AccessPolicy("synthetic-winner-review", ("synthetic",), ("synthetic-mode5",), 40, "diagnostic")
    winner = WinnerQualificationReport.build(mode5, access=winner_access,
        witness=AccessWitness("synthetic-mode5", "synthetic", 10, 20, 30),
        source_ref="public-synthetic-record-not-an-executed-market-account",
        request=WinnerQualificationRequest(include_account=False))
    reports = dict(diagnostics=diagnostic, mode4=mode4, mode5=mode5, winner=winner)
    # Independent simple-value checks supplement (not replace) exact replay of
    # all full-precision report bytes against the retained source snapshots.
    d = diagnostic.to_dict()
    assert d["coverage"]["evaluations"] == d["coverage"]["unique_effective_candidates"] == 12
    assert d["activity"]["zero_activity_evaluations"] == 3
    policy = mode4.to_dict(private=True, detail=True)["summary"]["cohorts"]["all_calendar"]["policies"]["applied"]
    assert policy["effects"]["R"]["mean"] == pytest.approx(.815)
    assert policy["effects"]["Q"]["mean"] == pytest.approx(-.185)
    assert policy["helped"] == 0 and policy["harmed"] == 2
    w = winner.to_dict(private=True)
    assert w["annual_summary"]["utility"]["minimum"] == .05
    assert w["explanation"]["comparisons"][0]["objective_delta"] == pytest.approx(.35)
    from quantbt.mode5.dossier.records import pointer
    values = {kind: {path: pointer(reproduction._private(report, kind), path)
        for path in reproduction.REQUIRED_VALUES[kind]} for kind, report in reports.items()}
    values["mode4"]["/payload/family/metric_contract_id"] = "synthetic-raw-sharpe"
    values["mode5"]["/summary/objective_semantics"] = "frozen selector score in declared channel; not raw Sharpe"
    values["winner"]["/annual_summary/utility/interpretation"] = (
        "Utility after registered risk preferences, not raw return or a gate requiring every year positive")
    return dict(diagnostic_inputs=raw_diagnostic, reports=reports, expected_values=values,
        access=dict(diagnostics=owner.access, mode4=access, winner=winner_access))


@pytest.fixture
def sample(tmp_path, inputs):
    pin = reproduction.seal_synthetic(tmp_path / "input", **inputs)
    return dict(path=Path(pin["path"]), pin=pin["sha256"], output=tmp_path / "output", inputs=inputs)


def run(sample):
    return reproduction.reproduce(sample["path"], expected_sha256=sample["pin"], output=sample["output"])


def test_rebuild_checks_numeric_values_masks_units_and_all_report_bytes(sample):
    receipt = run(sample)
    assert receipt["status"] == "REPRESENTATIVE_REPRODUCTION_VERIFIED"
    assert receipt["fresh_process"] is False  # this unit call is not M5T-113
    assert receipt["new_optimizer_trials"] == receipt["new_financial_runs"] == receipt["new_model_fits"] == 0
    assert receipt["twelve_phase_reports_rebuilt"] is receipt["historical_research_recomputed"] is False
    assert receipt["installed_artifact_qualified"] is receipt["publish_or_live_authorized"] is False
    assert len(receipt["files"]) == 8
    for kind, original in sample["inputs"]["reports"].items():
        assert receipt["report_ids"][kind] == original.record.identity
        for suffix, expected in reproduction._render(original, kind).items():
            path = sample["output"] / (kind + "." + suffix)
            assert path.read_bytes() == expected
            assert receipt["files"][path.name]["sha256"] == sha256(expected).hexdigest()
    winner = read(sample["output"] / "winner.json")
    assert winner["account"]["status"] == "NOT_SUPPLIED"
    assert next(row for row in winner["coverage"] if row["section"] == "regime")["status"] == "NOT_SUPPLIED"
    assert winner["annual_summary"]["independent_replications"] is None


def test_fresh_process_reproduces_from_files_without_parent_memory(sample):
    # Deliberately source-only. Installed M5-12 must execute TOOL directly with
    # ENV/bin/python -I -B, not use this explicit test bootstrap.
    bootstrap = ("import runpy,sys;script,source=sys.argv[1:3];sys.path.insert(0,source);"
        "sys.argv=[script,*sys.argv[3:]];runpy.run_path(script,run_name='__main__')")
    env = {key: value for key, value in os.environ.items() if key not in {"PYTHONPATH", "PYTHONHOME"}}
    env.update(OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="1", MKL_NUM_THREADS="1", NUMBA_NUM_THREADS="1")
    result = subprocess.run([sys.executable, "-I", "-B", "-c", bootstrap, str(TOOL), str(ROOT / "src"),
        "--manifest", str(sample["path"]), "--expected-sha256", sample["pin"], "--output", str(sample["output"])],
        cwd=sample["output"].parent, env=env, capture_output=True, text=True, timeout=90, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    receipt = read(sample["output"] / "reproduction.json")
    assert receipt["process_id"] != os.getpid() and receipt["fresh_process"] is True
    assert receipt["isolated_interpreter"] is True
    assert receipt["installed_artifact_qualified"] is False
    assert receipt["checked_values"]["diagnostics"]["/coverage/evaluations"] == 12
    assert receipt["checked_values"]["mode4"][reproduction.REQUIRED_VALUES["mode4"][1]] == pytest.approx(-.185)
    assert receipt["report_ids"] == {kind: report.record.identity for kind, report in sample["inputs"]["reports"].items()}


def test_wrong_externally_retained_hash_does_not_create_output(sample):
    sample["pin"] = "0" * 64
    with pytest.raises(ValueError, match="manifest SHA256"):
        run(sample)
    assert not sample["output"].exists()


def test_input_rewrite_even_as_valid_json_is_not_accepted_without_hash(sample):
    change_input(sample, "diagnostics", lambda value: value["observations"][0]["metrics"].update(quality=99.), repin=False)
    with pytest.raises(ValueError, match="input hash/size"):
        run(sample)
    assert not sample["output"].exists()


@pytest.mark.parametrize("kind", reproduction.KINDS)
def test_independently_wrong_numeric_or_unit_or_support_assertion_is_rejected(sample, kind):
    manifest = read(sample["path"])
    path = reproduction.REQUIRED_VALUES[kind][0]
    manifest["entries"][kind]["values"][path] = "wrong-unit-or-value"
    write_manifest(sample, manifest)
    with pytest.raises(ValueError, match="exact retained value"):
        run(sample)
    assert not sample["output"].exists()


@pytest.mark.parametrize("kind", reproduction.KINDS)
def test_output_hash_and_size_are_checked_not_just_input_json(sample, kind):
    manifest = read(sample["path"])
    manifest["entries"][kind]["outputs"]["md"]["sha256"] = "0" * 64
    write_manifest(sample, manifest)
    with pytest.raises(ValueError, match="rendered numeric/Markdown/JSON"):
        run(sample)


@pytest.mark.parametrize("kind,path", (
    ("diagnostics", "/context/metric_units"),
    ("mode4", "/payload/family/metric_contract_id"),
    ("mode5", "/summary/objective_unit"),
    ("winner", "/annual_summary/measures/net_return/unit"),
))
def test_unit_contract_is_not_silently_relabelled(sample, kind, path):
    manifest = read(sample["path"])
    manifest["entries"][kind]["values"][path] = "percent_instead_of_declared_contract"
    write_manifest(sample, manifest)
    with pytest.raises(ValueError, match="exact retained value"):
        run(sample)


def test_rehashed_diagnostic_input_cannot_silently_replace_original_numeric_report(sample):
    change_input(sample, "diagnostics", lambda value: value["observations"][0].update(activity_count=9))
    with pytest.raises(ValueError, match="rebuilt report identity"):
        run(sample)


def test_rehashed_fold_observation_with_stale_effect_or_source_identity_is_rejected(sample):
    def mutate(value):
        value["payload"]["rows"][0]["policies"]["applied"]["observations"]["selected_forward"]["raw_sharpe"] = 99.
    change_input(sample, "mode4", mutate)
    with pytest.raises(ValueError, match="altered|identity"):
        run(sample)


def test_rehashed_fold_summary_cannot_replace_reduction(sample):
    def mutate(value):
        value["summary"]["cohorts"]["all_calendar"]["policies"]["applied"]["helped"] = 2
    change_input(sample, "mode4", mutate)
    with pytest.raises(ValueError, match="altered report summary"):
        run(sample)


def test_legacy_raw_sharpe_cannot_be_substituted_for_selector_objective(sample):
    def mutate(value):
        runtime = value["runtime"]
        chosen = runtime["decision"]["chosen_candidate"]
        row = next(row for row in runtime["trial_ledger"] if row["candidate_id"] == chosen and row.get("components"))
        row["objective"] = row["raw_sharpe"]
    change_input(sample, "mode5", mutate)
    with pytest.raises(ValueError, match="objective|score"):
        run(sample)


def test_rehashed_winner_identity_cannot_certify_different_original_decision(sample):
    def mutate(value):
        value["subject"]["candidate_id"] = "other-candidate"
    change_input(sample, "winner", mutate)
    with pytest.raises(ValueError, match="winner identity|original decision"):
        run(sample)


@pytest.mark.parametrize("kind", ("diagnostics", "mode4", "winner"))
def test_permission_narrowing_is_rechecked_instead_of_trusting_readable_files(sample, kind):
    manifest = read(sample["path"])
    manifest["access"][kind]["cutoff_ns"] = 0
    write_manifest(sample, manifest)
    with pytest.raises(PermissionError, match="future|immature|policy|snapshot|evidence|source-bound"):
        run(sample)


def test_changed_report_owner_bytes_are_not_qualified_by_old_manifest(sample):
    manifest = read(sample["path"])
    manifest["owners"][reproduction.OWNERS[0]] = "f" * 64
    write_manifest(sample, manifest)
    with pytest.raises(ValueError, match="owner bytes"):
        run(sample)


@pytest.mark.parametrize("change", ("missing", "claim", "real", "path", "values"))
def test_incomplete_or_inflated_scope_cannot_emit_terminal_receipt(sample, change):
    manifest = read(sample["path"])
    if change == "missing":
        del manifest["entries"]["winner"]
    elif change == "claim":
        manifest["twelve_phase_reports_rebuilt"] = True
    elif change == "real":
        manifest["evidence_classification"] = "ACTUAL_MARKET_EXPERIMENT"
    elif change == "path":
        manifest["entries"]["mode4"]["file"] = "../mode4-input.json"
    else:
        manifest["entries"]["winner"]["values"] = {}
    write_manifest(sample, manifest)
    with pytest.raises(ValueError):
        run(sample)
    assert not sample["output"].exists()


def test_duplicate_keys_nonfinite_and_oversized_inputs_fail_closed(sample, monkeypatch):
    with pytest.raises(ValueError, match="duplicate"):
        reproduction._strict_json('{"x":1,"x":2}')
    with pytest.raises(ValueError, match="nonfinite"):
        reproduction._strict_json('{"x":NaN}')
    monkeypatch.setattr(reproduction, "MAX_TOTAL_BYTES", 1)
    with pytest.raises(ValueError, match="bundle budget"):
        run(sample)


def test_symlinked_input_or_output_is_not_followed(sample):
    manifest = read(sample["path"])
    path = sample["path"].parent / manifest["entries"]["mode4"]["file"]
    backup = path.with_suffix(".saved")
    path.rename(backup)
    path.symlink_to(backup)
    with pytest.raises(ValueError, match="non-symlink"):
        run(sample)
    path.unlink()
    backup.rename(path)
    sample["output"].symlink_to(sample["path"].parent, target_is_directory=True)
    with pytest.raises(ValueError, match="symlink"):
        run(sample)


def test_failed_partial_write_leaves_no_terminal_receipt_and_no_overwrite(sample, monkeypatch):
    original = Path.open
    def fail(path, *args, **kwargs):
        if path == sample["output"] / "mode4.json" and args == ("xb",):
            raise OSError("synthetic disk write interruption")
        return original(path, *args, **kwargs)
    with monkeypatch.context() as scope:
        scope.setattr(Path, "open", fail)
        with pytest.raises(OSError, match="write interruption"):
            run(sample)
    assert (sample["output"] / "diagnostics.json").is_file()
    assert not (sample["output"] / "reproduction.json").exists()
    with pytest.raises(FileExistsError):
        run(sample)


def test_custody_change_during_rendering_has_no_terminal_receipt(sample, monkeypatch):
    original = reproduction._render
    def changing(report, kind):
        output = original(report, kind)
        if kind == "winner":
            path = sample["path"].parent / "diagnostics-input.json"
            path.write_bytes(path.read_bytes() + b"\n")
        return output
    monkeypatch.setattr(reproduction, "_render", changing)
    with pytest.raises(ValueError, match="input changed during reproduction"):
        run(sample)
    assert not (sample["output"] / "reproduction.json").exists()


def test_tripwires_forbid_finance_search_and_fit_and_restore_original_entries():
    from quantbt import QuantBTEndpoint
    from quantbt.optimization.meta_selection.model import RidgeLearner
    import optuna
    before = QuantBTEndpoint.backtest
    with reproduction.no_execution():
        for callback in (QuantBTEndpoint.backtest, QuantBTEndpoint.simulate, optuna.create_study,
                optuna.study.Study.ask, RidgeLearner.fit):
            with pytest.raises(RuntimeError, match="must not execute"):
                callback()
    assert QuantBTEndpoint.backtest is before


def test_original_evidence_rng_and_owner_bytes_are_unchanged(sample):
    original = {path.name: sha256(path.read_bytes()).hexdigest() for path in sample["path"].parent.iterdir()}
    py_state, np_state = random.getstate(), np.random.get_state()
    owners = reproduction._owners()
    run(sample)
    assert reproduction._owners() == owners
    assert {path.name: sha256(path.read_bytes()).hexdigest() for path in sample["path"].parent.iterdir()} == original
    assert random.getstate() == py_state
    after = np.random.get_state()
    assert after[0] == np_state[0] and after[2:] == np_state[2:]
    np.testing.assert_array_equal(after[1], np_state[1])


def test_operations_inventory_targets_exist_without_importing_or_running_them():
    for group, targets in reproduction.OPERATIONS_TARGETS.items():
        assert group and targets
        for target in targets:
            relative, function = target.split("::")
            tree = ast.parse((ROOT / relative).read_text(encoding="utf-8"))
            assert function in {node.name for node in tree.body if isinstance(node, ast.FunctionDef)}, target


def test_scope_and_privacy_are_not_inferred_from_an_economic_result(inputs, tmp_path):
    incomplete = deepcopy(inputs)
    del incomplete["reports"]["winner"]
    with pytest.raises(ValueError, match="four representative reports"):
        reproduction.seal_synthetic(tmp_path / "partial", **incomplete)
    narrower = dict(inputs, access={**inputs["access"], "diagnostics":
        replace(inputs["access"]["diagnostics"], roles=("development",))})
    with pytest.raises(PermissionError, match="public synthetic"):
        reproduction.seal_synthetic(tmp_path / "real-input", **narrower)
    assert not (tmp_path / "partial").exists() and not (tmp_path / "real-input").exists()
