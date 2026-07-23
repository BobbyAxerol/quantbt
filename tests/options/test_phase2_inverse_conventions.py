from __future__ import annotations

import pytest

from quantbt import (
    black76_price,
    inverse_black76_intrinsic_base,
    inverse_black76_parity_residual_base,
    inverse_black76_parity_value_base,
    inverse_black76_price_base,
)


def test_phase2_inverse_price_is_linear_quote_price_divided_by_forward():
    forward = 95_000.0
    strike = 100_000.0
    tau = 45.0 / 365.0
    vol = 0.68

    call_base = inverse_black76_price_base(forward, strike, tau, vol, "call")
    put_base = inverse_black76_price_base(forward, strike, tau, vol, "put")
    call_quote = black76_price(forward, strike, tau, vol, "call")
    put_quote = black76_price(forward, strike, tau, vol, "put")

    assert call_base == pytest.approx(call_quote / forward, rel=0, abs=1e-15)
    assert put_base == pytest.approx(put_quote / forward, rel=0, abs=1e-15)


def test_phase2_inverse_put_call_parity_is_base_currency_parity():
    forward = 105_000.0
    strike = 100_000.0
    tau = 0.5
    vol = 0.55
    discount = 0.99

    call_base = inverse_black76_price_base(forward, strike, tau, vol, "call", discount=discount)
    put_base = inverse_black76_price_base(forward, strike, tau, vol, "put", discount=discount)

    assert inverse_black76_parity_value_base(forward, strike, discount=discount) == pytest.approx(
        discount * (1.0 - strike / forward)
    )
    assert inverse_black76_parity_residual_base(call_base, put_base, forward, strike, discount=discount) == pytest.approx(
        0.0,
        abs=1e-14,
    )


def test_phase2_inverse_intrinsic_matches_base_payoff_shape():
    assert inverse_black76_intrinsic_base(110_000.0, 100_000.0, "call") == pytest.approx(10_000.0 / 110_000.0)
    assert inverse_black76_intrinsic_base(90_000.0, 100_000.0, "put") == pytest.approx(10_000.0 / 90_000.0)
