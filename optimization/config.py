"""Configuration objects for QuantBT domain-agnostic optimization."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional, Tuple, Union


Direction = str


@dataclass(frozen=True)
class OptimizationConfig:
    """Runtime configuration for :class:`OptunaOptimizer`.

    The config intentionally avoids strategy/domain fields. Domain-specific
    data, endpoints, prepared runners, and metric extraction belong in
    evaluator adapters.
    """

    study_name: str
    n_trials: int = 300
    directions: Tuple[Direction, ...] = ("maximize",)
    seed: Optional[int] = 42
    n_jobs: int = 1
    early_stopping_rounds: Optional[int] = None
    early_stopping_min_delta: float = 1e-4
    show_progress_bar: bool = True
    storage: Optional[str] = None
    load_if_exists: bool = True
    log_path: Optional[Union[str, Path]] = None
    duplicate_policy: str = "prune"
    exception_policy: str = "raise"

    def __post_init__(self) -> None:
        if not str(self.study_name).strip():
            raise ValueError("study_name must be non-empty")
        if self.n_trials <= 0:
            raise ValueError("n_trials must be positive")
        if not self.directions:
            raise ValueError("at least one direction is required")
        directions = tuple(str(direction).lower().strip() for direction in self.directions)
        invalid = set(directions) - {"maximize", "minimize"}
        if invalid:
            raise ValueError(f"invalid directions: {invalid}")
        object.__setattr__(self, "directions", directions)
        if self.n_jobs <= 0:
            raise ValueError("n_jobs must be positive")
        if self.early_stopping_rounds is not None and self.early_stopping_rounds <= 0:
            raise ValueError("early_stopping_rounds must be positive when provided")
        if self.early_stopping_min_delta < 0.0:
            raise ValueError("early_stopping_min_delta must be >= 0")
        duplicate_policy = str(self.duplicate_policy).lower().strip()
        if duplicate_policy not in {"allow", "prune", "raise"}:
            raise ValueError("duplicate_policy must be allow, prune, or raise")
        object.__setattr__(self, "duplicate_policy", duplicate_policy)
        exception_policy = str(self.exception_policy).lower().strip()
        if exception_policy not in {"raise", "fail_trial", "prune"}:
            raise ValueError("exception_policy must be raise, fail_trial, or prune")
        object.__setattr__(self, "exception_policy", exception_policy)


@dataclass(frozen=True)
class SamplerConfig:
    """Optuna sampler selection and sampler-specific kwargs."""

    name: str = "tpe"
    kwargs: dict[str, Any] = field(default_factory=dict)
    constraint_mode: str = "sampler"

    def __post_init__(self) -> None:
        name = str(self.name).lower().strip()
        if not name:
            raise ValueError("sampler name must be non-empty")
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "kwargs", dict(self.kwargs or {}))
        constraint_mode = str(self.constraint_mode).lower().strip()
        if constraint_mode not in {"sampler", "post_filter"}:
            raise ValueError("constraint_mode must be sampler or post_filter")
        object.__setattr__(self, "constraint_mode", constraint_mode)
