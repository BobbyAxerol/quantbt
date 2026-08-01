"""
Versioned option venue conventions.

These conventions are descriptive configuration, not a pricing engine and not a
claim that venue portfolio margin is exactly replicated.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Tuple

from .schema import ExerciseStyle, PremiumConvention, SettlementStyle


@dataclass(frozen=True)
class OptionVenueConvention:
    venue: str
    convention_id: str
    premium_convention: PremiumConvention
    exercise_style: ExerciseStyle
    settlement_style: SettlementStyle
    premium_currency: str
    settlement_currency: str
    quote_currency: str
    supported_underlyings: Tuple[str, ...] = ()
    fee_schedule_id: str = ""
    margin_schedule_id: str = ""
    exact_venue_margin: bool = False
    notes: str = ""
    metadata: Dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "venue", str(self.venue).lower().strip())
        object.__setattr__(self, "premium_convention", _coerce(PremiumConvention, self.premium_convention, "premium_convention"))
        object.__setattr__(self, "exercise_style", _coerce(ExerciseStyle, self.exercise_style, "exercise_style"))
        object.__setattr__(self, "settlement_style", _coerce(SettlementStyle, self.settlement_style, "settlement_style"))
        if not self.venue or not self.convention_id:
            raise ValueError("venue and convention_id are required")
        for field_name in ("premium_currency", "settlement_currency", "quote_currency"):
            value = getattr(self, field_name)
            if not value:
                raise ValueError(f"{field_name} is required")
            object.__setattr__(self, field_name, str(value).upper())
        object.__setattr__(self, "supported_underlyings", tuple(str(value).upper() for value in self.supported_underlyings))
        _validate_convention(self)

    @property
    def signature(self) -> Tuple:
        return (
            self.venue,
            self.convention_id,
            self.premium_convention.value,
            self.exercise_style.value,
            self.settlement_style.value,
            self.premium_currency,
            self.settlement_currency,
            self.quote_currency,
            self.supported_underlyings,
            self.fee_schedule_id,
            self.margin_schedule_id,
            bool(self.exact_venue_margin),
        )


def deribit_inverse_option_convention(
    *,
    underlying: str = "BTC",
    version: str = "deribit_inverse_v1",
) -> OptionVenueConvention:
    base = str(underlying).upper()
    if base not in {"BTC", "ETH"}:
        raise ValueError("Deribit inverse convention currently supports BTC or ETH")
    return OptionVenueConvention(
        venue="deribit",
        convention_id=version,
        premium_convention=PremiumConvention.INVERSE_BASE,
        exercise_style=ExerciseStyle.EUROPEAN,
        settlement_style=SettlementStyle.CASH,
        premium_currency=base,
        settlement_currency=base,
        quote_currency="USD",
        supported_underlyings=(base,),
        fee_schedule_id=f"deribit_{base.lower()}_inverse_options",
        margin_schedule_id="deribit_pm_external_or_scenario_approximation",
        exact_venue_margin=False,
        notes="Inverse premium and settlement are in base currency; native margin is approximation unless validated externally.",
    )


def deribit_linear_usdc_option_convention(
    *,
    underlying: str = "BTC",
    version: str = "deribit_linear_usdc_v1",
    settlement_style: SettlementStyle = SettlementStyle.FUTURE_THEN_CASH,
) -> OptionVenueConvention:
    base = str(underlying).upper()
    return OptionVenueConvention(
        venue="deribit",
        convention_id=version,
        premium_convention=PremiumConvention.LINEAR_QUOTE,
        exercise_style=ExerciseStyle.EUROPEAN,
        settlement_style=settlement_style,
        premium_currency="USDC",
        settlement_currency="USDC",
        quote_currency="USDC",
        supported_underlyings=(base,),
        fee_schedule_id="deribit_linear_usdc_options",
        margin_schedule_id="deribit_pm_external_or_scenario_approximation",
        exact_venue_margin=False,
        notes="Linear USDC option convention supports economic cash or future-then-cash settlement representation.",
    )


def binance_european_options_convention(
    *,
    underlying: str = "BTC",
    version: str = "binance_european_options_v1",
) -> OptionVenueConvention:
    base = str(underlying).upper()
    return OptionVenueConvention(
        venue="binance",
        convention_id=version,
        premium_convention=PremiumConvention.LINEAR_QUOTE,
        exercise_style=ExerciseStyle.EUROPEAN,
        settlement_style=SettlementStyle.CASH,
        premium_currency="USDT",
        settlement_currency="USDT",
        quote_currency="USDT",
        supported_underlyings=(base,),
        fee_schedule_id="binance_options_versioned_external",
        margin_schedule_id="binance_options_external_or_scenario_approximation",
        exact_venue_margin=False,
        notes="Binance config is schema/convention metadata only until official fee/margin parity tests are added.",
    )


def _coerce(enum_cls, value, field_name: str):
    if isinstance(value, enum_cls):
        return value
    try:
        return enum_cls(str(value))
    except ValueError as exc:
        raise ValueError(f"{field_name} must be one of {[item.value for item in enum_cls]}") from exc


def _validate_convention(convention: OptionVenueConvention) -> None:
    if convention.premium_convention is PremiumConvention.INVERSE_BASE:
        if convention.premium_currency != convention.settlement_currency:
            raise ValueError("inverse convention requires premium_currency == settlement_currency")
        if convention.quote_currency == convention.premium_currency:
            raise ValueError("inverse convention requires quote_currency distinct from base premium currency")
    elif convention.premium_convention is PremiumConvention.LINEAR_QUOTE:
        if convention.premium_currency != convention.quote_currency:
            raise ValueError("linear convention requires premium_currency == quote_currency")
    elif convention.premium_convention is PremiumConvention.QUANTO:
        if convention.premium_currency == convention.settlement_currency == convention.quote_currency:
            raise ValueError("quanto convention requires at least one distinct currency")
