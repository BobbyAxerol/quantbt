"""Registered study queue preserves failed attempts and rejects foreign seals."""

import json
from pathlib import Path

import pytest

from tools import qms_e03_queue as queue


def registration(monkeypatch):
    monkeypatch.setattr(queue, "read_registration", lambda p: (dict(source=dict(source_sha256={"x":"y"})), "seal"))
    monkeypatch.setattr(queue, "CELLS", [("unit", "native_vectorized")])


def test_e03_t05_queue_resumes_only_exact_registered_complete_arms(tmp_path, monkeypatch):
    registration(monkeypatch)
    for arm in ("off", "active"):
        (tmp_path / f"unit-native_vectorized-{arm}-off.json").write_text(json.dumps(
            dict(registration_sha256="seal", source_sha256={"x":"y"}, attempts=3584)))
    monkeypatch.setattr(queue, "summarize", lambda p: dict(rows=[{}]))
    queue.queue(tmp_path, prepared=False)
    assert not (tmp_path / "queue-executions.jsonl").exists()
    receipt = tmp_path / "unit-native_vectorized-off-off.json"
    receipt.write_text(json.dumps(dict(registration_sha256="foreign", source_sha256={"x":"y"}, attempts=3584)))
    with pytest.raises(ValueError, match="unmatched"):
        queue.queue(tmp_path, prepared=False)


def test_e03_t05_failed_queue_keeps_log_and_never_retries_automatically(tmp_path, monkeypatch):
    registration(monkeypatch)
    calls = []

    class FailedProcess:
        def __init__(self, command, **kw):
            calls.append(command)
            self.stdout = ["traceback\n", "error\n"]
            assert "PYTHONPATH" not in kw["env"]
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def wait(self): return 1

    monkeypatch.setattr(queue.subprocess, "Popen", FailedProcess)
    with pytest.raises(RuntimeError, match="no automatic retry"):
        queue.queue(tmp_path, prepared=False)
    assert len(calls) == 1
    execution = json.loads((tmp_path / "queue-executions.jsonl").read_text())
    assert execution["exit_code"] == 1 and execution["log_sha256"]
    assert (tmp_path / "unit-native_vectorized-off-off-attempt-1.log").read_text() == "traceback\nerror\n"
    assert not (tmp_path / "unit-native_vectorized-off-off.json").exists()


def test_e03_t04_prepared_trace_numeric_tolerance_never_changes_logical_pool():
    trial = dict(trial_id=1, params={"window":22}, objective=.4, mean_is_sharpe=.5,
                 pruned=False, fold_id=0)
    a = dict(trials=[trial])
    queue.prepared_trace_parity(a, dict(trials=[{**trial, "objective":.4+1e-12}]))
    for override in (dict(params={"window":24}), dict(objective=.41), dict(pruned=True)):
        with pytest.raises(AssertionError):
            queue.prepared_trace_parity(a, dict(trials=[{**trial, **override}]))
