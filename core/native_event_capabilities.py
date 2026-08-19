"""Canonical native-event capability contract.

The Rust extension exposes a low-level capability map whose names are tied to
its release history (for example ``rust_batched_tape``).  Public selectors,
tests, and documentation need a stable vocabulary instead.  This module is
the single Python-side source of truth for the currently certified
single-symbol R2 surface. Full-contract 0.4 flags are additive and only
normalize to the wider vocabulary when the extension advertises the complete
capability gate.
"""

from __future__ import annotations

from hashlib import sha256
import json
from types import MappingProxyType
from typing import Mapping

from .event_contracts import NATIVE_EVENT_CONTRACT_FINGERPRINT
from .execution_trace import TRACE_SCHEMA_VERSION


NATIVE_EVENT_CAPABILITY_MATRIX_VERSION = "full-contract-v2-0.4"
NATIVE_EVENT_CORE_PROTOCOL_VERSION = 1
NATIVE_EVENT_COMMAND_ABI_VERSION = "full-command-v1"
NATIVE_EVENT_SEMANTIC_DESCRIPTOR_VERSION = "native-event-semantics-v1"

_CAPABILITIES = {
    "single_symbol": True,
    "market": True,
    "limit": True,
    "stop_market": True,
    "stop_limit": True,
    "place": True,
    "cancel": True,
    "amend": True,
    "replace": True,
    "reduce_only": True,
    "quantity_constraints": True,
    "gtc": True,
    "gtd": True,
    "ioc": True,
    "fok": True,
    "parent_child": True,
    "oco": True,
    "funding": True,
    "liquidation": True,
    "multi_symbol": True,
}

NATIVE_EVENT_CAPABILITY_MATRIX: Mapping[str, bool] = MappingProxyType(_CAPABILITIES)


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

    return {
        "descriptor_version": NATIVE_EVENT_SEMANTIC_DESCRIPTOR_VERSION,
        "native_api": "0.4",
        "core_protocol_min": NATIVE_EVENT_CORE_PROTOCOL_VERSION,
        "core_protocol_max": NATIVE_EVENT_CORE_PROTOCOL_VERSION,
        "contract_registry_fingerprint": NATIVE_EVENT_CONTRACT_FINGERPRINT,
        "trace_schema": TRACE_SCHEMA_VERSION,
        "command_abi": NATIVE_EVENT_COMMAND_ABI_VERSION,
        "contracts": ["event_lifecycle_v2_next_bar_close", "event_lifecycle_v3_next_open"],
        "orders": {
            "types": ["market", "limit", "stop_market", "stop_limit"],
            "partial_fill": False,
            "volume_model": "infinite_bar_liquidity",
            "gap_policy": ["legacy_trigger", "open_worse_than_trigger"],
        },
        "account": {
            "pnl_models": ["linear_quote_settled"],
            "margin_models": ["gross_cross"],
            "liquidation_models": ["zero_equity_legacy"],
        },
        "portfolio": {
            "target_execution": False,
            "package_atomicity": "python_reference_only",
        },
    }


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
    lifecycle = source.get("reactive_session", False) or source.get("r1_single_symbol", False)
    place_cancel = source.get("r1_place_cancel_market_limit_gtc", False)
    r2 = source.get("r2_stop_amend_replace_reduce_only_constraints", False)
    batched = source.get("rust_batched_tape", False) or source.get("rust_batched_tape_audit", False)
    full = source.get("native_event_v2_full_contract", False)

    normalized = native_event_capability_matrix()
    normalized["single_symbol"] = bool(full or lifecycle or batched)
    normalized["market"] = bool(full or place_cancel or batched)
    normalized["limit"] = bool(full or place_cancel or batched)
    normalized["stop_market"] = bool(full or r2)
    normalized["stop_limit"] = bool(full or r2)
    normalized["place"] = bool(full or place_cancel or batched)
    normalized["cancel"] = bool(full or place_cancel or batched)
    normalized["amend"] = bool(full or r2)
    normalized["replace"] = bool(full or r2)
    normalized["reduce_only"] = bool(full or r2)
    normalized["quantity_constraints"] = bool(full or r2)
    normalized["gtc"] = bool(full or place_cancel or batched)
    if full:
        normalized.update({
            "gtd": True, "ioc": True, "fok": True, "parent_child": True,
            "oco": True, "funding": True, "liquidation": True, "multi_symbol": True,
        })
    else:
        normalized.update({
            "gtd": False, "ioc": False, "fok": False, "parent_child": False,
            "oco": False, "funding": False, "liquidation": False, "multi_symbol": False,
        })
    return normalized


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
