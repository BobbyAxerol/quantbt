import numpy as np

from tests.mode5.test_environment_attribution import account,DAY
from tools.mode5_environments import daily_path,attribute_days,overlap_support


def test_actual_exit_cost_on_flat_close_mark_is_not_no_trade():
    _,result,evidence,policy = account()
    assert result.positions.iloc[10,0] == 0 and result.fees.iloc[10] > 0
    labels = np.zeros(12,dtype=int)
    labels[10:] = 1
    rows = attribute_days(daily_path(evidence,policy,initial_equity=20000.),labels)["rows"]
    assert rows[1]["fees"] > 0 and rows[1]["status"] == "NO_CLOSE_MARK_EXPOSURE"


def test_closed_campaigns_with_zero_close_mark_exposure_remain_visible():
    out = overlap_support(np.array([DAY,2*DAY],dtype=np.int64),
        {"exit":{"family":"states","membership":np.ones(2,dtype=int)}},family_weights={"states":1.},
        exposure=np.zeros(2),campaigns_per_day=np.array([1,0]),minimum_days=1,minimum_exposed_bars=1,minimum_campaigns=1)
    assert out["rows"][0]["closed_campaigns"] == 1
    assert out["rows"][0]["status"] == "INSUFFICIENT_SUPPORT"
