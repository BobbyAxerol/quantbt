"""Release plumbing is fail-closed and does not authorize publication."""

from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from tools import qms_installed_w3


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
        assert kwargs["cwd"] == lane / "w3-workspace"
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
