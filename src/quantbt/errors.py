"""Structured public errors shared across planning and engine backends."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class EngineErrorCode(str, Enum):
    CONFIGURATION = "configuration"
    CAPABILITY = "capability"
    CONTRACT_MISMATCH = "contract_mismatch"
    PREPARATION = "preparation"
    COMMAND_VALIDATION = "command_validation"
    EXECUTION_INVARIANT = "execution_invariant"
    STRATEGY_CALLBACK = "strategy_callback"
    NATIVE_PROTOCOL = "native_protocol"
    RESOURCE_LIMIT = "resource_limit"
    AUDIT_MISMATCH = "audit_mismatch"


@dataclass(frozen=True, slots=True)
class EngineErrorContext:
    code: EngineErrorCode
    phase: str
    bar_index: int | None = None
    timestamp_ns: int | None = None
    symbol_id: int | None = None
    order_handle: int | None = None
    strategy_id: str | None = None
    detail_code: int = 0


class QuantBTEngineError(RuntimeError):
    error_code = EngineErrorCode.EXECUTION_INVARIANT

    def __init__(self, message: str, *, context: EngineErrorContext | None = None):
        self.context = context or EngineErrorContext(self.error_code, "unknown")
        super().__init__(message)


def _error(name: str, code: EngineErrorCode):
    return type(name, (QuantBTEngineError,), {"error_code": code})


ConfigurationError = _error("ConfigurationError", EngineErrorCode.CONFIGURATION)
CapabilityError = _error("CapabilityError", EngineErrorCode.CAPABILITY)
ContractMismatchError = _error("ContractMismatchError", EngineErrorCode.CONTRACT_MISMATCH)
PreparationError = _error("PreparationError", EngineErrorCode.PREPARATION)
CommandValidationError = _error("CommandValidationError", EngineErrorCode.COMMAND_VALIDATION)
ExecutionInvariantError = _error("ExecutionInvariantError", EngineErrorCode.EXECUTION_INVARIANT)
StrategyCallbackError = _error("StrategyCallbackError", EngineErrorCode.STRATEGY_CALLBACK)
NativeProtocolError = _error("NativeProtocolError", EngineErrorCode.NATIVE_PROTOCOL)
ResourceLimitError = _error("ResourceLimitError", EngineErrorCode.RESOURCE_LIMIT)
AuditMismatchError = _error("AuditMismatchError", EngineErrorCode.AUDIT_MISMATCH)


__all__ = [
    "AuditMismatchError",
    "CapabilityError",
    "CommandValidationError",
    "ConfigurationError",
    "ContractMismatchError",
    "EngineErrorCode",
    "EngineErrorContext",
    "ExecutionInvariantError",
    "NativeProtocolError",
    "PreparationError",
    "QuantBTEngineError",
    "ResourceLimitError",
    "StrategyCallbackError",
]
