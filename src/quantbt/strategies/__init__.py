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
from .native_ir import (
    NativeIRLimits,
    NativeIRReferenceTape,
    NativeStrategyIR,
    NativeStrategyKind,
    NativeStrategyParameters,
    STRATEGY_IR_PARAMETER_NAMES,
    STRATEGY_IR_VERSION,
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
    "NativeIRLimits",
    "NativeIRReferenceTape",
    "NativeStrategyIR",
    "NativeStrategyKind",
    "NativeStrategyParameters",
    "STRATEGY_IR_PARAMETER_NAMES",
    "STRATEGY_IR_VERSION",
    "resolve_strategy_requirements",
    "strategy_requirements",
]
