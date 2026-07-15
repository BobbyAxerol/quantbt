from __future__ import annotations

import pandas as pd

from quantbt import (
    NautilusExecutionDepthConfig,
    OrderIntent,
    OrderSide,
    OrderType,
    TimeInForce,
    simulate_nautilus_order_package_depth,
)


def _idx():
    return pd.date_range("2024-01-01", periods=5, freq="1h", tz="UTC")


def _frame(close, high=None, low=None, volume=100.0):
    idx = _idx()
    close = pd.Series(close, index=idx, dtype=float)
    return pd.DataFrame(
        {
            "open": close,
            "high": pd.Series(high if high is not None else close, index=idx, dtype=float),
            "low": pd.Series(low if low is not None else close, index=idx, dtype=float),
            "close": close,
            "volume": pd.Series(volume if isinstance(volume, list) else [volume] * len(idx), index=idx, dtype=float),
        },
        index=idx,
    )


def _order(ts, symbol, side, order_type, qty, **kwargs):
    return OrderIntent(
        timestamp=ts,
        symbol=symbol,
        side=side,
        order_type=order_type,
        qty=qty,
        **kwargs,
    )


def test_phase5_4_all_or_none_package_rejects_every_leg_when_one_leg_cannot_fill():
    idx = _idx()
    data = {
        "BTC": _frame([100.0] * 5, high=[101.0] * 5, low=[95.0] * 5),
        "ETH": _frame([50.0] * 5, high=[51.0] * 5, low=[49.0] * 5),
    }
    meta = {"package_id": "BASKET-1", "package_type": "basket_package"}
    orders = [
        _order(idx[1], "BTC", OrderSide.BUY, OrderType.LIMIT, 1.0, price=96.0, metadata=meta),
        _order(idx[1], "ETH", OrderSide.BUY, OrderType.LIMIT, 1.0, price=45.0, metadata=meta),
    ]

    result = simulate_nautilus_order_package_depth(
        orders,
        data,
        NautilusExecutionDepthConfig(all_or_none_packages=True),
    )

    assert len(result.orders) == 0
    assert result.metadata["rejected_orders"] == 2
    assert result.package_report.iloc[0]["status"] == "rejected"
    assert set(result.order_report["reject_reason"]) == {"all_or_none_package_rejected"}


def test_phase5_4_best_effort_package_keeps_fillable_leg():
    idx = _idx()
    data = {
        "BTC": _frame([100.0] * 5, high=[101.0] * 5, low=[95.0] * 5),
        "ETH": _frame([50.0] * 5, high=[51.0] * 5, low=[49.0] * 5),
    }
    meta = {"package_id": "BASKET-2", "package_type": "basket_package"}
    orders = [
        _order(idx[1], "BTC", OrderSide.BUY, OrderType.LIMIT, 1.0, price=96.0, metadata=meta),
        _order(idx[1], "ETH", OrderSide.BUY, OrderType.LIMIT, 1.0, price=45.0, metadata=meta),
    ]

    result = simulate_nautilus_order_package_depth(orders, data)

    assert len(result.orders) == 1
    assert result.orders[0].symbol == "BTC"
    assert result.order_report["status"].tolist() == ["filled", "rejected"]


def test_phase5_4_partial_fill_respects_volume_participation_and_queue_ahead():
    idx = _idx()
    data = {"BTC": _frame([100.0] * 5, volume=[100.0] * 5)}
    orders = [_order(idx[1], "BTC", OrderSide.BUY, OrderType.MARKET, 10.0)]

    result = simulate_nautilus_order_package_depth(
        orders,
        data,
        NautilusExecutionDepthConfig(
            allow_partial_fills=True,
            max_participation_rate=0.05,
            queue_ahead_qty=2.0,
        ),
    )

    assert len(result.orders) == 1
    assert result.orders[0].qty == 3.0
    assert result.order_report.iloc[0]["status"] == "partial"
    assert result.order_report.iloc[0]["available_qty"] == 3.0


def test_phase5_4_reduce_only_exit_caps_to_position_and_oco_cancels_sibling():
    idx = _idx()
    data = {
        "BTC": _frame(
            [100.0, 100.0, 110.0, 100.0, 100.0],
            high=[100.0, 101.0, 111.0, 100.0, 100.0],
            low=[100.0, 99.0, 95.0, 94.0, 100.0],
        )
    }
    common = {
        "package_id": "BRACKET-DEPTH",
        "package_type": "bracket_oco",
        "oco_group_id": "BRACKET-DEPTH:oco",
        "oco_policy": "cancel_sibling_on_first_exit_fill",
    }
    orders = [
        _order(idx[1], "BTC", OrderSide.BUY, OrderType.MARKET, 1.0, tag="entry", metadata={**common, "leg_role": "entry"}),
        _order(
            idx[2],
            "BTC",
            OrderSide.SELL,
            OrderType.LIMIT,
            2.0,
            price=110.0,
            tif=TimeInForce.GTC,
            reduce_only=True,
            tag="tp",
            metadata={**common, "leg_role": "take_profit", "parent_tag": "entry"},
        ),
        _order(
            idx[2],
            "BTC",
            OrderSide.SELL,
            OrderType.STOP_MARKET,
            2.0,
            trigger_price=95.0,
            tif=TimeInForce.GTC,
            reduce_only=True,
            tag="sl",
            metadata={**common, "leg_role": "stop_loss", "parent_tag": "entry"},
        ),
    ]

    result = simulate_nautilus_order_package_depth(orders, data)

    assert len(result.orders) == 2
    assert result.orders[1].qty == 1.0
    assert result.order_report["status"].tolist() == ["filled", "partial", "canceled"]
    assert result.order_report.iloc[2]["reject_reason"] == "oco_sibling_already_filled"


def test_phase5_4_latency_shifts_effective_execution_bar():
    idx = _idx()
    data = {"BTC": _frame([100.0, 101.0, 105.0, 110.0, 111.0])}
    orders = [_order(idx[1], "BTC", OrderSide.BUY, OrderType.MARKET, 1.0)]

    result = simulate_nautilus_order_package_depth(
        orders,
        data,
        NautilusExecutionDepthConfig(latency_bars=1),
    )

    assert len(result.orders) == 1
    assert pd.Timestamp(result.orders[0].timestamp) == idx[2]
    assert result.order_report.iloc[0]["fill_price"] == 105.0
    assert result.order_report.iloc[0]["latency_bars"] == 1
