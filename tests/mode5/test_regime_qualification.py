from copy import deepcopy

import pytest

from tools.mode5_research.regime_qualification import finite_panel_regimes


def observations():
    values={"a":(.01,-.01),"b":(.02,-.02),"c":(.03,-.03),"winner":(.04,-.04)}
    return {cid:dict(views={"descriptive":{"trend":dict(conservation_residual=0.,rows=[
        dict(state=i,mean_net_daily_return=value,days=10,pnl=value*100)
        for i,value in enumerate(pair)])}}) for cid,pair in values.items()}


def test_later_winner_cannot_inflate_diagnostic_reference():
    source=observations();before=deepcopy(source)
    result=finite_panel_regimes(source,("a","b","c"),{"arm":"winner"})
    rows=result["views"]["descriptive"]["trend"]["states"]
    comparison=rows[0]["winners"]["arm"]["comparison_to_diagnostic_panel"]
    assert comparison["reference_mean_net_daily_return"]==.03
    assert comparison["signed_reference_gap"]==pytest.approx(-.01)
    assert comparison["regret"]==0
    assert comparison["extrapolated_above_reference"]
    assert rows[1]["winners"]["arm"]["comparison_to_diagnostic_panel"]["regret"]==pytest.approx(.03)
    assert result["views"]["descriptive"]["trend"]["rank_associations"][1]["spearman"]==-1
    assert source==before


def test_missing_state_and_account_mismatch_are_errors():
    rows=observations();rows["b"]["views"]["descriptive"]["trend"]["rows"].pop()
    with pytest.raises(ValueError,match="roster"):
        finite_panel_regimes(rows,("a","b","c"),{"arm":"winner"})
    rows=observations();rows["a"]["views"]["descriptive"]["trend"]["conservation_residual"]=.1
    with pytest.raises(ValueError,match="reconcile"):
        finite_panel_regimes(rows,("a","b","c"),{"arm":"winner"})


def test_zero_and_undefined_remain_visible():
    rows=observations()
    rows["a"]["views"]["descriptive"]["trend"]["rows"][0]["mean_net_daily_return"]=None
    rows["b"]["views"]["descriptive"]["trend"]["rows"][0]["mean_net_daily_return"]=0.
    result=finite_panel_regimes(rows,("a","b","c"),{"arm":"winner"})
    view=result["views"]["descriptive"]["trend"]["states"][0]
    assert view["undefined_diagnostic"]==view["flat_mean_candidates"]==1
