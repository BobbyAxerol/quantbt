"""Bounded runtime governance shared by native and hybrid execution routes.

The objects in this module do not execute trades.  They provide one small,
dependency-light contract for admission budgets, cancellation, parallelism,
bounded audit retention, runtime telemetry, and route-level A5 review.
Execution backends remain responsible for checking the counters they own.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
import json
import os
from pathlib import Path
from threading import Event, Lock
from time import monotonic_ns
from typing import Any, Callable, Iterable, Mapping
from uuid import uuid4


class RuntimeBudgetError(RuntimeError):
    """Raised before execution when a declared hard resource limit is exceeded."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = str(code)


class RuntimeCanceledError(RuntimeError):
    """Raised at a certified safe point when a synchronous run is canceled."""


class RuntimeState(str, Enum):
    READY = "ready"
    RUNNING = "running"
    CANCELED = "canceled"
    POISONED = "poisoned"
    CLOSED = "closed"


@dataclass(frozen=True, slots=True)
class RuntimeBudgetV1:
    """Canonical optional limits for one execution runtime.

    ``None`` means that a limit is intentionally not imposed by this layer.
    A backend must fail early if it cannot enforce a non-``None`` limit; it
    must never acknowledge a budget and then ignore it.
    """

    max_bars: int | None = None
    max_wall_time_ms: int | None = None
    max_commands: int | None = None
    max_orders: int | None = None
    max_active_orders: int | None = None
    max_fills: int | None = None
    max_audit_rows: int | None = None
    max_native_memory_bytes: int | None = None
    max_workers: int | None = None
    max_metric_rows: int = 1_000_000
    max_error_rows: int = 64

    def __post_init__(self) -> None:
        for name, value in asdict(self).items():
            if value is not None and (isinstance(value, bool) or int(value) <= 0):
                raise ValueError(f"RuntimeBudgetV1.{name} must be a positive integer or None")

    def require_preflight(
        self,
        *,
        bars: int,
        workers: int,
        native_memory_bytes: int = 0,
        metric_rows: int = 0,
        audit_rows: int = 0,
    ) -> None:
        checks = (
            ("MAX_BARS", self.max_bars, bars, "bar"),
            ("MAX_WORKERS", self.max_workers, workers, "worker"),
            ("MAX_NATIVE_MEMORY", self.max_native_memory_bytes, native_memory_bytes, "native byte"),
            ("MAX_METRIC_ROWS", self.max_metric_rows, metric_rows, "metric row"),
            ("MAX_AUDIT_ROWS", self.max_audit_rows, audit_rows, "audit row"),
        )
        for code, limit, actual, unit in checks:
            if limit is not None and int(actual) > int(limit):
                raise RuntimeBudgetError(
                    code,
                    f"runtime budget exceeded: {actual} {unit}s requested, limit={limit}",
                )

    def as_native_kwargs(self) -> dict[str, int | None]:
        """Return the stable PyO3 keyword surface for native WFO runtimes."""

        return {
            "max_bars": self.max_bars,
            "max_wall_time_ms": self.max_wall_time_ms,
            "max_commands": self.max_commands,
            "max_orders": self.max_orders,
            "max_active_orders": self.max_active_orders,
            "max_fills": self.max_fills,
            "max_audit_rows": self.max_audit_rows,
            "max_native_memory_bytes": self.max_native_memory_bytes,
            "max_workers": self.max_workers,
        }


@dataclass(frozen=True, slots=True)
class ParallelismPlanV1:
    python_processes: int
    rust_workers: int
    blas_threads: int
    openmp_threads: int
    numba_threads: int
    host_cpus: int
    constrained_by: tuple[str, ...]

    @classmethod
    def resolve(
        cls,
        *,
        python_processes: int = 1,
        rust_workers: int = 1,
        blas_threads: int | None = None,
        openmp_threads: int | None = None,
        numba_threads: int | None = None,
        max_total_threads: int | None = None,
        max_rust_workers: int | None = None,
        host_cpus: int | None = None,
    ) -> "ParallelismPlanV1":
        host = max(1, int(host_cpus or os.cpu_count() or 1))
        processes = _positive("python_processes", python_processes)
        requested_rust = _positive("rust_workers", rust_workers)
        total_limit = max(1, int(max_total_threads or host))
        per_process = max(1, total_limit // processes)
        effective_rust = min(requested_rust, per_process)
        constrained: list[str] = []
        if max_rust_workers is not None:
            bounded = min(effective_rust, _positive("max_rust_workers", max_rust_workers))
            if bounded != effective_rust:
                constrained.append("runtime_budget.max_workers")
            effective_rust = bounded
        if effective_rust != requested_rust:
            constrained.append("nested_parallelism")

        # A process running a Rust worker pool receives scalar math-library
        # pools by default. Explicit values are still capped to its CPU share.
        default_aux = 1 if effective_rust > 1 or processes > 1 else per_process
        values = []
        for name, requested in (
            ("blas_threads", blas_threads),
            ("openmp_threads", openmp_threads),
            ("numba_threads", numba_threads),
        ):
            value = min(_positive(name, requested or default_aux), per_process)
            if requested is not None and value != int(requested):
                constrained.append(name)
            values.append(value)
        return cls(
            python_processes=processes,
            rust_workers=effective_rust,
            blas_threads=values[0],
            openmp_threads=values[1],
            numba_threads=values[2],
            host_cpus=host,
            constrained_by=tuple(dict.fromkeys(constrained)),
        )

    @property
    def environment(self) -> Mapping[str, str]:
        return {
            "OPENBLAS_NUM_THREADS": str(self.blas_threads),
            "MKL_NUM_THREADS": str(self.blas_threads),
            "OMP_NUM_THREADS": str(self.openmp_threads),
            "NUMBA_NUM_THREADS": str(self.numba_threads),
        }


class RuntimeCancellationV1:
    """Thread-safe cancellation token with an explicit terminal reason."""

    def __init__(self) -> None:
        self._event = Event()
        self._reason: str | None = None
        self._lock = Lock()

    def cancel(self, reason: str = "requested") -> None:
        with self._lock:
            self._reason = str(reason)
            self._event.set()

    def clear(self) -> None:
        with self._lock:
            self._reason = None
            self._event.clear()

    @property
    def canceled(self) -> bool:
        return self._event.is_set()

    @property
    def reason(self) -> str | None:
        with self._lock:
            return self._reason


AuditExportHook = Callable[[tuple[Mapping[str, Any], ...]], None]


class BoundedAuditSinkV1:
    """Retain bounded detail while preserving complete accounting elsewhere."""

    def __init__(
        self,
        *,
        max_rows: int,
        chunk_rows: int = 1_024,
        export_hook: AuditExportHook | None = None,
    ) -> None:
        self.max_rows = _positive("max_rows", max_rows)
        self.chunk_rows = _positive("chunk_rows", chunk_rows)
        self.export_hook = export_hook
        self._retained: list[Mapping[str, Any]] = []
        self._pending: list[Mapping[str, Any]] = []
        self._dropped = 0
        self._exported = 0
        self._chunks = 0

    def append(self, row: Mapping[str, Any]) -> None:
        if len(self._retained) < self.max_rows:
            stable = dict(row)
            self._retained.append(stable)
            if self.export_hook is not None:
                self._pending.append(stable)
                if len(self._pending) >= self.chunk_rows:
                    self._flush()
        else:
            self._dropped += 1

    def extend(self, rows: Iterable[Mapping[str, Any]]) -> None:
        for row in rows:
            self.append(row)

    def close(self) -> None:
        self._flush()

    def _flush(self) -> None:
        if not self._pending or self.export_hook is None:
            return
        chunk = tuple(self._pending)
        self.export_hook(chunk)
        self._exported += len(chunk)
        self._chunks += 1
        self._pending.clear()

    @property
    def rows(self) -> tuple[Mapping[str, Any], ...]:
        return tuple(self._retained)

    @property
    def header(self) -> Mapping[str, int | bool]:
        return {
            "audit_rows_retained": len(self._retained),
            "audit_rows_dropped": self._dropped,
            "audit_rows_exported": self._exported,
            "audit_chunks_exported": self._chunks,
            "audit_truncated": self._dropped > 0,
        }


@dataclass(slots=True)
class RuntimeTelemetryV1:
    """Small process-local route telemetry; no market or result objects retained."""

    native_runs: int = 0
    python_runs: int = 0
    fallback_runs: int = 0
    shadow_runs: int = 0
    shadow_matches: int = 0
    shadow_mismatches: int = 0
    canceled_runs: int = 0
    budget_rejections: int = 0
    poison_recoveries: int = 0
    last_mismatch_bundle: str | None = None
    native_kill_switch: bool = False
    _lock: Lock = field(default_factory=Lock, repr=False)

    def increment(self, name: str, amount: int = 1) -> None:
        if name not in {
            "native_runs", "python_runs", "fallback_runs", "shadow_runs",
            "shadow_matches", "shadow_mismatches", "canceled_runs",
            "budget_rejections", "poison_recoveries",
        }:
            raise ValueError(f"unknown runtime telemetry counter: {name}")
        with self._lock:
            setattr(self, name, int(getattr(self, name)) + int(amount))

    def record_shadow(
        self,
        *,
        route_id: str,
        primary_fingerprint: str,
        oracle_fingerprint: str,
        evidence_dir: str | Path | None = None,
        details: Mapping[str, Any] | None = None,
    ) -> bool:
        matched = str(primary_fingerprint) == str(oracle_fingerprint)
        self.increment("shadow_runs")
        self.increment("shadow_matches" if matched else "shadow_mismatches")
        if matched:
            return True
        payload = {
            "schema": "quantbt-shadow-mismatch-v1",
            "route_id": str(route_id),
            "primary_fingerprint": str(primary_fingerprint),
            "oracle_fingerprint": str(oracle_fingerprint),
            "details": dict(details or {}),
        }
        with self._lock:
            self.native_kill_switch = True
        if evidence_dir is not None:
            target = Path(evidence_dir)
            target.mkdir(parents=True, exist_ok=True)
            path = target / f"shadow-mismatch-{route_id}-{monotonic_ns()}.json"
            path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            with self._lock:
                self.last_mismatch_bundle = str(path)
        return False

    def snapshot(self) -> Mapping[str, Any]:
        with self._lock:
            return {
                "native_runs": self.native_runs,
                "python_runs": self.python_runs,
                "fallback_runs": self.fallback_runs,
                "shadow_runs": self.shadow_runs,
                "shadow_matches": self.shadow_matches,
                "shadow_mismatches": self.shadow_mismatches,
                "canceled_runs": self.canceled_runs,
                "budget_rejections": self.budget_rejections,
                "poison_recoveries": self.poison_recoveries,
                "last_mismatch_bundle": self.last_mismatch_bundle,
                "native_kill_switch": self.native_kill_switch,
            }


@dataclass(frozen=True, slots=True)
class RuntimeIdentityV1:
    session_id: str
    generation: int = 1

    @classmethod
    def create(cls) -> "RuntimeIdentityV1":
        return cls(session_id=uuid4().hex)

    def next_generation(self) -> "RuntimeIdentityV1":
        return RuntimeIdentityV1(self.session_id, self.generation + 1)


def review_a5_candidate(
    candidate: Mapping[str, Any],
    *,
    stable_release_cycles: int,
    unexplained_mismatches: int,
    fallback_rate: float,
) -> tuple[bool, tuple[str, ...]]:
    """Evaluate a deletion candidate without deleting source or oracle code."""

    reasons: list[str] = []
    required = {
        "replacement_paths",
        "migration_docs",
        "tests",
        "rollback",
    }
    missing = sorted(key for key in required if not candidate.get(key))
    if missing:
        reasons.append("missing_manifest:" + ",".join(missing))
    if int(stable_release_cycles) < 1:
        reasons.append("stable_release_cycle_required")
    if int(unexplained_mismatches) != 0:
        reasons.append("unexplained_shadow_mismatch")
    if not 0.0 <= float(fallback_rate) <= 1.0:
        reasons.append("invalid_fallback_rate")
    elif float(fallback_rate) > 0.0:
        reasons.append("fallback_usage_nonzero")
    if not bool(candidate.get("deletion_approved", False)):
        reasons.append("explicit_deletion_approval_required")
    return not reasons, tuple(reasons)


def _positive(name: str, value: int) -> int:
    if isinstance(value, bool) or int(value) <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return int(value)


__all__ = [
    "BoundedAuditSinkV1",
    "ParallelismPlanV1",
    "RuntimeBudgetError",
    "RuntimeCanceledError",
    "RuntimeBudgetV1",
    "RuntimeCancellationV1",
    "RuntimeIdentityV1",
    "RuntimeState",
    "RuntimeTelemetryV1",
    "review_a5_candidate",
]
