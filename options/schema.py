"""
Option domain schema.

These objects are deliberately dependency-free and do not import Nautilus. They
describe instrument conventions and registry signatures; they do not perform
pricing, execution, or ledger accounting.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Iterable, Optional, Tuple

from ..core.schema import AssetType, InstrumentSpec


class OptionKind(str, Enum):
    CALL = "call"
    PUT = "put"


class ExerciseStyle(str, Enum):
    EUROPEAN = "european"
    AMERICAN = "american"


class PremiumConvention(str, Enum):
    LINEAR_QUOTE = "linear_quote"
    INVERSE_BASE = "inverse_base"
    QUANTO = "quanto"


class SettlementStyle(str, Enum):
    CASH = "cash"
    FUTURE_THEN_CASH = "future_then_cash"
    PHYSICAL = "physical"


class OptionDecisionFillPolicy(str, Enum):
    NEXT_SNAPSHOT = "next_snapshot"
    SAME_SNAPSHOT_AFTER_SIGNAL = "same_snapshot_after_signal"
    NEXT_BAR_OPEN = "next_bar_open"
    EXPLICIT_EVENT_SEQUENCE = "explicit_event_sequence"


@dataclass(frozen=True, kw_only=True)
class OptionInstrumentSpec(InstrumentSpec):
    """
    Option instrument definition with explicit quote/settlement conventions.

    `contract_size` remains the generic QuantBT multiplier field. `multiplier`
    is kept as an option-domain alias for readability; both must match.

    `lot_size` remains the generic QuantBT quantity increment field. `qty_step`
    is kept as an option-domain alias because options venues usually describe
    order precision this way. If either is supplied, both are normalized to the
    same value.
    """

    asset_type: AssetType = AssetType.OPTION
    venue: str
    underlying_id: str
    underlying_index_id: str
    option_kind: OptionKind
    exercise_style: ExerciseStyle
    premium_convention: PremiumConvention
    settlement_style: SettlementStyle
    strike: float
    expiry_ns: int
    settlement_currency: str
    premium_currency: str
    quote_currency: str
    multiplier: float = 1.0
    qty_step: float = 0.0
    settlement_time_ns: Optional[int] = None
    fee_schedule_id: str = ""
    margin_schedule_id: str = ""
    convention_version: str = ""
    metadata: Dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "asset_type", _coerce_enum(AssetType, self.asset_type, "asset_type"))
        object.__setattr__(self, "option_kind", _coerce_enum(OptionKind, self.option_kind, "option_kind"))
        object.__setattr__(self, "exercise_style", _coerce_enum(ExerciseStyle, self.exercise_style, "exercise_style"))
        object.__setattr__(
            self,
            "premium_convention",
            _coerce_enum(PremiumConvention, self.premium_convention, "premium_convention"),
        )
        object.__setattr__(
            self,
            "settlement_style",
            _coerce_enum(SettlementStyle, self.settlement_style, "settlement_style"),
        )
        super().__post_init__()
        if self.asset_type is not AssetType.OPTION:
            raise ValueError("OptionInstrumentSpec.asset_type must be OPTION")
        if not self.venue:
            raise ValueError("venue is required")
        if not self.underlying_id or not self.underlying_index_id:
            raise ValueError("underlying identifiers are required")
        if self.strike <= 0.0:
            raise ValueError("strike must be > 0")
        if int(self.expiry_ns) <= 0:
            raise ValueError("expiry_ns must be > 0")
        object.__setattr__(self, "expiry_ns", int(self.expiry_ns))
        if self.settlement_time_ns is not None and int(self.settlement_time_ns) <= 0:
            raise ValueError("settlement_time_ns must be > 0")
        if self.settlement_time_ns is not None:
            object.__setattr__(self, "settlement_time_ns", int(self.settlement_time_ns))
        if self.multiplier <= 0.0:
            raise ValueError("multiplier must be > 0")
        if abs(float(self.multiplier) - float(self.contract_size)) > 1e-15:
            raise ValueError("multiplier must match contract_size")
        if self.qty_step < 0.0:
            raise ValueError("qty_step must be >= 0")
        _normalize_quantity_step_alias(self)
        for field_name in ("settlement_currency", "premium_currency", "quote_currency"):
            value = getattr(self, field_name)
            if not value:
                raise ValueError(f"{field_name} is required")
            object.__setattr__(self, field_name, str(value).upper())
        object.__setattr__(self, "venue", str(self.venue).lower().strip())
        object.__setattr__(self, "underlying_id", str(self.underlying_id).strip())
        object.__setattr__(self, "underlying_index_id", str(self.underlying_index_id).strip())
        _validate_convention_currency_contract(self)

    @property
    def convention_signature_tuple(self) -> Tuple:
        return (
            self.symbol,
            self.venue,
            self.underlying_id,
            self.option_kind.value,
            self.exercise_style.value,
            self.premium_convention.value,
            self.settlement_style.value,
            float(self.strike),
            int(self.expiry_ns),
            self.premium_currency,
            self.settlement_currency,
            self.quote_currency,
            float(self.multiplier),
            float(self.qty_step),
            self.fee_schedule_id,
            self.margin_schedule_id,
            self.convention_version,
        )


@dataclass(frozen=True)
class InstrumentRegistrySignature:
    count: int
    symbols: Tuple[str, ...]
    convention_versions: Tuple[str, ...]
    signature: Tuple[Tuple, ...]


@dataclass(frozen=True)
class OptionInstrumentRegistry:
    instruments: Tuple[OptionInstrumentSpec, ...]

    def __post_init__(self) -> None:
        if not self.instruments:
            raise ValueError("OptionInstrumentRegistry requires at least one instrument")
        symbols = [instrument.symbol for instrument in self.instruments]
        if len(symbols) != len(set(symbols)):
            raise ValueError("option instrument symbols must be unique")

    @classmethod
    def from_iterable(cls, instruments: Iterable[OptionInstrumentSpec]) -> "OptionInstrumentRegistry":
        return cls(tuple(instruments))

    @property
    def symbols(self) -> Tuple[str, ...]:
        return tuple(instrument.symbol for instrument in self.instruments)

    @property
    def by_symbol(self) -> Dict[str, OptionInstrumentSpec]:
        return {instrument.symbol: instrument for instrument in self.instruments}

    @property
    def signature(self) -> InstrumentRegistrySignature:
        ordered = tuple(sorted((instrument.convention_signature_tuple for instrument in self.instruments), key=lambda row: row[0]))
        return InstrumentRegistrySignature(
            count=len(ordered),
            symbols=tuple(row[0] for row in ordered),
            convention_versions=tuple(row[-1] for row in ordered),
            signature=ordered,
        )


def _coerce_enum(enum_cls, value, field_name: str):
    if isinstance(value, enum_cls):
        return value
    try:
        return enum_cls(str(value))
    except ValueError as exc:
        raise ValueError(f"{field_name} must be one of {[item.value for item in enum_cls]}") from exc


def _validate_convention_currency_contract(spec: OptionInstrumentSpec) -> None:
    if spec.premium_convention is PremiumConvention.INVERSE_BASE:
        if spec.premium_currency != spec.settlement_currency:
            raise ValueError("inverse options require premium_currency == settlement_currency")
        if spec.quote_currency == spec.premium_currency:
            raise ValueError("inverse options require quote_currency distinct from premium currency")
    elif spec.premium_convention is PremiumConvention.LINEAR_QUOTE:
        if spec.premium_currency != spec.quote_currency:
            raise ValueError("linear quote options require premium_currency == quote_currency")
        if spec.settlement_style is SettlementStyle.PHYSICAL:
            raise ValueError("linear quote options cannot use physical settlement in Phase 1 schema")
    elif spec.premium_convention is PremiumConvention.QUANTO:
        if spec.premium_currency == spec.settlement_currency == spec.quote_currency:
            raise ValueError("quanto options require at least one distinct premium/settlement/quote currency")


def _normalize_quantity_step_alias(spec: OptionInstrumentSpec) -> None:
    lot_size = float(spec.lot_size)
    qty_step = float(spec.qty_step)
    if lot_size > 0.0 and qty_step > 0.0 and abs(lot_size - qty_step) > 1e-15:
        raise ValueError("qty_step must match lot_size when both are provided")
    if qty_step <= 0.0 and lot_size > 0.0:
        object.__setattr__(spec, "qty_step", lot_size)
    elif lot_size <= 0.0 and qty_step > 0.0:
        object.__setattr__(spec, "lot_size", qty_step)
