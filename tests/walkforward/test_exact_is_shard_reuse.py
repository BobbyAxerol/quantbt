"""Synthetic scorer contracts only; no financial endpoint execution."""

from copy import deepcopy
from dataclasses import replace
import random

import numpy as np
import pandas as pd
import pytest

from quantbt.optimization.exact_is_reuse import EXACT_IS_SHARD_REUSE_SCHEMA_V1
from quantbt.walkforward import PreparedWalkForwardContext, WalkForwardConfig, WalkForwardEngine


CONTRACT = {"schema": EXACT_IS_SHARD_REUSE_SCHEMA_V1, "no_rng": True}


@pytest.fixture(autouse=True)
def preserve_rng():
    python_state, numpy_state = random.getstate(), np.random.get_state()
    yield
    random.setstate(python_state)
    np.random.set_state(numpy_state)


class Scorer:
    def __init__(self):
        self.calls = []

    def __call__(self, **task):
        self.calls.append(task)
        value = float(task["output"].mean()) + 1.5
        return {
            "sharpe": value, "turnover": 2.0, "trade_count": 2.0,
            "meta_observation": {"status": "VALID", "raw_sharpe": value,
                "sample_count": len(task["index"]) - 1, "sample_std": 0.25,
                "nested": {"calendar_start": task["index"][0].isoformat()}},
        }


class QualifiedScorer(Scorer):
    def deterministic_is_shard_reuse_contract(self):
        return dict(CONTRACT)


class BatchScorer(QualifiedScorer):
    def score_batch(self, tasks):
        return [self(**task) for task in tasks]


def strategy(data, params, train_index, test_index, fold):
    return pd.Series(float(params["direction"]), index=test_index)


def setup(scorer, *, parts=1, prepared=False, mode="mode_4_is_only_robust"):
    index = pd.date_range("2024-01-01", periods=288, freq="h", tz="UTC")
    data = pd.DataFrame({"close": np.arange(len(index), dtype=float) + 100.0}, index=index)
    config = WalkForwardConfig(
        split_mode="2024-01-07", split_frequency="single", scoring_backend="endpoint",
        optimization_mode=mode,
        optimization_schedule="global" if mode == "mode_5_full_robust" else "per_fold_causal",
        optuna_trials=1,
        candidate_selection_metric="full_robust" if mode == "mode_5_full_robust" else "is_only_robust",
        is_subperiods=parts, min_trades_per_year=365.0, trade_penalty_factor=0.5,
        use_numba=False, metadata={"wfo_execution_reuse": "off"},
    )
    engine = WalkForwardEngine(strategy, config, scorer)
    folds = engine.build_folds(index)
    if prepared:
        engine._prepared_context = PreparedWalkForwardContext.prepare(
            data=data, datetime_index=index, folds=folds, config=config,
        )
    engine._performance_profile = {"enabled": True, "score_calls": 0}
    return engine, data, folds


@pytest.mark.parametrize("scorer_type,expected", [(Scorer, 2), (QualifiedScorer, 1), (BatchScorer, 1)])
@pytest.mark.parametrize("prepared", [False, True])
@pytest.mark.parametrize("mode", ["mode_4_is_only_robust", "mode_5_full_robust"])
def test_exact_full_is_shard_keeps_logical_statistics(scorer_type, expected, prepared, mode):
    scorer = scorer_type()
    engine, data, folds = setup(scorer, prepared=prepared, mode=mode)
    record = engine.evaluate_params_is(data, folds, {"direction": 1.0}, trial_id=7)
    assert len(scorer.calls) == expected
    assert engine._performance_profile["score_calls"] == 2
    metrics = record.fold_metrics[0]
    assert metrics["is_subperiod_count"] == record.selection_metadata["is_subperiod_count"] == 1
    assert metrics["is_subperiod_sharpes_raw"] == [metrics["is_sharpe_raw"]]
    assert metrics["is_subperiod_trade_counts"] == [metrics["is_trade_count"]]
    assert metrics["is_subperiod_sharpes"] == [record.objective]
    assert metrics["meta_observation"]["raw_sharpe"] == metrics["is_sharpe_raw"]


def test_qualified_complete_records_equal_reference_across_candidates():
    reference, data, folds = setup(Scorer())
    optimized, other_data, other_folds = setup(QualifiedScorer())
    for trial_id, direction in enumerate([1.0, -1.0, 1.0, 2.0]):
        expected = reference.evaluate_params_is(data, folds, {"direction": direction}, trial_id)
        actual = optimized.evaluate_params_is(other_data, other_folds, {"direction": direction}, trial_id)
        assert actual == expected
    assert len(reference.scorer.calls) == 8 and len(optimized.scorer.calls) == 4
    assert [p["params"]["direction"] for p in optimized.scorer.calls] == [1.0, -1.0, 1.0, 2.0]


@pytest.mark.parametrize("parts", [2, 3])
def test_multipart_shards_are_not_aliased(parts):
    engine, data, folds = setup(QualifiedScorer(), parts=parts)
    record = engine.evaluate_params_is(data, folds, {"direction": 1.0})
    assert len(engine.scorer.calls) == parts + 1
    assert record.fold_metrics[0]["is_subperiod_count"] == parts


def test_independent_folds_with_identical_calendars_are_not_aliased():
    engine, data, folds = setup(QualifiedScorer())
    folds = [folds[0], replace(folds[0], fold_id=1)]
    record = engine.evaluate_params_is(data, folds, {"direction": 1.0})
    assert [p["fold"].fold_id for p in engine.scorer.calls] == [0, 1]
    assert len(record.fold_metrics) == 2
    assert engine._performance_profile["score_calls"] == 4
    assert record.selection_metadata["is_subperiod_count"] == 2


@pytest.mark.parametrize("contract", [None, {}, [], True, {"schema": "unknown", "no_rng": True},
    {"schema": EXACT_IS_SHARD_REUSE_SCHEMA_V1}, {**CONTRACT, "no_rng": False},
    {**CONTRACT, "no_rng": 1}, {**CONTRACT, "no_rng": "true"}, {**CONTRACT, "unknown": True}])
def test_unknown_or_malformed_contract_keeps_both_calls(contract):
    scorer = Scorer()
    scorer.deterministic_is_shard_reuse_contract = lambda: contract
    engine, data, folds = setup(scorer)
    engine.evaluate_params_is(data, folds, {"direction": 1.0})
    assert len(scorer.calls) == 2


@pytest.mark.parametrize("hook", [True, lambda unused: CONTRACT])
def test_noncallable_or_wrong_signature_contract_keeps_both_calls(hook):
    scorer = Scorer()
    scorer.deterministic_is_shard_reuse_contract = hook
    engine, data, folds = setup(scorer)
    engine.evaluate_params_is(data, folds, {"direction": 1.0})
    assert len(scorer.calls) == 2


def test_throwing_contract_keeps_both_calls():
    scorer = Scorer()
    def broken_contract():
        raise ValueError("qualification unavailable")
    scorer.deterministic_is_shard_reuse_contract = broken_contract
    engine, data, folds = setup(scorer)
    engine.evaluate_params_is(data, folds, {"direction": 1.0})
    assert len(scorer.calls) == 2


@pytest.mark.parametrize("execution_seed", [None, 731])
def test_qualified_no_rng_keeps_seeded_and_unseeded_continuation(execution_seed):
    if execution_seed is not None:
        random.seed(execution_seed)
        np.random.seed(execution_seed)
    initial_python, initial_numpy = random.getstate(), np.random.get_state()
    reference, data, folds = setup(Scorer())
    expected = reference.evaluate_params_is(data, folds, {"direction": 1.0}, execution_seed=execution_seed)
    expected_next = (random.random(), np.random.random())
    random.setstate(initial_python)
    np.random.set_state(initial_numpy)
    optimized, data, folds = setup(QualifiedScorer())
    sentinel = {"stage": "outer", "rng_seed": 999}
    optimized._wfo_execution_scope = sentinel
    actual = optimized.evaluate_params_is(data, folds, {"direction": 1.0}, execution_seed=execution_seed)
    assert (random.random(), np.random.random()) == expected_next
    assert actual == expected
    assert optimized._wfo_execution_scope is sentinel


@pytest.mark.parametrize("execution_seed", [None, 731])
def test_default_stochastic_stateful_scorer_still_advances_twice(execution_seed):
    class StatefulScorer(Scorer):
        def __init__(self):
            super().__init__()
            self.rng = np.random.default_rng(17)
        def __call__(self, **task):
            metrics = super().__call__(**task)
            metrics["sharpe"] = len(self.calls) + random.random() + np.random.random() + self.rng.random()
            return metrics
    if execution_seed is not None:
        random.seed(execution_seed)
        np.random.seed(execution_seed)
    initial_python, initial_numpy = random.getstate(), np.random.get_state()
    rng = np.random.default_rng(17)
    expected_scores = [i + random.random() + np.random.random() + rng.random() for i in (1, 2)]
    expected_next = (random.random(), np.random.random(), rng.random())
    random.setstate(initial_python)
    np.random.set_state(initial_numpy)
    scorer = StatefulScorer()
    engine, data, folds = setup(scorer)
    record = engine.evaluate_params_is(data, folds, {"direction": 1.0}, execution_seed=execution_seed)
    assert len(scorer.calls) == 2
    assert record.fold_metrics[0]["is_sharpe_raw"] == expected_scores[0]
    assert record.fold_metrics[0]["is_subperiod_sharpes_raw"] == [expected_scores[1]]
    assert (random.random(), np.random.random(), scorer.rng.random()) == expected_next


def test_alias_copies_entire_metric_and_nested_observation():
    engine, data, folds = setup(QualifiedScorer())
    output = strategy(data, {"direction": 1.0}, folds[0].train_index, folds[0].train_index, folds[0])
    task = (output, folds[0].train_index, folds[0], {"direction": 1.0}, "unit")
    metrics = engine._score_strategy_outputs_with_scope(data, [task, task], trial_id=0,
        params={"direction": 1.0}, stage="is_search", adaptive_optimizer=True,
        exact_is_shard_aliases={1: 0})
    assert metrics[0] == metrics[1] and metrics[0] is not metrics[1]
    original = deepcopy(metrics[0])
    metrics[1]["meta_observation"]["nested"]["calendar_start"] = "modified"
    assert metrics[0] == original


def test_active_terminal_reuse_runtime_is_not_bypassed():
    engine, data, folds = setup(QualifiedScorer())
    class Runtime:
        enabled = True
        def lookup(self, entries, scope):
            from types import SimpleNamespace
            self.positions = tuple(range(len(entries)))
            return SimpleNamespace(miss_positions=self.positions, cached_metrics=[None] * len(entries), lookup_count=0)
        def commit(self, lookup, metrics_by_position):
            self.committed = tuple(metrics_by_position)
    runtime = engine._wfo_execution_runtime = Runtime()
    engine.evaluate_params_is(data, folds, {"direction": 1.0})
    assert len(engine.scorer.calls) == 2
    assert runtime.positions == runtime.committed == (0, 1)
