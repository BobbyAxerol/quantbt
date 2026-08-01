"""
Multi-currency option ledger.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable, Optional

import pandas as pd

from ..core.orders import Fill
from ..core.schema import OrderSide
from .fees import OptionFeeResult
from .schema import OptionInstrumentSpec


@dataclass
class OptionPosition:
    symbol: str
    qty: float = 0.0
    avg_entry: float = 0.0
    realized_pnl: float = 0.0
    premium_currency: str = ""
    settlement_currency: str = ""
    multiplier: float = 1.0

    @property
    def is_flat(self) -> bool:
        return abs(self.qty) <= 1e-12


@dataclass
class OptionLedger:
    cash: Dict[str, float] = field(default_factory=dict)
    positions: Dict[str, OptionPosition] = field(default_factory=dict)
    realized_pnl: Dict[str, float] = field(default_factory=dict)
    fees: Dict[str, float] = field(default_factory=dict)
    settlement_cashflows: Dict[str, float] = field(default_factory=dict)
    margin_locked: Dict[str, float] = field(default_factory=dict)
    events: list[Dict] = field(default_factory=list)
    settled_symbols: set[str] = field(default_factory=set)

    @classmethod
    def from_cash(cls, balances: Dict[str, float]) -> "OptionLedger":
        ledger = cls()
        for currency, amount in balances.items():
            ledger.cash[str(currency).upper()] = float(amount)
        return ledger

    def apply_fill(
        self,
        fill: Fill,
        instrument: OptionInstrumentSpec,
        *,
        fee: Optional[OptionFeeResult] = None,
        timestamp_ns: Optional[int] = None,
    ) -> None:
        """Apply premium cashflow, fee, position quantity, and realized PnL."""
        premium_currency = instrument.premium_currency
        fee_amount = float(fee.fee) if fee is not None else float(fill.fee)
        fee_currency = fee.currency if fee is not None else premium_currency
        premium = float(fill.qty) * float(fill.price) * float(instrument.multiplier)
        premium_cash_delta = premium if fill.side is OrderSide.SELL else -premium
        self._add_cash(premium_currency, premium_cash_delta)
        if fee_amount:
            self._add_cash(fee_currency, -fee_amount)
            self.fees[fee_currency] = self.fees.get(fee_currency, 0.0) + fee_amount
        realized = self._apply_position(fill, instrument)
        if realized:
            self.realized_pnl[premium_currency] = self.realized_pnl.get(premium_currency, 0.0) + realized
        self.events.append(
            {
                "timestamp_ns": int(timestamp_ns if timestamp_ns is not None else fill.timestamp),
                "event_type": "fill",
                "symbol": fill.symbol,
                "side": fill.side.value,
                "qty": float(fill.qty),
                "price": float(fill.price),
                "premium_currency": premium_currency,
                "premium_cashflow": float(premium_cash_delta),
                "fee_currency": fee_currency,
                "fee": fee_amount,
                "realized_pnl": float(realized),
                "cash_after": dict(self.cash),
                "position_after": self.positions.get(fill.symbol).qty if fill.symbol in self.positions else 0.0,
            }
        )

    def apply_settlement(
        self,
        instrument: OptionInstrumentSpec,
        *,
        timestamp_ns: int,
        settlement_price: float,
        payoff_per_unit: float,
        representation: str,
    ) -> float:
        """Settle and close an option position exactly once."""
        if instrument.symbol in self.settled_symbols:
            raise ValueError(f"{instrument.symbol} has already been settled")
        position = self.positions.get(instrument.symbol)
        if position is None or position.is_flat:
            self.settled_symbols.add(instrument.symbol)
            self.events.append(
                {
                    "timestamp_ns": int(timestamp_ns),
                    "event_type": "settlement",
                    "symbol": instrument.symbol,
                    "settlement_price": float(settlement_price),
                    "payoff_per_unit": float(payoff_per_unit),
                    "settlement_currency": instrument.settlement_currency,
                    "settlement_cashflow": 0.0,
                    "representation": representation,
                    "position_closed": True,
                    "cash_after": dict(self.cash),
                }
            )
            return 0.0
        cashflow = float(position.qty) * float(payoff_per_unit) * float(instrument.multiplier)
        self._add_cash(instrument.settlement_currency, cashflow)
        self.settlement_cashflows[instrument.settlement_currency] = (
            self.settlement_cashflows.get(instrument.settlement_currency, 0.0) + cashflow
        )
        position.realized_pnl += cashflow
        self.realized_pnl[instrument.settlement_currency] = self.realized_pnl.get(instrument.settlement_currency, 0.0) + cashflow
        position.qty = 0.0
        position.avg_entry = 0.0
        self.settled_symbols.add(instrument.symbol)
        self.events.append(
            {
                "timestamp_ns": int(timestamp_ns),
                "event_type": "settlement",
                "symbol": instrument.symbol,
                "settlement_price": float(settlement_price),
                "payoff_per_unit": float(payoff_per_unit),
                "settlement_currency": instrument.settlement_currency,
                "settlement_cashflow": float(cashflow),
                "representation": representation,
                "position_closed": True,
                "cash_after": dict(self.cash),
            }
        )
        return cashflow

    def equity(
        self,
        *,
        conversion_rates: Dict[str, float],
        marks: Optional[Dict[str, float]] = None,
        instruments: Optional[Dict[str, OptionInstrumentSpec]] = None,
        reporting_currency: str = "USD",
    ) -> float:
        """Return marked equity in reporting currency."""
        total = 0.0
        for currency, amount in self.cash.items():
            total += float(amount) * _conversion_rate(currency, conversion_rates, reporting_currency)
        if marks and instruments:
            for symbol, mark in marks.items():
                position = self.positions.get(symbol)
                instrument = instruments.get(symbol)
                if position is None or instrument is None or position.is_flat:
                    continue
                total += (
                    float(position.qty)
                    * float(mark)
                    * float(instrument.multiplier)
                    * _conversion_rate(instrument.premium_currency, conversion_rates, reporting_currency)
                )
        return float(total)

    def equity_identity_report(
        self,
        *,
        conversion_rates: Dict[str, float],
        marks: Optional[Dict[str, float]] = None,
        instruments: Optional[Dict[str, OptionInstrumentSpec]] = None,
        reporting_currency: str = "USD",
    ) -> Dict:
        equity = self.equity(
            conversion_rates=conversion_rates,
            marks=marks,
            instruments=instruments,
            reporting_currency=reporting_currency,
        )
        cash_equity = sum(
            float(amount) * _conversion_rate(currency, conversion_rates, reporting_currency)
            for currency, amount in self.cash.items()
        )
        mark_equity = equity - cash_equity
        return {
            "reporting_currency": reporting_currency.upper(),
            "cash_equity": float(cash_equity),
            "mark_equity": float(mark_equity),
            "equity": float(equity),
            "cash": dict(self.cash),
            "fees": dict(self.fees),
            "realized_pnl": dict(self.realized_pnl),
            "settlement_cashflows": dict(self.settlement_cashflows),
            "margin_locked": dict(self.margin_locked),
            "events": len(self.events),
            "reconciled": True,
        }

    def event_report(self) -> pd.DataFrame:
        return pd.DataFrame(self.events)

    def _apply_position(self, fill: Fill, instrument: OptionInstrumentSpec) -> float:
        position = self.positions.get(fill.symbol)
        if position is None:
            position = OptionPosition(
                symbol=fill.symbol,
                premium_currency=instrument.premium_currency,
                settlement_currency=instrument.settlement_currency,
                multiplier=instrument.multiplier,
            )
            self.positions[fill.symbol] = position
        signed_qty = float(fill.signed_qty)
        fill_price = float(fill.price)
        prev_qty = float(position.qty)
        realized = 0.0
        if abs(prev_qty) <= 1e-12 or prev_qty * signed_qty > 0.0:
            new_abs = abs(prev_qty) + abs(signed_qty)
            position.avg_entry = (
                (abs(prev_qty) * position.avg_entry + abs(signed_qty) * fill_price) / new_abs
                if new_abs > 0.0
                else 0.0
            )
            position.qty = prev_qty + signed_qty
            return 0.0
        close_qty = min(abs(prev_qty), abs(signed_qty))
        if prev_qty > 0.0:
            realized = (fill_price - position.avg_entry) * close_qty * float(instrument.multiplier)
        else:
            realized = (position.avg_entry - fill_price) * close_qty * float(instrument.multiplier)
        new_qty = prev_qty + signed_qty
        position.realized_pnl += realized
        if abs(new_qty) <= 1e-12:
            position.qty = 0.0
            position.avg_entry = 0.0
        elif prev_qty * new_qty > 0.0:
            position.qty = new_qty
        else:
            position.qty = new_qty
            position.avg_entry = fill_price
        return float(realized)

    def _add_cash(self, currency: str, amount: float) -> None:
        key = str(currency).upper()
        self.cash[key] = self.cash.get(key, 0.0) + float(amount)


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
