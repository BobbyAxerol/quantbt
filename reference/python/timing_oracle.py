"""Tiny independent timing oracle for Phase 57 hand fixtures."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Sequence


V2_NEXT_BAR_CLOSE = "event_lifecycle_v2_next_bar_close"
V3_NEXT_OPEN = "event_lifecycle_v3_next_open"


@dataclass(frozen=True, slots=True)
class EffectiveCommand:
    observed_bar: int
    effective_bar: int | None
    effective_phase: str | None
    outcome: str


def resolve_effective_command(*, contract_id: str, observed_bar: int, bar_count: int) -> EffectiveCommand:
    """Resolve the next eligible bar under the written V2/V3 timing contract."""

    if contract_id not in {V2_NEXT_BAR_CLOSE, V3_NEXT_OPEN}:
        raise ValueError("unsupported contract_id")
    if bar_count <= 0:
        raise ValueError("bar_count must be > 0")
    if not 0 <= observed_bar < bar_count:
        raise ValueError("observed_bar is outside tape")
    if observed_bar == 0 or observed_bar + 1 >= bar_count:
        return EffectiveCommand(observed_bar, None, None, "OUTSIDE_TAPE")
    phase = "NEXT_BAR_CLOSE" if contract_id == V2_NEXT_BAR_CLOSE else "NEXT_BAR_OPEN"
    return EffectiveCommand(observed_bar, observed_bar + 1, phase, "ACCEPTED")


def funding_phase_for_timestamp(*, timestamp_semantics: str) -> str:
    """Declare funding placement instead of guessing timestamp meaning."""

    if timestamp_semantics == "close":
        return "AFTER_INTRABAR_BEFORE_COMMAND_MATCHING"
    if timestamp_semantics == "open":
        return "BEFORE_OPEN_COMMAND_MATCHING"
    raise ValueError("timestamp_semantics must be 'open' or 'close'")


def exact_calendar_mapping(primary: Sequence[int], secondary: Sequence[int]) -> tuple[int, ...]:
    """Return an exact map or fail at the first divergent timestamp."""

    if len(primary) != len(secondary):
        raise ValueError(f"exact calendar length mismatch: {len(primary)} != {len(secondary)}")
    for index, (left, right) in enumerate(zip(primary, secondary, strict=True)):
        if int(left) != int(right):
            raise ValueError(f"exact calendar divergence at bar {index}: {left} != {right}")
    return tuple(range(len(primary)))


def oco_sibling_cancellations(*, filled_order_id: int, sibling_order_ids: Sequence[int]) -> tuple[int, ...]:
    """Return deterministic sibling cancellations after a successful OCO fill."""

    if filled_order_id < 0:
        raise ValueError("filled_order_id must be >= 0")
    return tuple(sorted({int(order_id) for order_id in sibling_order_ids if int(order_id) != filled_order_id}))


def floor_to_step(*, quantity: float, step: float) -> float:
    """Quantize a non-negative request without increasing its requested size."""

    if not math.isfinite(quantity) or not math.isfinite(step) or quantity < 0.0 or step <= 0.0:
        raise ValueError("quantity must be finite >= 0 and step must be finite > 0")
    return math.floor(quantity / step + 1e-12) * step


def maintenance_breached(*, equity: float, maintenance_margin: float) -> bool:
    """The boundary is inclusive: equity equal to maintenance is a breach."""

    if not math.isfinite(equity) or not math.isfinite(maintenance_margin) or maintenance_margin < 0.0:
        raise ValueError("equity and maintenance_margin must be finite; maintenance must be >= 0")
    return maintenance_margin > 0.0 and equity <= maintenance_margin


__all__ = [
    "EffectiveCommand",
    "V2_NEXT_BAR_CLOSE",
    "V3_NEXT_OPEN",
    "exact_calendar_mapping",
    "floor_to_step",
    "funding_phase_for_timestamp",
    "maintenance_breached",
    "oco_sibling_cancellations",
    "resolve_effective_command",
]
