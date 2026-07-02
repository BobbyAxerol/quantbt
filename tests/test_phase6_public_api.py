from __future__ import annotations

import pandas as pd
import pytest

from quantbt import (
    AccountConfig,
    BacktestEngineV2,
    BacktestResultV2,
    EventDrivenBacktestEngine,
    OrderIntent,
    OrderSide,
    OrderType,
    PortfolioBacktestEngine,
    TimeInForce,
)


def _bars():
    idx = pd.date_range("2024-01-01", periods=4, freq="1D", tz="UTC")
    return pd.DataFrame(
        {
            "open": [100.0, 100.0, 110.0, 120.0],
            "high": [100.0, 101.0, 112.0, 121.0],
            "low": [100.0, 99.0, 94.0, 119.0],
            "close": [100.0, 100.0, 110.0, 120.0],
            "volume": [1_000.0, 1_100.0, 1_200.0, 1_300.0],
        },
        index=idx,
    )


def test_backtest_engine_v2_routes_single_symbol_vectorized_signal():
    df = _bars()
    signal = pd.Series([0.0, 1.0, 1.0, 0.0], index=df.index)

    engine = BacktestEngineV2(
        data=df,
        signals=signal,
        symbols=["BTC"],
        backend="native_vectorized",
        account=AccountConfig(initial_capital=10_000.0, leverage=10.0),
        alloc_per_trade=1_000.0,
        use_funding=False,
    )

    assert isinstance(engine.result, BacktestResultV2)
    assert engine.result.metadata["backend"] == "native_vectorized"
    assert engine.result.positions["Position_BTC"].iloc[1] == 10.0


def test_backtest_engine_v2_keeps_timestamped_frame_values_sorted_with_index():
    df = pd.DataFrame(
        {
            "Date": ["2024-01-02", "2024-01-01"],
            "Close": [200.0, 100.0],
            "High": [201.0, 101.0],
            "Low": [199.0, 99.0],
        }
    )
    signal = pd.Series(
        [0.0, 1.0],
        index=pd.to_datetime(["2024-01-01", "2024-01-02"], utc=True),
    )

    engine = BacktestEngineV2(
        data=df,
        signals=signal,
        symbols=["BTC"],
        account=AccountConfig(initial_capital=10_000.0, leverage=10.0),
        alloc_per_trade=1_000.0,
        use_funding=False,
    )

    assert engine.result.closes["Close_BTC"].iloc[0] == 100.0
    assert engine.result.closes["Close_BTC"].iloc[1] == 200.0


def test_event_driven_backtest_engine_routes_explicit_orders():
    df = _bars()
    order = OrderIntent(
        timestamp=df.index[1],
        symbol="BTC",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        qty=10.0,
        price=99.0,
        tif=TimeInForce.GTC,
    )

    engine = EventDrivenBacktestEngine(
        data=df,
        symbols=["BTC"],
        orders=[order],
        account=AccountConfig(initial_capital=10_000.0, leverage=10.0),
        use_funding=False,
    )

    assert engine.result.metadata["backend"] == "native_event"
    assert len(engine.result.fills) == 1
    assert engine.result.fills[0].price == 99.0


def test_portfolio_backtest_engine_wraps_legacy_portfolio_as_v2_result():
    df = _bars()
    positions = {
        "BTC": pd.Series([0.0, 1.0, 1.0, 0.0], index=df.index),
        "ETH": pd.Series([0.0, -1.0, -1.0, 0.0], index=df.index),
    }
    closes = {"BTC": df["close"], "ETH": df["close"] * 0.1}

    engine = PortfolioBacktestEngine(
        positions=positions,
        closes=closes,
        datetime_index=df.index,
        mode="market_neutral",
        account=AccountConfig(initial_capital=10_000.0, leverage=10.0),
        use_funding=False,
    )

    assert isinstance(engine.result, BacktestResultV2)
    assert engine.result.metadata["backend"] == "legacy_portfolio"
    assert "Position_BTC" in engine.result.positions.columns


def test_backtest_engine_v2_rejects_unknown_backend():
    with pytest.raises(ValueError):
        BacktestEngineV2(backend="unknown", auto_run=False)
