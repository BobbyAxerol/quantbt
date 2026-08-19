"""Prepared instrument table and deterministic venue quantization policy."""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from hashlib import sha256
import json
from typing import Mapping, Sequence

import numpy as np

from .schema import AssetType, InstrumentSpec, OrderSide, OrderType


INSTRUMENT_TABLE_SCHEMA_VERSION = "prepared-instrument-table-v1"
NUMERIC_POLICY_VERSION = "deterministic-f64-ticks-v1"


class InstrumentRejectCode(IntEnum):
    ACCEPTED = 0
    INVALID_VALUE = 1
    MIN_QTY = 2
    MAX_QTY = 3
    MIN_NOTIONAL = 4
    UNSUPPORTED_CONTRACT = 5


@dataclass(frozen=True, slots=True)
class QuantizedOrderValue:
    price: float
    qty: float
    price_ticks: int
    qty_lots: int
    reject_code: InstrumentRejectCode

    @property
    def accepted(self) -> bool:
        return self.reject_code is InstrumentRejectCode.ACCEPTED


@dataclass(frozen=True)
class PreparedInstrumentTable:
    symbols: tuple[str, ...]
    symbol_code: np.ndarray
    venue_code: np.ndarray
    contract_type: np.ndarray
    tick_size: np.ndarray
    qty_step: np.ndarray
    min_qty: np.ndarray
    max_qty: np.ndarray
    min_notional: np.ndarray
    contract_size: np.ndarray
    price_scale: np.ndarray
    qty_scale: np.ndarray
    settlement_code: np.ndarray
    fee_model_id: np.ndarray
    margin_model_id: np.ndarray
    venue_values: tuple[str, ...]
    settlement_values: tuple[str, ...]
    fingerprint: str

    def __post_init__(self) -> None:
        for name in (
            "symbol_code", "venue_code", "contract_type", "tick_size", "qty_step",
            "min_qty", "max_qty", "min_notional", "contract_size", "price_scale",
            "qty_scale", "settlement_code", "fee_model_id", "margin_model_id",
        ):
            array = np.ascontiguousarray(getattr(self, name))
            array.setflags(write=False)
            object.__setattr__(self, name, array)

    @property
    def n_symbols(self) -> int:
        return len(self.symbols)

    def quantize(
        self,
        symbol: str,
        *,
        side: OrderSide | str,
        order_type: OrderType | str,
        price: float,
        qty: float,
    ) -> QuantizedOrderValue:
        try:
            col = self.symbols.index(str(symbol))
        except ValueError as exc:
            raise KeyError(f"unknown instrument symbol={symbol!r}") from exc
        return quantize_order_value(
            side=side,
            order_type=order_type,
            price=price,
            qty=qty,
            tick_size=float(self.tick_size[col]),
            qty_step=float(self.qty_step[col]),
            min_qty=float(self.min_qty[col]),
            max_qty=float(self.max_qty[col]),
            min_notional=float(self.min_notional[col]),
            contract_size=float(self.contract_size[col]),
        )


def compile_instrument_table(
    symbols: Sequence[str],
    instruments: Mapping[str, InstrumentSpec] | Sequence[InstrumentSpec] | None = None,
    *,
    default_contract_size: float = 1.0,
    default_venue: str = "SIM",
    default_settlement: str = "USD",
    fee_model_id: int | Mapping[str, int] = 0,
    margin_model_id: int | Mapping[str, int] = 0,
) -> PreparedInstrumentTable:
    """Compile Python instrument objects into immutable contiguous columns."""

    symbol_values = tuple(map(str, symbols))
    if len(symbol_values) != len(set(symbol_values)):
        raise ValueError("instrument symbols must be unique")
    specs = _instrument_map(instruments)
    venues: list[str] = []
    settlements: list[str] = []
    rows: list[dict[str, object]] = []
    for symbol in symbol_values:
        spec = specs.get(symbol) or InstrumentSpec(symbol=symbol, contract_size=default_contract_size)
        metadata = dict(spec.metadata or {})
        contract_type = str(metadata.get("contract_type", "linear")).lower().strip()
        if spec.asset_type is AssetType.OPTION or contract_type in {"inverse", "quanto", "option"}:
            raise NotImplementedError(
                f"instrument {symbol!r} requires an uncertified {contract_type} accounting model"
            )
        venue = str(metadata.get("venue", default_venue))
        settlement = str(metadata.get("settlement_currency", default_settlement))
        if venue not in venues:
            venues.append(venue)
        if settlement not in settlements:
            settlements.append(settlement)
        tick = float(spec.tick_size)
        step = float(spec.lot_size)
        rows.append(
            {
                "venue_code": venues.index(venue),
                "contract_type": 0,
                "tick_size": tick,
                "qty_step": step,
                "min_qty": float(spec.min_qty),
                "max_qty": float(metadata.get("max_qty", 0.0)),
                "min_notional": float(spec.min_notional),
                "contract_size": float(spec.contract_size),
                "price_scale": _scale_from_increment(tick, spec.price_precision),
                "qty_scale": _scale_from_increment(step, spec.qty_precision),
                "settlement_code": settlements.index(settlement),
                "fee_model_id": _mapped_int(fee_model_id, symbol),
                "margin_model_id": _mapped_int(margin_model_id, symbol),
            }
        )

    payload = {
        "schema": INSTRUMENT_TABLE_SCHEMA_VERSION,
        "numeric_policy": NUMERIC_POLICY_VERSION,
        "symbols": symbol_values,
        "venues": venues,
        "settlements": settlements,
        "rows": rows,
    }
    fingerprint = sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    columns = {name: np.asarray([row[name] for row in rows], dtype=dtype) for name, dtype in (
        ("venue_code", np.int32), ("contract_type", np.int8), ("tick_size", np.float64),
        ("qty_step", np.float64), ("min_qty", np.float64), ("max_qty", np.float64),
        ("min_notional", np.float64), ("contract_size", np.float64),
        ("price_scale", np.int64), ("qty_scale", np.int64),
        ("settlement_code", np.int32), ("fee_model_id", np.int16),
        ("margin_model_id", np.int16),
    )}
    return PreparedInstrumentTable(
        symbols=symbol_values,
        symbol_code=np.arange(len(symbol_values), dtype=np.int32),
        venue_values=tuple(venues),
        settlement_values=tuple(settlements),
        fingerprint=fingerprint,
        **columns,
    )


def quantize_order_value(
    *,
    side: OrderSide | str,
    order_type: OrderType | str,
    price: float,
    qty: float,
    tick_size: float,
    qty_step: float,
    min_qty: float = 0.0,
    max_qty: float = 0.0,
    min_notional: float = 0.0,
    contract_size: float = 1.0,
) -> QuantizedOrderValue:
    """Quantize once, then run all venue minima against the quantized values."""

    try:
        side_value = side if isinstance(side, OrderSide) else OrderSide(str(side).lower())
        order_value = order_type if isinstance(order_type, OrderType) else OrderType(str(order_type).lower())
    except ValueError:
        return QuantizedOrderValue(0.0, 0.0, 0, 0, InstrumentRejectCode.INVALID_VALUE)
    values = (price, qty, tick_size, qty_step, min_qty, max_qty, min_notional, contract_size)
    if any(not np.isfinite(float(value)) for value in values) or price <= 0.0 or qty <= 0.0 or contract_size <= 0.0:
        return QuantizedOrderValue(0.0, 0.0, 0, 0, InstrumentRejectCode.INVALID_VALUE)

    price_mode = _price_rounding_mode(side_value, order_value)
    price_ticks = _integer_units(float(price), float(tick_size), price_mode)
    qty_lots = _integer_units(float(qty), float(qty_step), "floor")
    quantized_price = float(price) if tick_size <= 0.0 else price_ticks * float(tick_size)
    quantized_qty = float(qty) if qty_step <= 0.0 else qty_lots * float(qty_step)
    if quantized_qty <= 0.0 or quantized_qty + 1e-12 < min_qty:
        code = InstrumentRejectCode.MIN_QTY
    elif max_qty > 0.0 and quantized_qty - 1e-12 > max_qty:
        code = InstrumentRejectCode.MAX_QTY
    elif min_notional > 0.0 and quantized_qty * quantized_price * contract_size + 1e-12 < min_notional:
        code = InstrumentRejectCode.MIN_NOTIONAL
    else:
        code = InstrumentRejectCode.ACCEPTED
    return QuantizedOrderValue(quantized_price, quantized_qty, price_ticks, qty_lots, code)


def _price_rounding_mode(side: OrderSide, order_type: OrderType) -> str:
    if order_type in {OrderType.LIMIT, OrderType.STOP_LIMIT}:
        return "floor" if side is OrderSide.BUY else "ceil"
    return "ceil" if side is OrderSide.BUY else "floor"


def _integer_units(value: float, increment: float, mode: str) -> int:
    if increment <= 0.0:
        return 0
    scaled = value / increment
    if mode == "floor":
        return int(np.floor(scaled + 1e-12))
    if mode == "ceil":
        return int(np.ceil(scaled - 1e-12))
    raise ValueError(f"unsupported rounding mode={mode!r}")


def _scale_from_increment(increment: float, precision: int | None) -> int:
    if precision is not None:
        return 10 ** int(precision)
    if increment <= 0.0:
        return 0
    text = np.format_float_positional(float(increment), trim="-")
    decimals = len(text.partition(".")[2])
    return 10 ** min(decimals, 12)


def _instrument_map(instruments) -> dict[str, InstrumentSpec]:
    if instruments is None:
        return {}
    if isinstance(instruments, Mapping):
        return {str(symbol): spec for symbol, spec in instruments.items()}
    return {str(spec.symbol): spec for spec in instruments}


def _mapped_int(value: int | Mapping[str, int], symbol: str) -> int:
    return int(value.get(symbol, 0)) if isinstance(value, Mapping) else int(value)


__all__ = [
    "INSTRUMENT_TABLE_SCHEMA_VERSION",
    "NUMERIC_POLICY_VERSION",
    "InstrumentRejectCode",
    "PreparedInstrumentTable",
    "QuantizedOrderValue",
    "compile_instrument_table",
    "quantize_order_value",
]
