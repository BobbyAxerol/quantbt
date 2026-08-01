from __future__ import annotations

import pytest

from quantbt import OrderCommand, OrderSide, OrderType, TimeInForce

from .conftest import bars, run_reactive


def test_native_event_initialize_and_bar0_ordering():
    df = bars(6)

    class Strategy:
        def __init__(self):
            self.calls = []

        def initialize(self, context):
            self.calls.append(("initialize", context.bar_index))
            return [
                OrderCommand(
                    timestamp=context.timestamp,
                    symbol="BTC",
                    side=OrderSide.BUY,
                    order_type=OrderType.MARKET,
                    qty=1.0,
                    tif=TimeInForce.IOC,
                    order_id="init-entry",
                )
            ]

        def on_bar_close(self, context):
            self.calls.append(("on_bar_close", context.bar_index))
            if context.bar_index == 0:
                return [
                    OrderCommand(
                        timestamp=context.timestamp,
                        symbol="BTC",
                        side=OrderSide.SELL,
                        order_type=OrderType.MARKET,
                        qty=1.0,
                        tif=TimeInForce.IOC,
                        reduce_only=True,
                        order_id="bar0-exit",
                    )
                ]
            return []

    strategy = Strategy()
    result = run_reactive("replay_certified", strategy, data=df)
    tape = result.metadata["emitted_command_tape"]

    assert strategy.calls[:2] == [("initialize", 0), ("on_bar_close", 0)]
    assert [cmd.order_id for cmd in tape[:2]] == ["init-entry", "bar0-exit"]
    assert [cmd.timestamp for cmd in tape[:2]] == [df.index[1], df.index[1]]
    assert [fill.order_id for fill in result.fills] == ["init-entry", "bar0-exit"]
    assert [fill.timestamp for fill in result.fills] == [df.index[1], df.index[1]]


def test_native_event_commands_effective_next_bar():
    df = bars(5)

    class Strategy:
        def on_bar_close(self, context):
            if context.bar_index == 0:
                return [
                    OrderCommand(
                        timestamp=context.timestamp,
                        symbol="BTC",
                        side=OrderSide.BUY,
                        order_type=OrderType.LIMIT,
                        qty=1.0,
                        price=float(df["close"].iloc[0]),
                        tif=TimeInForce.GTC,
                        order_id="next-bar-limit",
                    )
                ]
            return []

    result = run_reactive("replay_certified", Strategy(), data=df)
    assert result.metadata["emitted_command_tape"][0].timestamp == df.index[1]
    assert result.fills[0].timestamp == df.index[1]


def test_native_event_same_bar_command_sequence():
    df = bars(6)

    class Strategy:
        def on_bar_close(self, context):
            if context.bar_index == 0:
                return [
                    OrderCommand(
                        timestamp=context.timestamp,
                        symbol="BTC",
                        side=OrderSide.BUY,
                        order_type=OrderType.MARKET,
                        qty=1.0,
                        tif=TimeInForce.IOC,
                        order_id="seq-1",
                    ),
                    OrderCommand(
                        timestamp=context.timestamp,
                        symbol="BTC",
                        side=OrderSide.SELL,
                        order_type=OrderType.MARKET,
                        qty=1.0,
                        tif=TimeInForce.IOC,
                        reduce_only=True,
                        order_id="seq-2",
                    ),
                ]
            return []

    result = run_reactive("replay_certified", Strategy(), data=df)
    report = result.metadata["command_report"].sort_values("original_index")

    assert [cmd.order_id for cmd in result.metadata["emitted_command_tape"]] == ["seq-1", "seq-2"]
    assert report["order_id"].tolist() == ["seq-1", "seq-2"]
    assert [fill.order_id for fill in result.fills] == ["seq-1", "seq-2"]


@pytest.mark.xfail(reason="Phase 43A freeze: finalize commands are currently discarded when effective_bar is beyond data")
def test_native_event_finalize_command_is_recorded_beyond_executable_tape():
    df = bars(4)

    class Strategy:
        def finalize(self, context):
            return [
                OrderCommand(
                    timestamp=context.timestamp,
                    symbol="BTC",
                    side=OrderSide.BUY,
                    order_type=OrderType.MARKET,
                    qty=1.0,
                    tif=TimeInForce.IOC,
                    order_id="finalize-outside-tape",
                )
            ]

    result = run_reactive("replay_certified", Strategy(), data=df)
    tape = result.metadata["emitted_command_tape"]

    assert len(result.fills) == 0
    assert len(tape) == 1
    assert tape[0].order_id == "finalize-outside-tape"
