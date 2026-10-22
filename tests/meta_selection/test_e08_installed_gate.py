"""Fail-closed receipts and complete portable CI wiring, no mocked PASS runs."""

from copy import deepcopy
from pathlib import Path
from fnmatch import fnmatchcase

import pytest
import yaml

from tools import qms_installed_execution as gate
from tools.qms_e08_consumer import EXPECTED, GROUPS


def valid(group):
    manifest = dict(core="1.1.2", native="0.4.3", native_extension_sha256="hash", core_inventory={"__init__.py": "source"})
    row = dict(schema="qms-e08-installed-execution-v1", group=group,
        counts=dict(tests=EXPECTED[group], failures=0, errors=0, skipped=0),
        identity=dict(core="1.1.2", native="0.4.3", native_sha256="hash", modules=1,
            core_origin="/tmp/consumer/lib/python3.12/site-packages/quantbt",
            native_origin="/tmp/consumer/lib/python3.12/site-packages/_quantbt_native/core.so"),
        threads=dict(mismatches=[], inspection_limits=[]),
        source_sha256={name: gate.digest(gate.ROOT/"tests/meta_selection"/name) for name in GROUPS[group]},
        publication=False, empirical_promotion=False)
    return row, manifest


@pytest.mark.parametrize("group", GROUPS)
@pytest.mark.parametrize("mutation", ("missing", "skip", "error", "thread", "origin", "hash", "source", "publish"))
def test_incomplete_receipt_cannot_pass(group, mutation):
    row, manifest = valid(group)
    gate.validate_row(row, group, manifest)
    changed = deepcopy(row)
    if mutation == "missing": changed["counts"]["tests"] -= 1
    elif mutation == "skip": changed["counts"]["skipped"] = 1
    elif mutation == "error": changed["counts"]["errors"] = 1
    elif mutation == "thread": changed["threads"]["mismatches"] = [{"numba": 4}]
    elif mutation == "origin": changed["identity"]["core_origin"] = "/tmp/checkout/src/quantbt"
    elif mutation == "hash": changed["identity"]["native_sha256"] = "other"
    elif mutation == "source": changed["source_sha256"].pop(next(iter(changed["source_sha256"])))
    else: changed["publication"] = True
    with pytest.raises(ValueError):
        gate.validate_row(changed, group, manifest)


def test_workflow_covers_both_os_three_interpreters_and_all_execution_proofs():
    path = gate.ROOT/".github/workflows/qms-candidate.yml"
    workflow = yaml.load(path.read_text(), Loader=yaml.BaseLoader)
    job = workflow["jobs"]["installed-candidate"]
    assert job["strategy"]["matrix"] == {"runner": ["ubuntu-22.04", "ubuntu-24.04"], "python": ["3.11", "3.12", "3.13"]}
    assert set(job["env"].values()) == {"1"}
    assert set(job["env"]) == {"OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "OMP_NUM_THREADS", "NUMBA_NUM_THREADS"}
    assert any("tools.qms_installed_execution" in step.get("run", "") for step in job["steps"])
    assert "installed-execution-proof/*" in job["steps"][-1]["with"]["path"]
    filters = workflow["on"]["pull_request"]["paths"]
    for name in ("tools/qms_e06_support.py", "tools/qms_e07_mature.py", "tools/qms_e08_consumer.py", "src/quantbt/wfo_execution.py"):
        assert any(fnmatchcase(name, pattern) for pattern in filters), name


def test_package_inventory_includes_non_python_resources(tmp_path):
    from tools.qms_e08_consumer import inventory
    (tmp_path / "py.typed").write_bytes(b"")
    (tmp_path / "thresholds.json").write_text('{"unchanged":true}')
    (tmp_path / "__pycache__").mkdir()
    (tmp_path / "__pycache__/ignored.pyc").write_bytes(b"not a source")
    assert set(inventory(tmp_path)) == {"py.typed", "thresholds.json"}


def test_wrong_lane_cannot_be_qualified(tmp_path):
    with pytest.raises(ValueError, match="unsafe"):
        gate.qualify(tmp_path)


@pytest.fixture
def cold_deep_consumer(tmp_path, monkeypatch):
    import json
    import sys
    from types import SimpleNamespace
    from tools import qms_e08_consumer as consumer
    request = tmp_path / "manifest.json"
    request.write_text(json.dumps(dict(fixture_sha256={})))
    monkeypatch.setattr(consumer, "identity", lambda manifest, kind: dict(kind=kind))
    monkeypatch.setattr(sys, "path", list(sys.path))
    args = SimpleNamespace(root=gate.ROOT, manifest=request, output=tmp_path / "pair-intrabar.json",
        group="intrabar", kind="pair")
    return consumer, args


@pytest.mark.parametrize("group", GROUPS)
def test_deep_pytest_uses_output_owned_scratch_without_cache(cold_deep_consumer, monkeypatch, group):
    consumer, args = cold_deep_consumer
    args.group = group
    args.output = args.output.with_name("pair-" + group + ".json")
    calls = []
    class CapturedInvocation(Exception):
        pass
    def capture(arguments):
        calls.append(arguments)
        raise CapturedInvocation
    monkeypatch.setattr(pytest, "main", capture)
    with pytest.raises(CapturedInvocation):
        consumer.consume(args)
    assert len(calls) == 1
    arguments = calls[0]
    assert arguments[arguments.index("-p") + 1] == "no:cacheprovider"
    assert arguments[arguments.index("--basetemp") + 1] == str(
        args.output.parent / (args.output.stem + "-fixtures"))
    assert f"--junitxml={args.output.with_suffix('.xml')}" in arguments
    assert all(str(args.root / "tests/meta_selection" / name) in arguments for name in GROUPS[group])
    assert not args.output.exists()


@pytest.mark.parametrize("occupied", ("directory", "file", "dangling_symlink"))
def test_deep_pytest_cannot_replace_prior_fixture_scratch(cold_deep_consumer, monkeypatch, occupied):
    consumer, args = cold_deep_consumer
    scratch = args.output.parent / (args.output.stem + "-fixtures")
    if occupied == "directory":
        scratch.mkdir()
        marker = scratch / "retained.txt"
        marker.write_bytes(b"retained fixture evidence")
    elif occupied == "file":
        marker = scratch
        marker.write_bytes(b"retained fixture evidence")
    else:
        scratch.symlink_to(args.output.parent / "missing-target", target_is_directory=True)
    monkeypatch.setattr(pytest, "main", lambda *a, **kw: pytest.fail("prior scratch reached pytest"))
    with pytest.raises(ValueError, match="scratch already exists"):
        consumer.consume(args)
    if occupied == "dangling_symlink":
        assert scratch.is_symlink() and not scratch.exists()
    else:
        assert marker.read_bytes() == b"retained fixture evidence"
    assert not args.output.exists()


def bound_valid(group):
    row, manifest = valid(group)
    prefix = "/tmp/consumer"
    manifest.update(interpreter="cp312", prefixes={"pair": prefix},
        native_inventory={"__init__.py": "wrapper", "core.so": "hash"})
    row.update(kind="pair")
    row["identity"].update(prefix=prefix, interpreter="cp312", isolated=True,
        dont_write_bytecode=True, native_files=2,
        native_package_origin=prefix+"/lib/python3.12/site-packages/_quantbt_native")
    return row, manifest


@pytest.mark.parametrize("mutation", ("kind", "prefix", "interpreter", "isolated", "bytecode", "native_root", "native_count"))
def test_new_per_kind_receipt_requires_exact_isolated_consumer(mutation):
    row, manifest = bound_valid("intrabar")
    gate.validate_row(row, "intrabar", manifest, kind="pair")
    if mutation == "kind": row["kind"] = "sdist"
    elif mutation == "prefix": row["identity"]["prefix"] = "/tmp/other"
    elif mutation == "interpreter": row["identity"]["interpreter"] = "cp311"
    elif mutation == "isolated": row["identity"]["isolated"] = False
    elif mutation == "bytecode": row["identity"]["dont_write_bytecode"] = False
    elif mutation == "native_root": row["identity"]["native_package_origin"] = "/tmp/other/site-packages/_quantbt_native"
    else: row["identity"]["native_files"] = 1
    with pytest.raises(ValueError, match="consumer|prefix"):
        gate.validate_row(row, "intrabar", manifest, kind="pair")


@pytest.fixture
def installed_identity(tmp_path, monkeypatch):
    """Literal namespace files and fake imports; never compile/import native code."""
    import sys
    from types import ModuleType, SimpleNamespace
    from tools import qms_e08_consumer as consumer
    prefix = tmp_path / "pair"
    version = ".".join(map(str, sys.version_info[:2]))
    site = prefix / "lib" / ("python"+version) / "site-packages"
    core, native = site/"quantbt", site/"_quantbt_native"
    for root, files in ((core, {"__init__.py": b"core", "py.typed": b""}),
            (native, {"__init__.py": b"wrapper", "core.so": b"extension", "defaults.json": b"{}"})):
        root.mkdir(parents=True)
        for name, payload in files.items(): (root/name).write_bytes(payload)
    modules = {}
    for name, path in (("quantbt", core/"__init__.py"),
            ("_quantbt_native", native/"__init__.py"), ("_quantbt_native._quantbt_native", native/"core.so")):
        module = ModuleType(name)
        module.__file__ = str(path)
        module.__spec__ = SimpleNamespace(origin=str(path))
        if name.count(".") == 0: module.__path__ = [str(path.parent)]
        modules[name] = module
    modules["quantbt"].__version__ = "1.1.2"
    modules["_quantbt_native"].version = lambda: "0.4.3"
    modules["_quantbt_native"]._quantbt_native = modules["_quantbt_native._quantbt_native"]
    for name in tuple(sys.modules):
        if name.split(".", 1)[0] in {"quantbt", "_quantbt_native"}:
            monkeypatch.delitem(sys.modules, name)
    for name, module in modules.items(): monkeypatch.setitem(sys.modules, name, module)
    flags = SimpleNamespace(**{name: getattr(sys.flags, name) for name in dir(sys.flags) if not name.startswith("_")})
    flags.isolated, flags.dont_write_bytecode = 1, 1
    monkeypatch.setattr(sys, "flags", flags)
    monkeypatch.setattr(sys, "prefix", str(prefix))
    monkeypatch.setattr(sys, "executable", str(prefix/"bin/python"))
    monkeypatch.setattr(consumer.sysconfig, "get_path", lambda key: str(site))
    monkeypatch.setattr(consumer, "distribution", lambda name: SimpleNamespace(
        version="1.1.2" if name == "quantbt-engine" else "0.4.3", locate_file=lambda package: site/package))
    manifest = dict(core="1.1.2", native="0.4.3", core_inventory=consumer.inventory(core),
        native_inventory=consumer.inventory(native), native_extension_sha256=gate.digest(native/"core.so"),
        prefixes={"pair": str(prefix), "sdist": str(tmp_path/"sdist")},
        interpreter="cp"+"".join(map(str, sys.version_info[:2])))
    return SimpleNamespace(consumer=consumer, manifest=manifest, prefix=prefix,
        native=native, core=core, flags=flags, modules=modules)


def test_selected_consumer_checks_complete_native_namespace(installed_identity):
    value = installed_identity
    row = value.consumer.identity(value.manifest, "pair")
    assert row["prefix"] == str(value.prefix) and row["native_files"] == 3
    assert row["isolated"] is row["dont_write_bytecode"] is True
    (value.native/"__init__.py").write_bytes(b"tampered-wrapper-same-extension")
    with pytest.raises(ValueError, match="complete installed core/native"):
        value.consumer.identity(value.manifest, "pair")


@pytest.mark.parametrize("mutation", ("kind", "interpreter", "isolated", "bytecode", "external_extension", "external_metadata"))
def test_consumer_identity_rejects_cross_environment_imports_and_flags(installed_identity, monkeypatch, mutation):
    from types import SimpleNamespace
    value = installed_identity
    kind = "pair"
    if mutation == "kind": kind = "sdist"
    elif mutation == "interpreter": value.manifest["interpreter"] = "cp000"
    elif mutation == "isolated": value.flags.isolated = 0
    elif mutation == "bytecode": value.flags.dont_write_bytecode = 0
    elif mutation == "external_extension":
        path = value.prefix.parent/"external.so"
        path.write_bytes(b"extension")
        value.modules["_quantbt_native._quantbt_native"].__file__ = str(path)
    else:
        monkeypatch.setattr(value.consumer, "distribution", lambda name: SimpleNamespace(
            version="1.1.2", locate_file=lambda package: value.prefix.parent/package))
    with pytest.raises(ValueError, match="consumer|interpreter|namespace|site-packages"):
        value.consumer.identity(value.manifest, kind)


def test_native_wheel_inventory_pins_wrapper_extension_and_resources(tmp_path):
    from zipfile import ZipFile
    path = tmp_path/"native.whl"
    with ZipFile(path, "w") as archive:
        archive.writestr("_quantbt_native/__init__.py", b"wrapper")
        archive.writestr("_quantbt_native/core.so", b"extension")
        archive.writestr("_quantbt_native/defaults.json", b"{}")
    with ZipFile(path) as archive:
        rows = gate.native_inventory(archive)
    from hashlib import sha256
    assert rows == {name: sha256(payload).hexdigest() for name, payload in
        (("__init__.py", b"wrapper"), ("core.so", b"extension"), ("defaults.json", b"{}"))}


@pytest.mark.parametrize("names", (("core.so",), ("__init__.py",), ("__init__.py", "a.so", "b.so")))
def test_native_wheel_cannot_certify_partial_or_ambiguous_namespace(tmp_path, names):
    from zipfile import ZipFile
    path = tmp_path/"native.whl"
    with ZipFile(path, "w") as archive:
        for name in names: archive.writestr("_quantbt_native/"+name, b"literal")
    with ZipFile(path) as archive, pytest.raises(ValueError, match="native|wrapper"):
        gate.native_inventory(archive)


@pytest.fixture
def local_proof(tmp_path, monkeypatch):
    import json
    from tools import m5_12_local_artifacts as local
    proof = dict(schema="quantbt.m5_12.local_artifacts.v1", publication=False, source="sealed")
    path = tmp_path/"proof.json"
    path.write_text(json.dumps(proof))
    calls = []
    monkeypatch.setattr(local, "verify_local_artifacts", lambda value: calls.append(deepcopy(value)))
    return path, proof, calls, local


def test_current_provenance_is_reverified_before_and_after(local_proof):
    path, proof, calls, _ = local_proof
    initial = gate.verify_proof_custody(path, proof)
    assert gate.verify_proof_custody(path, proof, expected_sha256=initial) == initial
    assert calls == [proof, proof]


def test_replaced_proof_is_rejected_instead_of_hashing_unverified_replacement(local_proof):
    import json
    path, proof, calls, _ = local_proof
    initial = gate.verify_proof_custody(path, proof)
    replacement = dict(proof, source="not-the-executed-source")
    path.write_text(json.dumps(replacement))
    with pytest.raises(ValueError, match="admitted snapshot"):
        gate.verify_proof_custody(path, replacement, expected_sha256=initial)
    assert len(calls) == 1


def test_proof_changed_inside_verifier_is_not_a_passing_snapshot(local_proof, monkeypatch):
    import json
    path, proof, _, local = local_proof
    monkeypatch.setattr(local, "verify_local_artifacts", lambda value: path.write_text(json.dumps(dict(value, source="changed"))))
    with pytest.raises(ValueError, match="during provenance verification"):
        gate.verify_proof_custody(path, proof)


def test_unchanged_proof_does_not_hide_current_source_verifier_failure(local_proof, monkeypatch):
    path, proof, _, local = local_proof
    initial = gate.verify_proof_custody(path, proof)
    def changed_source(value): raise ValueError("current native/source drift")
    monkeypatch.setattr(local, "verify_local_artifacts", changed_source)
    with pytest.raises(ValueError, match="source drift"):
        gate.verify_proof_custody(path, proof, expected_sha256=initial)
