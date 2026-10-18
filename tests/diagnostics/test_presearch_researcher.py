"""M45R-01/03/04/05/06/08: source-qualified pre-search decision support."""

from copy import deepcopy
from dataclasses import asdict, replace
import json
import pickle
import random

import numpy as np
import pytest

from quantbt.diagnostics import (AccessPolicy, AccessWitness, AlphaDiagnostics,
    AlphaDiagnosticReport, DiagnosticAccount, DiagnosticAdvice, DiagnosticAnalysis,
    DiagnosticBudget, DiagnosticResearch, DiagnosticTrial, ExecutionEvidence)
from quantbt.diagnostics.evidence import FrozenBuffer
from quantbt.diagnostics.identity import digest
from quantbt.mode5.artifacts import file_identity
from quantbt.mode5.dossier.evidence import EvidenceCatalog, Source
from quantbt.mode5.dossier.records import Record
from tests.diagnostics.test_shared_alpha import context, observations, RANGES

DAY=86_400_000_000_000


def sample(*,sampler='tpe_legacy',equity=(100.,110.,105.,100.),positions=None,labels=True,view='prefix'):
    ctx=context(generation_method=sampler,outcome_blind_roster=False)
    witness=AccessWitness('tape-v1','development',0,4*DAY,4*DAY+1)
    policy=AccessPolicy('prefix',('development',),('tape-v1',),4*DAY+1,'diagnostic')
    owner=AlphaDiagnostics(RANGES,context=ctx,access=policy)
    rows=[replace(r,witness=witness) for r in observations(ctx,owner.geometry)]
    trials=tuple(DiagnosticTrial(str(i),i,'COMPLETE',r.evaluation_id,elapsed_seconds=.1) for i,r in enumerate(rows))
    arrays=dict(timestamps=np.arange(4,dtype=np.int64)*DAY,equity=np.asarray(equity),
        positions=np.asarray(positions if positions is not None else [1.,1.,-1.,0.]),fees=np.array([0.,.1,.1,.1]))
    evidence=ExecutionEvidence.from_arrays('actual-output',witness,arrays,source_ref='synthetic-original-account',backend='retained')
    account=DiagnosticAccount(rows[0].evaluation_id,digest(asdict(rows[0])),evidence,100.,'USD',
        labels=FrozenBuffer.from_array('labels',np.array([0,0,1,1],dtype=np.int64)) if labels else None,
        label_witness=witness if labels else None,label_source_ref='source-labels' if labels else None,
        label_names=((0,'bull'),(1,'bear')) if labels else ())
    research=DiagnosticResearch(ctx.identity,witness,'registered-ledger',view,trials,128,(account,))
    return owner,rows,research


def data(owner,rows,research,**kw):
    return owner.analyze(rows,research=research,**kw).to_dict()['researcher_diagnostics']


def source_catalog(tmp_path,owner,payload,*,ready=None):
    path=tmp_path/'source.json'
    path.write_text(json.dumps(payload))
    ident=file_identity(path)
    witness=AccessWitness('tape-v1','development',0,4*DAY,ready or 4*DAY+1)
    policy=replace(owner.access,cutoff_ns=max(witness.ready_ns,owner.access.cutoff_ns))
    source=Source('source-v1',str(path),ident['sha256'],ident['bytes'],witness)
    return EvidenceCatalog((source,),policy),path


def test_opt_in_keeps_legacy_default_payload_and_identity():
    owner,rows,research=sample()
    current=owner.analyze(rows)
    # Golden synthetic record from the pre-phase owner, not private evidence.
    assert current.identity=='e1be201faa0988433989d6792d993ecf98aab18dd6df61a168aebece8b5d3b27'
    assert 'researcher_diagnostics' not in current.to_dict()
    assert owner.analyze(rows,research=research).identity!=current.identity


@pytest.mark.parametrize('sampler',['tpe_legacy','tpe_multivariate_group','cmaes','sobol'])
def test_bull_concentration_is_not_attributed_to_sampler(sampler):
    owner,rows,research=sample(sampler=sampler)
    out=data(owner,rows,research)
    account=out['accounts'][0]
    assert account['net_pnl']==0 and account['positive_day_pnl']==10 and account['negative_day_loss']==10
    bull,bear=account['groups']
    assert bull['money_pnl']==10 and bear['money_pnl']==-10
    assert bull['positive_day_mass_share']==1. and bear['negative_day_mass_share']==1.
    assert bull['absolute_daily_pnl_share']==bear['absolute_daily_pnl_share']==.5
    assert account['signed_net_denominator_used'] is False
    assert 'any sampler' in str(out['findings'])
    assert all(c['applies_configuration'] is False for c in out['recipe_options'])


@pytest.mark.parametrize('equity',[(100.,101.,98.,95.),(100.,100.,100.,100.),(100.,90.,-1.,-2.)])
def test_negative_flat_and_bankrupt_paths_keep_named_denominators_and_nulls(equity):
    owner,rows,research=sample(equity=equity)
    result=data(owner,rows,research)['accounts'][0]
    assert result['net_pnl']==equity[-1]-100.
    assert result['attribution']['summed_group_pnl']==result['net_pnl']
    assert result['observed_days']==4
    if equity[-1]<0:
        assert result['undefined_return_days']==1
        assert result['zero_valid_return_days']==1
        assert result['attribution']['return_status']=='BANKRUPT_OR_NONPOSITIVE_BASE'
    if result['absolute_daily_pnl']==0:
        assert result['concentration_status']=='UNDEFINED_ZERO_ABSOLUTE_PNL'
        assert all(g['absolute_daily_pnl_share'] is None for g in result['groups'])


def test_sparse_specialist_and_cross_state_position_do_not_add_an_activity_gate():
    owner,rows,research=sample(positions=[0.,1.,1.,0.])
    out=data(owner,rows,research)
    account=out['accounts'][0]
    assert account['exposed_days']==2 and account['exposed_bars']==2
    assert account['groups'][0]['exposed_bars']==1 and account['groups'][1]['exposed_bars']==1
    assert account['groups'][1]['money_pnl']==-10  # no close/reopen at the boundary
    assert account['opportunities']['status']=='NOT_SUPPLIED'
    assert account['campaigns']['status']=='NOT_SUPPLIED'
    assert all('reject_sparse' not in f for f in out['findings'])
    assert out['search']['attempts']['declared_budget']==128


def test_multi_symbol_sides_are_named_nonexclusive_close_mark_counts():
    owner,rows,research=sample(positions=[[1.,-1.],[1.,0.],[0.,-1.],[0.,0.]])
    out=data(owner,rows,research)['accounts'][0]
    assert out['long_close_mark_bars']==out['short_close_mark_bars']==2
    assert out['exposed_bars']==3


def test_dispositions_duplicates_and_time_cost_have_distinct_units():
    owner,rows,research=sample()
    rows.append(replace(rows[0],evaluation_id='duplicate-point'))
    trials=research.trials+(DiagnosticTrial('pruned',12,'PRUNED',reason='DUPLICATE_EFFECTIVE_PARAMS'),
        DiagnosticTrial('failure',13,'FAILED',reason='RUNTIME_FAILED'),
        DiagnosticTrial('duplicate',14,'COMPLETE','duplicate-point'))
    out=data(owner,rows,replace(research,trials=trials))
    search=out['search']
    assert search['attempts']['attempted']==15 and search['unique_effective_points']==12
    assert search['duplicate_effective_observations']==1
    assert search['attempts']['status_counts']==dict(COMPLETE=13,FAILED=1,PRUNED=1)
    assert search['attempts']['measured_time_attempts']==12
    assert search['attempts']['missing_time_attempts']==3
    assert search['attempt_curve'][-1]['attempt']==15
    assert search['effective_dimension']['value'] is None
    assert search['axes'][0]['low_boundary_points']==1
    assert search['axes'][0]['high_boundary_points']==1


def test_missing_ledger_account_factor_probe_and_regime_are_not_neutral():
    owner,rows,research=sample()
    out=data(owner,rows,replace(research,trials=(),accounts=()))
    assert out['search']['attempts']['attempted'] is None
    assert out['accounts']==[]
    findings={x['finding_id']:x for x in out['findings']}
    for key in ('sharpness','factors','regime','sampler_response','account_participation_concentration'):
        assert findings[key]['status']=='NOT_SUPPLIED' and findings[key]['value'] is None
        assert findings[key]['missing_evidence']
    assert out['matrices']['center_neighbor_environment']['status']=='NOT_SUPPLIED'


@pytest.mark.parametrize('field',['market','label','root'])
def test_future_witness_denied_before_reduction(field,monkeypatch):
    owner,rows,research=sample()
    account=research.accounts[0]
    future=replace(research.witness,ready_ns=research.witness.ready_ns+1)
    if field=='root':
        research=replace(research,witness=future)
    elif field=='label':
        research=replace(research,accounts=(replace(account,label_witness=future),))
    else:
        research=replace(research,accounts=(replace(account,evidence=replace(account.evidence,witness=future)),))
    monkeypatch.setattr(owner,'_associations',lambda *args:pytest.fail('consumed forbidden input'))
    with pytest.raises(PermissionError):
        owner.analyze(rows,research=research)


def test_descriptive_state_fit_and_full_dossier_cannot_backdate_prefix(tmp_path):
    owner,rows,research=sample()
    account=replace(research.accounts[0],label_purpose='asof_calibration_descriptive')
    with pytest.raises(PermissionError):
        owner.analyze(rows,research=replace(research,accounts=(account,)))
    result=data(owner,rows,replace(research,view='full_development',accounts=(account,)))
    assert result['decision_use']=='NOT_BACKDATABLE'
    catalog,_=source_catalog(tmp_path,owner,dict(context_id=owner.context.identity,view='full_development'))
    with pytest.raises(PermissionError):
        owner.analyze(rows,research=research,catalog=catalog,
                      analyses=(DiagnosticAnalysis('fragility',owner.context.identity,'source-v1'),))


@pytest.mark.parametrize('mutation',['context','observation','window','ledger','geometry'])
def test_mismatched_join_cannot_claim_compatible_evidence(mutation,tmp_path):
    owner,rows,research=sample()
    if mutation=='context':
        research=replace(research,context_id='wrong-economics')
    elif mutation=='observation':
        research=replace(research,accounts=(replace(research.accounts[0],observation_identity='other-result'),))
    elif mutation=='window':
        research=replace(research,witness=replace(research.witness,start_ns=1))
    elif mutation=='ledger':
        research=replace(research,trials=(DiagnosticTrial('unknown',0,'COMPLETE','no-such-observation'),))
    else:
        catalog,_=source_catalog(tmp_path,owner,dict(context_id=owner.context.identity,geometry_id='other-space'))
        with pytest.raises(ValueError,match='geometry'):
            owner.analyze(rows,research=research,catalog=catalog,
                analyses=(DiagnosticAnalysis('fragility',owner.context.identity,'source-v1'),))
        return
    with pytest.raises(ValueError):
        owner.analyze(rows,research=research)


def test_ledger_order_unknown_cost_and_input_budgets_fail_closed():
    owner,rows,research=sample()
    with pytest.raises(ValueError,match='contiguous'):
        replace(research,trials=tuple(reversed(research.trials)))
    with pytest.raises(ValueError,match='nonnegative'):
        replace(research.trials[0],elapsed_seconds=-1.)
    limited=AlphaDiagnostics(RANGES,context=owner.context,access=owner.access,
        budget=DiagnosticBudget(max_account_bytes=1))
    with pytest.raises(ValueError,match='byte budget'):
        limited.analyze(rows,research=research)


def test_conditional_coupled_geometry_and_option_cards_use_existing_factory():
    from quantbt.diagnostics.geometry.schema import EffectiveGeometry, OrderedConstraint
    ranges={'branch':['on','off'],'short':(1,3),'long':(4,8),
        'filter':{'kind':'integer','low':1,'high':9,'active_if':{'branch':['on']}}}
    owner,_,research=sample()
    geometry=EffectiveGeometry.from_ranges(ranges,constraints=(OrderedConstraint(('short','long')),))
    owner=AlphaDiagnostics(ranges,context=owner.context,access=owner.access,geometry=geometry)
    rows=[]
    for i,params in enumerate((dict(branch='on',short=1,long=4,filter=3),dict(branch='off',short=2,long=5))):
        from quantbt.diagnostics import DiagnosticObservation
        rows.append(DiagnosticObservation.from_params(geometry=geometry,params=params,
            metrics={'quality':float(i),'risk':0.},evaluation_id=str(i),context_id=owner.context.identity,
            witness=research.witness,source_ref='retained'))
    out=data(owner,rows,replace(research,trials=(),accounts=()))
    compat={c['recipe_id']:c['compatible'] for c in out['recipe_options'] if c['kind']=='sampler'}
    assert compat==dict(tpe_legacy=True,tpe_multivariate_group=True,cmaes=False,sobol=False)
    assert len(out['search']['branches'])==2 and out['search']['constraint_count']==1
    assert next(a for a in out['search']['axes'] if a['name']=='filter')['active_effective_points']==1


@pytest.mark.parametrize('copy',[deepcopy,lambda v:pickle.loads(pickle.dumps(v))])
def test_immutable_cold_views_and_private_exports(copy,monkeypatch):
    owner,rows,research=sample()
    py_state,np_state=random.getstate(),np.random.get_state()
    from quantbt import QuantBTEndpoint
    monkeypatch.setattr(QuantBTEndpoint,'backtest',lambda *a,**kw:pytest.fail('financial execution'))
    monkeypatch.setattr(np.random,'default_rng',lambda *a,**kw:pytest.fail('RNG consumption'))
    a=owner.analyze(rows,research=research)
    b=copy(owner.analyze(rows,research=research))
    assert a.identity==b.identity
    restored=AlphaDiagnosticReport(Record.of(json.loads(a.to_json())))
    assert restored.to_markdown()==a.to_markdown()
    b.to_dict()['researcher_diagnostics']['accounts'][0]['net_pnl']=9999
    assert b.identity==a.identity and b.to_dict()['researcher_diagnostics']['accounts'][0]['net_pnl']==0
    assert random.getstate()==py_state
    now=np.random.get_state()
    np.testing.assert_array_equal(now[1],np_state[1]); assert now[2:]==np_state[2:]
    public=a.to_json(public=True)+a.to_markdown(public=True)
    for secret in (owner.context.alpha_id,owner.context.economics_id,'actual-output','source-labels','window','bull','synthetic-original-account'):
        assert secret not in public
    assert 'REDACTED' in public
    b.authorize(owner.access)


def test_card_choice_still_requires_explicit_researcher_shortlist():
    owner,rows,research=sample()
    advice=(DiagnosticAdvice('sampler','tpe_legacy','Keep registered comparator',('geometry',)),)
    report=owner.analyze(rows,research=research,advice=advice)
    chosen=report.with_choice(access=owner.access,sampler_id='tpe_legacy',selector_id=None,reason='Registered choice')
    assert chosen.to_dict()['researcher_choice']['applies_configuration'] is False
    with pytest.raises(ValueError,match='shortlist'):
        report.with_choice(access=owner.access,sampler_id='cmaes',selector_id=None,reason='Unregistered choice')


@pytest.mark.parametrize('status',['SHARP_PEAK','STABLE_NEIGHBORHOOD','INSUFFICIENT_COVERAGE'])
def test_source_bound_local_outcomes_remain_distinct_without_becoming_global_claims(tmp_path,status):
    owner,rows,research=sample()
    catalog,_=source_catalog(tmp_path,owner,dict(context_id=owner.context.identity,
        geometry_id=owner.geometry.identity,status=status,method='registered_local_probes_v1'))
    out=data(owner,rows,research,catalog=catalog,
        analyses=(DiagnosticAnalysis('fragility',owner.context.identity,'source-v1'),))
    item=next(f for f in out['findings'] if f['finding_id']=='sharpness')
    assert item['value']['producer_status']==status
    assert item['status']=='OBSERVED_SOURCE' and item['evidence_ids']==['source-v1']
    assert 'not a newly qualified estimator' in item['interpretation']


def test_promoted_environment_owners_keep_exact_math_bodies_and_legacy_imports():
    from tools.mode5_environments.attribution import daily_path as old
    from quantbt.diagnostics.environments.attribution import daily_path as new
    from tools.mode5_environments.manifests import match_calendar as old_calendar
    from quantbt.diagnostics.environments.manifests import match_calendar as new_calendar
    assert old is new
    assert old_calendar is new_calendar


def test_existing_six_matrix_owner_is_reverified_without_copying_matrix_rows(tmp_path):
    from tests.mode5.dossier_fixtures import fixture
    from quantbt.mode5.dossier.dossier import Dossier
    dossier,catalog,kwargs=fixture(tmp_path)
    ctx=context(alpha_id='frozen-1',market_id='frozen-1',economics_id='frozen-1',outcome_blind_roster=False)
    policy=AccessPolicy('prefix',('synthetic',),('development-1',),10,'diagnostic')
    owner=AlphaDiagnostics(RANGES,context=ctx,access=policy)
    kwargs['context']=Record.of(dict(dossier.record.data['context'],schema=owner.geometry.identity))
    dossier=Dossier.create(**kwargs)
    witness=AccessWitness('development-1','synthetic',0,8,9)
    rows=[replace(r,witness=witness) for r in observations(ctx,owner.geometry)]
    research=DiagnosticResearch(ctx.identity,witness,'registered-dossier',dossier=dossier)
    out=data(owner,rows,research,catalog=catalog)
    assert len(out['matrices'])==6
    assert all(m['status']=='VERIFIED_RETAINED_MATRIX' and m['row_count']==2 for m in out['matrices'].values())
    assert all('rows' not in m for m in out['matrices'].values())
    wrong=replace(dossier,record=Record.of(dict(dossier.record.data,context=dict(
        dossier.record.data['context'],economics='another-account'))))
    with pytest.raises(ValueError):
        owner.analyze(rows,research=replace(research,dossier=wrong),catalog=catalog)
    # A catalog made under later rights cannot grant an earlier policy access.
    earlier=AlphaDiagnostics(RANGES,context=ctx,access=replace(policy,cutoff_ns=8))
    with pytest.raises(PermissionError):
        earlier.analyze(rows,research=research,catalog=catalog)


@pytest.mark.parametrize('field,value',[('evaluation_id','another-winner'),('point_identity','other-geometry'),('probe_role','held_but_unregistered')])
def test_wrong_winner_or_probe_role_cannot_acquire_local_evidence(tmp_path,field,value):
    owner,rows,research=sample()
    center=dict(evaluation_id=rows[0].evaluation_id,point_identity=rows[0].point.identity,
                probe_role='selection_probes',f_max=.4,unique_probes=16)
    center[field]=value
    catalog,_=source_catalog(tmp_path,owner,dict(context_id=owner.context.identity,
        geometry_id=owner.geometry.identity,centers=[center]))
    with pytest.raises(ValueError):
        owner.analyze(rows,research=research,catalog=catalog,
            analyses=(DiagnosticAnalysis('fragility',owner.context.identity,'source-v1'),))


def test_selection_metrics_components_and_native_fallback_are_source_fields(tmp_path):
    owner,rows,research=sample()
    values=dict(context_id=owner.context.identity,geometry_id=owner.geometry.identity,
        raw_best_id=rows[-1].evaluation_id,native_id=rows[3].evaluation_id,
        selected_id=rows[3].evaluation_id,top_cohort_count=3,cluster_size=2,fallback='NATIVE_NO_CLUSTER',
        selection_reason='registered_source_selector',
        objective_version='source-objective-v1',objective_components=dict(raw=1.,risk_penalty=.2))
    catalog,_=source_catalog(tmp_path,owner,values)
    report=owner.analyze(rows,research=research,catalog=catalog,
        analyses=(DiagnosticAnalysis('selection',owner.context.identity,'source-v1'),))
    profile=report.to_dict()['researcher_diagnostics']['analysis_profiles']['selection']
    assert profile['values']['cluster_size']==2
    assert profile['values']['objective_components']==values['objective_components']
    assert profile['values']['fallback']=='NATIVE_NO_CLUSTER'
    assert profile['missing_fields']==[]
    assert 'source-objective-v1' in report.to_markdown()


def test_stable_identity_binds_raw_buffers_and_unknown_state_support():
    owner,rows,research=sample()
    account=research.accounts[0]
    labels=FrozenBuffer.from_array('labels',np.array([-1,-1,0,0],dtype=np.int64))
    revised=replace(research,accounts=(replace(account,labels=labels),))
    assert revised.identity!=research.identity
    before=data(owner,rows,research)
    after=data(owner,rows,revised)
    assert after['accounts'][0]['unknown_states']==2
    assert before['accounts'][0]['net_pnl']==after['accounts'][0]['net_pnl']
    assert after['input_identity']!=before['input_identity']


def test_optional_source_changed_during_report_is_denied(tmp_path,monkeypatch):
    owner,rows,research=sample()
    catalog,path=source_catalog(tmp_path,owner,dict(context_id=owner.context.identity,status='OBSERVED'))
    original=catalog.require_ref
    def replace_after_read(ref):
        result=original(ref)
        path.write_text('{}')
        return result
    monkeypatch.setattr(catalog,'require_ref',replace_after_read)
    with pytest.raises(ValueError,match='changed'):
        owner.analyze(rows,research=research,catalog=catalog,
            analyses=(DiagnosticAnalysis('fragility',owner.context.identity,'source-v1'),))


def test_legacy_composite_dossier_schema_uses_exact_catalogged_geometry(tmp_path):
    from tests.mode5.dossier_fixtures import fixture
    from quantbt.mode5.dossier.dossier import Dossier
    dossier,original,kwargs=fixture(tmp_path)
    ctx=context(alpha_id='frozen-1',market_id='frozen-1',economics_id='frozen-1',outcome_blind_roster=False)
    policy=AccessPolicy('prefix',('synthetic',),('development-1',),10,'diagnostic')
    owner=AlphaDiagnostics(RANGES,context=ctx,access=policy)
    witness=AccessWitness('development-1','synthetic',0,8,9)
    path=tmp_path/'geometry.json';path.write_text(json.dumps(owner.geometry.metadata()))
    ident=file_identity(path)
    old=original.manifest.data['sources'][0]
    sources=(Source(old['source_id'],old['path'],old['sha256'],old['bytes'],AccessWitness(**old['witness'])),
             Source('original-geometry',str(path),ident['sha256'],ident['bytes'],witness))
    catalog=EvidenceCatalog(sources,original.policy)
    kwargs['catalog']=catalog
    dossier=Dossier.create(**kwargs)  # original opaque composite dependency IDs
    rows=[replace(r,witness=witness) for r in observations(ctx,owner.geometry)]
    request=DiagnosticResearch(ctx.identity,witness,'registered-original',dossier=dossier)
    with pytest.raises(ValueError,match='explicit catalog-bound geometry'):
        owner.analyze(rows,research=request,catalog=catalog)
    bound=replace(request,dossier_geometry_ref=Record.of(catalog.ref('original-geometry')))
    result=data(owner,rows,bound,catalog=catalog)
    assert all(m['status']=='VERIFIED_RETAINED_MATRIX' for m in result['matrices'].values())
    assert result['dossier_geometry_binding']==catalog.ref('original-geometry')
    with pytest.raises(ValueError):
        owner.analyze(rows,research=replace(bound,dossier_geometry_ref=Record.of(catalog.ref('registered','/cells/0'))),catalog=catalog)


def test_sampler_timing_keeps_original_span_and_missing_time_separate():
    owner,rows,research=sample()
    telemetry=Record.of(dict(recipe_id='tpe_legacy',wall_seconds=1.25,source_ref='original-sampler-ledger',
        details=dict(independent_sample_calls=12,actual_fallback='not_used')))
    out=data(owner,rows,replace(research,sampler_telemetry=telemetry))
    assert out['search']['sampler_telemetry']['value']==telemetry.data
    assert out['search']['attempts']['summed_observed_attempt_seconds']==pytest.approx(1.2)
    assert '1.25' in owner.analyze(rows,research=replace(research,sampler_telemetry=telemetry)).to_markdown()
    assert data(owner,rows,research)['search']['sampler_telemetry']['value'] is None
    with pytest.raises(ValueError):
        replace(research,sampler_telemetry=Record.of(dict(recipe_id='tpe_legacy',wall_seconds=-1.,source_ref='x')))


def test_final_source_check_covers_mutation_during_cold_reduction(tmp_path,monkeypatch):
    import quantbt.diagnostics.researcher as module
    owner,rows,research=sample()
    catalog,path=source_catalog(tmp_path,owner,dict(context_id=owner.context.identity,status='OBSERVED'))
    original=module.assemble_research
    def changed_after_reduce(*args,**kwargs):
        result=original(*args,**kwargs)
        path.write_text('{}')
        return result
    monkeypatch.setattr(module,'assemble_research',changed_after_reduce)
    with pytest.raises(ValueError,match='changed'):
        owner.analyze(rows,research=research,catalog=catalog,
            analyses=(DiagnosticAnalysis('fragility',owner.context.identity,'source-v1'),))
