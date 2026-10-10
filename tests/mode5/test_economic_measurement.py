"""M5T-105..108: independent arithmetic, units and undefined populations."""
from dataclasses import replace
import copy
import pickle
import math

import numpy as np
import pytest

from tools.mode5_economics import account_summary, cost_margin, fixed_decay, profit_factor
from economics_fixtures import path, returns


def test_turnover_allocation_cost_mde_is_account_bps_not_position_bps():
    row = cost_margin(incremental_one_way_fee=.001, position_turnover_per_day=.064, account_allocation=.1)
    assert row["bps_account_per_day"] == pytest.approx(.064)
    assert row["decimal_account_per_day"] == pytest.approx(.0000064)
    assert row["already_in_net_returns_not_deducted_twice"]


@pytest.mark.parametrize("bad", [-1., float("nan"), float("inf")])
def test_invalid_cost_inputs_are_not_clamped(bad):
    with pytest.raises(ValueError):
        cost_margin(incremental_one_way_fee=bad, position_turnover_per_day=1., account_allocation=1.)


def test_daily_sharpe_psr_and_growth_match_independent_oracle():
    values = returns()
    row = account_summary(path(values))
    expected = np.mean(values)/np.std(values,ddof=1)*math.sqrt(365)
    assert row["annualized_sharpe"] == pytest.approx(expected,abs=1e-12)
    assert row["mean_daily_log_growth"] == pytest.approx(sum(math.log1p(v) for v in values)/len(values))
    psr = row["psr"]["components"]
    assert dict(psr)["sr_period"] == pytest.approx(expected/math.sqrt(365))
    assert row["daily_loss_es"]["unit"] == "decimal_return"


@pytest.mark.parametrize("values,status", [([0.]*64,"VALID"), ([-1.]+[0.]*63,"BANKRUPT"),
    ([float("nan")]+[0.]*63,"INVALID"), ([float("inf")]+[0.]*63,"INVALID")])
def test_invalid_bankrupt_and_zero_variance_paths_remain_distinct(values,status):
    row = account_summary(path(values))
    assert row["status"] == status
    if status == "VALID":
        assert row["annualized_sharpe"] is None and row["sharpe_status"] == "UNDEFINED"
        assert row["mean_daily_net"] == 0


def test_unverified_accounting_cannot_be_an_economic_observation():
    assert account_summary(path(returns(),accounting_verified=False))["status"] == "INVALID"


@pytest.mark.parametrize("clone", [copy.deepcopy, lambda x: pickle.loads(pickle.dumps(x))])
def test_daily_evidence_cannot_mutate_after_copy(clone):
    source = path(returns())
    cloned = clone(source)
    assert cloned.identity == source.identity
    with pytest.raises(ValueError):
        cloned.returns[-1] = -1.


def test_no_silent_calendar_intersection():
    source = path(returns())
    from tools.mode5_economics import DailyAccount
    with pytest.raises(ValueError,match="contiguous"):
        DailyAccount.from_arrays(source.times[::2],source.returns[::2],**{
            k:v for k,v in source.__dict__.items() if k not in {"times_bytes","return_bytes"}})


@pytest.mark.parametrize("pnl,status", [(None,"UNAVAILABLE"), ([0.,0.],"UNDEFINED"),
    ([1.,2.],"UNDEFINED"), ([-1.,-2.],"UNDEFINED"), ([1.,-2.],"VALID")])
def test_pf_zero_denominator_or_profit_never_gets_epsilon(pnl,status):
    row = profit_factor(pnl,minimum_campaigns=2)
    assert row["status"] == status
    assert (row["value"] is not None) == (status == "VALID")
    if status=="VALID": assert row["value"] == .5


def test_pf_campaign_support_and_overflow_are_explicit():
    assert profit_factor([1.,-1.],minimum_campaigns=20)["status"] == "INSUFFICIENT"
    assert profit_factor([1e308,1e308],minimum_campaigns=2)["status"] == "INVALID"


def test_same_vector_decay_matches_direct_difference_and_log_pf():
    values = returns()
    a, b = path(values), path(values*.5+.0002,year=2025)
    pa, pb = profit_factor([3.,-1.],minimum_campaigns=2), profit_factor([2.,-1.],minimum_campaigns=2)
    row = fixed_decay(a,b,development_pf=pa,forward_pf=pb)
    assert row["sharpe_decay"] == pytest.approx(account_summary(a)["annualized_sharpe"]-account_summary(b)["annualized_sharpe"])
    assert row["log_profit_factor_decay"] == pytest.approx(math.log(3)-math.log(2))
    assert row["ratio_not_used"]


@pytest.mark.parametrize("field,value", [("params_digest","different"),("economic_contract","fee_changed"),
    ("terminal_policy","carry")])
def test_incomparable_fixed_vectors_costs_or_terminal_fail(field,value):
    with pytest.raises(ValueError,match="fixed vector"):
        fixed_decay(path(returns()),replace(path(returns(),year=2025),**{field:value}))
