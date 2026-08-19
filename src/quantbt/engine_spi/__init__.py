"""Backend-neutral engine session protocol and registry."""

from .protocol import (
    BackendDescriptor,
    EngineBackend,
    EngineRunRequest,
    PreparedEngineSession,
    ResetRequest,
)
from .registry import create_backend, registered_backends

__all__ = [
    "BackendDescriptor",
    "EngineBackend",
    "EngineRunRequest",
    "PreparedEngineSession",
    "ResetRequest",
    "create_backend",
    "registered_backends",
]
