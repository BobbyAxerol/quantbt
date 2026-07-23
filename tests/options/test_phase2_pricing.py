from __future__ import annotations

import math

import pytest

from quantbt import (
    black76_intrinsic,
    black76_parity_residual,
    black76_parity_value,
    black76_price,
)


def test_phase2_linear_black76_put_call_parity_and_intrinsic_limits():
    forward = 100.0
    strike = 95.0
    tau = 0.75
    vol = 0.42
    discount = 0.97

    call = black76_price(forward, strike, tau, vol, "call", discount=discount)
    put = black76_price(forward, strike, tau, vol, "put", discount=discount)

    assert call > black76_intrinsic(forward, strike, "call", discount=discount)
    assert put > black76_intrinsic(forward, strike, "put", discount=discount)
    assert black76_parity_value(forward, strike, discount=discount) == pytest.approx(discount * (forward - strike))
    assert black76_parity_residual(call, put, forward, strike, discount=discount) == pytest.approx(0.0, abs=1e-10)


def test_phase2_linear_black76_zero_time_or_zero_vol_returns_intrinsic():
    assert black76_price(100.0, 90.0, 0.0, 0.5, "call") == pytest.approx(10.0)
    assert black76_price(100.0, 110.0, 1.0, 0.0, "put") == pytest.approx(10.0)


def test_phase2_linear_black76_rejects_invalid_inputs():
    with pytest.raises(ValueError, match="forward"):
        black76_price(0.0, 100.0, 1.0, 0.2, "call")
    with pytest.raises(ValueError, match="strike"):
        black76_price(100.0, -1.0, 1.0, 0.2, "call")
    with pytest.raises(ValueError, match="option_kind"):
        black76_price(100.0, 100.0, 1.0, 0.2, "straddle")
    with pytest.raises(ValueError, match="volatility"):
        black76_price(100.0, 100.0, 1.0, math.nan, "call")
