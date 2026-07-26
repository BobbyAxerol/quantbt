"""
Readable Python oracle for the Phase 31 intrabar execution contract.

This is not a performance engine. It is the reference state machine used to
prove the later Numba kernel. Strategy output is intentionally compact:
entry side/size plus optional stop, take-profit, trailing distance, and
technical-exit arrays.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, IntFlag
from typing import Dict, Optional, Sequence

import numpy as np
import pandas as pd

from .execution_contract import ExecutionContract, IntrabarSameBarPolicy, TakeProfitGapPolicy
from .market_tape import PreparedMarketTape
from .schema import AccountConfig


class IntrabarLevelMode(str, Enum):
    ABSOLUTE_PRICE = "absolute_price"
    PRICE_DISTANCE = "price_distance"
    PERCENT_DISTANCE = "percent_distance"


class IntrabarFillReason(str, Enum):
    ENTRY = "entry"
    TECHNICAL_EXIT = "technical_exit"
    REVERSAL_EXIT = "reversal_exit"
    REVERSAL_ENTRY = "reversal_entry"
    STOP_LOSS = "stop_loss"
    TAKE_PROFIT = "take_profit"
    FINAL_CLOSE = "final_close"


class IntrabarEventFlag(IntFlag):
    NONE = 0
    ENTRY_FILLED = 1 << 0
    EXIT_FILLED = 1 << 1
    STOP_FILLED = 1 << 2
    TP_FILLED = 1 << 3
    TECH_EXIT = 1 << 4
    REVERSAL = 1 << 5
    AMBIGUOUS = 1 << 6
    FUNDING = 1 << 7


@dataclass(frozen=True)
class IntrabarIntentTape:
    entry_side: np.ndarray
    entry_size: np.ndarray
    stop_value: Optional[np.ndarray] = None
    take_profit_value: Optional[np.ndarray] = None
    trailing_value: Optional[np.ndarray] = None
    technical_exit: Optional[np.ndarray] = None
    level_mode: IntrabarLevelMode = IntrabarLevelMode.PERCENT_DISTANCE

    def __post_init__(self) -> None:
        n = len(self.entry_side)
        if len(self.entry_size) != n:
            raise ValueError("entry_size must have the same length as entry_side")
        for name in ("stop_value", "take_profit_value", "trailing_value", "technical_exit"):
            value = getattr(self, name)
            if value is not None and len(value) != n:
                raise ValueError(f"{name} must have the same length as entry_side")

    @classmethod
    def from_arrays(
        cls,
        *,
        entry_side: Sequence,
        entry_size: Sequence,
        stop_value: Optional[Sequence] = None,
        take_profit_value: Optional[Sequence] = None,
        trailing_value: Optional[Sequence] = None,
        technical_exit: Optional[Sequence] = None,
        level_mode: IntrabarLevelMode = IntrabarLevelMode.PERCENT_DISTANCE,
    ) -> "IntrabarIntentTape":
        return cls(
            entry_side=np.ascontiguousarray(entry_side, dtype=np.int8),
            entry_size=np.ascontiguousarray(entry_size, dtype=np.float64),
            stop_value=_optional_float_array(stop_value),
            take_profit_value=_optional_float_array(take_profit_value),
            trailing_value=_optional_float_array(trailing_value),
            technical_exit=None if technical_exit is None else np.ascontiguousarray(technical_exit, dtype=np.bool_),
            level_mode=level_mode,
        )


@dataclass(frozen=True)
class IntrabarFill:
    bar_index: int
    sequence: int
    timestamp: pd.Timestamp
    side: int
    qty: float
    price: float
    fee: float
    reason: IntrabarFillReason


@dataclass(frozen=True)
class IntrabarReferenceResult:
    equity: pd.Series
    position: pd.Series
    average_entry: pd.Series
    active_stop: pd.Series
    active_take_profit: pd.Series
    fees: pd.Series
    funding: pd.Series
    event_flags: pd.Series
    fills: tuple[IntrabarFill, ...]
    ambiguity_count: int
    metadata: Dict = field(default_factory=dict)


def run_intrabar_reference(
    *,
    tape: PreparedMarketTape,
    intent: IntrabarIntentTape,
    account: AccountConfig,
    contract: Optional[ExecutionContract] = None,
    fee_rate: float = 0.0,
    slippage_rate: float = 0.0,
    contract_size: float = 1.0,
) -> IntrabarReferenceResult:
    """
    Execute a single-symbol intrabar bracket tape with causal next-open timing.

    Decision arrays at index `t-1` become executable at `open[t]`.
    """
    if tape.n_symbols != 1:
        raise NotImplementedError("Phase 31B intrabar oracle certifies single-symbol tapes only")
    if len(intent.entry_side) != tape.n_bars:
        raise ValueError("intent length must match market tape length")
    if account.initial_capital <= 0.0:
        raise ValueError("initial_capital must be > 0")
    if fee_rate < 0.0 or slippage_rate < 0.0:
        raise ValueError("fee_rate and slippage_rate must be >= 0")
    contract = contract or ExecutionContract.intrabar_bracket()
    if contract.engine_id != "intrabar_bracket_v1":
        raise ValueError("run_intrabar_reference requires intrabar_bracket_v1 contract")

    idx = pd.DatetimeIndex(pd.to_datetime(tape.timestamps_ns, utc=True))
    opens = tape.opens[:, 0]
    highs = tape.highs[:, 0]
    lows = tape.lows[:, 0]
    closes = tape.closes[:, 0]
    funding_rates = tape.funding_rates[:, 0]
    funding_mask = tape.funding_event_mask

    n = tape.n_bars
    equity_arr = np.zeros(n, dtype=np.float64)
    pos_arr = np.zeros(n, dtype=np.float64)
    avg_arr = np.zeros(n, dtype=np.float64)
    stop_arr = np.zeros(n, dtype=np.float64)
    tp_arr = np.zeros(n, dtype=np.float64)
    fee_arr = np.zeros(n, dtype=np.float64)
    funding_arr = np.zeros(n, dtype=np.float64)
    flags_arr = np.zeros(n, dtype=np.uint16)

    equity = float(account.initial_capital)
    position = 0.0
    avg_entry = 0.0
    active_stop = np.nan
    active_tp = np.nan
    fills: list[IntrabarFill] = []
    ambiguity_count = 0

    equity_arr[0] = equity
    for t in range(1, n):
        seq = 0
        open_ref = float(opens[t])
        close_ref = float(closes[t])
        if position != 0.0:
            equity += position * (open_ref - float(closes[t - 1])) * contract_size

        pending_side = int(intent.entry_side[t - 1])
        pending_size = float(intent.entry_size[t - 1])
        pending_exit = bool(intent.technical_exit[t - 1]) if intent.technical_exit is not None else False

        if position != 0.0 and (pending_exit or (pending_side != 0 and np.sign(position) != pending_side)):
            reason = IntrabarFillReason.REVERSAL_EXIT if pending_side != 0 and np.sign(position) != pending_side else IntrabarFillReason.TECHNICAL_EXIT
            side = -1 if position > 0.0 else 1
            price = _market_price(open_ref, side, slippage_rate)
            fee = abs(position) * price * contract_size * fee_rate
            equity += position * (price - open_ref) * contract_size - fee
            fee_arr[t] += fee
            fills.append(_fill(t, seq, idx[t], side, abs(position), price, fee, reason))
            seq += 1
            flags_arr[t] |= int(IntrabarEventFlag.EXIT_FILLED)
            if reason is IntrabarFillReason.TECHNICAL_EXIT:
                flags_arr[t] |= int(IntrabarEventFlag.TECH_EXIT)
            else:
                flags_arr[t] |= int(IntrabarEventFlag.REVERSAL)
            position = 0.0
            avg_entry = 0.0
            active_stop = np.nan
            active_tp = np.nan

        if pending_side != 0 and pending_size > 0.0 and position == 0.0:
            side = 1 if pending_side > 0 else -1
            price = _market_price(open_ref, side, slippage_rate)
            qty = float(pending_size)
            fee = qty * price * contract_size * fee_rate
            equity -= fee
            fee_arr[t] += fee
            position = qty * side
            avg_entry = price
            active_stop, active_tp = _initial_bracket(intent, t - 1, side, price)
            reason = IntrabarFillReason.REVERSAL_ENTRY if flags_arr[t] & int(IntrabarEventFlag.REVERSAL) else IntrabarFillReason.ENTRY
            fills.append(_fill(t, seq, idx[t], side, qty, price, fee, reason))
            seq += 1
            flags_arr[t] |= int(IntrabarEventFlag.ENTRY_FILLED)

        if position != 0.0:
            exit_info = _resolve_intrabar_exit(
                side=1 if position > 0.0 else -1,
                open_price=open_ref,
                high=float(highs[t]),
                low=float(lows[t]),
                stop_price=active_stop,
                tp_price=active_tp,
                same_bar_policy=contract.same_bar_policy,
                take_profit_gap_policy=contract.take_profit_gap_policy,
                slippage_rate=slippage_rate,
            )
            if exit_info is not None:
                exit_side, exit_price, reason, ambiguous = exit_info
                if ambiguous:
                    flags_arr[t] |= int(IntrabarEventFlag.AMBIGUOUS)
                    ambiguity_count += 1
                qty = abs(position)
                fee = qty * exit_price * contract_size * fee_rate
                equity += position * (exit_price - open_ref) * contract_size - fee
                fee_arr[t] += fee
                fills.append(_fill(t, seq, idx[t], exit_side, qty, exit_price, fee, reason))
                seq += 1
                flags_arr[t] |= int(IntrabarEventFlag.EXIT_FILLED)
                if reason is IntrabarFillReason.STOP_LOSS:
                    flags_arr[t] |= int(IntrabarEventFlag.STOP_FILLED)
                else:
                    flags_arr[t] |= int(IntrabarEventFlag.TP_FILLED)
                position = 0.0
                avg_entry = 0.0
                active_stop = np.nan
                active_tp = np.nan

        if position != 0.0:
            equity += position * (close_ref - open_ref) * contract_size
            active_stop = _update_trailing(intent, t - 1, position, close_ref, active_stop)

        if position != 0.0 and funding_mask[t]:
            funding_cost = position * close_ref * contract_size * funding_rates[t]
            equity -= funding_cost
            funding_arr[t] = funding_cost
            flags_arr[t] |= int(IntrabarEventFlag.FUNDING)

        equity_arr[t] = equity
        pos_arr[t] = position
        avg_arr[t] = avg_entry
        stop_arr[t] = 0.0 if not np.isfinite(active_stop) else active_stop
        tp_arr[t] = 0.0 if not np.isfinite(active_tp) else active_tp

    if contract.close_on_last_bar and position != 0.0:
        t = n - 1
        side = -1 if position > 0.0 else 1
        price = _market_price(float(closes[t]), side, slippage_rate)
        fee = abs(position) * price * contract_size * fee_rate
        equity += position * (price - float(closes[t])) * contract_size - fee
        fee_arr[t] += fee
        fills.append(_fill(t, 99, idx[t], side, abs(position), price, fee, IntrabarFillReason.FINAL_CLOSE))
        position = 0.0
        equity_arr[t] = equity
        pos_arr[t] = 0.0
        avg_arr[t] = 0.0
        stop_arr[t] = 0.0
        tp_arr[t] = 0.0

    return IntrabarReferenceResult(
        equity=pd.Series(equity_arr, index=idx, name="equity"),
        position=pd.Series(pos_arr, index=idx, name=f"Position_{tape.symbols[0]}"),
        average_entry=pd.Series(avg_arr, index=idx, name="average_entry"),
        active_stop=pd.Series(stop_arr, index=idx, name="active_stop"),
        active_take_profit=pd.Series(tp_arr, index=idx, name="active_take_profit"),
        fees=pd.Series(fee_arr, index=idx, name="fees"),
        funding=pd.Series(funding_arr, index=idx, name="funding"),
        event_flags=pd.Series(flags_arr, index=idx, name="event_flags"),
        fills=tuple(fills),
        ambiguity_count=int(ambiguity_count),
        metadata={
            "engine": "intrabar_reference_v1",
            "engine_id": "intrabar_reference_v1",
            "execution_contract": contract.to_metadata(),
            "data_signature": tape.signature,
            "fill_count": len(fills),
            "ambiguity_count": int(ambiguity_count),
            "oracle": True,
        },
    )


def _optional_float_array(value) -> Optional[np.ndarray]:
    if value is None:
        return None
    return np.ascontiguousarray(value, dtype=np.float64)


def _fill(bar, seq, ts, side, qty, price, fee, reason) -> IntrabarFill:
    return IntrabarFill(
        bar_index=int(bar),
        sequence=int(seq),
        timestamp=pd.Timestamp(ts),
        side=int(side),
        qty=float(qty),
        price=float(price),
        fee=float(fee),
        reason=reason,
    )


def _market_price(open_price: float, side: int, slippage_rate: float) -> float:
    return float(open_price * (1.0 + slippage_rate if side > 0 else 1.0 - slippage_rate))


def _initial_bracket(intent: IntrabarIntentTape, signal_bar: int, side: int, fill_price: float) -> tuple[float, float]:
    stop = np.nan
    tp = np.nan
    if intent.stop_value is not None and np.isfinite(intent.stop_value[signal_bar]) and intent.stop_value[signal_bar] > 0.0:
        stop = _level_price(fill_price, side, float(intent.stop_value[signal_bar]), intent.level_mode, is_stop=True)
    if (
        intent.take_profit_value is not None
        and np.isfinite(intent.take_profit_value[signal_bar])
        and intent.take_profit_value[signal_bar] > 0.0
    ):
        tp = _level_price(fill_price, side, float(intent.take_profit_value[signal_bar]), intent.level_mode, is_stop=False)
    if intent.trailing_value is not None and np.isfinite(intent.trailing_value[signal_bar]) and intent.trailing_value[signal_bar] > 0.0:
        trailing_stop = _level_price(fill_price, side, float(intent.trailing_value[signal_bar]), intent.level_mode, is_stop=True)
        stop = trailing_stop if not np.isfinite(stop) else (max(stop, trailing_stop) if side > 0 else min(stop, trailing_stop))
    return stop, tp


def _level_price(price: float, side: int, value: float, mode: IntrabarLevelMode, *, is_stop: bool) -> float:
    direction = -1.0 if (side > 0 and is_stop) or (side < 0 and not is_stop) else 1.0
    if mode is IntrabarLevelMode.ABSOLUTE_PRICE:
        return float(value)
    if mode is IntrabarLevelMode.PRICE_DISTANCE:
        return float(price + direction * value)
    if mode is IntrabarLevelMode.PERCENT_DISTANCE:
        return float(price * (1.0 + direction * value))
    raise NotImplementedError(f"unsupported level mode={mode!r}")


def _resolve_intrabar_exit(
    *,
    side: int,
    open_price: float,
    high: float,
    low: float,
    stop_price: float,
    tp_price: float,
    same_bar_policy: IntrabarSameBarPolicy,
    take_profit_gap_policy: TakeProfitGapPolicy,
    slippage_rate: float,
):
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
        return None
    ambiguous = bool(stop_hit and tp_hit)
    if ambiguous and same_bar_policy is IntrabarSameBarPolicy.REJECT_AMBIGUOUS:
        raise ValueError("same bar stop/take-profit ambiguity requires lower timeframe or explicit policy")
    stop_first = same_bar_policy in {
        IntrabarSameBarPolicy.CONSERVATIVE,
        IntrabarSameBarPolicy.STOP_FIRST,
        IntrabarSameBarPolicy.OLHC_PATH if side > 0 else IntrabarSameBarPolicy.OHLC_PATH,
    }
    if stop_hit and (not tp_hit or stop_first):
        price = open_price if stop_gap else stop_price
        price = _market_price(float(price), exit_side, slippage_rate)
        return exit_side, price, IntrabarFillReason.STOP_LOSS, ambiguous
    if tp_hit:
        if tp_gap and take_profit_gap_policy is TakeProfitGapPolicy.OPEN_PRICE_IMPROVEMENT:
            price = open_price
        else:
            price = tp_price
        return exit_side, float(price), IntrabarFillReason.TAKE_PROFIT, ambiguous
    return None


def _update_trailing(intent: IntrabarIntentTape, signal_bar: int, position: float, close_price: float, current_stop: float) -> float:
    if intent.trailing_value is None:
        return current_stop
    value = float(intent.trailing_value[signal_bar])
    if not np.isfinite(value) or value <= 0.0:
        return current_stop
    side = 1 if position > 0.0 else -1
    candidate = _level_price(close_price, side, value, intent.level_mode, is_stop=True)
    if not np.isfinite(current_stop):
        return candidate
    return max(current_stop, candidate) if side > 0 else min(current_stop, candidate)
