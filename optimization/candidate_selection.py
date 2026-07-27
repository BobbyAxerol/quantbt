"""Candidate selection helpers for optimization results."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from .result import OptimizationResult, OptimizationTrialRecord


def constraints_feasible(constraints: tuple[float, ...]) -> bool:
    """Return True when all Optuna formal constraints are feasible."""

    return all(float(value) <= 0.0 for value in constraints)


@dataclass(frozen=True)
class SelectedCandidate:
    """Selected production candidate after feasibility/robustness filtering."""

    params: dict[str, Any]
    values: tuple[float, ...] = ()
    metrics: dict[str, float] = field(default_factory=dict)
    constraints: tuple[float, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CandidateSelector:
    """Small public selector interface.

    This is intentionally conservative. Robust WFO plateau selectors can plug
    into this interface later; Phase 32B provides best/feasible/Pareto policies
    so Optuna's best trial is not silently treated as production params.
    """

    mode: str = "feasible_best"
    objective_index: int = 0

    def select(self, result: OptimizationResult) -> SelectedCandidate:
        mode = str(self.mode).lower().strip()
        if mode in {"best", "single_best"}:
            return self._single_best(result, require_feasible=False)
        if mode in {"feasible_best", "best_feasible"}:
            return self._single_best(result, require_feasible=True)
        if mode in {"pareto_first", "first_pareto"}:
            return self._pareto_first(result)
        raise ValueError(f"unsupported candidate selector mode={self.mode!r}")

    def _single_best(self, result: OptimizationResult, *, require_feasible: bool) -> SelectedCandidate:
        direction = _direction(result, int(self.objective_index))
        completed = [record for record in result.trials if record.state == "COMPLETE" and len(record.values) > int(self.objective_index)]
        if require_feasible:
            completed = [record for record in completed if constraints_feasible(record.constraints)]
        if not completed:
            raise ValueError("no completed feasible optimization trials")
        reverse = direction == "maximize"
        best = sorted(completed, key=lambda record: record.values[int(self.objective_index)], reverse=reverse)[0]
        return _selected_from_record(
            best,
            metadata={
                "selector": self.mode,
                "objective_index": int(self.objective_index),
                "feasibility_filter": bool(require_feasible),
            },
        )

    def _pareto_first(self, result: OptimizationResult) -> SelectedCandidate:
        if not result.pareto_trials:
            raise ValueError("optimization result has no Pareto trials")
        trial = result.pareto_trials[0]
        params = dict(trial.user_attrs.get("quantbt_full_params", trial.params))
        return SelectedCandidate(
            params=params,
            values=tuple(float(value) for value in (trial.values or ())),
            metrics=dict(trial.user_attrs.get("quantbt_metrics", {})),
            constraints=tuple(float(value) for value in trial.user_attrs.get("quantbt_constraints", ())),
            metadata={
                "selector": self.mode,
                "trial_number": int(trial.number),
                "pareto_count": int(len(result.pareto_trials)),
            },
        )


def _selected_from_record(record: OptimizationTrialRecord, *, metadata: Optional[dict[str, Any]] = None) -> SelectedCandidate:
    merged_metadata = dict(record.metadata)
    merged_metadata.update(metadata or {})
    merged_metadata["trial_number"] = int(record.number)
    return SelectedCandidate(
        params=dict(record.params),
        values=tuple(record.values),
        metrics=dict(record.metrics),
        constraints=tuple(record.constraints),
        metadata=merged_metadata,
    )


def _direction(result: OptimizationResult, objective_index: int) -> str:
    try:
        directions = tuple(str(direction.name).lower() for direction in result.study.directions)
    except Exception:
        directions = ("maximize",)
    if objective_index < 0 or objective_index >= len(directions):
        raise ValueError("objective_index out of range for optimization directions")
    return directions[objective_index]
