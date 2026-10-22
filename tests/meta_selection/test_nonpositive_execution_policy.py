"""Opt-in IS rejection never repairs prices or filters candidates on forward."""

from dataclasses import replace
from datetime import datetime, timezone
import random

import numpy as np
import optuna
import pandas as pd
import pytest

from quantbt import QuantBTEndpoint
from quantbt.core.orders import OrderCommand
from quantbt.core.schema import OrderSide, OrderType
from quantbt.core.wfo_failures import NonPositiveExecutionPrice, nonpositive_price_cause
from quantbt.walkforward import WalkForwardConfig
from quantbt.wfo_execution import WfoExecutionWindow

POLICY = 'prune_nonpositive_price_v1'
STAMP = datetime(2021, 1, 1, tzinfo=timezone.utc)


def failure(price=-1., **kw):
    return NonPositiveExecutionPrice(price,field=kw.get('field','price'),
        order_type=kw.get('order_type','limit'),timestamp=kw.get('timestamp',STAMP))


@pytest.mark.parametrize('price', [0., -0., -446.72510003048774])
def test_only_explicit_nonpositive_finite_prices_have_typed_disposition(price):
    error=failure(price)
    assert error.metadata()['price']==price
    assert error.metadata()['reason']=='NON_POSITIVE_EXECUTION_PRICE'


@pytest.mark.parametrize('price', [True,None,float('nan'),float('inf'),1.])
def test_unknown_or_positive_price_cannot_be_relabelled_infeasible(price):
    with pytest.raises(ValueError):
        failure(price)


def test_explicit_causes_only_not_error_strings_or_unrelated_context():
    typed=failure()
    outer=RuntimeError('strategy wrapper')
    outer.__cause__=typed
    assert nonpositive_price_cause(outer) is typed
    unrelated=ValueError('limit commands require price > 0')
    unrelated.__context__=typed
    assert nonpositive_price_cause(unrelated) is None
    outer.__cause__=outer
    assert nonpositive_price_cause(outer) is None


def data():
    index=pd.date_range('2021-01-01','2021-03-31',freq='D',tz='UTC')
    close=100.+np.arange(len(index))*.15+np.sin(np.arange(len(index)))
    return pd.DataFrame(dict(open=close,high=close+2.,low=close-2.,close=close,
        volume=1000.),index=index)


class Strategy:
    def __init__(self, kind='is'):
        self.kind=kind

    def generate_signal(self,*,data,params,train_index,test_index,fold):
        is_window=test_index.equals(train_index)
        invalid=self.kind=='forward' and not is_window or self.kind in {'is','unknown'} and params['x']==0
        if invalid:
            if self.kind=='unknown':
                raise ValueError('limit commands require price > 0')
            raise NonPositiveExecutionPrice(-1.,field='price',order_type='limit',timestamp=test_index[1])
        commands=(OrderCommand(test_index[1],symbol='X',side=OrderSide.BUY,
            order_type=OrderType.MARKET,qty=1.,order_id='entry'),
            OrderCommand(test_index[-2],symbol='X',side=OrderSide.SELL,
            order_type=OrderType.MARKET,qty=1.,reduce_only=True,order_id='exit'))
        return WfoExecutionWindow('order_commands',test_index,commands=commands)


def endpoint(strategy,policy=None,meta='off'):
    financial=QuantBTEndpoint.event_driven(input_mode='orders',backend='python',
        profile='audit',symbols=['X'],initial_capital=20000.,fee_rate=.0005,
        leverage=2.,use_funding=False,execution_contract='event_lifecycle_v3_next_open')
    cfg=dict(candidate_selection_metric='is_only_robust',flat_min_samples=1,
        flat_eps=1.,is_subperiods=1,use_scalar_trial_scoring=False,
        native_prepared_wfo='off',research_retention='full_trial_ledger')
    if policy is not None:
        cfg['invalid_execution_intent_policy']=policy
    if meta!='off':
        cfg['meta_selection']=dict(mode=meta,min_matured_origins=12,
            native_batch_policy='reference',label_observer=False)
    return QuantBTEndpoint.walk_forward(strategy_class=strategy,execution_endpoint=financial,
        target_mode='order_commands',split_mode='2021-03-01',split_frequency='monthly',
        window_mode='expanding',optimization_mode='mode_4_is_only_robust',
        optimization_schedule='per_fold_causal',optuna_trials=6,optuna_early_stopping=None,
        random_seed=731,optimization_config=cfg)


@pytest.fixture
def ordered_study(monkeypatch):
    original=optuna.create_study

    def create(*a,**kw):
        study=original(*a,**kw)
        for x in (0,1,2):
            study.enqueue_trial(dict(x=x))
        return study

    monkeypatch.setattr(optuna,'create_study',create)


RANGES={'x':dict(kind='integer',low=0,high=2)}


def test_public_is_prune_records_failure_and_uses_only_valid_pool(ordered_study):
    result=endpoint(Strategy(),POLICY).backtest(data=data(),param_ranges=RANGES)
    wf=result.metadata['walk_forward_result']
    trial=wf.trial_table.loc[wf.trial_table.trial_id.eq(0)].iloc[0]
    assert trial.pruned and trial.selection_metadata['reason']=='NON_POSITIVE_EXECUTION_PRICE'
    assert trial.selection_metadata['invalid_execution_intent']['price']==-1.
    assert wf.metadata['params_by_fold'][0]['x'] in (1,2)
    assert wf.metadata['sampler_studies'][0]['attempts']==6
    assert result.metadata['walk_forward']['invalid_execution_intent_policy']==POLICY


@pytest.mark.parametrize('kind,policy',[('is',None),('is','raise'),('unknown',POLICY),('forward',POLICY)])
def test_default_unknown_and_forward_errors_remain_fatal(kind,policy,ordered_study):
    with pytest.raises(RuntimeError):
        endpoint(Strategy(kind),policy).backtest(data=data(),param_ranges=RANGES)


def test_valid_only_input_has_identical_draws_selection_account_and_rng(ordered_study):
    random.seed(71)
    np.random.seed(72)
    baseline=endpoint(Strategy('valid')).backtest(data=data(),param_ranges=RANGES)
    state=random.getstate(),np.random.get_state()
    alternate=endpoint(Strategy('valid'),POLICY).backtest(data=data(),param_ranges=RANGES)
    assert random.getstate()==state[0]
    np.testing.assert_equal(np.random.get_state(),state[1])
    a,b=(r.metadata['walk_forward_result'] for r in (baseline,alternate))
    pd.testing.assert_frame_equal(a.trial_table,b.trial_table)
    assert a.metadata['params_by_fold']==b.metadata['params_by_fold']
    assert a.metadata['config_hash']!=b.metadata['config_hash']
    np.testing.assert_array_equal(a.metadata['strategy_lifecycle_table']['seed'],
        b.metadata['strategy_lifecycle_table']['seed'])
    assert a.metadata['sampler_studies'][0]['ask_tell_digest']==b.metadata['sampler_studies'][0]['ask_tell_digest']
    for key in ('equity','returns','positions','fees','funding','margin'):
        np.testing.assert_array_equal(getattr(baseline,key),getattr(alternate,key))


@pytest.mark.parametrize('policy',['prune',None,True])
def test_invalid_policy_values_fail_preflight(policy):
    with pytest.raises((ValueError,TypeError)):
        config=endpoint(Strategy(),POLICY).config.walkforward_config
        replace(config,metadata={**config.metadata,'invalid_execution_intent_policy':policy})


def test_nonexecution_route_cannot_silently_opt_in():
    with pytest.raises(NotImplementedError):
        WalkForwardConfig(split_mode='2021-03-01',optimization_mode='mode_4_is_only_robust',
            optimization_schedule='per_fold_causal',optuna_trials=6,
            candidate_selection_metric='is_only_robust',target_mode='pct_equity',
            metadata={'invalid_execution_intent_policy':POLICY})


def test_meta_excludes_pruned_trial_and_versions_the_nondefault_family(ordered_study):
    from quantbt.optimization.meta_selection.config import MetaHistoryContext
    from quantbt.optimization.meta_selection.history import MetaHistory

    def run(strategy,policy):
        context=MetaHistoryContext(MetaHistory(),'synthetic-price-policy','X','1D','price-test',
            clock=lambda f,s,e:f.train_index[-1]+pd.Timedelta(seconds={'search':10,'fit':20,'seal':30}[s]))
        return endpoint(strategy,policy,meta='active').backtest(data=data(),param_ranges=RANGES,
            meta_history=context).metadata['walk_forward_result'].metadata['meta_selection']

    rejected=run(Strategy(),POLICY)
    assert all(c.native_trial_id!=0 for c in rejected['tasks'][0].candidates)
    assert rejected['records'][0]['matured_origins']==0
    before=run(Strategy('valid'),None)
    after=run(Strategy('valid'),POLICY)
    assert before['tasks'][0].family.anchor_policy_id!=after['tasks'][0].family.anchor_policy_id
    assert before['records'][0]['selected_params']==after['records'][0]['selected_params']
