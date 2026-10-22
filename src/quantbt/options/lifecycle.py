"""
Option lifecycle and expiry settlement.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Union

from .ledger import OptionLedger
from .schema import OptionInstrumentSpec, OptionKind, PremiumConvention, SettlementStyle
from .validation import finite_number


class OptionSettlementRepresentation(str, Enum):
    ECONOMIC_CASH = "economic_cash"
    FUTURE_THEN_CASH = "future_then_cash"


@dataclass(frozen=True)
class OptionSettlementResult:
    symbol: str
    timestamp_ns: int
    settlement_price: float
    payoff_per_unit: float
    cashflow: float
    settlement_currency: str
    representation: OptionSettlementRepresentation
    itm: bool
    position_closed: bool
    realized_pnl_by_currency: dict[str, float] = field(default_factory=dict)


def option_expiry_payoff_per_unit(instrument: OptionInstrumentSpec, settlement_price: float) -> float:
    """Return payoff per 1 option unit in the instrument settlement currency."""
    price = finite_number(settlement_price, "settlement_price", positive=True)
    strike = float(instrument.strike)
    if instrument.option_kind is OptionKind.CALL:
        intrinsic_quote = max(price - strike, 0.0)
    else:
        intrinsic_quote = max(strike - price, 0.0)
    if instrument.premium_convention is PremiumConvention.INVERSE_BASE:
        return intrinsic_quote / price
    if instrument.premium_convention is PremiumConvention.LINEAR_QUOTE:
        return intrinsic_quote
    raise NotImplementedError("quanto option expiry payoff is not implemented in Phase 5")


def settle_option_expiry(
    ledger: OptionLedger,
    instrument: OptionInstrumentSpec,
    *,
    timestamp_ns: int,
    settlement_price: float,
    representation: Union[OptionSettlementRepresentation, str, None] = None,
) -> OptionSettlementResult:
    """Settle an option position and close it exactly once."""
    rep = _resolve_representation(instrument, representation)
    payoff = option_expiry_payoff_per_unit(instrument, settlement_price)
    cashflow = ledger.apply_settlement(
        instrument,
        timestamp_ns=int(timestamp_ns),
        settlement_price=float(settlement_price),
        payoff_per_unit=payoff,
        representation=rep.value,
    )
    return OptionSettlementResult(
        symbol=instrument.symbol,
        timestamp_ns=int(timestamp_ns),
        settlement_price=float(settlement_price),
        payoff_per_unit=float(payoff),
        cashflow=float(cashflow),
        settlement_currency=instrument.settlement_currency,
        representation=rep,
        itm=bool(payoff > 0.0),
        position_closed=True,
        realized_pnl_by_currency=dict(ledger.events[-1].get("realized_pnl_by_currency", {})),
    )


def _resolve_representation(
    instrument: OptionInstrumentSpec,
    representation: Union[OptionSettlementRepresentation, str, None],
) -> OptionSettlementRepresentation:
    if representation is not None:
        if isinstance(representation, OptionSettlementRepresentation):
            return representation
        try:
            return OptionSettlementRepresentation(str(representation))
        except ValueError as exc:
            raise ValueError("invalid settlement representation") from exc
    if instrument.settlement_style is SettlementStyle.FUTURE_THEN_CASH:
        return OptionSettlementRepresentation.FUTURE_THEN_CASH
    return OptionSettlementRepresentation.ECONOMIC_CASH
