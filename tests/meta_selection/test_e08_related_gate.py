"""Local integrated consumers cannot execute an unregistered checkout program."""

import json
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

from tools.qms_e08_related_consumer import consume
from tools import qms_e08_related_consumer as related
from tools import qms_e08_integrated as integrated

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("consumer", ("../private.py", "/tmp/private.py", "qms_unknown.py"))
def test_unregistered_consumer_rejected_before_runtime_import(tmp_path, consumer):
    manifest = tmp_path/"manifest.json"
    manifest.write_text(json.dumps(dict(allowed_consumers=["qms08_consumer.py"])))
    with pytest.raises(ValueError, match="unregistered"):
        consume(SimpleNamespace(manifest=manifest, consumer=consumer))


def bound():
    prefix = "/tmp/registered-pair"
    site = prefix+"/lib/python3.12/site-packages"
    manifest = dict(schema="qms-e08-installed-manifest-v1", core="1.1.2", native="0.4.3",
        prefixes={"pair": prefix}, interpreter="cp312", native_extension_sha256="binary-hash",
        core_inventory={"__init__.py": "core-hash"},
        native_inventory={"__init__.py": "wrapper-hash", "core.so": "binary-hash"},
        allowed_consumers=["qms08_consumer.py"], package_proof_schema="quantbt.m5_12.local_artifacts.v1",
        package_proof_sha256="a"*64, fixture_sha256={"tools/qms_e08_consumer.py":
            sha256((ROOT/"tools/qms_e08_consumer.py").read_bytes()).hexdigest()})
    row = dict(schema="qms-e08-related-installed-v1", kind="pair", consumer="qms08_consumer.py",
        manifest_sha256="request-hash", publication=False, result={"synthetic": True},
        threads=dict(mismatches=[], inspection_limits=[]), identity=dict(prefix=prefix,
            interpreter="cp312", isolated=True, dont_write_bytecode=True, core="1.1.2", native="0.4.3",
            core_origin=site+"/quantbt", native_package_origin=site+"/_quantbt_native",
            native_origin=site+"/_quantbt_native/core.so", native_sha256="binary-hash", modules=1, native_files=2))
    return manifest, row


@pytest.fixture
def cold_consumer(tmp_path, monkeypatch):
    """Only the wrapper runs; identity, telemetry and the inner program are fakes."""
    from quantbt.optimization.meta_selection import telemetry
    manifest, row = bound()
    path = tmp_path/"manifest.json"
    path.write_text(json.dumps(manifest))
    calls = []
    def identity(value, kind):
        assert value == manifest and kind == "pair"
        calls.append(kind)
        return deepcopy(row["identity"])
    monkeypatch.setattr(related, "identity_helper", lambda path: SimpleNamespace(identity=identity))
    monkeypatch.setattr(related.runpy, "run_path", lambda *a, **kw: print(json.dumps(row["result"])))
    monkeypatch.setattr(telemetry, "observed_threads", lambda **kw: row["threads"])
    monkeypatch.setattr(sys, "path", list(sys.path))
    args = SimpleNamespace(manifest=path, root=ROOT, kind="pair", consumer="qms08_consumer.py", arguments=[])
    return args, manifest, row, calls


def test_related_wrapper_passes_selected_kind_and_restores_argv(cold_consumer):
    args, _, expected, calls = cold_consumer
    previous = sys.argv
    row = consume(args)
    assert calls == ["pair", "pair"]
    assert row["kind"] == "pair" and row["identity"] == expected["identity"]
    assert row["result"] == expected["result"]
    assert row["manifest_sha256"] == sha256(args.manifest.read_bytes()).hexdigest()
    assert sys.argv is previous


@pytest.mark.parametrize("missing", ("kind", "prefixes", "interpreter", "native_inventory", "schema", "package_proof_schema", "package_proof_sha256"))
def test_historical_or_unbound_manifest_cannot_execute_related_consumer(tmp_path, monkeypatch, missing):
    manifest, _ = bound()
    args = SimpleNamespace(root=ROOT, kind="pair", consumer="qms08_consumer.py", arguments=[])
    if missing == "kind": args.kind = None
    else: manifest.pop(missing)
    args.manifest = tmp_path/"manifest.json"
    args.manifest.write_text(json.dumps(manifest))
    monkeypatch.setattr(related, "identity_helper", lambda *a: pytest.fail("unbound runtime imported"))
    monkeypatch.setattr(related.runpy, "run_path", lambda *a, **kw: pytest.fail("unbound consumer executed"))
    with pytest.raises(ValueError, match="fresh selected-prefix"):
        consume(args)


def test_related_manifest_mutation_has_no_successful_row(cold_consumer, monkeypatch):
    args, manifest, row, _ = cold_consumer
    def altered(*a, **kw):
        args.manifest.write_text(json.dumps(dict(manifest, unexpected="changed-during-consumer")))
        print(json.dumps(row["result"]))
    monkeypatch.setattr(related.runpy, "run_path", altered)
    with pytest.raises(ValueError, match="manifest changed"):
        consume(args)


def test_related_identity_is_revalidated_after_inner_consumer(cold_consumer, monkeypatch):
    args, _, row, _ = cold_consumer
    calls = []
    def changed(value, kind):
        calls.append(kind)
        return dict(row["identity"], prefix="/different-prefix") if len(calls)>1 else row["identity"]
    monkeypatch.setattr(related, "identity_helper", lambda path: SimpleNamespace(identity=changed))
    with pytest.raises(ValueError, match="identity changed"):
        consume(args)


@pytest.mark.parametrize("kind", ("pair", "sdist"))
def test_integrated_command_forwards_kind_and_both_isolation_flags(tmp_path, kind):
    lane = tmp_path/"cp312"
    command = integrated.consumer_command(lane, kind, tmp_path/"request.json", "qms08_consumer.py", ["--core", "1.1.2"])
    assert command[:3] == [str(lane/kind/"bin/python"), "-I", "-B"]
    assert command[command.index("--kind")+1] == kind
    assert command[command.index("--consumer")+1] == "qms08_consumer.py"
    assert command[-3:] == ["--", "--core", "1.1.2"]


@pytest.mark.parametrize("change", ("kind", "consumer", "request", "prefix", "interpreter", "isolated", "bytecode",
    "core_origin", "native_origin", "wrapper_origin", "native_hash", "native_count", "thread"))
def test_integrated_parent_rejects_wrong_consumer_identity(change):
    manifest, row = bound()
    kwargs = dict(manifest=manifest, kind="pair", name="qms08_consumer.py", request_hash="request-hash")
    integrated.validate_related(row, **kwargs)
    if change == "kind": row["kind"] = "sdist"
    elif change == "consumer": row["consumer"] = "another.py"
    elif change == "request": row["manifest_sha256"] = "another-request"
    elif change == "prefix": row["identity"]["prefix"] = "/other"
    elif change == "interpreter": row["identity"]["interpreter"] = "cp311"
    elif change == "isolated": row["identity"]["isolated"] = False
    elif change == "bytecode": row["identity"]["dont_write_bytecode"] = False
    elif change == "core_origin": row["identity"]["core_origin"] = "/other/site-packages/quantbt"
    elif change == "native_origin": row["identity"]["native_origin"] = "/other/core.so"
    elif change == "wrapper_origin": row["identity"]["native_package_origin"] = "/other/_quantbt_native"
    elif change == "native_hash": row["identity"]["native_sha256"] = "different-binary"
    elif change == "native_count": row["identity"]["native_files"] = 1
    else: row["threads"]["mismatches"] = ["too-many-threads"]
    with pytest.raises(ValueError, match="selected exact isolated"):
        integrated.validate_related(row, **kwargs)


def test_integrated_refuses_unknown_kind_or_unsafe_lane_before_provenance(tmp_path):
    with pytest.raises(ValueError, match="unknown artifact"):
        integrated.qualify(tmp_path, kind="unknown")
    with pytest.raises(ValueError, match="unsafe integrated"):
        integrated.qualify(tmp_path, kind="pair")


def test_related_has_no_legacy_identity_or_origins_call_signature():
    import ast
    tree = ast.parse((ROOT/"tools/qms_e08_related_consumer.py").read_text())
    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name) and node.func.id == "identity"]
    assert len(calls) == 2 and all(len(node.args) == 2 for node in calls)
    assert not any(isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        and node.func.id == "origins" for node in ast.walk(tree))
