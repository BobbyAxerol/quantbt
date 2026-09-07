"""Backend-neutral Canonical Trace V2 verification substrate.

This module is deliberately independent from result objects, pandas, Numba,
and the native extension.  Production routes continue to emit their existing
audit artifacts.  Phase 57 uses V2 to compare bounded fixtures without making
V2 a new runtime authority.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
import math
import struct
from typing import Iterable, Mapping, Sequence


CANONICAL_TRACE_V2_SCHEMA_VERSION = "canonical-trace-v2"
CANONICAL_TRACE_V2_SERIALIZER = "canonical-little-endian-v1"
CANONICAL_TRACE_V2_HASH = "fnv1a-dual-128-v1"
TERMINAL_FINGERPRINT_V2_SCHEMA_VERSION = "terminal-fingerprint-v2"
MISSING_ID = -1


class CanonicalEventKindV2(IntEnum):
    """Integer event vocabulary shared by future Python and Rust emitters."""

    MARKET_OBSERVED = 1
    FUNDING_APPLIED = 2
    COMMAND_SUBMITTED = 3
    COMMAND_ACCEPTED = 4
    COMMAND_REJECTED = 5
    ORDER_ACTIVATED = 6
    ORDER_AMENDED = 7
    ORDER_CANCELED = 8
    ORDER_EXPIRED = 9
    ORDER_TRIGGERED = 10
    FILL_COMMITTED = 11
    FEE_CHARGED = 12
    POSITION_CHANGED = 13
    CASH_CHANGED = 14
    MARGIN_CHANGED = 15
    LIQUIDATION_STARTED = 16
    LIQUIDATION_FILL = 17
    LIQUIDATION_COMPLETED = 18
    PACKAGE_STATE_CHANGED = 19
    RESERVATION_CREATED = 20
    RESERVATION_CONSUMED = 21
    RESERVATION_RELEASED = 22
    SETTLEMENT_APPLIED = 23
    RUN_COMPLETED = 24
    ACCOUNT_SNAPSHOT = 25


_FLOAT_FIELDS = (
    "qty",
    "price",
    "fee",
    "cash_before",
    "cash_after",
    "position_before",
    "position_after",
    "realized_pnl_before",
    "realized_pnl_after",
    "initial_margin_before",
    "initial_margin_after",
    "maintenance_margin_before",
    "maintenance_margin_after",
)
_DISCRETE_FIELDS = (
    "sequence",
    "bar_index",
    "event_timestamp_ns",
    "effective_timestamp_ns",
    "symbol_id",
    "account_id",
    "package_id",
    "order_id",
    "event_kind",
    "reason_code",
    "order_status_code",
    "state_hash_before",
    "state_hash_after",
)
_FNV64_PRIME = 0x100000001B3
_FNV64_OFFSET_A = 0xCBF29CE484222325
_FNV64_OFFSET_B = 0x84222325CBF29CE4
_U64_MASK = (1 << 64) - 1


@dataclass(frozen=True, slots=True)
class TraceFieldToleranceV2:
    """One declared comparison and hash-normalization policy for one field."""

    comparison: str
    absolute: float = 0.0
    relative: float = 0.0
    normalization_quantum: float = 0.0

    def __post_init__(self) -> None:
        if self.absolute < 0.0 or self.relative < 0.0 or self.normalization_quantum < 0.0:
            raise ValueError("trace tolerances must be non-negative")

    def normalize(self, value: float) -> float:
        if not math.isfinite(value) or self.normalization_quantum == 0.0:
            return float(value)
        units = math.floor(abs(value) / self.normalization_quantum + 0.5)
        normalized = units * self.normalization_quantum
        return math.copysign(normalized, value) if normalized else 0.0

    def equal(self, left: float, right: float) -> bool:
        if math.isnan(left) or math.isnan(right):
            return math.isnan(left) and math.isnan(right)
        if math.isinf(left) or math.isinf(right):
            return left == right
        limit = max(self.absolute, self.relative * max(abs(left), abs(right)))
        return abs(left - right) <= limit


@dataclass(frozen=True, slots=True)
class TraceTolerancePolicyV2:
    """Versioned field-specific policy; deliberately no global epsilon exists."""

    policy_id: str
    quantity: TraceFieldToleranceV2
    price: TraceFieldToleranceV2
    financial: TraceFieldToleranceV2
    metrics: TraceFieldToleranceV2

    def for_field(self, field: str) -> TraceFieldToleranceV2:
        if field in {"qty", "position_before", "position_after"}:
            return self.quantity
        if field == "price":
            return self.price
        if field in _FLOAT_FIELDS:
            return self.financial
        raise KeyError(f"no float tolerance is declared for {field!r}")


def default_linear_trace_tolerance_v2() -> TraceTolerancePolicyV2:
    """Return the V1.1 linear default from the machine-readable contract."""

    return TraceTolerancePolicyV2(
        policy_id="trace-tolerance-v2-linear-default",
        quantity=TraceFieldToleranceV2("lot_aware", absolute=1e-12, normalization_quantum=1e-12),
        price=TraceFieldToleranceV2("tick_aware", absolute=1e-10, relative=1e-12, normalization_quantum=1e-10),
        financial=TraceFieldToleranceV2("financial", absolute=1e-9, relative=1e-12, normalization_quantum=1e-10),
        metrics=TraceFieldToleranceV2("metric", absolute=1e-8, relative=1e-10, normalization_quantum=1e-8),
    )


@dataclass(frozen=True, slots=True)
class CanonicalTraceRowV2:
    """One typed trace row; absent identifiers use the ``-1`` sentinel."""

    sequence: int
    bar_index: int
    event_timestamp_ns: int
    effective_timestamp_ns: int
    event_kind: CanonicalEventKindV2
    symbol_id: int = MISSING_ID
    account_id: int = 0
    package_id: int = MISSING_ID
    order_id: int = MISSING_ID
    reason_code: int = 0
    order_status_code: int = MISSING_ID
    qty: float = math.nan
    price: float = math.nan
    fee: float = math.nan
    cash_before: float = math.nan
    cash_after: float = math.nan
    position_before: float = math.nan
    position_after: float = math.nan
    realized_pnl_before: float = math.nan
    realized_pnl_after: float = math.nan
    initial_margin_before: float = math.nan
    initial_margin_after: float = math.nan
    maintenance_margin_before: float = math.nan
    maintenance_margin_after: float = math.nan
    state_hash_before: int = MISSING_ID
    state_hash_after: int = MISSING_ID

    def __post_init__(self) -> None:
        if self.sequence < 0:
            raise ValueError("trace sequence must be >= 0")
        if self.bar_index < MISSING_ID:
            raise ValueError("bar_index must be >= -1")
        if self.event_timestamp_ns < MISSING_ID or self.effective_timestamp_ns < MISSING_ID:
            raise ValueError("trace timestamps must be >= -1")
        for field in ("symbol_id", "account_id", "package_id", "order_id", "order_status_code", "state_hash_before", "state_hash_after"):
            if int(getattr(self, field)) < MISSING_ID:
                raise ValueError(f"{field} must be >= -1")
        if not isinstance(self.event_kind, CanonicalEventKindV2):
            object.__setattr__(self, "event_kind", CanonicalEventKindV2(int(self.event_kind)))
        for field in _FLOAT_FIELDS:
            value = float(getattr(self, field))
            if math.isinf(value):
                raise ValueError(f"{field} cannot be infinite")

    def canonical_bytes(self, policy: TraceTolerancePolicyV2 | None = None) -> bytes:
        """Encode this row with the V2 little-endian, tolerance-aware schema."""

        policy = policy or default_linear_trace_tolerance_v2()
        payload = bytearray()
        for field in _DISCRETE_FIELDS:
            value = int(getattr(self, field))
            payload.extend(struct.pack("<q", value))
        for field in _FLOAT_FIELDS:
            payload.extend(_encode_float(policy.for_field(field).normalize(float(getattr(self, field)))))
        return bytes(payload)


@dataclass(frozen=True, slots=True)
class CanonicalTraceV2:
    """Ordered V2 rows plus a deterministic backend-neutral hash."""

    rows: tuple[CanonicalTraceRowV2, ...]
    schema_version: str = CANONICAL_TRACE_V2_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != CANONICAL_TRACE_V2_SCHEMA_VERSION:
            raise ValueError(f"unsupported trace schema {self.schema_version!r}")
        previous = -1
        for row in self.rows:
            if row.sequence <= previous:
                raise ValueError("trace sequence must be strictly increasing")
            previous = row.sequence

    @classmethod
    def from_rows(cls, rows: Iterable[CanonicalTraceRowV2]) -> "CanonicalTraceV2":
        return cls(tuple(rows))

    def canonical_bytes(self, policy: TraceTolerancePolicyV2 | None = None) -> bytes:
        policy = policy or default_linear_trace_tolerance_v2()
        payload = bytearray(b"QBT-CANONICAL-TRACE-V2\x00")
        payload.extend(struct.pack("<Q", len(self.rows)))
        for row in self.rows:
            payload.extend(row.canonical_bytes(policy))
        return bytes(payload)

    def fingerprint(self, policy: TraceTolerancePolicyV2 | None = None) -> str:
        return _stable_hash128(self.canonical_bytes(policy))


@dataclass(frozen=True, slots=True)
class TerminalFingerprintV2:
    """Financial terminal identity independent of score/compact/audit retention."""

    final_cash_hash: str
    final_position_hash: str
    final_order_hash: str
    final_margin_hash: str
    final_package_hash: str
    trace_hash: str
    metrics_hash: str
    schema_version: str = TERMINAL_FINGERPRINT_V2_SCHEMA_VERSION

    def to_dict(self) -> dict[str, str]:
        return {
            "schema_version": self.schema_version,
            "final_cash_hash": self.final_cash_hash,
            "final_position_hash": self.final_position_hash,
            "final_order_hash": self.final_order_hash,
            "final_margin_hash": self.final_margin_hash,
            "final_package_hash": self.final_package_hash,
            "trace_hash": self.trace_hash,
            "metrics_hash": self.metrics_hash,
        }


def terminal_fingerprint_v2(
    trace: CanonicalTraceV2 | Sequence[CanonicalTraceRowV2],
    *,
    metrics: Mapping[str, float] | None = None,
    policy: TraceTolerancePolicyV2 | None = None,
) -> TerminalFingerprintV2:
    """Derive a terminal accounting identity from V2 rows and scalar metrics."""

    trace = _as_trace(trace)
    policy = policy or default_linear_trace_tolerance_v2()
    final_cash = math.nan
    final_positions: dict[int, float] = {}
    final_orders: dict[int, int] = {}
    final_margin = (math.nan, math.nan)
    package_rows: list[tuple[int, int, int]] = []
    for row in trace.rows:
        if math.isfinite(row.cash_after):
            final_cash = row.cash_after
        if row.symbol_id != MISSING_ID and math.isfinite(row.position_after):
            final_positions[row.symbol_id] = row.position_after
        if row.order_id != MISSING_ID and row.order_status_code != MISSING_ID:
            final_orders[row.order_id] = row.order_status_code
        if math.isfinite(row.initial_margin_after) or math.isfinite(row.maintenance_margin_after):
            final_margin = (row.initial_margin_after, row.maintenance_margin_after)
        if row.package_id != MISSING_ID:
            package_rows.append((row.package_id, int(row.event_kind), row.reason_code))

    return TerminalFingerprintV2(
        final_cash_hash=_component_hash("cash", _encode_float(policy.financial.normalize(final_cash))),
        final_position_hash=_component_hash(
            "positions",
            b"".join(
                struct.pack("<q", symbol) + _encode_float(policy.quantity.normalize(position))
                for symbol, position in sorted(final_positions.items())
            ),
        ),
        final_order_hash=_component_hash(
            "orders",
            b"".join(struct.pack("<qq", order, status) for order, status in sorted(final_orders.items())),
        ),
        final_margin_hash=_component_hash(
            "margin",
            _encode_float(policy.financial.normalize(final_margin[0]))
            + _encode_float(policy.financial.normalize(final_margin[1])),
        ),
        final_package_hash=_component_hash(
            "packages",
            b"".join(struct.pack("<qqq", *item) for item in sorted(package_rows)),
        ),
        trace_hash=trace.fingerprint(policy),
        metrics_hash=_metrics_hash(metrics or {}, policy),
    )


def compare_canonical_traces_v2(
    left: CanonicalTraceV2 | Sequence[CanonicalTraceRowV2],
    right: CanonicalTraceV2 | Sequence[CanonicalTraceRowV2],
    *,
    policy: TraceTolerancePolicyV2 | None = None,
) -> dict[str, object]:
    """Return the first V2 divergence using field-specific comparison rules."""

    left = _as_trace(left)
    right = _as_trace(right)
    policy = policy or default_linear_trace_tolerance_v2()
    if len(left.rows) != len(right.rows):
        return {"passed": False, "field": "row_count", "left": len(left.rows), "right": len(right.rows)}
    for row_index, (left_row, right_row) in enumerate(zip(left.rows, right.rows, strict=True)):
        for field in _DISCRETE_FIELDS:
            left_value = int(getattr(left_row, field))
            right_value = int(getattr(right_row, field))
            if left_value != right_value:
                return _difference(row_index, left_row, field, left_value, right_value)
        for field in _FLOAT_FIELDS:
            left_value = float(getattr(left_row, field))
            right_value = float(getattr(right_row, field))
            if not policy.for_field(field).equal(left_value, right_value):
                return _difference(row_index, left_row, field, left_value, right_value)
    return {"passed": True, "rows": len(left.rows), "trace_hash": left.fingerprint(policy)}


def adapt_legacy_trace_v1_to_v2(legacy_trace: object) -> CanonicalTraceV2:
    """Project an existing V1 dataframe-like trace into a *lossy* V2 fixture.

    V1 lacks several required V2 fields, especially effective timestamps and
    typed lifecycle IDs. Missing data is represented explicitly with sentinels;
    this adapter must never be presented as a direct runtime V2 emitter.
    """

    rows: list[CanonicalTraceRowV2] = []
    records = legacy_trace.to_dict("records")
    for source in records:
        event_kind = _legacy_event_kind(str(source.get("event_kind", "")))
        timestamp = _int_or_default(source.get("timestamp_ns"), MISSING_ID)
        rows.append(
            CanonicalTraceRowV2(
                sequence=_int_or_default(source.get("sequence"), len(rows)),
                bar_index=_int_or_default(source.get("bar"), MISSING_ID),
                event_timestamp_ns=timestamp,
                effective_timestamp_ns=timestamp,
                event_kind=event_kind,
                symbol_id=_int_or_default(source.get("symbol_code"), MISSING_ID),
                account_id=0,
                package_id=_stable_id(source.get("package_id")),
                order_id=_stable_id(source.get("order_id")),
                reason_code=_stable_id(source.get("reason_code"), empty=0),
                order_status_code=_stable_id(source.get("order_status")),
                qty=_float_or_nan(source.get("qty_delta")),
                price=_float_or_nan(source.get("price")),
                fee=_float_or_nan(source.get("fee")),
                cash_before=math.nan,
                cash_after=_float_or_nan(source.get("equity_after")),
                position_before=_float_or_nan(source.get("position_before")),
                position_after=_float_or_nan(source.get("position_after")),
                realized_pnl_before=math.nan,
                realized_pnl_after=math.nan,
                initial_margin_before=math.nan,
                initial_margin_after=_float_or_nan(source.get("initial_margin_after")),
                maintenance_margin_before=math.nan,
                maintenance_margin_after=_float_or_nan(source.get("maintenance_margin_after")),
                state_hash_before=MISSING_ID,
                state_hash_after=MISSING_ID,
            )
        )
    return CanonicalTraceV2.from_rows(rows)


def _as_trace(value: CanonicalTraceV2 | Sequence[CanonicalTraceRowV2]) -> CanonicalTraceV2:
    return value if isinstance(value, CanonicalTraceV2) else CanonicalTraceV2.from_rows(value)


def _difference(row_index: int, row: CanonicalTraceRowV2, field: str, left: object, right: object) -> dict[str, object]:
    return {
        "passed": False,
        "row_index": row_index,
        "sequence": row.sequence,
        "bar_index": row.bar_index,
        "event_kind": row.event_kind.name,
        "field": field,
        "left": left,
        "right": right,
    }


def _encode_float(value: float) -> bytes:
    if math.isnan(value):
        return b"\x00"
    return b"\x01" + struct.pack("<d", 0.0 if value == 0.0 else value)


def _stable_hash128(payload: bytes) -> str:
    first = _FNV64_OFFSET_A
    second = _FNV64_OFFSET_B
    for byte in payload:
        first = ((first ^ byte) * _FNV64_PRIME) & _U64_MASK
        second = ((second ^ (byte ^ 0xA5)) * _FNV64_PRIME) & _U64_MASK
    return f"{first:016x}{second:016x}"


def _component_hash(name: str, payload: bytes) -> str:
    return _stable_hash128(b"QBT-TERMINAL-V2\x00" + name.encode("ascii") + b"\x00" + payload)


def _metrics_hash(metrics: Mapping[str, float], policy: TraceTolerancePolicyV2) -> str:
    payload = bytearray()
    for name, value in sorted(metrics.items()):
        encoded = str(name).encode("utf-8")
        payload.extend(struct.pack("<Q", len(encoded)))
        payload.extend(encoded)
        payload.extend(_encode_float(policy.metrics.normalize(float(value))))
    return _component_hash("metrics", bytes(payload))


def _legacy_event_kind(value: str) -> CanonicalEventKindV2:
    mapping = {
        "PHASE": CanonicalEventKindV2.MARKET_OBSERVED,
        "LIFECYCLE": CanonicalEventKindV2.COMMAND_SUBMITTED,
        "FILL_ACCOUNTING": CanonicalEventKindV2.FILL_COMMITTED,
        "ACCOUNT_SNAPSHOT": CanonicalEventKindV2.ACCOUNT_SNAPSHOT,
        "LIQUIDATION_ALLOCATION": CanonicalEventKindV2.LIQUIDATION_COMPLETED,
        "PACKAGE_RECONCILIATION": CanonicalEventKindV2.PACKAGE_STATE_CHANGED,
    }
    return mapping.get(value, CanonicalEventKindV2.MARKET_OBSERVED)


def _int_or_default(value: object, default: int) -> int:
    if value is None:
        return default
    try:
        if math.isnan(float(value)):
            return default
    except (TypeError, ValueError):
        return default
    return int(value)


def _float_or_nan(value: object) -> float:
    try:
        candidate = float(value)
    except (TypeError, ValueError):
        return math.nan
    return candidate if math.isfinite(candidate) else math.nan


def _stable_id(value: object, *, empty: int = MISSING_ID) -> int:
    if value is None:
        return empty
    text = str(value).strip()
    if not text or text.lower() == "nan":
        return empty
    payload = text.encode("utf-8")
    value = _stable_hash128(payload)
    return int(value[:15], 16)


__all__ = [
    "CANONICAL_TRACE_V2_HASH",
    "CANONICAL_TRACE_V2_SCHEMA_VERSION",
    "CANONICAL_TRACE_V2_SERIALIZER",
    "CanonicalEventKindV2",
    "CanonicalTraceRowV2",
    "CanonicalTraceV2",
    "MISSING_ID",
    "TERMINAL_FINGERPRINT_V2_SCHEMA_VERSION",
    "TerminalFingerprintV2",
    "TraceFieldToleranceV2",
    "TraceTolerancePolicyV2",
    "adapt_legacy_trace_v1_to_v2",
    "compare_canonical_traces_v2",
    "default_linear_trace_tolerance_v2",
    "terminal_fingerprint_v2",
]
