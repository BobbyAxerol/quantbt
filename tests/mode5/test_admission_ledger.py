"""Public synthetic fixtures; no private strategy source or parameters."""

import numpy as np
import pandas as pd
import pytest

from quantbt import OrderCommand, OrderSide, OrderType, QuantBTEndpoint
from tools.mode5_admission.ledger import assert_accounting, reconcile_fills


def market(prices=(100., 100., 105., 95., 110., 110.)):
    idx = pd.date_range("2024-01-01", periods=len(prices), freq="h", tz="UTC")
    return pd.DataFrame(dict(open=prices, high=np.asarray(prices)+1,
                             low=np.asarray(prices)-1, close=prices, volume=1000.), index=idx)


def run(data, commands, *, fee=.0004):
    endpoint = QuantBTEndpoint.event_driven(
        input_mode="orders", backend="python", profile="audit", symbols=["X"],
        execution_contract="event_lifecycle_v3_next_open", initial_capital=20000.,
        leverage=1., fee_rate=fee, slippage_bps=0., use_funding=False,
    )
    return endpoint.backtest(data=data, order_commands=commands, symbols=["X"])


def order(data, bar, side, qty, name, **kw):
    return OrderCommand(data.index[bar], symbol="X", side=side, order_type=OrderType.MARKET,
                        qty=qty, order_id=name, **kw)


def test_m5t_019_exact_quote_notional_one_way_fee_and_mtm():
    data = market((100.,)*5)
    out = run(data, (order(data, 1, OrderSide.BUY, 20., "entry"),
                     order(data, 3, OrderSide.SELL, 20., "exit", reduce_only=True)))
    assert [f.fee for f in out.fills] == pytest.approx([.8, .8])
    assert [f.timestamp for f in out.fills] == [data.index[1], data.index[3]]
    assert out.equity.iloc[-1] == pytest.approx(19998.4)
    witness = reconcile_fills(data.index, data.close, out.fills, initial_capital=20000., fee_rate=.0004)
    assert_accounting(out, witness)
    assert len(witness.closed_campaigns) == 1
    assert witness.closed_campaigns[0]["net_pnl"] == pytest.approx(-1.6)


def test_mtm_open_campaign_and_mark_only_terminal():
    data = market()
    out = run(data, (order(data, 1, OrderSide.BUY, 2., "entry"),))
    witness = reconcile_fills(data.index, data.close, out.fills, initial_capital=20000., fee_rate=.0004)
    assert_accounting(out, witness)
    assert len(witness.open_campaigns) == 1 and not witness.closed_campaigns
    assert out.equity.iloc[-1] == pytest.approx(20019.92)
    assert out.positions.iloc[-1, 0] == 2.


def test_partial_and_reversal_cost_allocation_is_one_actual_fill():
    data = market()
    out = run(data, (order(data, 1, OrderSide.BUY, 10., "entry"),
                     order(data, 2, OrderSide.SELL, 4., "partial", reduce_only=True),
                     order(data, 3, OrderSide.SELL, 8., "reverse"),
                     order(data, 4, OrderSide.BUY, 2., "short-exit", reduce_only=True)))
    witness = reconcile_fills(data.index, data.close, out.fills, initial_capital=20000., fee_rate=.0004)
    assert_accounting(out, witness)
    assert len(out.fills) == 4 and len(witness.closed_campaigns) == 2
    assert not witness.open_campaigns
    assert sum(row["fees"] for row in witness.closed_campaigns) == pytest.approx(out.fees.sum())


def test_post_cost_rejection_has_no_fabricated_fill():
    data = market()
    out = run(data, (order(data, 1, OrderSide.BUY, 200., "too-large"),))
    assert not out.fills
    assert "reject" in set(out.metadata["order_events"].event_name)
    assert_accounting(out, reconcile_fills(data.index, data.close, out.fills, initial_capital=20000.))


def test_bad_fill_fee_or_calendar_fails_closed():
    from dataclasses import replace
    data = market()
    out = run(data, (order(data, 1, OrderSide.BUY, 2., "entry"),))
    with pytest.raises(ValueError, match="one-way"):
        reconcile_fills(data.index, data.close, (replace(out.fills[0], fee=0.),),
                        initial_capital=20000., fee_rate=.0004)
    with pytest.raises(ValueError, match="calendar"):
        reconcile_fills(data.index[2:], data.close.iloc[2:], out.fills, initial_capital=20000.)


def test_small_actual_residual_is_not_silently_closed_or_counted_as_campaign():
    data = market((100.,)*5)
    out = run(data, (order(data, 1, OrderSide.BUY, .3, "entry"),
                     order(data, 3, OrderSide.SELL, .3-1e-13, "partial", reduce_only=True)))
    assert out.positions.iloc[-1, 0] > 0.
    witness = reconcile_fills(data.index, data.close, out.fills, initial_capital=20000., fee_rate=.0004)
    assert_accounting(out, witness)
    assert not witness.closed_campaigns and len(witness.open_campaigns) == 1
    assert witness.open_campaigns[0]["remaining_qty"] == out.positions.iloc[-1, 0]
