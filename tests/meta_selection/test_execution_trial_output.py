"""Transient trial output never changes account measurement or final audit."""

from dataclasses import replace
import random

import numpy as np
import pandas as pd
import pytest

from examples.wfo_meta_execution import generate, make_endpoint, market
from quantbt.endpoint import _make_walkforward_endpoint_scorer
from quantbt.optimization.execution_trial_output import execution_trial_config
from quantbt.optimization.meta_selection.common import wire
from quantbt.optimization.meta_selection.observer import (
    ResultMetricAdapter, canonical_metric_contract, economics_identity, market_signature,
)
from quantbt.wfo_execution import execute_window


@pytest.mark.parametrize("route", ("event_driven", "order_commands"))
@pytest.mark.parametrize("clock", ("event_lifecycle_v2_next_bar_close", "event_lifecycle_v3_next_open"))
def test_trial_paths_measurement_and_final_audit_are_identical(route, clock):
    endpoint = make_endpoint(route, "off", trials=2)
    config = replace(endpoint.config.wfo_execution_config, execution_contract=clock)
    trial = execution_trial_config(config, route=route,
        metadata={"execution_trial_output": "account_paths_v1"})
    data = market(end="2021-03-15")
    output = generate(route, data, {"window": 5}, data.index)
    audit = execute_window(config, data, output)
    compact = execute_window(trial, data, output)
    for field in ("equity", "returns", "positions", "fees", "funding", "margin"):
        np.testing.assert_array_equal(getattr(audit, field), getattr(compact, field))
    assert audit.fills == compact.fills
    assert audit.liquidated == compact.liquidated
    assert audit.full_report(trading_days=365, scope="full") == compact.full_report(trading_days=365, scope="full")
    adapter = ResultMetricAdapter(canonical_metric_contract())
    kwargs = dict(expected_index=data.index, economics_id=economics_identity(config),
        input_signature=market_signature(data, data.index, config=config), execution_config=config)
    assert wire(adapter.observe(audit, **kwargs)) == wire(adapter.observe(compact, **kwargs))
    assert config.report_level == "audit"
    assert trial.report_level == "standard"
    if route == "event_driven":
        assert audit.metadata["oracle_engine_runs"] == 1
        assert compact.metadata["oracle_engine_runs"] == 0


@pytest.mark.parametrize("audit_mode", ("dual_run_sampled", "sampled"))
def test_default_is_the_exact_original_object_and_sampled_rng_is_not_removed(audit_mode):
    config = make_endpoint("event_driven", "off").config.wfo_execution_config
    assert execution_trial_config(config, route="event_driven", metadata={}) is config
    with pytest.raises(ValueError, match="sampled-oracle RNG"):
        execution_trial_config(replace(config, audit_mode=audit_mode), route="event_driven",
            metadata={"execution_trial_output": "account_paths_v1"})


@pytest.mark.parametrize("route,policy", (("intrabar", "account_paths_v1"),
    ("portfolio", "account_paths_v1"), ("event_driven", "score")))
def test_invalid_or_unsupported_policy_fails_closed(route, policy):
    config = make_endpoint("event_driven", "off").config.wfo_execution_config
    with pytest.raises(ValueError):
        execution_trial_config(config, route=route, metadata={"execution_trial_output": policy})


def test_scorer_does_not_mutate_final_config_and_defaults_do_not_declare_purity():
    endpoint = make_endpoint("event_driven", "off", trials=2)
    config, wf = endpoint.config, endpoint.config.walkforward_config
    scorer = _make_walkforward_endpoint_scorer(config, "event_driven", wf_config=wf)
    assert scorer.deterministic_is_shard_reuse_contract() is None
    opted = replace(wf, metadata={**wf.metadata,
        "execution_trial_output": "account_paths_v1", "deterministic_is_shard_reuse": "no_rng_v1"})
    scorer = _make_walkforward_endpoint_scorer(config, "event_driven", wf_config=opted)
    assert scorer._execution_trial_config.report_level == "standard"
    assert scorer.score_config is config.wfo_execution_config
    assert scorer.score_config.report_level == "audit"
    assert scorer.deterministic_is_shard_reuse_contract()["no_rng"] is True


@pytest.mark.parametrize("route", ("event_driven", "order_commands"))
@pytest.mark.parametrize("mode", ("off", "shadow", "active"))
def test_public_study_preserves_order_objective_selection_rng_and_account(route, mode):
    from quantbt import QuantBTEndpoint
    from quantbt.optimization.meta_selection.config import MetaHistoryContext
    from quantbt.optimization.meta_selection.history import MetaHistory
    data = market(end="2021-04-30")
    def run(optimized):
        endpoint = make_endpoint(route, mode, trials=4, policy="reference")
        if optimized:
            wf = endpoint.config.walkforward_config
            endpoint = QuantBTEndpoint(replace(endpoint.config, walkforward_config=replace(wf,
                metadata={**wf.metadata, "execution_trial_output":"account_paths_v1",
                    "deterministic_is_shard_reuse":"no_rng_v1"})))
        kwargs = {} if mode == "off" else {"meta_history":MetaHistoryContext(MetaHistory(),
            "trial-output-parity", "SYNTHETIC-"+route, "1D", "matched",
            clock=lambda fold,stage,elapsed: fold.train_index[-1]+pd.Timedelta(
                seconds={"search":10,"fit":20,"seal":30}[stage]))}
        random.seed(199)
        np.random.seed(200)
        result = endpoint.backtest(data=data,
            param_ranges={"window":{"kind":"integer", "low":3, "high":9, "step":2}}, **kwargs)
        return result, random.getstate(), np.random.get_state()
    before, python_rng, numpy_rng = run(False)
    after, after_python_rng, after_numpy_rng = run(True)
    assert python_rng == after_python_rng
    np.testing.assert_equal(numpy_rng, after_numpy_rng)
    a,b = (r.metadata["walk_forward_result"] for r in (before,after))
    assert a.metadata["params_by_fold"] == b.metadata["params_by_fold"]
    assert [s["ask_tell_digest"] for s in a.metadata["sampler_studies"]] == [
        s["ask_tell_digest"] for s in b.metadata["sampler_studies"]]
    for column in ("objective", "mean_is_sharpe", "params"):
        assert a.trial_table[column].tolist() == b.trial_table[column].tolist()
    for field in ("equity", "returns", "positions", "fees", "funding", "margin"):
        np.testing.assert_array_equal(getattr(before,field),getattr(after,field))
    assert after.metadata["run_config"]["report_level"] == before.metadata["run_config"]["report_level"]
