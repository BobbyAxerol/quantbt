"""Strict parity certificates for native-event execution artifacts.

This module deliberately lives above the execution kernels.  It compares
observable lifecycle/accounting artifacts and therefore can certify Python,
Rust, and replay results without making any backend responsible for another
backend's object model.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from typing import Any, Mapping

import numpy as np
import pandas as pd

from .native_event_capabilities import NATIVE_EVENT_CAPABILITY_MATRIX


DEFAULT_NUMERIC_ATOL = 1e-12
_NUMERIC_FIELDS = (
    "equity",
    "positions",
    "fees",
    "funding",
    "turnover",
    "initial_margin",
    "maintenance_margin",
)
_DISCRETE_FIELDS = (
    "liquidated",
    "liquidation_bar",
)


class NativeEventParityError(AssertionError):
    """Raised when two native-event artifacts are not lifecycle-equivalent."""


@dataclass(frozen=True)
class NativeEventParityCertificate:
    """Serializable summary returned by :func:`assert_native_event_full_parity`."""

    passed: bool
    numeric_atol: float
    compared_fields: tuple[str, ...]
    missing_fields: tuple[str, ...]
    candidate_fingerprint: str
    oracle_fingerprint: str
    command_fingerprint: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "numeric_atol": self.numeric_atol,
            "compared_fields": list(self.compared_fields),
            "missing_fields": list(self.missing_fields),
            "candidate_fingerprint": self.candidate_fingerprint,
            "oracle_fingerprint": self.oracle_fingerprint,
            "command_fingerprint": self.command_fingerprint,
        }


def _metadata(result: object) -> Mapping[str, object]:
    value = getattr(result, "metadata", None)
    return value if isinstance(value, Mapping) else {}


def _array(value: object, *, name: str) -> np.ndarray | None:
    if value is None:
        return None
    if isinstance(value, pd.Series):
        return value.to_numpy(copy=True)
    if isinstance(value, pd.DataFrame):
        if name == "positions":
            columns = [column for column in value.columns if str(column).startswith("Position_")]
            if columns:
                return value[columns].to_numpy(copy=True)
        if name in value:
            return value[name].to_numpy(copy=True)
        return value.to_numpy(copy=True)
    return np.asarray(value).copy()


def _result_field(result: object, name: str) -> np.ndarray | object | None:
    value = getattr(result, name, None)
    if name == "turnover" and value is None:
        diagnostics = getattr(result, "diagnostics", None)
        value = diagnostics.get("turnover") if isinstance(diagnostics, pd.DataFrame) else None
    if name in {"initial_margin", "maintenance_margin"} and value is None:
        margin = getattr(result, "margin", None)
        if isinstance(margin, pd.DataFrame):
            value = margin.get(name)
    if value is None:
        value = _metadata(result).get(name)
    return _array(value, name=name) if name not in _DISCRETE_FIELDS else value


def _stable_bytes(value: object) -> bytes:
    if isinstance(value, Mapping):
        value = {str(key): value[key] for key in sorted(value, key=str)}
        return json.dumps(value, sort_keys=True, default=str, separators=(",", ":")).encode("utf-8")
    if isinstance(value, (str, int, float, bool)) or value is None:
        return json.dumps(value, sort_keys=True, default=str, separators=(",", ":")).encode("utf-8")
    array = np.asarray(value)
    if array.dtype.kind in "OUS":
        payload = [str(item) for item in array.reshape(-1)]
        return json.dumps({"shape": array.shape, "values": payload}, separators=(",", ":")).encode("utf-8")
    contiguous = np.ascontiguousarray(array)
    return b"|".join((str(contiguous.dtype).encode(), repr(contiguous.shape).encode(), contiguous.tobytes()))


def _fingerprint(fields: Mapping[str, object]) -> str:
    digest = sha256()
    for name in sorted(fields):
        digest.update(name.encode("utf-8"))
        digest.update(b"=")
        digest.update(_stable_bytes(fields[name]))
        digest.update(b"\n")
    return digest.hexdigest()


def _record_value(record: object, name: str, default: object = None) -> object:
    if isinstance(record, Mapping):
        return record.get(name, default)
    return getattr(record, name, default)


def _fill_records(result: object) -> list[tuple[object, ...]] | None:
    arrays = {name: getattr(result, f"fill_{name}", None) for name in (
        "bar", "order_id", "side", "qty", "price", "fee"
    )}
    if all(value is not None for value in arrays.values()):
        length = len(np.asarray(arrays["bar"]))
        return [
            tuple(np.asarray(arrays[name])[idx].item() for name in arrays)
            for idx in range(length)
        ]
    fills = getattr(result, "fills", None)
    if fills is None:
        fills = _metadata(result).get("fills")
    if fills is None:
        return None
    records = []
    for fill in fills:
        side = _record_value(fill, "side")
        side = getattr(side, "value", side)
        records.append(
            (
                str(_record_value(fill, "timestamp")),
                str(_record_value(fill, "symbol")),
                side,
                float(_record_value(fill, "qty")),
                float(_record_value(fill, "price")),
                float(_record_value(fill, "fee", 0.0)),
                str(_record_value(fill, "order_id")),
            )
        )
    return records


def _event_records(result: object) -> list[tuple[object, ...]] | None:
    arrays = {
        name: getattr(result, f"event_{name}", None)
        for name in ("bar", "kind", "status", "order_id", "target_id")
    }
    if all(value is not None for value in arrays.values()):
        length = len(np.asarray(arrays["bar"]))
        return [
            tuple(np.asarray(arrays[name])[idx].item() for name in arrays)
            for idx in range(length)
        ]
    metadata = _metadata(result)
    ledger = metadata.get("compact_order_event_ledger")
    if ledger is None:
        ledger = metadata.get("event_ledger")
    if ledger is None:
        return None
    if isinstance(ledger, Mapping):
        names = ("bar", "kind", "status", "order_id", "target_id")
        if all(name in ledger for name in names):
            arrays = {name: np.asarray(ledger[name]) for name in names}
            id_values = tuple(metadata.get("id_values", ()))

            def decoded_id(value: object) -> object:
                code = int(value)
                return id_values[code] if 0 <= code < len(id_values) else None

            return [
                (
                    arrays["bar"][idx].item(),
                    arrays["kind"][idx].item(),
                    arrays["status"][idx].item(),
                    decoded_id(arrays["order_id"][idx]),
                    decoded_id(arrays["target_id"][idx]),
                )
                for idx in range(len(arrays["bar"]))
            ]
    names = ("bar", "event_type", "status", "command_index", "related_command_index")
    if all(hasattr(ledger, name) for name in names):
        arrays = {name: np.asarray(getattr(ledger, name)) for name in names}
        commands = metadata.get("compact_command_ledger")
        id_values = tuple(metadata.get("id_values", ()))

        def command_id(value: object) -> object:
            index = int(value)
            if index < 0 or commands is None or not hasattr(commands, "order_id_code"):
                return None
            code = int(np.asarray(commands.order_id_code)[index])
            return id_values[code] if 0 <= code < len(id_values) else None

        def command_target_id(value: object) -> object:
            index = int(value)
            if index < 0 or commands is None or not hasattr(commands, "target_order_id_code"):
                return None
            code = int(np.asarray(commands.target_order_id_code)[index])
            return id_values[code] if 0 <= code < len(id_values) else None

        return [
            (
                arrays["bar"][idx].item(),
                arrays["event_type"][idx].item(),
                arrays["status"][idx].item(),
                command_id(arrays["command_index"][idx]),
                command_id(arrays["related_command_index"][idx])
                or command_target_id(arrays["command_index"][idx]),
            )
            for idx in range(len(arrays["bar"]))
        ]
    return None


def _command_fingerprint(command_tape: object) -> str:
    if isinstance(command_tape, Mapping):
        fields = command_tape
    else:
        names = (
            "effective_bar", "command_ptr", "command_action", "command_order_id",
            "command_status", "command_symbol", "command_sequence",
        )
        fields = {name: getattr(command_tape, name) for name in names if hasattr(command_tape, name)}
    if not fields:
        raise ValueError("command_tape must expose at least one deterministic command field")
    return _fingerprint({str(name): value for name, value in fields.items()})


def _snapshot(result: object) -> dict[str, object]:
    fields: dict[str, object] = {}
    for name in _NUMERIC_FIELDS:
        value = _result_field(result, name)
        if value is not None:
            fields[name] = value
    fills = _fill_records(result)
    if fills is not None:
        fields["fills"] = fills
    events = _event_records(result)
    if events is not None:
        fields["events"] = events
    for name in _DISCRETE_FIELDS:
        value = getattr(result, name, None)
        if value is not None:
            fields[name] = value
    return fields


def assert_native_event_full_parity(
    candidate: object,
    oracle: object,
    *,
    numeric_atol: float = DEFAULT_NUMERIC_ATOL,
    capabilities: Mapping[str, object] | None = None,
    command_tape: object | tuple[object, object] | None = None,
    require_full: bool = True,
) -> dict[str, object]:
    """Compare complete observable lifecycle and accounting artifacts.

    Discrete lifecycle artifacts (fills, event order, statuses, and boolean
    state) must match exactly. Numeric paths use ``rtol=0`` and the supplied
    absolute tolerance. ``require_full=True`` requires fills and event ledgers
    on both sides; use ``False`` only for an explicitly scalar/minimal run.
    ``command_tape`` may be one shared tape or ``(candidate, oracle)``.
    """

    atol = float(numeric_atol)
    if atol < 0.0 or not np.isfinite(atol):
        raise ValueError("numeric_atol must be finite and >= 0")
    left = _snapshot(candidate)
    right = _snapshot(oracle)
    capabilities = dict(NATIVE_EVENT_CAPABILITY_MATRIX if capabilities is None else capabilities)
    compared: list[str] = []
    missing: list[str] = []

    for name in _NUMERIC_FIELDS:
        left_value = left.get(name)
        right_value = right.get(name)
        required = name in {"equity", "positions", "fees", "turnover", "initial_margin", "maintenance_margin"}
        if name == "funding":
            required = bool(capabilities.get("funding", False))
        if left_value is None or right_value is None:
            if required:
                missing.append(name)
            continue
        lhs = np.asarray(left_value)
        rhs = np.asarray(right_value)
        if lhs.shape != rhs.shape:
            raise NativeEventParityError(f"{name} shape mismatch: {lhs.shape} != {rhs.shape}")
        if not np.allclose(lhs, rhs, rtol=0.0, atol=atol, equal_nan=True):
            difference = float(np.nanmax(np.abs(lhs.astype(float) - rhs.astype(float))))
            raise NativeEventParityError(f"{name} mismatch: max_abs_diff={difference:.17g}, atol={atol:.17g}")
        compared.append(name)

    for name in _DISCRETE_FIELDS:
        if name not in left or name not in right:
            if name in {"liquidated", "liquidation_bar"} and not capabilities.get("liquidation", False):
                continue
            missing.append(name)
            continue
        if left[name] != right[name]:
            raise NativeEventParityError(f"{name} mismatch: {left[name]!r} != {right[name]!r}")
        compared.append(name)

    for name in ("fills", "events"):
        lhs = left.get(name)
        rhs = right.get(name)
        if lhs is None or rhs is None:
            if require_full:
                missing.append(name)
            continue
        if lhs != rhs:
            raise NativeEventParityError(f"{name} lifecycle sequence mismatch")
        compared.append(name)

    command_fingerprint = None
    if command_tape is not None:
        if isinstance(command_tape, tuple):
            if len(command_tape) != 2:
                raise ValueError("command_tape tuple must contain (candidate_tape, oracle_tape)")
            left_command = _command_fingerprint(command_tape[0])
            right_command = _command_fingerprint(command_tape[1])
            if left_command != right_command:
                raise NativeEventParityError("command sequence/effective-bar fingerprint mismatch")
            command_fingerprint = left_command
        else:
            command_fingerprint = _command_fingerprint(command_tape)
        compared.append("command_tape")

    if missing:
        raise NativeEventParityError(f"parity artifacts missing: {sorted(set(missing))}")
    candidate_fingerprint = _fingerprint(left)
    oracle_fingerprint = _fingerprint(right)
    certificate = NativeEventParityCertificate(
        passed=True,
        numeric_atol=atol,
        compared_fields=tuple(compared),
        missing_fields=tuple(missing),
        candidate_fingerprint=candidate_fingerprint,
        oracle_fingerprint=oracle_fingerprint,
        command_fingerprint=command_fingerprint,
    )
    return certificate.to_dict()


__all__ = [
    "DEFAULT_NUMERIC_ATOL",
    "NativeEventParityCertificate",
    "NativeEventParityError",
    "assert_native_event_full_parity",
]
