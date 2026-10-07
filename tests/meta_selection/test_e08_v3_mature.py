"""Actual v3 fits plus chronology, witnesses and independent execution."""

from dataclasses import replace
import random

import numpy as np
import optuna
import pandas as pd
import pytest

from tests.meta_selection import e08_support as v3
from tests.meta_selection import e07_support as e07
from tests.meta_selection import pre_e06_02_support as shared

optuna.logging.set_verbosity(optuna.logging.WARNING)


@pytest.fixture(scope="module", params=v3.V3_CASES)
def mature(request):
    historical = v3.run(request.param, "shadow", start="2020-04-01")
    active = v3.run(request.param, history=shared.clone_history(historical.context.history))
    return request.param, historical, active


def test_mature_v3_actual_params_and_account(mature):
    case, history, active = mature
    meta = active.meta
    record, task = meta["records"][0], meta["tasks"][0]
    assert record["matured_origins"] >= 12 and meta["models"]
    assert record["final_selection_reason"] == "META_MODEL_PROPOSAL"
    assert not record["current_outer_oos_used_for_selection"]
    assert task.decision_sealed_at < task.first_forward_action_at
    assert len(record["proposal"].predictions) == len(task.candidates)
    assert e07.output(active)["params_by_fold"][0] == record["selected_params"]
    actual = active.result.metadata["wfo_execution_window"]
    assert actual["callback_boundary"] == "bar_close_next_open"
    assert actual["execution_contract_id"] == "event_lifecycle_v3_next_open"
    e07.rebuild(active)
    e07.rebuild(history)


def test_v3_all_raw_measurements(mature):
    from tests.meta_selection.test_e07_mature import test_e07_all_original_is_forward_measurements_and_output
    test_e07_all_original_is_forward_measurements_and_output(mature)


def test_v3_off_shadow_rng_and_account(mature):
    case, history, active = mature
    random.seed(81)
    np.random.seed(82)
    off = v3.run(case, "off")
    state = random.getstate(), np.random.get_state()
    shadow = v3.run(case, "shadow", history=shared.clone_history(history.context.history))
    assert random.getstate() == state[0]
    now = np.random.get_state()
    assert now[0] == state[1][0] and now[2:] == state[1][2:]
    np.testing.assert_array_equal(now[1], state[1][1])
    assert e07.output(off)["params_by_fold"] == e07.output(shadow)["params_by_fold"]
    pd.testing.assert_frame_equal(e07.output(off)["trial_table"], e07.output(shadow)["trial_table"])
    shared.account_equal(off.result, shadow.result)


def test_v3_future_mutation_does_not_change_selection(mature):
    case, history, active = mature
    data = active.data.copy()
    rows = data.index > shared.CUTOFFS[0]
    data.loc[rows, ["open", "high", "low", "close", "volume"]] *= 1.3
    data.loc[rows, "funding_rate"] *= 7
    altered = v3.run(case, data=data, history=shared.clone_history(history.context.history))
    shared.decision_equal(active, altered)
    assert [o.observation.input_signature for o in active.meta["observed_revisions"][0].outcomes] != [
        o.observation.input_signature for o in altered.meta["observed_revisions"][0].outcomes]


def test_v3_late_unavailable_labels_and_future_model(mature):
    case, historical, active = mature
    from tests.meta_selection.test_pre_e06_02_conformance import altered_labels
    from quantbt.optimization.meta_selection.artifacts import dumps_model, loads_model
    from quantbt.optimization.meta_selection.common import MetaRecordError
    history = shared.clone_history(historical.context.history, reverse=True)
    parent = next(r for r in history._revisions.values() if r.training_rows and r.revision_available_at < shared.CUTOFFS[0])
    correction = replace(parent, outcomes=altered_labels(parent, 100.),
        revision_available_at=shared.CUTOFFS[0]+pd.Timedelta(seconds=5),
        parent_revision_id=parent.revision_id, correction_reason="E08 late reconciliation fixture")
    added = []

    def clock(fold, stage, elapsed):
        if stage == "search" and not added:
            history.append(correction)
            added.append(correction.revision_id)
        return shared.replay_clock(fold, stage, elapsed)

    altered = v3.run(case, history=history, clock=clock)
    assert added and correction.revision_id not in altered.meta["records"][0]["training_revision_ids"]
    shared.decision_equal(active, altered)
    model = next(iter(active.meta["models"].values()))
    with pytest.raises(MetaRecordError, match="NOT_YET_AVAILABLE"):
        loads_model(dumps_model(model), expected_model_id=model.model_id, available_as_of=shared.CUTOFFS[0])


def test_v3_numeric_reference_and_prepared_witness_parity(mature):
    case, historical, active = mature
    reference = v3.run(case, variant=False, history=shared.clone_history(historical.context.history))
    shared.decision_equal(active, reference)
    shared.account_equal(active.result, reference.result)
