"""
quantbt.core.basket
-------------------
Basket and pair-trading order-plan helpers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple

import numpy as np
import pandas as pd

from .orders import OrderIntent
from .preprocessor import align_series, validate_datetime
from .schema import BasketSpec, OrderSide, OrderType, TimeInForce


@dataclass(frozen=True)
class FrozenBasketPlan:
    basket: BasketSpec
    orders: Tuple[OrderIntent, ...]
    target_units: pd.DataFrame
    signals: pd.Series
    entry_ratios: pd.DataFrame
    metadata: Dict = field(default_factory=dict)


def build_frozen_basket_orders(
    datetime_index,
    basket: BasketSpec,
    signal: pd.Series,
    closes: Dict[str, pd.Series],
    hedge_ratios: Optional[Dict[str, pd.Series]] = None,
    order_type: OrderType = OrderType.MARKET,
    tif: TimeInForce = TimeInForce.IOC,
    rebalance_threshold: Optional[float] = None,
    min_abs_delta: float = 1e-12,
) -> FrozenBasketPlan:
    """
    Convert a scalar basket signal into leg orders with hedge freezing.

    Ratios are interpreted as unit ratios per one basket unit. At every signal
    transition, units are recomputed from the entry bar prices and then held
    unchanged until the next signal transition. Price drift alone does not
    generate micro-rebalancing orders.
    """
    if order_type is not OrderType.MARKET:
        raise NotImplementedError("Phase 4 basket order generation supports market orders")
    if min_abs_delta < 0.0:
        raise ValueError("min_abs_delta must be >= 0")
    if rebalance_threshold is not None and rebalance_threshold < 0.0:
        raise ValueError("rebalance_threshold must be >= 0")

    idx = validate_datetime(datetime_index)
    symbols = [leg.symbol for leg in basket.legs]
    if len(set(symbols)) != len(symbols):
        raise ValueError("basket legs must have unique symbols")
    if not set(symbols).issubset(closes.keys()):
        missing = sorted(set(symbols) - set(closes.keys()))
        raise ValueError(f"missing closes for basket legs: {missing}")

    close_dict = align_series(closes, symbols, idx)
    sig = _align_signal(signal, idx)
    ratio_dict = _build_ratio_series(basket, hedge_ratios, symbols, idx)

    orders = []
    current_units = {s: 0.0 for s in symbols}
    current_signal = 0.0
    target_rows = []
    ratio_rows = []

    for ts in idx:
        raw_signal = float(sig.loc[ts])
        if abs(raw_signal) < min_abs_delta:
            raw_signal = 0.0

        signal_changed = abs(raw_signal - current_signal) > min_abs_delta
        ratio_drift = _max_ratio_drift(current_units, ratio_dict, symbols, ts)
        should_rebalance = (
            rebalance_threshold is not None
            and raw_signal != 0.0
            and not signal_changed
            and ratio_drift > rebalance_threshold
        )
        if signal_changed or should_rebalance:
            target_units = _compute_entry_units(
                basket=basket,
                signal_value=raw_signal,
                symbols=symbols,
                timestamp=ts,
                closes=close_dict,
                ratios=ratio_dict,
            )

            for sym in symbols:
                delta = target_units[sym] - current_units[sym]
                if abs(delta) <= min_abs_delta:
                    continue
                side = OrderSide.BUY if delta > 0.0 else OrderSide.SELL
                orders.append(
                    OrderIntent(
                        timestamp=ts,
                        symbol=sym,
                        side=side,
                        order_type=order_type,
                        qty=abs(delta),
                        tif=tif,
                        tag=basket.basket_id,
                        metadata={
                            "basket_id": basket.basket_id,
                            "basket_signal": raw_signal,
                            "basket_policy": basket.execution_policy.value,
                            "hedge_frozen": basket.freeze_hedge,
                            "rebalance": should_rebalance,
                            "ratio_drift": ratio_drift,
                            "target_units": target_units[sym],
                            "previous_units": current_units[sym],
                        },
                    )
                )
                current_units[sym] = target_units[sym]

            current_signal = raw_signal

        target_rows.append({s: current_units[s] for s in symbols})
        ratio_rows.append({s: float(ratio_dict[s].loc[ts]) for s in symbols})

    return FrozenBasketPlan(
        basket=basket,
        orders=tuple(orders),
        target_units=pd.DataFrame(target_rows, index=idx),
        signals=sig,
        entry_ratios=pd.DataFrame(ratio_rows, index=idx),
        metadata={
            "basket_id": basket.basket_id,
            "gross_notional": basket.gross_notional,
            "freeze_hedge": basket.freeze_hedge,
            "execution_policy": basket.execution_policy.value,
            "hedged_margin_offset": basket.hedged_margin_offset,
            "rebalance_threshold": rebalance_threshold,
        },
    )


def _align_signal(signal: pd.Series, idx: pd.DatetimeIndex) -> pd.Series:
    if not isinstance(signal, pd.Series):
        signal = pd.Series(signal, index=idx)
    else:
        signal = signal.copy()
        if isinstance(signal.index, pd.DatetimeIndex):
            if signal.index.tz is None:
                signal.index = signal.index.tz_localize("UTC")
            else:
                signal.index = signal.index.tz_convert("UTC")
    return signal.reindex(idx, method="ffill").fillna(0.0).astype(float)


def _build_ratio_series(
    basket: BasketSpec,
    hedge_ratios: Optional[Dict[str, pd.Series]],
    symbols: list[str],
    idx: pd.DatetimeIndex,
) -> Dict[str, pd.Series]:
    defaults = {leg.symbol: float(leg.ratio) for leg in basket.legs}
    if hedge_ratios is None:
        return {s: pd.Series(defaults[s], index=idx, dtype=float) for s in symbols}

    out = {}
    for s in symbols:
        value = hedge_ratios.get(s, defaults[s])
        if isinstance(value, pd.Series):
            ser = value.copy()
            if isinstance(ser.index, pd.DatetimeIndex):
                if ser.index.tz is None:
                    ser.index = ser.index.tz_localize("UTC")
                else:
                    ser.index = ser.index.tz_convert("UTC")
            out[s] = ser.reindex(idx, method="ffill").fillna(defaults[s]).astype(float)
        else:
            out[s] = pd.Series(float(value), index=idx, dtype=float)
    return out


def _compute_entry_units(
    basket: BasketSpec,
    signal_value: float,
    symbols: list[str],
    timestamp,
    closes: Dict[str, pd.Series],
    ratios: Dict[str, pd.Series],
) -> Dict[str, float]:
    if signal_value == 0.0:
        return {s: 0.0 for s in symbols}

    gross_unit_notional = 0.0
    for s in symbols:
        price = float(closes[s].loc[timestamp])
        ratio = float(ratios[s].loc[timestamp])
        gross_unit_notional += abs(ratio) * price

    if not np.isfinite(gross_unit_notional) or gross_unit_notional <= 0.0:
        return {s: 0.0 for s in symbols}

    basket_units = basket.gross_notional * abs(signal_value) / gross_unit_notional
    signal_side = 1.0 if signal_value > 0.0 else -1.0
    return {
        s: basket_units * float(ratios[s].loc[timestamp]) * signal_side
        for s in symbols
    }


def _max_ratio_drift(
    current_units: Dict[str, float],
    ratios: Dict[str, pd.Series],
    symbols: list[str],
    timestamp,
) -> float:
    if not symbols:
        return 0.0
    ref_symbol = symbols[0]
    frozen_ref = float(current_units[ref_symbol])
    current_ref = float(ratios[ref_symbol].loc[timestamp])
    if abs(frozen_ref) <= 1e-12 or abs(current_ref) <= 1e-12:
        return 0.0

    max_drift = 0.0
    for symbol in symbols[1:]:
        frozen_ratio = float(current_units[symbol]) / frozen_ref
        current_ratio = float(ratios[symbol].loc[timestamp]) / current_ref
        denom = max(abs(frozen_ratio), 1e-12)
        max_drift = max(max_drift, abs(current_ratio - frozen_ratio) / denom)
    return max_drift
