"""
quantbt.core.arbitrage
----------------------
Phase A arbitrage domain schema and executable order-plan helpers.

This module intentionally stops short of a full ArbitrageBacktestEngine.  It
defines the public domain objects and deterministic package order planning
needed by golden tests before engine implementation begins.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from math import floor, isfinite
from typing import Dict, Optional, Tuple

import pandas as pd

from .orders import OrderIntent
from .preprocessor import align_series, validate_datetime
from .schema import OrderSide, OrderType, TimeInForce


class ArbitrageType(str, Enum):
    BASIS = "basis"
    CALENDAR_SPREAD = "calendar_spread"
    FUNDING = "funding"
    STAT_ARB_PAIR = "stat_arb_pair"
    INDEX_BASKET = "index_basket"
    TRIANGULAR = "triangular"
    CROSS_EXCHANGE = "cross_exchange"
    SPOT_PERP_CASH_CARRY = "spot_perp_cash_carry"
    OPTIONS_VOL = "options_vol"


class ContractType(str, Enum):
    LINEAR = "linear"
    INVERSE = "inverse"
    QUANTO = "quanto"
    SPOT = "spot"
    OPTION = "option"


class HedgePolicyKind(str, Enum):
    BASE_QTY_EQUAL = "base_qty_equal"
    DELTA_NEUTRAL = "delta_neutral"
    NOTIONAL_NEUTRAL = "notional_neutral"
    BETA_NEUTRAL = "beta_neutral"
    VEGA_NEUTRAL = "vega_neutral"


class SizingPolicyKind(str, Enum):
    TARGET_NOTIONAL_TO_BASE_QTY = "target_notional_to_base_qty"
    TARGET_GROSS_NOTIONAL = "target_gross_notional"
    TARGET_BASE_QTY = "target_base_qty"
    EQUITY_FRACTION = "equity_fraction"


class PackageExecutionKind(str, Enum):
    ATOMIC_ALL_OR_NONE = "atomic_all_or_none"
    BEST_EFFORT = "best_effort"
    SEQUENTIAL = "sequential"
    HEDGE_AFTER_PRIMARY = "hedge_after_primary"
    REBALANCE_ONLY = "rebalance_only"


@dataclass(frozen=True)
class ArbitrageLeg:
    symbol: str
    ratio: float
    role: str = "leg"
    venue: Optional[str] = None
    asset_class: str = "future"
    quote_currency: str = "USDT"
    base_currency: Optional[str] = None
    contract_type: ContractType = ContractType.LINEAR
    contract_size: float = 1.0
    qty_step: float = 0.0
    min_qty: float = 0.0
    min_notional: float = 0.0
    tick_size: float = 0.0
    fee_rate: Optional[float] = None
    funding_enabled: bool = False
    expiry: Optional[pd.Timestamp] = None
    settlement_policy: Optional[str] = None
    metadata: Dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.symbol:
            raise ValueError("symbol is required")
        if not isfinite(float(self.ratio)) or float(self.ratio) == 0.0:
            raise ValueError("ratio must be finite and non-zero")
        if self.contract_size <= 0.0:
            raise ValueError("contract_size must be > 0")
        if self.qty_step < 0.0:
            raise ValueError("qty_step must be >= 0")
        if self.min_qty < 0.0 or self.min_notional < 0.0:
            raise ValueError("min_qty and min_notional must be >= 0")
        if self.tick_size < 0.0:
            raise ValueError("tick_size must be >= 0")
        if self.fee_rate is not None and self.fee_rate < 0.0:
            raise ValueError("fee_rate must be >= 0")


@dataclass(frozen=True)
class HedgePolicy:
    kind: HedgePolicyKind
    freeze_on_entry: bool = True
    rebalance_threshold: Optional[float] = None
    rebalance_interval: Optional[str] = None
    metadata: Dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.rebalance_threshold is not None and self.rebalance_threshold < 0.0:
            raise ValueError("rebalance_threshold must be >= 0")


@dataclass(frozen=True)
class SizingPolicy:
    kind: SizingPolicyKind
    notional: Optional[float] = None
    base_qty: Optional[float] = None
    equity_fraction: Optional[float] = None
    reference_symbol: Optional[str] = None
    metadata: Dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.notional is not None and self.notional <= 0.0:
            raise ValueError("notional must be > 0")
        if self.base_qty is not None and self.base_qty <= 0.0:
            raise ValueError("base_qty must be > 0")
        if self.equity_fraction is not None and self.equity_fraction <= 0.0:
            raise ValueError("equity_fraction must be > 0")
        if self.kind in (SizingPolicyKind.TARGET_NOTIONAL_TO_BASE_QTY, SizingPolicyKind.TARGET_GROSS_NOTIONAL):
            if self.notional is None:
                raise ValueError(f"{self.kind.value} requires notional")
        if self.kind is SizingPolicyKind.TARGET_BASE_QTY and self.base_qty is None:
            raise ValueError("target_base_qty requires base_qty")


@dataclass(frozen=True)
class ArbExecutionPolicy:
    kind: PackageExecutionKind = PackageExecutionKind.ATOMIC_ALL_OR_NONE
    allow_partial_fill: bool = False
    order_type: OrderType = OrderType.MARKET
    tif: TimeInForce = TimeInForce.IOC
    metadata: Dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.kind is PackageExecutionKind.ATOMIC_ALL_OR_NONE and self.allow_partial_fill:
            raise ValueError("atomic_all_or_none cannot allow partial fills")
        if self.kind is PackageExecutionKind.BEST_EFFORT and not self.allow_partial_fill:
            object.__setattr__(self, "allow_partial_fill", True)


@dataclass(frozen=True)
class ArbitrageSpec:
    arb_id: str
    legs: Tuple[ArbitrageLeg, ...]
    hedge_policy: HedgePolicy
    sizing_policy: SizingPolicy
    execution_policy: ArbExecutionPolicy = field(default_factory=ArbExecutionPolicy)
    arb_type: ArbitrageType = ArbitrageType.BASIS
    metadata: Dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.arb_id:
            raise ValueError("arb_id is required")
        if len(self.legs) < 2:
            raise ValueError("arbitrage spec requires at least two legs")
        symbols = [leg.symbol for leg in self.legs]
        if len(set(symbols)) != len(symbols):
            raise ValueError("arbitrage legs must have unique symbols")


@dataclass(frozen=True)
class BasisArbitrageSpec(ArbitrageSpec):
    arb_type: ArbitrageType = ArbitrageType.BASIS

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.hedge_policy.kind not in (HedgePolicyKind.BASE_QTY_EQUAL, HedgePolicyKind.DELTA_NEUTRAL):
            raise ValueError("BasisArbitrageSpec requires base_qty_equal or delta_neutral hedge policy")
        linear_legs = [leg for leg in self.legs if leg.contract_type is ContractType.LINEAR]
        if len(linear_legs) != len(self.legs):
            # Inverse/quanto support is planned, but Phase A keeps the clean
            # USDM linear basis contract explicit.
            raise NotImplementedError("Phase A BasisArbitrageSpec supports linear legs only")


@dataclass(frozen=True)
class CalendarSpreadSpec(ArbitrageSpec):
    arb_type: ArbitrageType = ArbitrageType.CALENDAR_SPREAD


@dataclass(frozen=True)
class FundingArbitrageSpec(ArbitrageSpec):
    arb_type: ArbitrageType = ArbitrageType.FUNDING


@dataclass(frozen=True)
class StatArbPairSpec(ArbitrageSpec):
    arb_type: ArbitrageType = ArbitrageType.STAT_ARB_PAIR


@dataclass(frozen=True)
class IndexBasketArbSpec(ArbitrageSpec):
    arb_type: ArbitrageType = ArbitrageType.INDEX_BASKET


@dataclass(frozen=True)
class TriangularArbSpec(ArbitrageSpec):
    arb_type: ArbitrageType = ArbitrageType.TRIANGULAR


@dataclass(frozen=True)
class CrossExchangeArbSpec(ArbitrageSpec):
    arb_type: ArbitrageType = ArbitrageType.CROSS_EXCHANGE


@dataclass(frozen=True)
class SpotPerpCashCarrySpec(ArbitrageSpec):
    arb_type: ArbitrageType = ArbitrageType.SPOT_PERP_CASH_CARRY


@dataclass(frozen=True)
class OptionsVolArbSpec(ArbitrageSpec):
    arb_type: ArbitrageType = ArbitrageType.OPTIONS_VOL


@dataclass(frozen=True)
class PackageRejection:
    timestamp: object
    arb_id: str
    reason: str
    failed_legs: Tuple[str, ...]
    metadata: Dict = field(default_factory=dict)


@dataclass(frozen=True)
class ArbitragePlan:
    spec: ArbitrageSpec
    orders: Tuple[OrderIntent, ...]
    target_units: pd.DataFrame
    signals: pd.Series
    entry_ratios: pd.DataFrame
    rejections: Tuple[PackageRejection, ...] = ()
    metadata: Dict = field(default_factory=dict)

    @property
    def rejection_report(self) -> pd.DataFrame:
        rows = [
            {
                "timestamp": rejection.timestamp,
                "arb_id": rejection.arb_id,
                "reason": rejection.reason,
                "failed_legs": ",".join(rejection.failed_legs),
                **rejection.metadata,
            }
            for rejection in self.rejections
        ]
        return pd.DataFrame(rows)


def build_arbitrage_order_plan(
    datetime_index,
    spec: ArbitrageSpec,
    signal: pd.Series,
    closes: Dict[str, pd.Series],
    hedge_ratios: Optional[Dict[str, pd.Series]] = None,
    min_abs_delta: float = 1e-12,
) -> ArbitragePlan:
    """
    Convert a scalar arbitrage signal into package leg orders.

    Phase A behavior is deterministic by design:

    * units are computed on signal transitions only;
    * units are frozen while signal is unchanged;
    * package precision/min-notional rejects are explicit;
    * atomic policy rejects the whole package;
    * best-effort policy keeps valid legs and records rejected legs.
    """
    if min_abs_delta < 0.0:
        raise ValueError("min_abs_delta must be >= 0")

    idx = validate_datetime(datetime_index)
    symbols = [leg.symbol for leg in spec.legs]
    if not set(symbols).issubset(closes.keys()):
        missing = sorted(set(symbols) - set(closes.keys()))
        raise ValueError(f"missing closes for arbitrage legs: {missing}")

    close_dict = align_series(closes, symbols, idx)
    sig = _align_signal(signal, idx)
    ratio_dict = _build_ratio_series(spec, hedge_ratios, symbols, idx)

    orders = []
    rejections = []
    current_units = {symbol: 0.0 for symbol in symbols}
    current_signal = 0.0
    target_rows = []
    ratio_rows = []

    for ts in idx:
        raw_signal = float(sig.loc[ts])
        if abs(raw_signal) < min_abs_delta:
            raw_signal = 0.0

        changed = abs(raw_signal - current_signal) > min_abs_delta
        if changed:
            target_units = _compute_target_units(spec, raw_signal, symbols, ts, close_dict, ratio_dict)
            failed = _validate_target_units(spec, target_units, ts, close_dict)
            if failed:
                rejections.append(
                    PackageRejection(
                        timestamp=ts,
                        arb_id=spec.arb_id,
                        reason="precision_or_min_notional",
                        failed_legs=tuple(failed.keys()),
                        metadata={"details": failed, "policy": spec.execution_policy.kind.value},
                    )
                )
                if spec.execution_policy.kind is PackageExecutionKind.ATOMIC_ALL_OR_NONE:
                    target_units = dict(current_units)
                elif spec.execution_policy.kind is PackageExecutionKind.BEST_EFFORT:
                    for failed_symbol in failed:
                        target_units[failed_symbol] = current_units[failed_symbol]

            for symbol in symbols:
                delta = target_units[symbol] - current_units[symbol]
                if abs(delta) <= min_abs_delta:
                    continue
                side = OrderSide.BUY if delta > 0.0 else OrderSide.SELL
                orders.append(
                    OrderIntent(
                        timestamp=ts,
                        symbol=symbol,
                        side=side,
                        order_type=spec.execution_policy.order_type,
                        qty=abs(delta),
                        tif=spec.execution_policy.tif,
                        tag=spec.arb_id,
                        metadata={
                            "arb_id": spec.arb_id,
                            "arb_type": spec.arb_type.value,
                            "package_policy": spec.execution_policy.kind.value,
                            "hedge_policy": spec.hedge_policy.kind.value,
                            "sizing_policy": spec.sizing_policy.kind.value,
                            "target_units": target_units[symbol],
                            "previous_units": current_units[symbol],
                        },
                    )
                )
                current_units[symbol] = target_units[symbol]

            current_signal = raw_signal

        target_rows.append({symbol: current_units[symbol] for symbol in symbols})
        ratio_rows.append({symbol: float(ratio_dict[symbol].loc[ts]) for symbol in symbols})

    return ArbitragePlan(
        spec=spec,
        orders=tuple(orders),
        target_units=pd.DataFrame(target_rows, index=idx),
        signals=sig,
        entry_ratios=pd.DataFrame(ratio_rows, index=idx),
        rejections=tuple(rejections),
        metadata={
            "arb_id": spec.arb_id,
            "arb_type": spec.arb_type.value,
            "execution_policy": spec.execution_policy.kind.value,
            "hedge_policy": spec.hedge_policy.kind.value,
            "sizing_policy": spec.sizing_policy.kind.value,
        },
    )


def round_down_to_step(value: float, step: float) -> float:
    if value < 0.0:
        raise ValueError("value must be >= 0")
    if step < 0.0:
        raise ValueError("step must be >= 0")
    if step == 0.0:
        return value
    return floor((value + 1e-15) / step) * step


def _align_signal(signal: pd.Series, idx: pd.DatetimeIndex) -> pd.Series:
    if not isinstance(signal, pd.Series):
        signal = pd.Series(signal, index=idx)
    else:
        signal = signal.copy()
        if isinstance(signal.index, pd.DatetimeIndex):
            signal.index = signal.index.tz_localize("UTC") if signal.index.tz is None else signal.index.tz_convert("UTC")
    return signal.reindex(idx, method="ffill").fillna(0.0).astype(float)


def _build_ratio_series(
    spec: ArbitrageSpec,
    hedge_ratios: Optional[Dict[str, pd.Series]],
    symbols: list[str],
    idx: pd.DatetimeIndex,
) -> Dict[str, pd.Series]:
    defaults = {leg.symbol: float(leg.ratio) for leg in spec.legs}
    if hedge_ratios is None:
        return {symbol: pd.Series(defaults[symbol], index=idx, dtype=float) for symbol in symbols}

    out = {}
    for symbol in symbols:
        value = hedge_ratios.get(symbol, defaults[symbol])
        if isinstance(value, pd.Series):
            series = value.copy()
            if isinstance(series.index, pd.DatetimeIndex):
                series.index = series.index.tz_localize("UTC") if series.index.tz is None else series.index.tz_convert("UTC")
            out[symbol] = series.reindex(idx, method="ffill").fillna(defaults[symbol]).astype(float)
        else:
            out[symbol] = pd.Series(float(value), index=idx, dtype=float)
    return out


def _compute_target_units(
    spec: ArbitrageSpec,
    signal_value: float,
    symbols: list[str],
    timestamp,
    closes: Dict[str, pd.Series],
    ratios: Dict[str, pd.Series],
) -> Dict[str, float]:
    if signal_value == 0.0:
        return {symbol: 0.0 for symbol in symbols}

    side = 1.0 if signal_value > 0.0 else -1.0
    magnitude = abs(signal_value)
    if spec.sizing_policy.kind is SizingPolicyKind.TARGET_BASE_QTY:
        base_qty = float(spec.sizing_policy.base_qty) * magnitude
    elif spec.sizing_policy.kind is SizingPolicyKind.TARGET_NOTIONAL_TO_BASE_QTY:
        reference_symbol = spec.sizing_policy.reference_symbol or symbols[0]
        reference_price = float(closes[reference_symbol].loc[timestamp])
        if reference_price <= 0.0:
            base_qty = 0.0
        else:
            raw_qty = float(spec.sizing_policy.notional) * magnitude / reference_price
            base_qty = _round_to_common_step(raw_qty, spec.legs)
    elif spec.sizing_policy.kind is SizingPolicyKind.TARGET_GROSS_NOTIONAL:
        gross_unit_notional = 0.0
        for symbol in symbols:
            gross_unit_notional += abs(float(ratios[symbol].loc[timestamp])) * float(closes[symbol].loc[timestamp])
        if gross_unit_notional <= 0.0:
            base_qty = 0.0
        else:
            base_qty = float(spec.sizing_policy.notional) * magnitude / gross_unit_notional
    else:
        raise NotImplementedError("equity_fraction sizing is reserved for engine phase")

    return {
        symbol: base_qty * float(ratios[symbol].loc[timestamp]) * side
        for symbol in symbols
    }


def _round_to_common_step(value: float, legs: Tuple[ArbitrageLeg, ...]) -> float:
    out = value
    for leg in legs:
        out = round_down_to_step(out, leg.qty_step)
    return out


def _validate_target_units(
    spec: ArbitrageSpec,
    target_units: Dict[str, float],
    timestamp,
    closes: Dict[str, pd.Series],
) -> Dict[str, Dict[str, float]]:
    failed: Dict[str, Dict[str, float]] = {}
    for leg in spec.legs:
        qty = abs(float(target_units[leg.symbol]))
        if qty == 0.0:
            continue
        price = float(closes[leg.symbol].loc[timestamp])
        notional = qty * price * leg.contract_size
        reasons = {}
        if leg.min_qty > 0.0 and qty < leg.min_qty:
            reasons["min_qty"] = leg.min_qty
        if leg.min_notional > 0.0 and notional < leg.min_notional:
            reasons["min_notional"] = leg.min_notional
        if leg.qty_step > 0.0:
            rounded = round_down_to_step(qty, leg.qty_step)
            if abs(qty - rounded) > 1e-12:
                reasons["qty_step"] = leg.qty_step
        if reasons:
            reasons["qty"] = qty
            reasons["notional"] = notional
            failed[leg.symbol] = reasons
    return failed
