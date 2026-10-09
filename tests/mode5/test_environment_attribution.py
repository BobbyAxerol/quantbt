from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from tests.mode5.test_admission_ledger import market, order, run
from quantbt import OrderSide
from tools.mode5_diagnostics import AccessPolicy, AccessWitness, ExecutionEvidence, MissingInputs
from tools.mode5_environments import daily_path, attribute_days, attribute_campaigns, overlap_support

DAY = 86_400_000_000_000


def account():
    frame = market(100.+np.arange(12))
    frame.index = pd.date_range("2024-01-01",periods=12,freq="D",tz="UTC")
    commands = (order(frame,1,OrderSide.BUY,20.,"entry"),
                order(frame,10,OrderSide.SELL,20.,"exit",reduce_only=True))
    result = run(frame,commands)
    witness = AccessWitness("actual-continuous","synthetic",int(frame.index[0].value),int(frame.index[-1].value)+DAY,
                            int(frame.index[-1].value)+DAY)
    policy = AccessPolicy("actual",("synthetic",),(witness.manifest_id,),witness.ready_ns,"diagnostic")
    arrays = dict(timestamps=frame.index.asi8,equity=result.equity.to_numpy(),
        positions=result.positions.iloc[:,0].to_numpy(),fees=result.fees.to_numpy())
    evidence = ExecutionEvidence.from_arrays("actual-account",witness,arrays,source_ref="synthetic-QuantBT",backend="python-oracle")
    return frame,result,evidence,policy


def test_m5t_044_disjoint_regime_uses_actual_account_marks_no_price_splice():
    _,result,evidence,policy = account()
    path = daily_path(evidence,policy,initial_equity=20000.)
    labels = np.array([0,0,1,1,1,0,0,1,1,0,1,1])
    groups = attribute_days(path,labels)
    assert len(result.fills) == 2 and np.count_nonzero(path.pnl.array()) > 3
    assert groups["summed_group_pnl"] == pytest.approx(result.equity.iloc[-1]-20000.,abs=1e-8)
    assert groups["fees"] == pytest.approx(result.fees.sum(),abs=1e-10)
    assert groups["compounded_path_return"] == pytest.approx(result.equity.iloc[-1]/20000.-1,abs=1e-12)
    assert all(row["annualized_return"] is None for row in groups["rows"])
    np.testing.assert_array_equal(evidence.arrays()["equity"],result.equity.to_numpy())


def test_m5t_045_actual_reset_episode_differs_from_carried_account():
    frame,result,evidence,policy = account()
    carried = daily_path(evidence,policy,initial_equity=20000.)
    episode = frame.iloc[5:].copy()
    reset = run(episode,())
    assert result.equity.iloc[8] > result.equity.iloc[4]
    assert reset.positions.to_numpy().sum() == 0 and reset.equity.iloc[-1] == 20000.
    reset_view = replace(carried,mode="CONTIGUOUS_RESET_EPISODES")
    with pytest.raises(ValueError,match="reset"):
        attribute_days(reset_view,np.zeros(12,dtype=int))


def test_m5t_046_dual_families_share_dates_without_double_evidence_mass():
    dates = np.arange(1,7,dtype=np.int64)*DAY
    views = {"anchor":{"family":"anchors","membership":np.ones(6,dtype=int)},
             "vol-high":{"family":"endogenous","membership":np.array([1,0,1,0,1,0])},
             "vol-low":{"family":"endogenous","membership":np.array([0,1,0,1,0,1])}}
    args = dict(family_weights={"anchors":.5,"endogenous":.5},exposure=np.ones(6),campaigns_per_day=np.ones(6),
                minimum_days=1,minimum_exposed_bars=1,minimum_campaigns=1)
    report = overlap_support(dates,views,**args)
    assert report["total_allocated_mass"] == 6 and report["repeated_memberships"] == 6
    assert report["covered_unique_dates"] == 6 and report["independent_information_count"] is None
    copies = dict(views,copy=views["anchor"])
    repeated = overlap_support(dates,copies,**args)
    assert repeated["total_allocated_mass"] == report["total_allocated_mass"]
    assert len(repeated["duplicate_views"]) == 1


def test_m5t_047_rare_no_trade_missing_and_adverse_cells_are_retained():
    dates = np.arange(1,7,dtype=np.int64)*DAY
    masks = {"rare":np.array([1,0,0,0,0,0]),"missing":np.full(6,-1),
             "no-trade":np.array([0,0,0,1,1,1]),"adverse":np.array([0,1,1,0,0,0])}
    views = {key:{"family":"states","membership":value} for key,value in masks.items()}
    report = overlap_support(dates,views,family_weights={"states":1.},exposure=np.array([1,1,1,0,0,0]),
        campaigns_per_day=np.array([0,1,1,0,0,0]),minimum_days=2,minimum_exposed_bars=2,minimum_campaigns=1)
    statuses = {r["view"]:r["status"] for r in report["rows"]}
    assert statuses == {"rare":"INSUFFICIENT_SUPPORT","missing":"MISSING", "no-trade":"NO_TRADE",
                        "adverse":"SUPPORTED_DESCRIPTIVE"}
    assert report["rows"][1]["unavailable_days"] == 6


@pytest.mark.parametrize("method",["entry_state","duration_weighted"])
def test_cross_state_campaigns_reconcile_with_named_attribution(method):
    _,result,evidence,policy = account()
    times = evidence.arrays()["timestamps"]
    fills = result.fills
    campaigns = [dict(id="campaign1",opened_ns=int(fills[0].timestamp.value),end_ns=int(fills[-1].timestamp.value),
        net_pnl=float(result.equity.iloc[-1]-20000.),closed=True)]
    labels = np.r_[np.zeros(5,dtype=int),np.ones(7,dtype=int)]
    out = attribute_campaigns(campaigns,times,labels,method=method)
    assert out["allocation_sum"] == pytest.approx(out["total_net_pnl"],abs=1e-12)
    assert out["closed_campaigns"] == 1 and not out["mark_attribution"]
    if method == "entry_state":
        assert out["allocation"][1] == 0
    else:
        assert out["allocation"][0] > 0 and out["allocation"][1] > 0


def test_duration_attribution_uses_elapsed_time_not_asynchronous_bar_counts():
    times = np.array([0,1,100],dtype=np.int64)
    out = attribute_campaigns([dict(id="c",opened_ns=0,end_ns=100,net_pnl=100.,closed=False)],
                              times,np.array([0,1,1]),method="duration_weighted")
    assert out["allocation"] == {0:1.,1:99.}
    assert out["censored_open_campaigns"] == 1


def test_missing_ledger_inputs_fail_without_implicit_replay_or_fabrication():
    _,_,evidence,policy = account()
    raw = evidence.arrays()
    del raw["fees"]
    incomplete = ExecutionEvidence.from_arrays(evidence.execution_id,evidence.witness,raw,
        source_ref=evidence.source_ref,backend=evidence.backend)
    with pytest.raises(MissingInputs,match="fees"):
        daily_path(incomplete,policy,initial_equity=20000.)


def test_bankrupt_and_unknown_label_kept_without_fake_zero_return():
    _,_,evidence,policy = account()
    arrays = evidence.arrays()
    arrays["equity"] = np.r_[np.full(5,20000.),-100.,np.full(6,-100.)]
    bankrupt = ExecutionEvidence.from_arrays(evidence.execution_id,evidence.witness,arrays,
        status="VALID_ADVERSE",source_ref=evidence.source_ref,backend=evidence.backend)
    groups = attribute_days(daily_path(bankrupt,policy,initial_equity=20000.),np.full(12,-1,dtype=int))
    assert groups["return_status"] == "BANKRUPT_OR_NONPOSITIVE_BASE"
    assert groups["compounded_path_return"] is None and groups["rows"][0]["money_pnl"] == -20100.


@pytest.mark.parametrize("change",["fees_length","duplicate_time","out_of_manifest","bad_labels"])
def test_invalid_account_or_membership_contract_rejected(change):
    _,_,evidence,policy = account()
    raw = {k:v.copy() for k,v in evidence.arrays().items()}
    if change == "fees_length":
        raw["fees"] = raw["fees"][:-1]
    elif change == "duplicate_time":
        raw["timestamps"][1] = raw["timestamps"][0]
    elif change == "out_of_manifest":
        raw["timestamps"][0] -= DAY
    else:
        with pytest.raises(ValueError):
            attribute_days(daily_path(evidence,policy,initial_equity=20000.),np.zeros(13,dtype=int))
        return
    invalid = ExecutionEvidence.from_arrays(evidence.execution_id,evidence.witness,raw,
        source_ref=evidence.source_ref,backend=evidence.backend)
    with pytest.raises(ValueError):
        daily_path(invalid,policy,initial_equity=20000.)
