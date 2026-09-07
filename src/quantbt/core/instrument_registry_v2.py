"""Canonical instrument rules for V1.1 certified execution routes.

This registry is deliberately an adapter around the established
``InstrumentSpec``/``PreparedInstrumentTable`` surface.  It consolidates the
source of truth without renaming public endpoint arguments that existing
notebooks still use.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from hashlib import sha256
import json
import math
from typing import Mapping, Optional, Sequence

import numpy as np

from .instrument_contracts import InstrumentRejectCode, PreparedInstrumentTable, compile_instrument_table
from .schema import AssetType, FeeModel, InstrumentSpec, OrderSide


INSTRUMENT_REGISTRY_V2_SCHEMA = "instrument-registry-v2"


class PricePurposeV2(str, Enum):
    LIMIT_BUY = "limit_buy"
    LIMIT_SELL = "limit_sell"
    STOP_BUY = "stop_buy"
    STOP_SELL = "stop_sell"
    RISK_INCREASING_BUY = "risk_increasing_buy"
    RISK_INCREASING_SELL = "risk_increasing_sell"
    RISK_REDUCING_BUY = "risk_reducing_buy"
    RISK_REDUCING_SELL = "risk_reducing_sell"
    LIQUIDATION_BUY = "liquidation_buy"
    LIQUIDATION_SELL = "liquidation_sell"
    HEDGE_BUY = "hedge_buy"
    HEDGE_SELL = "hedge_sell"


class QuantityPurposeV2(str, Enum):
    RISK_INCREASING = "risk_increasing"
    RISK_REDUCING = "risk_reducing"
    LIQUIDATION = "liquidation"
    HEDGE = "hedge"


class InstrumentValidationCodeV2(str, Enum):
    ACCEPTED = "accepted"
    INVALID_VALUE = "invalid_value"
    MIN_QTY = "min_qty"
    MAX_QTY = "max_qty"
    MIN_NOTIONAL = "min_notional"
    REDUCE_ONLY_POSITION = "reduce_only_position"


def _readonly(values, dtype) -> np.ndarray:
    array = np.ascontiguousarray(values, dtype=dtype)
    array.setflags(write=False)
    return array


def _finite_nonnegative(name: str, value: float) -> float:
    value = float(value)
    if not math.isfinite(value) or value < 0.0:
        raise ValueError(f"{name} must be finite and >= 0")
    return value


@dataclass(frozen=True, slots=True)
class InstrumentRuleV2:
    """All deterministic venue constraints for one normalized market symbol."""

    symbol: str
    symbol_id: int
    venue: str = ""
    instrument_kind: str = "crypto"
    price_tick: float = 0.0
    quantity_step: float = 0.0
    min_quantity: float = 0.0
    max_quantity: Optional[float] = None
    min_notional: float = 0.0
    contract_multiplier: float = 1.0
    leverage_limit: float = 1.0
    settlement_currency: str = "USD"
    fee_schedule_id: str = "default"
    funding_schedule_id: Optional[str] = None
    one_way_fee_rate: float = 0.0
    rounding_policy: str = "purpose_v1"

    def __post_init__(self) -> None:
        if not self.symbol:
            raise ValueError("instrument rule requires symbol")
        if int(self.symbol_id) < 0:
            raise ValueError("symbol_id must be >= 0")
        for name in ("price_tick", "quantity_step", "min_quantity", "min_notional", "one_way_fee_rate"):
            _finite_nonnegative(name, getattr(self, name))
        if self.max_quantity is not None:
            max_quantity = _finite_nonnegative("max_quantity", self.max_quantity)
            if max_quantity == 0.0:
                object.__setattr__(self, "max_quantity", None)
            elif max_quantity < self.min_quantity:
                raise ValueError("max_quantity must be >= min_quantity")
        if not math.isfinite(float(self.contract_multiplier)) or self.contract_multiplier <= 0.0:
            raise ValueError("contract_multiplier must be finite and > 0")
        if not math.isfinite(float(self.leverage_limit)) or self.leverage_limit <= 0.0:
            raise ValueError("leverage_limit must be finite and > 0")

    def quantize_price(self, raw: float, purpose: PricePurposeV2 | str) -> float:
        """Quantize price in the declared conservative direction.

        Passive limits preserve price improvement (buy down, sell up). Stops,
        risk-increasing/reducing, liquidation, and hedge references use the
        adverse direction (buy up, sell down), avoiding an accidental free
        price improvement in a certified replay.
        """
        raw = float(raw)
        if not math.isfinite(raw) or raw <= 0.0:
            raise ValueError("price must be finite and > 0")
        purpose_value = _price_purpose(purpose)
        if self.price_tick <= 0.0:
            return raw
        units = raw / self.price_tick
        if purpose_value is PricePurposeV2.LIMIT_BUY:
            ticks = math.floor(units + 1e-12)
        elif purpose_value is PricePurposeV2.LIMIT_SELL:
            ticks = math.ceil(units - 1e-12)
        elif purpose_value in {
            PricePurposeV2.STOP_BUY,
            PricePurposeV2.RISK_INCREASING_BUY,
            PricePurposeV2.RISK_REDUCING_BUY,
            PricePurposeV2.LIQUIDATION_BUY,
            PricePurposeV2.HEDGE_BUY,
        }:
            ticks = math.ceil(units - 1e-12)
        else:
            ticks = math.floor(units + 1e-12)
        quantized = float(ticks) * self.price_tick
        if quantized <= 0.0:
            raise ValueError("price quantization produced a non-positive price")
        return quantized

    def quantize_quantity(
        self,
        raw: float,
        purpose: QuantityPurposeV2 | str,
        *,
        current_position: Optional[float] = None,
        allow_close_remainder: bool = True,
    ) -> float:
        """Quantize an absolute quantity without allowing reduce-only reversal."""
        raw = abs(float(raw))
        if not math.isfinite(raw) or raw <= 0.0:
            return 0.0
        purpose_value = _quantity_purpose(purpose)
        if purpose_value is QuantityPurposeV2.RISK_REDUCING:
            if current_position is None:
                raise ValueError("risk_reducing quantization requires current_position")
            available = abs(float(current_position))
            if not math.isfinite(available) or available <= 0.0:
                return 0.0
            raw = min(raw, available)
            if allow_close_remainder and abs(raw - available) <= 1e-12:
                # Closing the remaining venue position exactly is allowed even
                # if a fractional remainder is below the normal lot step.
                return available
        if self.quantity_step <= 0.0:
            return raw
        lots = math.floor(raw / self.quantity_step + 1e-12)
        return float(lots) * self.quantity_step

    def validate(self, price: float, quantity: float) -> InstrumentValidationCodeV2:
        if not math.isfinite(float(price)) or not math.isfinite(float(quantity)) or price <= 0.0 or quantity <= 0.0:
            return InstrumentValidationCodeV2.INVALID_VALUE
        if quantity + 1e-12 < self.min_quantity:
            return InstrumentValidationCodeV2.MIN_QTY
        if self.max_quantity is not None and quantity - 1e-12 > self.max_quantity:
            return InstrumentValidationCodeV2.MAX_QTY
        if self.min_notional > 0.0 and self.cash_notional(price, quantity) + 1e-12 < self.min_notional:
            return InstrumentValidationCodeV2.MIN_NOTIONAL
        return InstrumentValidationCodeV2.ACCEPTED

    def cash_notional(self, price: float, quantity: float) -> float:
        return abs(float(price) * float(quantity) * self.contract_multiplier)

    def pnl(self, entry_price: float, exit_price: float, quantity: float, side: OrderSide | str) -> float:
        side_value = side if isinstance(side, OrderSide) else OrderSide(str(side).lower())
        direction = 1.0 if side_value is OrderSide.BUY else -1.0
        return direction * (float(exit_price) - float(entry_price)) * abs(float(quantity)) * self.contract_multiplier


@dataclass(frozen=True, slots=True)
class InstrumentRegistryV2:
    """Canonical immutable registry used by all V2 certified adapters."""

    rules: tuple[InstrumentRuleV2, ...]
    fingerprint: str
    schema: str = INSTRUMENT_REGISTRY_V2_SCHEMA

    def __post_init__(self) -> None:
        symbols = tuple(rule.symbol for rule in self.rules)
        if not symbols or symbols != tuple(sorted(symbols)):
            raise ValueError("InstrumentRegistryV2 rules must use nonempty lexicographic symbol order")
        if tuple(rule.symbol_id for rule in self.rules) != tuple(range(len(self.rules))):
            raise ValueError("InstrumentRegistryV2 symbol IDs must match normalized market columns")

    @property
    def symbols(self) -> tuple[str, ...]:
        return tuple(rule.symbol for rule in self.rules)

    def rule_for(self, symbol: str) -> InstrumentRuleV2:
        try:
            return self.rules[self.symbols.index(str(symbol))]
        except ValueError as exc:
            raise KeyError(f"instrument registry does not contain {symbol!r}") from exc

    def arrays(self) -> dict[str, np.ndarray]:
        return {
            "tick_size": _readonly([rule.price_tick for rule in self.rules], np.float64),
            "qty_step": _readonly([rule.quantity_step for rule in self.rules], np.float64),
            "min_qty": _readonly([rule.min_quantity for rule in self.rules], np.float64),
            "max_qty": _readonly([0.0 if rule.max_quantity is None else rule.max_quantity for rule in self.rules], np.float64),
            "min_notional": _readonly([rule.min_notional for rule in self.rules], np.float64),
            "contract_size": _readonly([rule.contract_multiplier for rule in self.rules], np.float64),
            "leverage": _readonly([rule.leverage_limit for rule in self.rules], np.float64),
            "fee_rate": _readonly([rule.one_way_fee_rate for rule in self.rules], np.float64),
        }

    def prepared_table(self) -> PreparedInstrumentTable:
        return compile_instrument_table(self.symbols, _legacy_specs_from_rules(self.rules))

    def metadata(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "fingerprint": self.fingerprint,
            "symbols": list(self.symbols),
            "constraints": {
                rule.symbol: {
                    "price_tick": rule.price_tick,
                    "quantity_step": rule.quantity_step,
                    "min_quantity": rule.min_quantity,
                    "max_quantity": rule.max_quantity,
                    "min_notional": rule.min_notional,
                    "contract_multiplier": rule.contract_multiplier,
                    "leverage_limit": rule.leverage_limit,
                    "one_way_fee_rate": rule.one_way_fee_rate,
                    "settlement_currency": rule.settlement_currency,
                    "fee_schedule_id": rule.fee_schedule_id,
                    "funding_schedule_id": rule.funding_schedule_id,
                }
                for rule in self.rules
            },
        }


def prepare_instrument_registry_v2(
    *,
    specs: Optional[Mapping[str, InstrumentSpec] | Sequence[InstrumentSpec]] = None,
    symbols: Optional[Sequence[str]] = None,
    contract_size: Optional[float | Mapping[str, float]] = None,
    leverage: float | Mapping[str, float] = 1.0,
    fee_rate: float | Mapping[str, float] = 0.0,
    qty_step: Optional[float | Mapping[str, float]] = None,
    min_qty: Optional[float | Mapping[str, float]] = None,
    min_notional: Optional[float | Mapping[str, float]] = None,
) -> InstrumentRegistryV2:
    """Build V2 rules from existing public instrument fields without renaming them."""
    spec_map = _spec_map(specs)
    if symbols is None:
        if not spec_map:
            raise ValueError("symbols or specs are required to prepare instruments")
        requested = tuple(spec_map)
    else:
        requested = tuple(map(str, symbols))
    if not requested or len(set(requested)) != len(requested):
        raise ValueError("instrument symbols must be nonempty and unique")
    symbol_values = tuple(sorted(requested))
    rules = []
    for symbol_id, symbol in enumerate(symbol_values):
        legacy = spec_map.get(symbol)
        if legacy is None:
            legacy = InstrumentSpec(
                symbol=symbol,
                contract_size=float(_value_for(contract_size, symbol, 1.0)),
                lot_size=float(_value_for(qty_step, symbol, 0.0)),
                min_qty=float(_value_for(min_qty, symbol, 0.0)),
                min_notional=float(_value_for(min_notional, symbol, 0.0)),
                fee_model=FeeModel(taker=float(_value_for(fee_rate, symbol, 0.0))),
            )
        metadata = dict(legacy.metadata or {})
        rule = InstrumentRuleV2(
            symbol=symbol,
            symbol_id=symbol_id,
            venue=str(metadata.get("venue", metadata.get("venue_id", ""))),
            instrument_kind=str(metadata.get("instrument_kind", legacy.asset_type.value)),
            price_tick=float(legacy.tick_size),
            quantity_step=float(_value_for(qty_step, symbol, legacy.lot_size)),
            min_quantity=float(_value_for(min_qty, symbol, legacy.min_qty)),
            max_quantity=_optional_positive(metadata.get("max_qty", metadata.get("max_quantity"))),
            min_notional=float(_value_for(min_notional, symbol, legacy.min_notional)),
            contract_multiplier=float(_value_for(contract_size, symbol, legacy.contract_size)),
            leverage_limit=float(_value_for(leverage, symbol, metadata.get("leverage_limit", 1.0))),
            settlement_currency=str(metadata.get("settlement_currency", metadata.get("settlement", "USD"))),
            fee_schedule_id=str(metadata.get("fee_schedule_id", "default")),
            funding_schedule_id=(None if metadata.get("funding_schedule_id") is None else str(metadata["funding_schedule_id"])),
            one_way_fee_rate=float(_value_for(fee_rate, symbol, legacy.fee_model.taker)),
            rounding_policy=str(metadata.get("rounding_policy", "purpose_v1")),
        )
        rules.append(rule)
    fingerprint = _registry_fingerprint(tuple(rules))
    return InstrumentRegistryV2(rules=tuple(rules), fingerprint=fingerprint)


def _price_purpose(value: PricePurposeV2 | str) -> PricePurposeV2:
    if isinstance(value, PricePurposeV2):
        return value
    aliases = {
        "limit_buy": PricePurposeV2.LIMIT_BUY,
        "limit_sell": PricePurposeV2.LIMIT_SELL,
        "stop_buy": PricePurposeV2.STOP_BUY,
        "stop_sell": PricePurposeV2.STOP_SELL,
        "risk_increasing_buy": PricePurposeV2.RISK_INCREASING_BUY,
        "risk_increasing_sell": PricePurposeV2.RISK_INCREASING_SELL,
        "risk_reducing_buy": PricePurposeV2.RISK_REDUCING_BUY,
        "risk_reducing_sell": PricePurposeV2.RISK_REDUCING_SELL,
        "liquidation_buy": PricePurposeV2.LIQUIDATION_BUY,
        "liquidation_sell": PricePurposeV2.LIQUIDATION_SELL,
        "hedge_buy": PricePurposeV2.HEDGE_BUY,
        "hedge_sell": PricePurposeV2.HEDGE_SELL,
    }
    try:
        return aliases[str(value).lower().strip()]
    except KeyError as exc:
        raise ValueError(f"unsupported price purpose {value!r}") from exc


def _quantity_purpose(value: QuantityPurposeV2 | str) -> QuantityPurposeV2:
    if isinstance(value, QuantityPurposeV2):
        return value
    try:
        return QuantityPurposeV2(str(value).lower().strip())
    except ValueError as exc:
        raise ValueError(f"unsupported quantity purpose {value!r}") from exc


def _spec_map(specs) -> dict[str, InstrumentSpec]:
    if specs is None:
        return {}
    if isinstance(specs, Mapping):
        return {str(symbol): spec for symbol, spec in specs.items()}
    return {str(spec.symbol): spec for spec in specs}


def _value_for(value, symbol: str, default: float) -> float:
    if value is None:
        return float(default)
    if isinstance(value, Mapping):
        return float(value.get(symbol, default))
    return float(value)


def _optional_positive(value) -> Optional[float]:
    if value is None:
        return None
    numeric = float(value)
    return None if numeric <= 0.0 else numeric


def _legacy_specs_from_rules(rules: Sequence[InstrumentRuleV2]) -> dict[str, InstrumentSpec]:
    out: dict[str, InstrumentSpec] = {}
    for rule in rules:
        try:
            asset_type = AssetType(rule.instrument_kind)
        except ValueError:
            asset_type = AssetType.CRYPTO
        out[rule.symbol] = InstrumentSpec(
            symbol=rule.symbol,
            asset_type=asset_type,
            contract_size=rule.contract_multiplier,
            tick_size=rule.price_tick,
            lot_size=rule.quantity_step,
            min_qty=rule.min_quantity,
            min_notional=rule.min_notional,
            fee_model=FeeModel(taker=rule.one_way_fee_rate),
            metadata={
                "venue": rule.venue,
                "max_qty": rule.max_quantity or 0.0,
                "settlement_currency": rule.settlement_currency,
                "fee_schedule_id": rule.fee_schedule_id,
                "funding_schedule_id": rule.funding_schedule_id,
                "rounding_policy": rule.rounding_policy,
            },
        )
    return out


def _registry_fingerprint(rules: Sequence[InstrumentRuleV2]) -> str:
    payload = {
        "schema": INSTRUMENT_REGISTRY_V2_SCHEMA,
        "rules": [
            {
                "symbol": rule.symbol,
                "symbol_id": rule.symbol_id,
                "venue": rule.venue,
                "instrument_kind": rule.instrument_kind,
                "price_tick": rule.price_tick,
                "quantity_step": rule.quantity_step,
                "min_quantity": rule.min_quantity,
                "max_quantity": rule.max_quantity,
                "min_notional": rule.min_notional,
                "contract_multiplier": rule.contract_multiplier,
                "leverage_limit": rule.leverage_limit,
                "settlement_currency": rule.settlement_currency,
                "fee_schedule_id": rule.fee_schedule_id,
                "funding_schedule_id": rule.funding_schedule_id,
                "one_way_fee_rate": rule.one_way_fee_rate,
                "rounding_policy": rule.rounding_policy,
            }
            for rule in rules
        ],
    }
    return sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


__all__ = [
    "INSTRUMENT_REGISTRY_V2_SCHEMA",
    "InstrumentRegistryV2",
    "InstrumentRuleV2",
    "InstrumentValidationCodeV2",
    "PricePurposeV2",
    "QuantityPurposeV2",
    "prepare_instrument_registry_v2",
]
