"""Result schemas for QuantBT optimization."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional, Sequence, Tuple


@dataclass(frozen=True)
class ObjectiveResult:
    """Evaluator output consumed by the domain-agnostic optimizer.

    `values` follows Optuna conventions: one value for single-objective
    optimization and one value per configured direction for multi-objective
    optimization. Formal constraints use Optuna's sign convention:
    `<= 0` means feasible and `> 0` means violated.
    """

    values: Tuple[float, ...]
    metrics: dict[str, float] = field(default_factory=dict)
    constraints: Tuple[float, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        values = tuple(float(value) for value in self.values)
        if not values:
            raise ValueError("ObjectiveResult.values must be non-empty")
        constraints = tuple(float(value) for value in self.constraints)
        metrics = {str(key): float(value) for key, value in dict(self.metrics or {}).items()}
        object.__setattr__(self, "values", values)
        object.__setattr__(self, "constraints", constraints)
        object.__setattr__(self, "metrics", metrics)
        object.__setattr__(self, "metadata", dict(self.metadata or {}))

    @classmethod
    def scalar(
        cls,
        value: float,
        *,
        metrics: Optional[dict[str, float]] = None,
        constraints: Sequence[float] = (),
        metadata: Optional[dict[str, Any]] = None,
    ) -> "ObjectiveResult":
        """Build a single-objective result."""

        return cls(values=(float(value),), metrics=dict(metrics or {}), constraints=tuple(constraints), metadata=dict(metadata or {}))


@dataclass(frozen=True)
class OptimizationTrialRecord:
    """Compact, serializable record of one completed/pruned/failed trial."""

    number: int
    state: str
    params: dict[str, Any]
    values: Tuple[float, ...] = ()
    metrics: dict[str, float] = field(default_factory=dict)
    constraints: Tuple[float, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class OptimizationResult:
    """Public result returned by :class:`OptunaOptimizer`."""

    study: Any
    best_params: Optional[dict[str, Any]]
    best_values: Optional[Tuple[float, ...]]
    pareto_trials: list[Any]
    trials: list[OptimizationTrialRecord]
    trials_frame: Any
    selected_params: Optional[dict[str, Any]] = None
    selection_metadata: dict[str, Any] = field(default_factory=dict)
    baseline_trials: list[OptimizationTrialRecord] = field(default_factory=list)
    phase_results: list[Any] = field(default_factory=list)
    seed_results: list[Any] = field(default_factory=list)
    robust_candidates: list[Any] = field(default_factory=list)
    selected_validation: dict[str, Any] = field(default_factory=dict)
    search_regression: bool = False
    search_diagnostics: dict[str, Any] = field(default_factory=dict)
