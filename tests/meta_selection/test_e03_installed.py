"""Exact-lane scalar proof rejects failed/missing results before writing a seal."""

import json
from pathlib import Path
import subprocess

import pytest

from tools import qms_e03_installed as installed


def setup_lane(tmp_path, monkeypatch):
    (tmp_path / "proof.json").write_text(json.dumps(dict(core="1.1.2", native="0.4.3")))
    monkeypatch.setattr(installed, "verify_pair", lambda p: None)
    monkeypatch.setenv("PYTHONPATH", "untrusted/source")
    cells = [dict(target=r, backend=b, off_shadow_account_exact=True, active_original_witness=True)
             for b in ("native_vectorized", "native_event") for r in ("signal_notional", "notional", "unit")]
    cells += [dict(target=r, backend="legacy", off_shadow_account_exact=True, active_original_witness=True)
              for r in ("pct_equity", "dca_ladder")]
    return dict(core="1.1.2", native="0.4.3", cells=cells)


def test_e03_t06_installed_lane_binds_both_artifact_consumers_and_isolates_sources(tmp_path, monkeypatch):
    record = setup_lane(tmp_path, monkeypatch)
    commands = []

    def run(command, **kw):
        commands.append(command)
        assert "PYTHONPATH" not in kw["env"] and kw["env"]["NUMBA_NUM_THREADS"] == "1"
        assert kw["cwd"] == tmp_path / "installed-scalar-proof/workspace"
        assert "-I" in command
        return subprocess.CompletedProcess(command, 0, json.dumps(record), "")

    monkeypatch.setattr(installed.subprocess, "run", run)
    result = installed.qualify(tmp_path)
    assert len(commands) == 2 and set(result["consumers"]) == {"pair", "sdist"}
    assert result["empirical_promotion"] is False
    assert result["package_proof_sha256"] and all(c["log_sha256"] for c in result["consumers"].values())
    with pytest.raises(ValueError, match="sealed"):
        installed.qualify(tmp_path)


@pytest.mark.parametrize("bad", ["failed", "missing", "duplicate", "account", "version"])
def test_e03_t06_bad_installed_evidence_never_seals_a_receipt(tmp_path, monkeypatch, bad):
    record = setup_lane(tmp_path, monkeypatch)
    if bad == "missing":
        record["cells"].pop()
    elif bad == "duplicate":
        record["cells"][0] = record["cells"][1]
    elif bad == "account":
        record["cells"][0]["off_shadow_account_exact"] = False
    elif bad == "version":
        record["native"] = "0.4.2"
    monkeypatch.setattr(installed.subprocess, "run", lambda command, **kw:
        subprocess.CompletedProcess(command, 1 if bad == "failed" else 0, json.dumps(record), "error"))
    with pytest.raises(ValueError):
        installed.qualify(tmp_path)
    assert not (tmp_path / "installed-scalar-proof.json").exists()


def test_e03_t06_remote_matrix_declares_installed_scalar_proof_without_private_alpha():
    root = Path(__file__).resolve().parents[2]
    workflow = (root / ".github/workflows/qms-candidate.yml").read_text()
    assert "python: [\"3.11\", \"3.12\", \"3.13\"]" in workflow
    assert "runner: [ubuntu-22.04, ubuntu-24.04]" in workflow
    assert "-m tools.qms_e03_installed --lane" in workflow
    assert "installed-scalar-proof.json" in workflow
    assert "tools/qms_e03_study.py" not in workflow
