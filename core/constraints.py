"""Exchange/instrument quantity constraints shared by all backends."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional, Sequence, Union

import numpy as np

from .schema import InstrumentSpec


NumberOrMap = Union[float, Dict[str, float], None]


@dataclass(frozen=True)
class QuantityConstraints:
    """Per-symbol exchange quantity rules.

    `contract_size` remains the PnL/notional multiplier.  Fractional crypto
    acceptance is controlled by `qty_step`/`lot_size`, `min_qty`, and
    `min_notional`.  QuantBT rounds target quantities down by default, matching
    the conservative side of common exchange filters.
    """

    symbols: tuple[str, ...]
    qty_step: np.ndarray
    min_qty: np.ndarray
    min_notional: np.ndarray

    @property
    def enabled(self) -> bool:
        return bool(
            np.any(self.qty_step > 0.0)
            or np.any(self.min_qty > 0.0)
            or np.any(self.min_notional > 0.0)
        )

    def as_dict(self) -> Dict[str, Dict[str, float]]:
        return {
            symbol: {
                "qty_step": float(self.qty_step[i]),
                "lot_size": float(self.qty_step[i]),
                "min_qty": float(self.min_qty[i]),
                "min_notional": float(self.min_notional[i]),
            }
            for i, symbol in enumerate(self.symbols)
        }


def build_quantity_constraints(
    symbols: Sequence[str],
    *,
    instruments: Optional[Union[Dict[str, InstrumentSpec], Sequence[InstrumentSpec]]] = None,
    qty_step: NumberOrMap = None,
    lot_size: NumberOrMap = None,
    slot_size: NumberOrMap = None,
    min_qty: NumberOrMap = None,
    min_notional: NumberOrMap = None,
) -> QuantityConstraints:
    """Resolve quantity constraints from explicit kwargs and InstrumentSpec.

    Explicit kwargs override `InstrumentSpec`. `slot_size` is accepted as a
    backward-compatible alias for `lot_size`.
    """

    symbol_list = tuple(symbols)
    inst_map = _instrument_map(instruments)
    step_source = qty_step if qty_step is not None else (lot_size if lot_size is not None else slot_size)

    steps = []
    min_qtys = []
    min_notionals = []
    for symbol in symbol_list:
        inst = inst_map.get(symbol)
        default_step = 0.0 if inst is None else float(inst.lot_size)
        default_min_qty = 0.0 if inst is None else float(inst.min_qty)
        default_min_notional = 0.0 if inst is None else float(inst.min_notional)
        steps.append(_value_for(step_source, symbol, default_step))
        min_qtys.append(_value_for(min_qty, symbol, default_min_qty))
        min_notionals.append(_value_for(min_notional, symbol, default_min_notional))

    out = QuantityConstraints(
        symbols=symbol_list,
        qty_step=np.asarray(steps, dtype=np.float64),
        min_qty=np.asarray(min_qtys, dtype=np.float64),
        min_notional=np.asarray(min_notionals, dtype=np.float64),
    )
    if np.any(out.qty_step < 0.0) or np.any(out.min_qty < 0.0) or np.any(out.min_notional < 0.0):
        raise ValueError("qty_step/lot_size, min_qty, and min_notional must be >= 0")
    return out


def quantize_target_units_matrix(
    target_units: np.ndarray,
    prices: np.ndarray,
    contract_sizes: np.ndarray,
    constraints: QuantityConstraints,
) -> np.ndarray:
    """Round target-unit matrix down to exchange-acceptable quantities."""

    if not constraints.enabled:
        return np.ascontiguousarray(target_units, dtype=np.float64)
    out = np.asarray(target_units, dtype=np.float64).copy(order="C")
    prices_arr = np.asarray(prices, dtype=np.float64)
    cs = np.asarray(contract_sizes, dtype=np.float64)
    for j in range(out.shape[1]):
        step = float(constraints.qty_step[j])
        mnq = float(constraints.min_qty[j])
        mnn = float(constraints.min_notional[j])
        for i in range(out.shape[0]):
            out[i, j] = quantize_signed_quantity(out[i, j], prices_arr[i, j], cs[j], step, mnq, mnn)
    return np.ascontiguousarray(out, dtype=np.float64)


def quantize_signed_quantity(
    qty: float,
    price: float,
    contract_size: float = 1.0,
    qty_step: float = 0.0,
    min_qty: float = 0.0,
    min_notional: float = 0.0,
) -> float:
    """Round a signed quantity down and zero it if below exchange minima."""

    q = float(qty)
    if q == 0.0:
        return 0.0
    sign = 1.0 if q > 0.0 else -1.0
    abs_q = abs(q)
    if qty_step > 0.0:
        abs_q = np.floor((abs_q / float(qty_step)) + 1e-12) * float(qty_step)
    if abs_q <= 0.0:
        return 0.0
    if min_qty > 0.0 and abs_q + 1e-12 < min_qty:
        return 0.0
    if min_notional > 0.0 and abs_q * float(price) * float(contract_size) + 1e-12 < min_notional:
        return 0.0
    return sign * abs_q


def _instrument_map(instruments) -> Dict[str, InstrumentSpec]:
    if instruments is None:
        return {}
    if isinstance(instruments, dict):
        return {symbol: spec for symbol, spec in instruments.items() if spec is not None}
    return {spec.symbol: spec for spec in instruments}


def _value_for(value: NumberOrMap, symbol: str, default: float) -> float:
    if value is None:
        return float(default)
    if isinstance(value, dict):
        return float(value.get(symbol, default))
    return float(value)
