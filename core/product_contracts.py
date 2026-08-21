"""Release-level native product contract helpers.

This module deliberately has no execution dependency.  It is the common
validator used by staged wheel tests and future runtime handshakes to prove
that a core/native pair is listed in the generated product registry.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Mapping

from .generated_product_contracts import (
    NATIVE_EVENT_COMMAND_ABI_VERSION,
    NATIVE_EVENT_COMPATIBILITY_MATRIX,
    NATIVE_EVENT_CORE_PACKAGE_VERSION,
    NATIVE_EVENT_CORE_PROTOCOL_MAX,
    NATIVE_EVENT_CORE_PROTOCOL_MIN,
    NATIVE_EVENT_DEPRECATION_MATRIX,
    NATIVE_EVENT_LIFECYCLE_REGISTRY_FINGERPRINT,
    NATIVE_EVENT_NATIVE_PACKAGE_VERSION,
    NATIVE_EVENT_PRODUCT_REGISTRY,
    NATIVE_EVENT_RESULT_ABI_VERSION,
    NATIVE_EVENT_STRATEGY_IR_VERSION,
    NATIVE_EVENT_TRACE_SCHEMA_VERSION,
    PRODUCT_CONTRACT_REGISTRY_FINGERPRINT,
    WORKLOAD_CAPABILITY_DESCRIPTORS,
)


class NativePackageCompatibilityError(RuntimeError):
    """Raised when a core/native wheel pair is not declared as compatible."""


@dataclass(frozen=True, slots=True)
class NativePackagePair:
    """One declared core/native compatibility record."""

    core_version: str
    native_version: str
    native_protocol_min: int
    native_protocol_max: int
    command_abis: tuple[str, ...]
    result_abis: tuple[str, ...]
    status: str
    fallback: str

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> "NativePackagePair":
        return cls(
            core_version=str(value["core_version"]),
            native_version=str(value["native_version"]),
            native_protocol_min=int(value["native_protocol_min"]),
            native_protocol_max=int(value["native_protocol_max"]),
            command_abis=tuple(str(item) for item in value["command_abis"]),
            result_abis=tuple(str(item) for item in value["result_abis"]),
            status=str(value["status"]),
            fallback=str(value["fallback"]),
        )


def native_product_registry() -> dict[str, object]:
    """Return a defensive copy of the generated product-level registry."""

    return deepcopy(NATIVE_EVENT_PRODUCT_REGISTRY)


def native_package_pairs() -> tuple[NativePackagePair, ...]:
    """Return all exact core/native package pairs declared for this source ref."""

    return tuple(NativePackagePair.from_mapping(item) for item in NATIVE_EVENT_COMPATIBILITY_MATRIX)


def find_native_package_pair(core_version: str, native_version: str) -> NativePackagePair | None:
    """Find an exact declared package pair without making a routing decision."""

    for pair in native_package_pairs():
        if pair.core_version == str(core_version) and pair.native_version == str(native_version):
            return pair
    return None


def require_native_package_pair(core_version: str, native_version: str) -> NativePackagePair:
    """Return the declared pair or raise a clear pre-execution compatibility error."""

    pair = find_native_package_pair(core_version, native_version)
    if pair is None:
        raise NativePackageCompatibilityError(
            "unsupported quantbt-engine/quantbt-native pair: "
            f"core={core_version!r}, native={native_version!r}, "
            f"registry={PRODUCT_CONTRACT_REGISTRY_FINGERPRINT}"
        )
    return pair


def native_runtime_product_descriptor() -> dict[str, object]:
    """Return the exact product ABI expected from an API 0.4 native wheel.

    This intentionally lives beside, rather than inside, the frozen semantic
    descriptor. The latter protects execution behavior; this descriptor
    protects package/protocol compatibility before native execution begins.
    """

    return {
        "descriptor_version": "native-event-product-v1",
        "product_registry_fingerprint": PRODUCT_CONTRACT_REGISTRY_FINGERPRINT,
        "lifecycle_registry_fingerprint": NATIVE_EVENT_LIFECYCLE_REGISTRY_FINGERPRINT,
        "core_package_version": NATIVE_EVENT_CORE_PACKAGE_VERSION,
        "native_package_version": NATIVE_EVENT_NATIVE_PACKAGE_VERSION,
        "native_protocol_min": NATIVE_EVENT_CORE_PROTOCOL_MIN,
        "native_protocol_max": NATIVE_EVENT_CORE_PROTOCOL_MAX,
        "command_abi": NATIVE_EVENT_COMMAND_ABI_VERSION,
        "result_abi": NATIVE_EVENT_RESULT_ABI_VERSION,
        "trace_schema": NATIVE_EVENT_TRACE_SCHEMA_VERSION,
        "strategy_ir": NATIVE_EVENT_STRATEGY_IR_VERSION,
    }


def validate_native_runtime_product_descriptor(
    descriptor: Mapping[str, object],
    *,
    pair: NativePackagePair,
) -> None:
    """Fail closed when a native wheel does not match the declared product ABI."""

    expected = native_runtime_product_descriptor()
    required_equal = (
        "descriptor_version",
        "product_registry_fingerprint",
        "lifecycle_registry_fingerprint",
        "core_package_version",
        "native_package_version",
        "command_abi",
        "result_abi",
        "trace_schema",
        "strategy_ir",
    )
    mismatches = [key for key in required_equal if descriptor.get(key) != expected[key]]
    protocol_min = int(descriptor.get("native_protocol_min", -1))
    protocol_max = int(descriptor.get("native_protocol_max", -1))
    if not protocol_min <= NATIVE_EVENT_CORE_PROTOCOL_MIN <= protocol_max:
        mismatches.append("native_protocol_range")
    if str(descriptor.get("command_abi")) not in pair.command_abis:
        mismatches.append("command_abi_pair")
    if str(descriptor.get("result_abi")) not in pair.result_abis:
        mismatches.append("result_abi_pair")
    if mismatches:
        raise NativePackageCompatibilityError(
            "native product descriptor mismatch: "
            f"{', '.join(sorted(set(mismatches)))}; "
            f"registry={PRODUCT_CONTRACT_REGISTRY_FINGERPRINT}"
        )


def workload_capabilities() -> tuple[dict[str, object], ...]:
    """Return defensive copies of generated workload capability descriptors."""

    return tuple(deepcopy(item) for item in WORKLOAD_CAPABILITY_DESCRIPTORS)


def native_deprecations() -> tuple[dict[str, object], ...]:
    """Return the machine-readable deprecation records for release tooling."""

    return tuple(deepcopy(item) for item in NATIVE_EVENT_DEPRECATION_MATRIX)


__all__ = [
    "NativePackageCompatibilityError",
    "NativePackagePair",
    "find_native_package_pair",
    "native_runtime_product_descriptor",
    "native_deprecations",
    "native_package_pairs",
    "native_product_registry",
    "require_native_package_pair",
    "validate_native_runtime_product_descriptor",
    "workload_capabilities",
]
