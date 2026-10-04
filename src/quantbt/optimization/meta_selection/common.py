"""Small immutable/portable primitives for the QMS record boundary."""

from __future__ import annotations

from dataclasses import fields, is_dataclass
from enum import Enum
from hashlib import sha256
import json
import math
from types import MappingProxyType
from typing import Mapping

import numpy as np
import pandas as pd


class MetaRecordError(ValueError):
    """Invalid identity, evidence, clock or portable record; not cold start."""


def utc(value):
    stamp = pd.Timestamp(value)
    if pd.isna(stamp) or stamp.tzinfo is None:
        raise MetaRecordError("META_CLOCK_INVALID: explicit aware timestamps required")
    return stamp.tz_convert("UTC")


def token(value, name="reference"):
    if not isinstance(value, str) or not value.strip():
        raise MetaRecordError(f"META_IDENTITY_INVALID: {name} must be nonempty")
    return value


def wire(value):
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, pd.Timestamp):
        return utc(value).isoformat()
    if is_dataclass(value):
        return {f.name: wire(getattr(value, f.name)) for f in fields(value)}
    if isinstance(value, Mapping):
        if any(not isinstance(k, str) for k in value):
            raise MetaRecordError("portable mappings require string keys")
        return {k: wire(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [wire(v) for v in value]
    if isinstance(value, np.generic):
        return wire(value.item())
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float) and math.isfinite(value):
        return value
    raise MetaRecordError(
        f"META_PAYLOAD_INVALID: nonportable/nonfinite {type(value).__name__}"
    )


def canonical(value):
    return json.dumps(
        wire(value), sort_keys=True, separators=(",", ":"), allow_nan=False
    )


def digest(value):
    return sha256(canonical(value).encode()).hexdigest()


def freeze(value):
    portable = wire(value)

    def convert(item):
        if isinstance(item, dict):
            return MappingProxyType({k: convert(v) for k, v in item.items()})
        if isinstance(item, list):
            return tuple(convert(v) for v in item)
        return item

    return convert(portable)


def frozen_array(value, *, dtype=np.float64):
    array = np.ascontiguousarray(value, dtype=dtype)
    # An immutable bytes owner prevents callers from re-enabling writeability.
    return np.frombuffer(array.tobytes(), dtype=array.dtype).reshape(array.shape)


def strict_fields(cls, payload):
    if not isinstance(payload, Mapping) or set(payload) != {
        f.name for f in fields(cls)
    }:
        raise MetaRecordError(f"META_SCHEMA_MISMATCH: invalid {cls.__name__} fields")
    return dict(payload)
