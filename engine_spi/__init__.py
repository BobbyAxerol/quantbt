"""Backend-neutral engine session protocol and registry."""

from .protocol import (
    BackendDescriptor,
    EngineBackend,
    EngineRunRequest,
    PreparedEngineSession,
    ResetRequest,
)
from .errors import (
    AuditMismatchError,
    CapabilityError,
    CommandValidationError,
    ConfigurationError,
    ContractMismatchError,
    EngineErrorCode,
    EngineErrorContext,
    ExecutionInvariantError,
    NativeProtocolError,
    PreparationError,
    QuantBTEngineError,
    ResourceLimitError,
    StrategyCallbackError,
)
from .registry import create_backend, registered_backends

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
    "BackendDescriptor",
    "EngineBackend",
    "EngineRunRequest",
    "PreparedEngineSession",
    "ResetRequest",
    "create_backend",
    "registered_backends",
]
