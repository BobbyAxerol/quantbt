"""Actual QuantBT goldens with independent, fully specified expectations."""

import pytest

from quantbt import OrderAction, OrderActivationPolicy, OrderCommand, OrderSide, OrderType, QuantBTEndpoint
from tools.mode5_admission.ledger import assert_accounting, reconcile_fills
from tests.mode5.test_admission_ledger import market, order, run


def protection(data, *, stop=95., q=10., ladder=((102., 4.), (104., 2.4), (106., 3.6))):
    common = dict(timestamp=data.index[1], symbol="X", side=OrderSide.SELL, reduce_only=True,
        parent_order_id="entry", activation_policy=OrderActivationPolicy.ON_PARENT_FIRST_FILL)
    return (OrderCommand(order_type=OrderType.STOP_MARKET, trigger_price=stop,
                        qty=q, order_id="stop", **common),
            *(OrderCommand(order_type=OrderType.LIMIT, price=price, qty=qty, order_id=f"rung-{i}", **common)
              for i, (price, qty) in enumerate(ladder)))


@pytest.mark.parametrize("same_bar", (False, True))
def test_m5t_017_actual_partial_ladder_not_one_tp(same_bar):
    data = market((100.,)*6)
    if same_bar:
        data.iloc[2, data.columns.get_loc("high")] = 107.
    else:
        for bar, high in ((2, 103.), (3, 105.), (4, 107.)):
            data.iloc[bar, data.columns.get_loc("high")] = high
    result = run(data, (order(data, 1, OrderSide.BUY, 10., "entry"), *protection(data)))
    assert [f.qty for f in result.fills] == pytest.approx([10., 4., 2.4, 3.6])
    assert [f.price for f in result.fills] == [100., 102., 104., 106.]
    assert [f.timestamp for f in result.fills] == [data.index[1], *(
        [data.index[2]] * 3 if same_bar else list(data.index[2:5]))]
    assert len(result.fills) == 4
    witness = reconcile_fills(data.index, data.close, result.fills, initial_capital=20000., fee_rate=.0004)
    assert_accounting(result, witness)
    assert len(witness.closed_campaigns) == 1 and not witness.open_campaigns
    assert result.equity.iloc[-1] == pytest.approx(20000.+4.*2.+2.4*4.+3.6*6.-.0004*(1000.+1039.2))


def test_m5t_018_stop_closes_only_remaining_quantity_after_partial():
    data = market((100., 100., 100., 94., 94., 94.))
    data.iloc[2, data.columns.get_loc("high")] = 103.
    result = run(data, (order(data, 1, OrderSide.BUY, 10., "entry"), *protection(data)))
    # Static result ledgers are command-ordered. These fills occur on distinct
    # bars, so chronological projection is unambiguous and changes no event.
    chronological = sorted(result.fills, key=lambda fill: fill.timestamp)
    assert [f.order_id for f in chronological] == ["entry", "rung-0", "stop"]
    assert [f.qty for f in chronological] == [10., 4., 6.]
    assert chronological[-1].price == 94.
    assert_accounting(result, reconcile_fills(data.index, data.close, chronological,
                                            initial_capital=20000., fee_rate=.0004))


def test_stop_before_tp_when_both_touched_and_gap_price_not_trigger():
    data = market((100.,)*5)
    data.iloc[2, data.columns.get_loc("high")] = 108.
    data.iloc[2, data.columns.get_loc("low")] = 90.
    result = run(data, (order(data, 1, OrderSide.BUY, 10., "entry"), *protection(data)))
    assert [f.order_id for f in result.fills] == ["entry", "stop"]
    assert result.fills[-1].price == 95.
    assert result.positions.iloc[-1, 0] == 0.
    gap = market((100., 100., 80., 80., 80.))
    result = run(gap, (order(gap, 1, OrderSide.BUY, 10., "entry"), *protection(gap)))
    assert result.fills[-1].price == 80.
    assert_accounting(result, reconcile_fills(gap.index, gap.close, result.fills,
                                            initial_capital=20000., fee_rate=.0004))


def test_m5t_016_actual_amendment_only_after_close_observation():
    data = market((100.,)*6)
    seen = []

    class Strategy:
        def on_bar_close(self, context):
            seen.append((context.bar_index, len(context.fills_this_bar)))
            common = dict(timestamp=context.timestamp, symbol="X", side=OrderSide.SELL,
                          order_type=OrderType.LIMIT, qty=1., reduce_only=True, order_id="tp", price=120.)
            if context.bar_index == 0:
                return (OrderCommand(context.timestamp, symbol="X", side=OrderSide.BUY,
                        order_type=OrderType.MARKET, qty=1., order_id="entry"), OrderCommand(**common))
            if context.bar_index == 2:
                return (OrderCommand(context.timestamp, action=OrderAction.AMEND,
                                     target_order_id="tp", price=101.),)
            return ()

    result = QuantBTEndpoint.event_driven(backend="python", profile="audit", symbols=["X"],
        execution_contract="event_lifecycle_v3_next_open", initial_capital=20000., leverage=1.,
        fee_rate=.0004, slippage_bps=0., use_funding=False).backtest(data=data, strategy=Strategy())
    assert [(f.timestamp, f.price) for f in result.fills] == [(data.index[1], 100.), (data.index[3], 101.)]
    amendments = result.metadata["order_events"]
    assert list(amendments.loc[amendments.event_name == "amend", "timestamp"]) == [data.index[3]]
    assert (2, 0) in seen and (3, 1) in seen
    assert_accounting(result, reconcile_fills(data.index, data.close, result.fills,
                                            initial_capital=20000., fee_rate=.0004))
