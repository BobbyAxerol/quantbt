from __future__ import annotations

import pandas as pd
import pytest

from quantbt import BacktestResult
from quantbt.core.orders import Fill, OrderIntent
from quantbt.core.results import BacktestResultV2
from quantbt.core.schema import (
    AccountConfig,
    ExecutionConfig,
    InstrumentSpec,
    LiquiditySide,
    OrderSide,
    OrderType,
    TimeInForce,
)


def test_account_config_exposes_buying_power_without_scaling_alloc():
    account = AccountConfig(initial_capital=10_000.0, leverage=10.0)

    assert account.initial_buying_power == 100_000.0


def test_execution_config_converts_slippage_bps_to_rate():
    execution = ExecutionConfig(slippage_bps=2.5)

    assert execution.slippage_rate == 0.00025


def test_instrument_spec_validates_core_market_constraints():
    spec = InstrumentSpec(
        symbol="BTCUSDT",
        contract_size=1.0,
        tick_size=0.1,
        lot_size=0.001,
        min_notional=5.0,
    )

    assert spec.symbol == "BTCUSDT"

    with pytest.raises(ValueError):
        InstrumentSpec(symbol="", contract_size=1.0)

    with pytest.raises(ValueError):
        InstrumentSpec(symbol="BTCUSDT", contract_size=0.0)


def test_order_intent_and_fill_keep_signed_quantity_semantics():
    order = OrderIntent(
        timestamp=pd.Timestamp("2024-01-01", tz="UTC"),
        symbol="ETHUSDT",
        side=OrderSide.SELL,
        order_type=OrderType.LIMIT,
        qty=2.0,
        price=2_000.0,
        tif=TimeInForce.GTC,
    )
    fill = Fill(
        timestamp=order.timestamp,
        symbol=order.symbol,
        side=OrderSide.SELL,
        qty=2.0,
        price=2_000.0,
        fee=1.6,
        liquidity=LiquiditySide.MAKER,
    )

    assert order.signed_qty == -2.0
    assert fill.signed_qty == -2.0
    assert fill.notional == 4_000.0


def test_backtest_result_v2_round_trips_legacy_result():
    idx = pd.date_range("2024-01-01", periods=2, freq="1D", tz="UTC")
    legacy = BacktestResult(
        equity=pd.Series([1_000.0, 1_010.0], index=idx, name="equity"),
        returns=pd.Series([0.0, 0.01], index=idx),
        positions=pd.DataFrame({"Position_BTC": [0.0, 1.0]}, index=idx),
        closes=pd.DataFrame({"Close_BTC": [100.0, 101.0]}, index=idx),
        symbols=["BTC"],
        initial_capital=1_000.0,
        leverage=2.0,
        metadata={"engine": "legacy"},
    )

    upgraded = BacktestResultV2.from_legacy(legacy)
    downgraded = upgraded.to_legacy()

    assert upgraded.metadata["engine"] == "legacy"
    assert len(upgraded.orders) == 0
    assert downgraded.symbols == legacy.symbols
    pd.testing.assert_series_equal(downgraded.equity, legacy.equity)
    pd.testing.assert_frame_equal(downgraded.positions, legacy.positions)
