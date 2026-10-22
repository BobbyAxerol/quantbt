"""Qualified trial output/reuse preserves an actually fitted causal decision."""

from dataclasses import replace

import pytest

from quantbt import QuantBTEndpoint
from tests.meta_selection import e07_support as event
from tests.meta_selection import pre_e06_02_support as shared


@pytest.mark.parametrize("route", ("event_driven", "order_commands"))
def test_actual_mature_rank_measurement_and_future_exclusion(route):
    case = route, "python"
    historical = event.run(case, "shadow", start="2020-04-01")
    reference = event.run(case, history=shared.clone_history(historical.context.history))

    def optimized(data=None):
        prepared = event.prepare_run(case, data=data,
            history=shared.clone_history(historical.context.history))
        _, endpoint, context, frame, kwargs = prepared
        config = endpoint.config
        wf = config.walkforward_config
        endpoint = QuantBTEndpoint(replace(config, walkforward_config=replace(wf,
            metadata={**wf.metadata, "execution_trial_output":"account_paths_v1",
                "deterministic_is_shard_reuse":"no_rng_v1"})))
        return shared.Run(route, endpoint, endpoint.backtest(**kwargs), context, frame)

    actual = optimized()
    shared.decision_equal(reference, actual)
    shared.account_equal(reference.result, actual.result)
    assert actual.meta["models"]
    assert actual.meta["records"][0]["matured_origins"] >= 12
    assert actual.meta["records"][0]["final_selection_reason"] == "META_MODEL_PROPOSAL"
    task = actual.meta["tasks"][0]
    assert [c.observation for c in task.candidates] == [
        c.observation for c in reference.meta["tasks"][0].candidates]
    event.rebuild(actual)
    data = actual.data.copy()
    future = data.index > shared.CUTOFFS[0]
    data.loc[future, ["open","high","low","close","volume"]] *= 1.3
    data.loc[future, "funding_rate"] *= 7
    changed = optimized(data)
    shared.decision_equal(actual, changed)
