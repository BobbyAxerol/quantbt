"""Actual mature meta on both intent/session and explicit financial backends."""

from dataclasses import replace
import random

import numpy as np
import optuna
import pandas as pd
import pytest

from quantbt import QuantBTEndpoint
from quantbt.optimization.meta_selection.config import MetaHistoryContext
from quantbt.optimization.meta_selection.history import MetaHistory
from quantbt.wfo_execution import WfoExecutionWindow, execute_window
from tests.meta_selection import pre_e06_02_support as shared

optuna.logging.set_verbosity(optuna.logging.WARNING)


def strategy(session, data, params, train_index, test_index, fold):
    prefix = data.loc[:test_index[-1]]
    value = shared.generate("intrabar", prefix, params, test_index)
    return value if session else WfoExecutionWindow("intrabar", test_index, intent=value.intent)


def run(case, mode, *, data, history=None, start="2020-04-01", witness=True):
    from functools import partial
    backend, session = case
    old = shared.endpoint("intrabar", data, mode, start=start, numeric="require", witness=witness)
    financial = old.config.wfo_execution_config
    metadata = dict(financial.metadata)
    if not session:
        metadata.pop("session_policy", None)
    if backend == "rust":
        metadata["rust_intrabar_explicit"] = True
    financial = replace(financial, metadata=metadata,
        mode="intrabar_bracket_rust" if backend == "rust" else financial.mode,
        backend="rust_intrabar" if backend == "rust" else financial.backend)
    bt = QuantBTEndpoint(replace(old.config, wfo_execution_config=financial,
        strategy_class=partial(strategy, session)))
    context = MetaHistoryContext(history or MetaHistory(), "e06-public-synthetic",
        "E06-INTRABAR", "1D", "e06-software-v1", clock=shared.replay_clock)
    result = bt.backtest(data=data, param_ranges=shared.RANGES,
        **({} if mode == "off" else {"meta_history": context}))
    return shared.Run("intrabar", bt, result, context, data)


@pytest.fixture(scope="module", params=(("numba", False), ("numba", True), ("rust", False), ("rust", True)))
def qualified(request):
    pytest.importorskip("_quantbt_native", reason="this corpus requires native meta numeric dispatch")
    case = request.param
    data = shared.tape("intrabar", end="2022-05-31")
    historical = run(case, "shadow", data=data)
    active = run(case, "active", data=data, start="2022-05-01",
        history=shared.clone_history(historical.context.history))
    return case, historical, active


def test_e06_actual_mature_model_and_original_raw_measurement(qualified):
    case, _, value = qualified
    meta = value.meta
    record, task = meta["records"][0], meta["tasks"][0]
    assert record["matured_origins"] >= 12
    assert record["final_selection_reason"] == "META_MODEL_PROPOSAL"
    assert meta["models"] and record["proposal"].predictions
    assert record["past_matured_forward_used_for_selection"]
    assert not record["current_outer_oos_used_for_selection"]
    assert task.decision_sealed_at < task.first_forward_action_at
    assert value.result.metadata["walk_forward"]["params_by_fold"][0] == record["selected_params"]
    assert bool(value.result.metadata.get("rust_intrabar_authority")) == (case[0] == "rust")
    revision = next(r for r in value.context.history._revisions.values() if r.task.task_id == task.task_id)
    for outcome in revision.outcomes:
        candidate = next(c for c in task.candidates if c.evaluation_id == outcome.evaluation_id)
        for forward, observation in ((False, candidate.observation), (True, outcome.observation)):
            a, b = (task.forward_start, task.forward_end) if forward else (task.is_start, task.is_end)
            index = value.data.loc[a:b].index
            payload = strategy(case[1], value.data, candidate.effective_params, index, index, None)
            original = execute_window(value.endpoint.config.wfo_execution_config, value.data, payload)
            metrics = original.full_report(scope="full", trading_days=365)
            assert observation.raw_sharpe == pytest.approx(metrics["sharpe"], rel=1e-12, abs=1e-12)
            assert observation.activity_count == metrics["num_trades"]
            assert observation.verification == "original_result"
    stitched = value.result.metadata["walk_forward_result"].oos_output
    assert (stitched.session is not None) == case[1]
    rebuilt = execute_window(value.endpoint.config.wfo_execution_config, value.data, stitched)
    shared.account_equal(value.result, rebuilt)


def test_e06_off_shadow_search_and_rng_are_unchanged(qualified):
    case, historical, _ = qualified
    data = historical.data
    random.seed(81)
    np.random.seed(82)
    off = run(case, "off", data=data, start="2022-05-01")
    state = random.getstate(), np.random.get_state()
    shadow = run(case, "shadow", data=data, start="2022-05-01",
        history=shared.clone_history(historical.context.history))
    assert shadow.meta["models"] and shadow.meta["records"][0]["matured_origins"] >= 12
    assert state[0] == random.getstate()
    now = np.random.get_state()
    assert state[1][0] == now[0] and state[1][2:] == now[2:]
    np.testing.assert_array_equal(state[1][1], now[1])
    a, b = (v.result.metadata["walk_forward"] for v in (off, shadow))
    assert a["params_by_fold"] == b["params_by_fold"]
    pd.testing.assert_frame_equal(a["trial_table"], b["trial_table"])
    shared.account_equal(off.result, shadow.result)


def test_e06_mature_prepared_witness_has_same_decision_and_original_account(qualified):
    case, historical, active = qualified
    reference = run(case, "active", data=historical.data, start="2022-05-01", witness=False,
        history=shared.clone_history(historical.context.history))
    shared.decision_equal(active, reference)
    shared.account_equal(active.result, reference.result)


def test_e06_active_future_ohlcv_funding_cannot_enter_current_selection(qualified):
    case, historical, active = qualified
    data = historical.data.copy()
    future = data.index > shared.CUTOFFS[0]
    data.loc[future, ["open", "high", "low", "close", "volume"]] *= 1.3
    data.loc[future, "funding_rate"] *= 7
    altered = run(case, "active", data=data, start="2022-05-01",
        history=shared.clone_history(historical.context.history))
    shared.decision_equal(active, altered)
    def forward_signatures(v):
        task = v.meta["tasks"][0]
        revision = next(r for r in v.context.history._revisions.values() if r.task.task_id == task.task_id)
        return {o.evaluation_id: o.observation.input_signature for o in revision.outcomes}
    assert forward_signatures(active) != forward_signatures(altered)
