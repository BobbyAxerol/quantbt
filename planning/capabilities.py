"""Lazy native capability snapshots used by the planning resolver."""

from __future__ import annotations

from dataclasses import dataclass
import importlib
from typing import Mapping

from ..core.native_event_capabilities import (
    native_event_semantic_descriptor,
    semantic_descriptor_fingerprint,
)


@dataclass(frozen=True, slots=True)
class CapabilitySnapshot:
    available: bool
    compatible: bool
    executable: bool
    capabilities: tuple[tuple[str, bool], ...]
    semantic_descriptor: tuple[tuple[str, object], ...]
    fingerprint: str
    reason: str | None = None

    def supports(self, required: tuple[str, ...]) -> bool:
        values = dict(self.capabilities)
        return all(bool(values.get(name, False)) for name in required)


def python_capability_snapshot() -> CapabilitySnapshot:
    descriptor = native_event_semantic_descriptor()
    return CapabilitySnapshot(
        available=True,
        compatible=True,
        executable=True,
        capabilities=(),
        semantic_descriptor=tuple(sorted(descriptor.items())),
        fingerprint=semantic_descriptor_fingerprint(descriptor),
    )


def load_rust_capability_snapshot() -> CapabilitySnapshot:
    """Probe Rust only when explicit planning asks for it."""

    module = importlib.import_module("quantbt.backends._native_event_rust")
    status = module.probe_native_event_rust_extension()
    descriptor: Mapping[str, object] = status.semantic_descriptor
    fingerprint = (
        semantic_descriptor_fingerprint(descriptor)
        if descriptor
        else "unavailable"
    )
    return CapabilitySnapshot(
        available=bool(status.available),
        compatible=bool(status.compatible),
        executable=bool(status.executable),
        capabilities=tuple(sorted((str(key), bool(value)) for key, value in status.capabilities.items())),
        semantic_descriptor=tuple(sorted(descriptor.items())),
        fingerprint=fingerprint,
        reason=status.reason,
    )


__all__ = ["CapabilitySnapshot", "load_rust_capability_snapshot", "python_capability_snapshot"]
