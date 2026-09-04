"""Independent standard-library oracle for the V1.1 FillReplay V2 contract.

This is deliberately small, explicit and slow.  It owns no production
imports, NumPy, pandas, Numba, or native bindings.  Tests use it to certify
the Rust accounting authority rather than to provide a second runtime engine.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
import struct
import sys
from typing import Sequence


EPSILON = 1e-12
POSITION_ZERO = sys.float_info.epsilon
CANONICAL_FINANCIAL_HASH_QUANTUM = 1e-6
I64_MAX = (1 << 63) - 1
U64_MASK = (1 << 64) - 1
FNV64_PRIME = 0x100000001B3
FNV64_OFFSET_A = 0xCBF29CE484222325
FNV64_OFFSET_B = 0x84222325CBF29CE4


class RejectCode:
    """Numeric values frozen by Rust ``AccountingRejectCodeV1``."""

    ACCEPTED = 0
    INVALID_ACCOUNT_CONFIG = 1
    INVALID_SYMBOL = 2
    INVALID_QUANTITY = 3
    INVALID_PRICE = 4
    INVALID_FEE = 5
    INVALID_MARK = 6
    POST_COST_MARGIN = 7
    TERMINAL_LIQUIDATION = 8
    STALE_PREVIEW = 9
    UNKNOWN_RESERVATION = 10
    RESERVATION_MISMATCH = 11
    DUPLICATE_FUNDING_EVENT = 12
    INVARIANT_VIOLATION = 13


class LiquidationState:
    """Numeric values frozen by Rust ``LiquidationStateV1``."""

    HEALTHY = 0
    BREACHED = 1
    CANCELING_ORDERS = 2
    REDUCING_POSITIONS = 3
    RECHECKING = 4
    LIQUIDATED = 5
    BANKRUPT = 6


class EventKind:
    """Numeric values frozen by Canonical Trace V2."""

    MARKET_OBSERVED = 1
    FUNDING_APPLIED = 2
    COMMAND_REJECTED = 5
    FILL_COMMITTED = 11
    LIQUIDATION_STARTED = 16
    LIQUIDATION_FILL = 17
    LIQUIDATION_COMPLETED = 18
    ACCOUNT_SNAPSHOT = 25


@dataclass(frozen=True, slots=True)
class LinearReplaySpecV2:
    """Immutable linear quote-settled gross-cross replay configuration."""

    initial_cash: float
    maintenance_ratio: float
    contract_sizes: tuple[float, ...]
    leverages: tuple[float, ...]
    liquidation_fee_rate: float = 0.0
    funding_phase: str = "after_fills_at_close"

    def __post_init__(self) -> None:
        if (
            not math.isfinite(self.initial_cash)
            or self.initial_cash < 0.0
            or not math.isfinite(self.maintenance_ratio)
            or self.maintenance_ratio < 0.0
            or not self.contract_sizes
            or len(self.contract_sizes) != len(self.leverages)
            or any(not math.isfinite(value) or value <= 0.0 for value in self.contract_sizes)
            or any(not math.isfinite(value) or value <= 0.0 for value in self.leverages)
            or not math.isfinite(self.liquidation_fee_rate)
            or self.liquidation_fee_rate < 0.0
        ):
            raise ValueError("invalid linear replay V2 configuration")
        if self.funding_phase not in {"before_fills_at_close", "after_fills_at_close"}:
            raise ValueError("unsupported funding_phase")

    @property
    def n_symbols(self) -> int:
        return len(self.contract_sizes)


@dataclass(frozen=True, slots=True)
class ReplayFillV2:
    bar_index: int
    sequence: int
    event_id: int
    symbol: int
    signed_qty: float
    price: float
    fee: float


@dataclass(frozen=True, slots=True)
class ReplayFundingV2:
    bar_index: int
    sequence: int
    event_id: int
    symbol: int
    rate: float


@dataclass(frozen=True, slots=True)
class LinearAccountStateV2:
    cash: float
    realized_pnl: float
    fees_paid: float
    funding_paid: float
    qty: tuple[float, ...]
    average_entry: tuple[float, ...]
    marks: tuple[float, ...]
    signed_fill_totals: tuple[float, ...]
    funding_event_ids: frozenset[int]
    liquidation_state: int = LiquidationState.HEALTHY


@dataclass(frozen=True, slots=True)
class AccountSnapshotV2:
    cash: float
    realized_pnl: float
    fees_paid: float
    funding_paid: float
    qty: tuple[float, ...]
    average_entry: tuple[float, ...]
    marks: tuple[float, ...]
    initial_margin: float
    maintenance_margin: float
    equity: float
    available_equity: float
    liquidation_state: int
    state_hash: int


@dataclass(frozen=True, slots=True)
class OracleTraceRowV2:
    sequence: int
    bar_index: int
    event_timestamp_ns: int
    effective_timestamp_ns: int
    event_kind: int
    symbol_id: int
    reason_code: int
    order_status_code: int
    qty: float
    price: float
    fee: float
    cash_before: float
    cash_after: float
    position_before: float
    position_after: float
    realized_pnl_before: float
    realized_pnl_after: float
    initial_margin_before: float
    initial_margin_after: float
    maintenance_margin_before: float
    maintenance_margin_after: float
    state_hash_before: int
    state_hash_after: int


@dataclass(frozen=True, slots=True)
class ReplayBarSnapshotV2:
    bar_index: int
    account: AccountSnapshotV2


@dataclass(frozen=True, slots=True)
class FillReplayOracleResultV2:
    account: AccountSnapshotV2
    trace: tuple[OracleTraceRowV2, ...]
    snapshots: tuple[ReplayBarSnapshotV2, ...]
    accepted_fill_count: int
    rejected_fill_count: int
    accepted_funding_count: int
    rejected_funding_count: int
    trace_fingerprint: str


def run_fill_replay_v2(
    *,
    timestamps_ns: Sequence[int],
    marks: Sequence[Sequence[float]],
    fills: Sequence[ReplayFillV2],
    funding: Sequence[ReplayFundingV2],
    spec: LinearReplaySpecV2,
) -> FillReplayOracleResultV2:
    """Run the bounded V2 whole-tape contract without production imports."""

    _validate_tape(timestamps_ns, marks, fills, funding, spec)
    state = LinearAccountStateV2(
        cash=float(spec.initial_cash),
        realized_pnl=0.0,
        fees_paid=0.0,
        funding_paid=0.0,
        qty=(0.0,) * spec.n_symbols,
        average_entry=(0.0,) * spec.n_symbols,
        marks=(0.0,) * spec.n_symbols,
        signed_fill_totals=(0.0,) * spec.n_symbols,
        funding_event_ids=frozenset(),
    )
    fills_by_bar = _group_by_bar(fills)
    funding_by_bar = _group_by_bar(funding)
    trace: list[OracleTraceRowV2] = []
    snapshots: list[ReplayBarSnapshotV2] = []
    accepted_fills = rejected_fills = accepted_funding = rejected_funding = 0

    for bar_index, timestamp in enumerate(timestamps_ns):
        before_mark = _snapshot(state, spec)
        state = _observe_marks(state, marks[bar_index], spec)
        after_mark = _snapshot(state, spec)
        _push_trace(
            trace,
            bar_index,
            int(timestamp),
            EventKind.MARKET_OBSERVED,
            -1,
            0.0,
            math.nan,
            0.0,
            before_mark,
            after_mark,
            RejectCode.ACCEPTED,
        )

        if spec.funding_phase == "before_fills_at_close":
            state, accepted, rejected = _process_funding(
                state,
                funding_by_bar.get(bar_index, ()),
                spec,
                trace,
                bar_index,
                int(timestamp),
            )
            accepted_funding += accepted
            rejected_funding += rejected

        state = _process_liquidation(state, spec, trace, bar_index, int(timestamp))

        for row in fills_by_bar.get(bar_index, ()):
            before = _snapshot(state, spec)
            next_state, reason = _preview_and_commit(state, row, spec)
            if reason == RejectCode.ACCEPTED:
                state = next_state
                accepted_fills += 1
                after = _snapshot(state, spec)
                _push_trace(
                    trace,
                    bar_index,
                    int(timestamp),
                    EventKind.FILL_COMMITTED,
                    row.symbol,
                    row.signed_qty,
                    row.price,
                    row.fee,
                    before,
                    after,
                    RejectCode.ACCEPTED,
                )
            else:
                rejected_fills += 1
                _push_trace(
                    trace,
                    bar_index,
                    int(timestamp),
                    EventKind.COMMAND_REJECTED,
                    row.symbol,
                    row.signed_qty,
                    row.price,
                    row.fee,
                    before,
                    before,
                    reason,
                )

        if spec.funding_phase == "after_fills_at_close":
            state, accepted, rejected = _process_funding(
                state,
                funding_by_bar.get(bar_index, ()),
                spec,
                trace,
                bar_index,
                int(timestamp),
            )
            accepted_funding += accepted
            rejected_funding += rejected

        state = _process_liquidation(state, spec, trace, bar_index, int(timestamp))
        snapshot = _snapshot(state, spec)
        _push_trace(
            trace,
            bar_index,
            int(timestamp),
            EventKind.ACCOUNT_SNAPSHOT,
            -1,
            0.0,
            math.nan,
            0.0,
            snapshot,
            snapshot,
            RejectCode.ACCEPTED,
        )
        snapshots.append(ReplayBarSnapshotV2(bar_index, snapshot))

    return FillReplayOracleResultV2(
        account=_snapshot(state, spec),
        trace=tuple(trace),
        snapshots=tuple(snapshots),
        accepted_fill_count=accepted_fills,
        rejected_fill_count=rejected_fills,
        accepted_funding_count=accepted_funding,
        rejected_funding_count=rejected_funding,
        trace_fingerprint=canonical_trace_fingerprint_v2(trace),
    )


def canonical_trace_fingerprint_v2(rows: Sequence[OracleTraceRowV2]) -> str:
    """Implement the shared V2 little-endian/FNV serializer independently."""

    payload = bytearray(b"QBT-CANONICAL-TRACE-V2\0")
    payload.extend(struct.pack("<Q", len(rows)))
    for row in rows:
        for value in (
            row.sequence,
            row.bar_index,
            row.event_timestamp_ns,
            row.effective_timestamp_ns,
            row.symbol_id,
            0,  # account_id
            -1,  # package_id
            -1,  # order_id
            row.event_kind,
            row.reason_code,
            row.order_status_code,
            row.state_hash_before,
            row.state_hash_after,
        ):
            payload.extend(struct.pack("<q", int(value)))
        for field, quantum in (
            (row.qty, 1e-12),
            (row.price, 1e-10),
            (row.fee, 1e-10),
            (row.cash_before, 1e-10),
            (row.cash_after, 1e-10),
            (row.position_before, 1e-12),
            (row.position_after, 1e-12),
            (row.realized_pnl_before, 1e-10),
            (row.realized_pnl_after, 1e-10),
            (row.initial_margin_before, 1e-10),
            (row.initial_margin_after, 1e-10),
            (row.maintenance_margin_before, 1e-10),
            (row.maintenance_margin_after, 1e-10),
        ):
            payload.extend(_canonical_float(field, quantum))
    return _fnv128(bytes(payload))


def _process_funding(
    state: LinearAccountStateV2,
    rows: Sequence[ReplayFundingV2],
    spec: LinearReplaySpecV2,
    trace: list[OracleTraceRowV2],
    bar_index: int,
    timestamp: int,
) -> tuple[LinearAccountStateV2, int, int]:
    accepted = rejected = 0
    for row in rows:
        before = _snapshot(state, spec)
        if row.event_id in state.funding_event_ids:
            rejected += 1
            _push_trace(
                trace,
                bar_index,
                timestamp,
                EventKind.COMMAND_REJECTED,
                row.symbol,
                0.0,
                state.marks[row.symbol],
                0.0,
                before,
                before,
                RejectCode.DUPLICATE_FUNDING_EVENT,
            )
            continue
        charge = state.qty[row.symbol] * state.marks[row.symbol] * spec.contract_sizes[row.symbol] * row.rate
        state = LinearAccountStateV2(
            cash=state.cash - charge,
            realized_pnl=state.realized_pnl,
            fees_paid=state.fees_paid,
            funding_paid=state.funding_paid + charge,
            qty=state.qty,
            average_entry=state.average_entry,
            marks=state.marks,
            signed_fill_totals=state.signed_fill_totals,
            funding_event_ids=state.funding_event_ids | frozenset((row.event_id,)),
            liquidation_state=state.liquidation_state,
        )
        accepted += 1
        after = _snapshot(state, spec)
        _push_trace(
            trace,
            bar_index,
            timestamp,
            EventKind.FUNDING_APPLIED,
            row.symbol,
            0.0,
            before.marks[row.symbol],
            abs(charge),
            before,
            after,
            RejectCode.ACCEPTED,
        )
    return state, accepted, rejected


def _process_liquidation(
    state: LinearAccountStateV2,
    spec: LinearReplaySpecV2,
    trace: list[OracleTraceRowV2],
    bar_index: int,
    timestamp: int,
) -> LinearAccountStateV2:
    margin = _margin(state, spec)
    if state.liquidation_state in {LiquidationState.LIQUIDATED, LiquidationState.BANKRUPT}:
        return state
    if not (margin.maintenance_margin > 0.0 and margin.equity <= margin.maintenance_margin + EPSILON):
        return state
    before = _snapshot(state, spec)
    _push_trace(
        trace,
        bar_index,
        timestamp,
        EventKind.LIQUIDATION_STARTED,
        -1,
        0.0,
        math.nan,
        0.0,
        before,
        before,
        state.liquidation_state,
    )
    state = _with_liquidation_state(state, LiquidationState.REDUCING_POSITIONS)
    for symbol, quantity in enumerate(state.qty):
        if abs(quantity) <= EPSILON:
            continue
        mark = state.marks[symbol]
        fee = abs(quantity) * mark * spec.contract_sizes[symbol] * spec.liquidation_fee_rate
        row = ReplayFillV2(
            bar_index=bar_index,
            sequence=0,
            event_id=(1 << 64) - 1 - symbol,
            symbol=symbol,
            signed_qty=-quantity,
            price=mark,
            fee=fee,
        )
        fill_before = _snapshot(state, spec)
        state = _apply_fill_unchecked(state, row, spec)
        fill_after = _snapshot(state, spec)
        _push_trace(
            trace,
            bar_index,
            timestamp,
            EventKind.LIQUIDATION_FILL,
            symbol,
            row.signed_qty,
            row.price,
            row.fee,
            fill_before,
            fill_after,
            RejectCode.ACCEPTED,
        )
    state = _with_liquidation_state(state, LiquidationState.RECHECKING)
    if all(abs(quantity) <= POSITION_ZERO for quantity in state.qty):
        state = _with_liquidation_state(
            state,
            LiquidationState.BANKRUPT if _margin(state, spec).equity < -EPSILON else LiquidationState.LIQUIDATED,
        )
    after = _snapshot(state, spec)
    _push_trace(
        trace,
        bar_index,
        timestamp,
        EventKind.LIQUIDATION_COMPLETED,
        -1,
        0.0,
        math.nan,
        0.0,
        after,
        after,
        state.liquidation_state,
    )
    return state


def _preview_and_commit(
    state: LinearAccountStateV2,
    row: ReplayFillV2,
    spec: LinearReplaySpecV2,
) -> tuple[LinearAccountStateV2, int]:
    if state.liquidation_state in {LiquidationState.LIQUIDATED, LiquidationState.BANKRUPT}:
        return state, RejectCode.TERMINAL_LIQUIDATION
    projected = _apply_fill_unchecked(state, row, spec)
    margin = _margin(projected, spec)
    if margin.available_equity < -EPSILON or margin.equity + EPSILON < margin.maintenance_margin:
        return state, RejectCode.POST_COST_MARGIN
    return projected, RejectCode.ACCEPTED


def _apply_fill_unchecked(
    state: LinearAccountStateV2,
    row: ReplayFillV2,
    spec: LinearReplaySpecV2,
) -> LinearAccountStateV2:
    symbol = row.symbol
    old_qty = state.qty[symbol]
    old_average = state.average_entry[symbol]
    delta = row.signed_qty
    new_qty = old_qty + delta
    realized = 0.0
    if old_qty == 0.0 or _same_sign(old_qty, delta):
        if old_qty == 0.0:
            new_average = row.price
        else:
            new_average = (abs(old_qty) * old_average + abs(delta) * row.price) / abs(new_qty)
    else:
        closed = min(abs(old_qty), abs(delta))
        realized = closed * (row.price - old_average) * math.copysign(1.0, old_qty) * spec.contract_sizes[symbol]
        opened = max(abs(delta) - closed, 0.0)
        if new_qty == 0.0:
            new_average = 0.0
        elif opened > 0.0:
            new_average = row.price
        else:
            new_average = old_average
    if abs(new_qty) <= POSITION_ZERO:
        new_qty = 0.0
    qty = list(state.qty)
    average_entry = list(state.average_entry)
    signed_fill_totals = list(state.signed_fill_totals)
    qty[symbol] = new_qty
    average_entry[symbol] = new_average
    signed_fill_totals[symbol] += delta
    return LinearAccountStateV2(
        cash=state.cash + realized - row.fee,
        realized_pnl=state.realized_pnl + realized,
        fees_paid=state.fees_paid + row.fee,
        funding_paid=state.funding_paid,
        qty=tuple(qty),
        average_entry=tuple(average_entry),
        marks=state.marks,
        signed_fill_totals=tuple(signed_fill_totals),
        funding_event_ids=state.funding_event_ids,
        liquidation_state=state.liquidation_state,
    )


def _observe_marks(
    state: LinearAccountStateV2,
    marks: Sequence[float],
    spec: LinearReplaySpecV2,
) -> LinearAccountStateV2:
    if len(marks) != spec.n_symbols:
        raise ValueError("mark row does not match symbol count")
    normalized = tuple(float(value) for value in marks)
    if any(not math.isfinite(value) or value <= 0.0 for value in normalized):
        raise ValueError("marks must be finite and > 0")
    return LinearAccountStateV2(
        cash=state.cash,
        realized_pnl=state.realized_pnl,
        fees_paid=state.fees_paid,
        funding_paid=state.funding_paid,
        qty=state.qty,
        average_entry=state.average_entry,
        marks=normalized,
        signed_fill_totals=state.signed_fill_totals,
        funding_event_ids=state.funding_event_ids,
        liquidation_state=state.liquidation_state,
    )


def _with_liquidation_state(state: LinearAccountStateV2, liquidation_state: int) -> LinearAccountStateV2:
    return LinearAccountStateV2(
        cash=state.cash,
        realized_pnl=state.realized_pnl,
        fees_paid=state.fees_paid,
        funding_paid=state.funding_paid,
        qty=state.qty,
        average_entry=state.average_entry,
        marks=state.marks,
        signed_fill_totals=state.signed_fill_totals,
        funding_event_ids=state.funding_event_ids,
        liquidation_state=liquidation_state,
    )


def _snapshot(state: LinearAccountStateV2, spec: LinearReplaySpecV2) -> AccountSnapshotV2:
    margin = _margin(state, spec)
    return AccountSnapshotV2(
        cash=state.cash,
        realized_pnl=state.realized_pnl,
        fees_paid=state.fees_paid,
        funding_paid=state.funding_paid,
        qty=state.qty,
        average_entry=state.average_entry,
        marks=state.marks,
        initial_margin=margin.initial_margin,
        maintenance_margin=margin.maintenance_margin,
        equity=margin.equity,
        available_equity=margin.available_equity,
        liquidation_state=state.liquidation_state,
        state_hash=min(_canonical_state_hash(state, spec), I64_MAX),
    )


@dataclass(frozen=True, slots=True)
class _Margin:
    initial_margin: float
    maintenance_margin: float
    equity: float
    available_equity: float


def _margin(state: LinearAccountStateV2, spec: LinearReplaySpecV2) -> _Margin:
    unrealized = 0.0
    initial_margin = 0.0
    maintenance_margin = 0.0
    for symbol, quantity in enumerate(state.qty):
        mark = state.marks[symbol]
        average = state.average_entry[symbol]
        size = spec.contract_sizes[symbol]
        notional = abs(quantity) * mark * size
        unrealized += quantity * (mark - average) * size
        initial_margin += notional / spec.leverages[symbol]
        maintenance_margin += notional * spec.maintenance_ratio
    equity = state.cash + unrealized
    return _Margin(
        initial_margin=initial_margin,
        maintenance_margin=maintenance_margin,
        equity=equity,
        available_equity=equity - initial_margin,
    )


def _canonical_state_hash(state: LinearAccountStateV2, spec: LinearReplaySpecV2) -> int:
    first = FNV64_OFFSET_A
    second = FNV64_OFFSET_B
    first, second = _hash_bytes(first, second, b"QBT-LINEAR-GROSS-CROSS-CANONICAL-STATE-V1\0")
    margin = _margin(state, spec)
    for value in (
        spec.initial_cash,
        state.cash,
        state.realized_pnl,
        state.fees_paid,
        state.funding_paid,
        margin.initial_margin,
        margin.maintenance_margin,
        0.0,  # reserved_margin: FillReplay owns no reservations.
        margin.equity,
        margin.available_equity,
    ):
        first, second = _hash_bytes(
            first,
            second,
            struct.pack("<d", _normalize_hash_float(value, CANONICAL_FINANCIAL_HASH_QUANTUM)),
        )
    first, second = _hash_bytes(
        first,
        second,
        struct.pack("<d", _normalize_hash_float(spec.maintenance_ratio, 1e-12)),
    )
    first, second = _hash_bytes(first, second, struct.pack("<q", state.liquidation_state))
    for symbol in range(spec.n_symbols):
        for value, quantum in (
            (spec.contract_sizes[symbol], 1e-10),
            (spec.leverages[symbol], 1e-10),
            (state.qty[symbol], 1e-12),
            (state.average_entry[symbol], 1e-10),
            (state.marks[symbol], 1e-10),
            (state.signed_fill_totals[symbol], 1e-12),
        ):
            first, second = _hash_bytes(first, second, struct.pack("<d", _normalize_hash_float(value, quantum)))
    for event_id in sorted(state.funding_event_ids):
        first, second = _hash_bytes(first, second, struct.pack("<Q", event_id))
    return first


def _push_trace(
    trace: list[OracleTraceRowV2],
    bar_index: int,
    timestamp: int,
    event_kind: int,
    symbol: int,
    quantity: float,
    price: float,
    fee: float,
    before: AccountSnapshotV2,
    after: AccountSnapshotV2,
    reason_code: int,
) -> None:
    trace.append(
        OracleTraceRowV2(
            sequence=len(trace),
            bar_index=bar_index,
            event_timestamp_ns=timestamp,
            effective_timestamp_ns=timestamp,
            event_kind=event_kind,
            symbol_id=symbol,
            reason_code=reason_code,
            order_status_code=-1,
            qty=quantity,
            price=price,
            fee=fee,
            cash_before=before.cash,
            cash_after=after.cash,
            position_before=before.qty[symbol] if symbol >= 0 else math.nan,
            position_after=after.qty[symbol] if symbol >= 0 else math.nan,
            realized_pnl_before=before.realized_pnl,
            realized_pnl_after=after.realized_pnl,
            initial_margin_before=before.initial_margin,
            initial_margin_after=after.initial_margin,
            maintenance_margin_before=before.maintenance_margin,
            maintenance_margin_after=after.maintenance_margin,
            state_hash_before=before.state_hash,
            state_hash_after=after.state_hash,
        )
    )


def _validate_tape(
    timestamps_ns: Sequence[int],
    marks: Sequence[Sequence[float]],
    fills: Sequence[ReplayFillV2],
    funding: Sequence[ReplayFundingV2],
    spec: LinearReplaySpecV2,
) -> None:
    if not timestamps_ns or len(timestamps_ns) != len(marks):
        raise ValueError("invalid FillReplay V2 market tape")
    normalized_timestamps = [int(value) for value in timestamps_ns]
    if any(left >= right for left, right in zip(normalized_timestamps, normalized_timestamps[1:])):
        raise ValueError("timestamps must be strictly increasing")
    for row in marks:
        if len(row) != spec.n_symbols or any(not math.isfinite(float(value)) or float(value) <= 0.0 for value in row):
            raise ValueError("invalid FillReplay V2 marks")
    fill_ids: set[int] = set()
    _validate_ordered_rows(fills, len(marks), spec.n_symbols, fill_ids, is_fill=True)
    _validate_ordered_rows(funding, len(marks), spec.n_symbols, set(), is_fill=False)


def _validate_ordered_rows(
    rows: Sequence[ReplayFillV2] | Sequence[ReplayFundingV2],
    n_bars: int,
    n_symbols: int,
    seen_event_ids: set[int],
    *,
    is_fill: bool,
) -> None:
    previous: tuple[int, int] | None = None
    for row in rows:
        if not (0 <= int(row.bar_index) < n_bars and 0 <= int(row.symbol) < n_symbols and int(row.sequence) >= 0):
            raise ValueError("invalid FillReplay V2 row")
        key = (int(row.bar_index), int(row.sequence))
        if previous is not None and key <= previous:
            raise ValueError("FillReplay V2 rows must be strictly sorted by bar_index then sequence")
        previous = key
        if is_fill:
            fill = row
            assert isinstance(fill, ReplayFillV2)
            if (
                not math.isfinite(fill.signed_qty)
                or abs(fill.signed_qty) <= EPSILON
                or not math.isfinite(fill.price)
                or fill.price <= 0.0
                or not math.isfinite(fill.fee)
                or fill.fee < 0.0
                or int(fill.event_id) in seen_event_ids
            ):
                raise ValueError("invalid FillReplay V2 fill row")
            seen_event_ids.add(int(fill.event_id))
        else:
            funding_row = row
            assert isinstance(funding_row, ReplayFundingV2)
            if not math.isfinite(funding_row.rate):
                raise ValueError("invalid FillReplay V2 funding row")


def _group_by_bar(rows: Sequence[ReplayFillV2] | Sequence[ReplayFundingV2]):
    grouped: dict[int, list[object]] = {}
    for row in rows:
        grouped.setdefault(int(row.bar_index), []).append(row)
    return {bar: tuple(items) for bar, items in grouped.items()}


def _same_sign(left: float, right: float) -> bool:
    return (left > 0.0 and right > 0.0) or (left < 0.0 and right < 0.0)


def _canonical_float(value: float, quantum: float) -> bytes:
    if math.isnan(value):
        return b"\x00"
    normalized = math.floor(abs(value) / quantum + 0.5) * quantum
    normalized = math.copysign(normalized, value) if normalized else 0.0
    return b"\x01" + struct.pack("<d", normalized)


def _normalize_hash_float(value: float, quantum: float) -> float:
    normalized = math.floor(abs(value) / quantum + 0.5) * quantum
    return math.copysign(normalized, value) if normalized else 0.0


def _fnv128(payload: bytes) -> str:
    first = FNV64_OFFSET_A
    second = FNV64_OFFSET_B
    for byte in payload:
        first = ((first ^ byte) * FNV64_PRIME) & U64_MASK
        second = ((second ^ (byte ^ 0xA5)) * FNV64_PRIME) & U64_MASK
    return f"{first:016x}{second:016x}"


def _hash_bytes(first: int, second: int, payload: bytes) -> tuple[int, int]:
    for byte in payload:
        first = ((first ^ byte) * FNV64_PRIME) & U64_MASK
        second = ((second ^ byte) * FNV64_PRIME) & U64_MASK
    return first, second


__all__ = [
    "AccountSnapshotV2",
    "EventKind",
    "FillReplayOracleResultV2",
    "LinearReplaySpecV2",
    "LiquidationState",
    "OracleTraceRowV2",
    "RejectCode",
    "ReplayBarSnapshotV2",
    "ReplayFillV2",
    "ReplayFundingV2",
    "canonical_trace_fingerprint_v2",
    "run_fill_replay_v2",
]
