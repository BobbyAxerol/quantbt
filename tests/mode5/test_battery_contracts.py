from dataclasses import replace
import copy
import json
import pickle

import pytest

from tests.mode5.selection_fixtures import panel,plan
from tools.mode5_batteries import ComparisonScope,HypothesisLedger,SupportPolicy,compare_selectors,fixed_panel_leave_out,same_front
from tools.mode5_diagnostics.access import AccessWitness
from tools.mode5_batteries.sampler_audit import audit_sampler,matched_sampler_work
from tools.mode5_diagnostics.identity import canonical


def scope(p):
    return ComparisonScope("synthetic-battery","v1","selector_only",tuple(c.candidate_id for c in p.candidates),
        p.reference.environment_ids,"daily-common-calendar","net-economic-utility","synthetic-fees-clock-v1",p.access)


def test_m5t_071_same_panel_different_actual_selectors_not_sampler_gain():
    p=panel(((.4,.0),(.15,.15),(-.2,.7)))
    out=compare_selectors(scope(p),p,[(plan(p),{}),(plan(p,"finite_panel_minimax_regret_v1",()),{})])
    assert len(out["decisions"])==2 and not out["sampler_advantage_claim"]
    assert all(len(d["component_rows"])==3 for d in out["decisions"])
    assert out["decisions"][0]["chosen_candidate"]=="c1"
    assert len(fixed_panel_leave_out(p,plan(p)))==2
    assert all(not x["refit_sampler"] for x in fixed_panel_leave_out(p,plan(p)))


@pytest.mark.parametrize("change",[dict(level="sampler_only"),dict(candidate_ids=("c0",)),dict(environment_ids=("wrong",))])
def test_m5t_071_incomparable_panels_fail_closed(change):
    p=panel()
    with pytest.raises(ValueError):
        compare_selectors(replace(scope(p),**change),p,[(plan(p),{})])


def test_m5t_073_shared_front_is_not_compromise_advantage():
    out=same_front(((.1,.8),(.5,.5),(.8,.1),(.0,.0)),("a","b","c","d"),("a","b"),directions=(1,1))
    assert out["front_ids"]==("a","b","c") and out["hypervolume_value"] is None
    assert not out["hypervolume_discriminates_selectors"]


def test_m5t_076_alpha_label_does_not_enter_math_or_recommendation():
    p=panel(((.05,.07),(.10,.02)))
    before=compare_selectors(scope(p),p,[(plan(p),{})])
    for label in ("momentum","mean-reversion","HMA","anything"):
        renamed=replace(p,context_id=label)
        after=compare_selectors(scope(renamed),renamed,[(plan(renamed),{})])
        assert after["decisions"][0]["chosen_params_digest"]==before["decisions"][0]["chosen_params_digest"]
        assert [r["score"] for r in after["decisions"][0]["component_rows"]]==[r["score"] for r in before["decisions"][0]["component_rows"]]


def test_m5t_078_changed_cohort_or_target_is_incomparable():
    s=scope(panel())
    for cohort,target in (("different",s.target_id),(s.cohort_id,"different")):
        out=s.compare_cohort(cohort_id=cohort,target_id=target)
        assert out["status"]=="INCOMPARABLE" and not out["decision_value_claim"]
    assert s.compare_cohort(cohort_id=s.cohort_id,target_id=s.target_id)["status"]=="COMPARABLE"


def test_m5t_079_new_recipe_requires_new_registered_hypothesis_and_reviewed_role():
    s=scope(panel()); w=AccessWitness("synthetic-panel","synthetic",0,5,5)
    old=HypothesisLedger(s).register("EH-01",("a","b"),w)
    seen=old.observe("EH-01",outcome="INCONCLUSIVE",evidence_refs=("receipt-1",))
    with pytest.raises(ValueError,match="revision"):
        seen.register("EH-01",("a","c"),w)
    with pytest.raises(ValueError):
        HypothesisLedger(s).observe("EH-01",outcome="POSITIVE_WITHIN_SCOPE",evidence_refs=("receipt",))
    assert len(old.entries)==1 and len(seen.entries)==2
    reviewed=AccessWitness("synthetic-panel","diagnostic_development",0,5,5)
    new_access=replace(s.access,roles=("diagnostic_development",))
    child=seen.revise(replace(s,revision="v2",access=new_access),hypothesis_id="EH-01-r2",recipes=("a","c"),
        witness=reviewed,parent_reason="post-review proposal; no clean validation reuse")
    assert child["parent_entries"]==seen.entries and child["contamination"]=="REVIEWED_DEVELOPMENT"


@pytest.mark.parametrize("clone",[copy.deepcopy,lambda x:pickle.loads(pickle.dumps(x))])
def test_battery_contracts_and_history_remain_immutable_across_copy(clone):
    s=scope(panel()); old=HypothesisLedger(s).register("EH-01",("a",),AccessWitness("synthetic-panel","synthetic",0,5,5))
    assert clone(old)==old
    row=json.loads(old.entries[0]); row["recipes"]=["changed"]
    assert json.loads(old.entries[0])["recipes"]==["a"]


def test_m5t_080_short_one_seed_slice_cannot_become_universal_evidence():
    policy=SupportPolicy(180,4,2,50,100)
    result=policy.check(days=43,origins=1,seeds=1,campaigns=3,fills=6)
    assert result["status"]=="INSUFFICIENT_EVIDENCE" and len(result["missing_or_insufficient"])==5
    assert not result["universal_superiority"]
    assert policy.check(days=365,origins=4,seeds=2,campaigns=None,fills=None)["status"]=="INSUFFICIENT_EVIDENCE"


def audit(recipe,*,duplicate=False):
    rows=[dict(trial_id=i,status="COMPLETE",effective_digest="same" if duplicate else str(i),evidence_ref="actual-r"+str(i),
        actual_execution_calls=1,visited_bars=100,objective=.1) for i in range(4)]
    return audit_sampler(rows,recipe=recipe,seed=731,proposal_budget=4,observed_relative={0:[],1:["x"]},
        observed_independent={"x":1},objective_id="fixed-v1",economic_contract="fixed-account-v1")


def test_m5t_072_all_trials_fallback_and_actual_work_bill():
    a=audit("sobol"); b=audit("cmaes",duplicate=True)
    out=matched_sampler_work((a,b))
    assert not out["unique_work_matched"] and out["financial_work_matched"]
    assert a["actual_relative_trials"]==1 and b["duplicate_completed"]==3
    assert not a["same_integer_seed_aligns_sequences"] and len(a["all_trials"])==4


def test_sampler_audit_never_turns_failure_into_bad_economic_score():
    rows=[dict(trial_id=0,status="FAIL",effective_digest="p",evidence_ref="failure",actual_execution_calls=1,
               visited_bars=100,objective=-1e9)]
    with pytest.raises(ValueError,match="adverse"):
        audit_sampler(rows,recipe="tpe",seed=1,proposal_budget=1,observed_relative={},observed_independent={},
                      objective_id="v1",economic_contract="v1")


def test_forged_persisted_hypothesis_outcome_without_registration_rejected():
    s=scope(panel())
    row=dict(scope=s.identity,hypothesis_id="EH-01",state="OBSERVED",outcome="POSITIVE_WITHIN_SCOPE",evidence_refs=["receipt"])
    with pytest.raises(ValueError,match="chronology"):
        HypothesisLedger(s,(canonical(row),))


@pytest.mark.parametrize("objective",[None,float("nan"),float("inf"),True])
def test_complete_sampler_observation_cannot_hide_unknown_scalar(objective):
    row=dict(trial_id=0,status="COMPLETE",effective_digest="p",evidence_ref="r",actual_execution_calls=0,visited_bars=0,objective=objective)
    with pytest.raises(ValueError,match="finite scalar"):
        audit_sampler([row],recipe="tpe",seed=1,proposal_budget=1,observed_relative={},observed_independent={},
                      objective_id="v1",economic_contract="v1")


def test_future_witness_cannot_enter_registered_hypothesis_even_with_matching_panel_hash():
    s=scope(panel())
    with pytest.raises(PermissionError):
        HypothesisLedger(s).register("EH-01",("r1",),AccessWitness("synthetic-panel","synthetic",0,5,20))
