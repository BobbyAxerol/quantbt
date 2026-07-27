"""Domain-agnostic optimization API for QuantBT."""

from .callbacks import JsonlOptimizationLogger, SingleObjectiveEarlyStopping
from .config import OptimizationConfig, SamplerConfig
from .constraints import CONSTRAINTS_USER_ATTR, constraints_from_trial, set_trial_constraints
from .evaluator import TrialEvaluator
from .optimizer import OptunaOptimizer
from .result import ObjectiveResult, OptimizationResult, OptimizationTrialRecord
from .samplers import build_sampler
from .space import (
    SearchSpaceInfo,
    build_grid_search_space,
    search_space_info,
    stable_params_key,
    suggest_parameter,
    suggest_params,
)

__all__ = [
    "CONSTRAINTS_USER_ATTR",
    "JsonlOptimizationLogger",
    "ObjectiveResult",
    "OptimizationConfig",
    "OptimizationResult",
    "OptimizationTrialRecord",
    "OptunaOptimizer",
    "SamplerConfig",
    "SearchSpaceInfo",
    "SingleObjectiveEarlyStopping",
    "TrialEvaluator",
    "build_grid_search_space",
    "build_sampler",
    "constraints_from_trial",
    "search_space_info",
    "set_trial_constraints",
    "stable_params_key",
    "suggest_parameter",
    "suggest_params",
]
