from __future__ import annotations

import math

import pytest

from quantbt import (
    IVStatus,
    black76_intrinsic,
    black76_price,
    implied_vol_black76,
    implied_vol_inverse_black76_base,
    inverse_black76_price_base,
)


def test_phase2_implied_vol_recovers_linear_generated_price():
    expected_vol = 0.73
    price = black76_price(100.0, 105.0, 0.8, expected_vol, "call", discount=0.98)

    result = implied_vol_black76(price, 100.0, 105.0, 0.8, "call", discount=0.98)

    assert result.status is IVStatus.OK
    assert result.ok
    assert result.implied_vol == pytest.approx(expected_vol, abs=1e-10)
    assert result.model_price == pytest.approx(price, abs=1e-10)


def test_phase2_implied_vol_recovers_inverse_base_generated_price():
    expected_vol = 0.61
    price = inverse_black76_price_base(95_000.0, 100_000.0, 0.4, expected_vol, "put")

    result = implied_vol_inverse_black76_base(price, 95_000.0, 100_000.0, 0.4, "put")

    assert result.status is IVStatus.OK
    assert result.implied_vol == pytest.approx(expected_vol, abs=1e-10)
    assert result.model_price == pytest.approx(price, abs=1e-12)


def test_phase2_implied_vol_returns_zero_at_intrinsic_boundary():
    intrinsic = black76_intrinsic(120.0, 100.0, "call")

    result = implied_vol_black76(intrinsic, 120.0, 100.0, 1.0, "call")

    assert result.status is IVStatus.OK
    assert result.implied_vol == 0.0


def test_phase2_implied_vol_invalid_prices_have_explicit_status():
    below = implied_vol_black76(0.5, 120.0, 100.0, 1.0, "call")
    above = implied_vol_black76(121.0, 120.0, 100.0, 1.0, "call")
    invalid = implied_vol_black76(math.nan, 120.0, 100.0, 1.0, "call")

    assert below.status is IVStatus.BELOW_INTRINSIC
    assert above.status is IVStatus.ABOVE_MAX_PRICE
    assert invalid.status is IVStatus.INVALID_INPUT
    assert math.isnan(below.implied_vol)
    assert math.isnan(above.implied_vol)


def test_phase2_implied_vol_invalid_type_returns_status_not_exception():
    result = implied_vol_black76("bad-price", 120.0, 100.0, 1.0, "call")

    assert result.status is IVStatus.INVALID_INPUT
    assert math.isnan(result.implied_vol)
