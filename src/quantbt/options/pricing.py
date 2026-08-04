"""
Option pricing primitives.

Phase 2 intentionally keeps pricing deterministic and scalar. Execution,
margin, expiry, and ledger accounting are added in later phases.
"""

from __future__ import annotations

import math
from typing import Union

from .schema import OptionKind


Number = Union[int, float]


def black76_price(
    forward: Number,
    strike: Number,
    time_to_expiry: Number,
    volatility: Number,
    option_kind: Union[OptionKind, str],
    *,
    discount: Number = 1.0,
) -> float:
    """Return linear Black-76 option value in quote currency per 1 underlying."""
    kind = _coerce_kind(option_kind)
    fwd, strike_, tau, vol, df = _validate_inputs(forward, strike, time_to_expiry, volatility, discount)
    intrinsic = black76_intrinsic(fwd, strike_, kind, discount=df)
    if tau <= 0.0 or vol <= 0.0:
        return intrinsic
    d1, d2 = black76_d1_d2(fwd, strike_, tau, vol)
    if kind is OptionKind.CALL:
        return df * (fwd * normal_cdf(d1) - strike_ * normal_cdf(d2))
    return df * (strike_ * normal_cdf(-d2) - fwd * normal_cdf(-d1))


def black76_intrinsic(
    forward: Number,
    strike: Number,
    option_kind: Union[OptionKind, str],
    *,
    discount: Number = 1.0,
) -> float:
    """Return discounted intrinsic value in quote currency."""
    kind = _coerce_kind(option_kind)
    fwd = _positive_float(forward, "forward")
    strike_ = _positive_float(strike, "strike")
    df = _positive_float(discount, "discount")
    if kind is OptionKind.CALL:
        return df * max(fwd - strike_, 0.0)
    return df * max(strike_ - fwd, 0.0)


def black76_parity_value(forward: Number, strike: Number, *, discount: Number = 1.0) -> float:
    """Return theoretical linear call-put parity value: C - P."""
    fwd = _positive_float(forward, "forward")
    strike_ = _positive_float(strike, "strike")
    df = _positive_float(discount, "discount")
    return df * (fwd - strike_)


def black76_parity_residual(
    call_price: Number,
    put_price: Number,
    forward: Number,
    strike: Number,
    *,
    discount: Number = 1.0,
) -> float:
    """Return residual of linear Black-76 put-call parity."""
    return float(call_price) - float(put_price) - black76_parity_value(forward, strike, discount=discount)


def inverse_black76_price_base(
    forward: Number,
    strike: Number,
    time_to_expiry: Number,
    volatility: Number,
    option_kind: Union[OptionKind, str],
    *,
    discount: Number = 1.0,
) -> float:
    """
    Return inverse option value in base settlement currency.

    The Phase 2 convention prices inverse BTC/ETH options as the corresponding
    forward Black-76 quote-currency option divided by forward. This gives the
    expiry payoff shape `max(S-K, 0) / S` for calls and `max(K-S, 0) / S` for
    puts, and locks inverse parity to `DF * (1 - K/F)`.
    """
    fwd = _positive_float(forward, "forward")
    return black76_price(fwd, strike, time_to_expiry, volatility, option_kind, discount=discount) / fwd


def inverse_black76_intrinsic_base(
    forward: Number,
    strike: Number,
    option_kind: Union[OptionKind, str],
    *,
    discount: Number = 1.0,
) -> float:
    """Return inverse intrinsic value in base settlement currency."""
    fwd = _positive_float(forward, "forward")
    return black76_intrinsic(fwd, strike, option_kind, discount=discount) / fwd


def inverse_black76_parity_value_base(forward: Number, strike: Number, *, discount: Number = 1.0) -> float:
    """Return inverse call-put parity value in base settlement currency."""
    fwd = _positive_float(forward, "forward")
    strike_ = _positive_float(strike, "strike")
    df = _positive_float(discount, "discount")
    return df * (1.0 - strike_ / fwd)


def inverse_black76_parity_residual_base(
    call_price_base: Number,
    put_price_base: Number,
    forward: Number,
    strike: Number,
    *,
    discount: Number = 1.0,
) -> float:
    """Return residual of inverse put-call parity in base settlement currency."""
    return (
        float(call_price_base)
        - float(put_price_base)
        - inverse_black76_parity_value_base(forward, strike, discount=discount)
    )


def black76_d1_d2(forward: Number, strike: Number, time_to_expiry: Number, volatility: Number) -> tuple[float, float]:
    fwd = _positive_float(forward, "forward")
    strike_ = _positive_float(strike, "strike")
    tau = _non_negative_float(time_to_expiry, "time_to_expiry")
    vol = _non_negative_float(volatility, "volatility")
    if tau <= 0.0 or vol <= 0.0:
        raise ValueError("d1/d2 require time_to_expiry > 0 and volatility > 0")
    vol_sqrt_t = vol * math.sqrt(tau)
    d1 = (math.log(fwd / strike_) + 0.5 * vol * vol * tau) / vol_sqrt_t
    return d1, d1 - vol_sqrt_t


def normal_pdf(x: Number) -> float:
    value = float(x)
    return math.exp(-0.5 * value * value) / math.sqrt(2.0 * math.pi)


def normal_cdf(x: Number) -> float:
    return 0.5 * (1.0 + math.erf(float(x) / math.sqrt(2.0)))


def _coerce_kind(option_kind: Union[OptionKind, str]) -> OptionKind:
    if isinstance(option_kind, OptionKind):
        return option_kind
    try:
        return OptionKind(str(option_kind).lower())
    except ValueError as exc:
        raise ValueError("option_kind must be call or put") from exc


def _validate_inputs(
    forward: Number,
    strike: Number,
    time_to_expiry: Number,
    volatility: Number,
    discount: Number,
) -> tuple[float, float, float, float, float]:
    return (
        _positive_float(forward, "forward"),
        _positive_float(strike, "strike"),
        _non_negative_float(time_to_expiry, "time_to_expiry"),
        _non_negative_float(volatility, "volatility"),
        _positive_float(discount, "discount"),
    )


def _positive_float(value: Number, name: str) -> float:
    out = float(value)
    if not math.isfinite(out) or out <= 0.0:
        raise ValueError(f"{name} must be finite and > 0")
    return out


def _non_negative_float(value: Number, name: str) -> float:
    out = float(value)
    if not math.isfinite(out) or out < 0.0:
        raise ValueError(f"{name} must be finite and >= 0")
    return out
