import pytest

from quantbt.optimization import (
    CandidateSelector,
    MultiSeedOptimization,
    ObjectiveResult,
    OptimizationConfig,
    OptimizationResult,
    OptimizationTrialRecord,
    OptunaOptimizer,
    RobustSelectionConfig,
    SamplerConfig,
)


class _Direction:
    name = "MAXIMIZE"


class _Study:
    directions = (_Direction(),)


def _trial(number, x, value, *, metrics=None, constraints=(), state="COMPLETE", seed=None):
    metadata = {}
    if seed is not None:
        metadata["quantbt_seed"] = seed
    return OptimizationTrialRecord(
        number=number,
        state=state,
        params={"x": x},
        values=(float(value),) if state == "COMPLETE" else (),
        metrics=dict(metrics or {"num_trades": 200, "max_drawdown_pct": 8.0}),
        constraints=tuple(constraints),
        metadata=metadata,
    )


def _result(records):
    return OptimizationResult(
        study=_Study(),
        best_params=dict(records[0].params),
        best_values=tuple(records[0].values),
        pareto_trials=[],
        trials=list(records),
        trials_frame=None,
    )


def test_robust_plateau_selector_avoids_isolated_spike():
    result = _result(
        [
            _trial(0, 100.0, 10.0, seed=1),
            _trial(1, -0.02, 8.00, seed=1),
            _trial(2, 0.00, 7.95, seed=2),
            _trial(3, 0.02, 7.90, seed=3),
            _trial(4, 0.05, 7.85, seed=4),
        ]
    )

    selected = CandidateSelector(
        mode="robust_plateau",
        config=RobustSelectionConfig(
            top_quantile=1.0,
            neighborhood_radius=0.05,
            min_neighbor_count=3,
            seed_consensus=2,
            instability_penalty=0.5,
            worst_weight=0.2,
        ),
    ).select(result)

    assert abs(float(selected.params["x"])) < 0.06
    assert selected.metadata["selected_by"] == "robust_plateau"
    assert selected.metadata["neighbor_count"] >= 3
    assert selected.metadata["seed_consensus_count"] >= 2
    assert result.robust_candidates[0]["params"]["x"] != 100.0


def test_robust_plateau_selector_respects_constraints_and_metric_filters():
    result = _result(
        [
            _trial(0, 1.0, 12.0, metrics={"num_trades": 20, "max_drawdown_pct": 4.0}),
            _trial(1, 2.0, 11.0, metrics={"num_trades": 200, "max_drawdown_pct": 40.0}),
            _trial(2, 3.0, 10.0, constraints=(1.0,), metrics={"num_trades": 200, "max_drawdown_pct": 4.0}),
            _trial(3, 4.0, 8.0, metrics={"num_trades": 200, "max_drawdown_pct": 4.0}),
            _trial(4, 4.1, 7.9, metrics={"num_trades": 210, "max_drawdown_pct": 4.1}),
            _trial(5, 4.2, 7.8, metrics={"num_trades": 220, "max_drawdown_pct": 4.2}),
        ]
    )

    selected = CandidateSelector(
        mode="robust_plateau",
        config=RobustSelectionConfig(
            top_quantile=1.0,
            min_trades=100,
            max_drawdown_pct=10.0,
            neighborhood_radius=0.04,
            min_neighbor_count=3,
        ),
    ).select(result)

    assert selected.params["x"] in {4.0, 4.1, 4.2}
    assert selected.metrics["num_trades"] >= 100
    assert selected.metrics["max_drawdown_pct"] <= 10.0
    assert selected.metadata["feasible_trials"] == 3


def test_robust_plateau_selector_raises_when_no_feasible_trials():
    result = _result([_trial(0, 1.0, 1.0, constraints=(1.0,))])

    with pytest.raises(ValueError, match="no completed feasible"):
        CandidateSelector(mode="robust_plateau").select(result)


class PlateauEvaluator:
    def evaluate(self, params):
        x = float(params["x"])
        if x == 10:
            score = 10.0
        elif x in {1.0, 2.0, 3.0}:
            score = 8.0 - abs(x - 2.0) * 0.05
        else:
            score = 4.0
        return ObjectiveResult.scalar(
            score,
            metrics={"num_trades": 200 + x, "max_drawdown_pct": 5.0 + abs(x - 2.0)},
        )


def test_multi_seed_optimization_selects_consensus_plateau():
    optimizer = MultiSeedOptimization(
        evaluator=PlateauEvaluator(),
        config=OptimizationConfig(
            study_name="phase33b_multiseed",
            n_trials=4,
            seed=None,
            show_progress_bar=False,
            duplicate_policy="allow",
        ),
        sampler_config=SamplerConfig(name="random"),
        seeds=(11, 22),
        trials_per_seed=4,
    )

    result = optimizer.optimize(
        param_ranges={"x": [1, 2, 3, 4, 10]},
        initial_trials=[{"x": 1}, {"x": 2}, {"x": 3}, {"x": 4}],
        candidate_selector=CandidateSelector(
            mode="robust_plateau",
            config=RobustSelectionConfig(
                top_quantile=1.0,
                neighborhood_radius=0.12,
                min_neighbor_count=3,
                seed_consensus=2,
            ),
        ),
    )

    assert result.selected_params is not None
    assert result.selected_params["x"] in {1, 2, 3}
    assert result.selection_metadata["selected_by_multiseed"] is True
    assert result.selection_metadata["seed_consensus_count"] == 2
    assert len(result.seed_results) == 2
    assert {record.metadata["quantbt_seed"] for record in result.trials if record.state == "COMPLETE"} == {"11", "22"}


def test_robust_selection_cannot_replace_better_warm_start_baseline():
    result = OptunaOptimizer(
        evaluator=PlateauEvaluator(),
        config=OptimizationConfig(
            study_name="phase33b_baseline_floor",
            n_trials=4,
            seed=1,
            show_progress_bar=False,
            duplicate_policy="allow",
        ),
        sampler_config=SamplerConfig(name="random"),
    ).optimize(
        param_ranges={"x": [1, 2, 3, 10]},
        initial_trials=[{"x": 10}, {"x": 1}, {"x": 2}, {"x": 3}],
        candidate_selector=CandidateSelector(
            mode="robust_plateau",
            config=RobustSelectionConfig(
                top_quantile=1.0,
                neighborhood_radius=0.12,
                min_neighbor_count=3,
            ),
        ),
    )

    assert result.selected_params == {"x": 10}
    assert result.search_regression is True
    assert result.selection_metadata["selected_by"] == "warm_start_baseline_floor"
