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
    result = owner.close()
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
    result = owner.close()
    assert observed == [2, 2, 1]
    assert result["marker"]["source_writer"]["queue_capacity_chunks"] == 1
    assert result["marker"]["source_writer"]["queue_high_watermark_chunks"] == 1


def test_m5t_040_cancelled_and_crashed_artifacts_are_partial_not_success(tmp_path):
    owner = DiagnosticAudit(tmp_path / "cancel", chunk_rows=1)
    owner.append_trials([trial(0), trial(1, "CANCELLED")])
    assert owner.close(cancelled=True, reason="requested", missing_range={"first_trial": 2})["status"] == "PARTIAL_CANCELLED"
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
    with pytest.raises(ValueError, match="failed flush"):
        owner.close()
    assert recover(owner.directory)["status"] == "PARTIAL_INTERRUPTED"
    budget = DiagnosticAudit(tmp_path / "budget", chunk_rows=1, max_chunks=1)
    with pytest.raises(ResearchAuditBudgetError):
        budget.append_trials([trial(0), trial(1)])
    assert not (budget.directory / "completion.json").exists()


def test_missing_modified_extra_chunk_and_trial_id_rewrite_fail_recovery(tmp_path):
    owner = DiagnosticAudit(tmp_path / "audit", chunk_rows=1)
    owner.append_trials([trial(0)])
    owner.close()
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
