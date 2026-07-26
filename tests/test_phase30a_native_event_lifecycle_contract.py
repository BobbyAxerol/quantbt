from __future__ import annotations

import pandas as pd
import pytest

from quantbt import NativeEventBackend, OrderAction, OrderActivationPolicy, OrderCommand
from quantbt.core.event import ORDER_TYPE_STOP_LIMIT, ORDER_TYPE_STOP_MARKET, TIF_GTC, TIF_IOC
from quantbt.core.order_compiler import (
    COMMAND_ACTION_CANCEL,
    COMMAND_ACTION_PLACE,
    COMMAND_ACTION_REPLACE,
    compile_order_commands,
    order_intents_to_commands,
)
from quantbt.core.orders import OrderIntent
from quantbt.core.schema import OrderSide, OrderType, TimeInForce


def _idx() -> pd.DatetimeIndex:
    return pd.date_range("2024-01-01", periods=5, freq="1h", tz="UTC")


def test_order_command_from_intent_preserves_legacy_order_fields():
    idx = _idx()
    intent = OrderIntent(
        timestamp=idx[1],
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        qty=0.25,
        price=40_000.0,
        tif=TimeInForce.GTC,
        reduce_only=True,
        order_id="legacy-entry",
        tag="legacy",
        metadata={"source": "test"},
    )

    command = order_intents_to_commands([intent])[0]

    assert command.action is OrderAction.PLACE
    assert command.symbol == intent.symbol
    assert command.signed_qty == intent.signed_qty
    assert command.to_intent() == intent


def test_order_command_validation_rejects_incomplete_lifecycle_commands():
    idx = _idx()
    with pytest.raises(ValueError, match="place command requires symbol"):
        OrderCommand(timestamp=idx[1], side=OrderSide.BUY, order_type=OrderType.MARKET, qty=1.0)

    with pytest.raises(ValueError, match="cancel command requires target_order_id"):
        OrderCommand(timestamp=idx[1], action=OrderAction.CANCEL)

    with pytest.raises(ValueError, match="replace command requires target_order_id"):
        OrderCommand(
            timestamp=idx[1],
            action=OrderAction.REPLACE,
            symbol="BTCUSDT",
            side=OrderSide.SELL,
            order_type=OrderType.LIMIT,
            qty=1.0,
            price=41_000.0,
        )


def test_compile_order_commands_stable_sorts_and_preserves_lifecycle_fields():
    idx = _idx()
    commands = [
        OrderCommand(
            timestamp=idx[2],
            action=OrderAction.PLACE,
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.STOP_MARKET,
            qty=0.5,
            trigger_price=40_500.0,
            tif=TimeInForce.IOC,
            order_id="entry-stop",
            group_id="grid-1",
        ),
        OrderCommand(
            timestamp=idx[1],
            action=OrderAction.PLACE,
            symbol="BTCUSDT",
            side=OrderSide.SELL,
            order_type=OrderType.STOP_LIMIT,
            qty=0.5,
            price=41_000.0,
            trigger_price=40_900.0,
            tif=TimeInForce.GTC,
            reduce_only=True,
            order_id="tp-stop-limit",
            parent_order_id="entry-stop",
            oco_group_id="bracket-1",
            activation_policy=OrderActivationPolicy.ON_PARENT_FIRST_FILL,
            expires_at=idx[4],
        ),
        OrderCommand(
            timestamp=idx[2],
            action=OrderAction.CANCEL,
            target_order_id="tp-stop-limit",
        ),
    ]

    compiled = compile_order_commands(idx, commands, {"BTCUSDT": 0})

    assert compiled.n_commands == 3
    assert compiled.original_index.tolist() == [1, 0, 2]
    assert compiled.command_ptr.tolist() == [0, 0, 1, 3, 3, 3]
    assert compiled.command_action.tolist() == [
        COMMAND_ACTION_PLACE,
        COMMAND_ACTION_PLACE,
        COMMAND_ACTION_CANCEL,
    ]
    assert compiled.command_type[0] == ORDER_TYPE_STOP_LIMIT
    assert compiled.command_type[1] == ORDER_TYPE_STOP_MARKET
    assert compiled.command_tif[0] == TIF_GTC
    assert compiled.command_tif[1] == TIF_IOC
    assert compiled.command_reduce_only[0] == 1
    assert compiled.command_trigger_price[0] == 40_900.0
    assert compiled.command_expires_bar[0] == 4
    assert "entry-stop" in compiled.id_values
    assert "tp-stop-limit" in compiled.id_values
    assert compiled.command_target_order_id[2] == compiled.command_order_id[0]


def test_backend_compile_order_commands_helper_matches_core_compiler():
    idx = _idx()
    commands = [
        OrderCommand(
            timestamp=idx[1],
            symbol="ETHUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            qty=1.0,
            order_id="entry",
        ),
        OrderCommand(
            timestamp=idx[2],
            action=OrderAction.REPLACE,
            target_order_id="entry",
            symbol="ETHUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            qty=1.0,
            price=2_000.0,
            order_id="entry-replaced",
        ),
    ]

    helper = NativeEventBackend.compile_order_commands(idx, commands, symbols=["ETHUSDT"])
    manual = compile_order_commands(idx, commands, {"ETHUSDT": 0})

    assert helper.symbols == manual.symbols
    assert helper.command_action.tolist() == [COMMAND_ACTION_PLACE, COMMAND_ACTION_REPLACE]
    assert helper.command_price.tolist() == manual.command_price.tolist()
