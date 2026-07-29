"""Domain-specific optimization evaluators.

Phase 32A intentionally keeps this namespace empty except for package
discovery. Prepared signal/intrabar/portfolio and generic endpoint evaluators
are implemented in Phase 32B.
"""

__all__: list[str] = []
"""Domain evaluator adapters for QuantBT optimization."""

from .arbitrage import ArbitrageGenericEvaluator, ArbitrageTrialOutput
from .generic import GenericEndpointEvaluator
from .grid_dca import GridDCAGenericEvaluator, GridDCATrialOutput
from .intrabar import PreparedIntrabarEvaluator
from .native_event import PreparedNativeEventStrategyEvaluator
from .options import OptionPackageGenericEvaluator, OptionTrialOutput
from .portfolio import PreparedPortfolioEvaluator
from .signal import PreparedSignalEvaluator

__all__ = [
    "ArbitrageGenericEvaluator",
    "ArbitrageTrialOutput",
    "GenericEndpointEvaluator",
    "GridDCAGenericEvaluator",
    "GridDCATrialOutput",
    "OptionPackageGenericEvaluator",
    "OptionTrialOutput",
    "PreparedIntrabarEvaluator",
    "PreparedNativeEventStrategyEvaluator",
    "PreparedPortfolioEvaluator",
    "PreparedSignalEvaluator",
]
