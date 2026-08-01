from __future__ import annotations

import numpy as np

from quantbt import AccountConfig, ExecutionConfig, NativeEventBackend, NativeEventConfig, OrderCommand, OrderSide, OrderType, TimeInForce

from .conftest import ScheduledCommandStrategy, assert_native_event_full_parity, bars, multi_bars, run_reactive


def _c(timestamp, **kwargs) -> OrderCommand:
    return OrderCommand(timestamp=timestamp, **kwargs)


def _assert_strategy_parity(strategy, df=None, symbols=None, **kwargs):
    df = bars(10) if df is None else df
    oracle = run_reactive("replay_certified", strategy, data=df, symbols=symbols, **kwargs)
    candidate = run_reactive("single_pass", strategy, data=df, symbols=symbols, **kwargs)
    assert_native_event_full_parity(candidate, oracle)
    return candidate, oracle


def test_native_event_funding_parity():
    df = bars(12)
    t0 = df.index[0]
    strategy = ScheduledCommandStrategy(
        {
            0: [_c(t0, symbol="BTC", side=OrderSide.BUY, order_type=OrderType.MARKET, qty=2.0, tif=TimeInForce.IOC, order_id="entry")],
            8: [_c(t0, symbol="BTC", side=OrderSide.SELL, order_type=OrderType.MARKET, qty=2.0, tif=TimeInForce.IOC, reduce_only=True, order_id="exit")],
        }
    )

    candidate, _ = _assert_strategy_parity(strategy, df, use_funding=True, funding_rate=0.0001)
    assert float(np.abs(candidate.funding).sum()) > 0.0


def test_native_event_margin_sequence_parity():
    df = bars(8)
    t0 = df.index[0]
    strategy = ScheduledCommandStrategy(
        {
            0: [_c(t0, symbol="BTC", side=OrderSide.BUY, order_type=OrderType.MARKET, qty=500.0, tif=TimeInForce.IOC, order_id="too-large")]
        }
    )

    candidate, _ = _assert_strategy_parity(strategy, df, initial_capital=1_000, leverage=1)
    assert len(candidate.fills) == 0
    assert int(candidate.metadata["lifecycle_counters"]["rejected_count"]) >= 1


def test_native_event_liquidation_priority_parity():
    df = bars(10)
    df.loc[df.index[2], "low"] = 1.0
    df.loc[df.index[2], "close"] = 5.0
    t0 = df.index[0]
    strategy = ScheduledCommandStrategy(
        {
            0: [_c(t0, symbol="BTC", side=OrderSide.BUY, order_type=OrderType.MARKET, qty=20.0, tif=TimeInForce.IOC, order_id="levered-entry")]
        }
    )

    candidate, _ = _assert_strategy_parity(strategy, df, initial_capital=1_000, leverage=10)
    assert candidate.liquidated is True
    assert candidate.liquidation_bar >= 0
    assert int(candidate.metadata["liquidation_reason"]) >= 0


def test_native_event_multisymbol_parity():
    data = multi_bars(12)
    idx = data["BTC"].index
    commands = [
        _c(idx[1], symbol="BTC", side=OrderSide.BUY, order_type=OrderType.MARKET, qty=1.0, tif=TimeInForce.IOC, order_id="btc-entry"),
        _c(idx[1], symbol="ETH", side=OrderSide.SELL, order_type=OrderType.MARKET, qty=1.0, tif=TimeInForce.IOC, order_id="eth-entry"),
        _c(idx[7], symbol="BTC", side=OrderSide.SELL, order_type=OrderType.MARKET, qty=1.0, tif=TimeInForce.IOC, reduce_only=True, order_id="btc-exit"),
        _c(idx[7], symbol="ETH", side=OrderSide.BUY, order_type=OrderType.MARKET, qty=1.0, tif=TimeInForce.IOC, reduce_only=True, order_id="eth-exit"),
    ]
    backend = NativeEventBackend(
        NativeEventConfig(
            account=AccountConfig(initial_capital=20_000, leverage=5),
            execution=ExecutionConfig(slippage_bps=0.0),
            fee_rate=0.0002,
            use_funding=False,
            report_level="audit",
        )
    )
    result = backend.run_order_commands(
        idx,
        commands,
        closes={symbol: frame["close"] for symbol, frame in data.items()},
        highs={symbol: frame["high"] for symbol, frame in data.items()},
        lows={symbol: frame["low"] for symbol, frame in data.items()},
        symbols=["BTC", "ETH"],
    )

    assert list(result.symbols) == ["BTC", "ETH"]
    assert len(result.fills) == 4
    assert result.positions["Position_BTC"].iloc[-1] == 0.0
    assert result.positions["Position_ETH"].iloc[-1] == 0.0
