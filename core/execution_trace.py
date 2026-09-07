"""Canonical execution trace, deterministic fingerprint, and replay verifier."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import math
import struct
from typing import Iterable, Mapping

import numpy as np
import pandas as pd

from ._trace_columns import AccountSnapshotProjection, TraceColumns


TRACE_SCHEMA_VERSION = "canonical-execution-trace-v1"
TRACE_FLOAT_CANONICAL_DECIMALS = 12
TRACE_FIELDS = (
    "trace_schema_version", "run_id", "bar", "timestamp_ns", "phase", "sequence",
    "event_kind", "command_id", "order_id", "order_generation", "parent_id",
    "group_id", "oco_id", "package_id", "symbol_code", "venue_code", "side",
    "order_type", "tif", "qty_before", "qty_delta", "qty_after", "price", "fee",
    "funding", "position_before", "position_after", "equity_before", "equity_after",
    "initial_margin_after", "maintenance_margin_after", "command_outcome",
    "order_status", "reason_code",
)
_FLOAT_FIELDS = frozenset(
    {
        "qty_before", "qty_delta", "qty_after", "price", "fee", "funding",
        "position_before", "position_after", "equity_before", "equity_after",
        "initial_margin_after", "maintenance_margin_after",
    }
)
_INT_FIELDS = frozenset({"bar", "timestamp_ns", "sequence", "order_generation", "symbol_code", "venue_code"})


@dataclass(frozen=True)
class CanonicalTraceArtifact:
    trace: pd.DataFrame
    fingerprint: str
    row_count: int
    event_counts: Mapping[str, int]
    column_store: TraceColumns | None = None

    def to_metadata(self) -> dict[str, object]:
        return {
            "trace_schema_version": TRACE_SCHEMA_VERSION,
            "canonical_trace_v1": self.trace,
            "canonical_trace_fingerprint": self.fingerprint,
            "canonical_trace_row_count": int(self.row_count),
            "canonical_trace_event_counts": dict(self.event_counts),
        }


@dataclass(frozen=True)
class TraceReplayResult:
    final_positions: Mapping[str, float]
    final_equity: float
    transitions_valid: bool
    terminal_orders_valid: bool
    package_reconciliation_valid: bool
    errors: tuple[str, ...]

    @property
    def passed(self) -> bool:
        return not self.errors


class TraceReplayer:
    """Verify a trace without re-running order matching or market simulation."""

    def replay(self, trace: pd.DataFrame, *, tolerance: float = 1e-12) -> TraceReplayResult:
        _validate_trace_frame(trace)
        fills: dict[str, float] = {}
        snapshots: dict[str, float] = {}
        final_equity = math.nan
        order_states: dict[str, str] = {}
        errors: list[str] = []

        for row in trace.itertuples(index=False):
            kind = str(row.event_kind)
            symbol = str(row.symbol_code)
            if kind == "FILL_ACCOUNTING" and symbol not in {"", "-1"}:
                before = fills.get(symbol, 0.0)
                after = before + float(row.qty_delta)
                if abs(float(row.qty_before) - before) > tolerance or abs(float(row.qty_after) - after) > tolerance:
                    errors.append(f"fill position transition mismatch at sequence={row.sequence}")
                fills[symbol] = after
            elif kind == "ACCOUNT_SNAPSHOT" and symbol not in {"", "-1"}:
                before = snapshots.get(symbol, 0.0)
                after = before + float(row.qty_delta)
                if abs(float(row.qty_before) - before) > tolerance or abs(float(row.qty_after) - after) > tolerance:
                    errors.append(f"snapshot position transition mismatch at sequence={row.sequence}")
                snapshots[symbol] = float(row.qty_after)
                final_equity = float(row.equity_after)
            elif kind == "LIFECYCLE":
                order_id = str(row.order_id)
                status = str(row.order_status)
                if order_id:
                    previous = order_states.get(order_id)
                    if previous in {"FILLED", "CANCELED", "REJECTED", "EXPIRED"} and status != previous:
                        errors.append(f"terminal order {order_id!r} transitioned from {previous} to {status}")
                    order_states[order_id] = status

        if not snapshots and fills:
            errors.append("trace contains fills but no account snapshots")
        if not np.isfinite(final_equity):
            errors.append("trace does not contain a finite terminal equity snapshot")

        package_ok = True
        package_rows = trace[(trace["package_id"].astype(str) != "") & (trace["event_kind"] == "PACKAGE_RECONCILIATION")]
        if not package_rows.empty:
            package_ok = bool((package_rows["reason_code"].astype(str) == "OK").all())
            if not package_ok:
                errors.append("package reconciliation row reports a residual")

        return TraceReplayResult(
            final_positions=dict(snapshots),
            final_equity=final_equity,
            transitions_valid=not any("transition" in error for error in errors),
            terminal_orders_valid=not any("terminal order" in error for error in errors),
            package_reconciliation_valid=package_ok,
            errors=tuple(errors),
        )

    def replay_columns(
        self,
        columns: TraceColumns,
        *,
        tolerance: float = 1e-12,
    ) -> TraceReplayResult:
        """Replay the just-built column store before pandas adaptation.

        The public audit frame is still materialized unchanged.  This simply
        avoids a second dense Python/Pandas row traversal while the canonical
        columns are already owned by the trace builder.
        """

        fills: dict[str, float] = {}
        snapshots: dict[str, float] = {}
        final_equity = math.nan
        order_states: dict[str, str] = {}
        errors: list[str] = []
        package_ok = True
        data = columns.columns
        for row in range(columns.size):
            kind = str(data["event_kind"][row])
            symbol = str(data["symbol_code"][row])
            if kind == "FILL_ACCOUNTING" and symbol not in {"", "-1"}:
                before = fills.get(symbol, 0.0)
                delta = float(data["qty_delta"][row])
                after = before + delta
                if (
                    abs(float(data["qty_before"][row]) - before) > tolerance
                    or abs(float(data["qty_after"][row]) - after) > tolerance
                ):
                    errors.append(f"fill position transition mismatch at sequence={data['sequence'][row]}")
                fills[symbol] = after
            elif kind == "ACCOUNT_SNAPSHOT" and symbol not in {"", "-1"}:
                before = snapshots.get(symbol, 0.0)
                delta = float(data["qty_delta"][row])
                after = before + delta
                if (
                    abs(float(data["qty_before"][row]) - before) > tolerance
                    or abs(float(data["qty_after"][row]) - after) > tolerance
                ):
                    errors.append(f"snapshot position transition mismatch at sequence={data['sequence'][row]}")
                snapshots[symbol] = float(data["qty_after"][row])
                final_equity = float(data["equity_after"][row])
            elif kind == "LIFECYCLE":
                order_id = str(data["order_id"][row])
                status = str(data["order_status"][row])
                if order_id:
                    previous = order_states.get(order_id)
                    if previous in {"FILLED", "CANCELED", "REJECTED", "EXPIRED"} and status != previous:
                        errors.append(f"terminal order {order_id!r} transitioned from {previous} to {status}")
                    order_states[order_id] = status
            elif kind == "PACKAGE_RECONCILIATION":
                if str(data["package_id"][row]) != "" and str(data["reason_code"][row]) != "OK":
                    package_ok = False
                    errors.append("package reconciliation row reports a residual")
        if not snapshots and fills:
            errors.append("trace contains fills but no account snapshots")
        if not np.isfinite(final_equity):
            errors.append("trace does not contain a finite terminal equity snapshot")
        return TraceReplayResult(
            final_positions=dict(snapshots),
            final_equity=final_equity,
            transitions_valid=not any("transition" in error for error in errors),
            terminal_orders_valid=not any("terminal order" in error for error in errors),
            package_reconciliation_valid=package_ok,
            errors=tuple(errors),
        )


def build_canonical_execution_trace(
    result,
    *,
    run_id: str = "native-event-run",
    materialize: bool = True,
) -> CanonicalTraceArtifact:
    """Project a backend result into the versioned backend-neutral trace."""

    metadata = getattr(result, "metadata", {}) or {}
    index = pd.DatetimeIndex(result.equity.index)
    timestamp_to_bar = {int(ts): bar for bar, ts in enumerate(index.asi8)}
    symbol_codes = {str(symbol): code for code, symbol in enumerate(result.symbols)}
    sequence = 0

    phase_report = _frame(metadata.get("event_phase_trace_v1"))
    lifecycle_report = _frame(metadata.get("lifecycle_event_report_v1"))
    command_report = _frame(metadata.get("command_report", metadata.get("order_report")))
    accounting = _frame(metadata.get("accounting_ledger_v1"))
    symbol_accounting = _frame(metadata.get("symbol_accounting_ledger_v1"))
    liquidation = _frame(metadata.get("liquidation_attribution_v1"))

    command_details = _command_details(command_report)
    lifecycle_by_bar = _group_rows(lifecycle_report, "bar")
    phase_by_bar = _group_rows(phase_report, "bar")
    fills_by_bar: dict[int, list[object]] = {}
    for fill in tuple(getattr(result, "fills", ()) or ()):
        bar = timestamp_to_bar.get(int(pd.Timestamp(fill.timestamp).value), -1)
        fills_by_bar.setdefault(bar, []).append(fill)
    liquidation_by_bar = _group_rows(liquidation, "bar")
    snapshots = AccountSnapshotProjection(symbol_accounting, index, timestamp_to_bar)
    sparse_counts = np.zeros(len(index), dtype=np.int64)
    for groups in (phase_by_bar, lifecycle_by_bar, fills_by_bar, liquidation_by_bar):
        for bar, sources in groups.items():
            if 0 <= bar < len(index):
                sparse_counts[bar] += len(sources)
    counts = sparse_counts + snapshots.counts
    offsets = np.cumsum(counts) - counts
    rows = TraceColumns(int(counts.sum()), _row(), _FLOAT_FIELDS, _INT_FIELDS)
    rows.size = int(counts.sum())
    snapshots.write(rows, offsets, sparse_counts, index, accounting, result, symbol_codes, run_id)
    previous_fill: dict[str, float] = {str(symbol): 0.0 for symbol in result.symbols}
    for bar in np.flatnonzero(sparse_counts):
        timestamp_ns = int(index[bar].value)
        sequence = int(offsets[bar])
        rows.cursor = sequence
        for source in phase_by_bar.get(bar, ()):
            rows.append(
                dict(
                    run_id=run_id, bar=bar, timestamp_ns=timestamp_ns, phase=str(source.get("phase", "")),
                    sequence=sequence, event_kind="PHASE", reason_code="OK",
                )
            )
            sequence += 1

        for source in lifecycle_by_bar.get(bar, ()):
            order_id = _text(source.get("order_id"))
            detail = command_details.get(order_id, {})
            rows.append(
                dict(
                    run_id=run_id, bar=bar, timestamp_ns=timestamp_ns, phase="LIFECYCLE",
                    sequence=sequence, event_kind="LIFECYCLE", command_id=order_id,
                    order_id=order_id,
                    parent_id=_text(_first_present(source.get("parent_order_id"), detail.get("parent_order_id"))),
                    group_id=_text(_first_present(source.get("group_id"), detail.get("group_id"))),
                    oco_id=_text(_first_present(source.get("oco_group_id"), detail.get("oco_group_id"))),
                    package_id=_text(detail.get("package_id")), symbol_code=symbol_codes.get(_text(detail.get("symbol")), -1),
                    venue_code=0, side=_text(detail.get("side")), order_type=_text(detail.get("order_type")),
                    # TIF is intentionally blank until both backend audit
                    # adapters expose the canonical value. It remains part of
                    # the versioned schema and cannot silently disagree.
                    tif="", command_outcome=_text(detail.get("command_outcome")),
                    order_status=_text(source.get("lifecycle_order_status", source.get("status"))),
                    reason_code=_reason_code(_first_present(source.get("reject_code"), detail.get("reject_code", "OK"))),
                )
            )
            sequence += 1

        for fill in fills_by_bar.get(bar, ()):
            symbol = str(fill.symbol)
            before = previous_fill.get(symbol, 0.0)
            delta = float(fill.signed_qty)
            after = before + delta
            detail = command_details.get(_text(fill.order_id), {})
            rows.append(
                dict(
                    run_id=run_id, bar=bar, timestamp_ns=timestamp_ns, phase="FILL_ACCOUNTING",
                    sequence=sequence, event_kind="FILL_ACCOUNTING", command_id=_text(fill.order_id),
                    order_id=_text(fill.order_id), parent_id=_text(detail.get("parent_order_id")),
                    group_id=_text(detail.get("group_id")), oco_id=_text(detail.get("oco_group_id")),
                    package_id=_text(detail.get("package_id")), symbol_code=symbol_codes[symbol], venue_code=0,
                    side=_text(getattr(fill.side, "value", fill.side)), order_type=_text(detail.get("order_type")),
                    tif="", qty_before=before, qty_delta=delta, qty_after=after,
                    price=float(fill.price), fee=float(fill.fee), position_before=before, position_after=after,
                    command_outcome="ACCEPTED", order_status="FILLED", reason_code="OK",
                )
            )
            previous_fill[symbol] = after
            sequence += 1

        for source in liquidation_by_bar.get(bar, ()):
            rows.append(
                dict(
                    run_id=run_id, bar=bar, timestamp_ns=timestamp_ns, phase="LIQUIDATION",
                    sequence=sequence, event_kind="LIQUIDATION_ALLOCATION",
                    equity_before=float(source.get("liquidation_cost", 0.0)),
                    equity_after=float(source.get("residual_equity", 0.0)),
                    reason_code=_text(source.get("reason_code")),
                )
            )
            sequence += 1

    fingerprint = rows.fingerprint(TRACE_SCHEMA_VERSION, _normalized_value_bytes)
    trace = rows.frame() if materialize else pd.DataFrame(columns=TRACE_FIELDS)
    return CanonicalTraceArtifact(trace, fingerprint, rows.size, rows.event_counts, rows)


def attach_canonical_execution_trace(result, *, run_id: str = "native-event-run"):
    artifact = build_canonical_execution_trace(result, run_id=run_id, materialize=True)
    column_store = getattr(artifact, "column_store", None)
    replay = (
        TraceReplayer().replay_columns(column_store)
        if column_store is not None
        else TraceReplayer().replay(artifact.trace)
    )
    result.metadata.update(artifact.to_metadata())
    result.metadata["canonical_trace_replay_v1"] = {
        "passed": replay.passed,
        "final_positions": dict(replay.final_positions),
        "final_equity": replay.final_equity,
        "transitions_valid": replay.transitions_valid,
        "terminal_orders_valid": replay.terminal_orders_valid,
        "package_reconciliation_valid": replay.package_reconciliation_valid,
        "errors": list(replay.errors),
    }
    return result


def canonical_trace_fingerprint(trace: pd.DataFrame | Iterable[Mapping[str, object]]) -> str:
    """Hash normalized fields with canonical NaN and little-endian floats."""

    if isinstance(trace, pd.DataFrame):
        _validate_trace_frame(trace)
        # Keep the public arbitrary-value serializer, without a second dense
        # list of row dictionaries for callers fingerprinting an audit frame.
        records = (dict(zip(TRACE_FIELDS, values))
                   for values in trace.loc[:, TRACE_FIELDS].itertuples(index=False, name=None))
    else:
        records = trace
    digest = sha256(TRACE_SCHEMA_VERSION.encode("ascii"))
    for record in records:
        for field in TRACE_FIELDS:
            digest.update(_normalized_value_bytes(field, record.get(field)))
    return digest.hexdigest()


def compare_canonical_traces(left: pd.DataFrame, right: pd.DataFrame) -> dict[str, object]:
    """Return the first divergent field with bar/phase/event context."""

    _validate_trace_frame(left)
    _validate_trace_frame(right)
    limit = min(len(left), len(right))
    for index in range(limit):
        lhs = left.iloc[index]
        rhs = right.iloc[index]
        for field in TRACE_FIELDS:
            if _normalized_value_bytes(field, lhs[field]) != _normalized_value_bytes(field, rhs[field]):
                return {
                    "passed": False,
                    "row": index,
                    "bar": int(lhs["bar"]),
                    "phase": str(lhs["phase"]),
                    "event_kind": str(lhs["event_kind"]),
                    "field": field,
                    "left": lhs[field],
                    "right": rhs[field],
                }
    if len(left) != len(right):
        return {"passed": False, "row": limit, "field": "row_count", "left": len(left), "right": len(right)}
    return {"passed": True, "row_count": len(left), "fingerprint": canonical_trace_fingerprint(left)}


def _row(**values) -> dict[str, object]:
    defaults: dict[str, object] = {field: "" for field in TRACE_FIELDS}
    for field in _FLOAT_FIELDS:
        defaults[field] = math.nan
    for field in _INT_FIELDS:
        defaults[field] = -1
    defaults["trace_schema_version"] = TRACE_SCHEMA_VERSION
    defaults["order_generation"] = 0
    defaults.update(values)
    return defaults


def _normalized_value_bytes(field: str, value: object) -> bytes:
    if field in _FLOAT_FIELDS:
        numeric = float(value) if value is not None else math.nan
        if math.isnan(numeric):
            return struct.pack("<Q", 0x7FF8000000000000)
        # Python and Rust both use IEEE-754 f64 but may accumulate equivalent
        # multi-symbol margin values in a different order. Canonical trace
        # identity uses a 12-decimal projection derived from the public
        # native-event parity precision, rather than treating harmless f64
        # accumulation-order artifacts as lifecycle divergence. Raw accounting
        # arrays are never rounded here.
        numeric = round(numeric, TRACE_FLOAT_CANONICAL_DECIMALS)
        if numeric == 0.0:
            numeric = 0.0  # normalize a possible negative zero before packing
        return struct.pack("<d", numeric)
    if field in _INT_FIELDS:
        return struct.pack("<q", int(value if value is not None else -1))
    encoded = _text(value).encode("utf-8")
    return struct.pack("<I", len(encoded)) + encoded


def _validate_trace_frame(trace: pd.DataFrame) -> None:
    missing = [field for field in TRACE_FIELDS if field not in trace]
    if missing:
        raise ValueError(f"canonical trace missing fields: {missing}")


def _frame(value) -> pd.DataFrame:
    return value if isinstance(value, pd.DataFrame) else pd.DataFrame()


def _group_rows(frame: pd.DataFrame, field: str) -> dict[int, list[dict[str, object]]]:
    if frame.empty or field not in frame:
        return {}
    grouped: dict[int, list[dict[str, object]]] = {}
    for record in frame.to_dict("records"):
        grouped.setdefault(int(record[field]), []).append(record)
    return grouped


def _command_details(frame: pd.DataFrame) -> dict[str, dict[str, object]]:
    if frame.empty or "order_id" not in frame:
        return {}
    return {_text(record.get("order_id")): record for record in frame.to_dict("records")}


def _text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and math.isnan(value):
        return ""
    return str(getattr(value, "value", value))


def _first_present(*values: object) -> object:
    """Return the first non-null trace source without truthiness coercion.

    Rust lifecycle rows own terminal status/rejection values, while relationship
    metadata remains immutable on the originating command.  This lets the
    canonical trace project both sources without losing an explicit numeric
    zero or treating a NumPy NaN as meaningful data.
    """

    for value in values:
        if _text(value) != "":
            return value
    return None


def _reason_code(value: object) -> str:
    text = _text(value)
    return "OK" if text in {"", "0", "0.0", "OK"} else text


__all__ = [
    "TRACE_FIELDS",
    "TRACE_SCHEMA_VERSION",
    "CanonicalTraceArtifact",
    "TraceReplayResult",
    "TraceReplayer",
    "attach_canonical_execution_trace",
    "build_canonical_execution_trace",
    "canonical_trace_fingerprint",
    "compare_canonical_traces",
]
