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


NATIVE_EVENT_CAPABILITY_MATRIX_VERSION = "full-contract-v2-0.4"

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
    "NATIVE_EVENT_CAPABILITY_MATRIX",
    "capability_matrix_fingerprint",
    "native_event_capability_matrix",
    "normalize_native_event_capabilities",
    "validate_native_event_capability_matrix",
]
