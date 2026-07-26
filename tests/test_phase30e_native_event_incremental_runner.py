from __future__ import annotations

import numpy as np
import pandas as pd

from quantbt import OrderCommand, OrderSide, OrderType, QuantBTEndpoint, TimeInForce
from quantbt.core.orders import OrderAction


def _bars(n: int = 8) -> pd.DataFrame:
    idx = pd.date_range("2024-01-01", periods=n, freq="1h", tz="UTC")
    base = 100.0 + np.sin(np.arange(n) / 2.0)
    return pd.DataFrame(
        {
            "open": base,
            "high": base + 3.0,
            "low": base - 3.0,
            "close": base,
            "volume": 1_000.0,
        },
        index=idx,
    )


def test_static_cancel_all_can_scope_by_side_and_symbol_without_old_behavior_change():
    df = _bars(5)
    commands = [
        OrderCommand(
            timestamp=df.index[1],
            action=OrderAction.PLACE,
            symbol="BTC",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            qty=1.0,
            price=90.0,
            tif=TimeInForce.GTC,
            order_id="buy-low",
        ),
        OrderCommand(
            timestamp=df.index[1],
            action=OrderAction.PLACE,
            symbol="BTC",
            side=OrderSide.SELL,
            order_type=OrderType.LIMIT,
            qty=1.0,
            price=110.0,
            tif=TimeInForce.GTC,
            order_id="sell-high",
        ),
        OrderCommand(
            timestamp=df.index[2],
            action=OrderAction.CANCEL_ALL,
            symbol="BTC",
            side=OrderSide.BUY,
        ),
    ]

    bt = QuantBTEndpoint.native_event_lifecycle(initial_capital=10_000, leverage=10, use_funding=False)
    result = bt.simulate(data=df, order_commands=commands, symbols=["BTC"])
    report = result.metadata["command_report"].set_index("order_id")

    assert int(report.loc["buy-low", "status"]) == 2
    assert int(report.loc["sell-high", "status"]) == 0
    assert result.metadata["reactive_context_builder"] if "reactive_context_builder" in result.metadata else True


def test_reactive_incremental_runner_expands_tag_prefix_cancel_all_to_targeted_cancels():
    df = _bars(7)

    class Strategy:
        def on_bar_close(self, context):
            if context.bar_index == 0:
                return [
                    OrderCommand(
                        timestamp=context.timestamp,
                        action=OrderAction.PLACE,
                        symbol="BTC",
                        side=OrderSide.BUY,
                        order_type=OrderType.LIMIT,
                        qty=1.0,
                        price=90.0,
                        tif=TimeInForce.GTC,
                        order_id="grid-c1-l1",
                        tag="GRID-C1-L1-ENTRY",
                    ),
                    OrderCommand(
                        timestamp=context.timestamp,
                        action=OrderAction.PLACE,
                        symbol="BTC",
                        side=OrderSide.BUY,
                        order_type=OrderType.LIMIT,
                        qty=1.0,
                        price=89.0,
                        tif=TimeInForce.GTC,
                        order_id="grid-c2-l1",
                        tag="GRID-C2-L1-ENTRY",
                    ),
                ]
            if context.bar_index == 1:
                return [
                    OrderCommand(
                        timestamp=context.timestamp,
                        action=OrderAction.CANCEL_ALL,
                        symbol="BTC",
                        tag_prefix="GRID-C1",
                    )
                ]
            return []

    bt = QuantBTEndpoint.native_event_strategy(initial_capital=10_000, leverage=10, use_funding=False)
    result = bt.simulate(data=df, strategy=Strategy(), symbols=["BTC"])
    tape = result.metadata["emitted_command_tape"]
    report = result.metadata["command_report"].set_index("order_id")

    assert result.metadata["reactive_context_builder"] == "incremental_session_v1"
    assert result.metadata["reactive_incremental_compile_replays"] == 0
    assert any(command.action is OrderAction.CANCEL and command.target_order_id == "grid-c1-l1" for command in tape)
    assert not any(command.action is OrderAction.CANCEL_ALL for command in tape)
    assert int(report.loc["grid-c1-l1", "status"]) == 2
    assert int(report.loc["grid-c2-l1", "status"]) == 0


def test_reactive_audit_records_incremental_vs_static_final_state_diff():
    df = _bars(6)

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
                        order_id="entry",
                    )
                ]
            return []

    bt = QuantBTEndpoint.native_event_strategy(
        initial_capital=10_000,
        leverage=10,
        use_funding=False,
        reactive_execution_mode="audit",
    )
    result = bt.simulate(data=df, strategy=Strategy(), symbols=["BTC"])

    assert result.metadata["reactive_audit"]["final_equity_diff"] == 0.0
    assert result.metadata["reactive_audit"]["final_position_diff"]["BTC"] == 0.0


def test_reactive_dynamic_grid_smoke_static_replay_parity():
    df = _bars(200)

    class DynamicGrid:
        def __init__(self):
            self.cycle = 0

        def on_bar_close(self, context):
            commands = []
            if context.bar_index % 20 == 0:
                self.cycle += 1
                commands.append(
                    OrderCommand(
                        timestamp=context.timestamp,
                        action=OrderAction.CANCEL_ALL,
                        symbol="BTC",
                        tag_prefix="GRID-",
                    )
                )
                for level in range(1, 6):
                    px = float(context.close[0] - 0.2 * level)
                    commands.append(
                        OrderCommand(
                            timestamp=context.timestamp,
                            symbol="BTC",
                            side=OrderSide.BUY,
                            order_type=OrderType.LIMIT,
                            qty=0.1,
                            price=px,
                            tif=TimeInForce.GTC,
                            order_id=f"grid-{self.cycle}-{level}",
                            tag=f"GRID-C{self.cycle}-L{level}",
                            metadata={"campaign_id": "GRID", "cycle_id": str(self.cycle), "level_id": str(level)},
                        )
                    )
            if context.positions["BTC"] > 0.0 and context.bar_index % 25 == 0:
                commands.append(
                    OrderCommand(
                        timestamp=context.timestamp,
                        symbol="BTC",
                        side=OrderSide.SELL,
                        order_type=OrderType.MARKET,
                        qty=abs(context.positions["BTC"]),
                        tif=TimeInForce.IOC,
                        reduce_only=True,
                        order_id=f"flatten-{context.bar_index}",
                    )
                )
            return commands

    bt = QuantBTEndpoint.native_event_strategy(initial_capital=10_000, leverage=10, use_funding=False)
    reactive = bt.simulate(data=df, strategy=DynamicGrid(), symbols=["BTC"])
    replay = QuantBTEndpoint.native_event_lifecycle(initial_capital=10_000, leverage=10, use_funding=False).simulate(
        data=df,
        order_commands=reactive.metadata["emitted_command_tape"],
        symbols=["BTC"],
    )

    pd.testing.assert_series_equal(reactive.equity, replay.equity)
    pd.testing.assert_frame_equal(reactive.positions, replay.positions)
    assert len(reactive.metadata["emitted_command_tape"]) > 20
