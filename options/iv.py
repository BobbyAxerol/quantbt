"""
Deterministic implied-volatility solvers.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import math
from typing import Callable, Union

from .pricing import (
    black76_intrinsic,
    black76_price,
    inverse_black76_intrinsic_base,
    inverse_black76_price_base,
    _coerce_kind,
    _non_negative_float,
    _positive_float,
)
from .schema import OptionKind


class IVStatus(str, Enum):
    OK = "ok"
    BELOW_INTRINSIC = "below_intrinsic"
    ABOVE_MAX_PRICE = "above_max_price"
    INVALID_INPUT = "invalid_input"
    NOT_BRACKETED = "not_bracketed"
    MAX_ITERATIONS = "max_iterations"


@dataclass(frozen=True)
class ImpliedVolResult:
    implied_vol: float
    status: IVStatus
    iterations: int
    model_price: float
    lower_bound: float
    upper_bound: float
    residual: float

    @property
    def ok(self) -> bool:
        return self.status is IVStatus.OK


def implied_vol_black76(
    price: float,
    forward: float,
    strike: float,
    time_to_expiry: float,
    option_kind: Union[OptionKind, str],
    *,
    discount: float = 1.0,
    tolerance: float = 1e-12,
    max_iterations: int = 100,
    vol_lower: float = 0.0,
    vol_upper: float = 5.0,
    max_vol_upper: float = 20.0,
) -> ImpliedVolResult:
    """Solve linear Black-76 implied volatility with bracketed bisection."""
    try:
        kind = _coerce_kind(option_kind)
        target = _non_negative_float(price, "price")
        fwd = _positive_float(forward, "forward")
        strike_ = _positive_float(strike, "strike")
        tau = _non_negative_float(time_to_expiry, "time_to_expiry")
        df = _positive_float(discount, "discount")
    except (TypeError, ValueError):
        return _invalid_result(price)
    lower_bound = black76_intrinsic(fwd, strike_, kind, discount=df)
    upper_bound = _black76_upper_bound(fwd, strike_, kind, discount=df)
    return _solve_bisection(
        target,
        lower_bound,
        upper_bound,
        lambda vol: black76_price(fwd, strike_, tau, vol, kind, discount=df),
        tolerance=tolerance,
        max_iterations=max_iterations,
        vol_lower=vol_lower,
        vol_upper=vol_upper,
        max_vol_upper=max_vol_upper,
    )


def implied_vol_inverse_black76_base(
    price_base: float,
    forward: float,
    strike: float,
    time_to_expiry: float,
    option_kind: Union[OptionKind, str],
    *,
    discount: float = 1.0,
    tolerance: float = 1e-12,
    max_iterations: int = 100,
    vol_lower: float = 0.0,
    vol_upper: float = 5.0,
    max_vol_upper: float = 20.0,
) -> ImpliedVolResult:
    """Solve inverse Black-76 implied volatility from base-currency price."""
    try:
        kind = _coerce_kind(option_kind)
        target = _non_negative_float(price_base, "price_base")
        fwd = _positive_float(forward, "forward")
        strike_ = _positive_float(strike, "strike")
        tau = _non_negative_float(time_to_expiry, "time_to_expiry")
        df = _positive_float(discount, "discount")
    except (TypeError, ValueError):
        return _invalid_result(price_base)
    lower_bound = inverse_black76_intrinsic_base(fwd, strike_, kind, discount=df)
    upper_bound = _black76_upper_bound(fwd, strike_, kind, discount=df) / fwd
    return _solve_bisection(
        target,
        lower_bound,
        upper_bound,
        lambda vol: inverse_black76_price_base(fwd, strike_, tau, vol, kind, discount=df),
        tolerance=tolerance,
        max_iterations=max_iterations,
        vol_lower=vol_lower,
        vol_upper=vol_upper,
        max_vol_upper=max_vol_upper,
    )


def _solve_bisection(
    target: float,
    lower_bound: float,
    upper_bound: float,
    price_fn: Callable[[float], float],
    *,
    tolerance: float,
    max_iterations: int,
    vol_lower: float,
    vol_upper: float,
    max_vol_upper: float,
) -> ImpliedVolResult:
    tol = _positive_float(tolerance, "tolerance")
    if max_iterations <= 0:
        return ImpliedVolResult(math.nan, IVStatus.INVALID_INPUT, 0, math.nan, lower_bound, upper_bound, math.nan)
    lower_vol = _non_negative_float(vol_lower, "vol_lower")
    upper_vol = _positive_float(vol_upper, "vol_upper")
    max_upper = _positive_float(max_vol_upper, "max_vol_upper")
    if upper_vol <= lower_vol:
        return ImpliedVolResult(math.nan, IVStatus.INVALID_INPUT, 0, math.nan, lower_bound, upper_bound, math.nan)
    if target < lower_bound - tol:
        return ImpliedVolResult(math.nan, IVStatus.BELOW_INTRINSIC, 0, lower_bound, lower_bound, upper_bound, target - lower_bound)
    if target > upper_bound + tol:
        return ImpliedVolResult(math.nan, IVStatus.ABOVE_MAX_PRICE, 0, upper_bound, lower_bound, upper_bound, target - upper_bound)
    if abs(target - lower_bound) <= tol:
        return ImpliedVolResult(0.0, IVStatus.OK, 0, lower_bound, lower_bound, upper_bound, lower_bound - target)

    lower_price = price_fn(lower_vol)
    upper_price = price_fn(upper_vol)
    while upper_price < target and upper_vol < max_upper:
        upper_vol = min(upper_vol * 2.0, max_upper)
        upper_price = price_fn(upper_vol)
    if target < lower_price - tol or upper_price < target - tol:
        return ImpliedVolResult(math.nan, IVStatus.NOT_BRACKETED, 0, upper_price, lower_bound, upper_bound, upper_price - target)

    mid = 0.5 * (lower_vol + upper_vol)
    mid_price = price_fn(mid)
    for iteration in range(1, max_iterations + 1):
        mid = 0.5 * (lower_vol + upper_vol)
        mid_price = price_fn(mid)
        residual = mid_price - target
        if abs(residual) <= tol:
            return ImpliedVolResult(mid, IVStatus.OK, iteration, mid_price, lower_bound, upper_bound, residual)
        if mid_price < target:
            lower_vol = mid
        else:
            upper_vol = mid
    return ImpliedVolResult(mid, IVStatus.MAX_ITERATIONS, max_iterations, mid_price, lower_bound, upper_bound, mid_price - target)


def _black76_upper_bound(forward: float, strike: float, option_kind: OptionKind, *, discount: float) -> float:
    if option_kind is OptionKind.CALL:
        return discount * forward
    return discount * strike


def _invalid_result(price: float) -> ImpliedVolResult:
    try:
        raw = float(price)
    except (TypeError, ValueError):
        raw = math.nan
    target = raw if math.isfinite(raw) else math.nan
    return ImpliedVolResult(math.nan, IVStatus.INVALID_INPUT, 0, math.nan, math.nan, math.nan, target)
