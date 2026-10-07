"""Cross-fold quantity clipping/rejection uses the original financial contract."""

import pytest
from dataclasses import replace

from quantbt import OrderCommand, OrderSide, OrderType
from quantbt.wfo_execution import WfoExecutionWindow, execute_window, stitch_execution_windows
from tests.meta_selection.test_e07_lifecycle import financial, frame


@pytest.mark.parametrize("backend", ("python", "rust"))
@pytest.mark.parametrize("route", ("event_driven", "order_commands"))
@pytest.mark.parametrize("clock", (None, "event_lifecycle_v3_next_open"))
def test_e07_cross_fold_partial_reduce_and_margin_rejection(backend, route, clock):
    data = frame()
    # Tape timestamps are effective bars; callback commands shift after close.
    entry_bar, exit_bar = (2, 4) if route == "event_driven" else (1, 3)
    data.loc[data.index[entry_bar], ["open", "high"]] = [110., 111.]
    data.loc[data.index[exit_bar], ["open", "high"]] = [105., 106.]
    schedule = {data.index[1]: OrderCommand(data.index[1], symbol="X", side=OrderSide.BUY,
            order_type=OrderType.MARKET, qty=1., order_id="entry"),
        data.index[3]: OrderCommand(data.index[3], symbol="X", side=OrderSide.SELL,
            order_type=OrderType.MARKET, qty=3., reduce_only=True, order_id="clipped-exit"),
        data.index[5]: OrderCommand(data.index[5], symbol="X", side=OrderSide.BUY,
            order_type=OrderType.MARKET, qty=1000., order_id="over-margin")}

    class Child:
        def on_bar_close(self, context):
            command = schedule.get(context.timestamp)
            return () if command is None else (command,)

    windows = []
    for index in (data.index[:2], data.index[2:]):
        kwargs = dict(strategy_factory=Child) if route == "event_driven" else dict(
            commands=tuple(c for c in schedule.values() if c.timestamp in index))
        windows.append(WfoExecutionWindow(route, index, **kwargs))
    config = replace(financial(backend, route).config, execution_contract=clock)
    result = execute_window(config, data,
                            stitch_execution_windows(windows, data.index))
    prices = (100., 100.) if clock is None else (110., 105.)
    assert [(f.timestamp, f.order_id, f.qty, f.price) for f in result.fills] == [
        (data.index[entry_bar], "entry", 1., prices[0]),
        (data.index[exit_bar], "clipped-exit", 1., prices[1])]
    assert result.metadata["execution_contract_id"] == (clock or "event_lifecycle_v2_next_bar_close")
    assert result.fees.sum() == pytest.approx(sum(prices)*.001)
    assert result.equity.iloc[-1] == pytest.approx(1000.+prices[1]-prices[0]-sum(prices)*.001)
    assert result.positions.iloc[-1, 0] == 0.
    assert result.metadata["lifecycle_counters"]["rejected_count"] == 1
