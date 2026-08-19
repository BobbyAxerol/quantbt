"""Deterministic fingerprints for immutable planning models."""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from enum import Enum, IntFlag
import hashlib
import json
from typing import Any, Mapping


def _canonical(value: Any) -> Any:
    if is_dataclass(value):
        return _canonical(asdict(value))
    if isinstance(value, (Enum, IntFlag)):
        return value.value
    if isinstance(value, Mapping):
        return {str(key): _canonical(item) for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))}
    if isinstance(value, (tuple, list)):
        return [_canonical(item) for item in value]
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    raise TypeError(f"planning fingerprint does not support {type(value).__name__}")


def canonical_payload(value: Any) -> dict[str, Any]:
    payload = _canonical(value)
    if not isinstance(payload, dict):
        raise TypeError("planning payload must serialize to a mapping")
    return payload


def planning_fingerprint(value: Any) -> str:
    encoded = json.dumps(
        canonical_payload(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("ascii")
    return hashlib.sha256(encoded).hexdigest()


__all__ = ["canonical_payload", "planning_fingerprint"]
