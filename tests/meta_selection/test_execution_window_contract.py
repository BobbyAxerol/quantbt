"""Test-first contract: execution outputs are not effective position proxies."""

import numpy as np
import pandas as pd
import pytest

from quantbt.core.orders import OrderCommand
from quantbt.core.schema import OrderSide, OrderType
from quantbt.walkforward import validate_walkforward_strategy_output
from quantbt.wfo_execution import WfoExecutionWindow, stitch_execution_windows
from quantbt.core.delivery_lifecycle import DeliveryContract, DeliveryLifecycle


def index():
    return pd.date_range("2024-01-01", periods=6, freq="h", tz="UTC")


def test_intent_calendar_is_exact_not_repaired():
    idx = index()
    intent = pd.DataFrame({"entry_signal": [1., 0., 0., 0., 0., 0.]}, index=idx)
    output = WfoExecutionWindow("intrabar", idx, intent=intent)
    assert validate_walkforward_strategy_output(output, idx) is output
    with pytest.raises(ValueError, match="exact"):
        WfoExecutionWindow("intrabar", idx, intent=intent.iloc[::-1])


def test_stitch_preserves_intent_and_window_boundaries_not_equity():
    idx = index()
    a = WfoExecutionWindow("intrabar", idx[:3], intent=pd.DataFrame(
        {"entry_signal": [1., 0., 0.], "stop_value": [.05]*3}, index=idx[:3]))
    b = WfoExecutionWindow("intrabar", idx[3:], intent=pd.DataFrame(
        {"entry_signal": [0., 0., 0.], "stop_value": [.01]*3}, index=idx[3:]))
    result = stitch_execution_windows((a, b), idx)
    assert result.parts == (a, b)
    np.testing.assert_array_equal(result.intent.entry_signal, [1., 0., 0., 0., 0., 0.])


def test_command_outside_window_rejected_and_no_numeric_substitute():
    idx = index()
    command = OrderCommand(idx[-1] + pd.Timedelta(hours=1), symbol="X",
        side=OrderSide.BUY, order_type=OrderType.MARKET, qty=1., order_id="entry")
    with pytest.raises(ValueError, match="window"):
        WfoExecutionWindow("order_commands", idx, commands=(command,))
    with pytest.raises(ValueError, match="payload"):
        WfoExecutionWindow("event_driven", idx)


def test_expiry_source_and_preexpiry_clock_are_explicit():
    idx = index()
    contract = DeliveryContract("X-QUARTER", idx[-1], idx[-2], "synthetic-instrument-v1")
    lifecycle = DeliveryLifecycle((contract,))
    assert lifecycle.contracts[0].expires_at == idx[-1]
    with pytest.raises(ValueError):
        DeliveryContract("X-QUARTER", idx[-1], idx[-1], "synthetic")
    with pytest.raises(NotImplementedError, match="cash"):
        DeliveryLifecycle((contract,), expiry_policy="cash_settlement")
