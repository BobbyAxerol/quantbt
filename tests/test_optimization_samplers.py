import optuna
import pytest

from quantbt.optimization import ObjectiveResult, OptimizationConfig, OptunaOptimizer, SamplerConfig, build_sampler


class MultiObjectiveEvaluator:
    def evaluate(self, params):
        x = float(params["x"])
        return ObjectiveResult(values=(x, abs(x - 0.5)), metrics={"x": x})


def test_tpe_factory():
    sampler = build_sampler(SamplerConfig(name="tpe"), seed=42, search_space={"x": (0.0, 1.0, 0.1)}, objective_count=1)

    assert isinstance(sampler, optuna.samplers.TPESampler)


def test_random_factory():
    sampler = build_sampler(SamplerConfig(name="random"), seed=42, search_space={"x": (0, 5, 1)}, objective_count=1)

    assert isinstance(sampler, optuna.samplers.RandomSampler)


def test_grid_factory():
    sampler = build_sampler(SamplerConfig(name="grid"), seed=42, search_space={"x": (1, 3, 1), "kind": ["a", "b"]}, objective_count=1)

    assert isinstance(sampler, optuna.samplers.GridSampler)


def test_cmaes_rejects_categorical():
    with pytest.raises(ValueError, match="categorical"):
        build_sampler(SamplerConfig(name="cmaes"), seed=42, search_space={"x": (0.0, 1.0, 0.1), "kind": ["a", "b"]}, objective_count=1)


def test_nsgaii_multiobjective():
    optimizer = OptunaOptimizer(
        evaluator=MultiObjectiveEvaluator(),
        config=OptimizationConfig(
            study_name="nsgaii_sampler",
            n_trials=8,
            directions=("maximize", "minimize"),
            seed=42,
            show_progress_bar=False,
        ),
        sampler_config=SamplerConfig(name="nsgaii", kwargs={"population_size": 4}),
    )

    result = optimizer.optimize(param_ranges={"x": (0.0, 1.0, 0.25)})

    assert result.best_params is None
    assert result.pareto_trials
    assert all(len(trial.values) == 2 for trial in result.pareto_trials)


def test_constraints_func_propagation():
    def constraints_func(trial):
        return (0.0,)

    tpe = build_sampler(
        SamplerConfig(name="tpe"),
        seed=42,
        search_space={"x": (0.0, 1.0, 0.1)},
        objective_count=1,
        constraints_func=constraints_func,
    )
    nsgaii = build_sampler(
        SamplerConfig(name="nsgaii"),
        seed=42,
        search_space={"x": (0.0, 1.0, 0.1)},
        objective_count=2,
        constraints_func=constraints_func,
    )

    assert getattr(tpe, "_constraints_func") is constraints_func
    assert getattr(nsgaii, "_constraints_func") is constraints_func
    with pytest.raises(ValueError, match="does not support formal constraints"):
        build_sampler(SamplerConfig(name="random"), seed=42, search_space={"x": [1, 2]}, objective_count=1, constraints_func=constraints_func)


def test_sampler_seed_reproducibility():
    def run_once():
        seen = []

        class Recorder:
            def evaluate(self, params):
                seen.append(dict(params))
                return ObjectiveResult.scalar(float(params["x"]))

        optimizer = OptunaOptimizer(
            evaluator=Recorder(),
            config=OptimizationConfig(study_name="seed_repro", n_trials=5, seed=123, show_progress_bar=False, duplicate_policy="allow"),
            sampler_config=SamplerConfig(name="random"),
        )
        optimizer.optimize(param_ranges={"x": (0, 100, 1)})
        return seen

    assert run_once() == run_once()


def test_multiobjective_rejects_single_best_callback():
    optimizer = OptunaOptimizer(
        evaluator=MultiObjectiveEvaluator(),
        config=OptimizationConfig(
            study_name="bad_multi_early",
            n_trials=2,
            directions=("maximize", "minimize"),
            early_stopping_rounds=1,
            show_progress_bar=False,
        ),
        sampler_config=SamplerConfig(name="nsgaii", kwargs={"population_size": 4}),
    )

    with pytest.raises(ValueError, match="single-objective"):
        optimizer.optimize(param_ranges={"x": (0.0, 1.0, 0.5)})
