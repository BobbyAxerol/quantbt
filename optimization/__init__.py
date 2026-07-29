"""Domain-agnostic optimization API for QuantBT."""

from .callbacks import JsonlOptimizationLogger, SingleObjectiveEarlyStopping
from .candidate_selection import CandidateSelector, RobustSelectionConfig, SelectedCandidate, constraints_feasible
from .config import OptimizationConfig, SamplerConfig
from .constraints import CONSTRAINTS_USER_ATTR, constraints_from_trial, set_trial_constraints
from .evaluator import TrialEvaluator
from .evaluators import (
    ArbitrageGenericEvaluator,
    ArbitrageTrialOutput,
    GenericEndpointEvaluator,
    GridDCAGenericEvaluator,
    GridDCATrialOutput,
    OptionPackageGenericEvaluator,
    OptionTrialOutput,
    PreparedIntrabarEvaluator,
    PreparedNativeEventStrategyEvaluator,
    PreparedPortfolioEvaluator,
    PreparedSignalEvaluator,
)
from .objectives import (
    MissingOptimizationMetricError,
    ReportMetricObjective,
    SharpeObjective,
    max_drawdown_constraint,
    max_margin_utilization_constraint,
    max_rejection_rate_constraint,
    max_turnover_constraint,
    metric_from_result,
    metrics_from_result,
    min_trades_constraint,
    result_full_report,
)
from .optimizer import OptunaOptimizer
from .multiseed import MultiSeedOptimization
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
    "ArbitrageGenericEvaluator",
    "ArbitrageTrialOutput",
    "CandidateSelector",
    "GenericEndpointEvaluator",
    "GridDCAGenericEvaluator",
    "GridDCATrialOutput",
    "JsonlOptimizationLogger",
    "MissingOptimizationMetricError",
    "MultiSeedOptimization",
    "ObjectiveResult",
    "OptionPackageGenericEvaluator",
    "OptionTrialOutput",
    "OptimizationConfig",
    "OptimizationResult",
    "OptimizationTrialRecord",
    "OptunaOptimizer",
    "PreparedIntrabarEvaluator",
    "PreparedNativeEventStrategyEvaluator",
    "PreparedPortfolioEvaluator",
    "PreparedSignalEvaluator",
    "ReportMetricObjective",
    "RobustSelectionConfig",
    "SamplerConfig",
    "SearchSpaceInfo",
    "SelectedCandidate",
    "SharpeObjective",
    "SingleObjectiveEarlyStopping",
    "TrialEvaluator",
    "build_grid_search_space",
    "build_sampler",
    "constraints_feasible",
    "constraints_from_trial",
    "max_drawdown_constraint",
    "max_margin_utilization_constraint",
    "max_rejection_rate_constraint",
    "max_turnover_constraint",
    "metric_from_result",
    "metrics_from_result",
    "min_trades_constraint",
    "search_space_info",
    "set_trial_constraints",
    "stable_params_key",
    "suggest_parameter",
    "suggest_params",
    "result_full_report",
]
