"""Research-only matched comparisons; not an execution or calibration owner."""

from .contracts import ComparisonScope, HypothesisLedger, SupportPolicy
from .comparisons import compare_selectors, fixed_panel_leave_out, same_front
from .transfer import RiskCalibration, paired_transfer

__all__ = ["ComparisonScope", "HypothesisLedger", "SupportPolicy", "compare_selectors",
           "fixed_panel_leave_out", "same_front", "RiskCalibration", "paired_transfer"]
