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

    def __init__(self, directory, *, chunk_rows=128, max_chunks=256, max_bytes=64*1024**2):
        self.directory = Path(directory)
        if self.directory.exists():
            raise ValueError("fresh audit directory required; never overwrite historical evidence")
        self.directory.mkdir(parents=True, mode=0o700)
        self._trials = set()
        self._chunk_refs = []
        self._sealed = False
        if type(max_bytes) is not int or max_bytes <= 0:
            raise ValueError("positive audit byte budget required")
        self.max_bytes = max_bytes
        self._owned_bytes = 0
        self.writer = ResearchAuditWriterV1(plan=ResearchRetentionPlanV1(
            financial_retention="compact", research_retention="full_trial_ledger",
            chunk_rows=chunk_rows, max_retained_chunks=max_chunks), export_hook=self._export)

    def _export(self, table, chunk_id, chunk):
        if not table.isascii() or not table.replace("_", "").isalnum():
            raise ValueError("safe table name required")
        name = chunk_id.replace(":", "-")+".json"
        payload = dict(schema="quantbt.mode5.diagnostic_chunk.v1", table=table,
            chunk_id=chunk_id, logical_digest=chunk.logical_digest, records=chunk.to_records())
        encoded = canonical(payload)
        size = len(encoded.encode())+chunk.physical_bytes
        if self._owned_bytes+size > self.max_bytes:
            raise MemoryError("diagnostic audit byte budget exceeded; never drop required rows")
        write_checkpoint(self.directory / name, encoded)
        self._owned_bytes += size
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

    def close(self, *, expected_trial_ids, expected_rows, cancelled=False, reason=None, missing_range=None):
        if self._sealed:
            raise ValueError("audit already sealed")
        expected_trial_ids = tuple(expected_trial_ids)
        if len(set(expected_trial_ids)) != len(expected_trial_ids):
            raise ValueError("duplicate scheduled trial IDs")
        actual_rows = self.writer.metadata()["table_rows"]
        if not cancelled and (set(expected_trial_ids) != self._trials or dict(expected_rows) != actual_rows):
            raise ValueError("required audit/trial cardinality incomplete")
        if cancelled and not self._trials.issubset(expected_trial_ids):
            raise ValueError("retained trial is not scheduled")
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
            expected_trial_ids=sorted(self._trials), scheduled_trial_ids=sorted(expected_trial_ids),
            expected_rows=dict(expected_rows), owned_bytes=self._owned_bytes, max_bytes=self.max_bytes)
        write_checkpoint(self.directory / "completion.json", canonical(marker))
        self._sealed = True
        return recover(self.directory)


def recover(directory):
    """Inspect committed chunks; absent final marker is always partial."""
    directory = Path(directory)
    rows, refs = {}, []
    for path in sorted(directory.glob("*-*.json")):
        if path.is_symlink():
            raise ValueError("symlinked audit chunk")
        payload = json.loads(read_checkpoint(path))
        if payload.get("schema") != "quantbt.mode5.diagnostic_chunk.v1":
            raise ValueError("unknown diagnostic chunk schema")
        chunk = ColumnarResearchTableV1.from_records(table_name=payload["table"],
            chunk_id=payload["chunk_id"], records=payload["records"])
        expected_id = f'{chunk.table_name}:{sum(r["table"] == chunk.table_name for r in refs):08d}'
        if chunk.chunk_id != expected_id or path.name != chunk.chunk_id.replace(":", "-")+".json":
            raise ValueError("audit chunk sequence/name mismatch")
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
        if marker["status"] not in {"COMPLETE", "PARTIAL_CANCELLED"}:
            raise ValueError("invalid audit completion status")
        actual_trials = [r["trial_id"] for r in rows.get("trial_ledger", [])]
        if sorted(actual_trials) != marker["expected_trial_ids"]:
            raise ValueError("trial attempt cardinality mismatch")
        if marker["status"] == "COMPLETE" and (
                marker["scheduled_trial_ids"] != sorted(actual_trials)
                or marker["expected_rows"] != {k: len(v) for k, v in rows.items()}
                or marker["source_writer"]["writer_state"] != "memory_complete"):
            raise ValueError("required audit cardinality/state mismatch")
        for name, count in marker["source_writer"]["table_rows"].items():
            if count != len(rows.get(name, [])):
                raise ValueError("table cardinality mismatch")
    return dict(status="PARTIAL_INTERRUPTED" if marker is None else marker["status"],
                rows=rows, chunks=refs, marker=marker)
