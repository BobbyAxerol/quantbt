from dataclasses import replace

import numpy as np
import pytest

from tools.mode5_batteries import RiskCalibration,paired_transfer
from tools.mode5_diagnostics.access import AccessPolicy,AccessWitness
from tools.mode5_statistics.uncertainty import BlockPolicy


def test_m5t_075_frozen_train_scale_requires_actual_forward_resimulation():
    train=AccessWitness("train","development",0,100,100)
    policy=AccessPolicy("train-only",("development",),("train",),100,"selection")
    calibration=RiskCalibration.fit(np.linspace(-.02,.02,91),train_execution_id="actual-train",witness=train,
        policy=policy,target_volatility=.005,scale_cap=1.)
    assert calibration.scale==pytest.approx(.005/np.std(np.linspace(-.02,.02,91),ddof=1))
    forward=AccessWitness("forward","EXPLORATORY_REVIEWED_2024",101,200,200)
    declared=calibration.require_forward(forward)
    assert declared["required_method"]=="ACTUAL_ACCOUNT_RESIMULATION" and not declared["ex_post_path_scaling_allowed"]
    with pytest.raises(PermissionError):
        calibration.require_forward(train)
    with pytest.raises(PermissionError):
        RiskCalibration.fit(np.arange(91)/1000,train_execution_id="later",witness=forward,policy=policy,
                            target_volatility=.005,scale_cap=1.)


@pytest.mark.parametrize("returns",[np.zeros(91),np.array([.1]*2),np.full(91,np.nan)])
def test_risk_scale_undefined_train_is_not_silently_favorable(returns):
    w=AccessWitness("train","development",0,100,100)
    with pytest.raises(ValueError):
        RiskCalibration.fit(returns,train_execution_id="actual",witness=w,
            policy=AccessPolicy("p",("development",),("train",),100,"selection"),target_volatility=.005,scale_cap=1.)


def test_paired_transfer_identity_has_zero_difference_not_fake_positive_gain():
    x=np.random.default_rng(731).normal(.001,.01,91)
    out=paired_transfer(x,x,x,x,policy=BlockPolicy(draws=32))
    assert out["status"]=="VALID" and all(v==0 for v in out["estimate"].values())
    assert all(v==(0.,0.) for v in out["intervals"].values())
    assert out["interval_scope"]=="FIXED_PATH_NOT_WHOLE_RECIPE_UNCERTAINTY"


def test_lower_is_alone_reduces_decay_without_better_forward_quality():
    x=np.random.default_rng(731).normal(.001,.01,91)
    out=paired_transfer(x+.01,x,x,x,policy=BlockPolicy(draws=32))
    assert out["estimate"]["decay_change"]<0 and out["estimate"]["forward_quality_change"]==0


def test_transfer_swapping_treatment_control_changes_estimate_sign_exactly():
    rng=np.random.default_rng(1); a,b,c,d=(rng.normal(0,.01,91) for _ in range(4))
    x=paired_transfer(a,b,c,d,policy=BlockPolicy(draws=32)); y=paired_transfer(b,a,d,c,policy=BlockPolicy(draws=32))
    assert x["estimate"]==pytest.approx({k:-v for k,v in y["estimate"].items()})
    assert x["intervals"]=={k:pytest.approx((-v[1],-v[0])) for k,v in y["intervals"].items()}


@pytest.mark.parametrize("x",[np.array([.1]*8),np.zeros(91)])
def test_insufficient_or_zero_variance_does_not_invent_uncertainty(x):
    assert paired_transfer(x,x,x,x)["status"]=="INSUFFICIENT"


def test_bankruptcy_and_mismatched_calendar_fail_closed():
    x=np.linspace(-.01,.01,91)
    with pytest.raises(ValueError,match="solvent"):
        paired_transfer(x,x,x,np.r_[-1.,x[1:]])
    with pytest.raises(ValueError,match="calendar"):
        paired_transfer(x,x[:-1],x,x)
