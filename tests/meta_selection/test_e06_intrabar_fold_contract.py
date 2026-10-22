"""E06 fold boundaries are intent boundaries, never account/session resets."""

from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from quantbt import IntrabarIntentTape, IntrabarSessionTape, QuantBTEndpoint, SessionExecutionPolicy
from quantbt.wfo_execution import WfoExecutionWindow, execute_window, stitch_execution_windows
from tests.meta_selection.pre_e06_02_support import account_equal

BACKENDS = ("reference", "numba", "rust")


def frame():
    index = pd.date_range("2024-01-01", periods=8, freq="h", tz="UTC")
    return pd.DataFrame(dict(open=100., high=101., low=99., close=100., volume=1000.), index=index)


def endpoint(backend, *, session=False):
    if backend == "rust":
        pytest.importorskip("_quantbt_native", reason="explicit Rust intrabar conformance needs the native wheel")
    constructor = {
        "reference": QuantBTEndpoint.intrabar_bracket_reference,
        "numba": QuantBTEndpoint.intrabar_bracket,
        "rust": QuantBTEndpoint.intrabar_bracket_rust,
    }[backend]
    return constructor(initial_capital=1000., leverage=3., fee_rate=.001,
        slippage_bps=0., use_funding=False, symbols=["X"], close_on_last_bar=False,
        report_level="audit", session_policy=SessionExecutionPolicy(
            max_long_entries_per_session=1, max_short_entries_per_session=1) if session else None)


def output(data, signals, *, session=False, stop=.05):
    index = data.index
    intent = pd.DataFrame(dict(entry_signal=signals, stop_value=stop,
        take_profit_value=.08, trailing_value=np.nan), index=index)
    tape = IntrabarSessionTape(np.full(len(index), 20917, np.int64),
        np.ones(len(index), bool), np.zeros(len(index), bool)) if session else None
    a = WfoExecutionWindow("intrabar", index, intent=intent, session=tape)
    return stitch_execution_windows((a.slice(index[:3]), a.slice(index[3:])), index)


@pytest.mark.parametrize("backend", BACKENDS)
@pytest.mark.parametrize("session", (False, True))
@pytest.mark.parametrize("side", (-1., 1.))
def test_e06_carry_stop_and_take_profit_bound_to_original_entry(backend, session, side):
    data = frame()
    data.loc[data.index[3], "high" if side < 0 else "low"] = 102. if side < 0 else 98.
    data.loc[data.index[5], "high" if side < 0 else "low"] = 106. if side < 0 else 94.
    out = output(data, [side, 0., 0., 0., 0., 0., 0., 0.], session=session)
    # The later fold's new proposed bracket does not amend an existing trade.
    out.intent.loc[data.index[3]:, "stop_value"] = .001
    out.intent.loc[data.index[3]:, "take_profit_value"] = .001
    result = execute_window(endpoint(backend, session=session).config, data, out)
    assert result.positions.Position_X.iloc[3] == side
    assert result.positions.Position_X.iloc[5] == 0.
    exit_price = 105. if side < 0 else 95.
    fees = .1 + exit_price * .001
    assert result.fees.sum() == pytest.approx(fees)
    assert result.equity.iloc[-1] == pytest.approx(1000. - 5. - fees)
    assert result.diagnostics.active_take_profit.iloc[3] == pytest.approx(92. if side < 0 else 108.)


@pytest.mark.parametrize("backend", BACKENDS)
def test_e06_pending_next_open_entry_crosses_fold_boundary(backend):
    data = frame()
    out = output(data, [0., 0., 1., 0., 0., 0., 0., 0.])
    result = execute_window(endpoint(backend).config, data, out)
    assert result.positions.Position_X.iloc[2] == 0.
    assert result.positions.Position_X.iloc[3] == 1.
    assert result.fees.sum() == pytest.approx(.1)
    assert result.equity.iloc[-1] == pytest.approx(999.9)


@pytest.mark.parametrize("backend", BACKENDS)
def test_e06_session_quota_and_force_flat_not_reset_at_fold(backend):
    data = frame()
    data.loc[data.index[2], "low"] = 94.
    out = output(data, [1., 0., 0., 1., 0., 0., 0., 0.], session=True)
    bt = endpoint(backend, session=True)
    continuous = execute_window(bt.config, data, out)
    assert continuous.positions.Position_X.iloc[4] == 0.
    assert continuous.fees.sum() == pytest.approx(.195)
    # A separately reset diagnostic is deliberately a different contract.
    diagnostic = execute_window(bt.config, data, out.slice(data.index[3:]))
    assert diagnostic.positions.Position_X.iloc[1] == 1.
    np.testing.assert_array_equal(out.session.session_id, 20917)
    forced = IntrabarSessionTape(out.session.session_id, out.session.entry_allowed_at_open,
        [False, False, False, False, True, False, False, False])
    force_output = WfoExecutionWindow("intrabar", data.index,
        intent=output(data, [1., 0., 0., 0., 1., 0., 0., 0.]).intent, session=forced)
    forced_result = execute_window(bt.config, frame(), force_output)
    assert forced_result.positions.Position_X.iloc[4] == 0.
    assert forced_result.positions.Position_X.iloc[5] == 0.


@pytest.mark.parametrize("backend", ("numba", "rust"))
@pytest.mark.parametrize("session", (False, True))
def test_e06_prepared_runs_are_independent_and_keep_all_account_buffers(backend, session):
    data = frame()
    data.loc[data.index[5], "low"] = 94.
    out = output(data, [1., 0., 0., 0., 0., 0., 0., 0.], session=session)
    bt = endpoint(backend, session=session)
    direct = execute_window(bt.config, data, out)
    runner = bt.prepare_intrabar(data=data, session_tape=out.session)
    intent = IntrabarIntentTape.from_arrays(entry_side=np.sign(out.intent.entry_signal).astype(np.int8),
        entry_size=np.abs(out.intent.entry_signal), stop_value=out.intent.stop_value,
        take_profit_value=out.intent.take_profit_value, trailing_value=out.intent.trailing_value)
    for level in ("audit", "minimal", "audit"):
        account_equal(direct, runner.run(intent, report_level=level))
    minimal = execute_window(replace(bt.config, report_level="minimal"), data, out)
    account_equal(direct, minimal)
