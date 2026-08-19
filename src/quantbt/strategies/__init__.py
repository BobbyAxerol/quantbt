"""Strategy-boundary contracts for event-driven execution."""

from .commands import CommandBatchView, CommandWriter
from .context import MaterializedStrategyContext, StaleStrategyContextError, StrategyContextView
from .driver import PreparedStrategyAdapter
from .requirements import (
    CallbackSchedule,
    StrategyContextRequirements,
    resolve_strategy_requirements,
    strategy_requirements,
)

__all__ = [
    "CallbackSchedule",
    "CommandBatchView",
    "CommandWriter",
    "MaterializedStrategyContext",
    "PreparedStrategyAdapter",
    "StaleStrategyContextError",
    "StrategyContextRequirements",
    "StrategyContextView",
    "resolve_strategy_requirements",
    "strategy_requirements",
]
