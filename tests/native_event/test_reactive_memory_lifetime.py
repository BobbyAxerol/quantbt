from __future__ import annotations

import gc
import tracemalloc

from quantbt import OrderCommand, OrderSide, OrderType, QuantBTEndpoint, TimeInForce

from .conftest import SEED, bars


class LowChurnStrategy:
    def __init__(self, entry_bar: int = 0, exit_bar: int = 8):
        self.entry_bar = int(entry_bar)
        self.exit_bar = int(exit_bar)

    def on_bar_close(self, context):
        if context.bar_index == self.entry_bar:
            return [
                OrderCommand(
                    timestamp=context.timestamp,
                    symbol="BTC",
                    side=OrderSide.BUY,
                    order_type=OrderType.MARKET,
                    qty=1.0,
                    tif=TimeInForce.IOC,
                    order_id=f"entry-{self.entry_bar}",
                )
            ]
        if context.bar_index == self.exit_bar:
            return [
                OrderCommand(
                    timestamp=context.timestamp,
                    symbol="BTC",
                    side=OrderSide.SELL,
                    order_type=OrderType.MARKET,
                    qty=1.0,
                    tif=TimeInForce.IOC,
                    reduce_only=True,
                    order_id=f"exit-{self.exit_bar}",
                )
            ]
        return []


def _prepared(n=64):
    endpoint = QuantBTEndpoint.native_event_strategy(
        initial_capital=10_000,
        leverage=10,
        use_funding=False,
        fee_rate=0.0002,
        report_level="audit",
    )
    return endpoint.prepare_native_event_strategy(data=bars(n), symbols=["BTC"])


def test_native_event_score_no_pandas_materialization():
    prepared = _prepared()
    score = prepared.score(LowChurnStrategy())

    assert score.metadata["engine"] == "event_v2_reactive_score"
    assert not hasattr(score, "fills")
    assert not hasattr(score, "orders")
    assert score.equity.ndim == 1
    assert score.positions.ndim == 2


def test_native_event_score_does_not_retain_terminal_orders():
    prepared = _prepared()
    score = prepared.score(LowChurnStrategy())

    assert "command_report" not in score.metadata
    assert "order_events" not in score.metadata
    assert "emitted_command_tape" not in score.metadata


def test_native_event_consumed_queues_are_released():
    prepared = _prepared()
    for i in range(10):
        prepared.score(LowChurnStrategy(entry_bar=i % 3, exit_bar=8 + i % 5))

    assert prepared.metadata["scores"] == 10
    assert prepared.metadata.get("last_score_fill_count", 0) <= 2


def test_native_event_repeated_score_rss_plateaus():
    prepared = _prepared(96)
    gc.collect()
    tracemalloc.start()
    try:
        for i in range(30):
            prepared.score(LowChurnStrategy(entry_bar=i % 5, exit_bar=12 + i % 7))
        current, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()

    assert prepared.metadata["scores"] == 30, f"seed={SEED}"
    assert current < 2_000_000, f"seed={SEED} current={current}"
    assert peak < 8_000_000, f"seed={SEED} peak={peak}"
