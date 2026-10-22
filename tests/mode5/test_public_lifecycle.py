"""M5T-099: actual feedback, protective OCO, amendment and rejection."""
from dataclasses import asdict
from functools import partial

import numpy as np
import pytest

from quantbt import (QuantBTEndpoint, OrderCommand, OrderAction, OrderSide,
                     OrderType, OrderActivationPolicy)
from quantbt.wfo_execution import WfoExecutionWindow, execute_window
from public_fixtures import public_setup, market


class LifecycleAlpha:
    def __init__(self, seen):
        self.seen = seen

    def on_bar_close(self, context):
        if context.fills_this_bar:
            self.seen.append((context.bar_index, context.positions["X"],
                              tuple(f.order_id for f in context.fills_this_bar)))
        at = context.timestamp
        common = dict(symbol="X", side=OrderSide.BUY, qty=.5)
        if context.bar_index == 2:
            protection = dict(symbol="X", side=OrderSide.SELL, qty=.5, reduce_only=True,
                parent_order_id="parent", activation_policy=OrderActivationPolicy.ON_PARENT_FIRST_FILL,
                oco_group_id="protection")
            return (OrderCommand(at, order_type=OrderType.MARKET, order_id="parent", **common),
                OrderCommand(at, order_type=OrderType.LIMIT, price=102., order_id="tp", **protection),
                OrderCommand(at, order_type=OrderType.STOP_MARKET, trigger_price=95., order_id="sl", **protection))
        if context.bar_index in (9, 22):
            return (OrderCommand(at, order_type=OrderType.LIMIT, price=50.,
                order_id="pending"+str(context.bar_index), **common),)
        if context.bar_index == 10:
            return (OrderCommand(at, action=OrderAction.AMEND, target_order_id="pending9", price=99.),)
        if context.bar_index == 12 and context.positions["X"]:
            return (OrderCommand(at, symbol="X", side=OrderSide.SELL, order_type=OrderType.MARKET,
                qty=context.positions["X"], reduce_only=True, order_id="feedback-exit"),)
        if context.bar_index == 20:
            return (OrderCommand(at, symbol="X", side=OrderSide.BUY, order_type=OrderType.MARKET,
                qty=1e8, order_id="oversized"),)
        if context.bar_index == 24:
            return (OrderCommand(at, action=OrderAction.CANCEL, target_order_id="pending22"),)
        return ()


def lifecycle_output(seen, data, params, train_index, test_index, fold):
    return WfoExecutionWindow("event_driven", test_index,
        strategy_factory=partial(LifecycleAlpha, seen))


@pytest.mark.parametrize("backend", ["python", "rust"])
def test_public_lifecycle_uses_original_fills_not_proxy(tmp_path, backend):
    frame = market()
    frame.loc[:, ["open", "close"]] = 100.
    frame.loc[:, "high"], frame.loc[:, "low"] = 101., 99.
    frame.iloc[8, frame.columns.get_loc("high")] = 103.
    seen = []
    alpha = partial(lifecycle_output, seen)
    original = QuantBTEndpoint.event_driven(input_mode="strategy", backend=backend,
        profile="audit", symbols=["X"], initial_capital=20000., leverage=3.,
        fee_rate=.001, slippage_bps=0., use_funding=False)
    e, _, ranges, _ = public_setup(tmp_path, frame=frame, strategy=alpha,
        ranges={"period": 6}, trials=1, execution_endpoint=original, target_mode="event_driven")
    result = e.backtest(data=frame, param_ranges=ranges)
    fixed = result.metadata["walk_forward_result"].oos_output
    replay = execute_window(original.config, frame, fixed)
    for name in ("equity", "positions", "fees", "funding", "margin"):
        np.testing.assert_array_equal(getattr(result, name), getattr(replay, name))
    assert [asdict(f) for f in result.fills] == [asdict(f) for f in replay.fills]
    ids = {f.order_id for f in result.fills}
    assert {"parent", "tp", "pending9", "feedback-exit"} <= ids
    assert "oversized" not in ids and "pending22" not in ids
    events = result.metadata["order_events"]
    assert {"amend", "cancel", "reject"} <= set(events.event_name)
    # The strategy boundary copies mutable user state. Prove feedback from
    # the actual exit quantity, not the original caller's diagnostic list.
    exit_fill = next(f for f in result.fills if f.order_id == "feedback-exit")
    assert exit_fill.qty == .5
    audit = result.metadata["walk_forward"]["mode5_diagnostics_first"]
    assert audit["compute_bill"]["original_account_observations"] == 2
    assert e.config.walkforward_config.mode5_calibration.journal.history()
