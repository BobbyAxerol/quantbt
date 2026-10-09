"""Durable local export hook for the existing synchronous columnar writer."""

from dataclasses import asdict, dataclass
import json
import math
from pathlib import Path

from quantbt.core.research_audit import (
    ColumnarResearchTableV1, ResearchAuditWriterV1, ResearchRetentionPlanV1,
)
from quantbt.optimization.continuation.storage import read_checkpoint, write_checkpoint

from .identity import canonical, digest


@dataclass(frozen=True)
class TrialRecord:
    trial_id: str
    raw_params_id: str
    effective_params_id: str
    status: str
    execution_id: str | None = None
    objective: float | None = None
    reason: str | None = None

    def __post_init__(self):
        if (not self.trial_id or not self.raw_params_id or not self.effective_params_id
                or self.status not in {"COMPLETE", "DUPLICATE", "PRUNED", "FAILED", "CANCELLED"}):
            raise ValueError("invalid trial status/identity")
        if self.status == "COMPLETE":
            if not self.execution_id or self.objective is None or not math.isfinite(self.objective):
                raise ValueError("COMPLETE requires actual execution and finite measured objective")
        elif self.objective is not None or not self.reason:
            raise ValueError("non-complete trials require reason and no fabricated objective")


class DiagnosticAudit:
    """One producer, bounded retained chunks, synchronous durable backpressure.

    Publication uses the shared POSIX local-filesystem checkpoint primitive.
    This is not an Optuna/account recovery checkpoint or a remote object store.
    """

    def __init__(self, directory, *, chunk_rows=128, max_chunks=256):
        self.directory = Path(directory)
        if self.directory.exists():
            raise ValueError("fresh audit directory required; never overwrite historical evidence")
        self.directory.mkdir(parents=True, mode=0o700)
        self._trials = set()
        self._chunk_refs = []
        self._sealed = False
        self.writer = ResearchAuditWriterV1(plan=ResearchRetentionPlanV1(
            financial_retention="compact", research_retention="full_trial_ledger",
            chunk_rows=chunk_rows, max_retained_chunks=max_chunks), export_hook=self._export)

    def _export(self, table, chunk_id, chunk):
        if not table.replace("_", "").isalnum():
            raise ValueError("safe table name required")
        name = chunk_id.replace(":", "-")+".json"
        payload = dict(schema="quantbt.mode5.diagnostic_chunk.v1", table=table,
            chunk_id=chunk_id, logical_digest=chunk.logical_digest, records=chunk.to_records())
        encoded = canonical(payload)
        write_checkpoint(self.directory / name, encoded)
        self._chunk_refs.append(dict(file=name, digest=digest(payload), rows=chunk.row_count, table=table))

    def append_trials(self, rows):
        rows = tuple(rows)
        ids = [row.trial_id for row in rows]
        if len(set(ids)) != len(ids) or any(i in self._trials for i in ids):
            raise ValueError("a trial attempt must be retained exactly once")
        self.writer.append_records("trial_ledger", [asdict(row) for row in rows])
        self._trials.update(ids)

    def append(self, table, rows):
        if table == "trial_ledger":
            raise ValueError("use typed append_trials")
        self.writer.append_records(table, list(rows))

    def close(self, *, cancelled=False, reason=None, missing_range=None):
        if self._sealed:
            raise ValueError("audit already sealed")
        if cancelled:
            if not reason or not missing_range:
                raise ValueError("explicit cancellation/missing range required")
            self.writer.cancel(missing_range=missing_range, reason=reason)
        else:
            self.writer.close()
        metadata = self.writer.metadata()
        if metadata["writer_state"] not in {"memory_complete", "canceled"}:
            raise ValueError("failed flush cannot become COMPLETE")
        marker = dict(schema="quantbt.mode5.diagnostic_audit.v1",
            status="PARTIAL_CANCELLED" if cancelled else "COMPLETE", chunks=self._chunk_refs,
            source_writer=metadata, crash_durable="POSIX_LOCAL_CHUNKS_AND_FINAL_MARKER",
            expected_trial_ids=sorted(self._trials))
        write_checkpoint(self.directory / "completion.json", canonical(marker))
        self._sealed = True
        return recover(self.directory)


def recover(directory):
    """Inspect committed chunks; absent final marker is always partial."""
    directory = Path(directory)
    rows, refs = {}, []
    for path in sorted(directory.glob("*-*.json")):
        payload = json.loads(read_checkpoint(path))
        if payload.get("schema") != "quantbt.mode5.diagnostic_chunk.v1":
            raise ValueError("unknown diagnostic chunk schema")
        chunk = ColumnarResearchTableV1.from_records(table_name=payload["table"],
            chunk_id=payload["chunk_id"], records=payload["records"])
        if chunk.logical_digest != payload["logical_digest"]:
            raise ValueError("audit chunk logical digest mismatch")
        refs.append(dict(file=path.name, digest=digest(payload), rows=chunk.row_count, table=chunk.table_name))
        rows.setdefault(chunk.table_name, []).extend(chunk.to_records())
    marker_path = directory / "completion.json"
    marker = json.loads(read_checkpoint(marker_path)) if marker_path.exists() else None
    if marker is not None:
        if (marker.get("schema") != "quantbt.mode5.diagnostic_audit.v1"
                or sorted(marker["chunks"], key=lambda r: r["file"]) != refs):
            raise ValueError("audit marker/chunk inventory mismatch")
        actual_trials = [r["trial_id"] for r in rows.get("trial_ledger", [])]
        if sorted(actual_trials) != marker["expected_trial_ids"]:
            raise ValueError("trial attempt cardinality mismatch")
        for name, count in marker["source_writer"]["table_rows"].items():
            if count != len(rows.get(name, [])):
                raise ValueError("table cardinality mismatch")
    return dict(status="PARTIAL_INTERRUPTED" if marker is None else marker["status"],
                rows=rows, chunks=refs, marker=marker)
