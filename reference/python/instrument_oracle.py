"""Standard-library-only V1.1 instrument rounding oracle."""

from __future__ import annotations

import math


def quantize_price(raw: float, tick: float, *, side: str, purpose: str) -> float:
    raw = float(raw)
    if not math.isfinite(raw) or raw <= 0.0:
        raise ValueError("invalid price")
    if tick <= 0.0:
        return raw
    units = raw / float(tick)
    side = str(side).lower()
    purpose = str(purpose).lower()
    if purpose == "limit":
        rounded = math.floor(units + 1e-12) if side == "buy" else math.ceil(units - 1e-12)
    else:
        rounded = math.ceil(units - 1e-12) if side == "buy" else math.floor(units + 1e-12)
    value = rounded * float(tick)
    if value <= 0.0:
        raise ValueError("non-positive quantized price")
    return value


def quantize_quantity(
    raw: float,
    step: float,
    *,
    purpose: str,
    current_position: float | None = None,
    allow_close_remainder: bool = True,
) -> float:
    value = abs(float(raw))
    if not math.isfinite(value) or value <= 0.0:
        return 0.0
    if str(purpose).lower() == "risk_reducing":
        if current_position is None:
            raise ValueError("reduce-only quantity needs current position")
        available = abs(float(current_position))
        value = min(value, available)
        if allow_close_remainder and abs(value - available) <= 1e-12:
            return available
    if step <= 0.0:
        return value
    return math.floor(value / float(step) + 1e-12) * float(step)
