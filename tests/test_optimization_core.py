import json

import optuna
import pytest

from quantbt.optimization import (
    ObjectiveResult,
    OptimizationConfig,
    OptunaOptimizer,
    SamplerConfig,
    SingleObjectiveEarlyStopping,
    build_grid_search_space,
    stable_params_key,
    suggest_params,
)


class QuadraticEvaluator:
    def __init__(self):
        self.calls = []

    def evaluate(self, params):
        self.calls.append(dict(params))
        x = float(params["x"])
        score = -((x - 3.0) ** 2)
        return ObjectiveResult.scalar(score, metrics={"score": score, "x": x}, metadata={"family": "mock"})


class ConstantEvaluator:
    def __init__(self, value=1.0):
        self.value = float(value)

    def evaluate(self, params):
        return ObjectiveResult.scalar(self.value, metrics={"constant": self.value})


def test_single_objective_result_and_config_validation():
    result = ObjectiveResult.scalar(1.25, metrics={"sharpe": 1}, constraints=[-0.1], metadata={"a": "b"})

    assert result.values == (1.25,)
    assert result.metrics["sharpe"] == 1.0
    assert result.constraints == (-0.1,)
    assert result.metadata == {"a": "b"}

    with pytest.raises(ValueError, match="n_trials"):
        OptimizationConfig(study_name="bad", n_trials=0)
    with pytest.raises(ValueError, match="invalid directions"):
        OptimizationConfig(study_name="bad", directions=("max",))


def test_fixed_params_override_and_search_space_specs():
    trial = optuna.trial.FixedTrial({"window": 20, "kind": "fast", "flag": True, "threshold": 0.3})
    params = suggest_params(
        trial,
        {
            "window": (5, 50, 5),
            "kind": ["fast", "slow"],
            "flag": [True, False],
            "threshold": (0.1, 1.0, 0.1),
            "constant": "keep",
        },
        fixed_params={"window": 34, "extra": 7},
    )

    assert params == {
        "window": 34,
        "kind": "fast",
        "flag": True,
        "threshold": 0.3,
        "constant": "keep",
        "extra": 7,
    }
    assert stable_params_key({"b": 2, "a": 1}) == stable_params_key({"a": 1, "b": 2})


def test_grid_search_space_and_size_guard():
    grid = build_grid_search_space(
        {
            "window": (10, 14, 2),
            "kind": ["a", "b"],
            "flag": [True, False],
            "fixed": 1,
        },
        fixed_params={"kind": "a"},
    )

    assert grid == {"window": [10, 12, 14], "flag": [True, False]}
    with pytest.raises(ValueError, match="float step"):
        build_grid_search_space({"x": (0.0, 1.0)})
    with pytest.raises(ValueError, match="above max_grid_size"):
        build_grid_search_space({"x": range(200), "y": range(200)}, max_grid_size=100)


def test_optuna_optimizer_single_objective_and_trial_records():
    evaluator = QuadraticEvaluator()
    optimizer = OptunaOptimizer(
        evaluator=evaluator,
        config=OptimizationConfig(study_name="single_core", n_trials=12, seed=7, show_progress_bar=False),
        sampler_config=SamplerConfig(name="tpe", kwargs={"n_startup_trials": 3}),
    )

    result = optimizer.optimize(param_ranges={"x": (0, 6, 1)})

    assert result.best_params is not None
    assert result.best_values is not None
    assert result.selected_params == result.best_params
    assert len(result.trials) == 12
    assert all(record.state in {"COMPLETE", "PRUNED", "FAIL"} for record in result.trials)
    assert any(record.metrics.get("x") == result.best_params["x"] for record in result.trials if record.metrics)


def test_optuna_optimizer_accepts_unseeded_sampler():
    evaluator = QuadraticEvaluator()
    optimizer = OptunaOptimizer(
        evaluator=evaluator,
        config=OptimizationConfig(study_name="unseeded_core", n_trials=4, seed=None, show_progress_bar=False),
        sampler_config=SamplerConfig(name="tpe", kwargs={"n_startup_trials": 1}),
    )

    result = optimizer.optimize(param_ranges={"x": (0, 6, 1)})

    assert result.best_params is not None
    assert len(result.trials) == 4


def test_initial_trials_are_evaluated_first_and_recorded_as_baselines():
    evaluator = QuadraticEvaluator()
    optimizer = OptunaOptimizer(
        evaluator=evaluator,
        config=OptimizationConfig(study_name="initial_trials_core", n_trials=4, seed=7, show_progress_bar=False),
        sampler_config=SamplerConfig(name="random"),
    )

    result = optimizer.optimize(
        param_ranges={"x": (0, 6, 1)},
        initial_trials=[{"x": 3}],
    )

    assert evaluator.calls[0]["x"] == 3
    assert result.baseline_trials
    assert result.baseline_trials[0].metadata["quantbt_source"] == "warm_start"
    assert result.search_diagnostics["source_counts"]["warm_start"] == 1
    assert result.search_diagnostics["baseline_rank"][0]["rank"] == 1


def test_baseline_floor_keeps_warm_start_when_selector_prefers_worse_sample():
    class FirstSampleSelector:
        def select(self, result):
            from quantbt.optimization import SelectedCandidate

            sampled = next(record for record in result.trials if record.metadata.get("quantbt_source") != "warm_start" and record.state == "COMPLETE")
            return SelectedCandidate(
                params=dict(sampled.params),
                values=tuple(sampled.values),
                metrics=dict(sampled.metrics),
                constraints=tuple(sampled.constraints),
                metadata={"selector": "first_sample", "trial_number": sampled.number},
            )

    evaluator = QuadraticEvaluator()
    optimizer = OptunaOptimizer(
        evaluator=evaluator,
        config=OptimizationConfig(study_name="baseline_floor_core", n_trials=3, seed=2, show_progress_bar=False),
        sampler_config=SamplerConfig(name="random"),
    )

    result = optimizer.optimize(
        param_ranges={"x": (0, 6, 1)},
        initial_trials=[{"x": 3}],
        candidate_selector=FirstSampleSelector(),
    )

    assert result.selected_params == {"x": 3}
    assert result.search_regression is True
    assert result.selection_metadata["selected_by"] == "warm_start_baseline_floor"


def test_effective_params_builder_prunes_semantic_duplicates():
    class ToggleEvaluator:
        def __init__(self):
            self.calls = []

        def evaluate(self, params):
            self.calls.append(dict(params))
            return ObjectiveResult.scalar(float(params["x"]), metrics={"x": params["x"]})

    evaluator = ToggleEvaluator()
    optimizer = OptunaOptimizer(
        evaluator=evaluator,
        config=OptimizationConfig(study_name="effective_duplicate_core", n_trials=3, seed=1, show_progress_bar=False),
        sampler_config=SamplerConfig(name="random"),
    )

    result = optimizer.optimize(
        param_ranges={"x": [1], "use_filter": [False], "len_filter": [10, 20]},
        effective_params_builder=lambda params: {"x": params["x"], "use_filter": params["use_filter"]},
    )

    assert len(evaluator.calls) == 1
    assert [record.state for record in result.trials].count("PRUNED") == 2
    assert result.search_diagnostics["effective_duplicate_count"] == 2


def test_constraint_storage():
    class ConstraintEvaluator:
        def evaluate(self, params):
            x = float(params["x"])
            return ObjectiveResult.scalar(x, metrics={"x": x}, constraints=(x - 0.5,))

    optimizer = OptunaOptimizer(
        evaluator=ConstraintEvaluator(),
        config=OptimizationConfig(study_name="constraints_core", n_trials=4, seed=4, show_progress_bar=False),
        sampler_config=SamplerConfig(name="tpe", kwargs={"n_startup_trials": 1}),
    )

    result = optimizer.optimize(param_ranges={"x": (0.0, 1.0, 0.5)})

    completed = [trial for trial in result.trials if trial.state == "COMPLETE"]
    assert completed
    assert all(len(trial.constraints) == 1 for trial in completed)
    assert all("quantbt_constraints" in trial.user_attrs for trial in result.study.trials if trial.state.name == "COMPLETE")


def test_duplicate_pruning_and_nonfinite_objective_pruned():
    duplicate = OptunaOptimizer(
        evaluator=ConstantEvaluator(1.0),
        config=OptimizationConfig(study_name="duplicate_core", n_trials=3, seed=1, show_progress_bar=False),
        sampler_config=SamplerConfig(name="random"),
    )
    duplicate_result = duplicate.optimize(param_ranges={"x": [1]})

    states = [record.state for record in duplicate_result.trials]
    assert states.count("COMPLETE") == 1
    assert states.count("PRUNED") == 2

    class InfiniteEvaluator:
        def evaluate(self, params):
            return ObjectiveResult.scalar(float("inf"))

    nonfinite = OptunaOptimizer(
        evaluator=InfiniteEvaluator(),
        config=OptimizationConfig(study_name="nonfinite_core", n_trials=2, seed=1, show_progress_bar=False),
        sampler_config=SamplerConfig(name="random"),
    )
    result = nonfinite.optimize(param_ranges={"x": [1, 2]})

    assert all(record.state == "PRUNED" for record in result.trials)
    assert result.best_params is None


def test_exception_policy_raise():
    class BrokenEvaluator:
        def evaluate(self, params):
            raise RuntimeError("boom")

    optimizer = OptunaOptimizer(
        evaluator=BrokenEvaluator(),
        config=OptimizationConfig(study_name="raise_core", n_trials=2, show_progress_bar=False),
        sampler_config=SamplerConfig(name="random"),
    )

    with pytest.raises(RuntimeError, match="boom"):
        optimizer.optimize(param_ranges={"x": [1, 2]})


def test_single_objective_early_stopping_and_jsonl_logger(tmp_path):
    log_path = tmp_path / "study.jsonl"
    optimizer = OptunaOptimizer(
        evaluator=ConstantEvaluator(1.0),
        config=OptimizationConfig(
            study_name="early_stop_core",
            n_trials=10,
            seed=1,
            early_stopping_rounds=2,
            early_stopping_min_delta=0.0,
            show_progress_bar=False,
            log_path=log_path,
        ),
        sampler_config=SamplerConfig(name="random"),
    )

    result = optimizer.optimize(param_ranges={"x": (1, 10, 1)})

    assert len(result.trials) < 10
    rows = [json.loads(line) for line in log_path.read_text().splitlines()]
    assert rows
    assert rows[0]["values"] == [1.0]


def test_early_stopping_respects_min_trials_floor():
    optimizer = OptunaOptimizer(
        evaluator=ConstantEvaluator(1.0),
        config=OptimizationConfig(
            study_name="early_stop_min_trials_core",
            n_trials=10,
            seed=1,
            early_stopping_rounds=1,
            early_stopping_min_trials=4,
            early_stopping_min_delta=0.0,
            show_progress_bar=False,
        ),
        sampler_config=SamplerConfig(name="random"),
    )

    result = optimizer.optimize(param_ranges={"x": (1, 10, 1)})

    assert len(result.trials) >= 4
    assert len(result.trials) < 10


def test_pruned_trials_do_not_consume_patience():
    callback = SingleObjectiveEarlyStopping(patience=1, direction="maximize")
    study = optuna.create_study(direction="maximize")
    study.optimize(lambda trial: (_ for _ in ()).throw(optuna.TrialPruned()), n_trials=2, callbacks=[callback])

    assert callback._stale == 0
