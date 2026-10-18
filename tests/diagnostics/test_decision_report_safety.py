"""Additional mask, permission, budget and disclosure regression controls."""

from dataclasses import replace
import json

import pytest

from quantbt.diagnostics import (ResearchDecisionReport,ReportCohort,FoldSlot,MetricSupplement)
from quantbt.mode5.dossier.records import Record
from tests.diagnostics.test_decision_reports import fold,inputs,build,private


def test_original_research_math_has_one_canonical_owner():
    from quantbt.diagnostics.decisions import effects
    from tools.meta_model_research import decision_analysis
    for name in ('raw_effect','worst_fraction','opportunity'):
        assert getattr(decision_analysis,name) is getattr(effects,name)


@pytest.mark.parametrize('kind',['empty','duplicate','reverse','unknown','max_folds','max_candidates','bytes','overlap'])
def test_input_budgets_and_roster_contracts_never_drop_rows(kind):
    a,b=fold(),fold(1)
    slots,access=inputs(a,b)
    with pytest.raises(ValueError):
        if kind=='empty':
            ResearchDecisionReport.mode4((),roster=slots,access=access)
        elif kind=='duplicate':
            ResearchDecisionReport.mode4((a,a),roster=slots,access=access)
        elif kind=='reverse':
            ResearchDecisionReport.mode4((a,b),roster=slots[::-1],access=access)
        elif kind=='unknown':
            ResearchDecisionReport.mode4((a,b),roster=slots[:1],access=access)
        elif kind=='max_folds':
            ResearchDecisionReport.mode4((a,b),roster=slots,access=access,max_folds=1)
        elif kind=='max_candidates':
            ResearchDecisionReport.mode4((a,b),roster=slots,access=access,max_candidates=1)
        elif kind=='bytes':
            ResearchDecisionReport.mode4((a,b),roster=slots,access=access,max_report_bytes=1)
        else:
            ResearchDecisionReport.mode4((a,b),roster=(slots[0],replace(slots[1],start_ns=slots[0].start_ns)),access=access)


def test_empty_registered_cohort_is_empty_not_an_all_calendar_fallback():
    report=build(fold(),cohorts=(ReportCohort('empty-evaluation',(),'frozen-protocol'),))
    stats=private(report)['summary']['cohorts']['empty-evaluation']['policies']['applied']
    assert stats['calendar_count']==0
    assert stats['effects']['R']['mean'] is None
    assert stats['q_help_rate'] is None


@pytest.mark.parametrize('kind',['unknown','reserved','duplicate'])
def test_cohort_names_cannot_hide_or_redefine_registered_masks(kind):
    a=fold()
    cohort=ReportCohort('custom',(a.fold_id,),'source')
    cohorts=(replace(cohort,fold_ids=('unknown',)),) if kind=='unknown' else (
        replace(cohort,name='all_calendar'),) if kind=='reserved' else (cohort,cohort)
    with pytest.raises(ValueError):
        build(a,cohorts=cohorts)


def test_overlapping_source_states_are_dependent_views_and_do_not_leak_names():
    a=fold()
    a=replace(a,state_labels=('PRIVATE_BULL_STATE','PRIVATE_LIQUIDITY_STATE'),state_witness=a.witness,state_source_ref='private-state-classifier')
    b=fold(1)
    report=build(a,b)
    summary=private(report)['summary']
    assert summary['state_coverage']['labelled_fold_ids']==[a.fold_id]
    assert len(summary['state_consistency'])==2
    assert all(v['calendar_count']==1 for v in summary['state_consistency'].values())
    public=report.to_json()
    assert 'PRIVATE_BULL_STATE' not in public and 'PRIVATE_LIQUIDITY_STATE' not in public
    assert len(report.to_dict()['summary']['state_consistency'])==2
    assert private(build(b))['summary']['state_coverage']['status']=='NOT_SUPPLIED'


def test_execution_differences_require_original_decision_binding():
    a=fold()
    comparison=Record.of(dict(anchor_evaluation_id=a.revision.task.anchor_candidate_evaluation_id,
        applied_evaluation_id=a.decision.actual_evaluation_id,positions_identical=False,
        source_ref='private-comparison',fill_delta=2))
    report=build(replace(a,execution_comparison=comparison))
    value=private(report)['summary']['execution_differences']
    assert value['observed_fold_ids']==[a.fold_id]
    assert value['status']=='SOURCE_BOUND_NOT_REPLAYED'
    assert private(build(a))['summary']['execution_differences']['status']=='NOT_SUPPLIED'
    assert 'private-comparison' not in report.to_json(detail=True)
    with pytest.raises(ValueError):
        replace(a,execution_comparison=Record.of(dict(anchor_evaluation_id='other',applied_evaluation_id='other')))


def test_no_current_forward_selection_claim_is_admitted():
    a=fold()
    with pytest.raises(ValueError,match='forward inputs'):
        replace(a,decision=replace(a.decision,numeric={'current_forward_inputs':True}))


def test_original_source_witness_cannot_disappear_on_reload():
    data=private(build(fold()))
    data['source_witnesses']=[]
    with pytest.raises(ValueError,match='witness'):
        ResearchDecisionReport.from_json(json.dumps(data))


@pytest.mark.parametrize('view',['public','compact','oversize'])
def test_reload_requires_explicit_bounded_private_detail(view):
    report=build(fold())
    text=report.to_json(private=view!='public',detail=view=='oversize')
    with pytest.raises(ValueError):
        ResearchDecisionReport.from_json(text,max_bytes=1 if view=='oversize' else 16*1024**2)


def test_units_do_not_turn_fill_counts_into_closed_actions_or_percentages():
    a=fold()
    with pytest.raises(ValueError,match='unit'):
        MetricSupplement('candidate','obs','result',Record.of(dict(fill_count=2)),Record.of(dict(fill_count='closed_action_count')))
    with pytest.raises(ValueError,match='fraction'):
        MetricSupplement('candidate','obs','result',Record.of(dict(max_drawdown=25.)),Record.of(dict(max_drawdown='fraction')))


def test_parameter_turnover_is_observed_adjacent_params_not_fill_count():
    a,b=fold(),fold(1)
    report=build(a,b)
    turnover=private(report)['summary']['parameter_turnover']['applied']
    assert turnover['observed_adjacent_transitions']==1
    assert turnover['changed_transitions']==0
    assert private(report)['summary']['cohorts']['all_calendar']['policies']['applied']['supplemental']['fill_count']['statistics']['mean'] is None


def test_fractional_tail_and_no_forward_superiority_gate_on_negative_folds():
    rows=tuple(fold(i,forward=(.5,-i/10)) for i in range(10))
    report=build(*rows)
    stats=private(report)['summary']['cohorts']['all_calendar']['policies']['applied']
    assert stats['harmed']==10 and stats['helped']==0
    assert stats['effects']['Q']['mean_worst_20pct']==pytest.approx((-1.4-1.3)/2)
    assert stats['effects']['selected_decay']['count']==10
    assert stats['positive_forward_sharpe']['defined']==10
    assert stats['positive_forward_sharpe']['positive']==0


def test_extra_report_state_is_not_an_implicit_meta_activation():
    report=build(replace(fold(),decision=None))
    data=private(report)
    assert data['payload']['rows'][0]['activation']=='off'
    assert data['summary']['cohorts']['meta_disabled']['fold_ids']==['private-fold-0']
    assert data['summary']['cohorts']['model_ready']['fold_ids']==[]
    assert data['summary']['acquired_prediction_loss']['origin_macro_y_mse'] is None


def test_registered_mask_order_cannot_be_compressed_or_reordered():
    a,b=fold(),fold(1)
    with pytest.raises(ValueError,match='calendar order'):
        build(a,b,cohorts=(ReportCohort('reverse',(b.fold_id,a.fold_id),'source'),))


def test_prediction_structural_identity_is_checked_not_only_finite_numbers():
    e=fold()
    predictions=tuple(dict(p,qhat=1.234) if p['evaluation_id']==e.decision.proposed_evaluation_id else p for p in e.decision.predictions)
    with pytest.raises(ValueError,match='structural identity'):
        replace(e,decision=replace(e.decision,predictions=predictions))


def test_original_continuous_account_requires_exact_reported_scope():
    from quantbt.diagnostics import RetainedAccountReport
    e=fold(); slots,access=inputs(e)
    account=RetainedAccountReport(e.revision.task.family.family_id,'applied','original-account',e.witness,
        Record.of(dict(final_equity=21000.)),Record.of(dict(final_equity='USD')),
        'original-contract','original-result',slots[0].start_ns,slots[0].stop_ns-1)
    with pytest.raises(ValueError,match='scope'):
        ResearchDecisionReport.mode4((e,),roster=slots,access=access,accounts=(account,))


def test_mode5_first_trial_clock_denies_source_available_before_search(monkeypatch):
    from pathlib import Path
    from quantbt.diagnostics import AccessPolicy,AccessWitness
    from quantbt.mode5 import DecisionReport
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1]/'mode5'))
    from tests.mode5.test_decision_report import runtime_metadata
    metadata,params=runtime_metadata()
    first=metadata.get('chronology',{}).get('first_trial_ns',1000)
    # These synthetic observations use tiny scope times; only the record clock is changed.
    metadata.setdefault('chronology',{})['first_trial_ns']=10**20
    original=DecisionReport.read(metadata,selected_params=params)
    witness=AccessWitness('source','synthetic',0,10**19,10**19)
    policy=AccessPolicy('rights',('synthetic',),('source',),10**19,'diagnostic')
    with pytest.raises(PermissionError,match='predates'):
        ResearchDecisionReport.mode5(original,access=policy,witness=witness,source_ref='record')


def test_no_hidden_calls_even_when_fallbacks_and_active_decisions_are_reported(monkeypatch):
    from quantbt import QuantBTEndpoint
    from quantbt.optimization.meta_selection.model import RidgeLearner
    import optuna
    def denied(*a,**k):
        raise AssertionError('unexpected financial/search/model call')
    monkeypatch.setattr(QuantBTEndpoint,'backtest',denied)
    monkeypatch.setattr(QuantBTEndpoint,'simulate',denied)
    monkeypatch.setattr(RidgeLearner,'fit',denied)
    monkeypatch.setattr(optuna,'create_study',denied)
    report=build(fold(ready=False),fold(1))
    assert 'Research Decision Report' in report.to_markdown()
    assert private(report)['summary']['cohorts']['model_ready']['fold_ids']==['private-fold-1']


def test_state_labels_have_independent_future_and_purpose_denial():
    e=fold(); slots,access=inputs(e)
    labelled=replace(e,state_labels=('private-state',),state_witness=replace(e.witness,ready_ns=e.witness.ready_ns+1),state_source_ref='label-source')
    with pytest.raises(PermissionError):
        ResearchDecisionReport.mode4((labelled,),roster=slots,access=access)
    labelled=replace(labelled,state_witness=e.witness,state_label_purpose='asof_calibration_descriptive')
    with pytest.raises(PermissionError,match='states|partition'):
        ResearchDecisionReport.mode4((labelled,),roster=slots,access=access,view='prefix')
    assert ResearchDecisionReport.mode4((labelled,),roster=slots,access=access).to_dict()['summary']['state_coverage']['status']=='OBSERVED_SOURCE_LABELS'


def metadata_for(*folds):
    return dict(optimization_mode='mode_4_is_only_robust',optimization_schedule='per_fold_causal',
        meta_selection=dict(schema='qms-public-run-v1',config=dict(mode=folds[0].decision.mode),
            current_outer_oos_used_for_selection=False,tasks=tuple(f.revision.task for f in folds),
            observed_revisions=tuple(f.revision for f in folds),records=tuple(dict(
                fold_id=f.fold_id,task_id=f.revision.task.task_id,current_outer_oos_used_for_selection=False,
                native_optimization_mode='mode_4_is_only_robust',proposal=f.decision,
                selected_evaluation_id=f.decision.actual_evaluation_id,
                selected_params=dict(next(c for c in f.revision.task.candidates if c.evaluation_id==f.decision.actual_evaluation_id).effective_params),
                matured_origins=12,training_snapshot_id=f.decision.training_snapshot_id) for f in folds)))


@pytest.mark.parametrize('activation',['active','shadow'])
def test_normal_wfo_metadata_reader_equals_typed_report(activation):
    a,b=fold(activation=activation),fold(1,activation=activation)
    _,access=inputs(a,b)
    metadata=metadata_for(a,b)
    report=ResearchDecisionReport.from_walk_forward(metadata,access=access,source_ref='original-result',role='synthetic')
    expected=build(a,b)
    assert report.to_dict()['summary']==expected.to_dict()['summary']


@pytest.mark.parametrize('change',['mode','schedule','selection','no_labels','params','json_unverified','duplicate_revision'])
def test_metadata_reader_never_invents_missing_evidence_or_expands_support(change):
    a=fold(); _,access=inputs(a)
    metadata=metadata_for(a)
    meta=metadata['meta_selection']
    if change=='mode':
        metadata['optimization_mode']='mode_1_decay'
    elif change=='schedule':
        metadata['optimization_schedule']='global'
    elif change=='selection':
        meta['current_outer_oos_used_for_selection']=True
    elif change=='no_labels':
        meta['observed_revisions']=()
    elif change=='params':
        meta['records'][0]['selected_params']={'secret':0}
    elif change=='json_unverified':
        meta['observed_revisions']=({},)
    else:
        meta['observed_revisions']=(a.revision,a.revision)
    with pytest.raises(ValueError):
        ResearchDecisionReport.from_walk_forward(metadata,access=access,source_ref='result',role='synthetic')


def test_independent_validation_audit_cannot_be_relabelled_prefix_advice():
    from quantbt.diagnostics import AccessPolicy
    e=fold(); slots,access=inputs(e)
    e=replace(e,witness=replace(e.witness,role='independent_validation'))
    validation=AccessPolicy('audit-only',('independent_validation',),access.manifests,access.cutoff_ns,'independent_validation')
    assert ResearchDecisionReport.mode4((e,),roster=slots,access=validation).to_dict()['payload']['decision_use']=='NOT_BACKDATABLE'
    with pytest.raises(PermissionError,match='prefix advice'):
        ResearchDecisionReport.mode4((e,),roster=slots,access=validation,view='prefix')
