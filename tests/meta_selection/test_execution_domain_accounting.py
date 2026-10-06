"""Independent domain expectations before judging meta economics."""

from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from quantbt import QuantBTEndpoint
from quantbt.core.delivery_lifecycle import DeliveryContract, DeliveryLifecycle
from quantbt.core.orders import OrderAction, OrderCommand
from quantbt.core.schema import OrderSide, OrderType
from quantbt.wfo_execution import WfoExecutionWindow, execute_window, stitch_execution_windows


def frame(n=6):
    idx = pd.date_range("2024-01-01", periods=n, freq="h", tz="UTC")
    return pd.DataFrame(dict(open=100., high=101., low=99., close=100., volume=1000.), index=idx)


def test_carried_intrabar_trade_keeps_original_stop_across_new_fold():
    data = frame()
    data.loc[data.index[3], "low"] = 98.
    data.loc[data.index[5], "low"] = 94.
    idx = data.index
    a = WfoExecutionWindow("intrabar", idx[:3], intent=pd.DataFrame(
        dict(entry_signal=[1., 0., 0.], stop_value=.05), index=idx[:3]))
    b = WfoExecutionWindow("intrabar", idx[3:], intent=pd.DataFrame(
        dict(entry_signal=0., stop_value=.001), index=idx[3:]))
    output = stitch_execution_windows((a, b), idx)
    endpoint = QuantBTEndpoint.intrabar_bracket(initial_capital=1000., leverage=3.,
        fee_rate=.001, slippage_bps=0., use_funding=False, symbols=["X"],
        close_on_last_bar=False, report_level="audit")
    result = execute_window(endpoint.config, data, output)
    assert result.positions.Position_X.iloc[3] == 1.
    assert result.positions.Position_X.iloc[-1] == 0.
    assert result.equity.iloc[-1] == pytest.approx(1000.-5.-.100-.095)
    assert result.fees.sum() == pytest.approx(.195)


def test_pending_command_crosses_fold_boundary_without_reset():
    data = frame()
    data.loc[data.index[3], "low"] = 98.
    idx = data.index
    place = OrderCommand(idx[1], symbol="X", side=OrderSide.BUY,
        order_type=OrderType.LIMIT, qty=1., price=98.5, order_id="pending")
    cancel = OrderCommand(idx[4], OrderAction.CANCEL, target_order_id="pending")
    output = stitch_execution_windows((WfoExecutionWindow("order_commands", idx[:3], commands=(place,)),
        WfoExecutionWindow("order_commands", idx[3:], commands=(cancel,))), idx)
    endpoint = QuantBTEndpoint.event_driven(input_mode="orders", profile="audit", backend="python",
        symbols=["X"], initial_capital=1000., leverage=3., fee_rate=0., use_funding=False)
    result = execute_window(endpoint.config, data, output)
    assert result.positions.Position_X.iloc[2] == 0.
    assert result.positions.Position_X.iloc[3] == 1.
    assert result.equity.iloc[-1] == pytest.approx(1001.5)


def test_empty_command_window_keeps_a_valid_flat_original_account():
    data = frame()
    endpoint = QuantBTEndpoint.event_driven(input_mode="orders", backend="python",
        symbols=["X"], initial_capital=1000., use_funding=False)
    result = execute_window(endpoint.config, data, WfoExecutionWindow("order_commands", data.index))
    np.testing.assert_array_equal(result.equity, 1000.)
    assert not result.fills


def test_delivery_leg_cannot_accumulate_perpetual_funding():
    from examples.wfo_meta_execution import make_endpoint
    from quantbt.wfo_execution import validate_execution_route
    cfg = make_endpoint("delivery_arbitrage").config
    bad = replace(cfg, wfo_execution_config=replace(cfg.wfo_execution_config,
        use_funding=True, funding_rate=.0001))
    with pytest.raises(ValueError, match="do not accrue"):
        validate_execution_route(bad, cfg.walkforward_config)


@pytest.mark.parametrize("clock", ("event_lifecycle_v2_next_bar_close", "event_lifecycle_v3_next_open"))
def test_quarterly_roll_flatten_prices_and_each_one_way_fee(clock):
    data = frame()
    data.loc[data.index[3]:, ["open", "close"]] = 104.
    data.loc[data.index[3]:, "high"] = 105.
    data.loc[data.index[3]:, "low"] = 103.
    idx = data.index
    lifecycle = DeliveryLifecycle((DeliveryContract("Q1", idx[4], idx[3], "synthetic-contract-v1"),
        DeliveryContract("Q2", idx[-1]+pd.Timedelta(hours=2), idx[-1]+pd.Timedelta(hours=1), "synthetic-contract-v1")))
    endpoint = QuantBTEndpoint.event_driven(input_mode="orders", profile="audit", backend="python",
        symbols=["Q1", "Q2"], initial_capital=1000., leverage=3., fee_rate=.001,
        slippage_bps=0., use_funding=False, execution_contract=clock,
        metadata={"delivery_lifecycle": lifecycle})
    commands = (OrderCommand(idx[1], symbol="Q1", side=OrderSide.BUY,
        order_type=OrderType.MARKET, qty=.5, order_id="old"),
        OrderCommand(idx[3], symbol="Q2", side=OrderSide.BUY,
        order_type=OrderType.MARKET, qty=.5, order_id="new"))
    result = execute_window(endpoint.config, {"Q1": data, "Q2": data},
        WfoExecutionWindow("delivery_arbitrage", idx, commands=commands))
    assert result.positions.Position_Q1.iloc[-1] == 0.
    assert result.positions.Position_Q2.iloc[-1] == .5
    assert result.fees.sum() == pytest.approx(.05+.052+.052)
    assert result.equity.iloc[-1] == pytest.approx(1000.+2.-.154)
    assert result.metadata["delivery_lifecycle"]["expiry_flat_reconciled"]
    assert not result.metadata["delivery_lifecycle"]["cash_settlement"]


def test_quarterly_insufficient_close_capacity_cannot_get_a_pass_receipt():
    data = frame()
    idx = data.index
    lifecycle = DeliveryLifecycle((DeliveryContract("Q1", idx[4], idx[3], "synthetic"),), max_close_qty=.1)
    endpoint = QuantBTEndpoint.event_driven(input_mode="orders", profile="audit", backend="python",
        symbols=["Q1"], initial_capital=1000., leverage=3., fee_rate=0., use_funding=False,
        metadata={"delivery_lifecycle": lifecycle})
    place = OrderCommand(idx[1], symbol="Q1", side=OrderSide.BUY, order_type=OrderType.MARKET,
        qty=1., order_id="old")
    with pytest.raises(RuntimeError, match="not flat"):
        execute_window(endpoint.config, {"Q1": data}, WfoExecutionWindow("delivery_arbitrage", idx, commands=(place,)))


@pytest.mark.parametrize("field", ("equity", "returns", "positions", "fees", "funding", "margin"))
def test_intrabar_minimal_and_audit_accounting_match(field):
    data = frame()
    output = WfoExecutionWindow("intrabar", data.index,
        intent=pd.DataFrame(dict(entry_signal=[1., 0., 0., -1., 0., 0.], stop_value=.05), index=data.index))
    endpoint = QuantBTEndpoint.intrabar_bracket(initial_capital=1000., leverage=3.,
        fee_rate=.001, use_funding=False, symbols=["X"], report_level="audit")
    a = execute_window(endpoint.config, data, output)
    b = execute_window(replace(endpoint.config, report_level="minimal"), data, output)
    np.testing.assert_array_equal(getattr(a, field), getattr(b, field))


@pytest.mark.parametrize("field", ("fees", "funding", "margin"))
def test_execution_witness_binds_original_cost_and_margin_buffers(field):
    from copy import deepcopy
    from quantbt.optimization.meta_selection.observer import (
        ResultMetricAdapter, canonical_metric_contract, economics_identity, market_signature)
    from quantbt.optimization.meta_selection.common import MetaRecordError

    data = frame()
    config = QuantBTEndpoint.intrabar_bracket(initial_capital=1000., leverage=3.,
        fee_rate=.001, use_funding=False, symbols=["X"], report_level="audit").config
    output = WfoExecutionWindow("intrabar", data.index,
        intent=pd.DataFrame(dict(entry_signal=[1., 0., 0., 0., 0., 0.]), index=data.index))
    result = execute_window(config, data, output)
    adapter = ResultMetricAdapter(canonical_metric_contract())
    kwargs = dict(expected_index=data.index, economics_id=economics_identity(config),
        input_signature=market_signature(data, data.index, config=config), execution_config=config)
    first = adapter.observe(result, **kwargs)
    changed = deepcopy(result)
    getattr(changed, field).iloc[0] += .123
    second = adapter.observe(changed, **kwargs)
    assert first.output_ref != second.output_ref
    setattr(changed, field, None)
    with pytest.raises(MetaRecordError, match="costs/margin missing"):
        adapter.observe(changed, **kwargs)
