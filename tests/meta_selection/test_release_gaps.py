"""Release plumbing is fail-closed and does not authorize publication."""

from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from tools import qms_installed_w3


def test_build_tool_prefers_local_executable_and_falls_back_to_path(tmp_path, monkeypatch):
    from tools import qms08_package

    monkeypatch.setattr(qms08_package, "ROOT", tmp_path)
    system = tmp_path / "system-uv"
    monkeypatch.setattr(qms08_package.shutil, "which", lambda name: str(system) if name == "uv" else None)
    assert qms08_package.build_tool("uv") == system
    local = tmp_path / ".venv/bin/uv"
    local.parent.mkdir(parents=True)
    local.write_text("#!/bin/sh\nexit 0\n")
    assert qms08_package.build_tool("uv") == system
    local.chmod(0o755)
    assert qms08_package.build_tool("uv") == local
    with pytest.raises(FileNotFoundError, match="absent"):
        qms08_package.build_tool("missing")


def test_missing_command_preserves_failed_build_log(tmp_path, monkeypatch):
    from tools import qms08_package

    def missing(*args, **kwargs):
        raise FileNotFoundError("no installed uv")

    monkeypatch.setattr(qms08_package.subprocess, "run", missing)
    log = tmp_path / "build.log"
    with pytest.raises(RuntimeError, match="could not start"):
        qms08_package.run(["uv", "venv"], cwd=tmp_path, log=log)
    assert log.read_text() == "$ uv venv\nno installed uv\n"


def fake_lane(tmp_path, monkeypatch):
    lane = tmp_path / "cp312"
    lane.mkdir()
    proof = dict(core="1.1.1+qms08", native="0.4.3.dev4")
    (lane / "proof.json").write_text(json.dumps(proof))
    monkeypatch.setattr(qms_installed_w3, "verify_pair", lambda p: p == proof or pytest.fail("wrong proof"))
    record = dict(core_version=proof["core"], native_version=proof["native"],
                  off_shadow_exact=True, same_pass=True, selected_lineage=True,
                  closed=True, observer_failures=0)
    return lane, record


def test_remote_workflow_has_all_six_installed_w3_rows_without_publish():
    root = Path(__file__).resolve().parents[2]
    text = (root / ".github/workflows/qms-candidate.yml").read_text()
    workflow = yaml.load(text, Loader=yaml.BaseLoader)
    assert workflow["permissions"] == {"contents": "read"}
    assert workflow["on"]["push"]["branches"] == ["feat/meta-selection-samplers"]
    job = workflow["jobs"]["installed-candidate"]
    assert job["strategy"]["matrix"] == dict(
        runner=["ubuntu-22.04", "ubuntu-24.04"], python=["3.11", "3.12", "3.13"])
    step = next(s for s in job["steps"] if "tools.qms_installed_w3" in s.get("run", ""))
    assert "sys.version_info[:2]" in step["run"]
    assert "installed-w3-proof.json" in text
    assert "id-token" not in text and "pypi-publish" not in text


def test_installed_proof_checks_both_wheel_and_sdist_with_isolation(tmp_path, monkeypatch):
    lane, record = fake_lane(tmp_path, monkeypatch)
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        assert "-I" in command and "--core-version" in command and "--native-version" in command
        assert kwargs["cwd"] == lane / "installed-w3-proof/workspace"
        assert "PYTHONPATH" not in kwargs["env"]
        return SimpleNamespace(returncode=0, stdout=json.dumps(record), stderr="")

    monkeypatch.setattr(qms_installed_w3.subprocess, "run", run)
    result = qms_installed_w3.qualify(lane)
    assert len(calls) == 2 and set(result["consumers"]) == {"pair", "sdist"}
    assert result["publication"] is False
    with pytest.raises(ValueError, match="sealed"):
        qms_installed_w3.qualify(lane)


@pytest.mark.parametrize("mutation", ["version", "shadow", "same_pass", "lineage", "cleanup", "observer"])
def test_incomplete_installed_proof_fails(tmp_path, monkeypatch, mutation):
    lane, record = fake_lane(tmp_path, monkeypatch)
    row = deepcopy(record)
    key = dict(version="native_version", shadow="off_shadow_exact", same_pass="same_pass",
               lineage="selected_lineage", cleanup="closed", observer="observer_failures")[mutation]
    row[key] = "wrong" if mutation == "version" else 1 if mutation == "observer" else False
    monkeypatch.setattr(qms_installed_w3.subprocess, "run", lambda *a, **k: SimpleNamespace(
        returncode=0, stdout=json.dumps(row), stderr=""))
    with pytest.raises(ValueError, match="contract mismatch"):
        qms_installed_w3.qualify(lane)
    assert not (lane / "installed-w3-proof.json").exists()


def test_failed_consumer_cannot_produce_pass_receipt(tmp_path, monkeypatch):
    lane, _ = fake_lane(tmp_path, monkeypatch)
    monkeypatch.setattr(qms_installed_w3.subprocess, "run", lambda *a, **k: SimpleNamespace(
        returncode=1, stdout="", stderr="native mismatch"))
    with pytest.raises(ValueError, match="consumer failed"):
        qms_installed_w3.qualify(lane)
    assert not (lane / "installed-w3-proof.json").exists()


def test_new_w3_receipt_preserves_previous_logs(tmp_path, monkeypatch):
    lane, record = fake_lane(tmp_path, monkeypatch)
    monkeypatch.setattr(qms_installed_w3.subprocess, "run", lambda *a, **k: SimpleNamespace(
        returncode=0, stdout=json.dumps(record), stderr=""))
    qms_installed_w3.qualify(lane)
    originals = {p: p.read_bytes() for p in lane.rglob("*") if p.is_file()}
    qms_installed_w3.qualify(lane, receipt_name="installed-w3-v2.json")
    assert all(p.read_bytes() == data for p, data in originals.items())
    with pytest.raises(ValueError, match="basename"):
        qms_installed_w3.qualify(lane, receipt_name="../outside.json")


def test_declared_release_pair_and_default_features_are_exact():
    import tomllib
    from tools.qms08_package import ROOT, declared_pair

    assert declared_pair() == ("1.1.2", "0.4.3")
    cargo = tomllib.loads((ROOT / "rust/native_event/Cargo.toml").read_text())
    assert cargo["features"]["default"] == ["qms-numeric-candidate", "qms-prepared-witness-candidate"]
    assert cargo["package"]["version"] == "0.4.3"
    product = json.loads((ROOT / "contracts/native_event_product_registry.json").read_text())
    assert product["versions"]["native_package"]["published"] is False
    core = tomllib.loads((ROOT / "pyproject.toml").read_text())
    assert sum(dep.startswith("quantbt-native==0.4.3;") for dep in core["project"]["dependencies"]) == 1


def test_release_stage_has_no_private_identity_rewrites(tmp_path):
    from tools.qms08_package import ROOT, stage_source

    stage = tmp_path / "release"
    assert stage_source(stage, release_pair=True) == {}
    for name in ("pyproject.toml", "src/quantbt/__init__.py", "rust/Cargo.lock",
                 "rust/native_event/Cargo.toml", "rust/native_event/pyproject.toml"):
        assert (stage / name).read_bytes() == (ROOT / name).read_bytes()
    assert not (stage / "candidate_registry.json").exists()
    private = tmp_path / "private"
    assert len(stage_source(private)) == 6


def test_release_source_allowlist_cannot_hide_financial_changes():
    from tools.qms_release_source_guard import ROOT, PACKAGING_FILES, without_release_identity

    for name in PACKAGING_FILES:
        source = (ROOT / name).read_bytes()
        without_release_identity(source, name)
        with pytest.raises(AssertionError, match="unapproved"):
            without_release_identity(source + b"\n# unexpected economic change\n", name)


def test_release_rejects_private_native_reuse_before_any_build(tmp_path):
    from tools.qms08_package import qualify

    with pytest.raises(ValueError, match="fresh default-feature"):
        qualify(Path("/usr/bin/python3"), output=tmp_path, reuse_native_lane=tmp_path, release_pair=True)


def test_remote_and_public_gates_require_actual_qms_proofs():
    from tools.qms08_package import ROOT
    from tools.verify_public_native_consumer import ConsumerProofSpec, poetry_install_commands

    candidate = (ROOT / ".github/workflows/qms-candidate.yml").read_text()
    assert "tools.qms08_package --release-pair" in candidate
    assert "--features" not in candidate
    public = (ROOT / ".github/workflows/public-native-consumer.yml").read_text()
    assert "--require-qms" in public and "1.1.2" in public and "0.4.3" in public
    spec = ConsumerProofSpec("pypi", "1.1.2", "0.4.3", "poetry", Path("/python"), 30, require_qms=True)
    commands = poetry_install_commands(spec)
    assert commands[1][2] == "quantbt-engine"
    assert commands[2][2] == "quantbt-engine[optimization]==1.1.2"


@pytest.mark.parametrize("mutation", ["pair", "recipes", "rust", "shadow", "same_pass", "observer"])
def test_exact_release_consumers_fail_closed(mutation):
    from tools.qms_release_consumers import validate_consumers

    scalar = dict(core_version="1.1.2", native_version="0.4.3",
        active_reference_prepared_parity=True, off_shadow_parity=True, actual_meta_folds=6,
        sampler_recipes=["tpe_legacy", "tpe_multivariate_group", "cmaes", "sobol"],
        numeric_blocks={"selected_backend_by_block": {"gram_solve": "rust"}})
    w3 = dict(core_version="1.1.2", native_version="0.4.3", off_shadow_exact=True,
              same_pass=True, selected_lineage=True, closed=True, observer_failures=0)
    rows = {"qms08_consumer.py": scalar, "qms_local_consumer.py": w3}
    assert validate_consumers(rows, core="1.1.2", native="0.4.3")
    if mutation == "pair":
        scalar["native_version"] = "0.4.2"
    elif mutation == "recipes":
        scalar["sampler_recipes"].pop()
    elif mutation == "rust":
        scalar["numeric_blocks"]["selected_backend_by_block"]["gram_solve"] = "numpy"
    elif mutation == "shadow":
        scalar["off_shadow_parity"] = False
    else:
        w3["same_pass" if mutation == "same_pass" else "observer_failures"] = False if mutation == "same_pass" else 1
    with pytest.raises(ValueError):
        validate_consumers(rows, core="1.1.2", native="0.4.3")
