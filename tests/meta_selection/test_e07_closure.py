"""Artifact, privacy and cleanup gates must reject unqualified handoffs."""

from copy import deepcopy
from hashlib import sha256
from io import BytesIO
import json
import subprocess
import tarfile
import zipfile

import pytest

from tools import qms_e07_closure as closure
from tools.qms_pre06_contract import EXTENSION_SHA


def identity():
    return dict(core="1.1.2", native="0.4.3", modules=260, native_sha256=EXTENSION_SHA,
                core_origin="/tmp/e07/lib/python3.12/site-packages/quantbt/__init__.py")


def test_e07_exact_installed_identity():
    assert closure.installed_identity(identity()) == identity()


@pytest.mark.parametrize("key,value", (("core", "1.1.1"), ("native", "0.4.2"),
    ("modules", 259), ("native_sha256", "wrong"), ("core_origin", "/tmp/src/quantbt/__init__.py")))
def test_e07_wrong_artifact_or_checkout_runtime_rejected(key, value):
    changed = deepcopy(identity())
    changed[key] = value
    with pytest.raises(ValueError, match="runtime identity"):
        closure.installed_identity(changed)


def test_e07_cleanup_unknown_root_rejected():
    with pytest.raises(ValueError, match="unreviewed"):
        closure.scratch("../g01-package-v1")


def test_e07_cleanup_symlink_root_rejected(tmp_path, monkeypatch):
    outside = tmp_path / "outside"
    outside.mkdir()
    lane = tmp_path / "lane"
    lane.mkdir()
    (lane / "wheel-consumer").symlink_to(outside, target_is_directory=True)
    monkeypatch.setattr(closure, "LANE", lane)
    with pytest.raises(ValueError, match="symlinked"):
        closure.scratch("wheel-consumer")
    assert outside.is_dir()


def test_e07_cleanup_active_consumer_never_removed(tmp_path, monkeypatch):
    roots = {name: tmp_path / name for name in closure.CLEANABLE}
    for path in roots.values():
        path.mkdir(parents=True)
    monkeypatch.setattr(closure, "LANE", tmp_path)
    monkeypatch.setattr(closure, "scratch", roots.__getitem__)
    monkeypatch.setattr(closure.subprocess, "check_output",
                        lambda *a, **kw: str(roots["wheel-consumer"] / "bin/python"))
    with pytest.raises(ValueError, match="still used"):
        closure.cleanup({})
    assert all(path.is_dir() for path in roots.values())


@pytest.mark.parametrize("private", ("alpha", "token"))
def test_e07_public_patch_rejects_private_material(private, monkeypatch):
    material = ("/root/bobby/pool_alpha/"+"alphas_storage/private.py") if private == "alpha" else "pypi-"+"x"*35

    def output(args, **kwargs):
        if args[:3] == ["git", "diff", "--name-only"]:
            return "docs/e07-fixture.md\n"
        if args[:2] == ["git", "ls-files"]:
            return ""
        return "diff fixture\n+"+material

    monkeypatch.setattr(closure.subprocess, "check_output", output)
    with pytest.raises(ValueError, match="private path or credential"):
        closure.privacy()


def test_e07_historical_receipt_bound_to_committed_source_and_native():
    from tools.qms_e08_source_guard import ENTRY, baseline
    from tools.qms_pre06_contract import NATIVE_SHA

    name = "benchmarks/optimization/meta_selection/qms_e07_closure.json"
    archived = baseline(name, ENTRY)
    assert (closure.ROOT / name).read_bytes() == archived
    receipt = json.loads(archived)
    names = subprocess.check_output(["git", "ls-tree", "-r", "--name-only", ENTRY, "--",
        "src/quantbt", "rust", "pyproject.toml", "MANIFEST.in"], cwd=closure.ROOT, text=True).splitlines()
    runtime = {name: sha256(baseline(name, ENTRY)).hexdigest() for name in names}
    assert len(runtime) == receipt["runtime_files"] == 322
    assert sha256(json.dumps(runtime, sort_keys=True).encode()).hexdigest() == receipt["runtime_inventory_sha256"]
    assert sha256(baseline(closure.GUIDE, ENTRY)).hexdigest() == receipt["guide_sha256"]
    for name, expected in receipt["verification_source_sha256"].items():
        assert sha256(baseline(name, ENTRY)).hexdigest() == expected
    assert receipt["artifacts"]["wheel"]["modules"] == receipt["artifacts"]["sdist"]["modules"] == 260
    assert receipt["native_sha256"] == NATIVE_SHA
    assert {kind: row["cells"] for kind, row in receipt["evidence"].items()} == {
        "source": 90, "wheel": 30, "sdist": 30,
    }
    assert receipt["publication"] is False


def test_e07_current_source_cannot_reissue_historical_registration(tmp_path, monkeypatch):
    from tools import qms_e07_contract as contract
    from tests.meta_selection.current_source_assertions import current_source_rejects_historical_certificate

    # A unit fixture exercises rejection; it is not a historical artifact receipt.
    (tmp_path / "registration.json").write_text(json.dumps({
        "runtime_sha256": {}, "guide_sha256": "unqualified", "protected_sha256": {},
    }))
    monkeypatch.setattr(contract, "LANE", tmp_path)
    current_source_rejects_historical_certificate(closure.check_registration, error=ValueError)


@pytest.fixture
def unit_artifacts(tmp_path, monkeypatch):
    payload = b'"""Synthetic package fixture, not a release artifact."""\n'
    wheel = tmp_path / "quantbt_engine-0.0.0-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr("quantbt/__init__.py", payload)
    sdist = tmp_path / "quantbt_engine-0.0.0.tar.gz"
    with tarfile.open(sdist, "w:gz") as archive:
        member = tarfile.TarInfo("quantbt_engine-0.0.0/src/quantbt/__init__.py")
        member.size = len(payload)
        archive.addfile(member, BytesIO(payload))
    native = tmp_path / "synthetic-native.bin"
    native.write_bytes(b"unit fixture only")
    paths = {"wheel": wheel, "sdist": sdist, "native": native}
    hashes = {kind: sha256(path.read_bytes()).hexdigest() for kind, path in paths.items()}
    (tmp_path / "artifacts.json").write_text(json.dumps({
        "paths": {kind: str(path) for kind, path in paths.items()}, "sha256": hashes,
    }))
    monkeypatch.setattr(closure, "LANE", tmp_path)
    return paths, {"native": {"wheel_sha256": hashes["native"]},
                   "core_inventory": {"__init__.py": sha256(payload).hexdigest()}}


def test_e07_artifact_validator_reads_complete_synthetic_archives(unit_artifacts):
    paths, registered = unit_artifacts
    result = closure.artifacts(registered)
    assert set(result) == {"wheel", "sdist"}
    for kind, row in result.items():
        assert row == {"modules": 1, "sha256": sha256(paths[kind].read_bytes()).hexdigest(),
                       "bytes": paths[kind].stat().st_size}


@pytest.mark.parametrize("mutation", ("wheel", "sdist", "native", "registered_native", "inventory"))
def test_e07_artifact_validator_rejects_drift(unit_artifacts, mutation):
    paths, registered = unit_artifacts
    if mutation in paths:
        paths[mutation].write_bytes(paths[mutation].read_bytes() + b"drift")
        message = "exact artifact changed"
    elif mutation == "registered_native":
        registered["native"]["wheel_sha256"] = "wrong"
        message = "different native wheel"
    else:
        registered["core_inventory"]["missing.py"] = "wrong"
        message = "complete canonical package inventory mismatch"
    with pytest.raises(ValueError, match=message):
        closure.artifacts(registered)


def test_e07_public_grid_example_fits_mature_history_without_private_inputs():
    from examples.wfo_meta_reactive_grid import run
    value = run("active")
    assert value["folds"] == value["observed_revisions"] == 26
    assert value["fit_count"] > 0 and len(value["params_by_fold"]) == 26
    assert not value["continuous_equity_available"] and not value["economic_promotion"]
