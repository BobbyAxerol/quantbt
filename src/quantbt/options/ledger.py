"""
Multi-currency option ledger.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Dict, Optional

import pandas as pd

from ..core.orders import Fill
from ..core.schema import OrderSide
from .fees import OptionFeeResult
from .schema import OptionInstrumentSpec
from .validation import conversion_rate as _conversion_rate, currency_amounts, finite_number


@dataclass
class OptionPosition:
    symbol: str
    qty: float = 0.0
    avg_entry: float = 0.0
    realized_pnl: float = 0.0
    premium_currency: str = ""
    settlement_currency: str = ""
    multiplier: float = 1.0
    # The legacy scalar is premium-currency PnL, never a sum of currencies.
    realized_pnl_by_currency: Dict[str, float] = field(default_factory=dict)

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

    def __post_init__(self) -> None:
        for name in ("cash", "realized_pnl", "fees", "settlement_cashflows", "margin_locked"):
            amounts = currency_amounts(getattr(self, name), name)
            if name in ("fees", "margin_locked"):
                for currency, amount in amounts.items():
                    finite_number(amount, f"{name}[{currency}]", minimum=0.0)
            setattr(self, name, amounts)

    @classmethod
    def from_cash(cls, balances: Dict[str, float]) -> "OptionLedger":
        return cls(cash=dict(balances))

    def clone(self) -> "OptionLedger":
        """Copy all financial state for an all-or-nothing admission preview."""

        return OptionLedger(
            cash=dict(self.cash),
            positions={
                symbol: OptionPosition(
                    symbol=position.symbol,
                    qty=float(position.qty),
                    avg_entry=float(position.avg_entry),
                    realized_pnl=float(position.realized_pnl),
                    premium_currency=position.premium_currency,
                    settlement_currency=position.settlement_currency,
                    multiplier=float(position.multiplier),
                    realized_pnl_by_currency=dict(position.realized_pnl_by_currency),
                )
                for symbol, position in self.positions.items()
            },
            realized_pnl=dict(self.realized_pnl),
            fees=dict(self.fees),
            settlement_cashflows=dict(self.settlement_cashflows),
            margin_locked=dict(self.margin_locked),
            events=[dict(event) for event in self.events],
            settled_symbols=set(self.settled_symbols),
        )

    def apply_fill(
        self,
        fill: Fill,
        instrument: OptionInstrumentSpec,
        *,
        fee: Optional[OptionFeeResult] = None,
        timestamp_ns: Optional[int] = None,
    ) -> None:
        """Apply premium cashflow, fee, position quantity, and realized PnL."""
        if fill.symbol != instrument.symbol:
            raise ValueError("fill symbol must match instrument")
        if fill.symbol in self.settled_symbols:
            raise ValueError(f"{fill.symbol} has already been settled")
        finite_number(fill.qty, "fill.qty", positive=True)
        finite_number(fill.price, "fill.price", positive=True)
        finite_number(fill.fee, "fill.fee", minimum=0.0)
        finite_number(instrument.multiplier, "multiplier", positive=True)
        event_time = int(timestamp_ns if timestamp_ns is not None else fill.timestamp)
        if event_time != int(fill.timestamp):
            raise ValueError("ledger timestamp must match effective fill timestamp")
        premium_currency = instrument.premium_currency
        fee_amount = finite_number(fee.fee if fee is not None else fill.fee, "applied fee", minimum=0.0)
        fee_currency = fee.currency if fee is not None else premium_currency
        premium = finite_number(float(fill.qty) * float(fill.price) * float(instrument.multiplier), "premium")
        premium_cash_delta = premium if fill.side is OrderSide.SELL else -premium
        cash = dict(self.cash)
        cash[premium_currency] = finite_number(cash.get(premium_currency, 0.0) + premium_cash_delta, "cash after premium")
        fees = dict(self.fees)
        if fee_amount:
            cash[fee_currency] = finite_number(cash.get(fee_currency, 0.0) - fee_amount, "cash after fee")
            fees[fee_currency] = finite_number(fees.get(fee_currency, 0.0) + fee_amount, "total fees")
        previous = self.positions.get(fill.symbol)
        position = replace(previous, realized_pnl_by_currency=dict(previous.realized_pnl_by_currency)) if previous is not None else OptionPosition(
            symbol=fill.symbol,
            premium_currency=premium_currency,
            settlement_currency=instrument.settlement_currency,
            multiplier=instrument.multiplier,
        )
        realized = self._apply_position(fill, instrument, position)
        realized_pnl = dict(self.realized_pnl)
        if realized:
            realized_pnl[premium_currency] = finite_number(realized_pnl.get(premium_currency, 0.0) + realized, "realized_pnl")
            position.realized_pnl_by_currency[premium_currency] = finite_number(
                position.realized_pnl_by_currency.get(premium_currency, 0.0) + realized, "position realized_pnl"
            )
        for name in ("qty", "avg_entry", "realized_pnl"):
            finite_number(getattr(position, name), f"position.{name}")
        self.cash = cash
        self.fees = fees
        self.realized_pnl = realized_pnl
        self.positions[fill.symbol] = position
        self.events.append(
            {
                "timestamp_ns": event_time,
                "quote_timestamp_ns": fill.metadata.get("quote_timestamp_ns"),
                "decision_timestamp_ns": fill.metadata.get("decision_timestamp_ns", event_time),
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
                "realized_pnl_by_currency": {premium_currency: float(realized)},
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
        finite_number(settlement_price, "settlement_price", positive=True)
        finite_number(payoff_per_unit, "payoff_per_unit", minimum=0.0)
        finite_number(instrument.multiplier, "multiplier", positive=True)
        timestamp_ns = int(timestamp_ns)
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
                    "realized_pnl_by_currency": {},
                    "representation": representation,
                    "position_closed": True,
                    "cash_after": dict(self.cash),
                }
            )
            return 0.0
        cashflow = finite_number(float(position.qty) * float(payoff_per_unit) * float(instrument.multiplier), "settlement cashflow")
        basis = finite_number(float(position.qty) * float(position.avg_entry) * float(instrument.multiplier), "remaining entry basis")
        premium_currency = instrument.premium_currency
        settlement_currency = instrument.settlement_currency
        realized = {premium_currency: -basis}
        realized[settlement_currency] = finite_number(realized.get(settlement_currency, 0.0) + cashflow, "settlement realized_pnl")
        cash_after = finite_number(self.cash.get(settlement_currency, 0.0) + cashflow, "cash after settlement")
        settlement_total = finite_number(self.settlement_cashflows.get(settlement_currency, 0.0) + cashflow, "total settlement cashflow")
        totals = dict(self.realized_pnl)
        position_totals = dict(position.realized_pnl_by_currency)
        for currency, amount in realized.items():
            totals[currency] = finite_number(totals.get(currency, 0.0) + amount, "total realized_pnl")
            position_totals[currency] = finite_number(position_totals.get(currency, 0.0) + amount, "position realized_pnl")
        scalar_realized = finite_number(position.realized_pnl + realized[premium_currency], "position realized_pnl")
        self.cash[settlement_currency] = cash_after
        self.settlement_cashflows[settlement_currency] = settlement_total
        self.realized_pnl = totals
        position.realized_pnl_by_currency = position_totals
        position.realized_pnl = scalar_realized
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
                "entry_cost_basis": basis,
                "premium_currency": premium_currency,
                "realized_pnl": realized[premium_currency] if premium_currency == settlement_currency else None,
                "realized_pnl_by_currency": realized,
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
            total = finite_number(total + finite_number(amount, f"cash[{currency}]") * _conversion_rate(currency, conversion_rates, reporting_currency), "cash equity")
        for symbol, position in self.positions.items():
            finite_number(position.qty, f"position[{symbol}]")
            if position.is_flat:
                continue
            if not marks or symbol not in marks:
                raise ValueError(f"missing mark for {symbol}")
            if not instruments or symbol not in instruments:
                raise ValueError(f"missing instrument for {symbol}")
            instrument = instruments[symbol]
            total += (
                float(position.qty)
                * finite_number(marks[symbol], f"mark[{symbol}]", minimum=0.0)
                * finite_number(instrument.multiplier, f"multiplier[{symbol}]", positive=True)
                * _conversion_rate(instrument.premium_currency, conversion_rates, reporting_currency)
            )
        return finite_number(total, "equity")

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
        finite_number(cash_equity, "cash_equity")
        mark_equity = finite_number(equity - cash_equity, "mark_equity")
        for name, amounts in (("fees", self.fees), ("realized_pnl", self.realized_pnl), ("settlement_cashflows", self.settlement_cashflows), ("margin_locked", self.margin_locked)):
            currency_amounts(amounts, name)
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
            "reconciliation_scope": "finite_cash_plus_mark_valuation_not_independent_account_replay",
        }

    def event_report(self) -> pd.DataFrame:
        return pd.DataFrame(self.events)

    def _apply_position(self, fill: Fill, instrument: OptionInstrumentSpec, position: OptionPosition) -> float:
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
