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
