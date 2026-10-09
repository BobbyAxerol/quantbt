"""Opt-in research analysis; no endpoint, selector or simulation activation."""

from .contracts import MetricValue, StatisticsPolicy
from .moments import MomentEstimate, classical_psr, moments, sharpe_to_period
from .dependence import HACPolicy, sharpe_hac
from .tails import FrozenReference, expected_shortfall, lower_tail, regret, weighted_mad, weighted_median

__all__ = ["MetricValue", "StatisticsPolicy", "MomentEstimate", "classical_psr", "moments",
           "sharpe_to_period", "HACPolicy", "sharpe_hac", "FrozenReference", "expected_shortfall",
           "lower_tail", "regret", "weighted_mad", "weighted_median"]
