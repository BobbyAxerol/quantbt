from dataclasses import replace
import copy
import pickle

import numpy as np
import pytest

from tools.mode5_diagnostics import AccessPolicy, AccessWitness
from tools.mode5_environments import (AnchorManifest, EnvironmentRegistry, FeatureTape, VintageStore,
    fit_partition, ChronologyPlan, KnownArtifact, ScopeUse, require_known, independent_scope, match_calendar)


def fixture():
    times = np.arange(1,61,dtype=np.int64)
    tape = FeatureTape.from_arrays("reviewed-trailing-provider-sha",times,np.sin(times/2),times,
                                   np.zeros(len(times),dtype=np.int8))
    train = AccessWitness("train","synthetic",1,31,31)
    inner = AccessWitness("inner","synthetic",31,41,41)
    outer = AccessWitness("outer","holdout",41,61,61)
    plan = ChronologyPlan("registered",train,inner,outer,41)
    return tape,plan


def test_m5t_041_future_mutation_preserves_fit_and_earlier_decisions():
    tape,plan = fixture()
    fit = fit_partition(tape,plan.train,plan.fit_policy(),namespace="vintage1")
    labels = fit.label(tape,purpose="decision_vintage")
    values = tape.values.array().copy()
    values[40:] *= -1000
    future = FeatureTape.from_arrays(tape.provider_id,tape.times.array(),values,tape.available.array(),tape.quality.array())
    again = fit_partition(future,plan.train,plan.fit_policy(),namespace="vintage1")
    assert fit == again
    assert labels.prefix_identity(40) == again.label(future,purpose="decision_vintage").prefix_identity(40)
    assert np.unique(labels.decision_labels()[30:40]).size > 1


def test_m5t_042_retrospective_revision_does_not_overwrite_decision_vintages():
    tape,plan = fixture()
    decision = fit_partition(tape,plan.train,plan.fit_policy(),namespace="past").label(tape,purpose="decision_vintage")
    store = VintageStore()
    before = store.seal(decision)
    whole = AccessWitness("whole","synthetic",1,61,61)
    policy = AccessPolicy("whole",("synthetic",),("whole",),61,"diagnostic")
    current = fit_partition(tape,whole,policy,namespace="current").label(tape,purpose="asof_calibration_descriptive")
    store.seal(current)
    assert len(store.records()) == 2 and store.seal(decision) == before
    with pytest.raises(PermissionError,match="retrospective"):
        current.decision_labels()
    changed = replace(decision,transform_id="altered-transform")
    with pytest.raises(ValueError,match="sealed"):
        store.seal(changed)


def test_m5t_043_inner_validation_mutation_cannot_change_train_scaler_thresholds():
    tape,plan = fixture()
    original = fit_partition(tape,plan.train,plan.fit_policy(),namespace="fold")
    values = tape.values.array().copy()
    values[30:40] = 1e7
    changed = FeatureTape.from_arrays(tape.provider_id,tape.times.array(),values,tape.available.array(),tape.quality.array())
    fitted = fit_partition(changed,plan.train,plan.fit_policy(),namespace="fold")
    assert original.mean == fitted.mean and original.scale == fitted.scale
    assert original.thresholds == fitted.thresholds and original.identity == fitted.identity
    with pytest.raises(PermissionError):
        fit_partition(changed,plan.inner_validation,plan.fit_policy(),namespace="wrong")


def test_m5t_049_maturity_discovery_recipe_and_lineage_are_all_required():
    _,plan = fixture()
    log = []
    artifact = KnownArtifact("selected",plan.inner_validation,41,41,("registered-candidate",))
    require_known(artifact,plan.selection_policy(),permitted_lineage={"registered-candidate"},log=log.append)
    for item in (replace(artifact,discovered_ns=42,selected_ns=42),
                 replace(artifact,lineage_ids=("future-recipe",)),
                 replace(artifact,witness=AccessWitness("inner","synthetic",31,41,42),discovered_ns=42,selected_ns=42)):
        with pytest.raises(PermissionError):
            require_known(item,plan.selection_policy(),permitted_lineage={"registered-candidate"},log=log.append)
    assert [row["decision"] for row in log] == ["AUTHORIZED","DENIED","DENIED","DENIED"]


def test_m5t_050_reviewed_stress_dates_cannot_be_renamed_as_independent_holdout():
    reviewed = AccessWitness("2024-stress","EXPLORATORY_REVIEWED_2024",100,200,200)
    prior = [ScopeUse("BTC-history",reviewed,"diagnostic")]
    request = ScopeUse("BTC-history",AccessWitness("new-holdout-id","holdout",150,250,250),"independent_validation")
    with pytest.raises(PermissionError,match="REVIEWED"):
        independent_scope(request,prior)
    safe = replace(request,witness=AccessWitness("later","holdout",200,250,250))
    assert independent_scope(safe,prior)["checked_prior_uses"] == 1


def test_m5t_048_realistic_candidate_warmup_common_score_without_silent_truncation():
    times = np.arange(100,200,dtype=np.int64)
    rows = {"short":{"required_preload_ns":100,"ready_ns":110},
            "long":{"required_preload_ns":80,"ready_ns":130}}
    result = match_calendar(times,score_start_ns=120,end_ns=190,candidates=rows)
    assert result["status"] == "NOT_READY" and result["actual_first_ns"] == 120
    assert result["scored_bars"] == 70 and result["candidates"][0]["status"] == "NOT_READY"
    ready = match_calendar(np.arange(80,200,dtype=np.int64),score_start_ns=130,end_ns=190,candidates=rows)
    assert ready["status"] == "READY" and ready["scored_bars"] == 60


def test_exact_anchor_boundary_and_registry_revision():
    row = dict(start="2021-01-01",sim_start="2021-01-02",end="2021-01-04",name="not a magic causal state")
    anchor = AnchorManifest.from_historical("D1/R1",row,source_id="sealed-master",pointer="/metadata/regimes/R1",
                                           lifecycle_id="actual-reset-contract")
    reg = EnvironmentRegistry()
    reg.register(anchor)
    with pytest.raises(ValueError,match="unverified"):
        anchor.membership(np.array([anchor.score_start_ns,anchor.end_ns]))
    with pytest.raises(ValueError,match="revision"):
        reg.register(replace(anchor,end_policy="inclusive"))
    revised = replace(anchor,manifest_id="D1/R1/verified-v2",end_policy="inclusive")
    reg.register(revised)
    assert revised.membership(np.array([anchor.score_start_ns,anchor.end_ns])).array().tolist() == [True,True]
    excluded = replace(revised,end_policy="exclusive")
    assert excluded.membership(np.array([anchor.score_start_ns,anchor.end_ns])).array().tolist() == [True,False]


@pytest.mark.parametrize("kind",["late_feature","missing","stale","warmup"])
def test_unpublished_missing_and_stale_feature_cannot_emit_normal_state(kind):
    tape,plan = fixture()
    flags,available = tape.quality.array().copy(),tape.available.array().copy()
    if kind == "late_feature":
        available[35] = 1000
    else:
        flags[35] = {"missing":1,"stale":2,"warmup":3}[kind]
    changed = FeatureTape.from_arrays(tape.provider_id,tape.times.array(),tape.values.array(),available,flags)
    labels = fit_partition(changed,plan.train,plan.fit_policy(),namespace="v1").label(changed,purpose="decision_vintage")
    assert not labels.valid.array()[35] and labels.labels.array()[35] == -1


def test_namespace_provider_and_train_population_changes_invalidate_analysis_identity():
    tape,plan = fixture()
    fit = fit_partition(tape,plan.train,plan.fit_policy(),namespace="n1")
    assert fit.identity != replace(fit,namespace="n2").identity
    changed = FeatureTape.from_arrays("other-provider",tape.times.array(),tape.values.array(),tape.available.array(),tape.quality.array())
    with pytest.raises(ValueError,match="provider"):
        fit.label(changed,purpose="decision_vintage")
    values = tape.values.array().copy()
    values[5] += 100
    training = FeatureTape.from_arrays(tape.provider_id,tape.times.array(),values,tape.available.array(),tape.quality.array())
    assert fit_partition(training,plan.train,plan.fit_policy(),namespace="n1").identity != fit.identity


@pytest.mark.parametrize("clone",[copy.deepcopy,lambda v:pickle.loads(pickle.dumps(v))])
def test_feature_and_label_buffers_remain_immutable_after_transport(clone):
    tape,plan = fixture()
    label = fit_partition(tape,plan.train,plan.fit_policy(),namespace="n").label(tape,purpose="decision_vintage")
    for item in (clone(tape).values,clone(label).labels):
        with pytest.raises(ValueError):
            item.array().setflags(write=True)


@pytest.mark.parametrize("mutation",["overlap","immature","future_selection"])
def test_invalid_inner_outer_plans_fail_closed(mutation):
    _,plan = fixture()
    args = dict(inner_validation=AccessWitness("inner","synthetic",20,41,41)) if mutation == "overlap" else (
        dict(inner_validation=AccessWitness("inner","synthetic",31,41,45)) if mutation == "immature" else
        dict(discovery_cutoff_ns=42))
    with pytest.raises(ValueError,match="chronology"):
        replace(plan,**args)


def test_retrospective_leave_out_cannot_be_claimed_as_chronological():
    _,plan = fixture()
    historical = AccessWitness("past-held","synthetic",1,20,20)
    with pytest.raises(ValueError):
        replace(plan,outer_validation=historical)
    retro = replace(plan,outer_validation=historical,claim="retrospective_transfer")
    assert retro.claim == "retrospective_transfer"


@pytest.mark.parametrize("values",[np.zeros(60),np.r_[np.zeros(30),np.ones(30)]])
def test_constant_train_feature_fails_not_artificial_epsilon_state(values):
    tape,plan = fixture()
    flat = FeatureTape.from_arrays(tape.provider_id,tape.times.array(),values,tape.available.array(),tape.quality.array())
    with pytest.raises(ValueError,match="constant"):
        fit_partition(flat,plan.train,plan.fit_policy(),namespace="flat")


def test_m5t_041_actual_quantbt_future_prices_and_account_prefix_unchanged():
    from tests.mode5.test_admission_ledger import market,order,run
    from quantbt import OrderSide
    frame = market(100.+3*np.sin(np.arange(60)/2))
    values = frame.close.pct_change().rolling(3,min_periods=3).std().to_numpy()
    times = frame.index.asi8
    flags = np.where(np.isfinite(values),0,3).astype(np.int8)
    raw = FeatureTape.from_arrays("synthetic-trailing-volatility-v1",times,values,times,flags)
    train = AccessWitness("train","synthetic",int(times[0]),int(times[30]),int(times[30]))
    policy = AccessPolicy("fit",("synthetic",),("train",),train.ready_ns,"diagnostic")
    fitted = fit_partition(raw,train,policy,namespace="origin30")
    labels = fitted.label(raw,purpose="decision_vintage")
    changed = frame.copy()
    changed.iloc[40:,changed.columns.get_indexer(["open","high","low","close"])] *= 10
    future_values = changed.close.pct_change().rolling(3,min_periods=3).std().to_numpy()
    future = FeatureTape.from_arrays(raw.provider_id,times,future_values,times,flags)
    again = fit_partition(future,train,policy,namespace="origin30")
    assert fitted == again
    assert labels.prefix_identity(int(times[39])) == again.label(future,purpose="decision_vintage").prefix_identity(int(times[39]))
    commands = (order(frame,31,OrderSide.BUY,2.,"entry"),order(frame,50,OrderSide.SELL,2.,"exit",reduce_only=True))
    initial,later = run(frame,commands),run(changed,commands)
    assert len(initial.fills) == len(later.fills) == 2
    np.testing.assert_array_equal(initial.equity.iloc[:40],later.equity.iloc[:40])
    assert initial.equity.iloc[-1] != later.equity.iloc[-1]


def test_unpublished_train_observation_mutation_cannot_change_fitted_identity():
    tape,plan = fixture()
    available = tape.available.array().copy()
    available[10] = 1000
    original = FeatureTape.from_arrays(tape.provider_id,tape.times.array(),tape.values.array(),available,tape.quality.array())
    values = tape.values.array().copy()
    values[10] = -1e9
    changed = FeatureTape.from_arrays(tape.provider_id,tape.times.array(),values,available,tape.quality.array())
    a = fit_partition(original,plan.train,plan.fit_policy(),namespace="asof31")
    b = fit_partition(changed,plan.train,plan.fit_policy(),namespace="asof31")
    assert a.identity == b.identity and a.count == 29
