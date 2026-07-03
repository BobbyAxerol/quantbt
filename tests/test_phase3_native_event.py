from __future__ import annotations

import pandas as pd

from quantbt import NativeEventBackend, NativeEventConfig
from quantbt.core.event import (
    ORDER_STATUS_CANCELED,
    ORDER_STATUS_REJECTED,
    REJECT_INSUFFICIENT_MARGIN,
)
from quantbt.core.orders import OrderIntent
from quantbt.core.schema import AccountConfig, ExecutionConfig, OrderSide, OrderType, TimeInForce


def _backend(initial_capital=10_000.0, leverage=10.0, fee_rate=0.0, slippage_bps=0.0):
    return NativeEventBackend(
        NativeEventConfig(
            account=AccountConfig(initial_capital=initial_capital, leverage=leverage),
            execution=ExecutionConfig(slippage_bps=slippage_bps),
            fee_rate=fee_rate,
            use_funding=False,
        )
    )


def _bars():
    idx = pd.date_range("2024-01-01", periods=4, freq="1D", tz="UTC")
    close = pd.Series([100.0, 100.0, 110.0, 120.0], index=idx)
    high = pd.Series([100.0, 101.0, 112.0, 121.0], index=idx)
    low = pd.Series([100.0, 99.0, 94.0, 119.0], index=idx)
    return idx, close, high, low


def test_native_event_market_order_fills_at_close_and_marks_to_market():
    idx, close, high, low = _bars()
    orders = [
        OrderIntent(
            timestamp=idx[1],
            symbol="BTC",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            qty=10.0,
            tif=TimeInForce.IOC,
        )
    ]

    result = _backend().run_orders(
        datetime_index=idx,
        orders=orders,
        closes={"BTC": close},
        highs={"BTC": high},
        lows={"BTC": low},
    )

    assert len(result.fills) == 1
    assert result.fills[0].price == 100.0
    assert result.positions["Position_BTC"].iloc[1] == 10.0
    assert result.equity.iloc[2] == 10_100.0


def test_native_event_limit_order_fills_at_touch_price():
    idx, close, high, low = _bars()
    orders = [
        OrderIntent(
            timestamp=idx[1],
            symbol="BTC",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            qty=10.0,
            price=99.0,
            tif=TimeInForce.GTC,
        )
    ]

    result = _backend().run_orders(
        datetime_index=idx,
        orders=orders,
        closes={"BTC": close},
        highs={"BTC": high},
        lows={"BTC": low},
    )

    assert len(result.fills) == 1
    assert result.fills[0].timestamp == idx[1]
    assert result.fills[0].price == 99.0
    assert result.equity.iloc[1] == 10_010.0
    assert result.equity.iloc[2] == 10_110.0


def test_native_event_gtc_limit_waits_until_future_touch():
    idx, close, high, low = _bars()
    orders = [
        OrderIntent(
            timestamp=idx[1],
            symbol="BTC",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            qty=10.0,
            price=95.0,
            tif=TimeInForce.GTC,
        )
    ]

    result = _backend().run_orders(
        datetime_index=idx,
        orders=orders,
        closes={"BTC": close},
        highs={"BTC": high},
        lows={"BTC": low},
    )

    assert len(result.fills) == 1
    assert result.fills[0].timestamp == idx[2]
    assert result.fills[0].price == 95.0
    assert result.positions["Position_BTC"].iloc[1] == 0.0
    assert result.positions["Position_BTC"].iloc[2] == 10.0


def test_native_event_ioc_limit_cancels_when_not_touched():
    idx, close, high, low = _bars()
    orders = [
        OrderIntent(
            timestamp=idx[1],
            symbol="BTC",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            qty=10.0,
            price=95.0,
            tif=TimeInForce.IOC,
        )
    ]

    result = _backend().run_orders(
        datetime_index=idx,
        orders=orders,
        closes={"BTC": close},
        highs={"BTC": high},
        lows={"BTC": low},
    )
    order_report = result.metadata["order_report"]

    assert len(result.fills) == 0
    assert order_report["status"].iloc[0] == ORDER_STATUS_CANCELED
    assert result.diagnostics["canceled_orders"].iloc[1] == 1


def test_native_event_rejects_order_above_buying_power():
    idx, close, high, low = _bars()
    orders = [
        OrderIntent(
            timestamp=idx[1],
            symbol="BTC",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            qty=500.0,
            tif=TimeInForce.IOC,
        )
    ]

    result = _backend(leverage=1.0).run_orders(
        datetime_index=idx,
        orders=orders,
        closes={"BTC": close},
        highs={"BTC": high},
        lows={"BTC": low},
    )
    order_report = result.metadata["order_report"]

    assert len(result.fills) == 0
    assert order_report["status"].iloc[0] == ORDER_STATUS_REJECTED
    assert order_report["reject_code"].iloc[0] == REJECT_INSUFFICIENT_MARGIN
    assert result.positions["Position_BTC"].iloc[1] == 0.0
