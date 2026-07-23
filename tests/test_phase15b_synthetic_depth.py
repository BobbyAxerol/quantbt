from __future__ import annotations

import pandas as pd
import pytest

from quantbt import (
    NautilusExecutionDepthConfig,
    OrderIntent,
    OrderSide,
    OrderType,
    l2_replay_available,
    simulate_nautilus_order_package_depth,
)


def _idx():
    return pd.date_range("2024-01-01", periods=3, freq="1h", tz="UTC")


def _frame():
    idx = _idx()
    return pd.DataFrame(
        {
            "open": [100.0, 100.0, 100.0],
            "high": [101.0, 101.0, 101.0],
            "low": [99.0, 99.0, 99.0],
            "close": [100.0, 100.0, 100.0],
            "volume": [100.0, 100.0, 100.0],
        },
        index=idx,
    )


def _order(qty: float, side: OrderSide = OrderSide.BUY, order_type: OrderType = OrderType.MARKET, **kwargs):
    return OrderIntent(
        timestamp=_idx()[1],
        symbol="BTCUSDT-PERP.BINANCE",
        side=side,
        order_type=order_type,
        qty=qty,
        **kwargs,
    )


def test_phase15b_synthetic_market_order_consumes_book_levels_with_vwap():
    order = _order(2.0)
    result = simulate_nautilus_order_package_depth(
        [order],
        {"BTCUSDT-PERP.BINANCE": _frame()},
        NautilusExecutionDepthConfig(
            depth_model="synthetic_book",
            synthetic_spread_bps=10.0,
            synthetic_level_spacing_bps=10.0,
            synthetic_levels=3,
            synthetic_base_depth_qty=1.0,
            allow_partial_fills=True,
        ),
    )

    row = result.order_report.iloc[0]
    assert row["status"] == "filled"
    assert row["levels_consumed"] == 2
    assert row["filled_qty"] == 2.0
    assert row["fill_price"] == pytest.approx((100.05 + 100.15) / 2.0)
    assert row["depth_model"] == "synthetic_book"


def test_phase15b_synthetic_partial_fill_respects_book_depth_and_queue():
    order = _order(3.0)
    result = simulate_nautilus_order_package_depth(
        [order],
        {"BTCUSDT-PERP.BINANCE": _frame()},
        NautilusExecutionDepthConfig(
            depth_model="synthetic_book",
            synthetic_levels=2,
            synthetic_base_depth_qty=1.0,
            queue_ahead_qty=0.5,
            allow_partial_fills=True,
        ),
    )

    row = result.order_report.iloc[0]
    assert row["status"] == "partial"
    assert row["available_qty"] == pytest.approx(1.5)
    assert result.orders[0].qty == pytest.approx(1.5)
    assert result.orders[0].metadata["depth_model"] == "synthetic_book"


def test_phase15b_synthetic_all_or_none_rejects_when_partial_not_allowed():
    order = _order(3.0)
    result = simulate_nautilus_order_package_depth(
        [order],
        {"BTCUSDT-PERP.BINANCE": _frame()},
        NautilusExecutionDepthConfig(
            depth_model="synthetic_book",
            synthetic_levels=2,
            synthetic_base_depth_qty=1.0,
            allow_partial_fills=False,
        ),
    )

    assert len(result.orders) == 0
    assert result.order_report.iloc[0]["status"] == "rejected"
    assert result.order_report.iloc[0]["reject_reason"] == "insufficient_queue_capacity"


def test_phase15b_synthetic_limit_order_respects_high_low_touch_and_limit_price():
    untouched = _order(1.0, order_type=OrderType.LIMIT, price=98.0)
    touched = _order(1.0, order_type=OrderType.LIMIT, price=100.2)
    cfg = NautilusExecutionDepthConfig(
        depth_model="synthetic_book",
        synthetic_spread_bps=10.0,
        synthetic_level_spacing_bps=10.0,
        synthetic_levels=3,
        synthetic_base_depth_qty=1.0,
    )

    miss = simulate_nautilus_order_package_depth([untouched], {"BTCUSDT-PERP.BINANCE": _frame()}, cfg)
    hit = simulate_nautilus_order_package_depth([touched], {"BTCUSDT-PERP.BINANCE": _frame()}, cfg)

    assert miss.order_report.iloc[0]["reject_reason"] == "limit_not_touched"
    assert hit.order_report.iloc[0]["status"] == "filled"
    assert hit.order_report.iloc[0]["fill_price"] <= 100.2


def test_phase15b_l2_replay_is_explicitly_provider_gated():
    if not l2_replay_available():
        pytest.skip("L2 replay requires a real provider with snapshots, updates and trades")
    raise AssertionError("unexpected test provider available")


def test_phase15b_l2_replay_model_refuses_without_provider():
    with pytest.raises(NotImplementedError, match="real venue L2"):
        simulate_nautilus_order_package_depth(
            [_order(1.0)],
            {"BTCUSDT-PERP.BINANCE": _frame()},
            NautilusExecutionDepthConfig(depth_model="l2_replay"),
        )
