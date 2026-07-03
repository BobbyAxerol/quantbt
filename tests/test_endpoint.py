from __future__ import annotations

import pandas as pd

from quantbt import (
    AccountConfig,
    BasketLegSpec,
    BasketSpec,
    OrderIntent,
    OrderSide,
    OrderType,
    QuantBTEndpoint,
    TimeInForce,
)


def _bars():
    idx = pd.date_range("2024-01-01", periods=5, freq="1D", tz="UTC")
    return pd.DataFrame(
        {
            "open": [100.0, 100.0, 110.0, 120.0, 115.0],
            "high": [100.0, 101.0, 112.0, 121.0, 116.0],
            "low": [100.0, 99.0, 94.0, 113.0, 112.0],
            "close": [100.0, 100.0, 110.0, 120.0, 115.0],
            "volume": [1_000.0, 1_100.0, 1_200.0, 1_300.0, 1_400.0],
        },
        index=idx,
    )


def test_endpoint_pct_equity_uses_legacy_backtester():
    df = _bars()
    df["pos"] = [0.0, 1.0, 1.0, 0.0, 0.0]

    endpoint = QuantBTEndpoint.pct_equity(
        initial_capital=10_000.0,
        leverage=5.0,
        alloc_per_trade=0.5,
        fee=0.0004,
        use_funding=False,
    )
    result = endpoint.backtest(data=df, signal_col="pos")

    assert result.metadata["hedge_type"] == "%_equity"
    assert result.initial_capital == 10_000.0
    assert endpoint.full_report()["num_trades"] >= 2


def test_endpoint_signal_notional_vectorized_and_event_match():
    df = _bars()
    signal = pd.Series([0.0, 1.0, 1.0, 0.0, 0.0], index=df.index)
    common = dict(
        initial_capital=10_000.0,
        leverage=10.0,
        alloc_per_trade=1_000.0,
        fee_rate=0.0,
        use_funding=False,
    )

    vectorized = QuantBTEndpoint.signal_notional(backend="native_vectorized", **common)
    event = QuantBTEndpoint.signal_notional(backend="native_event", **common)

    r_vec = vectorized.backtest(data=df, signal=signal, symbols=["BTC"])
    r_evt = event.backtest(data=df, signal=signal, symbols=["BTC"])

    assert r_vec.equity.equals(r_evt.equity)
    assert len(r_evt.fills) == 2


def test_endpoint_orders_simulation():
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

    endpoint = QuantBTEndpoint.orders(initial_capital=10_000.0, leverage=10.0, use_funding=False)
    result = endpoint.simulate(data=df, orders=[order], symbols=["BTC"])

    assert result.metadata["backend"] == "native_event"
    assert len(result.fills) == 1
    assert result.fills[0].price == 99.0


def test_endpoint_basket_simulation():
    df = _bars()
    signal = pd.Series([0.0, 1.0, 1.0, 0.0, 0.0], index=df.index)
    basket = BasketSpec(
        basket_id="PAIR-001",
        legs=(
            BasketLegSpec(symbol="BASE", ratio=1.0),
            BasketLegSpec(symbol="HEDGE", ratio=-0.5),
        ),
        gross_notional=1_000.0,
    )
    data = {"BASE": df, "HEDGE": df.assign(close=df["close"] * 2.0)}

    endpoint = QuantBTEndpoint.basket(basket=basket, initial_capital=10_000.0, leverage=10.0, use_funding=False)
    result = endpoint.simulate(data=data, signal=signal)

    assert result.metadata["backend"] == "native_event"
    assert "basket_target_units" in result.metadata


def test_endpoint_portfolio_accepts_positions_dataframe_and_data_dict():
    df = _bars()
    positions = pd.DataFrame(
        {
            "BTC": [0.0, 1.0, 1.0, 0.0, 0.0],
            "ETH": [0.0, -1.0, -1.0, 0.0, 0.0],
        },
        index=df.index,
    )
    data = {"BTC": df, "ETH": df.assign(close=df["close"] * 0.1)}

    endpoint = QuantBTEndpoint.portfolio(
        portfolio_mode="market_neutral",
        initial_capital=10_000.0,
        leverage=10.0,
        alloc_per_trade=1_000.0,
        use_funding=False,
    )
    result = endpoint.backtest(data=data, positions=positions)

    assert result.metadata["backend"] == "legacy_portfolio"
    assert "Position_BTC" in result.positions.columns


def test_endpoint_dca_ladder_requires_high_low_and_runs():
    df = _bars()
    signal = pd.Series([0, 2, 2, 0, 0], index=df.index)

    endpoint = QuantBTEndpoint.dca_ladder(
        initial_capital=20_000.0,
        leverage=5.0,
        alloc_per_trade=1_000.0,
        dca_max_safety_orders=1,
        dca_step_pct=0.01,
        use_funding=False,
    )
    result = endpoint.backtest(data=df, signal=signal)

    assert result.metadata["hedge_type"] == "dca_ladder"
    assert result.metadata["dca_actual_level"] is not None
