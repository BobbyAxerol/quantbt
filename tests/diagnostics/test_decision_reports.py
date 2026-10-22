"""M45R-01/02/03/04/07/08: synthetic original records, no fits or finance."""

from copy import deepcopy
from dataclasses import replace
import json
import pickle
import random

import numpy as np
import pytest

from quantbt.diagnostics import (AccessPolicy,AccessWitness,FoldDecisionEvidence,FoldSlot,
    MetricSupplement,ReportCohort,ResearchDecisionReport,RetainedAccountReport,RetainedInterval)
from quantbt.mode5.dossier.records import Record
from quantbt.optimization.meta_selection.common import digest
from quantbt.optimization.meta_selection.records import OutcomeStatus
from quantbt.optimization.meta_selection.selection import MetaSelectionDecision
from tests.meta_selection.test_qms03_history import make_task,revision_for


def fold(number=0,*,activation='active',ready=True,is_values=(2.,1.),forward=(.5,.3),same=False):
    task,schema=make_task(n=2,year=2020+number)
    candidates=tuple(replace(c,observation=replace(c.observation,raw_sharpe=is_values[i]))
        for i,c in enumerate(task.candidates))
    if same:
        candidates=(candidates[0],replace(candidates[1],effective_params=dict(candidates[0].effective_params)))
    task=replace(task,candidates=candidates)
    revision=revision_for(task,schema)
    revision=replace(revision,outcomes=tuple(replace(o,observation=replace(o.observation,raw_sharpe=forward[i]))
        for i,o in enumerate(revision.outcomes)))
    anchor,winner=candidates[0],candidates[1] if ready else candidates[0]
    predictions=tuple(dict(evaluation_id=c.evaluation_id,candidate_id=c.candidate_id,
        raw_is=c.observation.raw_sharpe,yhat=0. if i==0 else -1.,
        qhat=0. if i==0 else c.observation.raw_sharpe-anchor.observation.raw_sharpe+1.,
        distance=float(i),eligible=True,exclusion=None) for i,c in enumerate(candidates)) if ready else ()
    decision=MetaSelectionDecision(task.task_id,anchor.evaluation_id,winner.evaluation_id,
        anchor.evaluation_id if activation=='shadow' else winner.evaluation_id if activation=='active' else None,
        dict(winner.effective_params),anchor.evaluation_id,'synthetic-model' if ready else None,
        'synthetic-history' if ready else None,task.data_cutoff,task.search_completed_at if ready else None,
        task.decision_sealed_at,task.decision_sealed_at,task.clock_mode,activation,
        'META_MODEL_PROPOSAL' if ready else 'META_SUPPORT_INSUFFICIENT',predictions,
        (winner.evaluation_id,) if ready else (),(),dict(epsilon=.1,tie_tolerance=1e-10),{})
    witness=AccessWitness(task.corpus_id,'synthetic',int(task.is_start.value),int(task.forward_end.value)+1,
        int(revision.revision_available_at.value))
    return FoldDecisionEvidence(f'private-fold-{number}',revision,decision,witness,'private-source-'+str(number),
        model_support=Record.of(dict(original_mature_origins=12,source_ref='synthetic-saved-artifact-not-a-fit')))


def inputs(*folds):
    slots=tuple(FoldSlot(f.fold_id,int(f.revision.task.forward_start.value),int(f.revision.task.forward_end.value)+1) for f in folds)
    access=AccessPolicy('reviewed-report',('synthetic',),('approved',),max(f.witness.ready_ns for f in folds),'diagnostic')
    return slots,access


def build(*folds,**kwargs):
    roster,access=inputs(*folds)
    return ResearchDecisionReport.mode4(folds,roster=roster,access=access,**kwargs)


def private(report):
    return report.to_dict(private=True,detail=True)


def test_hand_computable_r_q_and_positive_decay_negative_forward():
    report=build(fold())
    data=private(report)
    row=data['payload']['rows'][0]['policies']['applied']
    assert row['effect']['R']==pytest.approx(.8)
    assert row['effect']['Q']==pytest.approx(-.2)
    assert row['effect']['IS_contribution']==1.
    value=data['summary']['cohorts']['all_calendar']['policies']['applied']
    assert value['helped']==0 and value['harmed']==1 and value['r_improvement_rate']==1
    assert value['effects']['Q']['mean']==pytest.approx(-.2)
    assert value['guard']['accepted_negative_q']==1
    assert value['guard']['accepted_below_original_floor']==1
    assert value['prediction']['q_mse']==pytest.approx(.04)
    assert value['prediction']['y_mse']==pytest.approx(.04)
    assert 'Positive R does not imply positive Q' in report.to_markdown()


@pytest.mark.parametrize('activation',['active','shadow','proposal'])
def test_proposed_and_applied_states_are_not_conflated(activation):
    data=private(build(fold(activation=activation)))
    policies=data['payload']['rows'][0]['policies']
    assert policies['proposed']['same_id'] is False
    assert policies['applied']['same_id'] is (activation=='shadow') if activation!='proposal' else policies['applied']['same_id'] is None
    if activation=='shadow':
        assert policies['applied']['effect']['R']==policies['applied']['effect']['Q']==0
        assert policies['proposed']['effect']['Q']<0
    if activation=='proposal':
        assert policies['applied']['effect'] is None


def test_fallback_off_and_missing_fold_remain_in_declared_calendar():
    a,b,c=fold(0,ready=False),fold(1),fold(2)
    c=replace(c,decision=None)
    slots,access=inputs(a,b,c)
    report=ResearchDecisionReport.mode4((a,c),roster=slots,access=access)
    data=private(report)
    assert len(data['payload']['rows'])==3
    assert data['payload']['rows'][1]['status']=='MISSING_FOLD_RECORD'
    cohorts=data['summary']['cohorts']
    assert cohorts['fallback']['fold_ids']==[a.fold_id]
    assert cohorts['meta_disabled']['fold_ids']==[c.fold_id]
    assert cohorts['model_ready']['fold_ids']==[]
    assert cohorts['all_calendar']['policies']['applied']['effects']['Q']['count']==2
    assert data['summary']['parameter_turnover']['applied']['observed_adjacent_transitions']==0
    assert data['summary']['parameter_turnover']['applied']['missing_adjacent_transitions']==2


def test_same_effective_with_distinct_ids_still_retains_observed_effect():
    report=build(fold(same=True))
    value=private(report)['summary']['cohorts']['all_calendar']['policies']['applied']
    assert value['changed_ids']==1 and value['changed_effective']==0
    assert value['effects']['Q']['mean']==pytest.approx(-.2)
    assert value['harmed']==1  # never fabricate zero just from params equality


def test_explicit_cohort_masks_include_unchanged_fallbacks_and_exclude_only_as_declared():
    a,b=fold(0,ready=False),fold(1)
    cohort=ReportCohort('reserved-evaluation',(a.fold_id,b.fold_id),'original-registration')
    report=build(a,b,cohorts=(cohort,))
    stats=private(report)['summary']['cohorts']
    assert stats['all_calendar']['policies']['applied']['effects']['Q']['count']==2
    assert stats['all_calendar']['policies']['applied']['effects']['Q']['mean']==pytest.approx(-.1)
    assert stats['applied_changed']['policies']['applied']['effects']['Q']['count']==1
    assert stats['reserved-evaluation']['fold_ids']==[a.fold_id,b.fold_id]


def test_positive_return_is_not_positive_sharpe_and_zero_not_missing():
    evidence=fold()
    winner=evidence.decision.actual_evaluation_id
    observation=next(o.observation for o in evidence.revision.outcomes if o.evaluation_id==winner)
    metric=MetricSupplement(winner,digest(observation),'original-MET-result',
        Record.of(dict(net_return=-.1,max_drawdown=.25,exposure_fraction=0.,fill_count=0)),
        Record.of(dict(net_return='fraction',max_drawdown='fraction',exposure_fraction='fraction',fill_count='executed_fill_count')))
    evidence=replace(evidence,metrics=(metric,))
    report=build(evidence)
    value=private(report)['summary']['cohorts']['all_calendar']['policies']['applied']
    assert value['positive_forward_sharpe']['positive']==1
    assert value['positive_forward_return']['positive']==0
    assert value['positive_forward_return']['defined']==1
    assert value['supplemental']['exposure_fraction']['statistics']['mean']==0.
    assert value['supplemental']['fees']['statistics']['mean'] is None
    assert value['supplemental']['fill_count']['statistics']['mean']==0
    assert value['supplemental']['closed_action_count']['statistics']['mean'] is None


def test_no_variance_flat_retains_zero_return_but_not_zero_sharpe():
    evidence=fold()
    winner=evidence.decision.actual_evaluation_id
    outcomes=tuple(replace(o,observation=replace(o.observation,status=OutcomeStatus.NO_VARIANCE,
        raw_sharpe=0.,sample_std=0.,sample_count=30)) if o.evaluation_id==winner else o for o in evidence.revision.outcomes)
    revision=replace(evidence.revision,outcomes=outcomes)
    metric=MetricSupplement(winner,digest(outcomes[1].observation),'actual-flat-account',Record.of(dict(net_return=0.)),Record.of(dict(net_return='fraction')))
    report=build(replace(evidence,revision=revision,metrics=(metric,)))
    value=private(report)['summary']['cohorts']['all_calendar']['policies']['applied']
    assert value['effects']['R']['count']==value['effects']['Q']['count']==0
    assert value['positive_forward_return']['defined']==1
    assert value['positive_forward_return']['positive']==0
    assert value['positive_forward_sharpe']['defined']==0
    assert value['helped']==value['harmed']==value['tied']==0


def test_partial_operands_keep_q_own_mask_and_matched_decomposition_separate():
    evidence=fold(ready=False)
    task=evidence.revision.task
    anchor=replace(task.anchor,observation=replace(task.anchor.observation,status=OutcomeStatus.NO_VARIANCE,
        raw_sharpe=0.,sample_count=0,sample_std=0.))
    task=replace(task,candidates=(anchor,task.candidates[1]))
    from quantbt.optimization.meta_selection.panel import freeze_panel
    from tests.meta_selection.test_qms03_history import make_task
    _,schema=make_task(n=2)
    panel=freeze_panel(task,schema,sealed_at=task.decision_sealed_at)
    revision=replace(evidence.revision,task=task,panel=panel,outcomes=tuple(replace(o,task_id=task.task_id) for o in evidence.revision.outcomes))
    decision=replace(evidence.decision,task_id=task.task_id)
    report=build(replace(evidence,revision=revision,decision=decision))
    value=private(report)['summary']['cohorts']['all_calendar']['policies']['applied']
    assert value['effects']['R']['count']==0
    assert value['effects']['Q']['count']==1 and value['effects']['Q']['mean']==0
    assert value['matched_decomposition']['fold_ids']==[]


def test_fractional_tail_threshold_and_descriptive_units():
    from quantbt.diagnostics.decisions.reduction import describe
    from quantbt.diagnostics.decisions.effects import worst_fraction
    assert describe([-5.,-1.,0.])['mean_worst_20pct'] is None
    assert describe(list(range(10)))['mean_worst_20pct']==.5
    assert worst_fraction([0.,1.,2.],.5)==pytest.approx(1/3)
    assert describe([1.])['sample_std'] is None
    assert describe([])['mean'] is None


def test_masks_not_unmatched_means_for_paired_contrasts():
    a,b=fold(),fold(1)
    report=build(a,b)
    data=private(report)
    comparison=data['summary']['cohorts']['all_calendar']['comparisons']['applied_vs_native']
    assert comparison['paired_fold_ids']==[a.fold_id,b.fold_id]
    assert comparison['differences']['Q']['mean']==pytest.approx(-.2)
    assert comparison['matched_levels']['native']['Q']['mean']==0


def test_intervals_require_original_registration_exact_mask_and_point_no_rng():
    evidence=fold(); slots,access=inputs(evidence)
    interval=RetainedInterval('all_calendar','applied_vs_native','Q',(evidence.fold_id,),
        'original-interval-receipt','original-block-bootstrap-registration',evidence.witness,
        'DEFINED_EXPLORATORY',-.2,-.5,.3)
    report=ResearchDecisionReport.mode4((evidence,),roster=slots,access=access,intervals=(interval,))
    assert private(report)['summary']['uncertainty']['coordinates'][0]['lower']==-.5
    with pytest.raises(ValueError,match='mask'):
        ResearchDecisionReport.mode4((evidence,),roster=slots,access=access,intervals=(replace(interval,fold_ids=('another',)),))
    with pytest.raises(ValueError,match='point'):
        ResearchDecisionReport.mode4((evidence,),roster=slots,access=access,intervals=(replace(interval,estimate=.9),))
    assert private(build(evidence))['summary']['uncertainty']['status']=='NOT_SUPPLIED'


def test_future_revision_denied_and_earlier_prefix_unchanged_by_later_mutation():
    a,b=fold(),fold(1)
    slots,access=inputs(a)
    before=ResearchDecisionReport.mode4((a,),roster=slots,access=access,view='prefix')
    mutated=fold(1,forward=(100.,-100.))
    assert build(a).to_dict()['summary']==before.to_dict()['summary']
    assert ResearchDecisionReport.mode4((a,),roster=slots,access=access,view='prefix').identity==before.identity
    future_slots,_=inputs(a,b)
    with pytest.raises(PermissionError,match='future|immature'):
        ResearchDecisionReport.mode4((a,mutated),roster=future_slots,access=access,view='prefix')


@pytest.mark.parametrize('change',['window','economics','candidate','cutoff','params','supplement'])
def test_source_contract_mismatch_fails_closed(change):
    e=fold()
    with pytest.raises(ValueError):
        if change=='window':
            slots,access=inputs(e)
            ResearchDecisionReport.mode4((e,),roster=(replace(slots[0],stop_ns=slots[0].stop_ns+1),),access=access)
        elif change=='economics':
            changed=fold(1)
            task=replace(changed.revision.task,family=replace(changed.revision.task.family,economics_id='wrong'))
            replace(changed.revision,task=task)
        elif change=='candidate':
            replace(e,decision=replace(e.decision,raw_best_evaluation_id='not-in-pool'))
        elif change=='cutoff':
            replace(e,decision=replace(e.decision,information_as_of=e.revision.task.search_completed_at))
        elif change=='params':
            replace(e,decision=replace(e.decision,proposed_params={'SECRET':1}))
        else:
            replace(e,metrics=(MetricSupplement(e.decision.actual_evaluation_id,'wrong','source',Record.of(dict(net_return=.1)),Record.of(dict(net_return='fraction'))),))


@pytest.mark.parametrize('kind',['summary','effect','params','observation','application'])
def test_reload_rejects_internal_tampering(kind):
    data=private(build(fold()))
    policy=data['payload']['rows'][0]['policies']['applied']
    if kind=='summary':
        data['summary']['cohorts']['all_calendar']['policies']['applied']['helped']=100
    elif kind=='effect':
        policy['effect']['R']=100
    elif kind=='params':
        policy['params']['hma_length']=999
    elif kind=='observation':
        policy['observations']['selected_forward']['raw_sharpe']=999
    else:
        data['payload']['rows'][0]['activation']='shadow'
    with pytest.raises(ValueError):
        ResearchDecisionReport.from_json(json.dumps(data))


def test_immutable_roundtrip_private_opt_in_access_and_global_rng():
    e=fold(); slots,access=inputs(e)
    py,np_before=random.getstate(),np.random.get_state()
    report=build(e)
    for other in (deepcopy(report),pickle.loads(pickle.dumps(report)),
                  ResearchDecisionReport.from_json(report.to_json(private=True,detail=True))):
        assert other.identity==report.identity
        assert other.to_markdown(private=True,detail=True)==report.to_markdown(private=True,detail=True)
        other.authorize(access)
    value=report.to_dict(private=True,detail=True)
    value['summary']['cohorts'].clear()
    assert report.to_dict(private=True)['summary']['cohorts']
    with pytest.raises(PermissionError):
        report.authorize(replace(access,cutoff_ns=access.cutoff_ns-1))
    public=report.to_json(detail=True)
    for secret in ('private-fold','private-source','hma_length','synthetic-model','is-output','approved','candidate-'):
        assert secret not in public
    assert report.to_dict()['summary']['cohorts']['all_calendar']['policies']['applied']['effects']['Q']['mean']==pytest.approx(-.2)
    assert random.getstate()==py
    after=np.random.get_state()
    np.testing.assert_array_equal(np_before[1],after[1]); assert np_before[2:]==after[2:]


def test_account_scope_never_reconstructs_diagnostic_equity():
    e=fold(); slots,access=inputs(e)
    account=RetainedAccountReport(e.revision.task.family.family_id,'applied','original-continuous',e.witness,
        Record.of(dict(final_equity=19000.,sharpe=-.2)),Record.of(dict(final_equity='USD',sharpe='ratio')),
        'original-MET-contract','original-continuous-result',slots[0].start_ns,slots[0].stop_ns)
    report=ResearchDecisionReport.mode4((e,),roster=slots,access=access,accounts=(account,))
    value=private(report)['summary']['continuous_accounts'][0]
    assert value['metrics']['final_equity']==19000
    assert value['metrics']['sharpe']==-.2
    assert private(build(e))['summary']['continuous_accounts'][0]['status']=='NOT_SUPPLIED'
    with pytest.raises(ValueError):
        replace(account,account_policy='stitched_reset_diagnostic_equity')
    with pytest.raises(ValueError):
        ResearchDecisionReport.mode4((e,),roster=slots,access=access,accounts=(replace(account,family_id='other'),))


@pytest.mark.parametrize('continuous,no_selection',[(False,False),(True,False),(False,True)])
def test_mode5_original_reader_keeps_fixed_dict_reset_or_continuous_semantics(continuous,no_selection,monkeypatch):
    from pathlib import Path
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1]/'mode5'))
    from tests.mode5.test_decision_report import runtime_metadata
    from quantbt.mode5 import DecisionReport
    metadata,params=runtime_metadata(continuous=continuous,no_selection=no_selection)
    original=DecisionReport.read(metadata,selected_params=params)
    witness=AccessWitness('mode5-source','synthetic',0,10**19,10**19)
    access=AccessPolicy('mode5-rights',('synthetic',),('mode5-source',),10**19,'diagnostic')
    report=ResearchDecisionReport.mode5(original,access=access,witness=witness,source_ref='private-mode5-source')
    assert private(report)['payload']['decision_use']=='NOT_BACKDATABLE'
    assert private(report)['summary']['selected_params']==params
    assert report.to_dict()['summary']['mode5_report']==original.to_dict()
    assert ResearchDecisionReport.from_json(report.to_json(private=True,detail=True)).identity==report.identity
    assert 'private-mode5-source' not in report.to_json()
