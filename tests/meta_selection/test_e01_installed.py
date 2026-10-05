"""E01-T04/T05 plumbing/failure injection; actual runs are separate receipts."""

import ast
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
from types import SimpleNamespace
import subprocess

import pytest
import yaml

from _e01_fixtures import records
from tools import qms_installed_consumers as proof
from tools.qms_release_consumers import CONSUMERS, consumer_arguments, validate_consumers

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("name", CONSUMERS)
def test_e01_t05_missing_consumer_is_not_a_successful_skip(name):
    rows = records()
    del rows[name]
    with pytest.raises(ValueError, match="missing required"):
        validate_consumers(rows, core="1.1.2", native="0.4.3")


@pytest.mark.parametrize("mutation", ["transport", "token", "ipc", "scheduler", "duplicate", "process",
    "pool", "rust", "shadow", "continuation", "resume_states", "resume_pair", "financial_replay"])
def test_e01_t05_extended_proofs_are_independently_required(mutation):
    rows = records()
    c02 = rows["qms_local_consumer.py"]["c02_transport"]
    c03, c04 = rows["qms_c03_consumer.py"], rows["qms_c04_consumer.py"]
    if mutation == "transport": c02["original_pool_account_witness_exact"] = False
    elif mutation == "token": c02["native_tokens"] = False
    elif mutation == "ipc": c02["market_ipc_bytes_per_task"] = 8
    elif mutation == "scheduler": c03["matrix"].pop()
    elif mutation == "duplicate": c03["matrix"][1] = deepcopy(c03["matrix"][0])
    elif mutation == "process": c03["closed_children"] = False
    elif mutation == "pool": c03["meta_matrix"][0]["pool_exact"] = False
    elif mutation == "rust": c03["meta_matrix"][0]["actual_rust_fit"] = False
    elif mutation == "shadow": c03["meta_matrix"][0]["shadow_account_exact"] = False
    elif mutation == "continuation": c04["matrix"][0]["fresh_process_exact"] = False
    elif mutation == "resume_states": c04["matrix"][0]["states"].pop()
    elif mutation == "resume_pair": c04["native"] = "0.4.2"
    elif mutation == "financial_replay": c04["no_financial_replay"] = False
    with pytest.raises(ValueError):
        validate_consumers(rows, core="1.1.2", native="0.4.3")


def test_e01_t04_shared_runner_isolated_commands_and_retained_hashes(tmp_path, monkeypatch):
    rows, calls = records(), []

    def run(command, **kwargs):
        calls.append(command)
        assert "PYTHONPATH" not in kwargs["env"] and "PYTHONHOME" not in kwargs["env"]
        assert all(kwargs["env"][k] == "1" for k in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"))
        name = Path(command[command.index("-I") + 1]).name
        if name == "qms_local_consumer.py": assert "--witness-transport" in command
        if name.startswith("qms_c0"): assert "--example" in command
        return SimpleNamespace(returncode=0, stdout=json.dumps(rows[name]), stderr="")

    monkeypatch.setattr(proof.subprocess, "run", run)
    result = proof.qualify(["python"], root=ROOT, core="1.1.2", native="0.4.3",
        workspace=tmp_path, logs=tmp_path / "logs", environment={"PYTHONPATH": "src", "PYTHONHOME": "wrong"})
    assert len(calls) == 4 and result["consumers"] == rows
    for record in result["logs"].values():
        assert sha256(Path(record["log_path"]).read_bytes()).hexdigest() == record["log_sha256"]
    assert "examples/optimization_exact_continuation.py" in result["consumer_source_sha256"]
    with pytest.raises(FileExistsError):
        proof.qualify(["python"], root=ROOT, core="1.1.2", native="0.4.3",
                      workspace=tmp_path, logs=tmp_path / "logs")


@pytest.mark.parametrize("failure", ["exit", "missing", "timeout", "json", "non_object"])
def test_e01_t05_subprocess_failure_keeps_log_without_pass(tmp_path, monkeypatch, failure):
    def run(command, **kwargs):
        if failure == "missing": raise FileNotFoundError("no native consumer interpreter")
        if failure == "timeout": raise subprocess.TimeoutExpired(command, 1)
        return SimpleNamespace(returncode=1 if failure == "exit" else 0,
                              stdout="[]" if failure == "non_object" else "not JSON", stderr="diagnostic")
    monkeypatch.setattr(proof.subprocess, "run", run)
    with pytest.raises(ValueError):
        proof.qualify(["python"], root=ROOT, core="1.1.2", native="0.4.3", workspace=tmp_path, logs=tmp_path / "logs")
    assert list((tmp_path / "logs").glob("*.log"))


def test_e01_t05_all_entrypoints_use_shared_mandatory_consumer_runner():
    for name in ("qms_installed_w3.py", "certify_native_release.py", "verify_public_native_consumer.py"):
        tree = ast.parse((ROOT / "tools" / name).read_text())
        imports = [n for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module == "tools.qms_installed_consumers"]
        assert len(imports) == 1
        alias = imports[0].names[0].asname
        assert any(isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == alias for n in ast.walk(tree))
    workflow = yaml.load((ROOT / ".github/workflows/qms-candidate.yml").read_text(), Loader=yaml.BaseLoader)
    filters = workflow["on"]["pull_request"]["paths"]
    assert "tools/qms_c0*" in filters and "tools/qms_installed_consumers.py" in filters
    assert "examples/wfo_reactive_samplers.py" in filters
    assert "src/quantbt/backends/reactive_wfo*.py" in filters
    assert "installed-w3-proof/**/*.log" in (ROOT / ".github/workflows/qms-candidate.yml").read_text()
    for name in ("native-release.yml", "publish-native.yml"):
        assert "dist/staged/qms-release-consumers/*.log" in (ROOT / ".github/workflows" / name).read_text()
    assert "public-native-consumer-*-qms-consumers/*.log" in (ROOT / ".github/workflows/public-native-consumer.yml").read_text()


def test_e01_t05_unknown_consumer_rejected():
    with pytest.raises(ValueError):
        consumer_arguments("made-up.py", core="1.1.2", native="0.4.3", examples=ROOT / "examples")
