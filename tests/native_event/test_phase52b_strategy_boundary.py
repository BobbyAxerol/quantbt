from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from quantbt import (
    CallbackSchedule,
    CommandWriter,
    OrderCommand,
    OrderSide,
    OrderType,
    QuantBTEndpoint,
    ResourceLimitError,
    StaleStrategyContextError,
    StrategyContextRequirements,
    TimeInForce,
)


def _bars(n: int = 24) -> pd.DataFrame:
    index = pd.date_range("2026-01-01", periods=n, freq="h", tz="UTC")
    close = 100.0 + np.linspace(0.0, 6.0, n)
    return pd.DataFrame(
        {
            "open": close - 0.1,
            "high": close + 0.8,
            "low": close - 0.8,
            "close": close,
            "volume": np.full(n, 10.0),
        },
        index=index,
    )


def _endpoint():
    return QuantBTEndpoint.native_event_strategy(
        initial_capital=10_000.0,
        leverage=5.0,
        use_funding=False,
        fee_rate=0.0002,
        report_level="minimal",
        reactive_kernel_mode="single_pass",
        native_backend="python",
    )


class LegacyStrategy:
    def on_bar_close(self, context):
        if context.bar_index == 2:
            return (
                OrderCommand(
                    timestamp=context.timestamp,
                    symbol="BTC",
                    side=OrderSide.BUY,
                    order_type=OrderType.MARKET,
                    qty=1.0,
                    tif=TimeInForce.IOC,
                    order_id="qbt-1",
                ),
            )
        if context.bar_index == 12:
            return (
                OrderCommand(
                    timestamp=context.timestamp,
                    symbol="BTC",
                    side=OrderSide.SELL,
                    order_type=OrderType.MARKET,
                    qty=1.0,
                    tif=TimeInForce.IOC,
                    reduce_only=True,
                    order_id="qbt-2",
                ),
            )
        return ()


class NumericStrategy:
    quantbt_requirements = StrategyContextRequirements(
        market=("close",),
        account=("equity", "liquidated"),
        positions=("qty",),
        fills="none",
        events="none",
        active_orders="none",
        context_mode="numeric",
    )

    def __init__(self):
        self.retained = None

    def on_bar_close(self, context, out):
        assert context.timestamp_ns > 0
        assert context.close(0) > 0.0
        if context.bar_index == 2:
            self.retained = context
            out.market(0, 1, 1.0, order_handle=1, tif=TimeInForce.IOC)
        elif context.bar_index == 12:
            out.market(0, -1, 1.0, order_handle=2, tif=TimeInForce.IOC, reduce_only=True)


def test_numeric_context_and_writer_preserve_legacy_accounting():
    frame = _bars()
    legacy = _endpoint().simulate(data=frame, strategy=LegacyStrategy(), symbols=["BTC"])
    strategy = NumericStrategy()
    numeric = _endpoint().simulate(data=frame, strategy=strategy, symbols=["BTC"])

    np.testing.assert_array_equal(numeric.equity.to_numpy(), legacy.equity.to_numpy())
    np.testing.assert_array_equal(numeric.positions.to_numpy(), legacy.positions.to_numpy())
    np.testing.assert_array_equal(numeric.fees.to_numpy(), legacy.fees.to_numpy())
    boundary = numeric.metadata["strategy_boundary"]
    assert boundary["context_mode"] == "numeric"
    assert boundary["legacy_command_objects"] == 0
    assert boundary["writer_command_rows"] == 2
    with pytest.raises(StaleStrategyContextError):
        _ = strategy.retained.equity


def test_sparse_schedule_calls_only_declared_bars_without_hidden_callbacks():
    class SparseStrategy:
        quantbt_requirements = StrategyContextRequirements(
            market=("close",),
            account=("equity", "liquidated"),
            positions=(),
            fills="none",
            events="none",
            active_orders="none",
            callback=CallbackSchedule(
                every_n_bars=None,
                explicit_bars=(0, 5, 10, 15, 20),
                on_fill=False,
                on_order_event=False,
                on_liquidation=True,
            ),
            context_mode="numeric",
        )

        def on_bar_close(self, context, out):
            return None

    result = _endpoint().simulate(data=_bars(), strategy=SparseStrategy(), symbols=["BTC"])
    boundary = result.metadata["strategy_boundary"]
    assert boundary["python_callbacks"] == 5
    assert boundary["skipped_callbacks"] == 19
    assert result.metadata["strategy_callback_count"] == 5


def test_command_writer_reuses_capacity_and_enforces_limit():
    writer = CommandWriter(initial_capacity=1, hard_limit=3)
    writer.market(0, 1, 1.0)
    first = writer.finish()
    assert len(first.to_order_commands(timestamp=pd.Timestamp("2026-01-01", tz="UTC"), symbols=("BTC",))) == 1
    writer.reset()
    writer.market(0, 1, 1.0)
    writer.limit(0, -1, 1.0, 101.0)
    writer.stop_market(0, -1, 1.0, 99.0)
    assert writer.growth_count == 2
    with pytest.raises(ResourceLimitError):
        writer.market(0, 1, 1.0)
    with pytest.raises(RuntimeError, match="stale"):
        first.to_order_commands(timestamp=pd.Timestamp("2026-01-01", tz="UTC"), symbols=("BTC",))

    malformed = CommandWriter()
    malformed.market(0, 1, -1.0)
    with pytest.raises(ValueError, match="qty > 0"):
        malformed.finish().to_order_commands(
            timestamp=pd.Timestamp("2026-01-01", tz="UTC"), symbols=("BTC",)
        )


def test_numeric_callback_exception_contains_strategy_location():
    class Broken:
        quantbt_requirements = StrategyContextRequirements(context_mode="numeric")

        def on_bar_close(self, context, out):
            raise ValueError("bad alpha command")

    with pytest.raises(RuntimeError, match=r"bar_index=0.*strategy_id='.*Broken'.*bad alpha command") as caught:
        _endpoint().simulate(data=_bars(4), strategy=Broken(), symbols=["BTC"])
    assert caught.value.context.strategy_id.endswith("Broken")
