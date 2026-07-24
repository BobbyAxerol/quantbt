"""
Option fee schedules.

Phase 5 implements deterministic per-leg capped fees. There is intentionally no
package-level cap because real venues cap option fees per contract/leg.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Union

from ..core.orders import Fill
from ..core.schema import LiquiditySide
from .schema import OptionInstrumentSpec, PremiumConvention


@dataclass(frozen=True)
class OptionFeeResult:
    fee: float
    currency: str
    raw_fee: float
    cap: float
    capped: bool
    schedule_id: str


@dataclass(frozen=True)
class OptionFeeSchedule:
    schedule_id: str
    fee_currency: str
    maker_rate: float = 0.0
    taker_rate: float = 0.0
    cap_premium_fraction: float = 0.125
    per_contract_fee: float = 0.0
    premium_convention: Union[PremiumConvention, str] = PremiumConvention.LINEAR_QUOTE

    def __post_init__(self) -> None:
        object.__setattr__(self, "premium_convention", _coerce_premium(self.premium_convention))
        object.__setattr__(self, "fee_currency", str(self.fee_currency).upper())
        if not self.schedule_id:
            raise ValueError("schedule_id is required")
        if not self.fee_currency:
            raise ValueError("fee_currency is required")
        if self.maker_rate < 0.0 or self.taker_rate < 0.0:
            raise ValueError("maker_rate and taker_rate must be >= 0")
        if self.cap_premium_fraction < 0.0:
            raise ValueError("cap_premium_fraction must be >= 0")
        if self.per_contract_fee < 0.0:
            raise ValueError("per_contract_fee must be >= 0")

    def rate_for(self, liquidity: LiquiditySide) -> float:
        return self.maker_rate if liquidity is LiquiditySide.MAKER else self.taker_rate


def deribit_inverse_fee_schedule(
    *,
    base_currency: str = "BTC",
    per_contract_fee: float = 0.0003,
    cap_premium_fraction: float = 0.125,
) -> OptionFeeSchedule:
    return OptionFeeSchedule(
        schedule_id=f"deribit_{base_currency.lower()}_inverse_options_phase5",
        fee_currency=base_currency,
        per_contract_fee=per_contract_fee,
        cap_premium_fraction=cap_premium_fraction,
        premium_convention=PremiumConvention.INVERSE_BASE,
    )


def deribit_linear_usdc_fee_schedule(
    *,
    taker_rate: float = 0.0003,
    maker_rate: float = 0.0003,
    cap_premium_fraction: float = 0.125,
) -> OptionFeeSchedule:
    return OptionFeeSchedule(
        schedule_id="deribit_linear_usdc_options_phase5",
        fee_currency="USDC",
        maker_rate=maker_rate,
        taker_rate=taker_rate,
        cap_premium_fraction=cap_premium_fraction,
        premium_convention=PremiumConvention.LINEAR_QUOTE,
    )


def calculate_option_fee(
    fill: Fill,
    instrument: OptionInstrumentSpec,
    schedule: OptionFeeSchedule,
    *,
    reference_price: float,
) -> OptionFeeResult:
    """
    Calculate a per-leg capped option fee.

    For inverse options the common venue-like form is a base-currency fee per
    contract capped by a fraction of option premium. For linear options the raw
    fee is reference notional times rate, also capped by option premium.
    """
    if schedule.premium_convention != instrument.premium_convention:
        raise ValueError("fee schedule premium convention does not match instrument")
    if schedule.fee_currency != instrument.premium_currency:
        raise ValueError("fee schedule currency must match option premium currency in Phase 5")
    if reference_price <= 0.0:
        raise ValueError("reference_price must be > 0")
    premium_notional = float(fill.qty) * float(fill.price) * float(instrument.multiplier)
    cap = premium_notional * float(schedule.cap_premium_fraction)
    if instrument.premium_convention is PremiumConvention.INVERSE_BASE:
        raw_fee = float(fill.qty) * float(instrument.multiplier) * float(schedule.per_contract_fee)
    else:
        raw_fee = (
            float(fill.qty)
            * float(instrument.multiplier)
            * float(reference_price)
            * float(schedule.rate_for(fill.liquidity))
        )
    fee = min(raw_fee, cap) if schedule.cap_premium_fraction > 0.0 else raw_fee
    return OptionFeeResult(
        fee=float(fee),
        currency=schedule.fee_currency,
        raw_fee=float(raw_fee),
        cap=float(cap),
        capped=bool(fee < raw_fee),
        schedule_id=schedule.schedule_id,
    )


def _coerce_premium(value: Union[PremiumConvention, str]) -> PremiumConvention:
    if isinstance(value, PremiumConvention):
        return value
    try:
        return PremiumConvention(str(value))
    except ValueError as exc:
        raise ValueError("premium_convention is invalid") from exc
