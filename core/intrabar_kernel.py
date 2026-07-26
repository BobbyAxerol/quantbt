"""
Fast Numba kernels for Phase 31 intrabar execution contracts.

The public Python reference oracle remains the readability source of truth.
This module mirrors that state machine with primitive arrays only: no Python
objects are created inside hot loops, and sparse fills are generated only by an
optional deterministic second pass.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional, Sequence

import numpy as np
import pandas as pd
from numba import njit

from .execution_contract import ExecutionContract, IntrabarSameBarPolicy, TakeProfitGapPolicy
from .intrabar_reference import IntrabarFill, IntrabarFillReason, IntrabarIntentTape, IntrabarLevelMode, IntrabarSizingMode, _validate_intrabar_contract_supported
from .market_tape import PreparedMarketTape
from .schema import AccountConfig


LEVEL_ABSOLUTE_PRICE = 1
LEVEL_PRICE_DISTANCE = 2
LEVEL_PERCENT_DISTANCE = 3

SAME_BAR_CONSERVATIVE = 1
SAME_BAR_STOP_FIRST = 2
SAME_BAR_TP_FIRST = 3
SAME_BAR_OHLC_PATH = 4
SAME_BAR_OLHC_PATH = 5
SAME_BAR_REJECT_AMBIGUOUS = 6

TP_LIMIT_CONSERVATIVE = 1
TP_OPEN_PRICE_IMPROVEMENT = 2

FILL_ENTRY = 1
FILL_TECHNICAL_EXIT = 2
FILL_REVERSAL_EXIT = 3
FILL_REVERSAL_ENTRY = 4
FILL_STOP_LOSS = 5
FILL_TAKE_PROFIT = 6
FILL_LIQUIDATION = 7
FILL_FINAL_CLOSE = 8

FLAG_ENTRY_FILLED = 1 << 0
FLAG_EXIT_FILLED = 1 << 1
FLAG_STOP_FILLED = 1 << 2
FLAG_TP_FILLED = 1 << 3
FLAG_TECH_EXIT = 1 << 4
FLAG_REVERSAL = 1 << 5
FLAG_AMBIGUOUS = 1 << 6
FLAG_FUNDING = 1 << 7
FLAG_LIQUIDATION = 1 << 8
FLAG_REJECTED = 1 << 9

SIZING_UNITS = 1
SIZING_FIXED_NOTIONAL = 2
SIZING_PCT_EQUITY = 3
SIZING_RISK_PER_TRADE = 4


@dataclass(frozen=True)
class NativeIntrabarKernelResult:
    equity: pd.Series
    position: pd.Series
    average_entry: pd.Series
    active_stop: pd.Series
    active_take_profit: pd.Series
    fees: pd.Series
    funding: pd.Series
    event_flags: pd.Series
    initial_margin: pd.Series
    maintenance_margin: pd.Series
    fills: tuple[IntrabarFill, ...] = ()
    fills_report: pd.DataFrame = field(default_factory=pd.DataFrame)
    ambiguity_count: int = 0
    rejected_count: int = 0
    fill_count: int = 0
    liquidated: bool = False
    liquidation_bar: int = -1
    report_level: str = "standard"
    metadata: Dict = field(default_factory=dict)


@dataclass(frozen=True)
class FillReplayTape:
    bar_index: np.ndarray
    sequence: np.ndarray
    side: np.ndarray
    qty: np.ndarray
    price: np.ndarray
    fee: np.ndarray
    reason: np.ndarray

    @classmethod
    def from_frame(cls, frame: pd.DataFrame, *, fee_rate: float = 0.0, contract_size: float = 1.0) -> "FillReplayTape":
        required = {"bar_index", "side", "qty", "price"}
        missing = sorted(required - set(frame.columns))
        if missing:
            raise ValueError(f"fill replay frame is missing columns {missing}")
        sequence = frame["sequence"] if "sequence" in frame else pd.Series(np.arange(len(frame)), index=frame.index)
        price = pd.to_numeric(frame["price"], errors="raise").to_numpy(dtype=np.float64)
        qty = pd.to_numeric(frame["qty"], errors="raise").to_numpy(dtype=np.float64)
        if "fee" in frame:
            fee = pd.to_numeric(frame["fee"], errors="raise").to_numpy(dtype=np.float64)
        else:
            fee = np.abs(qty) * price * float(contract_size) * float(fee_rate)
        reason = _reason_series_to_codes(frame["reason"]) if "reason" in frame else np.zeros(len(frame), dtype=np.int16)
        return cls(
            bar_index=np.ascontiguousarray(pd.to_numeric(frame["bar_index"], errors="raise").to_numpy(dtype=np.int64)),
            sequence=np.ascontiguousarray(pd.to_numeric(sequence, errors="raise").to_numpy(dtype=np.int64)),
            side=np.ascontiguousarray(np.sign(pd.to_numeric(frame["side"], errors="raise").to_numpy(dtype=np.float64)).astype(np.int8)),
            qty=np.ascontiguousarray(qty, dtype=np.float64),
            price=np.ascontiguousarray(price, dtype=np.float64),
            fee=np.ascontiguousarray(fee, dtype=np.float64),
            reason=np.ascontiguousarray(reason, dtype=np.int16),
        )


@dataclass(frozen=True)
class NativeFillReplayResult:
    equity: pd.Series
    position: pd.Series
    fees: pd.Series
    event_flags: pd.Series
    fill_count: int
    metadata: Dict = field(default_factory=dict)


def run_intrabar_kernel(
    *,
    tape: PreparedMarketTape,
    intent: IntrabarIntentTape,
    account: AccountConfig,
    contract: Optional[ExecutionContract] = None,
    fee_rate: float = 0.0,
    slippage_rate: float = 0.0,
    contract_size: float = 1.0,
    sizing_mode: IntrabarSizingMode | str = IntrabarSizingMode.UNITS,
    fixed_notional: float = 0.0,
    equity_fraction: float = 0.0,
    risk_fraction: float = 0.0,
    qty_step: float = 0.0,
    min_qty: float = 0.0,
    min_notional: float = 0.0,
    report_level: str = "standard",
) -> NativeIntrabarKernelResult:
    """
    Run the fast single-symbol `intrabar_bracket_v1` Numba kernel.

    `report_level="audit"` triggers the second pass and materializes sparse
    fills. `minimal` and `standard` keep fill accounting as counters/flags only.
    """
    if tape.n_symbols != 1:
        raise NotImplementedError("intrabar fast kernel v1 supports exactly one symbol")
    if len(intent.entry_side) != tape.n_bars:
        raise ValueError("intent length must match market tape length")
    if fee_rate < 0.0 or slippage_rate < 0.0:
        raise ValueError("fee_rate and slippage_rate must be >= 0")
    level = _normalize_report_level(report_level)
    contract = contract or ExecutionContract.intrabar_bracket()
    if contract.engine_id != "intrabar_bracket_v1":
        raise ValueError("run_intrabar_kernel requires intrabar_bracket_v1 contract")
    _validate_intrabar_contract_supported(contract)
    if contract.same_bar_policy is IntrabarSameBarPolicy.REJECT_AMBIGUOUS:
        raise NotImplementedError("fast intrabar kernel v1 does not support REJECT_AMBIGUOUS; use the reference oracle for debug rejection")
    sizing_mode_value = IntrabarSizingMode(sizing_mode)

    arrays = _run_intrabar_pass(
        record_fills=False,
        fill_capacity=1,
        tape=tape,
        intent=intent,
        account=account,
        contract=contract,
        fee_rate=fee_rate,
        slippage_rate=slippage_rate,
        contract_size=contract_size,
        sizing_mode=sizing_mode_value,
        fixed_notional=fixed_notional,
        equity_fraction=equity_fraction,
        risk_fraction=risk_fraction,
        qty_step=qty_step,
        min_qty=min_qty,
        min_notional=min_notional,
    )
    (
        equity,
        position,
        avg_entry,
        active_stop,
        active_tp,
        fees,
        funding,
        flags,
        initial_margin,
        maintenance_margin,
        fill_count,
        ambiguity_count,
        rejected_count,
        liquidated,
        liquidation_bar,
        _fill_bar,
        _fill_seq,
        _fill_side,
        _fill_qty,
        _fill_price,
        _fill_fee,
        _fill_reason,
    ) = arrays

    fills: tuple[IntrabarFill, ...] = ()
    fills_report = pd.DataFrame()
    if level == "audit":
        audit = _run_intrabar_pass(
            record_fills=True,
            fill_capacity=int(fill_count),
            tape=tape,
            intent=intent,
            account=account,
            contract=contract,
            fee_rate=fee_rate,
            slippage_rate=slippage_rate,
            contract_size=contract_size,
            sizing_mode=sizing_mode_value,
            fixed_notional=fixed_notional,
            equity_fraction=equity_fraction,
            risk_fraction=risk_fraction,
            qty_step=qty_step,
            min_qty=min_qty,
            min_notional=min_notional,
        )
        _assert_intrabar_audit_parity(arrays, audit)
        fills = _materialize_intrabar_fills(
            timestamps_ns=tape.timestamps_ns,
            fill_bar=audit[15],
            fill_seq=audit[16],
            fill_side=audit[17],
            fill_qty=audit[18],
            fill_price=audit[19],
            fill_fee=audit[20],
            fill_reason=audit[21],
            fill_count=int(fill_count),
        )
        fills_report = _fills_to_report(fills)

    idx = pd.DatetimeIndex(pd.to_datetime(tape.timestamps_ns, utc=True))
    symbol = tape.symbols[0]
    metadata = {
        "engine": "intrabar_bracket_v1",
        "engine_id": "intrabar_bracket_v1",
        "backend": "native_intrabar",
        "backend_alias": "native_intrabar",
        "kernel_version": "intrabar_numba_v1",
        "execution_contract": contract.to_metadata(),
        "data_signature": tape.signature,
        "validation_certificate": tape.validation_certificate.__dict__.copy(),
        "report_level": level,
        "two_pass_audit": level == "audit",
        "fill_count": int(fill_count),
        "ambiguity_count": int(ambiguity_count),
        "rejected_count": int(rejected_count),
        "liquidated": bool(liquidated),
        "liquidation_bar": int(liquidation_bar),
        "sizing_mode": sizing_mode_value.value,
        "sizing": {
            "fixed_notional": float(fixed_notional),
            "equity_fraction": float(equity_fraction),
            "risk_fraction": float(risk_fraction),
        },
        "quantity_constraints": {
            "qty_step": float(qty_step),
            "min_qty": float(min_qty),
            "min_notional": float(min_notional),
        },
    }
    return NativeIntrabarKernelResult(
        equity=pd.Series(equity, index=idx, name="equity"),
        position=pd.Series(position, index=idx, name=f"Position_{symbol}"),
        average_entry=pd.Series(avg_entry, index=idx, name="average_entry"),
        active_stop=pd.Series(active_stop, index=idx, name="active_stop"),
        active_take_profit=pd.Series(active_tp, index=idx, name="active_take_profit"),
        fees=pd.Series(fees, index=idx, name="fees"),
        funding=pd.Series(funding, index=idx, name="funding"),
        event_flags=pd.Series(flags, index=idx, name="event_flags"),
        initial_margin=pd.Series(initial_margin, index=idx, name="initial_margin"),
        maintenance_margin=pd.Series(maintenance_margin, index=idx, name="maintenance_margin"),
        fills=fills,
        fills_report=fills_report,
        ambiguity_count=int(ambiguity_count),
        rejected_count=int(rejected_count),
        fill_count=int(fill_count),
        liquidated=bool(liquidated),
        liquidation_bar=int(liquidation_bar),
        report_level=level,
        metadata=metadata,
    )


def run_fill_replay_kernel(
    *,
    tape: PreparedMarketTape,
    fill_tape: FillReplayTape,
    account: AccountConfig,
    contract_size: float = 1.0,
) -> NativeFillReplayResult:
    """Replay explicit fills through fast accounting without certifying signal generation."""
    if tape.n_symbols != 1:
        raise NotImplementedError("fill replay v1 supports exactly one symbol")
    _validate_fill_replay_tape(fill_tape, tape.n_bars)
    equity, position, fees, flags = _engine_fill_replay_v1(
        tape.opens[:, 0],
        tape.closes[:, 0],
        fill_tape.bar_index,
        fill_tape.sequence,
        fill_tape.side,
        fill_tape.qty,
        fill_tape.price,
        fill_tape.fee,
        account.initial_capital,
        float(contract_size),
    )
    idx = pd.DatetimeIndex(pd.to_datetime(tape.timestamps_ns, utc=True))
    metadata = {
        "engine": "fill_replay_v1",
        "engine_id": "fill_replay_v1",
        "backend": "native_intrabar",
        "accounting_certified": True,
        "price_accounting_certified": True,
        "fee_accounting_certified": True,
        "funding_certified": False,
        "margin_certified": False,
        "liquidation_certified": False,
        "execution_generation_certified": False,
        "causality_certified": False,
        "data_signature": tape.signature,
        "fill_count": int(len(fill_tape.bar_index)),
    }
    return NativeFillReplayResult(
        equity=pd.Series(equity, index=idx, name="equity"),
        position=pd.Series(position, index=idx, name=f"Position_{tape.symbols[0]}"),
        fees=pd.Series(fees, index=idx, name="fees"),
        event_flags=pd.Series(flags, index=idx, name="event_flags"),
        fill_count=int(len(fill_tape.bar_index)),
        metadata=metadata,
    )


def _run_intrabar_pass(
    *,
    record_fills: bool,
    fill_capacity: int,
    tape,
    intent,
    account,
    contract,
    fee_rate,
    slippage_rate,
    contract_size,
    sizing_mode,
    fixed_notional,
    equity_fraction,
    risk_fraction,
    qty_step,
    min_qty,
    min_notional,
):
    stop_value = _optional_float_array(intent.stop_value, tape.n_bars)
    tp_value = _optional_float_array(intent.take_profit_value, tape.n_bars)
    trailing_value = _optional_float_array(intent.trailing_value, tape.n_bars)
    exit_long = _optional_bool_array(intent.exit_long if intent.exit_long is not None else intent.technical_exit, tape.n_bars)
    exit_short = _optional_bool_array(intent.exit_short if intent.exit_short is not None else intent.technical_exit, tape.n_bars)
    fill_bar = np.zeros(max(1, int(fill_capacity)), dtype=np.int64)
    fill_seq = np.zeros(max(1, int(fill_capacity)), dtype=np.int16)
    fill_side = np.zeros(max(1, int(fill_capacity)), dtype=np.int8)
    fill_qty = np.zeros(max(1, int(fill_capacity)), dtype=np.float64)
    fill_price = np.zeros(max(1, int(fill_capacity)), dtype=np.float64)
    fill_fee = np.zeros(max(1, int(fill_capacity)), dtype=np.float64)
    fill_reason = np.zeros(max(1, int(fill_capacity)), dtype=np.int16)
    return _engine_intrabar_bracket_v1(
        tape.opens[:, 0],
        tape.highs[:, 0],
        tape.lows[:, 0],
        tape.closes[:, 0],
        np.ascontiguousarray(intent.entry_side, dtype=np.int8),
        np.ascontiguousarray(intent.entry_size, dtype=np.float64),
        stop_value,
        tp_value,
        trailing_value,
        exit_long,
        exit_short,
        tape.funding_rates[:, 0],
        tape.funding_event_mask,
        float(account.initial_capital),
        float(account.leverage),
        float(account.maintenance_ratio),
        float(account.margin_buffer),
        float(contract_size),
        float(fee_rate),
        float(slippage_rate),
        _sizing_mode_code(sizing_mode),
        float(fixed_notional),
        float(equity_fraction),
        float(risk_fraction),
        float(qty_step),
        float(min_qty),
        float(min_notional),
        _level_mode_code(intent.level_mode),
        _same_bar_policy_code(contract.same_bar_policy),
        _tp_policy_code(contract.take_profit_gap_policy),
        bool(contract.close_on_last_bar),
        bool(record_fills),
        fill_bar,
        fill_seq,
        fill_side,
        fill_qty,
        fill_price,
        fill_fee,
        fill_reason,
    )


@njit(cache=True, nogil=True)
def _engine_intrabar_bracket_v1(
    opens,
    highs,
    lows,
    closes,
    entry_side,
    entry_size,
    stop_value,
    tp_value,
    trailing_value,
    exit_long,
    exit_short,
    funding_rates,
    funding_mask,
    initial_capital,
    leverage,
    maintenance_ratio,
    margin_buffer,
    contract_size,
    fee_rate,
    slippage_rate,
    sizing_mode,
    fixed_notional,
    equity_fraction,
    risk_fraction,
    qty_step,
    min_qty,
    min_notional,
    level_mode,
    same_bar_policy,
    tp_gap_policy,
    close_on_last_bar,
    record_fills,
    fill_bar,
    fill_seq,
    fill_side,
    fill_qty,
    fill_price,
    fill_fee,
    fill_reason,
):
    n = closes.shape[0]
    equity_arr = np.zeros(n, dtype=np.float64)
    pos_arr = np.zeros(n, dtype=np.float64)
    avg_arr = np.zeros(n, dtype=np.float64)
    stop_arr = np.zeros(n, dtype=np.float64)
    tp_arr = np.zeros(n, dtype=np.float64)
    fee_arr = np.zeros(n, dtype=np.float64)
    funding_arr = np.zeros(n, dtype=np.float64)
    flags_arr = np.zeros(n, dtype=np.uint16)
    init_margin = np.zeros(n, dtype=np.float64)
    maint_margin = np.zeros(n, dtype=np.float64)

    equity = initial_capital
    position = 0.0
    avg_entry = 0.0
    active_stop = np.nan
    active_tp = np.nan
    fill_count = 0
    ambiguity_count = 0
    rejected_count = 0
    liquidated = False
    liquidation_bar = -1

    equity_arr[0] = equity
    for t in range(1, n):
        if liquidated:
            equity_arr[t] = 0.0
            continue

        seq = 0
        open_ref = opens[t]
        close_ref = closes[t]
        last_ref = open_ref

        if position != 0.0:
            equity += position * (open_ref - closes[t - 1]) * contract_size

        if position != 0.0 and _maintenance_breached_numba(equity, position, open_ref, contract_size, maintenance_ratio):
            side = -1 if position > 0.0 else 1
            price = _market_price_numba(open_ref, side, slippage_rate)
            qty = abs(position)
            fee = qty * price * contract_size * fee_rate
            equity += position * (price - open_ref) * contract_size - fee
            fee_arr[t] += fee
            fill_count = _record_fill_numba(record_fills, fill_count, t, seq, side, qty, price, fee, FILL_LIQUIDATION, fill_bar, fill_seq, fill_side, fill_qty, fill_price, fill_fee, fill_reason)
            flags_arr[t] |= FLAG_EXIT_FILLED | FLAG_LIQUIDATION
            liquidated = True
            liquidation_bar = t
            equity = 0.0
            equity_arr[t] = 0.0
            continue

        pending_side = entry_side[t - 1]
        pending_size = entry_size[t - 1]
        pending_exit = (position > 0.0 and exit_long[t - 1]) or (position < 0.0 and exit_short[t - 1])
        exit_same_side_conflict = pending_exit and pending_side != 0 and position != 0.0 and _sign_numba(position) == pending_side

        if position != 0.0 and (pending_exit or (pending_side != 0 and _sign_numba(position) != pending_side)):
            reason = FILL_REVERSAL_EXIT if pending_side != 0 and _sign_numba(position) != pending_side else FILL_TECHNICAL_EXIT
            side = -1 if position > 0.0 else 1
            price = _market_price_numba(open_ref, side, slippage_rate)
            qty = abs(position)
            fee = qty * price * contract_size * fee_rate
            equity += position * (price - open_ref) * contract_size - fee
            fee_arr[t] += fee
            fill_count = _record_fill_numba(record_fills, fill_count, t, seq, side, qty, price, fee, reason, fill_bar, fill_seq, fill_side, fill_qty, fill_price, fill_fee, fill_reason)
            seq += 1
            flags_arr[t] |= FLAG_EXIT_FILLED
            if reason == FILL_TECHNICAL_EXIT:
                flags_arr[t] |= FLAG_TECH_EXIT
            else:
                flags_arr[t] |= FLAG_REVERSAL
            position = 0.0
            avg_entry = 0.0
            active_stop = np.nan
            active_tp = np.nan

        if pending_side != 0 and pending_size > 0.0 and position == 0.0:
            side = 1 if pending_side > 0 else -1
            price = _market_price_numba(open_ref, side, slippage_rate)
            if exit_same_side_conflict:
                qty = 0.0
            else:
                qty = _compile_entry_quantity_numba(
                    pending_size,
                    price,
                    equity,
                    contract_size,
                    sizing_mode,
                    fixed_notional,
                    equity_fraction,
                    risk_fraction,
                    stop_value[t - 1],
                    level_mode,
                    side,
                )
                qty = abs(_quantize_signed_quantity_numba(qty, price, contract_size, qty_step, min_qty, min_notional))
            if qty <= 0.0:
                flags_arr[t] |= FLAG_REJECTED
                rejected_count += 1
                equity_arr[t] = equity
                pos_arr[t] = position
                avg_arr[t] = avg_entry
                stop_arr[t] = 0.0 if not np.isfinite(active_stop) else active_stop
                tp_arr[t] = 0.0 if not np.isfinite(active_tp) else active_tp
                continue
            if not _has_initial_margin_numba(equity, qty, price, contract_size, leverage, margin_buffer):
                flags_arr[t] |= FLAG_REJECTED
                rejected_count += 1
                equity_arr[t] = equity
                pos_arr[t] = position
                avg_arr[t] = avg_entry
                stop_arr[t] = 0.0 if not np.isfinite(active_stop) else active_stop
                tp_arr[t] = 0.0 if not np.isfinite(active_tp) else active_tp
                continue
            fee = qty * price * contract_size * fee_rate
            equity -= fee
            fee_arr[t] += fee
            position = qty * side
            avg_entry = price
            last_ref = price
            active_stop, active_tp = _initial_bracket_numba(stop_value[t - 1], tp_value[t - 1], trailing_value[t - 1], side, price, level_mode)
            reason = FILL_REVERSAL_ENTRY if (flags_arr[t] & FLAG_REVERSAL) != 0 else FILL_ENTRY
            fill_count = _record_fill_numba(record_fills, fill_count, t, seq, side, qty, price, fee, reason, fill_bar, fill_seq, fill_side, fill_qty, fill_price, fill_fee, fill_reason)
            seq += 1
            flags_arr[t] |= FLAG_ENTRY_FILLED

        if position != 0.0:
            exit_side, exit_price, exit_reason, ambiguous = _resolve_intrabar_exit_numba(
                1 if position > 0.0 else -1,
                open_ref,
                highs[t],
                lows[t],
                active_stop,
                active_tp,
                same_bar_policy,
                tp_gap_policy,
                slippage_rate,
            )
            if exit_reason != 0:
                if ambiguous:
                    flags_arr[t] |= FLAG_AMBIGUOUS
                    ambiguity_count += 1
                qty = abs(position)
                fee = qty * exit_price * contract_size * fee_rate
                equity += position * (exit_price - last_ref) * contract_size - fee
                fee_arr[t] += fee
                fill_count = _record_fill_numba(record_fills, fill_count, t, seq, exit_side, qty, exit_price, fee, exit_reason, fill_bar, fill_seq, fill_side, fill_qty, fill_price, fill_fee, fill_reason)
                seq += 1
                flags_arr[t] |= FLAG_EXIT_FILLED
                if exit_reason == FILL_STOP_LOSS:
                    flags_arr[t] |= FLAG_STOP_FILLED
                else:
                    flags_arr[t] |= FLAG_TP_FILLED
                position = 0.0
                avg_entry = 0.0
                active_stop = np.nan
                active_tp = np.nan

        if position != 0.0:
            if _maintenance_breached_worst_numba(equity, position, last_ref, highs[t], lows[t], contract_size, maintenance_ratio):
                side = -1 if position > 0.0 else 1
                worst = lows[t] if position > 0.0 else highs[t]
                price = _market_price_numba(worst, side, slippage_rate)
                qty = abs(position)
                fee = qty * price * contract_size * fee_rate
                equity += position * (price - last_ref) * contract_size - fee
                fee_arr[t] += fee
                fill_count = _record_fill_numba(record_fills, fill_count, t, seq, side, qty, price, fee, FILL_LIQUIDATION, fill_bar, fill_seq, fill_side, fill_qty, fill_price, fill_fee, fill_reason)
                flags_arr[t] |= FLAG_EXIT_FILLED | FLAG_LIQUIDATION
                liquidated = True
                liquidation_bar = t
                equity = 0.0
                position = 0.0
                avg_entry = 0.0
                active_stop = np.nan
                active_tp = np.nan
            else:
                equity += position * (close_ref - last_ref) * contract_size
                active_stop = _update_trailing_numba(trailing_value[t], position, close_ref, active_stop, level_mode)

        if liquidated:
            equity_arr[t] = 0.0
            pos_arr[t] = 0.0
            avg_arr[t] = 0.0
            stop_arr[t] = 0.0
            tp_arr[t] = 0.0
            continue

        if position != 0.0 and funding_mask[t]:
            funding_cost = position * close_ref * contract_size * funding_rates[t]
            equity -= funding_cost
            funding_arr[t] = funding_cost
            flags_arr[t] |= FLAG_FUNDING

        equity_arr[t] = equity
        pos_arr[t] = position
        avg_arr[t] = avg_entry
        stop_arr[t] = 0.0 if not np.isfinite(active_stop) else active_stop
        tp_arr[t] = 0.0 if not np.isfinite(active_tp) else active_tp
        init_margin[t] = abs(position) * close_ref * contract_size / leverage
        maint_margin[t] = abs(position) * close_ref * contract_size * maintenance_ratio

    if close_on_last_bar and position != 0.0 and not liquidated:
        t = n - 1
        side = -1 if position > 0.0 else 1
        price = _market_price_numba(closes[t], side, slippage_rate)
        qty = abs(position)
        fee = qty * price * contract_size * fee_rate
        equity += position * (price - closes[t]) * contract_size - fee
        fee_arr[t] += fee
        fill_count = _record_fill_numba(record_fills, fill_count, t, 99, side, qty, price, fee, FILL_FINAL_CLOSE, fill_bar, fill_seq, fill_side, fill_qty, fill_price, fill_fee, fill_reason)
        position = 0.0
        equity_arr[t] = equity
        pos_arr[t] = 0.0
        avg_arr[t] = 0.0
        stop_arr[t] = 0.0
        tp_arr[t] = 0.0
        init_margin[t] = 0.0
        maint_margin[t] = 0.0

    return (
        equity_arr,
        pos_arr,
        avg_arr,
        stop_arr,
        tp_arr,
        fee_arr,
        funding_arr,
        flags_arr,
        init_margin,
        maint_margin,
        fill_count,
        ambiguity_count,
        rejected_count,
        liquidated,
        liquidation_bar,
        fill_bar,
        fill_seq,
        fill_side,
        fill_qty,
        fill_price,
        fill_fee,
        fill_reason,
    )


@njit(cache=True, nogil=True)
def _engine_fill_replay_v1(opens, closes, fill_bar, fill_seq, fill_side, fill_qty, fill_price, fill_fee, initial_capital, contract_size):
    n = closes.shape[0]
    equity_arr = np.zeros(n, dtype=np.float64)
    pos_arr = np.zeros(n, dtype=np.float64)
    fee_arr = np.zeros(n, dtype=np.float64)
    flags_arr = np.zeros(n, dtype=np.uint16)
    equity = initial_capital
    position = 0.0
    ptr = 0
    n_fills = fill_bar.shape[0]
    prev_close = opens[0]
    for t in range(n):
        current_ref = opens[t]
        if t > 0 and position != 0.0:
            equity += position * (opens[t] - prev_close) * contract_size
        while ptr < n_fills and fill_bar[ptr] == t:
            price = fill_price[ptr]
            side = fill_side[ptr]
            qty = fill_qty[ptr]
            fee = fill_fee[ptr]
            if position != 0.0:
                equity += position * (price - current_ref) * contract_size
            equity -= fee
            fee_arr[t] += fee
            position += side * qty
            current_ref = price
            flags_arr[t] |= FLAG_ENTRY_FILLED if side > 0 else FLAG_EXIT_FILLED
            ptr += 1
        if position != 0.0:
            equity += position * (closes[t] - current_ref) * contract_size
        equity_arr[t] = equity
        pos_arr[t] = position
        prev_close = closes[t]
    return equity_arr, pos_arr, fee_arr, flags_arr


@njit(cache=True, nogil=True)
def _market_price_numba(price, side, slippage_rate):
    return price * (1.0 + slippage_rate if side > 0 else 1.0 - slippage_rate)


@njit(cache=True, nogil=True)
def _sign_numba(value):
    if value > 0.0:
        return 1
    if value < 0.0:
        return -1
    return 0


@njit(cache=True, nogil=True)
def _has_initial_margin_numba(equity, qty, price, contract_size, leverage, margin_buffer):
    required = abs(qty) * price * contract_size / leverage
    return equity >= required * (1.0 + margin_buffer)


@njit(cache=True, nogil=True)
def _maintenance_breached_numba(equity, position, price, contract_size, maintenance_ratio):
    maintenance = abs(position) * price * contract_size * maintenance_ratio
    return maintenance > 0.0 and equity <= maintenance


@njit(cache=True, nogil=True)
def _maintenance_breached_worst_numba(equity, position, reference_price, high, low, contract_size, maintenance_ratio):
    worst = low if position > 0.0 else high
    worst_equity = equity + position * (worst - reference_price) * contract_size
    maintenance = abs(position) * worst * contract_size * maintenance_ratio
    return maintenance > 0.0 and worst_equity <= maintenance


@njit(cache=True, nogil=True)
def _initial_bracket_numba(stop_value, tp_value, trailing_value, side, fill_price, level_mode):
    stop = np.nan
    tp = np.nan
    if np.isfinite(stop_value) and stop_value > 0.0:
        stop = _level_price_numba(fill_price, side, stop_value, level_mode, True)
    if np.isfinite(tp_value) and tp_value > 0.0:
        tp = _level_price_numba(fill_price, side, tp_value, level_mode, False)
    if np.isfinite(trailing_value) and trailing_value > 0.0:
        trailing_stop = _level_price_numba(fill_price, side, trailing_value, level_mode, True)
        if not np.isfinite(stop):
            stop = trailing_stop
        elif side > 0:
            stop = max(stop, trailing_stop)
        else:
            stop = min(stop, trailing_stop)
    return stop, tp


@njit(cache=True, nogil=True)
def _level_price_numba(price, side, value, level_mode, is_stop):
    direction = -1.0 if (side > 0 and is_stop) or (side < 0 and not is_stop) else 1.0
    if level_mode == LEVEL_ABSOLUTE_PRICE:
        return value
    if level_mode == LEVEL_PRICE_DISTANCE:
        return price + direction * value
    return price * (1.0 + direction * value)


@njit(cache=True, nogil=True)
def _resolve_intrabar_exit_numba(side, open_price, high, low, stop_price, tp_price, same_bar_policy, tp_gap_policy, slippage_rate):
    has_stop = np.isfinite(stop_price) and stop_price > 0.0
    has_tp = np.isfinite(tp_price) and tp_price > 0.0
    if side > 0:
        stop_hit = has_stop and low <= stop_price
        tp_hit = has_tp and high >= tp_price
        stop_gap = has_stop and open_price <= stop_price
        tp_gap = has_tp and open_price >= tp_price
        exit_side = -1
    else:
        stop_hit = has_stop and high >= stop_price
        tp_hit = has_tp and low <= tp_price
        stop_gap = has_stop and open_price >= stop_price
        tp_gap = has_tp and open_price <= tp_price
        exit_side = 1
    if not stop_hit and not tp_hit:
        return 0, 0.0, 0, False
    ambiguous = stop_hit and tp_hit
    if ambiguous and same_bar_policy == SAME_BAR_REJECT_AMBIGUOUS:
        return 0, 0.0, -1, True
    stop_first = (
        same_bar_policy == SAME_BAR_CONSERVATIVE
        or same_bar_policy == SAME_BAR_STOP_FIRST
        or (side > 0 and same_bar_policy == SAME_BAR_OLHC_PATH)
        or (side < 0 and same_bar_policy == SAME_BAR_OHLC_PATH)
    )
    if stop_hit and ((not tp_hit) or stop_first):
        price = open_price if stop_gap else stop_price
        return exit_side, _market_price_numba(price, exit_side, slippage_rate), FILL_STOP_LOSS, ambiguous
    if tp_hit:
        price = open_price if tp_gap and tp_gap_policy == TP_OPEN_PRICE_IMPROVEMENT else tp_price
        return exit_side, price, FILL_TAKE_PROFIT, ambiguous
    return 0, 0.0, 0, False


@njit(cache=True, nogil=True)
def _update_trailing_numba(trailing_value, position, close_price, current_stop, level_mode):
    if not np.isfinite(trailing_value) or trailing_value <= 0.0:
        return current_stop
    side = 1 if position > 0.0 else -1
    candidate = _level_price_numba(close_price, side, trailing_value, level_mode, True)
    if not np.isfinite(current_stop):
        return candidate
    return max(current_stop, candidate) if side > 0 else min(current_stop, candidate)


@njit(cache=True, nogil=True)
def _compile_entry_quantity_numba(size_weight, fill_price, equity, contract_size, sizing_mode, fixed_notional, equity_fraction, risk_fraction, stop_value, level_mode, side):
    weight = abs(size_weight)
    if sizing_mode == SIZING_UNITS:
        return weight
    if fill_price <= 0.0 or contract_size <= 0.0:
        return 0.0
    if sizing_mode == SIZING_FIXED_NOTIONAL:
        return fixed_notional * weight / (fill_price * contract_size)
    if sizing_mode == SIZING_PCT_EQUITY:
        return equity * equity_fraction * weight / (fill_price * contract_size)
    if sizing_mode == SIZING_RISK_PER_TRADE:
        if not np.isfinite(stop_value) or stop_value <= 0.0:
            return 0.0
        stop_price = _level_price_numba(fill_price, side, stop_value, level_mode, True)
        stop_distance = abs(fill_price - stop_price)
        if stop_distance <= 0.0:
            return 0.0
        return equity * risk_fraction * weight / (stop_distance * contract_size)
    return 0.0


@njit(cache=True, nogil=True)
def _quantize_signed_quantity_numba(qty, price, contract_size, qty_step, min_qty, min_notional):
    if qty == 0.0:
        return 0.0
    sign = 1.0 if qty > 0.0 else -1.0
    abs_q = abs(qty)
    if qty_step > 0.0:
        abs_q = np.floor((abs_q / qty_step) + 1e-12) * qty_step
    if abs_q <= 0.0:
        return 0.0
    if min_qty > 0.0 and abs_q + 1e-12 < min_qty:
        return 0.0
    if min_notional > 0.0 and abs_q * price * contract_size + 1e-12 < min_notional:
        return 0.0
    return sign * abs_q


@njit(cache=True, nogil=True)
def _record_fill_numba(record, count, bar, seq, side, qty, price, fee, reason, fill_bar, fill_seq, fill_side, fill_qty, fill_price, fill_fee, fill_reason):
    if record and count < fill_bar.shape[0]:
        fill_bar[count] = bar
        fill_seq[count] = seq
        fill_side[count] = side
        fill_qty[count] = qty
        fill_price[count] = price
        fill_fee[count] = fee
        fill_reason[count] = reason
    return count + 1


def _optional_float_array(value, n: int) -> np.ndarray:
    if value is None:
        return np.full(n, np.nan, dtype=np.float64)
    return np.ascontiguousarray(value, dtype=np.float64)


def _optional_bool_array(value, n: int) -> np.ndarray:
    if value is None:
        return np.zeros(n, dtype=np.bool_)
    return np.ascontiguousarray(value, dtype=np.bool_)


def _level_mode_code(mode) -> int:
    value = mode.value if hasattr(mode, "value") else str(mode)
    if value == IntrabarLevelMode.ABSOLUTE_PRICE.value:
        return LEVEL_ABSOLUTE_PRICE
    if value == IntrabarLevelMode.PRICE_DISTANCE.value:
        return LEVEL_PRICE_DISTANCE
    if value == IntrabarLevelMode.PERCENT_DISTANCE.value:
        return LEVEL_PERCENT_DISTANCE
    raise NotImplementedError(f"unsupported intrabar level mode={mode!r}")


def _sizing_mode_code(mode) -> int:
    value = mode.value if hasattr(mode, "value") else str(mode)
    mapping = {
        IntrabarSizingMode.UNITS.value: SIZING_UNITS,
        IntrabarSizingMode.FIXED_NOTIONAL.value: SIZING_FIXED_NOTIONAL,
        IntrabarSizingMode.PCT_EQUITY.value: SIZING_PCT_EQUITY,
        IntrabarSizingMode.RISK_PER_TRADE.value: SIZING_RISK_PER_TRADE,
    }
    if value not in mapping:
        raise NotImplementedError(f"unsupported intrabar sizing_mode={mode!r}")
    return mapping[value]


def _same_bar_policy_code(policy) -> int:
    value = policy.value if hasattr(policy, "value") else str(policy)
    mapping = {
        IntrabarSameBarPolicy.CONSERVATIVE.value: SAME_BAR_CONSERVATIVE,
        IntrabarSameBarPolicy.STOP_FIRST.value: SAME_BAR_STOP_FIRST,
        IntrabarSameBarPolicy.TP_FIRST.value: SAME_BAR_TP_FIRST,
        IntrabarSameBarPolicy.OHLC_PATH.value: SAME_BAR_OHLC_PATH,
        IntrabarSameBarPolicy.OLHC_PATH.value: SAME_BAR_OLHC_PATH,
        IntrabarSameBarPolicy.REJECT_AMBIGUOUS.value: SAME_BAR_REJECT_AMBIGUOUS,
    }
    if value not in mapping:
        raise NotImplementedError(f"unsupported same-bar policy={policy!r}")
    return mapping[value]


def _tp_policy_code(policy) -> int:
    value = policy.value if hasattr(policy, "value") else str(policy)
    if value == TakeProfitGapPolicy.LIMIT_PRICE_CONSERVATIVE.value:
        return TP_LIMIT_CONSERVATIVE
    if value == TakeProfitGapPolicy.OPEN_PRICE_IMPROVEMENT.value:
        return TP_OPEN_PRICE_IMPROVEMENT
    raise NotImplementedError(f"unsupported take-profit gap policy={policy!r}")


def _normalize_report_level(report_level: str) -> str:
    level = str(report_level or "standard").lower().strip()
    aliases = {"full": "audit", "debug": "audit", "optimizer": "minimal", "scoring": "minimal"}
    level = aliases.get(level, level)
    if level not in {"minimal", "standard", "audit"}:
        raise ValueError("report_level must be minimal, standard, or audit")
    return level


def _assert_intrabar_audit_parity(first, second, atol: float = 1e-9) -> None:
    for i, name in enumerate(("equity", "position", "average_entry", "active_stop", "active_take_profit", "fees", "funding", "flags")):
        if not np.allclose(first[i], second[i], atol=atol, rtol=0.0):
            raise AssertionError(f"intrabar audit replay drifted from pass 1 for {name}")
    for i, name in ((10, "fill_count"), (11, "ambiguity_count"), (12, "rejected_count"), (13, "liquidated"), (14, "liquidation_bar")):
        if first[i] != second[i]:
            raise AssertionError(f"intrabar audit replay drifted from pass 1 for {name}")


def _materialize_intrabar_fills(
    *,
    timestamps_ns: np.ndarray,
    fill_bar: np.ndarray,
    fill_seq: np.ndarray,
    fill_side: np.ndarray,
    fill_qty: np.ndarray,
    fill_price: np.ndarray,
    fill_fee: np.ndarray,
    fill_reason: np.ndarray,
    fill_count: int,
) -> tuple[IntrabarFill, ...]:
    idx = pd.DatetimeIndex(pd.to_datetime(timestamps_ns, utc=True))
    out = []
    for i in range(fill_count):
        bar = int(fill_bar[i])
        out.append(
            IntrabarFill(
                bar_index=bar,
                sequence=int(fill_seq[i]),
                timestamp=pd.Timestamp(idx[bar]),
                side=int(fill_side[i]),
                qty=float(fill_qty[i]),
                price=float(fill_price[i]),
                fee=float(fill_fee[i]),
                reason=_reason_code_to_enum(int(fill_reason[i])),
            )
        )
    return tuple(out)


def _fills_to_report(fills: Sequence[IntrabarFill]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "bar_index": fill.bar_index,
                "sequence": fill.sequence,
                "timestamp": fill.timestamp,
                "side": fill.side,
                "qty": fill.qty,
                "price": fill.price,
                "fee": fill.fee,
                "reason": fill.reason.value,
            }
            for fill in fills
        ]
    )


def _reason_code_to_enum(code: int) -> IntrabarFillReason:
    mapping = {
        FILL_ENTRY: IntrabarFillReason.ENTRY,
        FILL_TECHNICAL_EXIT: IntrabarFillReason.TECHNICAL_EXIT,
        FILL_REVERSAL_EXIT: IntrabarFillReason.REVERSAL_EXIT,
        FILL_REVERSAL_ENTRY: IntrabarFillReason.REVERSAL_ENTRY,
        FILL_STOP_LOSS: IntrabarFillReason.STOP_LOSS,
        FILL_TAKE_PROFIT: IntrabarFillReason.TAKE_PROFIT,
        FILL_LIQUIDATION: IntrabarFillReason.LIQUIDATION,
        FILL_FINAL_CLOSE: IntrabarFillReason.FINAL_CLOSE,
    }
    return mapping.get(code, IntrabarFillReason.ENTRY)


def _reason_series_to_codes(series: pd.Series) -> np.ndarray:
    out = np.zeros(len(series), dtype=np.int16)
    mapping = {reason.value: code for code, reason in (
        (FILL_ENTRY, IntrabarFillReason.ENTRY),
        (FILL_TECHNICAL_EXIT, IntrabarFillReason.TECHNICAL_EXIT),
        (FILL_REVERSAL_EXIT, IntrabarFillReason.REVERSAL_EXIT),
        (FILL_REVERSAL_ENTRY, IntrabarFillReason.REVERSAL_ENTRY),
        (FILL_STOP_LOSS, IntrabarFillReason.STOP_LOSS),
        (FILL_TAKE_PROFIT, IntrabarFillReason.TAKE_PROFIT),
        (FILL_LIQUIDATION, IntrabarFillReason.LIQUIDATION),
        (FILL_FINAL_CLOSE, IntrabarFillReason.FINAL_CLOSE),
    )}
    for i, value in enumerate(series.astype(str)):
        out[i] = mapping.get(value, 0)
    return out


def _validate_fill_replay_tape(fill_tape: FillReplayTape, n_bars: int) -> None:
    if not (len(fill_tape.bar_index) == len(fill_tape.sequence) == len(fill_tape.side) == len(fill_tape.qty) == len(fill_tape.price) == len(fill_tape.fee)):
        raise ValueError("fill replay arrays must have matching lengths")
    if len(fill_tape.bar_index) == 0:
        return
    if np.any(fill_tape.bar_index < 0) or np.any(fill_tape.bar_index >= n_bars):
        raise ValueError("fill replay bar_index is out of market tape range")
    if not np.isfinite(fill_tape.qty).all() or not np.isfinite(fill_tape.price).all() or not np.isfinite(fill_tape.fee).all():
        raise ValueError("fill replay qty/price/fee must be finite")
    if np.any(fill_tape.qty <= 0.0) or np.any(fill_tape.price <= 0.0) or np.any(fill_tape.fee < 0.0):
        raise ValueError("fill replay qty/price must be positive and fee non-negative")
    prev_bar = int(fill_tape.bar_index[0])
    prev_seq = int(fill_tape.sequence[0])
    for bar, seq in zip(fill_tape.bar_index[1:], fill_tape.sequence[1:]):
        bar_i = int(bar)
        seq_i = int(seq)
        if bar_i < prev_bar or (bar_i == prev_bar and seq_i < prev_seq):
            raise ValueError("fill replay tape must be sorted by bar_index then sequence")
        prev_bar = bar_i
        prev_seq = seq_i
