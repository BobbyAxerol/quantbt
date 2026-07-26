from __future__ import annotations

import pandas as pd
import pytest

from quantbt import (
    NativeEventStrategyError,
    OrderCommand,
    OrderSide,
    OrderType,
    QuantBTEndpoint,
    TimeInForce,
)


def _bars() -> pd.DataFrame:
    idx = pd.date_range("2024-01-01", periods=5, freq="1h", tz="UTC")
    return pd.DataFrame(
        {
            "open": [100.0, 100.0, 100.0, 110.0, 100.0],
            "high": [101.0, 101.0, 112.0, 111.0, 101.0],
            "low": [90.0, 98.0, 99.0, 99.0, 99.0],
            "close": [100.0, 100.0, 110.0, 100.0, 100.0],
            "volume": 1_000.0,
        },
        index=idx,
    )


def test_reactive_commands_emit_after_close_and_fill_next_bar_only():
    df = _bars()

    class Strategy:
        def __init__(self):
            self.calls = []

        def on_bar_close(self, context):
            self.calls.append(context.bar_index)
            if context.bar_index == 0:
                return [
                    OrderCommand(
                        timestamp=context.timestamp,
                        symbol="BTC",
                        side=OrderSide.BUY,
                        order_type=OrderType.LIMIT,
                        qty=1.0,
                        price=99.0,
                        tif=TimeInForce.GTC,
                        order_id="entry",
                    )
                ]
            return []

    strategy = Strategy()
    endpoint = QuantBTEndpoint.native_event_strategy(initial_capital=10_000, leverage=10, use_funding=False)
    result = endpoint.simulate(data=df, strategy=strategy, symbols=["BTC"])

    assert strategy.calls == [0, 1, 2, 3, 4]
    assert len(result.fills) == 1
    assert result.fills[0].timestamp == df.index[1]
    assert result.fills[0].price == 99.0
    assert result.metadata["emitted_command_tape"][0].timestamp == df.index[1]


def test_reactive_context_receives_fill_and_rearms_reduce_only_exit_with_static_replay_parity():
    df = _bars()

    class Strategy:
        def __init__(self):
            self.fill_contexts = []

        def initialize(self, context):
            return [
                OrderCommand(
                    timestamp=context.timestamp,
                    symbol="BTC",
                    side=OrderSide.BUY,
                    order_type=OrderType.MARKET,
                    qty=1.0,
                    tif=TimeInForce.IOC,
                    order_id="entry-c1-l1",
                    tag="GRID-C1-L1-ENTRY",
                    metadata={"campaign_id": "C1", "cycle_id": "1", "level_id": "L1"},
                )
            ]

        def on_bar_close(self, context):
            if context.fills_this_bar:
                self.fill_contexts.append(
                    (
                        context.bar_index,
                        context.fills_this_bar[0].order_id,
                        context.fills_this_bar[0].level_id,
                        context.positions["BTC"],
                    )
                )
            if context.bar_index == 1 and context.fills_this_bar:
                qty = context.fills_this_bar[0].qty
                return [
                    OrderCommand(
                        timestamp=context.timestamp,
                        symbol="BTC",
                        side=OrderSide.SELL,
                        order_type=OrderType.LIMIT,
                        qty=qty,
                        price=112.0,
                        tif=TimeInForce.GTC,
                        reduce_only=True,
                        order_id="exit-c1-l1",
                        tag="GRID-C1-L1-EXIT",
                        metadata={"campaign_id": "C1", "cycle_id": "1", "level_id": "L1"},
                    )
                ]
            return []

    strategy = Strategy()
    endpoint = QuantBTEndpoint.native_event_strategy(initial_capital=10_000, leverage=10, use_funding=False)
    reactive = endpoint.simulate(data=df, strategy=strategy, symbols=["BTC"])
    tape = reactive.metadata["emitted_command_tape"]

    replay_endpoint = QuantBTEndpoint.native_event_lifecycle(initial_capital=10_000, leverage=10, use_funding=False)
    replay = replay_endpoint.simulate(data=df, order_commands=tape, symbols=["BTC"])

    assert strategy.fill_contexts[0] == (1, "entry-c1-l1", "L1", 1.0)
    assert [fill.order_id for fill in reactive.fills] == ["entry-c1-l1", "exit-c1-l1"]
    assert reactive.positions["Position_BTC"].iloc[-1] == 0.0
    pd.testing.assert_series_equal(reactive.equity, replay.equity)
    pd.testing.assert_frame_equal(reactive.positions, replay.positions)
    assert [fill.order_id for fill in replay.fills] == [fill.order_id for fill in reactive.fills]


def test_reactive_rejected_command_is_visible_in_next_callback():
    df = _bars()

    class Strategy:
        def __init__(self):
            self.rejected_seen = False

        def on_bar_close(self, context):
            if any(event.event_name == "reject" for event in context.order_events_this_bar):
                self.rejected_seen = True
            if context.bar_index == 0:
                return [
                    OrderCommand(
                        timestamp=context.timestamp,
                        symbol="BTC",
                        side=OrderSide.BUY,
                        order_type=OrderType.MARKET,
                        qty=500.0,
                        tif=TimeInForce.IOC,
                        order_id="too-large",
                    )
                ]
            return []

    strategy = Strategy()
    endpoint = QuantBTEndpoint.native_event_strategy(initial_capital=1_000, leverage=1, use_funding=False)
    result = endpoint.simulate(data=df, strategy=strategy, symbols=["BTC"])

    assert strategy.rejected_seen is True
    assert len(result.fills) == 0
    assert "reject" in set(result.metadata["order_events"]["event_name"])


def test_reactive_context_size_order_uses_backend_quantity_constraints():
    df = _bars()

    class Strategy:
        def __init__(self):
            self.sized_qty = None

        def on_bar_close(self, context):
            if context.bar_index == 0:
                self.sized_qty = context.size_order(symbol="BTC", notional=105.0, price=100.0)
            return []

    strategy = Strategy()
    endpoint = QuantBTEndpoint.native_event_strategy(
        initial_capital=10_000,
        leverage=10,
        use_funding=False,
        qty_step={"BTC": 0.1},
    )
    endpoint.simulate(data=df, strategy=strategy, symbols=["BTC"])

    assert strategy.sized_qty == 1.0


def test_reactive_duplicate_order_id_fails_fast_with_clear_error():
    df = _bars()

    class Strategy:
        def on_bar_close(self, context):
            if context.bar_index in (0, 1):
                return [
                    OrderCommand(
                        timestamp=context.timestamp,
                        symbol="BTC",
                        side=OrderSide.BUY,
                        order_type=OrderType.LIMIT,
                        qty=1.0,
                        price=50.0,
                        order_id="duplicate",
                    )
                ]
            return []

    endpoint = QuantBTEndpoint.native_event_strategy(initial_capital=10_000, leverage=10, use_funding=False)
    with pytest.raises(ValueError, match="duplicate reactive order_id"):
        endpoint.simulate(data=df, strategy=Strategy(), symbols=["BTC"])


def test_reactive_strategy_callback_error_reports_bar_and_timestamp():
    df = _bars()

    class Strategy:
        def on_bar_close(self, context):
            if context.bar_index == 2:
                raise RuntimeError("boom")
            return []

    endpoint = QuantBTEndpoint.native_event_strategy(initial_capital=10_000, leverage=10, use_funding=False)
    with pytest.raises(NativeEventStrategyError) as exc:
        endpoint.simulate(data=df, strategy=Strategy(), symbols=["BTC"])

    assert exc.value.bar_index == 2
    assert exc.value.timestamp == df.index[2]
