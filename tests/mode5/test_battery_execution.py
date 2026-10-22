import numpy as np
import pytest

from quantbt import OrderSide
from tests.mode5.test_admission_ledger import market,order,run
from tests.mode5.selection_fixtures import panel,plan
from tools.mode5_admission.ledger import assert_accounting,reconcile_fills
from tools.mode5_batteries import compare_selectors
from tests.mode5.test_battery_contracts import scope


@pytest.mark.parametrize("world",["positive","null","all_bad"])
def test_m5t_074_actual_quantbt_broad_region_null_and_bad_without_alpha_name_rules(world):
    counts=[]; values=[]
    for qty in (2.,4.,6.):
        rows=[]
        for drift in (.8,1.,1.2):
            trend=drift if world=="positive" else 0. if world=="null" else -drift
            data=market(100.+trend*np.arange(40))
            result=run(data,(order(data,1,OrderSide.BUY,qty,"entry"),
                order(data,38,OrderSide.SELL,qty,"exit",reduce_only=True)))
            assert len(result.fills)==2 and result.fees.sum()>0
            witness=reconcile_fills(data.index,data.close,result.fills,initial_capital=20000.,fee_rate=.0004)
            assert_accounting(result,witness)
            counts.append(len(witness.closed_campaigns))
            rows.append(float(result.equity.iloc[-1]/20000.-1))
        values.append(rows)
    p=panel(values)
    # The same explicit quality rule handles every world, not its label.
    from dataclasses import replace
    p=replace(p,candidates=tuple(replace(c,quality_pass=min(c.metrics[j].value for j in range(3))>0)
                                for c in p.candidates))
    out=compare_selectors(scope(p),p,[(plan(p),{})])
    decision=out["decisions"][0]
    assert len(decision["component_rows"])==3 and sum(counts)==9
    assert (decision["status"]=="SELECTED")==(world=="positive")
    if world!="positive":
        assert decision["chosen_candidate"] is None


def test_real_execution_double_fee_control_reconciles_not_posthoc_fill_edits():
    data=market((100.,101.,102.,103.,104.))
    commands=(order(data,1,OrderSide.BUY,2.,"entry"),order(data,3,OrderSide.SELL,2.,"exit",reduce_only=True))
    first=run(data,commands,fee=.0004); stress=run(data,commands,fee=.0008)
    assert len(first.fills)==len(stress.fills)==2
    assert stress.fees.sum()==pytest.approx(2*first.fees.sum())
    assert_accounting(stress,reconcile_fills(data.index,data.close,stress.fills,initial_capital=20000.,fee_rate=.0008))
    assert first.equity.iloc[-1]-stress.equity.iloc[-1]==pytest.approx(first.fees.sum())
