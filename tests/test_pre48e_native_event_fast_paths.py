from __future__ import annotations

import numpy as np
import pandas as pd

from quantbt import OrderCommand, OrderSide, OrderType, QuantBTEndpoint, TimeInForce


def _bars(n: int = 32) -> pd.DataFrame:
    index = pd.date_range("2024-01-01", periods=n, freq="h", tz="UTC")
    close = 100.0 + np.arange(n, dtype=np.float64)
    return pd.DataFrame(
        {
            "open": close,
            "high": close + 1.0,
            "low": close - 1.0,
            "close": close,
            "volume": 1_000.0,
        },
        index=index,
    )


class SparseStrategy:
    def initialize(self, context):
        return ()

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
                    order_id="entry",
                ),
            )
        if context.bar_index == 8:
            return (
                OrderCommand(
                    timestamp=context.timestamp,
                    symbol="BTC",
                    side=OrderSide.SELL,
                    order_type=OrderType.MARKET,
                    qty=1.0,
                    tif=TimeInForce.IOC,
                    reduce_only=True,
                    order_id="exit",
                ),
            )
        return ()

    def finalize(self, context):
        return ()


def _endpoint(**kwargs):
    return QuantBTEndpoint.native_event_strategy(
        initial_capital=10_000.0,
        leverage=5.0,
        maintenance_ratio=0.0,
        fee_rate=0.0002,
        use_funding=False,
        native_backend="python",
        reactive_kernel_mode="single_pass",
        report_level="score",
        **kwargs,
    )


def test_pre48e_empty_batches_skip_retime_and_quantity_preflight():
    result = _endpoint().simulate(data=_bars(), strategy=SparseStrategy(), symbols=["BTC"])
    counters = result.metadata["execution_counters"]

    assert counters["bars_processed"] == len(_bars())
    assert counters["contexts_materialized"] == len(_bars()) + 1
    assert counters["bars_with_commands"] == 2
    assert counters["empty_command_batches_skipped"] >= len(_bars()) - 1
    assert counters["constraint_preflight_calls"] == 0
    assert counters["constraint_preflight_skipped"] == 2


def test_pre48e_zero_constraint_fast_path_matches_explicit_zero_constraint_path():
    data = _bars()
    base = _endpoint().simulate(data=data, strategy=SparseStrategy(), symbols=["BTC"])
    explicit_zero = _endpoint(qty_step=0.0, min_qty=0.0, min_notional=0.0).simulate(
        data=data,
        strategy=SparseStrategy(),
        symbols=["BTC"],
    )

    pd.testing.assert_series_equal(base.equity, explicit_zero.equity)
    pd.testing.assert_frame_equal(base.positions, explicit_zero.positions)
    pd.testing.assert_series_equal(base.fees, explicit_zero.fees)
    pd.testing.assert_series_equal(base.funding, explicit_zero.funding)
    assert base.metadata["lifecycle_counters"] == explicit_zero.metadata["lifecycle_counters"]


def test_pre48e_enabled_constraints_keep_quantity_preflight():
    result = _endpoint(qty_step=0.1, min_qty=0.1).simulate(
        data=_bars(),
        strategy=SparseStrategy(),
        symbols=["BTC"],
    )
    counters = result.metadata["execution_counters"]

    assert counters["constraint_preflight_calls"] == 2
    assert counters["constraint_preflight_skipped"] == 0
    assert counters["commands_quantized"] == 2
