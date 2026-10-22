"""Independent event-window expectations across factory/command boundaries."""

from dataclasses import replace

import pandas as pd
import pytest

from quantbt import OrderAction, OrderActivationPolicy, OrderCommand, OrderSide, OrderType, QuantBTEndpoint
from quantbt.wfo_execution import WfoExecutionWindow, execute_window, stitch_execution_windows
from tests.meta_selection.pre_e06_02_support import account_equal


def frame():
    index = pd.date_range("2024-01-01", periods=8, freq="h", tz="UTC")
    return pd.DataFrame(dict(open=100., high=101., low=99., close=100., volume=1000.), index=index)


def financial(backend, route):
    return QuantBTEndpoint.event_driven(input_mode="strategy" if route == "event_driven" else "orders",
        backend=backend, profile="audit", symbols=["X"], initial_capital=1000., leverage=3.,
        fee_rate=.001, slippage_bps=0., use_funding=False)


@pytest.mark.parametrize("backend", ("python", "rust"))
def test_e07_pending_entry_survives_factory_switch_and_fill_feedback(backend):
    data, seen, instances = frame(), [], []

    class Child:
        def __init__(self, first):
            self.first = first
            instances.append(self)

        def initialize(self, context):
            seen.append(("initialize", self.first, context.timestamp, context.positions["X"]))
            return ()

        def on_bar_close(self, context):
            seen.append(("close", self.first, context.timestamp, context.positions["X"],
                         len(context.fills_this_bar)))
            if self.first and context.bar_index == 2:
                return (OrderCommand(context.timestamp, symbol="X", side=OrderSide.BUY,
                    order_type=OrderType.MARKET, qty=1., order_id="previous-fold-entry"),)
            if not self.first and context.positions["X"] > 0 and context.fills_this_bar:
                return (OrderCommand(context.timestamp, symbol="X", side=OrderSide.SELL,
                    order_type=OrderType.MARKET, qty=context.positions["X"], reduce_only=True,
                    order_id="new-fold-fill-exit"),)
            return ()

        def finalize(self, context):
            seen.append(("finalize", self.first, context.timestamp))
            return ()

    parts = (WfoExecutionWindow("event_driven", data.index[:3], strategy_factory=lambda: Child(True)),
             WfoExecutionWindow("event_driven", data.index[3:], strategy_factory=lambda: Child(False)))
    result = execute_window(financial(backend, "event_driven").config, data,
                            stitch_execution_windows(parts, data.index))
    assert len(instances) == 2 and instances[0] is not instances[1]
    assert [(f.timestamp, f.price, f.qty) for f in result.fills] == [(data.index[3], 100., 1.), (data.index[4], 100., 1.)]
    assert ("initialize", False, data.index[3], 1.) in seen
    assert ("close", False, data.index[3], 1., 1) in seen
    assert [(r[1], r[2]) for r in seen if r[0] == "finalize"] == [(False, data.index[-1])]
    assert result.fees.sum() == pytest.approx(.2)
    assert result.equity.iloc[-1] == pytest.approx(999.8)


@pytest.mark.parametrize("backend", ("python", "rust"))
@pytest.mark.parametrize("exit_kind", ("tp", "sl"))
def test_e07_parent_oco_protections_not_reset_at_factory_boundary(backend, exit_kind):
    data = frame()
    data.loc[data.index[5], "high" if exit_kind == "tp" else "low"] = 103. if exit_kind == "tp" else 94.

    class Child:
        def __init__(self, first):
            self.first = first

        def on_bar_close(self, context):
            if not self.first or context.bar_index != 2:
                return ()
            parent = OrderCommand(context.timestamp, symbol="X", side=OrderSide.BUY,
                order_type=OrderType.MARKET, qty=1., order_id="parent")
            common = dict(symbol="X", side=OrderSide.SELL, qty=1., reduce_only=True,
                parent_order_id="parent", activation_policy=OrderActivationPolicy.ON_PARENT_FIRST_FILL,
                oco_group_id="bracket")
            return (parent, OrderCommand(context.timestamp, order_type=OrderType.LIMIT,
                price=102., order_id="tp", **common), OrderCommand(context.timestamp,
                order_type=OrderType.STOP_MARKET, trigger_price=95., order_id="sl", **common))

    parts = tuple(WfoExecutionWindow("event_driven", index,
        strategy_factory=lambda first=first: Child(first))
        for first, index in ((True, data.index[:3]), (False, data.index[3:])))
    result = execute_window(financial(backend, "event_driven").config, data,
                            stitch_execution_windows(parts, data.index))
    price = 102. if exit_kind == "tp" else 95.
    assert [(f.order_id, f.timestamp, f.price) for f in result.fills] == [
        ("parent", data.index[3], 100.), (exit_kind, data.index[5], price)]
    assert result.fees.sum() == pytest.approx(.1+price*.001)
    assert result.equity.iloc[-1] == pytest.approx(1000.+price-100.-.1-price*.001)
    assert "cancel" in set(result.metadata["order_events"].event_name)


@pytest.mark.parametrize("backend", ("python", "rust"))
@pytest.mark.parametrize("action", ("cancel", "amend", "replace"))
def test_e07_static_pending_controls_cross_fold_with_original_clock(backend, action):
    data = frame()
    pending = OrderCommand(data.index[2], symbol="X", side=OrderSide.BUY,
        order_type=OrderType.LIMIT, qty=1., price=50., order_id="old")
    change = OrderCommand(data.index[4], action=OrderAction(action), target_order_id="old",
        **({} if action == "cancel" else dict(price=99.)),
        **(dict(symbol="X", side=OrderSide.BUY, order_type=OrderType.LIMIT,
                qty=1., order_id="replacement") if action == "replace" else {}))
    parts = (WfoExecutionWindow("order_commands", data.index[:3], commands=(pending,)),
             WfoExecutionWindow("order_commands", data.index[3:], commands=(change,)))
    out = stitch_execution_windows(parts, data.index)
    endpoint = financial(backend, "order_commands")
    result = execute_window(endpoint.config, data, out)
    original = endpoint.backtest(data=data, order_commands=(pending, change), symbols=["X"])
    account_equal(result, original)
    if action == "cancel":
        assert not result.fills and result.equity.iloc[-1] == 1000.
    else:
        assert [(f.timestamp, f.price, f.qty) for f in result.fills] == [(data.index[4], 99., 1.)]
        assert result.fees.sum() == pytest.approx(.099)
        assert result.equity.iloc[-1] == pytest.approx(1000.901)


@pytest.mark.parametrize("backend", ("python", "rust"))
def test_e07_wrong_callback_protocol_fails_instead_of_signal_proxy(backend):
    data = frame()
    out = WfoExecutionWindow("event_driven", data.index, strategy_factory=lambda: pd.Series(0., index=data.index))
    from quantbt.core.reactive import NativeEventStrategyError
    with pytest.raises(NativeEventStrategyError, match="callback protocol") as failure:
        execute_window(financial(backend, "event_driven").config, data, out)
    assert isinstance(failure.value.__cause__, TypeError)


def test_e07_numeric_grid_uses_real_fill_feedback_and_independent_account():
    from types import SimpleNamespace
    from examples.wfo_meta_reactive_grid import FillFeedbackGrid
    from quantbt import ExecutionConfig
    data = frame()
    data.loc[data.index[1], "low"] = 99.
    endpoint = QuantBTEndpoint.native_event_strategy(initial_capital=1000., leverage=3.,
        fee_rate=.001, use_funding=False, native_backend="rust", report_level="audit",
        reactive_runtime="numeric_every_bar_v1", reactive_kernel_mode="single_pass",
        execution_contract="event_lifecycle_v3_next_open", execution=ExecutionConfig(slippage_bps=0.))
    prepared = endpoint.prepare_native_event_strategy(data=data, symbols=["X"])
    task = SimpleNamespace(start_bar=0, end_bar=len(data), seed=731)
    strategy = FillFeedbackGrid(task=task, window=9)
    try:
        result = prepared.run_window(strategy, start_bar=0, end_bar=len(data), report_level="audit")
    finally:
        prepared.backend.clear_prepared_caches()
    assert strategy.fill_feedback_count == 2
    prices = (99.8, 99.8*1.003)
    assert [f.price for f in result.fills] == pytest.approx(prices)
    assert result.fees.sum() == pytest.approx(sum(prices)*.5*.001)
    assert result.equity.iloc[-1] == pytest.approx(1000.+(prices[1]-prices[0])*.5-sum(prices)*.5*.001)
