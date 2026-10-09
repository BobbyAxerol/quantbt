"""Durability, bounded synchronous flush and all-attempt ledger fixtures."""

import json
from time import sleep

import pytest

from quantbt.core.research_audit import ResearchAuditBudgetError, ResearchAuditWriteError
from tools.mode5_diagnostics.audit import DiagnosticAudit, TrialRecord, recover


def trial(number, status="COMPLETE"):
    return TrialRecord(str(number), "raw"+str(number), "same-effective", status,
        "execution1" if status == "COMPLETE" else None,
        0. if status == "COMPLETE" else None, None if status == "COMPLETE" else status.lower())


def test_m5t_037_all_trial_states_reconcile_without_unique_execution_conflation(tmp_path):
    owner = DiagnosticAudit(tmp_path / "audit", chunk_rows=2)
    states = ["COMPLETE", "DUPLICATE", "PRUNED", "FAILED", "CANCELLED", "COMPLETE"]
    owner.append_trials([trial(i, status) for i, status in enumerate(states)])
    result = owner.close(expected_trial_ids=[str(i) for i in range(6)], expected_rows={"trial_ledger": 6})
    rows = result["rows"]["trial_ledger"]
    assert result["status"] == "COMPLETE" and len(rows) == 6
    assert [r["status"] for r in rows] == states
    assert {r["execution_id"] for r in rows if r["status"] == "COMPLETE"} == {"execution1"}
    assert all(r["objective"] is None for r in rows if r["status"] != "COMPLETE")
    with pytest.raises(ValueError, match="once"):
        owner.append_trials([trial(0)])


def test_m5t_038_failed_trials_never_become_complete_minus_sentinel():
    with pytest.raises(ValueError, match="fabricated"):
        TrialRecord("t", "raw", "effective", "FAILED", objective=-1e9, reason="error")
    with pytest.raises(ValueError, match="actual execution"):
        TrialRecord("t", "raw", "effective", "COMPLETE", objective=1.)


def test_m5t_040_slow_sink_backpressure_and_success_after_durable_flush(tmp_path):
    owner = DiagnosticAudit(tmp_path / "audit", chunk_rows=2)
    export = owner.writer._export_hook
    observed = []
    def slow(table, chunk_id, chunk):
        assert not (owner.directory / "completion.json").exists()
        sleep(.002)
        export(table, chunk_id, chunk)
        observed.append(chunk.row_count)
    owner.writer._export_hook = slow
    owner.append_trials([trial(i) for i in range(5)])
    result = owner.close(expected_trial_ids=[str(i) for i in range(5)], expected_rows={"trial_ledger": 5})
    assert observed == [2, 2, 1]
    assert result["marker"]["source_writer"]["queue_capacity_chunks"] == 1
    assert result["marker"]["source_writer"]["queue_high_watermark_chunks"] == 1


def test_m5t_040_cancelled_and_crashed_artifacts_are_partial_not_success(tmp_path):
    owner = DiagnosticAudit(tmp_path / "cancel", chunk_rows=1)
    owner.append_trials([trial(0), trial(1, "CANCELLED")])
    assert owner.close(expected_trial_ids=["0", "1", "2"], expected_rows={"trial_ledger": 3},
        cancelled=True, reason="requested", missing_range={"first_trial": 2})["status"] == "PARTIAL_CANCELLED"
    interrupted = DiagnosticAudit(tmp_path / "interrupted", chunk_rows=1)
    interrupted.append_trials([trial(0)])
    recovered = recover(interrupted.directory)
    assert recovered["status"] == "PARTIAL_INTERRUPTED" and len(recovered["rows"]["trial_ledger"]) == 1


def test_m5t_040_export_error_and_chunk_budget_never_emit_completion(tmp_path):
    owner = DiagnosticAudit(tmp_path / "failed", chunk_rows=1)
    export = owner.writer._export_hook
    def fails(table, chunk_id, chunk):
        if chunk_id.endswith("00000001"):
            raise OSError("synthetic disk failure")
        export(table, chunk_id, chunk)
    owner.writer._export_hook = fails
    with pytest.raises(ResearchAuditWriteError):
        owner.append_trials([trial(0), trial(1)])
    with pytest.raises(ValueError):
        owner.close(expected_trial_ids=["0", "1"], expected_rows={"trial_ledger": 2})
    assert recover(owner.directory)["status"] == "PARTIAL_INTERRUPTED"
    budget = DiagnosticAudit(tmp_path / "budget", chunk_rows=1, max_chunks=1)
    with pytest.raises(ResearchAuditBudgetError):
        budget.append_trials([trial(0), trial(1)])
    assert not (budget.directory / "completion.json").exists()


def test_missing_modified_extra_chunk_and_trial_id_rewrite_fail_recovery(tmp_path):
    owner = DiagnosticAudit(tmp_path / "audit", chunk_rows=1)
    owner.append_trials([trial(0)])
    owner.close(expected_trial_ids=["0"], expected_rows={"trial_ledger": 1})
    path = owner.directory / "trial_ledger-00000000.json"
    payload = json.loads(path.read_text())
    payload["records"][0]["objective"] = -999.
    path.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="digest"):
        recover(owner.directory)


def test_audit_table_name_and_double_close_are_rejected(tmp_path):
    owner = DiagnosticAudit(tmp_path / "audit")
    with pytest.raises(ResearchAuditWriteError):
        owner.append("../escape", [{"value": 1}])
    assert not (tmp_path / "escape.json").exists()
    healthy = DiagnosticAudit(tmp_path / "healthy")
    healthy.append_trials([trial(0)])
    healthy.close(expected_trial_ids=["0"], expected_rows={"trial_ledger": 1})
    with pytest.raises(ValueError, match="sealed"):
        healthy.close(expected_trial_ids=["0"], expected_rows={"trial_ledger": 1})


def test_removed_or_extra_chunk_cannot_pass_completed_inventory(tmp_path):
    from shutil import copyfile
    owner = DiagnosticAudit(tmp_path / "audit")
    owner.append_trials([trial(0)])
    owner.close(expected_trial_ids=["0"], expected_rows={"trial_ledger": 1})
    path = owner.directory / "trial_ledger-00000000.json"
    copyfile(path, owner.directory / "trial_ledger-00000001.json")
    with pytest.raises(ValueError, match="sequence"):
        recover(owner.directory)
    (owner.directory / "trial_ledger-00000001.json").unlink()
    path.unlink()
    with pytest.raises(ValueError, match="inventory"):
        recover(owner.directory)


def test_m5t_040_byte_budget_and_missing_scheduled_attempt_block_success(tmp_path):
    small = DiagnosticAudit(tmp_path / "small", max_bytes=1)
    with pytest.raises(ResearchAuditWriteError, match="budget"):
        small.append_trials([trial(0)])
    assert not (small.directory / "completion.json").exists()
    owner = DiagnosticAudit(tmp_path / "missing")
    owner.append_trials([trial(0)])
    with pytest.raises(ValueError, match="incomplete"):
        owner.close(expected_trial_ids=["0", "1"], expected_rows={"trial_ledger": 2})
    assert recover(owner.directory)["status"] == "PARTIAL_INTERRUPTED"


def test_m5t_040_fsync_failure_has_no_success_marker(tmp_path, monkeypatch):
    from quantbt.optimization.continuation import storage
    owner = DiagnosticAudit(tmp_path / "fsync")
    def fail(_):
        raise OSError("synthetic fsync failure")
    monkeypatch.setattr(storage.os, "fsync", fail)
    with pytest.raises(ResearchAuditWriteError, match="fsync"):
        owner.append_trials([trial(0)])
    assert recover(owner.directory)["status"] == "PARTIAL_INTERRUPTED"


def test_m5t_037_optuna_trial_store_matches_append_only_attempts(tmp_path):
    import optuna
    study = optuna.create_study(sampler=optuna.samplers.RandomSampler(seed=731))
    def objective(trial):
        trial.suggest_int("fixed", 1, 1)
        if trial.number == 1:
            raise optuna.TrialPruned("synthetic pruning")
        if trial.number == 2:
            raise RuntimeError("synthetic runtime error")
        return 0.
    study.optimize(objective, n_trials=4, catch=(RuntimeError,))
    owner = DiagnosticAudit(tmp_path / "optuna")
    mapping = {"COMPLETE": "COMPLETE", "PRUNED": "PRUNED", "FAIL": "FAILED"}
    owner.append_trials([trial(t.number, mapping[t.state.name]) for t in study.trials])
    done = owner.close(expected_trial_ids=[str(t.number) for t in study.trials], expected_rows={"trial_ledger": 4})
    assert [r["status"] for r in done["rows"]["trial_ledger"]] == ["COMPLETE", "PRUNED", "FAILED", "COMPLETE"]
