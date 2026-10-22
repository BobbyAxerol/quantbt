"""Cold installed-proof plumbing negatives; never run native, finance or pytest recursively."""

from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import xml.etree.ElementTree as ET

import pytest

from tools import m5_12_pct_installed as tool


def outcomes():
    ids = [name + "::test_literal_" + str(i) for name, count in tool.MODULES.items() for i in range(count)]
    return ids, {node: dict(setup="passed", call="passed", teardown="passed") for node in ids}, {
        str(tool.ROOT / name): count for name, count in tool.MODULES.items()}


def test_roster_is_additional_exact_16_plus_3_with_both_source_amendments():
    assert tool.MODULES == {"tests/test_phase77_2_pct_equity_native.py": 16, "tests/test_m5_12_pct_alias.py": 3}
    assert tool.COUNTS == dict(tests=19, failures=0, errors=0, skipped=0)
    assert set(tool.MODULES) <= set(tool.PINNED_FILES)
    assert {"tools/m5_12_pct_source_amendment.py", "tools/m5_12_pct_alias_amendment.py"} <= set(tool.PINNED_FILES)


def junit(path, *, count=19, skipped=0):
    root = ET.Element("testsuites")
    suite = ET.SubElement(root, "testsuite", tests=str(count), failures="0", errors="0", skipped=str(skipped))
    for i in range(count):
        case = ET.SubElement(suite, "testcase", name="literal_" + str(i))
        if i < skipped:
            ET.SubElement(case, "skipped")
    ET.ElementTree(root).write(path)


def identity(manifest, kind):
    prefix = Path(manifest["prefixes"][kind])
    site = prefix / "lib/python3.12/site-packages"
    return dict(prefix=str(prefix), interpreter="cp312", isolated=True, dont_write_bytecode=True,
        core=manifest["core"], native=manifest["native"], core_origin=str(site / "quantbt"),
        native_package_origin=str(site / "_quantbt_native"), native_origin=str(site / "_quantbt_native/core.so"),
        modules=len(manifest["core_inventory"]), native_files=len(manifest["native_inventory"]),
        native_sha256=manifest["native_extension_sha256"])


@pytest.fixture
def host(tmp_path, monkeypatch):
    from tools import m5_12_local_artifacts as provenance
    from tools import m5_12_consumer_artifacts as archives
    root = tmp_path / "repository"
    lane = root / ".maturin/qms08/arbitrary-final-attempt/cp312"
    lane.mkdir(parents=True)
    monkeypatch.setattr(tool, "ROOT", root)
    monkeypatch.setattr(tool, "PINNED_FILES", tuple(tool.MODULES))
    for name in tool.MODULES:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("PUBLIC UNIT FIXTURE, NEVER EXECUTED\n")
    for kind in ("pair", "sdist"):
        prefix = lane / kind
        (prefix / "bin").mkdir(parents=True)
        (prefix / "bin/python").write_text("NOT AN EXECUTABLE\n")
        (prefix / "pyvenv.cfg").write_text("UNIT FIXTURE\n")
        binary = prefix / "lib/python3.12/site-packages/_quantbt_native/core.so"
        binary.parent.mkdir(parents=True)
        binary.write_bytes(b"NOT A NATIVE LIBRARY")
    binary_hash = sha256(b"NOT A NATIVE LIBRARY").hexdigest()
    proof = dict(schema=tool.PROOF_SCHEMA, source=dict(source_commit="e" * 40,
        qualified_source_count=466, financial_source_changed=True))
    (lane / "proof.json").write_text(json.dumps(proof))
    artifacts = dict(core="1.1.2", native="0.4.3", core_inventory={"__init__.py": "core", "py.typed": "typing"},
        native_inventory={"__init__.py": "wrapper", "core.so": binary_hash},
        native_extension_sha256=binary_hash, artifact_refs=[])
    case = SimpleNamespace(lane=lane, proof=proof, commands=[], verifications=[], artifacts=[],
        mutate=None, error=None, returncode=0, archive_drift=False)
    monkeypatch.setattr(provenance, "verify_local_artifacts", lambda value: case.verifications.append(deepcopy(value)))
    def manifest(value, actual_lane):
        assert value == proof and actual_lane == lane
        case.artifacts.append(actual_lane)
        result = deepcopy(artifacts)
        if case.archive_drift and len(case.artifacts) > 1:
            result["native_inventory"]["__init__.py"] = "changed-wrapper"
        return result
    monkeypatch.setattr(archives, "artifact_manifest", manifest)
    def run(command, **kwargs):
        case.commands.append((command, kwargs))
        if case.error:
            raise case.error
        kind = command[command.index("--kind") + 1]
        request = Path(command[command.index("--child-request") + 1])
        binding = json.loads(request.read_bytes())
        output = request.parent / (kind + ".json")
        junit(output.with_suffix(".xml"))
        ids, reports, modules = outcomes()
        row = dict(schema=tool.SCHEMA, kind=kind, identity=identity(binding, kind),
            capability=tool.ACTIVITY, counts=dict(tool.COUNTS), collected=ids, reports=reports,
            modules=modules, xfail=False, manifest_sha256=tool.digest(request),
            package_proof_sha256=binding["package_proof_sha256"], source=binding["source"],
            source_sha256=binding["source_sha256"], junit_sha256=tool.digest(output.with_suffix(".xml")),
            threads=dict(configured=dict(tool.NUMERIC_THREADS), mismatches=[], inspection_limits=[]),
            publication=False, complete_pair=False)
        if case.mutate:
            case.mutate(row, request)
        tool.write_json(output, row)
        return SimpleNamespace(returncode=case.returncode, stdout="retained child stdout\n", stderr="retained child stderr\n")
    monkeypatch.setattr(tool.subprocess, "run", run)
    monkeypatch.setenv("PYTHONPATH", "src")
    monkeypatch.setenv("PYTHONHOME", "wrong")
    monkeypatch.setenv("PYTEST_ADDOPTS", "--ignore=tests")
    monkeypatch.setenv("PYTEST_PLUGINS", "untrusted")
    return case


@pytest.mark.parametrize("kind", ("pair", "sdist"))
def test_serial_kind_uses_exact_current_source_and_retains_commands(host, kind):
    result = tool.qualify(host.lane, kind=kind)
    assert result["source"] == host.proof["source"]
    assert result["complete_pair"] is result["publication"] is False
    assert result["consumer"]["counts"] == dict(tests=19, failures=0, errors=0, skipped=0)
    command, kwargs = host.commands[0]
    assert command[:3] == [str(host.lane / kind / "bin/python"), "-I", "-B"]
    assert command[command.index("--kind") + 1] == kind
    assert all(kwargs["env"][key] == "1" for key in
        ("OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "OMP_NUM_THREADS", "NUMBA_NUM_THREADS", "PYTEST_DISABLE_PLUGIN_AUTOLOAD"))
    assert not {"PYTHONPATH", "PYTHONHOME", "PYTEST_ADDOPTS", "PYTEST_PLUGINS"} & kwargs["env"].keys()
    directory = host.lane / ("installed-pct-" + kind + "-proof")
    record = json.loads((directory / "process.json").read_bytes())
    assert record["command"] == command and record["returncode"] == 0
    assert "retained child stderr" in (directory / "consumer.log").read_text()
    assert len(host.verifications) == len(host.artifacts) == 2
    for name, expected in result["retained_sha256"].items():
        assert tool.digest(directory / name) == expected
    assert set(tool.MODULES) <= result["source_sha256"].keys()
    previous = {path: path.read_bytes() for path in directory.iterdir() if path.is_file()}
    with pytest.raises(ValueError, match="refuse overwrite"):
        tool.qualify(host.lane, kind=kind)
    assert all(path.read_bytes() == value for path, value in previous.items())
    assert len(host.commands) == 1


@pytest.mark.parametrize("defect", ("kind", "prefix", "interpreter", "bytecode", "native_root", "capability",
    "skip", "source", "proof_hash", "manifest_hash", "junit_hash", "collection", "xfail", "modules", "threads"))
def test_parent_cannot_promote_an_incomplete_or_wrong_kind_child(host, defect):
    def mutate(row, request):
        if defect == "kind": row["kind"] = "sdist"
        elif defect == "prefix": row["identity"]["prefix"] = str(host.lane / "sdist")
        elif defect == "interpreter": row["identity"]["interpreter"] = "cp311"
        elif defect == "bytecode": row["identity"]["dont_write_bytecode"] = False
        elif defect == "native_root": row["identity"]["native_package_origin"] = "/other/_quantbt_native"
        elif defect == "capability": row["capability"] = "processed_signal_states_v1"
        elif defect == "skip": row["reports"][row["collected"][0]]["call"] = "skipped"
        elif defect == "source": row["source"] = {"source_commit": "old-proof-overlay"}
        elif defect == "proof_hash": row["package_proof_sha256"] = "changed"
        elif defect == "manifest_hash": row["manifest_sha256"] = "changed"
        elif defect == "junit_hash": row["junit_sha256"] = "changed"
        elif defect == "collection": row["collected"][1] = row["collected"][0]
        elif defect == "xfail": row["xfail"] = True
        elif defect == "modules":
            first, second = list(row["modules"])
            row["modules"][first], row["modules"][second] = 15, 4
        else: row["threads"]["configured"]["numba_threads"] = 4
    host.mutate = mutate
    with pytest.raises(ValueError):
        tool.qualify(host.lane, kind="pair")
    directory = host.lane / "installed-pct-pair-proof"
    assert (directory / "consumer.log").is_file() and (directory / "process.json").is_file()
    assert not directory.with_suffix(".json").exists()
    assert len(host.verifications) == 2


@pytest.mark.parametrize("changed", ("proof", "fixture", "request", "archive"))
def test_post_execution_custody_change_retains_failure_and_no_final_receipt(host, changed):
    def mutate(row, request):
        if changed == "proof":
            (host.lane / "proof.json").write_text(json.dumps(dict(host.proof, source={"changed": True})))
        elif changed == "fixture":
            (tool.ROOT / next(iter(tool.MODULES))).write_text("changed public fixture")
        elif changed == "request":
            request.write_text(request.read_text() + "\n")
        else: host.archive_drift = True
    host.mutate = mutate
    with pytest.raises(ValueError):
        tool.qualify(host.lane, kind="pair")
    directory = host.lane / "installed-pct-pair-proof"
    assert json.loads((directory / "custody.json").read_text())["status"] == "FAIL_RETAINED"
    assert (directory / "consumer.log").is_file()
    assert not directory.with_suffix(".json").exists()


@pytest.mark.parametrize("failure", ("exit", "timeout", "missing"))
def test_failed_child_retains_exact_exit_or_launch_failure_without_install(host, failure):
    if failure == "exit": host.returncode = 1
    elif failure == "timeout": host.error = subprocess.TimeoutExpired("literal-child", 1200, output=b"partial", stderr=b"timeout")
    else: host.error = FileNotFoundError("no consumer python")
    with pytest.raises(ValueError, match="child failed"):
        tool.qualify(host.lane, kind="pair")
    directory = host.lane / "installed-pct-pair-proof"
    record = json.loads((directory / "process.json").read_text())
    assert record["returncode"] == (1 if failure == "exit" else None)
    assert bool(record["error"]) is (failure != "exit")
    assert (directory / "consumer.log").read_text().startswith("$ ")
    assert not directory.with_suffix(".json").exists()
    assert len(host.verifications) == 2


def test_historical_native_reuse_proof_cannot_be_overlaid_as_current(host):
    (host.lane / "proof.json").write_text(json.dumps(dict(host.proof, schema="quantbt.m5_12.local_artifacts.v1")))
    with pytest.raises(ValueError, match="fresh-native v2"):
        tool.qualify(host.lane, kind="pair")
    assert not host.commands and not (host.lane / "installed-pct-pair-proof").exists()


@pytest.mark.parametrize("kind", ("unknown", None))
def test_unknown_consumer_kind_fails_before_artifact_or_child_work(host, kind):
    with pytest.raises(ValueError, match="absolute canonical"):
        tool.qualify(host.lane, kind=kind)
    assert not host.verifications and not host.commands


def test_relative_lane_and_prior_dangling_output_are_rejected(host):
    with pytest.raises(ValueError, match="absolute canonical"):
        tool.qualify(Path(".maturin/qms08/cp312"), kind="pair")
    destination = host.lane / "installed-pct-pair-proof.json"
    destination.symlink_to(host.lane / "missing")
    with pytest.raises(ValueError, match="refuse overwrite"):
        tool.qualify(host.lane, kind="pair")
    assert destination.is_symlink() and not host.commands


@pytest.mark.parametrize("value", (None, True, "processed_signal_states_v1", tool.ACTIVITY))
def test_same_version_does_not_replace_exact_native_capability(value):
    native = SimpleNamespace(__version__="0.4.3", **{tool.CAPABILITY: value})
    if value == tool.ACTIVITY:
        tool.check_capability(native)
    else:
        with pytest.raises(ValueError, match="accepted-quantity"):
            tool.check_capability(native)


@pytest.mark.parametrize("count,skipped", ((18, 0), (19, 1), (20, 0)))
def test_junit_count_and_skip_negatives(tmp_path, count, skipped):
    path = tmp_path / "result.xml"
    junit(path, count=count, skipped=skipped)
    with pytest.raises(ValueError, match="exactly 19"):
        tool.counts_from_xml(path)


def test_identity_reuses_existing_complete_namespace_checker(monkeypatch):
    from tools import qms_e08_consumer
    calls = []
    native = SimpleNamespace(**{tool.CAPABILITY: tool.ACTIVITY})
    monkeypatch.setitem(sys.modules, "_quantbt_native", native)
    monkeypatch.setattr(qms_e08_consumer, "identity", lambda manifest, kind: calls.append((manifest, kind)) or {"checked": True})
    manifest = {"core_inventory": {"py.typed": "pinned"}, "native_inventory": {"__init__.py": "pinned"}}
    assert tool.installed_identity(manifest, "sdist") == {"checked": True}
    assert calls == [(manifest, "sdist")]
