"""Pure reductions pay fees from solvent equity, not locked initial margin."""

from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from quantbt import OrderCommand, OrderSide, OrderType, TimeInForce
from quantbt.backends.native_event import NativeEventBackend, NativeEventConfig
from quantbt.core.event import _event_margin_allows_fill
from quantbt.core.schema import AccountConfig

from .conftest import ScheduledCommandStrategy, run_reactive


def scenario(*, quantity=190., reduce_only=True, extra_side=OrderSide.BUY,
             close_type=OrderType.MARKET, open_price=110.):
    idx=pd.date_range('2024-01-01',periods=4,freq='h',tz='UTC')
    close=pd.Series([100.,100.,110.,110.],index=idx)
    frame=pd.DataFrame(dict(open=close,high=close,low=close,close=close,volume=10000.),index=idx)
    frame.loc[idx[2],'open']=open_price
    frame.loc[idx[2],'high']=max(110.,open_price)
    frame.loc[idx[2],'low']=min(110.,open_price)
    extra=dict(trigger_price=open_price) if close_type==OrderType.STOP_MARKET else {}
    commands=(OrderCommand(timestamp=idx[1],symbol='BTC',side=OrderSide.SELL,
        order_type=OrderType.MARKET,qty=190.,tif=TimeInForce.IOC,order_id='entry'),
        OrderCommand(timestamp=idx[2],symbol='BTC',side=extra_side,order_type=close_type,
        qty=quantity,reduce_only=reduce_only,tif=TimeInForce.IOC,order_id='exit',**extra))
    return frame,commands


def execute(kind,frame,commands):
    if kind=='callback_python':
        schedule={i:[replace(command,timestamp=frame.index[i])] for i,command in enumerate(commands)}
        return run_reactive('single_pass',ScheduledCommandStrategy(schedule),data=frame,
            initial_capital=20000.,leverage=1.,fee_rate=.0004,native_backend='python',
            execution_contract='event_lifecycle_v3_next_open')
    backend=NativeEventBackend(NativeEventConfig(account=AccountConfig(initial_capital=20000.,leverage=1.),
        fee_rate=.0004,use_funding=False,native_backend='rust' if kind=='rust' else 'python',
        execution_contract='event_lifecycle_v3_next_open'))
    return backend.run_order_commands(frame.index,commands,{'BTC':frame.close},{'BTC':frame.high},
        {'BTC':frame.low},opens={'BTC':frame.open},symbols=['BTC'])


@pytest.mark.parametrize('kind',['numba','callback_python','rust'])
@pytest.mark.parametrize('quantity',[10.,190.,1000.])
def test_solvent_full_partial_and_clipped_reduction_with_negative_free_margin(kind,quantity):
    frame,commands=scenario(quantity=quantity)
    result=execute(kind,frame,commands)
    actual=min(quantity,190.)
    assert len(result.fills)==2
    assert result.fills[-1].qty==pytest.approx(actual)
    assert result.positions.iloc[-1,0]==pytest.approx(-190.+actual)
    assert result.equity.iloc[-1]==pytest.approx(18092.4-actual*110*.0004)
    assert not result.liquidated


@pytest.mark.parametrize('kind',['numba','callback_python','rust'])
@pytest.mark.parametrize('side,quantity',[(OrderSide.SELL,1.),(OrderSide.BUY,300.),(OrderSide.BUY,190.)])
def test_non_reduce_only_increase_reversal_and_legacy_reduction_keep_original_gate(kind,side,quantity):
    frame,commands=scenario(quantity=quantity,reduce_only=False,extra_side=side)
    result=execute(kind,frame,commands)
    assert len(result.fills)==1
    assert result.positions.iloc[-1,0]==pytest.approx(-190.)
    assert result.equity.iloc[-1]==pytest.approx(18092.4)


@pytest.mark.parametrize('kind',['numba','callback_python','rust'])
def test_fee_affordability_uses_actual_fill_price_equity(kind):
    frame,commands=scenario(open_price=90.)
    result=execute(kind,frame,commands)
    assert len(result.fills)==2 and result.fills[-1].price==pytest.approx(90.)
    assert result.positions.iloc[-1,0]==pytest.approx(0.)
    assert result.equity.iloc[-1]==pytest.approx(20000.-7.6+1900.-6.84)


@pytest.mark.parametrize('kind',['numba','callback_python','rust'])
def test_protective_stop_can_release_locked_margin(kind):
    frame,commands=scenario(close_type=OrderType.STOP_MARKET)
    result=execute(kind,frame,commands)
    assert len(result.fills)==2
    assert result.positions.iloc[-1,0]==pytest.approx(0.)
    assert result.equity.iloc[-1]==pytest.approx(18084.04)


@pytest.mark.parametrize('compiled',[False,True])
def test_insolvent_fee_and_reversal_do_not_receive_a_reduction_exemption(compiled):
    check=_event_margin_allows_fill if compiled else _event_margin_allows_fill.py_func
    assert not check(True,-190.,190.,1.,20900.,8.36,110.,110.,1.,8.36)
    assert not check(True,-190.,300.,18092.4,20900.,13.2,110.,110.,1.,13.2)
    assert check(True,-190.,10.,18092.4,20900.,.44,110.,110.,1.,.44)


def test_numba_python_and_rust_account_paths_match():
    frame,commands=scenario()
    results=[execute(k,frame,commands) for k in ('numba','callback_python','rust')]
    for other in results[1:]:
        for field in ('equity','positions','fees','funding','margin'):
            np.testing.assert_allclose(np.asarray(getattr(results[0],field)),
                                       np.asarray(getattr(other,field)),rtol=0,atol=1e-10)
