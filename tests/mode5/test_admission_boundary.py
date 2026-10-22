"""Non-vacuous negative controls for financial route qualification."""

import pytest

from tools.mode5_admission.feedback import UnsupportedFinancialBinding, require_binding, require_exercised


@pytest.mark.parametrize("case", ({"assumed_fills": True}, {"unmapped_intents": 1},
    {"ladder_collapsed": True}, {"requires_fill_reaction": True}))
def test_m5t_020_approximations_never_gain_actual_route_authority(case):
    with pytest.raises(UnsupportedFinancialBinding):
        require_binding(**case)


def test_actual_next_open_plain_binding_can_be_admitted_without_protection_claim():
    require_binding()


def test_zero_fill_path_is_not_an_execution_certificate():
    from tools.mode5_admission.ledger import reconcile_fills
    from tests.mode5.test_admission_ledger import market
    data = market()
    witness = reconcile_fills(data.index, data.close, (), initial_capital=20000.)
    with pytest.raises(ValueError, match="INSUFFICIENT"):
        require_exercised(witness)


def test_existing_callback_observes_fill_after_bar_not_inside_matching():
    from quantbt import OrderCommand, OrderSide, OrderType, QuantBTEndpoint
    from tests.mode5.test_admission_ledger import market
    data = market()
    seen = []

    class Strategy:
        def on_fill(self, *args):
            raise AssertionError("existing callback protocol has no fill-reaction hook")

        def on_bar_close(self, context):
            seen.append((context.bar_index, tuple(fill.price for fill in context.fills_this_bar),
                         float(context.close[0])))
            if context.bar_index == 0:
                return (OrderCommand(context.timestamp, symbol="X", side=OrderSide.BUY,
                    order_type=OrderType.MARKET, qty=1., order_id="actual-entry"),)
            return ()

    result = QuantBTEndpoint.event_driven(backend="python", profile="audit", symbols=["X"],
        execution_contract="event_lifecycle_v3_next_open", initial_capital=20000.,
        leverage=1., fee_rate=.0004, slippage_bps=0., use_funding=False).backtest(data=data, strategy=Strategy())
    assert len(result.fills) == 1
    assert seen[1] == (1, (100.,), 100.)
    assert result.metadata["execution_contract_id"] == "event_lifecycle_v3_next_open"
