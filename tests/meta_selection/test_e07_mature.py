"""Five protocol/backend cells actually fit and apply mature meta decisions."""

from dataclasses import replace
import random

import numpy as np
import optuna
import pandas as pd
import pytest

from tests.meta_selection import e07_support as e07
from tests.meta_selection import pre_e06_02_support as shared

optuna.logging.set_verbosity(optuna.logging.WARNING)


@pytest.fixture(scope="module", params=e07.CASES)
def mature(request):
    case = request.param
    historical = e07.run(case, "shadow", start="2020-04-01")
    active = e07.run(case, history=shared.clone_history(historical.context.history))
    return case, historical, active


def test_e07_full_pool_fit_rank_actual_applied_params(mature):
    case, _, active = mature
    meta = active.meta
    record, task = meta["records"][0], meta["tasks"][0]
    assert record["matured_origins"] >= 12 and meta["models"]
    assert record["final_selection_reason"] == "META_MODEL_PROPOSAL"
    assert len(record["proposal"].predictions) == record["eligible_is_pool_size"] == len(task.candidates)
    assert record["past_matured_forward_used_for_selection"]
    assert not record["current_outer_oos_used_for_selection"]
    assert task.decision_sealed_at < task.first_forward_action_at
    chosen = next(c for c in task.candidates if c.evaluation_id == record["selected_evaluation_id"])
    params = active.result.params_by_fold if active.route == "reactive_reset" else e07.output(active)["params_by_fold"]
    assert dict(chosen.effective_params) == record["selected_params"] == params[0]
    e07.rebuild(active)
    if case[0] == "reactive_reset":
        assert not active.result.metadata["continuous_equity_available"]
        assert meta["account_authority"] == "existing_native_segmented_reset_flat"
        assert meta["witness_transport"]["financial_replays"] == 0
    else:
        assert active.result.metadata["wfo_execution_window"]["financial_replays"] == 0


def test_e07_all_original_is_forward_measurements_and_output(mature):
    _, _, active = mature
    meta = active.meta
    task = meta["tasks"][0]
    revision = meta["observed_revisions"][0]
    assert revision is active.context.history._revisions[revision.revision_id]
    for outcome in revision.outcomes:
        candidate = next(c for c in task.candidates if c.evaluation_id == outcome.evaluation_id)
        for forward, observation in ((False, candidate.observation), (True, outcome.observation)):
            original = e07.independent(active, task, candidate, forward=forward)
            report = original.full_report(scope="full", trading_days=365)
            assert observation.raw_sharpe == pytest.approx(report["sharpe"], rel=1e-12, abs=1e-12)
            assert observation.activity_count == report["num_trades"]
            from quantbt.metrics.performance import _array_returns_for_stats
            sample = _array_returns_for_stats(original.equity.index,
                original.equity.to_numpy(float), original.returns.to_numpy(float))
            assert observation.sample_count == len(sample)
            assert observation.sample_std == pytest.approx(np.std(sample, ddof=1), rel=1e-12, abs=1e-12)
            assert observation.verification == "original_result"
            expected = "CENSORED" if original.liquidated else "NO_VARIANCE" if np.std(sample, ddof=1) <= 0 else "VALID"
            assert observation.status.value == expected
        assert outcome.label_available_at > task.forward_end


def test_e07_off_shadow_exact_search_rng_accounts(mature):
    case, historical, _ = mature
    random.seed(81)
    np.random.seed(82)
    off = e07.run(case, "off")
    state = random.getstate(), np.random.get_state()
    shadow = e07.run(case, "shadow", history=shared.clone_history(historical.context.history))
    assert random.getstate() == state[0]
    now = np.random.get_state()
    assert now[0] == state[1][0] and now[2:] == state[1][2:]
    np.testing.assert_array_equal(now[1], state[1][1])
    if case[0] == "reactive_reset":
        assert off.result.params_by_fold == shadow.result.params_by_fold
        pd.testing.assert_frame_equal(off.result.trial_table, shadow.result.trial_table)
        shared.account_equal(off.result.fold_results[0].result, shadow.result.fold_results[0].result)
    else:
        a, b = e07.output(off), e07.output(shadow)
        assert a["params_by_fold"] == b["params_by_fold"]
        pd.testing.assert_frame_equal(a["trial_table"], b["trial_table"])
        shared.account_equal(off.result, shadow.result)
    assert shadow.meta["records"][0]["final_selection_reason"] == "META_MODEL_PROPOSAL"


def test_e07_mature_future_ohlcv_funding_excluded(mature):
    case, historical, active = mature
    data = active.data.copy()
    future = data.index > shared.CUTOFFS[0]
    data.loc[future, ["open", "high", "low", "close", "volume"]] *= 1.3
    data.loc[future, "funding_rate"] *= 7
    altered = e07.run(case, data=data, history=shared.clone_history(historical.context.history))
    shared.decision_equal(active, altered)
    assert [o.observation.input_signature for o in active.meta["observed_revisions"][0].outcomes] != [
        o.observation.input_signature for o in altered.meta["observed_revisions"][0].outcomes]


def test_e07_reverse_history_and_late_correction_excluded(mature):
    case, historical, active = mature
    from tests.meta_selection.test_pre_e06_02_conformance import altered_labels
    history = shared.clone_history(historical.context.history, reverse=True)
    parent = next(r for r in history._revisions.values() if r.training_rows and r.revision_available_at < shared.CUTOFFS[0])
    correction = replace(parent, outcomes=altered_labels(parent, 100.),
        revision_available_at=shared.CUTOFFS[0]+pd.Timedelta(seconds=5),
        parent_revision_id=parent.revision_id, correction_reason="E07 late reconciliation fixture")
    added = []

    def clock(fold, stage, elapsed):
        if stage == "search" and not added:
            history.append(correction)
            added.append(correction.revision_id)
        return shared.replay_clock(fold, stage, elapsed)

    altered = e07.run(case, history=history, clock=clock)
    assert added and correction.revision_id not in altered.meta["records"][0]["training_revision_ids"]
    shared.decision_equal(active, altered)


def test_e07_prepared_or_numeric_reference_has_same_policy_and_account(mature):
    case, historical, active = mature
    reference = e07.run(case, variant=False, history=shared.clone_history(historical.context.history))
    if case[0] == "reactive_reset":
        shared.policy_equal(active, reference)
    else:
        shared.decision_equal(active, reference)
        shared.account_equal(active.result, reference.result)


def test_e07_current_multifold_account_rebuild(mature):
    _, historical, _ = mature
    e07.rebuild(historical)


def test_e07_unavailable_history_and_future_models_are_rejected(mature):
    case, historical, active = mature
    history = historical.context.history
    from tests.meta_selection.test_pre_e06_02_conformance import altered_labels
    from quantbt.optimization.meta_selection.artifacts import dumps_model, loads_model
    from quantbt.optimization.meta_selection.common import MetaRecordError
    revisions = [replace(r, outcomes=altered_labels(r, 1000.))
        if r.revision_available_at > shared.CUTOFFS[0] else r
        for r in history._revisions.values()]
    altered = e07.run(case, history=shared.clone_history(history, revisions=revisions))
    shared.decision_equal(active, altered)
    model = next(iter(active.meta["models"].values()))
    with pytest.raises(MetaRecordError, match="NOT_YET_AVAILABLE"):
        loads_model(dumps_model(model), expected_model_id=model.model_id,
                    available_as_of=shared.CUTOFFS[0])
    assert loads_model(dumps_model(model), expected_model_id=model.model_id,
                       available_as_of=model.fit_completed_at) == model
