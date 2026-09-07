"""Versioned V1.1 benchmark measurement contract.

This module deliberately has no engine, pandas, Rust, or reporting imports.
It defines one JSON-safe shape for baseline and future performance evidence so
that a score benchmark, a reactive benchmark, and a WFO benchmark can report
their boundary and RSS costs without pretending that absent measurements are
zeros.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


MEASUREMENT_SCHEMA_V1 = "quantbt-rust-primary-measurement-v1"

PHASE_TIMING_FIELDS_V1 = (
    "input_adaptation_ns",
    "market_prepare_ns",
    "instrument_prepare_ns",
    "strategy_prepare_ns",
    "strategy_generate_ns",
    "intent_ingest_ns",
    "native_execution_ns",
    "native_metrics_ns",
    "native_result_ns",
    "python_materialization_ns",
    "report_ns",
)

BOUNDARY_COUNTER_FIELDS_V1 = (
    "native_entry_calls",
    "python_callback_calls",
    "gil_acquisitions",
    "context_projection_bytes",
    "command_ingest_bytes",
    "market_copy_bytes",
    "intent_copy_bytes",
    "result_copy_bytes",
    "worker_pool_starts",
    "session_resets",
)

MEMORY_FIELDS_V1 = (
    "cold_peak_rss_bytes",
    "warm_steady_rss_bytes",
    "native_allocated_bytes",
    "python_allocated_bytes",
    "cache_bytes",
    "result_retained_bytes",
)

MEASUREMENT_STATUSES_V1 = frozenset({"measured", "historical_artifact", "not_applicable"})


def _normalize_non_negative_mapping(
    values: Mapping[str, int | None] | None,
    fields: Sequence[str],
    *,
    label: str,
) -> dict[str, int | None]:
    source = dict(values or {})
    unknown = sorted(set(source) - set(fields))
    if unknown:
        raise ValueError(f"{label} contains unknown fields: {unknown}")
    normalized: dict[str, int | None] = {}
    for field in fields:
        value = source.get(field)
        if value is None:
            normalized[field] = None
            continue
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"{label}.{field} must be a non-negative integer or None")
        normalized[field] = int(value)
    return normalized


def build_measurement_record_v1(
    *,
    workload_id: str,
    route_id: str,
    profile: str,
    requested_backend: str,
    resolved_backend: str,
    runtime_class: str,
    measurement_status: str = "historical_artifact",
    phase_timings_ns: Mapping[str, int | None] | None = None,
    boundary_counters: Mapping[str, int | None] | None = None,
    memory_bytes: Mapping[str, int | None] | None = None,
    result_status: str = "not_recorded",
    terminal_fingerprint: str | None = None,
    artifact_refs: Sequence[str] = (),
    notes: Sequence[str] = (),
) -> dict[str, Any]:
    """Build a complete, JSON-safe V1.1 measurement record.

    ``None`` means the source artifact did not measure that field. It is
    intentionally different from zero, which represents a measured zero.
    """

    if measurement_status not in MEASUREMENT_STATUSES_V1:
        raise ValueError(f"unsupported measurement_status: {measurement_status!r}")
    required = {
        "workload_id": workload_id,
        "route_id": route_id,
        "profile": profile,
        "requested_backend": requested_backend,
        "resolved_backend": resolved_backend,
        "runtime_class": runtime_class,
        "result_status": result_status,
    }
    blank = sorted(name for name, value in required.items() if not isinstance(value, str) or not value.strip())
    if blank:
        raise ValueError(f"measurement record requires non-empty strings: {blank}")
    record = {
        "schema": MEASUREMENT_SCHEMA_V1,
        "measurement_status": measurement_status,
        "workload_id": workload_id,
        "route_id": route_id,
        "profile": profile,
        "requested_backend": requested_backend,
        "resolved_backend": resolved_backend,
        "runtime_class": runtime_class,
        "phase_timings_ns": _normalize_non_negative_mapping(
            phase_timings_ns, PHASE_TIMING_FIELDS_V1, label="phase_timings_ns"
        ),
        "boundary_counters": _normalize_non_negative_mapping(
            boundary_counters, BOUNDARY_COUNTER_FIELDS_V1, label="boundary_counters"
        ),
        "memory_bytes": _normalize_non_negative_mapping(memory_bytes, MEMORY_FIELDS_V1, label="memory_bytes"),
        "result_status": result_status,
        "terminal_fingerprint": terminal_fingerprint,
        "artifact_refs": sorted({str(item) for item in artifact_refs}),
        "notes": list(notes),
    }
    violations = validate_measurement_record_v1(record)
    if violations:
        raise ValueError("invalid measurement record: " + "; ".join(violations))
    return record


def validate_measurement_record_v1(record: Mapping[str, Any]) -> list[str]:
    """Return deterministic violations for one V1.1 measurement record."""

    violations: list[str] = []
    if record.get("schema") != MEASUREMENT_SCHEMA_V1:
        violations.append("unsupported measurement schema")
    if record.get("measurement_status") not in MEASUREMENT_STATUSES_V1:
        violations.append("unsupported measurement status")
    for field in (
        "workload_id",
        "route_id",
        "profile",
        "requested_backend",
        "resolved_backend",
        "runtime_class",
        "result_status",
    ):
        if not isinstance(record.get(field), str) or not str(record[field]).strip():
            violations.append(f"missing non-empty {field}")
    for label, fields in (
        ("phase_timings_ns", PHASE_TIMING_FIELDS_V1),
        ("boundary_counters", BOUNDARY_COUNTER_FIELDS_V1),
        ("memory_bytes", MEMORY_FIELDS_V1),
    ):
        value = record.get(label)
        if not isinstance(value, Mapping):
            violations.append(f"{label} must be a mapping")
            continue
        if set(value) != set(fields):
            violations.append(f"{label} must contain the exact V1 field set")
            continue
        for field in fields:
            number = value[field]
            if number is not None and (isinstance(number, bool) or not isinstance(number, int) or number < 0):
                violations.append(f"{label}.{field} must be non-negative integer or None")
    for field in ("artifact_refs", "notes"):
        value = record.get(field)
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            violations.append(f"{field} must be a string list")
    fingerprint = record.get("terminal_fingerprint")
    if fingerprint is not None and (not isinstance(fingerprint, str) or not fingerprint.strip()):
        violations.append("terminal_fingerprint must be a non-empty string or None")
    return violations


def measurement_contract_definition_v1() -> dict[str, Any]:
    """Return the checked schema description written into V1.1 artifacts."""

    return {
        "schema": MEASUREMENT_SCHEMA_V1,
        "measurement_statuses": sorted(MEASUREMENT_STATUSES_V1),
        "phase_timings_ns": list(PHASE_TIMING_FIELDS_V1),
        "boundary_counters": list(BOUNDARY_COUNTER_FIELDS_V1),
        "memory_bytes": list(MEMORY_FIELDS_V1),
        "null_semantics": "null means not measured by the referenced artifact; zero means measured zero",
    }
