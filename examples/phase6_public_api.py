"""
Phase 6 public API examples.

The examples are intentionally small and deterministic so they can be copied
into notebooks or promoted into regression tests.
"""

from __future__ import annotations

import pandas as pd

from quantbt import (
    AccountConfig,
    BacktestEngineV2,
    BasketLegSpec,
    BasketSpec,
    EventDrivenBacktestEngine,
    OrderIntent,
    OrderSide,
    OrderType,
    PortfolioBacktestEngine,
    TimeInForce,
)


def bars() -> pd.DataFrame:
    idx = pd.date_range("2024-01-01", periods=5, freq="1D", tz="UTC")
    return pd.DataFrame(
        {
            "open": [100.0, 100.0, 102.0, 105.0, 104.0],
            "high": [101.0, 103.0, 106.0, 106.0, 108.0],
            "low": [99.0, 98.0, 101.0, 103.0, 102.0],
            "close": [100.0, 102.0, 105.0, 104.0, 107.0],
            "volume": [1_000.0, 1_100.0, 1_200.0, 1_300.0, 1_400.0],
        },
        index=idx,
    )


def single_order_event():
    df = bars()
    order = OrderIntent(
        timestamp=df.index[1],
        symbol="BTC",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        qty=10.0,
        price=99.0,
        tif=TimeInForce.GTC,
    )
    return EventDrivenBacktestEngine(
        data=df,
        symbols=["BTC"],
        orders=[order],
        account=AccountConfig(initial_capital=10_000.0, leverage=10.0),
        use_funding=False,
    ).result


def dca_grid_vectorized():
    df = bars()
    structural_levels = pd.Series([0.0, 1.0, 2.0, 2.0, 0.0], index=df.index)
    return BacktestEngineV2(
        data=df,
        signals=structural_levels,
        symbols=["BTC"],
        backend="native_vectorized",
        hedge_type="signal_notional",
        alloc_per_trade=1_000.0,
        account=AccountConfig(initial_capital=10_000.0, leverage=10.0),
        use_funding=False,
    ).result


def multi_symbol_portfolio():
    df = bars()
    positions = {
        "BTC": pd.Series([0.0, 1.0, 1.0, 0.0, 0.0], index=df.index),
        "ETH": pd.Series([0.0, -1.0, -1.0, 0.0, 0.0], index=df.index),
    }
    closes = {"BTC": df["close"], "ETH": df["close"] * 0.1}
    return PortfolioBacktestEngine(
        positions=positions,
        closes=closes,
        datetime_index=df.index,
        mode="market_neutral",
        account=AccountConfig(initial_capital=10_000.0, leverage=10.0),
        use_funding=False,
    ).result


def pair_basket_event():
    df = bars()
    signal = pd.Series([0.0, 1.0, 1.0, 0.0, 0.0], index=df.index)
    basket = BasketSpec(
        basket_id="PAIR-001",
        legs=(
            BasketLegSpec(symbol="BASE", ratio=1.0),
            BasketLegSpec(symbol="HEDGE", ratio=-0.5),
        ),
        gross_notional=1_000.0,
    )
    closes = {"BASE": df["close"], "HEDGE": df["close"] * 2.0}
    return BacktestEngineV2(
        backend="native_event",
        basket=basket,
        signal=signal,
        closes=closes,
        highs=closes,
        lows=closes,
        datetime_index=df.index,
        account=AccountConfig(initial_capital=10_000.0, leverage=10.0),
        use_funding=False,
    ).result


def nautilus_validation():
    df = bars()
    signal = pd.Series([0.0, 1.0, 1.0, 0.0, 0.0], index=df.index)
    return BacktestEngineV2(
        data=df,
        signals=signal,
        symbols=["BTCUSDT-PERP.BINANCE"],
        backend="nautilus",
        account=AccountConfig(initial_capital=10_000.0, leverage=10.0),
        alloc_per_trade=1_000.0,
        use_funding=False,
    ).result
