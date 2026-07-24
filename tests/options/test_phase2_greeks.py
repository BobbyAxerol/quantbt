from __future__ import annotations

import pytest

from quantbt import (
    black76_price,
    inverse_black76_greeks_base,
    inverse_black76_greeks_quote,
    inverse_black76_price_base,
    linear_black76_greeks,
    scale_greeks_to_reporting_currency,
)


def _central_delta(fn, x: float, eps: float) -> float:
    return (fn(x + eps) - fn(x - eps)) / (2.0 * eps)


def _central_gamma(fn, x: float, eps: float) -> float:
    return (fn(x + eps) - 2.0 * fn(x) + fn(x - eps)) / (eps * eps)


def test_phase2_linear_greeks_match_finite_difference_delta_gamma_vega():
    forward = 100.0
    strike = 97.0
    tau = 0.6
    vol = 0.38
    discount = 0.99
    greeks = linear_black76_greeks(forward, strike, tau, vol, "call", discount=discount, currency="USD")

    price_by_forward = lambda fwd: black76_price(fwd, strike, tau, vol, "call", discount=discount)
    price_by_vol = lambda sigma: black76_price(forward, strike, tau, sigma, "call", discount=discount)

    assert greeks.currency == "USD"
    assert greeks.unit == "quote"
    assert greeks.delta == pytest.approx(_central_delta(price_by_forward, forward, 1e-3), rel=1e-7)
    assert greeks.gamma == pytest.approx(_central_gamma(price_by_forward, forward, 1e-2), rel=1e-5)
    assert greeks.vega == pytest.approx(_central_delta(price_by_vol, vol, 1e-5), rel=1e-7)
    assert greeks.vega_per_vol_point == pytest.approx(greeks.vega / 100.0)
    assert greeks.theta < 0.0


def test_phase2_inverse_base_greeks_match_finite_difference():
    forward = 95_000.0
    strike = 100_000.0
    tau = 0.25
    vol = 0.7
    greeks = inverse_black76_greeks_base(forward, strike, tau, vol, "put", currency="BTC")

    price_by_forward = lambda fwd: inverse_black76_price_base(fwd, strike, tau, vol, "put")
    price_by_vol = lambda sigma: inverse_black76_price_base(forward, strike, tau, sigma, "put")

    assert greeks.currency == "BTC"
    assert greeks.unit == "base"
    assert greeks.delta == pytest.approx(_central_delta(price_by_forward, forward, 1.0), rel=1e-6)
    assert greeks.gamma == pytest.approx(_central_gamma(price_by_forward, forward, 10.0), rel=1e-4)
    assert greeks.vega == pytest.approx(_central_delta(price_by_vol, vol, 1e-5), rel=1e-7)


def test_phase2_inverse_quote_reporting_matches_linear_quote_greeks():
    inverse_quote = inverse_black76_greeks_quote(90_000.0, 95_000.0, 0.5, 0.6, "call", currency="USD")
    linear = linear_black76_greeks(90_000.0, 95_000.0, 0.5, 0.6, "call", currency="USD")

    assert inverse_quote.price == pytest.approx(linear.price)
    assert inverse_quote.delta == pytest.approx(linear.delta)
    assert inverse_quote.gamma == pytest.approx(linear.gamma)
    assert inverse_quote.vega == pytest.approx(linear.vega)
    assert inverse_quote.theta == pytest.approx(linear.theta)


def test_phase2_static_reporting_currency_scaling_is_explicit():
    native = linear_black76_greeks(100.0, 100.0, 1.0, 0.5, "call", currency="USD")
    scaled = scale_greeks_to_reporting_currency(native, 25_000.0, reporting_currency="VND", vega_per_vol_point=True)

    assert scaled.currency == "VND"
    assert scaled.price == pytest.approx(native.price * 25_000.0)
    assert scaled.vega == pytest.approx(native.vega * 25_000.0 / 100.0)
