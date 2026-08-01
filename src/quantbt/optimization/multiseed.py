"""Multi-seed optimization orchestration."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Callable, Mapping, Optional, Sequence

from .candidate_selection import CandidateSelector, RobustSelectionConfig
from .config import OptimizationConfig, SamplerConfig
from .evaluator import TrialEvaluator
from .optimizer import OptunaOptimizer, _apply_baseline_floor, _is_better
from .result import OptimizationResult, OptimizationTrialRecord


@dataclass(frozen=True)
class MultiSeedOptimization:
    """Run the same search across several sampler seeds and aggregate trials.

    This is a search-quality tool, not a different objective. Each seed still
    optimizes the same evaluator; the aggregate result then selects production
    params from regions that survive multiple random trajectories.
    """

    evaluator: TrialEvaluator
    config: OptimizationConfig
    sampler_config: SamplerConfig = field(default_factory=SamplerConfig)
    seeds: Sequence[Optional[int]] = (None, 41, 42, 43, 44)
    trials_per_seed: Optional[int] = None

    def optimize(
        self,
        *,
        param_ranges: Mapping[str, Any],
        fixed_params: Optional[Mapping[str, Any]] = None,
        initial_trials: Optional[Sequence[Mapping[str, Any]]] = None,
        effective_params_builder: Optional[Callable[[Mapping[str, Any]], Mapping[str, Any]]] = None,
        candidate_selector: Optional[CandidateSelector] = None,
    ) -> OptimizationResult:
        if not self.seeds:
            raise ValueError("MultiSeedOptimization.seeds must be non-empty")

        seed_results: list[OptimizationResult] = []
        combined_trials: list[OptimizationTrialRecord] = []
        seed_summaries: list[dict[str, Any]] = []
        global_number = 0
        for seed_index, seed in enumerate(self.seeds):
            seed_label = "none" if seed is None else str(seed)
            config = replace(
                self.config,
                seed=seed,
                n_trials=int(self.trials_per_seed or self.config.n_trials),
                study_name=f"{self.config.study_name}_seed_{seed_label}",
            )
            result = OptunaOptimizer(
                evaluator=self.evaluator,
                config=config,
                sampler_config=self.sampler_config,
            ).optimize(
                param_ranges=param_ranges,
                fixed_params=fixed_params,
                initial_trials=initial_trials,
                effective_params_builder=effective_params_builder,
            )
            seed_results.append(result)
            seed_summaries.append(_seed_summary(result, seed=seed, seed_index=seed_index))
            for record in result.trials:
                metadata = dict(record.metadata)
                metadata.update(
                    {
                        "quantbt_seed": seed_label,
                        "quantbt_seed_index": int(seed_index),
                        "quantbt_original_trial_number": int(record.number),
                    }
                )
                combined_trials.append(
                    OptimizationTrialRecord(
                        number=int(global_number),
                        state=str(record.state),
                        params=dict(record.params),
                        values=tuple(record.values),
                        metrics=dict(record.metrics),
                        constraints=tuple(record.constraints),
                        metadata=metadata,
                    )
                )
                global_number += 1

        study_view = _StudyDirectionsView(seed_results[0].study.directions)
        aggregate = OptimizationResult(
            study=study_view,
            best_params=None,
            best_values=None,
            pareto_trials=[],
            trials=combined_trials,
            trials_frame=None,
        )
        aggregate.baseline_trials = [
            record
            for record in combined_trials
            if record.metadata.get("quantbt_source") == "warm_start"
        ]
        aggregate.seed_results = seed_summaries
        _set_best_from_trials(aggregate)

        selector = candidate_selector or CandidateSelector(
            mode="robust_plateau",
            config=RobustSelectionConfig(seed_consensus=min(2, len(self.seeds))),
        )
        selected = selector.select(aggregate)
        aggregate.selected_params = dict(selected.params)
        aggregate.selection_metadata = dict(selected.metadata)
        aggregate.selection_metadata.update(
            {
                "selected_by_multiseed": True,
                "seed_count": int(len(self.seeds)),
            }
        )
        aggregate.search_diagnostics = {
            "seed_count": int(len(self.seeds)),
            "seed_results": seed_summaries,
            "completed_trials": int(sum(1 for record in combined_trials if record.state == "COMPLETE")),
            "pruned_trials": int(sum(1 for record in combined_trials if record.state == "PRUNED")),
            "failed_trials": int(sum(1 for record in combined_trials if record.state == "FAIL")),
            "top_parameter_frequency": _top_parameter_frequency(combined_trials),
        }
        _apply_baseline_floor(aggregate)
        return aggregate


def _set_best_from_trials(result: OptimizationResult) -> None:
    try:
        direction = str(result.study.directions[0].name).lower()
    except Exception:
        direction = "maximize"
    completed = [record for record in result.trials if record.state == "COMPLETE" and record.values]
    if not completed:
        return
    best = completed[0]
    for record in completed[1:]:
        if _is_better(record.values[0], best.values[0], direction):
            best = record
    result.best_params = dict(best.params)
    result.best_values = tuple(best.values)


def _seed_summary(result: OptimizationResult, *, seed: Optional[int], seed_index: int) -> dict[str, Any]:
    return {
        "seed": None if seed is None else int(seed),
        "seed_index": int(seed_index),
        "best_params": None if result.best_params is None else dict(result.best_params),
        "best_values": None if result.best_values is None else tuple(float(value) for value in result.best_values),
        "selected_params": None if result.selected_params is None else dict(result.selected_params),
        "search_regression": bool(result.search_regression),
        "baseline_rank": list(result.search_diagnostics.get("baseline_rank", [])),
        "completed_trials": int(result.search_diagnostics.get("completed_trials", 0)),
    }


def _top_parameter_frequency(records: Sequence[OptimizationTrialRecord]) -> dict[str, dict[str, int]]:
    completed = [record for record in records if record.state == "COMPLETE" and record.values]
    if not completed:
        return {}
    ranked = sorted(completed, key=lambda record: record.values[0], reverse=True)
    top_n = max(1, len(ranked) // 10)
    counts: dict[str, dict[str, int]] = {}
    for record in ranked[:top_n]:
        for name, value in record.params.items():
            bucket = counts.setdefault(str(name), {})
            label = str(value)
            bucket[label] = bucket.get(label, 0) + 1
    return counts


class _StudyDirectionsView:
    def __init__(self, directions: Sequence[Any]):
        self.directions = tuple(directions)
