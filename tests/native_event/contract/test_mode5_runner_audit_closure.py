"""Cold audit projections must retain the actual native order outcome."""

import numpy as np
import pandas as pd
import pytest

from quantbt.backends import NativeEventBackend, NativeEventConfig
from quantbt.core.orders import OrderCommand
from quantbt.core.schema import AccountConfig, OrderSide, OrderType


def _run(backend, commands, frame):
    runner = NativeEventBackend(NativeEventConfig(
        account=AccountConfig(initial_capital=20_000.0, leverage=3.0),
        native_backend=backend, use_funding=False, fee_rate=0.0004,
        execution_contract="event_lifecycle_v3_next_open",
    ))
    return runner.run_order_commands(
        datetime_index=frame.index, commands=commands, symbols=["TEST"],
        **{f"{name}s": {"TEST": frame[name]} for name in ("open", "high", "low", "close")},
    )


def _frame():
    return pd.DataFrame({
        "open": [100., 100., 100., 100., 100.],
        "high": [101., 101., 106., 101., 101.],
        "low": [99., 99., 99., 99., 99.],
        "close": [100., 100., 100., 100., 100.],
    }, index=pd.date_range("2021-01-01", periods=5, freq="h", tz="UTC"))


def _bracket(frame, *, cleanup=False):
    idx = frame.index
    commands = [OrderCommand(timestamp=idx[1], symbol="TEST", side=OrderSide.BUY,
        order_type=OrderType.MARKET, qty=1., order_id="entry")]
    for name, kind, level in (("tp", OrderType.LIMIT, 105.), ("stop", OrderType.STOP_MARKET, 95.)):
        commands.append(OrderCommand(timestamp=idx[1], symbol="TEST", side=OrderSide.SELL,
            order_type=kind, qty=1., order_id=name, reduce_only=True,
            parent_order_id="entry", activation_policy="on_parent_first_fill", oco_group_id="bracket",
            **({"price": level} if kind is OrderType.LIMIT else {"trigger_price": level})))
    if cleanup:
        commands.append(OrderCommand(timestamp=idx[3], action="cancel_all", symbol="TEST", order_id="empty-cleanup"))
        commands.append(OrderCommand(timestamp=idx[4], action="cancel_all", symbol="TEST", order_id="cleanup"))
    return tuple(commands)


@pytest.mark.parametrize("cleanup", [False, True])
def test_oco_cause_reference_does_not_cancel_filled_winner(cleanup):
    frame = _frame()
    commands = _bracket(frame, cleanup=cleanup)
    python = _run("python", commands, frame)
    rust = _run("rust", commands, frame)
    assert [fill.order_id for fill in python.fills] == ["entry", "tp"]
    np.testing.assert_array_equal(python.equity.to_numpy(), rust.equity.to_numpy())
    columns = ["original_index", "sorted_index", "action", "order_id", "target_order_id",
        "command_outcome", "order_status", "legacy_status_code"]
    pd.testing.assert_frame_equal(python.metadata["command_outcome_report_v1"][columns],
        rust.metadata["command_outcome_report_v1"][columns], check_dtype=False)
    state = rust.metadata["command_outcome_report_v1"].set_index("order_id")
    assert state.loc["tp", "order_status"] == "FILLED"
    assert state.loc["stop", "order_status"] == "CANCELED"


def test_authoritative_cancel_units_include_orders_not_control_events():
    frame = _frame()
    idx = frame.index
    commands = tuple(OrderCommand(timestamp=idx[1], symbol="TEST", side=OrderSide.BUY,
        order_type=OrderType.LIMIT, qty=1., price=price, order_id=name)
        for name, price in (("one", 50.), ("two", 40.))) + (
        OrderCommand(timestamp=idx[2], action="cancel_all", order_id="cancel-two"),
        OrderCommand(timestamp=idx[3], action="cancel_all", order_id="cancel-none"),
    )
    python = _run("python", commands, frame)
    rust = _run("rust", commands, frame)
    assert rust.metadata["native_terminal_state_v1"]["available"]
    np.testing.assert_array_equal(python.diagnostics.canceled_orders, rust.diagnostics.canceled_orders)
    assert rust.diagnostics.canceled_orders.sum() == 2
    assert rust.metadata["lifecycle_counters"]["canceled_event_count"] == 2
    assert rust.metadata["lifecycle_counters"]["canceled_order_count"] == 2


def test_authoritative_terminal_retains_active_and_waiting_amended_slots():
    frame = _frame()
    idx = frame.index
    commands = (
        OrderCommand(timestamp=idx[1], symbol="TEST", side=OrderSide.BUY, order_type=OrderType.LIMIT,
            qty=1., price=50., order_id="parent"),
        OrderCommand(timestamp=idx[1], symbol="TEST", side=OrderSide.SELL, order_type=OrderType.LIMIT,
            qty=1., price=120., order_id="child", parent_order_id="parent", activation_policy="on_parent_full_fill"),
        OrderCommand(timestamp=idx[2], action="amend", target_order_id="parent", qty=2., price=45.),
    )
    python = _run("python", commands, frame)
    rust = _run("rust", commands, frame)
    assert rust.metadata["native_terminal_state_v1"] == {
        "available": True, "authority": "rust", "reason": None, "replayed": False,
    }
    columns = ["original_index", "sorted_index", "order_id", "status", "active", "waiting_parent"]
    pd.testing.assert_frame_equal(python.metadata["command_report"][columns], rust.metadata["command_report"][columns], check_dtype=False)
    working = ["working_qty", "working_price", "working_trigger_price"]
    available = rust.metadata["command_report"].working_state_available
    pd.testing.assert_frame_equal(python.metadata["command_report"].loc[available, working],
        rust.metadata["command_report"].loc[available, working], check_dtype=False)
    assert not available.iloc[-1]  # AMEND is a control, not another live order.
    assert set(rust.metadata["active_orders"].order_id) == {"parent", "child"}
    assert not rust.fills


def test_fill_liquidity_and_provenance_match_oracle():
    frame = _frame()
    frame.loc[frame.index[2], "low"] = 94.
    frame.loc[frame.index[2], "high"] = 101.
    commands = _bracket(frame)
    python = _run("python", commands, frame)
    rust = _run("rust", commands, frame)
    assert [fill.order_id for fill in python.fills] == ["entry", "stop"]
    assert [fill.liquidity for fill in python.fills] == [fill.liquidity for fill in rust.fills]
    assert {fill.metadata["liquidity_provenance"] for fill in rust.fills} == {"native_matched_order_type_v1"}
    np.testing.assert_array_equal(python.fees, rust.fees)
