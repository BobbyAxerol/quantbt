"""Registered metric repair never retunes or loses failed worker evidence."""

import json
from pathlib import Path

import pytest

from tools import qms_g01_study as study


def registration(tmp_path, monkeypatch):
    monkeypatch.setattr(study, "private_path", lambda p: Path(p))
    monkeypatch.setattr(study, "read_registration", lambda p: ({}, "seal"))
    monkeypatch.setattr(study, "verify", lambda: {"approved": "source"})
    amendment = dict(original_registration_sha256="seal", source={"approved": "source"})
    (tmp_path/"g01-replay-registration.json").write_text(json.dumps(amendment))
    return amendment


def test_g01_resume_accepts_only_identical_registered_complete_arms(tmp_path, monkeypatch):
    amendment = registration(tmp_path, monkeypatch)
    for preparation in ("off", "require"):
        (tmp_path/f"unit-native_vectorized-active-{preparation}.json").write_text(json.dumps(
            dict(registration_sha256="seal", attempts=3584, approved_metric_amendment=amendment)))
    monkeypatch.setattr(study, "compare", lambda **kwargs: {"compared": True})
    assert study.queue(original=tmp_path, output=tmp_path) == {"compared": True}
    assert not (tmp_path/"queue-executions.jsonl").exists()
    file = tmp_path/"unit-native_vectorized-active-off.json"
    file.write_text(json.dumps(dict(registration_sha256="foreign", attempts=3584,
                                   approved_metric_amendment=amendment)))
    with pytest.raises(ValueError, match="unmatched"):
        study.queue(original=tmp_path, output=tmp_path)


def test_g01_failure_retains_log_and_never_starts_second_arm(tmp_path, monkeypatch):
    registration(tmp_path, monkeypatch)
    calls = []

    class FailedProcess:
        def __init__(self, command, **kwargs):
            calls.append(command)
            self.stdout = ["traceback\n", "failed\n"]
            assert "PYTHONPATH" not in kwargs["env"]
            assert kwargs["env"]["OPENBLAS_NUM_THREADS"] == "1"

        def __enter__(self): return self
        def __exit__(self, *args): pass
        def wait(self): return 1

    monkeypatch.setattr(study.subprocess, "Popen", FailedProcess)
    with pytest.raises(RuntimeError, match="no automatic retry"):
        study.queue(original=tmp_path, output=tmp_path)
    assert len(calls) == 1 and "--g01-replay" in calls[0]
    execution = json.loads((tmp_path/"queue-executions.jsonl").read_text())
    assert execution["exit_code"] == 1 and execution["log_sha256"]
    assert (tmp_path/"unit-native_vectorized-active-off-attempt-1.log").read_text() == "traceback\nfailed\n"
    assert not (tmp_path/"unit-native_vectorized-active-off.json").exists()


def test_g01_registration_drift_prevents_any_worker_start(tmp_path, monkeypatch):
    registration(tmp_path, monkeypatch)
    monkeypatch.setattr(study, "verify", lambda: {"unapproved": "source"})
    with pytest.raises(ValueError, match="source amendment changed"):
        study.queue(original=tmp_path, output=tmp_path)
