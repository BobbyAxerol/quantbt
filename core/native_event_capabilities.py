"""Canonical native-event capability contract.

The Rust extension exposes a low-level capability map whose names are tied to
its release history (for example ``rust_batched_tape``).  Public selectors,
tests, and documentation need a stable vocabulary instead. The versioned
product registry is the source of truth; this module exposes its generated
Python view for the currently certified single-symbol R2 surface.
Full-contract 0.4 flags are additive and only normalize to the wider vocabulary
when the extension advertises the complete capability gate.
"""

from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
from types import MappingProxyType
from typing import Mapping

from .event_contracts import NATIVE_EVENT_CONTRACT_FINGERPRINT
from .execution_trace import TRACE_SCHEMA_VERSION
from .generated_product_contracts import (
    NATIVE_EVENT_CAPABILITY_MATRIX_VERSION,
    NATIVE_EVENT_COMMAND_ABI_VERSION,
    NATIVE_EVENT_CAPABILITY_NORMALIZATION,
    NATIVE_EVENT_CORE_PROTOCOL_MAX,
    NATIVE_EVENT_CORE_PROTOCOL_MIN,
    NATIVE_EVENT_RUNTIME_DESCRIPTOR,
    NATIVE_EVENT_STABLE_CAPABILITIES,
    NATIVE_EVENT_TRACE_SCHEMA_VERSION,
)


if NATIVE_EVENT_TRACE_SCHEMA_VERSION != TRACE_SCHEMA_VERSION:
    raise RuntimeError("generated product registry trace schema differs from the execution trace schema")
if NATIVE_EVENT_CORE_PROTOCOL_MIN != NATIVE_EVENT_CORE_PROTOCOL_MAX:
    raise RuntimeError("the current Python adapter exposes exactly one native core protocol")


NATIVE_EVENT_CORE_PROTOCOL_VERSION = NATIVE_EVENT_CORE_PROTOCOL_MIN
NATIVE_EVENT_SEMANTIC_DESCRIPTOR_VERSION = str(NATIVE_EVENT_RUNTIME_DESCRIPTOR["descriptor_version"])
NATIVE_EVENT_CAPABILITY_MATRIX: Mapping[str, bool] = MappingProxyType(
    dict(NATIVE_EVENT_STABLE_CAPABILITIES)
)


def native_event_capability_matrix() -> dict[str, bool]:
    """Return a mutable copy of the canonical capability matrix."""

    return dict(NATIVE_EVENT_CAPABILITY_MATRIX)


def capability_matrix_fingerprint() -> str:
    """Return a reproducible SHA-256 fingerprint for the capability contract."""

    payload = {
        "version": NATIVE_EVENT_CAPABILITY_MATRIX_VERSION,
        "capabilities": dict(sorted(NATIVE_EVENT_CAPABILITY_MATRIX.items())),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return sha256(encoded).hexdigest()


def native_event_semantic_descriptor() -> dict[str, object]:
    """Return the structured execution semantics required from API 0.4 Rust."""

    descriptor = deepcopy(NATIVE_EVENT_RUNTIME_DESCRIPTOR)
    descriptor.update(
        {
            "core_protocol_min": NATIVE_EVENT_CORE_PROTOCOL_VERSION,
            "core_protocol_max": NATIVE_EVENT_CORE_PROTOCOL_VERSION,
            "contract_registry_fingerprint": NATIVE_EVENT_CONTRACT_FINGERPRINT,
            "trace_schema": TRACE_SCHEMA_VERSION,
            "command_abi": NATIVE_EVENT_COMMAND_ABI_VERSION,
        }
    )
    return descriptor


def semantic_descriptor_fingerprint(descriptor: Mapping[str, object] | None = None) -> str:
    payload = dict(descriptor or native_event_semantic_descriptor())
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return sha256(encoded).hexdigest()


def validate_native_event_semantic_descriptor(descriptor: Mapping[str, object]) -> None:
    """Fail before market preparation when the native semantic ABI drifts."""

    expected = native_event_semantic_descriptor()
    required_equal = (
        "descriptor_version", "native_api", "contract_registry_fingerprint",
        "trace_schema", "command_abi", "contracts", "orders", "account", "portfolio",
    )
    mismatches = [key for key in required_equal if descriptor.get(key) != expected[key]]
    protocol_min = int(descriptor.get("core_protocol_min", -1))
    protocol_max = int(descriptor.get("core_protocol_max", -1))
    if not protocol_min <= NATIVE_EVENT_CORE_PROTOCOL_VERSION <= protocol_max:
        mismatches.append("core_protocol_range")
    if mismatches:
        raise ValueError(f"native-event semantic descriptor mismatch: {sorted(set(mismatches))}")


def normalize_native_event_capabilities(raw: Mapping[str, object] | None) -> dict[str, bool]:
    """Map extension-specific flags into the stable public vocabulary.

    Unknown raw flags are intentionally ignored.  A raw flag cannot silently
    enable a capability that is outside the certified matrix; a later release
    must update this module and its tests first.
    """

    source = {str(key): bool(value) for key, value in (raw or {}).items()}
    return {
        stable_name: any(source.get(raw_name, False) for raw_name in raw_names)
        for stable_name, raw_names in NATIVE_EVENT_CAPABILITY_NORMALIZATION.items()
    }


def validate_native_event_capability_matrix(matrix: Mapping[str, object]) -> None:
    """Raise if a consumer attempts to advertise an unknown capability."""

    unknown = sorted(set(matrix) - set(NATIVE_EVENT_CAPABILITY_MATRIX))
    if unknown:
        raise ValueError(f"unknown native-event capability fields: {unknown}")


__all__ = [
    "NATIVE_EVENT_CAPABILITY_MATRIX_VERSION",
    "NATIVE_EVENT_COMMAND_ABI_VERSION",
    "NATIVE_EVENT_CORE_PROTOCOL_VERSION",
    "NATIVE_EVENT_SEMANTIC_DESCRIPTOR_VERSION",
    "NATIVE_EVENT_CAPABILITY_MATRIX",
    "capability_matrix_fingerprint",
    "native_event_capability_matrix",
    "native_event_semantic_descriptor",
    "normalize_native_event_capabilities",
    "validate_native_event_capability_matrix",
    "semantic_descriptor_fingerprint",
    "validate_native_event_semantic_descriptor",
]
