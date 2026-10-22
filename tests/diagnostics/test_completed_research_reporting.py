"""Public cold accessors; synthetic retained metadata, never new alpha runs."""

import ast
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
import pickle
import random
import subprocess
from types import SimpleNamespace

import numpy as np
import pytest

from quantbt import QuantBTEndpoint
from quantbt.core.types import BacktestResult
from quantbt.core.results import (BacktestResultV2, BacktestScalarScoreResult,
    NativeEventScoreResult, NativeEventScalarScoreResult, OptionBacktestResult)
from quantbt.diagnostics import AccessPolicy, AccessWitness, ResearchDecisionReport
from quantbt.mode5 import DecisionReport
from quantbt.mode5.diagnostics.identity import canonical
from quantbt.mode5.dossier.records import Record
from quantbt.optimization.meta_selection.common import wire
from tests.diagnostics.test_decision_reports import fold, inputs, build
from tests.diagnostics.test_decision_report_safety import metadata_for

ROOT = Path(__file__).resolve().parents[2]
RESULT_TYPES = (BacktestResult, BacktestResultV2, BacktestScalarScoreResult,
                NativeEventScoreResult, NativeEventScalarScoreResult, OptionBacktestResult)


@pytest.fixture
def mode5_fixture(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / 'tests/mode5'))
    from tests.mode5.test_decision_report import runtime_metadata, SECRET
    return runtime_metadata, SECRET


def result_shell(result_type, metadata):
    # Only the accessor is exercised; this is not a constructed financial account.
    result = object.__new__(result_type)
    object.__setattr__(result, 'metadata', metadata)
    return result


def test_existing_endpoint_and_result_code_ast_is_unchanged_except_new_accessors():
    from tools.portfolio_repair_source_guard import without_portfolio_repair

    for path in ('src/quantbt/endpoint.py', 'src/quantbt/core/types.py', 'src/quantbt/core/results.py'):
        original = subprocess.check_output(['git','show','1633809:'+path], cwd=ROOT, text=True)
        current = ast.parse(without_portfolio_repair((ROOT/path).read_bytes(), path).decode())
        methods = []
        for node in current.body:
            if isinstance(node, ast.ClassDef):
                methods.extend(n for n in node.body if isinstance(n, ast.FunctionDef) and n.name=='research_report')
                node.body = [n for n in node.body if n not in methods]
        assert len(methods) == (4 if path.endswith('results.py') else 1)
        assert ast.dump(current, include_attributes=False)==ast.dump(ast.parse(original), include_attributes=False)


@pytest.mark.parametrize('kind', RESULT_TYPES)
@pytest.mark.parametrize('activation', ['active','shadow'])
def test_all_public_result_shapes_use_the_same_qualified_reader(kind, activation):
    rows = (fold(activation=activation), fold(1, activation=activation))
    _, access = inputs(*rows)
    metadata = dict(walk_forward=metadata_for(*rows))
    result = result_shell(kind, metadata)
    before = canonical(wire(metadata))
    actual = result.research_report(access=access, source_ref='synthetic-completed', role='synthetic')
    expected = ResearchDecisionReport.from_walk_forward(metadata['walk_forward'], access=access,
        source_ref='synthetic-completed', role='synthetic')
    assert actual.identity == expected.identity
    assert actual.to_dict()['summary'] == build(*rows).to_dict()['summary']
    assert canonical(wire(metadata)) == before


def test_endpoint_result_and_class_reader_are_identical_and_do_not_store_a_cache():
    row=fold(); _, access=inputs(row)
    result = result_shell(BacktestResultV2, dict(walk_forward=metadata_for(row)))
    endpoint = object.__new__(QuantBTEndpoint); endpoint.result=result
    options=dict(access=access,source_ref='synthetic-completed',role='synthetic')
    for _ in range(2):
        assert endpoint.research_report(**options).identity == result.research_report(**options).identity
    assert set(endpoint.__dict__)=={'result'}
    endpoint.result=None
    with pytest.raises(RuntimeError):
        endpoint.research_report(**options)


@pytest.mark.parametrize('continuous,no_selection', [(False,False),(True,False),(False,True),(True,True)])
def test_mode5_uses_original_reader_params_and_full_development_rights(continuous,no_selection,mode5_fixture):
    runtime_metadata,SECRET=mode5_fixture
    metadata, params = runtime_metadata(continuous=continuous,no_selection=no_selection)
    witness=AccessWitness('synthetic','synthetic',0,10**18,10**18)
    access=AccessPolicy('full-development',('synthetic',),('synthetic',),10**18,'diagnostic')
    result=SimpleNamespace(metadata=dict(walk_forward=dict(optimization_mode='mode_5_full_robust',
        mode5_diagnostics_first=metadata,best_trial=dict(params=params))))
    report=ResearchDecisionReport.from_result(result,access=access,source_ref='synthetic-mode5',
        role='synthetic',witness=witness)
    expected=ResearchDecisionReport.mode5(DecisionReport.read(metadata,selected_params=params),
        access=access,source_ref='synthetic-mode5',witness=witness)
    assert report.identity==expected.identity
    assert report.to_dict()['payload']['decision_use']=='NOT_BACKDATABLE'
    assert SECRET not in report.to_json(detail=True)
    assert report.to_dict(private=True)['summary']['selected_params']==params


@pytest.mark.parametrize('change',['missing_witness','dict_witness','wrong_role','wrong_params','prefix','future'])
def test_mode5_accessor_does_not_guess_params_permission_or_causal_scope(change,mode5_fixture):
    runtime_metadata,_=mode5_fixture
    metadata,params=runtime_metadata()
    witness=AccessWitness('synthetic','synthetic',0,10**18,10**18)
    access=AccessPolicy('full-development',('synthetic',),('synthetic',),10**18,'diagnostic')
    options=dict(access=access,source_ref='synthetic-mode5',role='synthetic',witness=witness)
    if change=='missing_witness': options.pop('witness')
    elif change=='dict_witness': options['witness']={}
    elif change=='wrong_role': options['role']='diagnostic_development'
    elif change=='wrong_params': params={'wrong':1}
    elif change=='prefix': options['view']='prefix'
    else: options['access']=replace(access,cutoff_ns=10)
    result=SimpleNamespace(metadata=dict(walk_forward=dict(optimization_mode='mode_5_full_robust',
        mode5_diagnostics_first=metadata,best_trial=dict(params=params))))
    with pytest.raises((ValueError,PermissionError)):
        ResearchDecisionReport.from_result(result,**options)


@pytest.mark.parametrize('mode',['mode_1_decay','mode_2_sbb','mode_3_flat_minima','mode_5_full_robust',None])
def test_missing_or_unqualified_modes_remain_explicit_not_a_new_meta_capability(mode):
    result=SimpleNamespace(metadata=dict(walk_forward=dict(optimization_mode=mode)))
    _, access=inputs(fold())
    with pytest.raises(ValueError,match='supports'):
        ResearchDecisionReport.from_result(result,access=access,source_ref='synthetic')


@pytest.mark.parametrize('metadata',[{},None,dict(walk_forward=None)])
def test_non_wfo_and_score_only_results_never_recreate_discarded_observations(metadata):
    _, access=inputs(fold())
    with pytest.raises(ValueError,match='completed public WFO'):
        ResearchDecisionReport.from_result(SimpleNamespace(metadata=metadata),access=access,source_ref='synthetic')


def test_meta_off_default_is_unchanged_and_rq_requires_retained_observer_records():
    row=fold(); _,access=inputs(row)
    metadata=metadata_for(row); metadata.pop('meta_selection')
    result=result_shell(BacktestScalarScoreResult,dict(walk_forward=metadata))
    before=deepcopy(result.metadata)
    with pytest.raises(ValueError,match='meta metadata'):
        result.research_report(access=access,source_ref='synthetic',role='synthetic')
    assert result.metadata==before
    off=replace(row,decision=None)
    slots,_=inputs(row)
    report=ResearchDecisionReport.mode4((off,),roster=slots,access=access)
    assert report.to_dict()['summary']['cohorts']['meta_disabled']['policies']['native']['calendar_count']==1


@pytest.mark.parametrize('private,detail',[(False,False),(False,True),(True,False),(True,True)])
def test_canonical_export_optimization_is_byte_identical_and_detached(private,detail):
    report=build(fold(),fold(1))
    expected=Record.of(report.to_dict(private=private,detail=detail)).payload
    assert report.to_json(private=private,detail=detail)==expected
    assert canonical(report.to_dict(private=private,detail=detail))==expected
    value=report.to_dict(private=private,detail=detail)
    value.clear()
    assert report.to_json(private=private,detail=detail)==expected
    for clone in (deepcopy(report),pickle.loads(pickle.dumps(report)),
        ResearchDecisionReport.from_json(report.to_json(private=True,detail=True))):
        assert clone.identity==report.identity


def test_accessors_reauthorize_every_call_and_have_no_finance_fit_search_or_rng_effect(monkeypatch):
    from quantbt.optimization.meta_selection.model import RidgeLearner
    from quantbt.walkforward import WalkForwardEngine
    import optuna
    def forbidden(*args,**kwargs):
        pytest.fail('cold reporting called financial/model/optimizer code')
    for owner,name in ((QuantBTEndpoint,'backtest'),(QuantBTEndpoint,'simulate'),
        (WalkForwardEngine,'run'),(WalkForwardEngine,'optimize_params'),(RidgeLearner,'fit'),(optuna,'create_study')):
        monkeypatch.setattr(owner,name,forbidden)
    row=fold(); _,access=inputs(row)
    result=result_shell(BacktestResult,dict(walk_forward=metadata_for(row)))
    rng=(random.getstate(),np.random.get_state())
    a=result.research_report(access=access,source_ref='synthetic',role='synthetic')
    b=result.research_report(access=access,source_ref='synthetic',role='synthetic')
    assert a.identity==b.identity
    with pytest.raises(PermissionError):
        result.research_report(access=replace(access,cutoff_ns=row.witness.ready_ns-1),
            source_ref='synthetic',role='synthetic')
    assert random.getstate()==rng[0]
    now=np.random.get_state(); np.testing.assert_array_equal(now[1],rng[1][1]); assert now[2:]==rng[1][2:]


def test_reporting_accessors_do_not_eagerly_import_diagnostics_into_legacy_results():
    script="import sys; import quantbt.core.results; assert 'quantbt.diagnostics.decisions.completed' not in sys.modules"
    subprocess.run([__import__('sys').executable,'-B','-c',script],cwd=ROOT,check=True)


def w3_metadata(row):
    return dict(metadata_for(row),schema='quantbt-reactive-wfo-result-v1',engine='reactive_wfo_w3',
        fold_account_policy='reset_flat',account_execution='segmented_reset_flat',continuous_equity_available=False)


def test_w3_direct_metadata_is_read_without_inventing_continuous_equity():
    row=fold(); _,access=inputs(row)
    result=SimpleNamespace(metadata=w3_metadata(row))
    report=ResearchDecisionReport.from_result(result,access=access,source_ref='synthetic-w3',role='synthetic')
    expected=ResearchDecisionReport.from_walk_forward(result.metadata,access=access,source_ref='synthetic-w3',role='synthetic')
    assert report.identity==expected.identity
    assert report.to_dict()['summary']['continuous_accounts']==[dict(status='NOT_SUPPLIED')]


@pytest.mark.parametrize('change',['engine','account','execution','continuous','ambiguous','accounts'])
def test_w3_reporting_never_silently_promotes_carry(change):
    row=fold(); _,access=inputs(row)
    metadata=w3_metadata(row); options={}
    if change=='engine': metadata['engine']='unknown'
    elif change=='account': metadata['fold_account_policy']='carry'
    elif change=='execution': metadata['account_execution']='continuous'
    elif change=='continuous': metadata['continuous_equity_available']=True
    elif change=='ambiguous': metadata['walk_forward']=metadata_for(row)
    else: options['accounts']=(object(),)
    with pytest.raises(ValueError,match='W3'):
        ResearchDecisionReport.from_result(SimpleNamespace(metadata=metadata),access=access,
            source_ref='synthetic-w3',role='synthetic',**options)


def test_public_completed_example_is_numeric_and_sanitized():
    from examples.completed_research_reporting import example_report
    report=example_report()
    assert report.to_dict()['summary']['cohorts']['all_calendar']['policies']['applied']['calendar_count']==12
    assert 'lookback' not in report.to_json(detail=True)
    assert 'Mean Q' in report.to_markdown()


def test_public_mode5_projection_does_not_revalidate_an_already_verified_snapshot(mode5_fixture,monkeypatch):
    runtime_metadata,_=mode5_fixture
    metadata,params=runtime_metadata(continuous=True)
    decision=DecisionReport.read(metadata,selected_params=params)
    witness=AccessWitness('synthetic','synthetic',0,10**18,10**18)
    access=AccessPolicy('full-development',('synthetic',),('synthetic',),10**18,'diagnostic')
    report=ResearchDecisionReport.mode5(decision,access=access,witness=witness,source_ref='synthetic')
    expected=report.to_json(detail=True)
    def forbidden(*a,**k):
        pytest.fail('renderer repeated cold input validation after report ownership was verified')
    monkeypatch.setattr(DecisionReport,'__post_init__',forbidden)
    assert report.to_json(detail=True)==expected
