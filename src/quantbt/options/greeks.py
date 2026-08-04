"""
Option Greeks with explicit units.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Union

from .pricing import (
    black76_d1_d2,
    black76_price,
    normal_cdf,
    normal_pdf,
    _coerce_kind,
    _non_negative_float,
    _positive_float,
)
from .schema import OptionKind


@dataclass(frozen=True)
class OptionGreeks:
    price: float
    delta: float
    gamma: float
    vega: float
    theta: float
    currency: str
    unit: str

    @property
    def vega_per_vol_point(self) -> float:
        """Return vega for a 1 vol-point change, not a 1.0 vol change."""
        return self.vega / 100.0


def linear_black76_greeks(
    forward: float,
    strike: float,
    time_to_expiry: float,
    volatility: float,
    option_kind: Union[OptionKind, str],
    *,
    discount: float = 1.0,
    currency: str = "QUOTE",
) -> OptionGreeks:
    """Return Black-76 Greeks in quote currency per 1 underlying."""
    kind = _coerce_kind(option_kind)
    fwd, strike_, tau, vol, df = _validated_greek_inputs(forward, strike, time_to_expiry, volatility, discount)
    price = black76_price(fwd, strike_, tau, vol, kind, discount=df)
    if tau <= 0.0 or vol <= 0.0:
        delta = df if (kind is OptionKind.CALL and fwd > strike_) else 0.0
        if kind is OptionKind.PUT and fwd < strike_:
            delta = -df
        return OptionGreeks(price=price, delta=delta, gamma=0.0, vega=0.0, theta=0.0, currency=currency, unit="quote")
    d1, _ = black76_d1_d2(fwd, strike_, tau, vol)
    pdf = normal_pdf(d1)
    if kind is OptionKind.CALL:
        delta = df * normal_cdf(d1)
    else:
        delta = df * (normal_cdf(d1) - 1.0)
    gamma = df * pdf / (fwd * vol * math.sqrt(tau))
    vega = df * fwd * pdf * math.sqrt(tau)
    theta = -0.5 * df * fwd * pdf * vol / math.sqrt(tau)
    return OptionGreeks(
        price=price,
        delta=delta,
        gamma=gamma,
        vega=vega,
        theta=theta,
        currency=str(currency).upper(),
        unit="quote",
    )


def inverse_black76_greeks_base(
    forward: float,
    strike: float,
    time_to_expiry: float,
    volatility: float,
    option_kind: Union[OptionKind, str],
    *,
    discount: float = 1.0,
    currency: str = "BASE",
) -> OptionGreeks:
    """Return inverse option Greeks in native base settlement currency."""
    fwd = _positive_float(forward, "forward")
    linear = linear_black76_greeks(fwd, strike, time_to_expiry, volatility, option_kind, discount=discount)
    price = linear.price / fwd
    delta = linear.delta / fwd - linear.price / (fwd * fwd)
    gamma = linear.gamma / fwd - 2.0 * linear.delta / (fwd * fwd) + 2.0 * linear.price / (fwd * fwd * fwd)
    vega = linear.vega / fwd
    theta = linear.theta / fwd
    return OptionGreeks(
        price=price,
        delta=delta,
        gamma=gamma,
        vega=vega,
        theta=theta,
        currency=str(currency).upper(),
        unit="base",
    )


def inverse_black76_greeks_quote(
    forward: float,
    strike: float,
    time_to_expiry: float,
    volatility: float,
    option_kind: Union[OptionKind, str],
    *,
    discount: float = 1.0,
    currency: str = "QUOTE",
) -> OptionGreeks:
    """
    Return inverse option Greeks converted to quote reporting currency.

    Under the Phase 2 inverse convention, quote-reporting value equals the
    corresponding linear Black-76 value, so Greeks match the linear Greeks.
    """
    return linear_black76_greeks(
        forward,
        strike,
        time_to_expiry,
        volatility,
        option_kind,
        discount=discount,
        currency=currency,
    )


def scale_greeks_to_reporting_currency(
    greeks: OptionGreeks,
    conversion_rate: float,
    *,
    reporting_currency: str,
    vega_per_vol_point: bool = False,
) -> OptionGreeks:
    """
    Statically scale Greeks into a reporting currency.

    This is a pure currency conversion helper. It does not add chain-rule delta
    from a conversion rate that itself depends on the underlying.
    """
    rate = _positive_float(conversion_rate, "conversion_rate")
    vega_scale = 0.01 if vega_per_vol_point else 1.0
    return OptionGreeks(
        price=greeks.price * rate,
        delta=greeks.delta * rate,
        gamma=greeks.gamma * rate,
        vega=greeks.vega * rate * vega_scale,
        theta=greeks.theta * rate,
        currency=str(reporting_currency).upper(),
        unit=f"{greeks.unit}_reported",
    )


def _validated_greek_inputs(
    forward: float,
    strike: float,
    time_to_expiry: float,
    volatility: float,
    discount: float,
) -> tuple[float, float, float, float, float]:
    return (
        _positive_float(forward, "forward"),
        _positive_float(strike, "strike"),
        _non_negative_float(time_to_expiry, "time_to_expiry"),
        _non_negative_float(volatility, "volatility"),
        _positive_float(discount, "discount"),
    )
