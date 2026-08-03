"""
Option margin and liquidation approximations.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Optional, Protocol, Tuple

import pandas as pd

from ..core.orders import Fill
from ..core.schema import LiquiditySide, OrderSide
from .ledger import OptionLedger
from .schema import OptionInstrumentSpec


class OptionMarginModel(str, Enum):
    LONG_PREMIUM_ONLY = "long_premium_only"
    STANDARD_VENUE_APPROX = "standard_venue_approx"
    SCENARIO_PM_APPROX = "scenario_pm_approx"
    NO_MARGIN_RESEARCH = "no_margin_research"
    EXTERNAL_VALIDATOR = "external_validator"


class ExternalOptionMarginValidator(Protocol):
    def calculate_margin(
        self,
        ledger: OptionLedger,
        instruments: Dict[str, OptionInstrumentSpec],
        marks: Dict[str, float],
        underlying_prices: Dict[str, float],
        reporting_currency: str,
        conversion_rates: Dict[str, float],
    ) -> "OptionMarginRequirement":
        ...


@dataclass(frozen=True)
class OptionMarginConfig:
    model: OptionMarginModel = OptionMarginModel.STANDARD_VENUE_APPROX
    maintenance_ratio: float = 0.20
    long_option_margin_rate: float = 1.0
    short_option_margin_rate: float = 0.15
    scenario_shocks: Tuple[float, ...] = (-0.20, -0.10, 0.0, 0.10, 0.20)
    liquidation_fee_rate: float = 0.0
    metadata: Dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "model", _coerce_model(self.model))
        if self.maintenance_ratio < 0.0:
            raise ValueError("maintenance_ratio must be >= 0")
        if self.long_option_margin_rate < 0.0 or self.short_option_margin_rate < 0.0:
            raise ValueError("margin rates must be >= 0")
        if self.liquidation_fee_rate < 0.0:
            raise ValueError("liquidation_fee_rate must be >= 0")
        if not self.scenario_shocks:
            raise ValueError("scenario_shocks cannot be empty")


@dataclass(frozen=True)
class OptionMarginRequirement:
    initial_margin: float
    maintenance_margin: float
    model: OptionMarginModel
    venue_exact: bool
    reporting_currency: str
    detail_report: pd.DataFrame
    metadata: Dict = field(default_factory=dict)


@dataclass(frozen=True)
class OptionLiquidationAudit:
    breached: bool
    breach_reason: str
    equity_before: float
    maintenance_margin: float
    equity_after: float
    final_cash: Dict[str, float]
    final_positions: Dict[str, float]
    liquidation_orders: pd.DataFrame
    metadata: Dict = field(default_factory=dict)


def calculate_option_margin(
    ledger: OptionLedger,
    instruments: Dict[str, OptionInstrumentSpec],
    marks: Dict[str, float],
    underlying_prices: Dict[str, float],
    *,
    config: Optional[OptionMarginConfig] = None,
    reporting_currency: str = "USD",
    conversion_rates: Optional[Dict[str, float]] = None,
    external_validator: Optional[ExternalOptionMarginValidator] = None,
) -> OptionMarginRequirement:
    cfg = config or OptionMarginConfig()
    rates = conversion_rates or {}
    if cfg.model is OptionMarginModel.EXTERNAL_VALIDATOR:
        if external_validator is None:
            raise ValueError("external_validator is required for external margin model")
        return external_validator.calculate_margin(ledger, instruments, marks, underlying_prices, reporting_currency, rates)
    rows = []
    total_initial = 0.0
    for symbol, position in ledger.positions.items():
        if position.is_flat:
            continue
        instrument = instruments.get(symbol)
        if instrument is None:
            raise ValueError(f"missing instrument for {symbol}")
        mark = _positive_map_value(marks, symbol, "mark")
        conversion = _conversion_rate(instrument.premium_currency, rates, reporting_currency)
        qty = float(position.qty)
        abs_qty = abs(qty)
        long_value = max(qty, 0.0) * mark * instrument.multiplier * conversion
        short_abs_value = max(-qty, 0.0) * mark * instrument.multiplier * conversion
        underlying = _underlying_price(instrument, underlying_prices)
        underlying_notional = abs_qty * underlying * instrument.multiplier * _conversion_rate(instrument.quote_currency, rates, reporting_currency)
        if cfg.model is OptionMarginModel.NO_MARGIN_RESEARCH:
            requirement = 0.0
            reason = "research_no_margin"
        elif cfg.model is OptionMarginModel.LONG_PREMIUM_ONLY:
            requirement = long_value * cfg.long_option_margin_rate
            reason = "long_premium_only"
        elif cfg.model is OptionMarginModel.STANDARD_VENUE_APPROX:
            requirement = long_value * cfg.long_option_margin_rate + max(short_abs_value, underlying_notional * cfg.short_option_margin_rate)
            reason = "standard_short_notional_approx"
        elif cfg.model is OptionMarginModel.SCENARIO_PM_APPROX:
            requirement = _scenario_requirement(position_qty=qty, mark=mark, underlying=underlying, instrument=instrument, cfg=cfg, conversion=conversion)
            reason = "scenario_pm_approx"
        else:
            raise ValueError(f"unsupported margin model: {cfg.model}")
        total_initial += requirement
        rows.append(
            {
                "symbol": symbol,
                "qty": qty,
                "mark": mark,
                "underlying_price": underlying,
                "premium_currency": instrument.premium_currency,
                "requirement": float(requirement),
                "reason": reason,
                "venue_exact": False,
            }
        )
    maintenance = total_initial * cfg.maintenance_ratio
    ledger.margin_locked[str(reporting_currency).upper()] = float(total_initial)
    return OptionMarginRequirement(
        initial_margin=float(total_initial),
        maintenance_margin=float(maintenance),
        model=cfg.model,
        venue_exact=False,
        reporting_currency=str(reporting_currency).upper(),
        detail_report=pd.DataFrame(rows),
        metadata={"venue_exact": False, **cfg.metadata},
    )


def liquidate_option_positions(
    ledger: OptionLedger,
    instruments: Dict[str, OptionInstrumentSpec],
    *,
    bid_prices: Dict[str, float],
    ask_prices: Dict[str, float],
    margin_requirement: OptionMarginRequirement,
    conversion_rates: Dict[str, float],
    reporting_currency: str = "USD",
    timestamp_ns: int,
    fee_rate: float = 0.0,
) -> OptionLiquidationAudit:
    """Liquidate all option positions with adverse bid/ask prices if breached."""
    equity_before = ledger.equity(
        conversion_rates=conversion_rates,
        marks=_marks_from_bbo(bid_prices, ask_prices),
        instruments=instruments,
        reporting_currency=reporting_currency,
    )
    if equity_before >= margin_requirement.maintenance_margin:
        return OptionLiquidationAudit(
            breached=False,
            breach_reason="equity_above_maintenance",
            equity_before=float(equity_before),
            maintenance_margin=float(margin_requirement.maintenance_margin),
            equity_after=float(equity_before),
            final_cash=dict(ledger.cash),
            final_positions={symbol: pos.qty for symbol, pos in ledger.positions.items() if not pos.is_flat},
            liquidation_orders=pd.DataFrame(),
            metadata={"venue_exact": margin_requirement.venue_exact},
        )
    rows = []
    for symbol, position in list(ledger.positions.items()):
        if position.is_flat:
            continue
        instrument = instruments.get(symbol)
        if instrument is None:
            raise ValueError(f"missing instrument for {symbol}")
        if position.qty > 0.0:
            side = OrderSide.SELL
            price = _positive_map_value(bid_prices, symbol, "bid")
        else:
            side = OrderSide.BUY
            price = _positive_map_value(ask_prices, symbol, "ask")
        qty = abs(float(position.qty))
        fee = qty * price * instrument.multiplier * float(fee_rate)
        fill = Fill(
            timestamp=int(timestamp_ns),
            symbol=symbol,
            side=side,
            qty=qty,
            price=price,
            fee=fee,
            liquidity=LiquiditySide.TAKER,
            metadata={"liquidation": True, "adverse_bid_ask": True},
        )
        ledger.apply_fill(fill, instrument, timestamp_ns=timestamp_ns)
        rows.append(
            {
                "timestamp_ns": int(timestamp_ns),
                "symbol": symbol,
                "side": side.value,
                "qty": qty,
                "price": price,
                "fee": fee,
                "reason": "maintenance_margin_breach",
                "adverse_bid_ask": True,
            }
        )
    equity_after = ledger.equity(
        conversion_rates=conversion_rates,
        marks=_marks_from_bbo(bid_prices, ask_prices),
        instruments=instruments,
        reporting_currency=reporting_currency,
    )
    return OptionLiquidationAudit(
        breached=True,
        breach_reason="maintenance_margin_breach",
        equity_before=float(equity_before),
        maintenance_margin=float(margin_requirement.maintenance_margin),
        equity_after=float(equity_after),
        final_cash=dict(ledger.cash),
        final_positions={symbol: pos.qty for symbol, pos in ledger.positions.items() if not pos.is_flat},
        liquidation_orders=pd.DataFrame(rows),
        metadata={
            "venue_exact": margin_requirement.venue_exact,
            "liquidation_sequence": "all_positions_adverse_bid_ask",
            "fee_rate": float(fee_rate),
        },
    )


def _scenario_requirement(
    *,
    position_qty: float,
    mark: float,
    underlying: float,
    instrument: OptionInstrumentSpec,
    cfg: OptionMarginConfig,
    conversion: float,
) -> float:
    if position_qty >= 0.0:
        return abs(position_qty) * mark * instrument.multiplier * conversion * cfg.long_option_margin_rate
    worst_loss = 0.0
    base_value = mark
    for shock in cfg.scenario_shocks:
        shocked_mark = max(mark * (1.0 + abs(float(shock)) * underlying / max(underlying, 1e-12)), 0.0)
        pnl = float(position_qty) * (shocked_mark - base_value) * instrument.multiplier * conversion
        worst_loss = max(worst_loss, -pnl)
    floor = abs(position_qty) * underlying * instrument.multiplier * conversion * cfg.short_option_margin_rate
    return max(worst_loss, floor)


def _underlying_price(instrument: OptionInstrumentSpec, underlying_prices: Dict[str, float]) -> float:
    if instrument.underlying_id in underlying_prices:
        return _positive_map_value(underlying_prices, instrument.underlying_id, "underlying")
    return _positive_map_value(underlying_prices, instrument.symbol, "underlying")


def _marks_from_bbo(bid_prices: Dict[str, float], ask_prices: Dict[str, float]) -> Dict[str, float]:
    symbols = set(bid_prices).union(ask_prices)
    return {symbol: 0.5 * (_positive_map_value(bid_prices, symbol, "bid") + _positive_map_value(ask_prices, symbol, "ask")) for symbol in symbols}


def _positive_map_value(values: Dict[str, float], key: str, label: str) -> float:
    if key not in values:
        raise ValueError(f"missing {label} for {key}")
    value = float(values[key])
    if value <= 0.0:
        raise ValueError(f"{label} for {key} must be > 0")
    return value


def _conversion_rate(currency: str, conversion_rates: Dict[str, float], reporting_currency: str) -> float:
    ccy = str(currency).upper()
    report = str(reporting_currency).upper()
    if ccy == report:
        return 1.0
    if ccy not in conversion_rates:
        raise ValueError(f"missing conversion rate for {ccy}->{report}")
    rate = float(conversion_rates[ccy])
    if rate <= 0.0:
        raise ValueError(f"conversion rate for {ccy}->{report} must be > 0")
    return rate


def _coerce_model(value) -> OptionMarginModel:
    if isinstance(value, OptionMarginModel):
        return value
    try:
        return OptionMarginModel(str(value))
    except ValueError as exc:
        raise ValueError("invalid option margin model") from exc
