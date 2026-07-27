from __future__ import annotations

import json
import optuna
import pytest

import quantbt.walkforward as walkforward_module
from quantbt import (
    CandidateSelector,
    GenericEndpointEvaluator,
    MissingOptimizationMetricError,
    ObjectiveResult,
    OptimizationConfig,
    OptunaOptimizer,
    ReportMetricObjective,
    SamplerConfig,
    SharpeObjective,
    constraints_feasible,
    max_turnover_constraint,
)
from quantbt.optimization.space import suggest_params


class Result:
    def __init__(self, value, report=None, metadata=None):
        self.value = float(value)
        self._report = report
        self.metadata = dict(metadata or {})

    def full_report(self, trading_days=365, scope="auto"):
        if self._report is not None:
            return dict(self._report)
        return {"sharpe": self.value, "max_drawdown_pct": abs(self.value), "num_trades": 1}


def test_optimizer_preserves_fixed_params_in_best_and_trial_records():
    evaluator = GenericEndpointEvaluator(
        build_run_inputs=lambda params: {"value": params["x"]},
        run_func=lambda value: Result(value),
        objective_builder=lambda result, params: ObjectiveResult.scalar(result.value, metrics={"x": result.value}),
    )
    optimizer = OptunaOptimizer(
        evaluator=evaluator,
        config=OptimizationConfig(study_name="fixed_params_integration", n_trials=4, seed=1, show_progress_bar=False),
        sampler_config=SamplerConfig(name="random"),
    )

    result = optimizer.optimize(param_ranges={"x": [1, 2, 3]}, fixed_params={"issl": True}, candidate_selector=CandidateSelector())

    assert result.best_params["issl"] is True
    assert result.selected_params["issl"] is True
    assert all(record.params.get("issl") is True for record in result.trials if record.state == "COMPLETE")


def test_walkforward_sampling_reuses_optimization_core_and_preserves_float_int_ranges():
    trial = optuna.trial.FixedTrial(
        {
            "window": 3,
            "threshold": 0.2,
            "flag": True,
            "mode": "fast",
        }
    )
    ranges = {
        "window": (1.0, 5.0, 1.0),
        "threshold": (0.1, 0.5, 0.1),
        "flag": [True, False],
        "mode": ["fast", "slow"],
        "constant": 7,
    }

    assert walkforward_module._sample_params(trial, ranges) == suggest_params(trial, ranges)


def test_constrained_optimization_and_feasible_candidate_selector():
    evaluator = GenericEndpointEvaluator(
        build_run_inputs=lambda params: {"value": float(params["x"])},
        run_func=lambda value: Result(value),
        objective_builder=lambda result, params: ObjectiveResult.scalar(
            result.value,
            metrics={"score": result.value},
            constraints=(result.value - 1.0,),
        ),
    )
    optimizer = OptunaOptimizer(
        evaluator=evaluator,
        config=OptimizationConfig(study_name="constraints_integration", n_trials=4, seed=2, show_progress_bar=False),
        sampler_config=SamplerConfig(name="grid", constraint_mode="post_filter"),
    )

    result = optimizer.optimize(param_ranges={"x": [0.0, 1.0, 2.0]}, candidate_selector=CandidateSelector("feasible_best"))

    assert result.selected_params["x"] == 1.0
    assert all(constraints_feasible(record.constraints) for record in result.trials if record.params.get("x") <= 1.0)
    assert any(not constraints_feasible(record.constraints) for record in result.trials if record.params.get("x") > 1.0)


def test_missing_objective_metric_raises():
    result = Result(1.0, report={"max_drawdown_pct": 1.0, "num_trades": 10})

    with pytest.raises(MissingOptimizationMetricError, match="sharpe"):
        SharpeObjective()(result, {})


def test_missing_constraint_metric_raises():
    result = Result(1.0, report={"sharpe": 1.0, "max_drawdown_pct": 1.0, "num_trades": 10})

    with pytest.raises(MissingOptimizationMetricError, match="turnover"):
        ReportMetricObjective(constraints=(max_turnover_constraint(1.0),))(result, {})


def test_turnover_does_not_fallback_to_trade_count():
    result = Result(1.0, report={"sharpe": 1.0, "max_drawdown_pct": 1.0, "num_trades": 99})

    with pytest.raises(MissingOptimizationMetricError, match="turnover"):
        ReportMetricObjective(value_metrics=("turnover",))(result, {})


def test_infeasible_highest_score_not_selected():
    evaluator = GenericEndpointEvaluator(
        build_run_inputs=lambda params: {"value": float(params["x"])},
        run_func=lambda value: Result(value),
        objective_builder=lambda result, params: ObjectiveResult.scalar(
            result.value,
            metrics={"score": result.value},
            constraints=(result.value - 1.0,),
        ),
    )
    optimizer = OptunaOptimizer(
        evaluator=evaluator,
        config=OptimizationConfig(study_name="infeasible_best", n_trials=3, seed=1, show_progress_bar=False),
        sampler_config=SamplerConfig(name="grid", constraint_mode="post_filter"),
    )

    raw = optimizer.optimize(param_ranges={"x": [0.0, 1.0, 2.0]})
    filtered = optimizer.optimize(param_ranges={"x": [0.0, 1.0, 2.0]}, candidate_selector=CandidateSelector("feasible_best"))

    assert raw.best_params["x"] == 2.0
    assert raw.selected_params is None
    assert filtered.selected_params["x"] == 1.0


def test_no_feasible_trial_returns_no_selected_params():
    evaluator = GenericEndpointEvaluator(
        build_run_inputs=lambda params: {"value": float(params["x"])},
        run_func=lambda value: Result(value),
        objective_builder=lambda result, params: ObjectiveResult.scalar(result.value, constraints=(1.0,)),
    )
    optimizer = OptunaOptimizer(
        evaluator=evaluator,
        config=OptimizationConfig(study_name="no_feasible", n_trials=2, seed=1, show_progress_bar=False),
        sampler_config=SamplerConfig(name="grid", constraint_mode="post_filter"),
    )

    result = optimizer.optimize(param_ranges={"x": [1.0, 2.0]})

    assert result.best_params["x"] == 2.0
    assert result.selected_params is None


def test_multi_objective_pareto_smoke_and_selector_policy():
    evaluator = GenericEndpointEvaluator(
        build_run_inputs=lambda params: {"x": float(params["x"])},
        run_func=lambda x: x,
        objective_builder=lambda result, params: ObjectiveResult(
            values=(float(result), abs(float(result) - 1.0)),
            metrics={"score": float(result), "risk": abs(float(result) - 1.0)},
        ),
    )
    optimizer = OptunaOptimizer(
        evaluator=evaluator,
        config=OptimizationConfig(
            study_name="pareto_integration",
            n_trials=4,
            directions=("maximize", "minimize"),
            seed=3,
            show_progress_bar=False,
            duplicate_policy="allow",
        ),
        sampler_config=SamplerConfig(name="nsgaii"),
    )

    result = optimizer.optimize(param_ranges={"x": [0.0, 1.0, 2.0]})

    assert result.best_params is None
    assert result.selected_params is None
    assert result.pareto_trials
    selected = CandidateSelector("pareto_first").select(result)
    assert "x" in selected.params


def test_pareto_selector_filters_infeasible_trials():
    evaluator = GenericEndpointEvaluator(
        build_run_inputs=lambda params: {"x": float(params["x"])},
        run_func=lambda x: x,
        objective_builder=lambda result, params: ObjectiveResult(
            values=(float(result), abs(float(result) - 1.0)),
            constraints=(float(result) - 1.0,),
            metrics={"score": float(result)},
        ),
    )
    optimizer = OptunaOptimizer(
        evaluator=evaluator,
        config=OptimizationConfig(
            study_name="pareto_feasible_filter",
            n_trials=3,
            directions=("maximize", "minimize"),
            show_progress_bar=False,
            duplicate_policy="allow",
        ),
        sampler_config=SamplerConfig(name="grid", constraint_mode="post_filter"),
    )

    result = optimizer.optimize(param_ranges={"x": [0.0, 1.0, 2.0]})
    selected = CandidateSelector("pareto_first").select(result)

    assert selected.params["x"] <= 1.0
    assert constraints_feasible(selected.constraints)


def test_unsupported_constraint_sampler_requires_post_filter():
    evaluator = GenericEndpointEvaluator(
        build_run_inputs=lambda params: {"value": float(params["x"])},
        run_func=lambda value: Result(value),
        objective_builder=lambda result, params: ObjectiveResult.scalar(result.value, constraints=(0.0,)),
    )
    optimizer = OptunaOptimizer(
        evaluator=evaluator,
        config=OptimizationConfig(study_name="unsupported_constraints", n_trials=1, show_progress_bar=False),
        sampler_config=SamplerConfig(name="random"),
    )

    with pytest.raises(ValueError, match="constraint_mode='post_filter'"):
        optimizer.optimize(param_ranges={"x": [1.0]})


def test_parallel_mode_rejected_until_thread_safe():
    optimizer = OptunaOptimizer(
        evaluator=GenericEndpointEvaluator(
            build_run_inputs=lambda params: {"value": params["x"]},
            run_func=lambda value: Result(value),
            objective_builder=lambda result, params: ObjectiveResult.scalar(result.value),
        ),
        config=OptimizationConfig(study_name="parallel_reject", n_trials=1, n_jobs=2, show_progress_bar=False),
        sampler_config=SamplerConfig(name="random"),
    )

    with pytest.raises(NotImplementedError, match="parallel optimization is not certified"):
        optimizer.optimize(param_ranges={"x": [1.0]})


def test_duplicate_detection_after_sqlite_resume(tmp_path):
    storage = f"sqlite:///{tmp_path / 'dup_resume.db'}"

    def make_optimizer():
        return OptunaOptimizer(
            evaluator=GenericEndpointEvaluator(
                build_run_inputs=lambda params: {"value": float(params["x"])},
                run_func=lambda value: Result(value),
                objective_builder=lambda result, params: ObjectiveResult.scalar(result.value),
            ),
            config=OptimizationConfig(
                study_name="dup_resume",
                n_trials=1,
                storage=storage,
                load_if_exists=True,
                show_progress_bar=False,
            ),
            sampler_config=SamplerConfig(name="random"),
        )

    first = make_optimizer().optimize(param_ranges={"x": [1.0]})
    second = make_optimizer().optimize(param_ranges={"x": [1.0]})

    assert [record.state for record in first.trials] == ["COMPLETE"]
    assert [record.state for record in second.trials][-1] == "PRUNED"


def test_repeated_optimize_does_not_reuse_stale_seen_set():
    optimizer = OptunaOptimizer(
        evaluator=GenericEndpointEvaluator(
            build_run_inputs=lambda params: {"value": float(params["x"])},
            run_func=lambda value: Result(value),
            objective_builder=lambda result, params: ObjectiveResult.scalar(result.value),
        ),
        config=OptimizationConfig(study_name="stale_seen", n_trials=1, show_progress_bar=False),
        sampler_config=SamplerConfig(name="random"),
    )

    first = optimizer.optimize(param_ranges={"x": [1.0]})
    second = optimizer.optimize(param_ranges={"x": [2.0]})

    assert first.trials[-1].state == "COMPLETE"
    assert second.trials[-1].state == "COMPLETE"


def test_jsonl_contains_fixed_and_search_params(tmp_path):
    log_path = tmp_path / "study.jsonl"
    optimizer = OptunaOptimizer(
        evaluator=GenericEndpointEvaluator(
            build_run_inputs=lambda params: {"value": float(params["x"])},
            run_func=lambda value: Result(value),
            objective_builder=lambda result, params: ObjectiveResult.scalar(result.value),
        ),
        config=OptimizationConfig(study_name="jsonl_full_params", n_trials=1, show_progress_bar=False, log_path=log_path),
        sampler_config=SamplerConfig(name="random"),
    )

    optimizer.optimize(param_ranges={"x": [1.0]}, fixed_params={"issl": True})
    row = json.loads(log_path.read_text().splitlines()[0])

    assert row["params"] == {"issl": True, "x": 1.0}


def test_custom_objective_can_raise_and_exception_policy_prunes():
    class BrokenObjective:
        def __call__(self, result, params):
            raise ValueError("bad score")

    evaluator = GenericEndpointEvaluator(
        build_run_inputs=lambda params: {"value": params["x"]},
        run_func=lambda value: Result(value),
        objective_builder=BrokenObjective(),
    )
    optimizer = OptunaOptimizer(
        evaluator=evaluator,
        config=OptimizationConfig(
            study_name="custom_objective_prune",
            n_trials=2,
            seed=1,
            show_progress_bar=False,
            exception_policy="prune",
        ),
        sampler_config=SamplerConfig(name="random"),
    )

    result = optimizer.optimize(param_ranges={"x": [1, 2]})

    assert all(record.state == "PRUNED" for record in result.trials)


def test_persistent_sqlite_resume_smoke(tmp_path):
    storage = f"sqlite:///{tmp_path / 'resume.db'}"

    def make_optimizer(n_trials):
        evaluator = GenericEndpointEvaluator(
            build_run_inputs=lambda params: {"value": float(params["x"])},
            run_func=lambda value: Result(value),
            objective_builder=lambda result, params: ObjectiveResult.scalar(result.value, metrics={"score": result.value}),
        )
        return OptunaOptimizer(
            evaluator=evaluator,
            config=OptimizationConfig(
                study_name="sqlite_resume",
                n_trials=n_trials,
                seed=11,
                show_progress_bar=False,
                storage=storage,
                load_if_exists=True,
                duplicate_policy="allow",
            ),
            sampler_config=SamplerConfig(name="random"),
        )

    first = make_optimizer(2).optimize(param_ranges={"x": [0.0, 1.0, 2.0]})
    second = make_optimizer(3).optimize(param_ranges={"x": [0.0, 1.0, 2.0]})

    assert len(first.trials) == 2
    assert len(second.trials) == 5
    assert second.best_params is not None
