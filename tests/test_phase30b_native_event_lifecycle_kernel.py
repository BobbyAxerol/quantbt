from __future__ import annotations

import pandas as pd

from quantbt import (
    AccountConfig,
    ExecutionConfig,
    NativeEventBackend,
    NativeEventConfig,
    OrderAction,
    OrderActivationPolicy,
    OrderCommand,
    OrderSide,
    OrderType,
    TimeInForce,
)
from quantbt.core.event import (
    ORDER_STATUS_CANCELED,
    ORDER_STATUS_FILLED,
    ORDER_STATUS_PENDING,
    ORDER_STATUS_REJECTED,
    REJECT_INSUFFICIENT_MARGIN,
    REJECT_REDUCE_ONLY_NO_POSITION,
)
from quantbt.core.order_compiler import order_intents_to_commands
from quantbt.core.orders import OrderIntent


def _backend(initial_capital: float = 10_000.0, leverage: float = 10.0) -> NativeEventBackend:
    return NativeEventBackend(
        NativeEventConfig(
            account=AccountConfig(initial_capital=initial_capital, leverage=leverage),
            execution=ExecutionConfig(slippage_bps=0.0),
            fee_rate=0.0,
            use_funding=False,
        )
    )


def _market():
    idx = pd.date_range("2024-01-01", periods=6, freq="1h", tz="UTC")
    close = pd.Series([100.0, 100.0, 103.0, 108.0, 96.0, 100.0], index=idx)
    high = pd.Series([100.0, 101.0, 106.0, 111.0, 100.0, 101.0], index=idx)
    low = pd.Series([100.0, 99.0, 98.0, 94.0, 89.0, 99.0], index=idx)
    return idx, {"BTC": close}, {"BTC": high}, {"BTC": low}


def test_event_v2_cancel_prevents_later_gtc_limit_fill():
    idx, close, high, low = _market()
    commands = [
        OrderCommand(
            timestamp=idx[1],
            symbol="BTC",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            qty=1.0,
            price=90.0,
            tif=TimeInForce.GTC,
            order_id="entry",
        ),
        OrderCommand(timestamp=idx[2], action=OrderAction.CANCEL, target_order_id="entry"),
    ]

    result = _backend().run_order_commands(idx, commands, close, high, low)
    report = result.metadata["command_report"].sort_values("original_index")

    assert len(result.fills) == 0
    assert int(report.iloc[0]["status"]) == ORDER_STATUS_CANCELED
    assert int(report.iloc[1]["status"]) == ORDER_STATUS_FILLED
    assert result.positions["Position_BTC"].iloc[-1] == 0.0
    assert "cancel" in set(result.metadata["order_events"]["event_name"])


def test_event_v2_replace_cancels_old_slot_and_fills_replacement():
    idx, close, high, low = _market()
    commands = [
        OrderCommand(
            timestamp=idx[1],
            symbol="BTC",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            qty=1.0,
            price=90.0,
            tif=TimeInForce.GTC,
            order_id="entry",
        ),
        OrderCommand(
            timestamp=idx[2],
            action=OrderAction.REPLACE,
            target_order_id="entry",
            symbol="BTC",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            qty=1.0,
            price=99.0,
            tif=TimeInForce.GTC,
            order_id="entry-r1",
        ),
    ]

    result = _backend().run_order_commands(idx, commands, close, high, low)
    report = result.metadata["command_report"].sort_values("original_index")

    assert len(result.fills) == 1
    assert result.fills[0].order_id == "entry-r1"
    assert result.fills[0].price == 99.0
    assert int(report.iloc[0]["status"]) == ORDER_STATUS_CANCELED
    assert int(report.iloc[1]["status"]) == ORDER_STATUS_FILLED


def test_event_v2_amend_updates_working_limit_before_matching():
    idx, close, high, low = _market()
    commands = [
        OrderCommand(
            timestamp=idx[1],
            symbol="BTC",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            qty=1.0,
            price=90.0,
            tif=TimeInForce.GTC,
            order_id="entry",
        ),
        OrderCommand(timestamp=idx[2], action=OrderAction.AMEND, target_order_id="entry", price=99.0),
    ]

    result = _backend().run_order_commands(idx, commands, close, high, low)
    report = result.metadata["command_report"].sort_values("original_index")

    assert len(result.fills) == 1
    assert result.fills[0].order_id == "entry"
    assert result.fills[0].price == 99.0
    assert float(report.iloc[0]["working_price"]) == 99.0
    assert int(report.iloc[1]["status"]) == ORDER_STATUS_FILLED


def test_event_v2_stop_market_uses_high_low_trigger_and_trigger_fill_price():
    idx, close, high, low = _market()
    commands = [
        OrderCommand(
            timestamp=idx[1],
            symbol="BTC",
            side=OrderSide.BUY,
            order_type=OrderType.STOP_MARKET,
            qty=1.0,
            trigger_price=105.0,
            tif=TimeInForce.GTC,
            order_id="breakout",
        )
    ]

    result = _backend().run_order_commands(idx, commands, close, high, low)

    assert len(result.fills) == 1
    assert result.fills[0].timestamp == idx[2]
    assert result.fills[0].price == 105.0
    assert result.positions["Position_BTC"].iloc[2] == 1.0


def test_event_v2_stop_limit_requires_trigger_and_limit_touch():
    idx, close, high, low = _market()
    commands = [
        OrderCommand(
            timestamp=idx[1],
            symbol="BTC",
            side=OrderSide.BUY,
            order_type=OrderType.STOP_LIMIT,
            qty=1.0,
            price=104.0,
            trigger_price=105.0,
            tif=TimeInForce.GTC,
            order_id="stop-limit-entry",
        )
    ]

    result = _backend().run_order_commands(idx, commands, close, high, low)

    assert len(result.fills) == 1
    assert result.fills[0].timestamp == idx[2]
    assert result.fills[0].price == 104.0
    assert result.positions["Position_BTC"].iloc[2] == 1.0


def test_event_v2_cancel_all_cancels_active_and_waiting_child_orders():
    idx, close, high, low = _market()
    commands = [
        OrderCommand(
            timestamp=idx[1],
            symbol="BTC",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            qty=1.0,
            price=50.0,
            tif=TimeInForce.GTC,
            order_id="deep-bid",
        ),
        OrderCommand(
            timestamp=idx[1],
            symbol="BTC",
            side=OrderSide.SELL,
            order_type=OrderType.LIMIT,
            qty=1.0,
            price=150.0,
            tif=TimeInForce.GTC,
            order_id="waiting-child",
            parent_order_id="missing-parent",
            activation_policy=OrderActivationPolicy.ON_PARENT_FIRST_FILL,
        ),
        OrderCommand(timestamp=idx[2], action=OrderAction.CANCEL_ALL, symbol="BTC"),
    ]

    result = _backend().run_order_commands(idx, commands, close, high, low)
    report = result.metadata["command_report"].sort_values("original_index")

    assert len(result.fills) == 0
    assert int(report.iloc[0]["status"]) == ORDER_STATUS_CANCELED
    assert int(report.iloc[1]["status"]) == ORDER_STATUS_CANCELED
    assert int(report.iloc[2]["status"]) == ORDER_STATUS_FILLED
    assert result.metadata["active_orders"].empty


def test_event_v2_parent_child_bracket_activates_and_oco_cancels_sibling():
    idx, close, high, low = _market()
    commands = [
        OrderCommand(
            timestamp=idx[1],
            symbol="BTC",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            qty=1.0,
            tif=TimeInForce.IOC,
            order_id="entry",
        ),
        OrderCommand(
            timestamp=idx[1],
            symbol="BTC",
            side=OrderSide.SELL,
            order_type=OrderType.LIMIT,
            qty=1.0,
            price=110.0,
            tif=TimeInForce.GTC,
            reduce_only=True,
            order_id="take-profit",
            parent_order_id="entry",
            oco_group_id="bracket",
            activation_policy=OrderActivationPolicy.ON_PARENT_FIRST_FILL,
        ),
        OrderCommand(
            timestamp=idx[1],
            symbol="BTC",
            side=OrderSide.SELL,
            order_type=OrderType.STOP_MARKET,
            qty=1.0,
            trigger_price=93.0,
            tif=TimeInForce.GTC,
            reduce_only=True,
            order_id="stop-loss",
            parent_order_id="entry",
            oco_group_id="bracket",
            activation_policy=OrderActivationPolicy.ON_PARENT_FIRST_FILL,
        ),
    ]

    result = _backend().run_order_commands(idx, commands, close, high, low)
    report = result.metadata["command_report"].sort_values("original_index")
    events = result.metadata["order_events"]

    assert [fill.order_id for fill in result.fills] == ["entry", "take-profit"]
    assert result.positions["Position_BTC"].iloc[-1] == 0.0
    assert int(report.iloc[1]["status"]) == ORDER_STATUS_FILLED
    assert int(report.iloc[2]["status"]) == ORDER_STATUS_CANCELED
    assert "activate" in set(events["event_name"])
    assert "cancel" in set(events["event_name"])


def test_event_v2_reduce_only_without_opposite_position_cancels_noop():
    idx, close, high, low = _market()
    commands = [
        OrderCommand(
            timestamp=idx[1],
            symbol="BTC",
            side=OrderSide.SELL,
            order_type=OrderType.MARKET,
            qty=1.0,
            reduce_only=True,
            order_id="bad-reduce",
        )
    ]

    result = _backend().run_order_commands(idx, commands, close, high, low)
    report = result.metadata["command_report"].sort_values("original_index")

    assert len(result.fills) == 0
    assert int(report.iloc[0]["status"]) == ORDER_STATUS_CANCELED
    assert int(report.iloc[0]["reject_code"]) == REJECT_REDUCE_ONLY_NO_POSITION


def test_event_v2_reduce_only_clips_to_existing_position_size():
    idx, close, high, low = _market()
    commands = [
        OrderCommand(
            timestamp=idx[1],
            symbol="BTC",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            qty=1.0,
            tif=TimeInForce.IOC,
            order_id="entry",
        ),
        OrderCommand(
            timestamp=idx[2],
            symbol="BTC",
            side=OrderSide.SELL,
            order_type=OrderType.MARKET,
            qty=3.0,
            tif=TimeInForce.IOC,
            reduce_only=True,
            order_id="oversized-exit",
        ),
    ]

    result = _backend().run_order_commands(idx, commands, close, high, low)

    assert [fill.qty for fill in result.fills] == [1.0, 1.0]
    assert result.positions["Position_BTC"].iloc[2] == 0.0
    assert result.positions["Position_BTC"].iloc[-1] == 0.0


def test_event_v2_rejects_order_above_buying_power():
    idx, close, high, low = _market()
    commands = [
        OrderCommand(
            timestamp=idx[1],
            symbol="BTC",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            qty=500.0,
            tif=TimeInForce.IOC,
            order_id="too-large",
        )
    ]

    result = _backend(leverage=1.0).run_order_commands(idx, commands, close, high, low)
    report = result.metadata["command_report"].sort_values("original_index")

    assert len(result.fills) == 0
    assert int(report.iloc[0]["status"]) == ORDER_STATUS_REJECTED
    assert int(report.iloc[0]["reject_code"]) == REJECT_INSUFFICIENT_MARGIN
    assert result.positions["Position_BTC"].iloc[-1] == 0.0


def test_event_v2_dca_ladder_style_limits_fill_at_grid_prices():
    idx, close, high, low = _market()
    commands = [
        OrderCommand(
            timestamp=idx[1],
            symbol="BTC",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            qty=1.0,
            tif=TimeInForce.IOC,
            order_id="base",
            group_id="dca-grid",
        ),
        OrderCommand(
            timestamp=idx[1],
            symbol="BTC",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            qty=1.5,
            price=95.0,
            tif=TimeInForce.GTC,
            order_id="safety-1",
            group_id="dca-grid",
        ),
        OrderCommand(
            timestamp=idx[1],
            symbol="BTC",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            qty=2.0,
            price=90.0,
            tif=TimeInForce.GTC,
            order_id="safety-2",
            group_id="dca-grid",
        ),
    ]

    result = _backend().run_order_commands(idx, commands, close, high, low)

    assert [fill.order_id for fill in result.fills] == ["base", "safety-1", "safety-2"]
    assert [fill.price for fill in result.fills] == [100.0, 95.0, 90.0]
    assert result.fills[1].timestamp == idx[3]
    assert result.fills[2].timestamp == idx[4]
    assert result.positions["Position_BTC"].iloc[-1] == 4.5


def test_event_v2_gtd_expires_before_later_touch():
    idx, close, high, low = _market()
    commands = [
        OrderCommand(
            timestamp=idx[1],
            symbol="BTC",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            qty=1.0,
            price=90.0,
            tif=TimeInForce.GTD,
            expires_at=idx[3],
            order_id="gtd-entry",
        )
    ]

    result = _backend().run_order_commands(idx, commands, close, high, low)
    report = result.metadata["command_report"].sort_values("original_index")

    assert len(result.fills) == 0
    assert int(report.iloc[0]["status"]) == ORDER_STATUS_CANCELED
    assert "expire" in set(result.metadata["order_events"]["event_name"])
    assert int(report.iloc[0]["fill_bar"]) == -1
    assert result.metadata["active_orders"].empty


def test_event_v2_unfilled_gtc_remains_active_in_snapshot():
    idx, close, high, low = _market()
    commands = [
        OrderCommand(
            timestamp=idx[1],
            symbol="BTC",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            qty=1.0,
            price=50.0,
            tif=TimeInForce.GTC,
            order_id="deep-bid",
        )
    ]

    result = _backend().run_order_commands(idx, commands, close, high, low)
    report = result.metadata["command_report"].sort_values("original_index")

    assert len(result.fills) == 0
    assert int(report.iloc[0]["status"]) == ORDER_STATUS_PENDING
    assert bool(report.iloc[0]["active"]) is True
    assert len(result.metadata["active_orders"]) == 1


def test_event_v2_matches_v1_for_simple_market_and_limit_intents():
    idx, close, high, low = _market()
    orders = [
        OrderIntent(
            timestamp=idx[1],
            symbol="BTC",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            qty=1.0,
            tif=TimeInForce.IOC,
            order_id="market-entry",
        ),
        OrderIntent(
            timestamp=idx[3],
            symbol="BTC",
            side=OrderSide.SELL,
            order_type=OrderType.LIMIT,
            qty=1.0,
            price=110.0,
            tif=TimeInForce.GTC,
            order_id="limit-exit",
        ),
    ]
    backend = _backend()

    v1 = backend.run_orders(idx, orders, close, high, low)
    v2 = backend.run_order_commands(idx, order_intents_to_commands(orders), close, high, low)

    pd.testing.assert_series_equal(v2.equity, v1.equity)
    pd.testing.assert_frame_equal(v2.positions, v1.positions)
    assert [fill.price for fill in v2.fills] == [fill.price for fill in v1.fills]
