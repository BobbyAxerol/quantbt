from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from quantbt import QuantBTEndpoint, QuantBTPreparedContext


def test_phase16_prepared_single_signal_context_matches_normal_endpoint_and_updates_latest_result():
    idx = pd.date_range("2024-01-01", periods=80, freq="1h", tz="UTC")
    close = pd.Series(100.0 + np.sin(np.linspace(0.0, 12.0, len(idx))).cumsum() * 0.05, index=idx)
    data = pd.DataFrame(
        {
            "open": close,
            "high": close * 1.002,
            "low": close * 0.998,
            "close": close,
            "volume": 1_000.0,
        },
        index=idx,
    )
    signal = pd.Series(np.sign(np.sin(np.linspace(0.0, 8.0, len(idx)))), index=idx)

    normal_endpoint = QuantBTEndpoint.signal_notional(
        initial_capital=20_000.0,
        leverage=3.0,
        alloc_per_trade=5_000.0,
        fee_rate=0.0002,
        use_funding=False,
        slippage=0.0001,
        use_pyramiding=True,
    )
    normal = normal_endpoint.backtest(data=data, signal=signal, symbols=["BTC"])

    prepared_endpoint = QuantBTEndpoint.signal_notional(
        initial_capital=20_000.0,
        leverage=3.0,
        alloc_per_trade=5_000.0,
        fee_rate=0.0002,
        use_funding=False,
        slippage=0.0001,
        use_pyramiding=True,
    )
    context = prepared_endpoint.prepare_service_context(data=data, symbols=["BTC"])
    prepared = context.backtest(signal=signal)

    assert isinstance(context, QuantBTPreparedContext)
    assert prepared_endpoint.result is prepared
    assert prepared.metadata["prepared_service_context"]["runs"] == 1
    np.testing.assert_allclose(prepared.equity.to_numpy(), normal.equity.to_numpy(), rtol=0.0, atol=1e-10)
    np.testing.assert_allclose(prepared.positions.to_numpy(), normal.positions.to_numpy(), rtol=0.0, atol=1e-12)
    np.testing.assert_allclose(prepared.fees.to_numpy(), normal.fees.to_numpy(), rtol=0.0, atol=1e-12)


def test_phase16_prepared_portfolio_context_matches_normal_endpoint_core_accounting():
    idx = pd.date_range("2024-01-01", periods=90, freq="1h", tz="UTC")
    symbols = ["BTC", "ETH", "SOL"]
    data = {}
    positions = {}
    for j, symbol in enumerate(symbols):
        close = pd.Series(100.0 + j * 20.0 + np.sin(np.linspace(0.0, 10.0, len(idx)) + j), index=idx)
        data[symbol] = pd.DataFrame(
            {
                "open": close,
                "high": close * 1.002,
                "low": close * 0.998,
                "close": close,
                "volume": 1_000.0,
            },
            index=idx,
        )
        positions[symbol] = np.sign(np.sin(np.linspace(0.0, 6.0, len(idx)) + j))
    positions_df = pd.DataFrame(positions, index=idx)

    kwargs = dict(
        portfolio_mode="market_neutral",
        backend="native_portfolio",
        hedge_type="signal_notional",
        initial_capital=100_000.0,
        leverage=4.0,
        alloc_per_trade={symbol: 5_000.0 for symbol in symbols},
        fee=0.0004,
        use_funding=False,
        report_level="minimal",
    )
    normal_endpoint = QuantBTEndpoint.portfolio(**kwargs)
    normal = normal_endpoint.backtest(data=data, positions=positions_df, symbols=symbols)

    prepared_endpoint = QuantBTEndpoint.portfolio(**kwargs)
    context = prepared_endpoint.prepare_service_context(data=data, symbols=symbols)
    prepared = context.backtest(positions=positions_df)

    assert prepared.metadata["prepared_service_context"]["runs"] == 1
    np.testing.assert_allclose(prepared.equity.to_numpy(), normal.equity.to_numpy(), rtol=0.0, atol=1e-10)
    np.testing.assert_allclose(prepared.returns.to_numpy(), normal.returns.to_numpy(), rtol=0.0, atol=1e-12)
    np.testing.assert_allclose(prepared.positions.to_numpy(), normal.positions.to_numpy(), rtol=0.0, atol=1e-12)
    np.testing.assert_allclose(prepared.fees.to_numpy(), normal.fees.to_numpy(), rtol=0.0, atol=1e-12)
    np.testing.assert_allclose(prepared.margin.to_numpy(), normal.margin.to_numpy(), rtol=0.0, atol=1e-10)


def test_phase16_prepared_context_rejects_unsupported_legacy_pct_equity():
    idx = pd.date_range("2024-01-01", periods=5, freq="1h", tz="UTC")
    data = pd.DataFrame({"close": 100.0}, index=idx)
    endpoint = QuantBTEndpoint.pct_equity(initial_capital=20_000.0)

    with pytest.raises(NotImplementedError, match="prepared service context"):
        endpoint.prepare_service_context(data=data)
