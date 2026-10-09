"""M5T-001..010: synthetic/source controls, not private-alpha economics."""

from copy import deepcopy
from hashlib import sha256
import io
import ast
import re
import stat
import tarfile
import zipfile

import pytest

from tools.check_release_artifacts import inspect_artifact
from tools.mode5_baseline.cleanup import cleanup_workspace
from tools.mode5_baseline.evidence import (
    duplicate_decisions, interval_record, load_json, metric_availability,
    sampler_observation, spec_table_errata,
)
from tools.mode5_baseline.inventory import NEW_SELECTORS, binding_map, compatibility_key
from tools.mode5_baseline.isolation import (
    canonical_digest, copy_python_tree, copy_reviewed_files, extract_reviewed_zip, file_identity,
    private_output, write_json, zip_manifest,
)
from tools.mode5_baseline.registration import authorize_economic_run, study_registration
from tools.mode5_baseline.runner import ROOT, archive_inventory, expected_inputs, verify_snapshot


@pytest.mark.parametrize("member", ["../escape.py", "/absolute.py", "C:/escape.py",
                                     "..\\escape.py", "a/../../escape.py", "input-manifest.json",
                                     "input-manifest.json/child.py"])
def test_m5t_001_archive_path_rejected_before_any_output(tmp_path, member):
    archive = tmp_path / "input.zip"
    with zipfile.ZipFile(archive, "w") as zipped:
        zipped.writestr(member, "do not execute")
    output = tmp_path / "private/attempt"
    with pytest.raises(ValueError):
        extract_reviewed_zip(archive, output, allowed_roots=[tmp_path / "private"])
    assert not output.exists()


def test_m5t_001_symlink_and_file_parent_collisions_fail_closed(tmp_path):
    archive = tmp_path / "input.zip"
    link = zipfile.ZipInfo("link")
    link.create_system = 3
    link.external_attr = (stat.S_IFLNK | 0o777) << 16
    with zipfile.ZipFile(archive, "w") as zipped:
        zipped.writestr(link, "../source")
    with pytest.raises(ValueError, match="links"):
        zip_manifest(archive)
    with zipfile.ZipFile(archive, "w") as zipped:
        zipped.writestr("parent", "file")
        zipped.writestr("parent/child.py", "child")
    with pytest.raises(ValueError, match="collision"):
        zip_manifest(archive)


def test_m5t_001_limits_and_duplicate_names(tmp_path):
    archive = tmp_path / "input.zip"
    with zipfile.ZipFile(archive, "w") as zipped:
        zipped.writestr("x.py", "12345")
    with pytest.raises(ValueError, match="budget"):
        zip_manifest(archive, max_bytes=4)
    with zipfile.ZipFile(archive, "w") as zipped:
        zipped.writestr("a//b.py", "a")
        zipped.writestr("a/b.py", "b")
    with pytest.raises(ValueError, match="duplicate"):
        zip_manifest(archive)


def test_m5t_001_manifest_before_copy_and_no_bytecode(tmp_path):
    archive = tmp_path / "input.zip"
    with zipfile.ZipFile(archive, "w") as zipped:
        zipped.writestr("pkg/alpha.py", "raise RuntimeError('must not import')")
        zipped.writestr("pkg/__pycache__/alpha.pyc", b"untrusted-bytecode")
    output = tmp_path / "private/attempt"
    manifest = extract_reviewed_zip(archive, output, allowed_roots=[tmp_path / "private"])
    assert (output / "input-manifest.json").exists()
    assert (output / "pkg/alpha.py").exists()
    assert not (output / "pkg/__pycache__").exists()
    assert manifest["members"][1]["excluded_bytecode"]


def test_m5t_001_protected_or_symlink_output_and_existing_revision(tmp_path):
    source = tmp_path / "protected"
    source.mkdir()
    with pytest.raises(ValueError, match="protected"):
        private_output(source / "child", [tmp_path], [source])
    linked = tmp_path / "alias"
    linked.symlink_to(source, target_is_directory=True)
    with pytest.raises(ValueError, match="symlink"):
        private_output(linked / "child", [tmp_path])
    with pytest.raises(ValueError, match="already exists"):
        private_output(source, [tmp_path])


def test_m5t_002_private_copy_preserves_bytes_without_hardlinks(tmp_path):
    source = tmp_path / "alpha.py"
    source.write_text("raise RuntimeError('do not import')\n")
    before = file_identity(source)
    output = tmp_path / "private/attempt"
    copy_reviewed_files([source], output, allowed_roots=[tmp_path / "private"])
    copied = output / source.name
    assert before == file_identity(source)
    assert copied.stat().st_ino != source.stat().st_ino
    copied.write_text("edited research copy\n")
    verify_snapshot({str(source): before["sha256"]})
    source.write_text("altered original")
    with pytest.raises(ValueError, match="protected source changed"):
        verify_snapshot({str(source): before["sha256"]})


def test_m5t_002_python_tree_preserves_relative_import_layout(tmp_path):
    source = tmp_path / "source"
    (source / "reference").mkdir(parents=True)
    (source / "reference/indicators.py").write_text("# synthetic\n")
    (source / "alpha.py").write_text("# synthetic\n")
    output = tmp_path / "private/attempt"
    copy_python_tree(source, output, allowed_roots=[tmp_path / "private"])
    assert (output / "reference/indicators.py").read_bytes() == (source / "reference/indicators.py").read_bytes()


def test_m5t_002_receipts_are_exclusive_and_guide_original_identity_pinned(tmp_path):
    path = tmp_path / "receipt.json"
    write_json(path, {"revision": 1})
    with pytest.raises(FileExistsError):
        write_json(path, {"revision": 2})
    assert load_json(path) == {"revision": 1}
    guide = ROOT / "upgrade/QUANTBT_MODE5_UPGRADE_V1_DIAGNOSTICS_FIRST_GUIDE_VI.md"
    assert sha256(guide.read_bytes()).hexdigest() == "661a2a3d83eed2b2592bfb98e3b4f8e3aa34bcd9740ec6b50c812f73753b99fe"
    assert {"D0", "D1", "D2", "D3", "BUNDLE", "D4"} <= set(expected_inputs(guide.read_text()))


def test_m5t_002_archive_presence_is_observed_never_inferred(tmp_path):
    path = tmp_path / "input.zip"
    missing = archive_inventory([path], {"sha256": "expected", "bytes": 1}, "synthetic")
    assert missing["observed"] is None
    with zipfile.ZipFile(path, "w") as zipped:
        zipped.writestr("synthetic.py", "# never imported\n")
    expected = file_identity(path)
    found = archive_inventory([path], expected, "synthetic")
    assert found["status"] == "VERIFIED_ORIGINAL_ARCHIVE"
    assert found["observed"][0]["manifest"]["source"] == expected
    with pytest.raises(ValueError, match="identity mismatch"):
        archive_inventory([path], expected | {"sha256": "wrong"}, "synthetic")


def test_m5t_003_errata_is_source_linked_and_does_not_rewrite_records():
    rows = [{"alpha_id": "SYNTH", "formulation_name": "DRO", "oos_2024_fills": 17,
             "oos_2024_max_dd_pct": -1.0093}]
    old = deepcopy(rows)
    prose = "| SYNTH | DRO | +5.02 | +2.48% | -1.01% | 46 fills |"
    errata = spec_table_errata(prose, rows, source_ref="fixture-spec")
    assert rows == old
    assert errata == [{"kind": "ARTIFACT_DISCREPANCY", "field": "oos_2024_fills",
                       "old_value": 46, "new_value": 17, "prose_pointer": "fixture-spec:L1",
                       "json_pointer": "D3#/0/oos_2024_fills", "status": "RECOMPUTED_FROM_ARTIFACT"}]


@pytest.mark.parametrize("payload", ['{"a":1,"a":2}', '{"x":NaN}', '{"x":Infinity}'])
def test_m5t_003_ambiguous_nonfinite_json_not_silently_parsed(tmp_path, payload):
    path = tmp_path / "original.json"
    path.write_text(payload)
    with pytest.raises(ValueError):
        load_json(path)


def test_m5t_004_actual_shared_factory_reports_resolution_without_claiming_purity():
    from quantbt.optimization.config import SamplerConfig
    from quantbt.optimization.samplers import build_sampler
    for recipe, expected in (("tpe_legacy", "TPESampler"), ("tpe_multivariate_group", "TPESampler"),
                             ("cmaes", "CmaEsSampler"), ("sobol", "QMCSampler")):
        sampler = build_sampler(SamplerConfig(name=recipe), seed=731,
                                search_space={"x": (0.1, 1.0)}, objective_count=1)
        assert type(sampler).__name__ == expected
        row = sampler_observation(recipe, expected, verified=True)
        assert row["requested"] == recipe and row["resolved"] == expected
        assert row["mixed"] is False
    assert sampler_observation("CmaEsSampler", "CmaEsSampler")["mixed"] is None


def test_m5t_004_actual_observer_detects_independent_draws():
    import optuna
    from quantbt.optimization.wfo_study import ObservedSampler
    sampler = ObservedSampler(optuna.samplers.CmaEsSampler(seed=731))
    study = optuna.create_study(sampler=sampler, direction="maximize")
    study.optimize(lambda trial: trial.suggest_float("x", 0.1, 1.0) +
                   float(trial.suggest_categorical("branch", [False, True])), n_trials=3)
    observation = sampler_observation("CmaEsSampler", type(sampler.delegate).__name__, sampler.independent, verified=True)
    assert observation["mixed"] is True
    assert observation["independent_counts"]["branch"] > 0
    assert len(sampler.events) == 6


def test_m5t_005_scored_days_and_warmup_not_a_whole_year():
    row = interval_record({"start": "2024-01-24", "sim_start": "2024-02-01", "end": "2024-03-15"}, reviewed=True)
    assert row["elapsed_scored_days"] == 43.0
    assert row["warmup_days"] == 8.0
    assert row["role"] == "EXPLORATORY_REVIEWED_2024"
    assert row["bars"] is None
    with pytest.raises(ValueError):
        interval_record({"start": "2024-02-01", "sim_start": "2024-01-24", "end": "2024-03-15"})


def test_m5t_006_same_params_keep_decisions_not_independent_executions():
    rows = [{"alpha_id": alpha, "formulation_name": selector, "best_params": {"x": 2}}
            for alpha, selector in (("synthetic", "first"), ("synthetic", "second"), ("other", "first"))]
    result = duplicate_decisions(rows)
    assert len(result["decision_records"]) == 3
    assert result["unique_parameter_vectors"] == 2
    assert result["unique_by_alpha"] == {"synthetic": 1, "other": 1}
    assert result["execution_reuse_authorized"] is False


@pytest.mark.parametrize("field", ["core_sha256", "native_sha256", "module_origin", "data_id",
                                   "clock_id", "economics_id", "alpha_sha256", "terminal_id", "warmup_id"])
def test_m5t_007_same_version_never_overrides_execution_identity(field):
    identity = dict.fromkeys(("core_sha256", "native_sha256", "module_origin", "data_id",
                              "clock_id", "economics_id", "alpha_sha256", "parameter_id", "terminal_id", "warmup_id"), "same")
    changed = identity | {field: "changed", "version": "1.1.2"}
    assert compatibility_key(identity) != compatibility_key(changed)
    with pytest.raises(ValueError):
        compatibility_key(identity | {field: None})


def test_m5t_008_reviewed_data_and_fullset_presets_cannot_be_renamed_untouched():
    registration = study_registration(["SYNTH"], "guide-id")
    assert registration["data_rights"]["reviewed_2024"] == "EXPLORATORY_REVIEWED_2024"
    assert registration["data_rights"]["fullset_presets"] == "REFERENCE_ONLY_SELECTION_ADJUSTED"
    assert registration["data_rights"]["other_history"] == "CONTAMINATION_UNKNOWN_NOT_UNTOUCHED"
    with pytest.raises(ValueError, match="PRECONDITION"):
        authorize_economic_run(registration, "SYNTH")
    changed = deepcopy(registration)
    changed["data_rights"]["reviewed_2024"] = "untouched"
    with pytest.raises(ValueError, match="without revision"):
        authorize_economic_run(changed, "SYNTH")


@pytest.mark.parametrize("metric", ["psr", "tail", "campaign_tail"])
def test_m5t_009_summary_metrics_and_fill_counts_never_invent_raw_moments(metric):
    row = metric_availability({"sharpe": 5, "max_dd": 0.02, "fills": 3}, metric)
    assert row["status"] == "MISSING_REQUIRED_INPUT" and row["value"] is None
    assert row["missing"]


def test_m5t_010_existing_bindings_and_future_selectors_not_fictional_apis():
    from quantbt.walkforward import WalkForwardConfig
    result = binding_map(ROOT)
    assert len(result["bindings"]) == 15
    assert all(row["line"] and row["test_present"] for row in result["bindings"])
    for selector in NEW_SELECTORS:
        with pytest.raises(ValueError):
            WalkForwardConfig(optimization_mode="mode_5_full_robust", candidate_selection_metric=selector)
    for selector in result["legacy_selectors"]:
        config = WalkForwardConfig(optimization_mode="mode_5_full_robust", candidate_selection_metric=selector)
        assert config.candidate_selection_metric == selector


@pytest.mark.parametrize("distribution", ["quantbt_engine-1.1.2", "quantbt_native-0.4.3"])
def test_privacy_alpha_paths_denied_in_both_distribution_sdists(tmp_path, distribution):
    artifact = tmp_path / f"{distribution}.tar.gz"
    with tarfile.open(artifact, "w:gz") as archive:
        member = tarfile.TarInfo(f"{distribution}/upgrade/alphas/synthetic.py")
        payload = b"# synthetic canary, not a private strategy"
        member.size = len(payload)
        archive.addfile(member, io.BytesIO(payload))
    assert any("private/local" in finding for finding in inspect_artifact(artifact))
    assert "prune upgrade/alphas" in (ROOT / "MANIFEST.in").read_text()


@pytest.mark.parametrize("kind", ["core_wheel", "native_wheel", "core_sdist", "native_sdist"])
def test_privacy_renamed_payload_detected_without_disclosing_source(tmp_path, kind):
    payload = b"# synthetic private payload canary\n"
    prefix = "quantbt_native-0.4.3" if kind.startswith("native") else "quantbt_engine-1.1.2"
    if kind.endswith("wheel"):
        artifact = tmp_path / f"{prefix}-py3-none-any.whl"
        name = "_quantbt_native/__init__.py" if kind.startswith("native") else "quantbt/ordinary.py"
        with zipfile.ZipFile(artifact, "w") as archive:
            archive.writestr(name, payload)
    else:
        artifact = tmp_path / f"{prefix}.tar.gz"
        with tarfile.open(artifact, "w:gz") as archive:
            member = tarfile.TarInfo(f"{prefix}/src/ordinary.py")
            member.size = len(payload)
            archive.addfile(member, io.BytesIO(payload))
    findings = inspect_artifact(artifact, private_payload_hashes={sha256(payload).hexdigest()})
    assert any("private research payload" in finding for finding in findings)
    assert all(payload.decode().strip() not in finding for finding in findings)


def test_support_registry_all_five_and_no_zero_defaults():
    roster = ["A-SC", "A-HMA", "A-VWAP", "A-HASH", "A-RSI"]
    registration = study_registration(roster, "guide-id")
    assert set(registration["alpha_support"]) == set(roster)
    assert len(registration["hypotheses"]) == 12
    for alpha in roster:
        assert registration["alpha_support"][alpha]["minimum_fills"] is None
        with pytest.raises(ValueError):
            authorize_economic_run(registration, alpha)


def approved_synthetic_registration():
    registration = study_registration(["synthetic"], "guide-id")
    registration["market_authorized"] = True
    row = registration["alpha_support"]["synthetic"]
    for key in row:
        if row[key] is None:
            row[key] = 1.0 if key.startswith(("min_", "minimum_")) else "synthetic-contract"
    row.update(status="APPROVED", is_start="2020-01-01", is_end="2022-01-01",
               forward_start="2022-01-02", forward_end="2023-01-02")
    registration["registration_id"] = canonical_digest({k: v for k, v in registration.items() if k != "registration_id"})
    return registration


@pytest.mark.parametrize("value", [0.0, -1.0, False, "unresolved"])
def test_support_zero_negative_boolean_or_placeholder_never_unlocks_market(value):
    registration = approved_synthetic_registration()
    registration["alpha_support"]["synthetic"]["minimum_fills"] = value
    registration["registration_id"] = canonical_digest({k:v for k,v in registration.items() if k != "registration_id"})
    with pytest.raises(ValueError, match="SUPPORT"):
        authorize_economic_run(registration, "synthetic")


def test_support_sufficient_and_inadequate_registered_calendars():
    registration = approved_synthetic_registration()
    authorize_economic_run(registration, "synthetic")
    registration["alpha_support"]["synthetic"]["min_scored_forward_days"] = 500.0
    registration["registration_id"] = canonical_digest({k:v for k,v in registration.items() if k != "registration_id"})
    with pytest.raises(ValueError, match="DURATION"):
        authorize_economic_run(registration, "synthetic")


def test_guide_math_oracle_syntax_not_a_market_or_implementation_certificate():
    guide = (ROOT / "upgrade/QUANTBT_MODE5_UPGRADE_V1_DIAGNOSTICS_FIRST_GUIDE_VI.md").read_text()
    appendix = guide.split('<a id="appendix-c"></a>', 1)[1].split('<a id="appendix-d"></a>', 1)[0]
    blocks = re.findall(r"```python\n(.*?)\n```", appendix, re.DOTALL)
    assert blocks
    for block in blocks:
        ast.parse(block)


def test_failed_check_retained_before_cleanup_and_no_following_checks(tmp_path, monkeypatch):
    import subprocess
    from tools.mode5_baseline.runner import run_checks
    output = tmp_path / "receipts"
    output.mkdir()
    scratch = tmp_path / "scratch/attempt"
    calls = []

    def fail(command, **kwargs):
        calls.append(command)
        scratch.mkdir()
        (scratch / "synthetic.tmp").write_text("disposable")
        return subprocess.CompletedProcess(command, 1, "synthetic failure", "")

    monkeypatch.setattr(subprocess, "run", fail)
    with pytest.raises(ValueError, match="check failed"):
        run_checks(output, scratch)
    assert len(calls) == 1
    assert load_json(output / "check-01.json")["exit_code"] == 1
    copies = tmp_path / "copies"
    copies.mkdir()
    plan = {"scratch": str(scratch), "filesystem_free_bytes": 0,
            "incremental_budget_bytes": 1024**2, "minimum_free_bytes": 0}
    before = file_identity(output / "check-01.json")
    cleanup = cleanup_workspace(output, copies, scratch, {}, plan)
    assert not scratch.exists()
    assert file_identity(output / "check-01.json") == before
    assert cleanup["receipts_unchanged"]


def test_check_timeout_preserves_partial_output_and_exit_is_not_pass(tmp_path, monkeypatch):
    import subprocess
    from tools.mode5_baseline.runner import run_checks
    output = tmp_path / "receipts"
    output.mkdir()

    def timeout(command, **kwargs):
        raise subprocess.TimeoutExpired(command, 600, output=b"synthetic partial output", stderr=b"timeout")

    monkeypatch.setattr(subprocess, "run", timeout)
    with pytest.raises(subprocess.TimeoutExpired):
        run_checks(output, tmp_path / "scratch/attempt")
    receipt = load_json(output / "check-01.json")
    assert receipt["status"] == "TIMED_OUT" and receipt["exit_code"] is None
    assert receipt["stdout"] == "synthetic partial output"


def test_cleanup_rejects_unregistered_scratch_and_never_follows_link(tmp_path):
    output, copies, scratch = (tmp_path / name for name in ("output", "copies", "scratch"))
    output.mkdir()
    copies.mkdir()
    scratch.mkdir()
    plan = {"scratch": str(tmp_path / "different"), "filesystem_free_bytes": 0,
            "incremental_budget_bytes": 1024**2, "minimum_free_bytes": 0}
    with pytest.raises(ValueError, match="ownership"):
        cleanup_workspace(output, copies, scratch, {}, plan)
    protected = tmp_path / "protected"
    protected.mkdir()
    (protected / "keep").write_text("original")
    linked = tmp_path / "linked"
    linked.symlink_to(protected, target_is_directory=True)
    plan["scratch"] = str(linked)
    with pytest.raises(ValueError, match="symlink scratch"):
        cleanup_workspace(output, copies, linked, {}, plan)
    assert (protected / "keep").read_text() == "original"


def test_cleanup_budget_failure_still_retains_receipt(tmp_path):
    output, copies, scratch = (tmp_path / name for name in ("output", "copies", "scratch"))
    output.mkdir()
    copies.mkdir()
    scratch.mkdir()
    (output / "proof.txt").write_text("retained")
    plan = {"scratch": str(scratch), "filesystem_free_bytes": 0,
            "incremental_budget_bytes": 1, "minimum_free_bytes": 0}
    with pytest.raises(ValueError, match="budget exceeded"):
        cleanup_workspace(output, copies, scratch, {}, plan)
    assert not scratch.exists()
    assert load_json(output / "cleanup_receipt.json")["receipts_unchanged"]
    assert (output / "proof.txt").read_text() == "retained"
