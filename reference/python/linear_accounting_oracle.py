"""Small independent oracle for linear quote-settled accounting.

This module deliberately imports only the Python standard library.  It is not
allowed to import QuantBT production modules, Rust bindings, Numba, NumPy, or
pandas.  The goal is readable verification on bounded fixtures, not speed.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
import math


@dataclass(frozen=True, slots=True)
class LinearAccountSpec:
    initial_cash: float
    leverage: float = 1.0
    maintenance_ratio: float = 0.0
    contract_size: float = 1.0

    def __post_init__(self) -> None:
        if not math.isfinite(self.initial_cash) or self.initial_cash < 0.0:
            raise ValueError("initial_cash must be finite and >= 0")
        if not math.isfinite(self.leverage) or self.leverage <= 0.0:
            raise ValueError("leverage must be finite and > 0")
        if not math.isfinite(self.maintenance_ratio) or self.maintenance_ratio < 0.0:
            raise ValueError("maintenance_ratio must be finite and >= 0")
        if not math.isfinite(self.contract_size) or self.contract_size <= 0.0:
            raise ValueError("contract_size must be finite and > 0")


@dataclass(frozen=True, slots=True)
class LinearAccountState:
    cash: float
    position_qty: float = 0.0
    average_entry: float = 0.0
    cumulative_realized_pnl: float = 0.0
    cumulative_fees: float = 0.0
    cumulative_funding: float = 0.0
    liquidated: bool = False


@dataclass(frozen=True, slots=True)
class MarginSnapshot:
    mark_price: float
    unrealized_pnl: float
    equity: float
    gross_notional: float
    initial_margin: float
    maintenance_margin: float
    available_equity: float


@dataclass(frozen=True, slots=True)
class FillTransition:
    before: LinearAccountState
    after: LinearAccountState
    signed_qty: float
    price: float
    fee: float
    realized_pnl: float
    ignored: bool = False


@dataclass(frozen=True, slots=True)
class FundingTransition:
    before: LinearAccountState
    after: LinearAccountState
    rate: float
    mark_price: float
    charge: float


@dataclass(frozen=True, slots=True)
class MarginPreview:
    accepted: bool
    reason_code: str
    projected_state: LinearAccountState
    projected_margin: MarginSnapshot


def initial_state(spec: LinearAccountSpec) -> LinearAccountState:
    return LinearAccountState(cash=float(spec.initial_cash))


def apply_fill(
    state: LinearAccountState,
    *,
    signed_qty: float,
    price: float,
    fee: float,
    spec: LinearAccountSpec,
) -> FillTransition:
    """Apply one accepted fill with explicit linear scale/reduce/reverse math."""

    _finite(signed_qty, "signed_qty")
    _positive(price, "price")
    _non_negative(fee, "fee")
    _validate_state(state)
    if signed_qty == 0.0:
        return FillTransition(state, state, 0.0, float(price), float(fee), 0.0, ignored=True)

    before = state
    quantity = float(before.position_qty)
    average = float(before.average_entry)
    delta = float(signed_qty)
    realized = 0.0

    if quantity == 0.0 or _same_sign(quantity, delta):
        new_qty = quantity + delta
        if quantity == 0.0:
            new_average = float(price)
        else:
            new_average = (
                abs(quantity) * average + abs(delta) * float(price)
            ) / abs(new_qty)
    else:
        closed = min(abs(quantity), abs(delta))
        if quantity > 0.0:
            realized = closed * (float(price) - average) * spec.contract_size
        else:
            realized = closed * (average - float(price)) * spec.contract_size
        new_qty = quantity + delta
        if new_qty == 0.0:
            new_average = 0.0
        elif _same_sign(quantity, new_qty):
            new_average = average
        else:
            new_average = float(price)

    after = LinearAccountState(
        cash=before.cash + realized - float(fee),
        position_qty=new_qty,
        average_entry=new_average,
        cumulative_realized_pnl=before.cumulative_realized_pnl + realized,
        cumulative_fees=before.cumulative_fees + float(fee),
        cumulative_funding=before.cumulative_funding,
        liquidated=before.liquidated,
    )
    _validate_state(after)
    return FillTransition(before, after, delta, float(price), float(fee), realized)


def apply_funding(
    state: LinearAccountState,
    *,
    rate: float,
    mark_price: float,
    spec: LinearAccountSpec,
) -> FundingTransition:
    """Apply one close-boundary funding event. Positive rate charges longs."""

    _finite(rate, "rate")
    _positive(mark_price, "mark_price")
    _validate_state(state)
    charge = state.position_qty * float(mark_price) * spec.contract_size * float(rate)
    after = replace(
        state,
        cash=state.cash - charge,
        cumulative_funding=state.cumulative_funding + charge,
    )
    _validate_state(after)
    return FundingTransition(state, after, float(rate), float(mark_price), charge)


def mark_to_market(state: LinearAccountState, *, mark_price: float, spec: LinearAccountSpec) -> MarginSnapshot:
    """Return linear PnL and gross-cross margin without mutating state."""

    _positive(mark_price, "mark_price")
    _validate_state(state)
    unrealized = state.position_qty * (float(mark_price) - state.average_entry) * spec.contract_size
    equity = state.cash + unrealized
    gross_notional = abs(state.position_qty * float(mark_price) * spec.contract_size)
    initial_margin = gross_notional / spec.leverage
    maintenance_margin = gross_notional * spec.maintenance_ratio
    return MarginSnapshot(
        mark_price=float(mark_price),
        unrealized_pnl=unrealized,
        equity=equity,
        gross_notional=gross_notional,
        initial_margin=initial_margin,
        maintenance_margin=maintenance_margin,
        available_equity=equity - initial_margin,
    )


def preview_fill_margin(
    state: LinearAccountState,
    *,
    signed_qty: float,
    price: float,
    fee: float,
    mark_price: float,
    spec: LinearAccountSpec,
) -> MarginPreview:
    """Preview a fill and reject post-cost insufficient margin without mutation."""

    transition = apply_fill(state, signed_qty=signed_qty, price=price, fee=fee, spec=spec)
    projected = mark_to_market(transition.after, mark_price=mark_price, spec=spec)
    accepted = projected.available_equity >= 0.0 and projected.equity >= projected.maintenance_margin
    return MarginPreview(
        accepted=accepted,
        reason_code="ACCEPTED" if accepted else "POST_COST_MARGIN",
        projected_state=transition.after,
        projected_margin=projected,
    )


def forced_close(
    state: LinearAccountState,
    *,
    price: float,
    fee_rate: float,
    spec: LinearAccountSpec,
) -> FillTransition:
    """Close any remaining position at a declared executable liquidation price."""

    _non_negative(fee_rate, "fee_rate")
    signed_qty = -state.position_qty
    fee = abs(signed_qty) * float(price) * spec.contract_size * float(fee_rate)
    transition = apply_fill(state, signed_qty=signed_qty, price=price, fee=fee, spec=spec)
    return replace(transition, after=replace(transition.after, liquidated=True))


def _same_sign(left: float, right: float) -> bool:
    return (left > 0.0 and right > 0.0) or (left < 0.0 and right < 0.0)


def _finite(value: float, name: str) -> None:
    if not math.isfinite(float(value)):
        raise ValueError(f"{name} must be finite")


def _positive(value: float, name: str) -> None:
    _finite(value, name)
    if float(value) <= 0.0:
        raise ValueError(f"{name} must be > 0")


def _non_negative(value: float, name: str) -> None:
    _finite(value, name)
    if float(value) < 0.0:
        raise ValueError(f"{name} must be >= 0")


def _validate_state(state: LinearAccountState) -> None:
    for name in (
        "cash",
        "position_qty",
        "average_entry",
        "cumulative_realized_pnl",
        "cumulative_fees",
        "cumulative_funding",
    ):
        _finite(float(getattr(state, name)), name)
    if state.position_qty == 0.0 and state.average_entry != 0.0:
        raise ValueError("flat position must have zero average_entry")
    if state.position_qty != 0.0 and state.average_entry <= 0.0:
        raise ValueError("non-flat position requires positive average_entry")


__all__ = [
    "FillTransition",
    "FundingTransition",
    "LinearAccountSpec",
    "LinearAccountState",
    "MarginPreview",
    "MarginSnapshot",
    "apply_fill",
    "apply_funding",
    "forced_close",
    "initial_state",
    "mark_to_market",
    "preview_fill_margin",
]
