"""Mocked/static wiring negatives only; no build, install, native run or search."""

import ast
from fnmatch import fnmatchcase
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import subprocess
import sys
import tarfile
from types import SimpleNamespace
from zipfile import ZipFile

import pytest

from tools import m5_12_consumer_artifacts as artifacts
from tools.m5_12_consumer_budget import OptimizerBudget
from tools import m5_12_consumer_matrix as matrix
from tools import m5_12_consumer_runtime as runtime
from tools import m5_12_installed_preflight as preflight


ROOT = Path(__file__).resolve().parents[1]


def passed_roster():
    ids = [node + (f"[case-{number}]" if count > 1 else "")
           for node, count in matrix.selectors().items() for number in range(count)]
    reports = {node: dict(setup="passed", call="passed", teardown="passed") for node in ids}
    return ids, reports


def test_every_feature_is_required_with_real_non_skipped_phases():
    ids, reports = passed_roster()
    actual = matrix.validate_outcomes(ids, reports)
    assert set(actual) == {"diagnostics", "calibration", "winner", "donor", "reporting_v1", "acc_account", "acc_options"}
    assert sum(row["tests"] for row in actual.values()) == 44
    assert len(matrix.selectors()) == sum(len(nodes) for nodes in matrix.FEATURES.values())


@pytest.mark.parametrize("defect", ["missing", "duplicate", "unknown", "not-run", "skipped", "xfail", "failed", "no-teardown"])
def test_incomplete_or_skipped_feature_never_passes(defect):
    ids, reports = passed_roster()
    if defect == "missing":
        reports.pop(ids.pop())
    elif defect == "duplicate":
        ids.append(ids[0])
    elif defect == "unknown":
        ids.append("unapproved.py::test_extra")
    elif defect == "not-run":
        reports.pop(ids[0])
    elif defect == "no-teardown":
        reports[ids[0]].pop("teardown")
    else:
        reports[ids[0]]["call"] = defect
    with pytest.raises(ValueError):
        matrix.validate_outcomes(ids, reports)


def test_fixture_allowlist_is_public_exists_and_has_no_checkout_runtime():
    assert len(set(matrix.FIXTURES.values())) == len(matrix.FIXTURES)
    for source, target in matrix.FIXTURES.items():
        assert (ROOT / source).is_file()
        assert Path(source).parts[0] in {"tools", "tests", "examples"}
        assert Path(target).parts[0] in {"tools", "tests", "examples"}
        assert ".." not in Path(target).parts
    for node in matrix.selectors():
        source, function = node.split("::")
        tree = ast.parse((ROOT / source).read_text())
        assert function in {n.name for n in tree.body if isinstance(n, ast.FunctionDef)}
    tree = ast.parse((ROOT / "tools/m5_12_consumer_fixtures.py").read_text())
    assert all(not (n.module or "").startswith("tools.") for n in ast.walk(tree) if isinstance(n, ast.ImportFrom))


def test_workflow_current_branch_shared_paths_step_order_and_retention():
    text = (ROOT / ".github/workflows/qms-candidate.yml").read_text()
    assert "branches: [feat/mode5-diagnostics-first]" in text
    assert "feat/meta-selection-samplers" not in text
    assert "paths: &m512_candidate_paths" in text and "paths: *m512_candidate_paths" in text
    paths = [line.strip().removeprefix('- "').removesuffix('"') for line in
             text.split("paths: &m512_candidate_paths", 1)[1].split("  pull_request:", 1)[0].splitlines()
             if line.strip().startswith('- "')]
    for name in (
        "src/quantbt/diagnostics/calibration/donors.py", "src/quantbt/mode5/runtime.py",
        "src/quantbt/metrics/reporting/public.py", "src/quantbt/options/endpoint_validation.py",
        "src/quantbt/backends/native_option_accounting.py", "examples/mode5_cross_mode_qualification.py",
        "examples/reporting_metrics_v1.py", "tools/m5_12_installed_preflight.py",
        "tools/account_metrics_source_guard.py", "tools/public_inventory_source_amendment.py",
        "tests/test_m5_12_consumer_wiring.py",
        "docs/metrics/PUBLIC_REPORTING.md",
        "docs/maintenance/evidence/pre-m512-source-amendment.json",
    ):
        assert any(fnmatchcase(name, pattern) for pattern in paths), name
    assert text.index("tools.qms08_package --release-pair") < text.index("tools.qms_installed_execution --lane")
    assert text.index("tools.qms_installed_execution --lane") < text.index("tools.m5_12_installed_preflight --lane")
    assert "installed-m5-12-proof.json" in text and "installed-m5-12-proof/*" in text
    assert 'if: always()' in text and "m5-12-preflight.log" in text


def test_inventory_includes_resources_and_rejects_links(tmp_path):
    (tmp_path / "__init__.py").write_text("value = 1\n")
    (tmp_path / "schema.json").write_text('{"version": 1}\n')
    (tmp_path / "py.typed").write_text("")
    (tmp_path / "__pycache__").mkdir()
    (tmp_path / "__pycache__/ignored.pyc").write_bytes(b"cache")
    assert set(runtime.inventory(tmp_path)) == {"__init__.py", "schema.json", "py.typed"}
    (tmp_path / "alias.py").symlink_to(tmp_path / "__init__.py")
    with pytest.raises(ValueError, match="symlink"):
        runtime.inventory(tmp_path)


@pytest.mark.parametrize("defect", [None, "outside", "bytes", "spec", "search-path", "no-origin"])
def test_actual_loaded_paths_are_checked_not_just_version_labels(tmp_path, monkeypatch, defect):
    package = "_m512_test_package"
    root = tmp_path / package
    root.mkdir()
    path = root / "__init__.py"
    path.write_text("value = 1\n")
    expected = runtime.inventory(root)
    module = SimpleNamespace(__file__=str(path), __spec__=SimpleNamespace(origin=str(path)), __path__=[str(root)])
    if defect == "outside":
        module.__file__ = str(tmp_path / "checkout.py")
    elif defect == "bytes":
        path.write_text("value = 2\n")
    elif defect == "spec":
        module.__spec__.origin = str(tmp_path / "checkout.py")
    elif defect == "search-path":
        module.__path__.append(str(tmp_path / "checkout"))
    elif defect == "no-origin":
        module.__file__ = None
    monkeypatch.setitem(sys.modules, package, module)
    if defect:
        with pytest.raises(ValueError):
            runtime.check_loaded({package: root}, {package: expected})
    else:
        assert runtime.check_loaded({package: root}, {package: expected}) == {package: str(path)}


def archive_case(tmp_path, monkeypatch):
    root = tmp_path / "repository"
    source = root / "src/quantbt"
    source.mkdir(parents=True)
    files = {"__init__.py": b'__version__ = "1.1.2"\n', "py.typed": b"", "schema.json": b'{"version":1}\n'}
    for name, payload in files.items():
        (source / name).write_bytes(payload)
    lane = root / ".maturin/qms08/cp312"
    dist = lane / "dist"
    dist.mkdir(parents=True)
    wheel, sdist, native = (dist / "quantbt_engine-1.1.2-py3-none-any.whl",
        dist / "quantbt_engine-1.1.2.tar.gz", dist / "quantbt_native-0.4.3-cp312-linux_x86_64.whl")
    def metadata(name, version):
        return f"Name: {name}\nVersion: {version}\n".encode()
    with ZipFile(wheel, "w") as archive:
        for name, payload in files.items():
            archive.writestr("quantbt/" + name, payload)
        archive.writestr("quantbt_engine-1.1.2.dist-info/METADATA", metadata("quantbt-engine", "1.1.2"))
    with ZipFile(native, "w") as archive:
        archive.writestr("_quantbt_native/__init__.py", b"# synthetic wrapper\n")
        archive.writestr("_quantbt_native/_quantbt_native.so", b"SYNTHETIC_NOT_EXECUTABLE")
        archive.writestr("quantbt_native-0.4.3.dist-info/METADATA", metadata("quantbt-native", "0.4.3"))
    with tarfile.open(sdist, "w:gz") as archive:
        for name, payload in {**{"src/quantbt/" + n: p for n, p in files.items()},
                              "PKG-INFO": metadata("quantbt-engine", "1.1.2")}.items():
            info = tarfile.TarInfo("quantbt_engine-1.1.2/" + name)
            info.size = len(payload)
            archive.addfile(info, BytesIO(payload))
    monkeypatch.setattr(artifacts, "ROOT", root)
    monkeypatch.setattr(artifacts, "declared_pair", lambda: ("1.1.2", "0.4.3"))
    monkeypatch.setattr(artifacts, "verify_pair", lambda proof: True)
    monkeypatch.setattr(artifacts, "inspect_artifact", lambda path: [])
    proof = dict(schema="qms-release-installed-pair-v1", artifact_refs=[
        dict(path=str(p.relative_to(root)), sha256=runtime.digest(p), bytes=p.stat().st_size)
        for p in (wheel, sdist, native)])
    return root, lane, proof


@pytest.mark.parametrize("defect", [None, "historical", "missing", "duplicate", "hash", "source", "metadata", "privacy"])
def test_exact_archive_manifest_fails_closed(tmp_path, monkeypatch, defect):
    root, lane, proof = archive_case(tmp_path, monkeypatch)
    if defect == "historical":
        proof["schema"] = "qms08-installed-candidate-v1"
    elif defect == "missing":
        proof["artifact_refs"].pop()
    elif defect == "duplicate":
        proof["artifact_refs"][-1] = proof["artifact_refs"][0]
    elif defect == "hash":
        proof["artifact_refs"][0]["sha256"] = "0" * 64
    elif defect == "source":
        (root / "src/quantbt/schema.json").write_text('{"version":2}\n')
    elif defect == "metadata":
        monkeypatch.setattr(artifacts, "declared_pair", lambda: ("1.1.3", "0.4.3"))
    elif defect == "privacy":
        monkeypatch.setattr(artifacts, "inspect_artifact", lambda path: ["private content"])
    if defect:
        with pytest.raises(ValueError):
            artifacts.artifact_manifest(proof, lane)
    else:
        result = artifacts.artifact_manifest(proof, lane)
        assert set(result["core_inventory"]) == {"__init__.py", "py.typed", "schema.json"}
        assert result["native_extension_sha256"] == sha256(b"SYNTHETIC_NOT_EXECUTABLE").hexdigest()


@pytest.mark.parametrize("name", ["/absolute", "../parent", "quantbt/../../escape"])
def test_unsafe_archive_members_are_rejected(name):
    with pytest.raises(ValueError):
        artifacts.unique_members([(name, b"fixture")])


def test_duplicate_archive_members_are_rejected():
    with pytest.raises(ValueError):
        artifacts.unique_members([("quantbt/a.py", b"1"), ("quantbt/a.py", b"2")])


@pytest.mark.parametrize("defect", [None, "checkout", "missing", "changed"])
def test_fixture_origins_are_staged_not_source_examples(tmp_path, monkeypatch, defect):
    relative = "examples/synthetic.py"
    path = tmp_path / relative
    path.parent.mkdir()
    path.write_text("# public synthetic fixture\n")
    manifest = dict(fixtures={relative: runtime.digest(path)})
    origin = str(path) if defect != "checkout" else str(tmp_path / "checkout/examples/synthetic.py")
    if defect != "missing":
        monkeypatch.setitem(sys.modules, "m512_fixture_origin", SimpleNamespace(__file__=origin))
    if defect == "changed":
        path.write_text("# changed fixture\n")
    required = {"m512_fixture_origin": relative}
    if defect:
        with pytest.raises(ValueError):
            runtime.fixture_origins(manifest, tmp_path, required)
    else:
        assert runtime.fixture_origins(manifest, tmp_path, required) == {"m512_fixture_origin": str(path)}


def execution_case():
    summary = dict(schema="quantbt.synthetic_cross_mode_run.v1", status="COMPLETED_SYNTHETIC_MECHANICS",
        work={arm: dict(proposals=4, financial_invocations=count) for arm, count in
              (("mode4", 11), ("baseline", 6), ("challenger", 6))},
        observed_proposals=12, observed_financial_invocations=23, financial_invocation_ceiling=23,
        baseline_warm_start_attempts=0, challenger_warm_start_attempts=1, challenger_attempts=4,
        donor_evidence_ids=["mode4-fold-0"], archive_score_dispositions={
            "mode4-fold-0": "TARGETED_EXECUTION_REQUIRED", "mode4-fold-1": "TARGETED_EXECUTION_REQUIRED"},
        donor_plan_id="a" * 64, baseline_winner_id="b" * 64, challenger_winner_id="c" * 64,
        winner_report_id="d" * 64, economic_superiority="NOT_QUALIFIED",
        independent_validation="NOT_PERFORMED", automatic_routing=False, deployment_authorized=False)
    raw = json.dumps(summary, sort_keys=True)
    execution = dict(summary=summary, summary_json=raw, summary_sha256=sha256(raw.encode()).hexdigest(),
        protocol=dict(proposal_slots=12, financial_invocation_ceiling=23, donor_folds=[0],
                      retries=0, automatic_routing=False),
        reconciliation_statuses=dict(baseline="RECONCILED_RETAINED_RUN", challenger="RECONCILED_RETAINED_RUN"),
        winner_baseline_status="SOURCE_BOUND_SELECTED_PATHS", winner_report_id="d" * 64,
        winner_candidate_id="c" * 64, baseline_candidate_id="b" * 64,
        planned_donor_params=[dict(period=8)], applied_donor_params=[dict(period=8)], donor_sources=["warm_start"],
        continuous_snapshot_checks={arm: dict(query_count=4, protocols=["copy", "deepcopy", "pickle4", "pickle5"])
                                    for arm in ("baseline", "challenger")})
    optimizer = dict(execution_case=matrix.EXECUTION_CASE, execution_cases=1, proposal_limit=12,
        financial_limit=23, create_study_calls=4, optimize_trials=[2, 2], ask_calls=12,
        tell_calls=8, walkforward_runs=3, forbidden_calls=[], observed_proposals=12)
    return execution, optimizer


def row_case(tmp_path):
    prefix = tmp_path / "pair"
    version = ".".join(map(str, sys.version_info[:2]))
    site = prefix / "lib" / ("python" + version) / "site-packages"
    loaded, inventories = {}, {"quantbt": {"py.typed": sha256(b"").hexdigest()}, "_quantbt_native": {}}
    for name in matrix.REQUIRED_MODULES:
        package, *parts = name.split(".")
        relative = "/".join(parts) + (".so" if package == "_quantbt_native" else ".py")
        if not parts:
            relative = "__init__.py"
        path = site / package / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"synthetic-not-executed")
        loaded[name] = str(path)
        inventories[package][relative] = runtime.digest(path)
    native = loaded["_quantbt_native._quantbt_native"]
    manifest = dict(core="1.1.2", native="0.4.3", interpreter="cp" + version.replace(".", ""),
        python_version=version, run_id="fresh-run", prefixes={"pair": str(prefix)},
        stages={"pair": str(tmp_path / "external/pair/harness")},
        core_inventory=inventories["quantbt"], native_inventory=inventories["_quantbt_native"],
        source=dict(current_commit="a" * 40, provenance=dict(financial_source_changed=True, artifacts_qualified=False)),
        native_extension_sha256=runtime.digest(native))
    ids, reports = passed_roster()
    execution, optimizer = execution_case()
    row = dict(schema="m5-12-installed-consumer-v1", kind="pair", run_id="fresh-run", manifest_sha256="request",
        source_commit=manifest["source"]["current_commit"],
        source_provenance_sha256=preflight.source_digest(manifest["source"]),
        fixture_modules={name: str(Path(manifest["stages"]["pair"]) / relative)
                         for name, relative in matrix.REQUIRED_FIXTURE_MODULES.items()},
        features=matrix.validate_outcomes(ids, reports), collected=ids, reports=reports,
        cwd=str(tmp_path / "external/pair"), harness=manifest["stages"]["pair"],
        skipped=0, optimizer=optimizer, execution=execution,
        execution_sha256=sha256(matrix.execution_bytes(execution)).hexdigest(),
        publication=False, empirical_promotion=False, defaults_activated=False,
        identity=dict(core="1.1.2", native="0.4.3", prefix=str(prefix), interpreter=manifest["interpreter"],
            core_origin=str(site / "quantbt"), native_origin=native, native_sha256=runtime.digest(native),
            loaded_modules=loaded, resources={"py.typed": sha256(b"").hexdigest()},
            core_files=len(inventories["quantbt"]), native_files=len(inventories["_quantbt_native"])))
    return row, manifest


@pytest.mark.parametrize("defect", [None, "nonce", "request", "source", "skip", "optimizer", "native", "origin", "loaded", "resource", "version", "default"])
def test_parent_revalidates_actual_receipt_not_self_reported_pass(tmp_path, defect):
    row, manifest = row_case(tmp_path)
    if defect == "nonce":
        row["run_id"] = "stale-run"
    elif defect == "request":
        row["manifest_sha256"] = "old-request"
    elif defect == "source":
        row["source_provenance_sha256"] = "old-source"
    elif defect == "skip":
        row["reports"][row["collected"][0]]["call"] = "skipped"
    elif defect == "optimizer":
        row["optimizer"]["ask_calls"] = 13
    elif defect == "native":
        Path(row["identity"]["native_origin"]).write_bytes(b"other-extension")
    elif defect == "origin":
        row["identity"]["core_origin"] = str(tmp_path / "checkout/src/quantbt")
    elif defect == "loaded":
        row["identity"]["loaded_modules"].pop("quantbt.diagnostics.winner.report")
    elif defect == "resource":
        row["identity"]["resources"] = {}
    elif defect == "version":
        row["identity"]["core"] = "1.1.1"
    elif defect == "default":
        row["defaults_activated"] = True
    if defect:
        with pytest.raises(ValueError):
            preflight.validate_row(row, manifest, "pair", "request")
    else:
        preflight.validate_row(row, manifest, "pair", "request")


@pytest.mark.parametrize("existing", ["installed-m5-12-proof.json", "installed-m5-12-proof"])
def test_existing_pass_or_failed_scratch_is_never_reused(tmp_path, monkeypatch, existing):
    monkeypatch.setattr(preflight, "ROOT", tmp_path)
    lane = tmp_path / ".maturin/qms08" / ("cp" + "".join(map(str, sys.version_info[:2])))
    lane.mkdir(parents=True)
    (lane / existing).write_text("stale receipt or failed scratch")
    with pytest.raises(ValueError, match="never reuse PASS"):
        preflight.qualify(lane)


@pytest.mark.parametrize("failure", ["exit", "timeout"])
def test_failed_child_retains_logs_without_pass_and_has_no_checkout_cwd(tmp_path, monkeypatch, failure):
    root = tmp_path / "repo"
    lane = root / ".maturin/qms08" / ("cp" + "".join(map(str, sys.version_info[:2])))
    for kind in ("pair", "sdist"):
        (lane / kind / "bin").mkdir(parents=True)
        (lane / kind / "pyvenv.cfg").write_text("synthetic mocked environment")
        (lane / kind / "bin/python").write_text("not executable")
    (lane / "proof.json").write_text("{}")
    monkeypatch.setattr(preflight, "ROOT", root)
    monkeypatch.setattr(preflight, "artifact_manifest", lambda proof, lane: {})
    monkeypatch.setattr(preflight, "source_manifest", lambda: {})
    monkeypatch.setattr(preflight, "fixture_manifest", lambda: {})
    monkeypatch.setattr(preflight, "verifier_manifest", lambda: {})
    monkeypatch.setattr(preflight, "FIXTURES", {})
    monkeypatch.setattr(preflight.tempfile, "mkdtemp", lambda **kwargs: str(tmp_path / "external"))
    monkeypatch.setenv("PYTHONPATH", str(root / "src"))
    monkeypatch.setenv("PYTEST_ADDOPTS", "--ignore-everything")

    def child(command, **kwargs):
        assert "-I" in command and "-B" in command and "-X" in command
        assert not Path(kwargs["cwd"]).is_relative_to(root)
        assert "PYTHONPATH" not in kwargs["env"] and "PYTEST_ADDOPTS" not in kwargs["env"]
        assert kwargs["env"]["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] == "1"
        if failure == "timeout":
            raise subprocess.TimeoutExpired(command, 1200, output=b"PARTIAL", stderr=b"TIMEOUT")
        return SimpleNamespace(returncode=1, stdout="PARTIAL", stderr="FAILED")

    monkeypatch.setattr(preflight.subprocess, "run", child)
    with pytest.raises(ValueError):
        preflight.qualify(lane)
    assert not (lane / "installed-m5-12-proof.json").exists()
    assert "PARTIAL" in (lane / "installed-m5-12-proof/pair.log").read_text()
    assert json.loads((lane / "installed-m5-12-proof/scratch.json").read_text())["workspace"] == str(tmp_path / "external")


@pytest.mark.parametrize("changed,qualified", [(True, False), (False, False), (True, True)])
def test_current_source_guard_is_called_and_cannot_become_an_old_unchanged_finance_claim(monkeypatch, changed, qualified):
    calls = []
    provenance = dict(financial_source_changed=changed, native_artifacts_qualified=qualified,
        current_source_qualified=True, historical_receipts_unchanged=True, publication=False,
        source_commit="b" * 40, source_tree="exact-tree")

    def verify():
        calls.append("current-source")
        return provenance

    monkeypatch.setitem(sys.modules, "tools.m5_12_source_guard", SimpleNamespace(verify_current_source=verify))
    monkeypatch.setattr(preflight.subprocess, "check_output", lambda *args, **kwargs: "a" * 40 + "\n")
    if changed and not qualified:
        result = preflight.source_manifest()
        assert result == dict(current_commit="a" * 40, artifacts_qualified=False, provenance=provenance)
    else:
        with pytest.raises(ValueError):
            preflight.source_manifest()
    assert calls == ["current-source"]


@pytest.mark.parametrize("defect", [None, "missing-budget", "changed-budget", "ask-overrun",
    "finance-overrun", "missing-summary", "missing-ceiling", "changed-proposals", "work-total",
    "donor", "reconciliation", "stale-bytes"])
def test_bounded_execution_missing_changed_and_overrun_are_rejected(defect):
    execution, optimizer = execution_case()
    if defect == "missing-budget":
        optimizer = None
    elif defect == "changed-budget":
        optimizer["proposal_limit"] = 13
    elif defect == "ask-overrun":
        optimizer["ask_calls"] = 13
    elif defect == "finance-overrun":
        execution["summary"]["observed_financial_invocations"] = 24
    elif defect == "missing-summary":
        execution.pop("summary")
    elif defect == "missing-ceiling":
        execution["protocol"].pop("financial_invocation_ceiling")
    elif defect == "changed-proposals":
        execution["summary"]["observed_proposals"] = 11
    elif defect == "work-total":
        execution["summary"]["work"]["baseline"]["financial_invocations"] = 5
    elif defect == "donor":
        execution["applied_donor_params"] = [dict(period=9)]
    elif defect == "reconciliation":
        execution["reconciliation_statuses"]["challenger"] = "PARTIAL"
    if defect != "stale-bytes" and "summary" in execution:
        execution["summary_json"] = json.dumps(execution["summary"], sort_keys=True)
        execution["summary_sha256"] = sha256(execution["summary_json"].encode()).hexdigest()
    elif defect == "stale-bytes":
        execution["summary_json"] += " "
    if defect:
        with pytest.raises(ValueError):
            matrix.validate_execution(execution, optimizer)
    else:
        matrix.validate_execution(execution, optimizer)


def test_execution_skip_or_missing_record_property_cannot_pass(tmp_path):
    row, manifest = row_case(tmp_path)
    row["reports"][matrix.EXECUTION_CASE]["call"] = "skipped"
    with pytest.raises(ValueError):
        preflight.validate_row(row, manifest, "pair", "request")
    row["reports"][matrix.EXECUTION_CASE]["call"] = "passed"
    row["execution"] = None
    with pytest.raises(ValueError):
        preflight.validate_row(row, manifest, "pair", "request")


@pytest.mark.parametrize("defect", ["missing", "one-arm", "null", "zero", "bool", "protocol"])
def test_missing_or_incomplete_actual_snapshot_roundtrips_are_rejected(defect):
    execution, optimizer = execution_case()
    checks = execution["continuous_snapshot_checks"]
    if defect == "missing":
        execution.pop("continuous_snapshot_checks")
    elif defect == "one-arm":
        checks.pop("challenger")
    elif defect == "null":
        checks["baseline"] = None
    elif defect == "protocol":
        checks["baseline"]["protocols"].pop()
    else:
        checks["baseline"]["query_count"] = True if defect == "bool" else 0
    with pytest.raises(ValueError, match="snapshot roundtrips"):
        matrix.validate_execution(execution, optimizer)


def test_record_property_belongs_only_to_the_named_execution_case():
    outcomes = runtime.Outcomes(matrix.EXECUTION_CASE, matrix.EXECUTION_PROPERTY)
    execution, _ = execution_case()
    report = SimpleNamespace(nodeid="cold.py::test_no_search", when="call", outcome="passed",
        user_properties=[(matrix.EXECUTION_PROPERTY, json.dumps(execution))])
    with pytest.raises(ValueError):
        outcomes.pytest_runtest_logreport(report)
    outcomes = runtime.Outcomes(matrix.EXECUTION_CASE, matrix.EXECUTION_PROPERTY)
    report.nodeid = matrix.EXECUTION_CASE
    outcomes.pytest_runtest_logreport(report)
    assert outcomes.execution == execution


def exercised_mock_budget():
    budget = OptimizerBudget(matrix.EXECUTION_CASE)
    calls = []
    def create_study():
        calls.append("create_study")
        return object()
    def optimize(study, *, n_trials=None, n_jobs=1):
        calls.append(("optimize", n_trials, n_jobs))
        for _ in range(n_trials):
            wrapped["ask"](study)
    def ask(study):
        calls.append("ask")
        return object()
    def tell(study, trial):
        calls.append("tell")
    def walkforward():
        calls.append("walkforward")
    original = dict(create_study=create_study, optimize=optimize, ask=ask, tell=tell, walkforward=walkforward)
    wrapped = {name: budget.wrap(name, function) for name, function in original.items()}
    budget.begin(matrix.EXECUTION_CASE)
    studies = [wrapped["create_study"]() for _ in range(4)]
    for study in studies[:2]:
        wrapped["optimize"](study, n_trials=2)
    for study in studies[2:]:
        for _ in range(4):
            wrapped["tell"](study, wrapped["ask"](study))
    for _ in range(3):
        wrapped["walkforward"]()
    return budget, wrapped, studies, calls


def test_observed_budget_wrappers_call_originals_without_search_emulation():
    budget, _, _, calls = exercised_mock_budget()
    execution, expected = execution_case()
    assert budget.receipt() == expected
    assert calls.count("ask") == 12 and calls.count("tell") == 8
    assert calls.count(("optimize", 2, 1)) == 2 and calls.count("walkforward") == 3
    matrix.validate_execution(execution, budget.receipt())


def test_real_optuna_optimize_internal_asks_are_counted_once():
    import optuna
    class Engine:
        def run(self):
            pass
    budget = OptimizerBudget(matrix.EXECUTION_CASE)
    budget.begin(matrix.EXECUTION_CASE)
    with budget.protect(optuna, Engine):
        study = optuna.create_study()
        study.optimize(lambda trial: trial.suggest_int("x", 0, 1), n_trials=2)
    assert budget.ask_calls == budget.receipt()["observed_proposals"] == 2
    assert budget.optimize_trials == [2] and not budget.forbidden


@pytest.mark.parametrize("attempt", [0, 17, True, "2"])
def test_invalid_attempt_cannot_reuse_outputs(tmp_path, attempt):
    with pytest.raises(ValueError, match="attempt"):
        preflight.qualify(tmp_path, attempt=attempt)


@pytest.mark.parametrize("operation", ["ask", "walkforward", "create_study"])
def test_overrun_is_stopped_before_calling_original(operation):
    budget, wrapped, studies, calls = exercised_mock_budget()
    before = list(calls)
    with pytest.raises(AssertionError):
        wrapped[operation](*([studies[-1]] if operation == "ask" else []))
    assert calls == before and budget.forbidden


@pytest.mark.parametrize("node", [None, "tools/m5_12_consumer_features.py::test_cold_calibration",
                                  matrix.EXECUTION_CASE + "[unapproved]"])
def test_only_precise_execution_call_can_reach_optimizer_original(node):
    budget = OptimizerBudget(matrix.EXECUTION_CASE)
    called = []
    if node is not None:
        budget.begin(node)
    with pytest.raises(AssertionError):
        budget.wrap("create_study", lambda: called.append(True))()
    assert called == [] and budget.forbidden


@pytest.mark.parametrize("trials,jobs", [(None, 1), (3, 1), (2, 2)])
def test_missing_changed_or_parallel_optimize_budget_never_calls_original(trials, jobs):
    budget = OptimizerBudget(matrix.EXECUTION_CASE)
    budget.begin(matrix.EXECUTION_CASE)
    study = budget.wrap("create_study", object)()
    calls = []
    def optimize(study, *, n_trials=None, n_jobs=1):
        calls.append(True)
    with pytest.raises(AssertionError):
        budget.wrap("optimize", optimize)(study, n_trials=trials, n_jobs=jobs)
    assert not calls and budget.forbidden


@pytest.mark.parametrize("kind", [None, "pair", "sdist"])
def test_kind_scope_requires_only_selected_environments_and_seals_distinct_receipt(tmp_path, monkeypatch, kind):
    root = tmp_path / "repo"
    lane = root / ".maturin/qms08" / ("cp" + "".join(map(str, sys.version_info[:2])))
    kinds = [kind] if kind else ["pair", "sdist"]
    for name in kinds:
        (lane / name / "bin").mkdir(parents=True)
        (lane / name / "pyvenv.cfg").write_text("mocked")
        (lane / name / "bin/python").write_text("not executable")
    (lane / "proof.json").write_text("{}")
    monkeypatch.setattr(preflight, "ROOT", root)
    monkeypatch.setattr(preflight, "source_manifest", lambda: {})
    monkeypatch.setattr(preflight, "artifact_manifest", lambda proof, lane: {})
    monkeypatch.setattr(preflight, "fixture_manifest", lambda: {})
    monkeypatch.setattr(preflight, "verifier_manifest", lambda: {})
    monkeypatch.setattr(preflight, "FIXTURES", {})
    monkeypatch.setattr(preflight, "validate_row", lambda *args: None)
    monkeypatch.setattr(preflight.tempfile, "mkdtemp", lambda **kwargs: str(tmp_path / "external"))
    called = []
    def child(command, **kwargs):
        name = command[command.index("--kind") + 1]
        assert command[0] == str(lane / name / "bin/python") and name in kinds
        called.append(name)
        output = Path(command[command.index("--output") + 1])
        execution, _ = execution_case()
        execution_output = output.with_name(name + "-execution.json")
        execution_output.write_bytes(matrix.execution_bytes(execution))
        output.write_text(json.dumps(dict(execution=execution, execution_sha256=runtime.digest(execution_output))))
        return SimpleNamespace(returncode=0, stdout="mocked", stderr="")
    monkeypatch.setattr(preflight.subprocess, "run", child)
    receipt = preflight.qualify(lane, kind=kind)
    assert called == kinds and receipt["kinds"] == kinds and set(receipt["consumers"]) == set(kinds)
    assert receipt["complete_pair"] is (kind is None)
    assert receipt["proof_scope"] == ("single_artifact_consumer" if kind else "wheel_and_sdist_consumers")
    basename = "installed-m5-12" + ("-" + kind if kind else "") + "-proof"
    assert (lane / (basename + ".json")).is_file()
    if kind:
        assert not (lane / ("sdist" if kind == "pair" else "pair")).exists()
        assert not (lane / "installed-m5-12-proof.json").exists()
    with pytest.raises(ValueError, match="never reuse PASS"):
        preflight.qualify(lane, kind=kind)
