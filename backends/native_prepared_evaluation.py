"""Rust-owned scheduling for immutable prepared native requests.

The public object in this module owns cache-generation checks, resource
budgets, and cold-path adaptation only. A complete candidate/fold/scenario
batch crosses Python/Rust once: Rust owns its persistent worker pool, executes
the typed request handles, and returns compact scalar SoA buffers. This keeps
the specialized Rust request responsible for execution/accounting semantics
without recreating a Python state machine per candidate.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
import hashlib
import json
from threading import Lock
from time import perf_counter_ns
from typing import Any, Iterable, Mapping, Sequence

import numpy as np

from ..core.runtime_governance import (
    ParallelismPlanV1,
    RuntimeBudgetV1,
    RuntimeCancellationV1,
    RuntimeIdentityV1,
)
from ..preparation.native_execution import (
    NativeExecutionPreparationCache,
    NativePreparedRequest,
)


_ERROR_SENTINEL = int(np.iinfo(np.uint32).max)
_SUCCESS = "success"
_CANCELED = "canceled"
_FAILED = "failed"
_STATUS_BY_CODE = {0: _SUCCESS, 1: _CANCELED, 2: _FAILED}
_CERTIFIED_ANNUALIZATION = 365


class NativePreparedWorkloadV1(str, Enum):
    """Execution-semantic families admitted by the shared evaluator."""

    STATIC_COMMAND = "static_command_tape"
    STRATEGY_IR = "strategy_ir"
    TARGET_UNITS = "target_units"
    TARGET_NOTIONAL = "target_notional"
    TARGET_WEIGHT = "target_weight"
    TARGET_EQUITY_FRACTION = "target_equity_fraction"
    PCT_EQUITY_TRANSITION = "pct_equity_transition"
    PORTFOLIO_TARGET = "shared_portfolio_target"
    BOUNDED_PACKAGE = "bounded_same_account_package"
    INTRABAR = "single_symbol_intrabar"


_REQUEST_WORKLOADS: Mapping[NativePreparedWorkloadV1, frozenset[str]] = {
    NativePreparedWorkloadV1.STATIC_COMMAND: frozenset({"command_tape_v5"}),
    NativePreparedWorkloadV1.STRATEGY_IR: frozenset({"strategy_ir_v1"}),
    NativePreparedWorkloadV1.TARGET_UNITS: frozenset({"direct_target_v1"}),
    NativePreparedWorkloadV1.TARGET_NOTIONAL: frozenset({"direct_target_v1"}),
    NativePreparedWorkloadV1.TARGET_WEIGHT: frozenset({"direct_target_v1"}),
    NativePreparedWorkloadV1.TARGET_EQUITY_FRACTION: frozenset({"direct_target_v1"}),
    NativePreparedWorkloadV1.PCT_EQUITY_TRANSITION: frozenset({"direct_target_v1"}),
    NativePreparedWorkloadV1.PORTFOLIO_TARGET: frozenset(
        {"shared_portfolio_target_v1", "portfolio_target_market_v1"}
    ),
    NativePreparedWorkloadV1.BOUNDED_PACKAGE: frozenset(
        {"package_atomic_market_v1", "package_market_v2"}
    ),
    NativePreparedWorkloadV1.INTRABAR: frozenset({"intrabar_bracket_v1"}),
}


@dataclass(frozen=True, slots=True)
class NativeEvaluationMetricContractV1:
    """Scalar row policy certified for the shared prepared runtime.

    The current Rust authority emits the public crypto-daily MetricContractV2.
    Requests for a different annualization are rejected before execution rather
    than silently relabelling a 365-day native Sharpe as another convention.
    """

    contract_id: str = "native-prepared-evaluation-metric-v1"
    trading_days: int = _CERTIFIED_ANNUALIZATION
    scope: str = "fold"
    native_metric_contract_version: int = 2
    required_fields: tuple[str, ...] = (
        "final_equity",
        "total_fee",
        "total_funding",
        "turnover",
        "native_metric_contract_version",
        "native_metric_annualization_factor",
        "fill_count",
        "rejected_count",
        "liquidated",
    )

    def __post_init__(self) -> None:
        if not str(self.contract_id).strip():
            raise ValueError("metric contract_id must be non-empty")
        if int(self.trading_days) <= 0:
            raise ValueError("metric trading_days must be > 0")
        if int(self.trading_days) != _CERTIFIED_ANNUALIZATION:
            raise NotImplementedError(
                "prepared native evaluation currently certifies only the "
                f"crypto-daily MetricContractV2 annualization={_CERTIFIED_ANNUALIZATION}; "
                f"received trading_days={self.trading_days}"
            )
        if int(self.native_metric_contract_version) != 2:
            raise NotImplementedError(
                "prepared native evaluation currently certifies MetricContractV2 only"
            )
        if str(self.scope).lower().strip() not in {"fold", "scenario", "full"}:
            raise ValueError("metric scope must be fold, scenario, or full")
        if not self.required_fields or any(not str(value).strip() for value in self.required_fields):
            raise ValueError("metric required_fields must contain non-empty names")

    @property
    def fingerprint(self) -> str:
        payload = json.dumps(
            {
                "contract_id": str(self.contract_id),
                "trading_days": int(self.trading_days),
                "scope": str(self.scope).lower().strip(),
                "native_metric_contract_version": int(self.native_metric_contract_version),
                "required_fields": tuple(str(value) for value in self.required_fields),
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True, slots=True)
class NativePreparedEvaluationBindingV1:
    """Immutable request bound to one Rust runtime generation."""

    request: NativePreparedRequest
    workload: NativePreparedWorkloadV1
    candidate_id: int
    fold_id: int
    scenario_id: int
    cutoff_bar: int | None
    evaluation_start: int
    evaluation_end: int
    account_policy: str
    metric_contract: NativeEvaluationMetricContractV1
    estimated_cost: int
    cache_generation: int
    runtime_id: str
    runtime_generation: int
    binding_fingerprint: str
    native_binding: Any


@dataclass(frozen=True, slots=True)
class NativePreparedEvaluationRowV1:
    """Stable cold-path scalar row from the Rust SoA matrix."""

    candidate_id: int
    fold_id: int
    scenario_id: int
    status: str
    final_equity: float
    total_fee: float
    total_funding: float
    turnover: float
    total_return: float
    sharpe: float
    sortino: float
    max_drawdown: float
    cagr: float
    calmar: float
    omega: float
    profit_factor: float
    average_gross_exposure: float
    native_metric_contract_version: int
    native_metric_annualization_factor: float
    fill_count: int
    report_trade_count: int
    event_count: int
    rejected_count: int
    canceled_count: int
    sample_count: int
    liquidated: bool
    request_fingerprint: str
    terminal_fingerprint: str
    metric_contract_fingerprint: str
    error_slot: int = _ERROR_SENTINEL


@dataclass(frozen=True, slots=True)
class NativePreparedEvaluationResultV1:
    """Bounded scalar output from one shared prepared-native batch."""

    rows: tuple[NativePreparedEvaluationRowV1, ...]
    errors: tuple[str, ...]
    metadata: Mapping[str, object]

    def by_identity(self) -> Mapping[tuple[int, int, int], NativePreparedEvaluationRowV1]:
        return {(row.candidate_id, row.fold_id, row.scenario_id): row for row in self.rows}

    def assert_terminal_parity(self, other: "NativePreparedEvaluationResultV1") -> None:
        """Verify score/audit equality without creating a dataframe."""

        expected = self.by_identity()
        for identity, observed in other.by_identity().items():
            reference = expected.get(identity)
            if reference is None:
                raise AssertionError("audit row was absent from the prepared score result")
            if reference.status != _SUCCESS or observed.status != _SUCCESS:
                raise AssertionError("score/audit parity requires successful rows")
            if reference.terminal_fingerprint != observed.terminal_fingerprint:
                raise AssertionError("prepared score/audit terminal fingerprint differs")
            for field in (
                "final_equity",
                "total_fee",
                "total_funding",
                "turnover",
                "total_return",
                "sharpe",
                "sortino",
                "max_drawdown",
                "cagr",
                "calmar",
                "omega",
                "profit_factor",
                "average_gross_exposure",
                "native_metric_annualization_factor",
            ):
                if not np.isclose(
                    getattr(reference, field), getattr(observed, field), rtol=0.0, atol=1e-10
                ):
                    raise AssertionError(f"prepared score/audit {field} differs")

    def to_frame(self):
        """Materialize a dataframe only for a cold inspection/report path."""

        import pandas as pd

        return pd.DataFrame([asdict(row) for row in self.rows])


@dataclass(frozen=True, slots=True)
class NativePreparedScoreColumnsV1:
    """Hot-path scalar SoA returned without per-row Python objects.

    This is intentionally narrower than :class:`NativePreparedEvaluationResultV1`:
    Optuna/WFO needs status and a small fixed metric set, while audit callers
    continue to use the complete provenance-preserving row adapter.
    """

    candidate_id: np.ndarray
    fold_id: np.ndarray
    scenario_id: np.ndarray
    status: np.ndarray
    total_return: np.ndarray
    sharpe: np.ndarray
    max_drawdown: np.ndarray
    profit_factor: np.ndarray
    report_trade_count: np.ndarray
    error_slot: np.ndarray
    errors: tuple[str, ...]
    metadata: Mapping[str, object]

    def index_by_scenario(self) -> Mapping[int, int]:
        """Return a small boundary lookup after validating unique scenarios."""

        lookup: dict[int, int] = {}
        for row, scenario in enumerate(self.scenario_id.tolist()):
            scenario_id = int(scenario)
            if scenario_id in lookup:
                raise RuntimeError("native prepared score returned a duplicate scenario_id")
            lookup[scenario_id] = row
        return lookup


def native_prepared_evaluation_support_matrix() -> tuple[Mapping[str, object], ...]:
    """Explicit native request adapter matrix; no route is inferred from arrays."""

    return tuple(
        {
            "workload": workload.value,
            "prepared_request_workloads": tuple(sorted(requests)),
            "execution_authority": "rust_specialized_request",
            "scheduler": "rust_prepared_evaluation_core_v1",
            "batch_boundary": "one_python_to_rust_call_per_prepared_batch",
            "public_wfo_integration": "phase_74",
        }
        for workload, requests in _REQUEST_WORKLOADS.items()
    )


class NativePreparedEvaluationRuntimeV1:
    """Lifecycle adapter around the Rust-owned prepared evaluation runtime.

    Each bound request represents an isolated account/session. The runtime
    deliberately retains no mutable execution state across candidate rows, so
    stale account, order, or lifecycle state cannot bleed into another trial.
    Immutable market/template/request handles remain shared by the preparation
    cache and are cloned by Arc-backed Rust owners, not copied per evaluation.
    """

    def __init__(
        self,
        cache: NativeExecutionPreparationCache,
        *,
        workers: int = 1,
        runtime_budget: RuntimeBudgetV1 | None = None,
        parallelism_plan: ParallelismPlanV1 | None = None,
    ) -> None:
        if not isinstance(cache, NativeExecutionPreparationCache):
            raise TypeError("cache must be NativeExecutionPreparationCache")
        budget = runtime_budget or RuntimeBudgetV1(max_workers=max(1, int(workers)))
        plan = parallelism_plan or ParallelismPlanV1.resolve(
            rust_workers=max(1, int(workers)),
            max_rust_workers=budget.max_workers,
        )
        if int(plan.rust_workers) <= 0:
            raise ValueError("prepared evaluation requires at least one worker")
        budget.require_preflight(bars=1, workers=int(plan.rust_workers))
        native = cache._native()
        core_type = getattr(native, "NativePreparedEvaluationRuntimeCore", None)
        if core_type is None:
            raise RuntimeError(
                "installed quantbt-native extension lacks NativePreparedEvaluationRuntimeCore; "
                "rebuild/install the matching native wheel"
            )
        self.cache = cache
        self.runtime_budget = budget
        self.parallelism_plan = plan
        self.workers = int(plan.rust_workers)
        self._identity = RuntimeIdentityV1.create()
        self._cancel = RuntimeCancellationV1()
        self._native_runtime = core_type(
            workers=self.workers,
            max_metric_rows=int(budget.max_metric_rows),
            max_error_rows=int(budget.max_error_rows),
        )
        self._lock = Lock()
        self._active_batches = 0
        self._closed = False

    @property
    def closed(self) -> bool:
        with self._lock:
            return self._closed

    @property
    def runtime_id(self) -> str:
        return self._identity.session_id

    @property
    def generation(self) -> int:
        return self._identity.generation

    def bind_request(
        self,
        request: NativePreparedRequest,
        *,
        workload: NativePreparedWorkloadV1 | str,
        candidate_id: int = 0,
        fold_id: int = 0,
        scenario_id: int = 0,
        cutoff_bar: int | None = None,
        evaluation_start: int = 0,
        evaluation_end: int | None = None,
        account_policy: str = "fresh_account_per_evaluation",
        metric_contract: NativeEvaluationMetricContractV1 | None = None,
        estimated_cost: int | None = None,
    ) -> NativePreparedEvaluationBindingV1:
        """Bind one immutable local-tape request without execution or copying."""

        self._assert_open()
        if not isinstance(request, NativePreparedRequest):
            raise TypeError("request must be NativePreparedRequest from NativeExecutionPreparationCache")
        try:
            kind = (
                workload
                if isinstance(workload, NativePreparedWorkloadV1)
                else NativePreparedWorkloadV1(str(workload))
            )
        except ValueError as exc:
            supported = ", ".join(item.value for item in NativePreparedWorkloadV1)
            raise ValueError(f"unsupported prepared workload={workload!r}; supported: {supported}") from exc
        if request.workload not in _REQUEST_WORKLOADS[kind]:
            raise ValueError(
                f"prepared workload {kind.value!r} cannot bind request workload {request.workload!r}"
            )
        identifiers = (candidate_id, fold_id, scenario_id)
        if any(isinstance(value, bool) or int(value) < 0 for value in identifiers):
            raise ValueError("candidate_id, fold_id, and scenario_id must be non-negative integers")
        bars = _request_bars(request)
        start = int(evaluation_start)
        end = bars if evaluation_end is None else int(evaluation_end)
        if not 0 <= start < end <= bars:
            raise ValueError("evaluation range must satisfy 0 <= start < end <= prepared request bars")
        if start != 0 or end != bars:
            raise NotImplementedError(
                "prepared evaluation executes one immutable request over its full local tape; "
                "build NativeExecutionPreparationCache.window_template() for the declared fold "
                "instead of binding a partial range against a full request"
            )
        if cutoff_bar is not None and not start <= int(cutoff_bar) < end:
            raise ValueError("cutoff_bar must lie inside the declared evaluation range")
        policy = str(account_policy).strip()
        if policy != "fresh_account_per_evaluation":
            raise NotImplementedError(
                "prepared evaluation supports fresh_account_per_evaluation only; account continuity "
                "belongs to a separately versioned execution contract"
            )
        metrics = metric_contract or NativeEvaluationMetricContractV1()
        cost = int(estimated_cost) if estimated_cost is not None else max(1, int(request.request_bytes))
        if cost <= 0:
            raise ValueError("estimated_cost must be > 0")
        native_binding = self._native_runtime.bind(
            request.core,
            kind.value,
            candidate_id=int(candidate_id),
            fold_id=int(fold_id),
            scenario_id=int(scenario_id),
            estimated_cost=cost,
        )
        binding_fingerprint = _binding_fingerprint(
            request_signature=request.signature,
            workload=kind.value,
            candidate_id=int(candidate_id),
            fold_id=int(fold_id),
            scenario_id=int(scenario_id),
            cutoff_bar=None if cutoff_bar is None else int(cutoff_bar),
            evaluation_start=start,
            evaluation_end=end,
            account_policy=policy,
            metric_contract=metrics.fingerprint,
        )
        return NativePreparedEvaluationBindingV1(
            request=request,
            workload=kind,
            candidate_id=int(candidate_id),
            fold_id=int(fold_id),
            scenario_id=int(scenario_id),
            cutoff_bar=None if cutoff_bar is None else int(cutoff_bar),
            evaluation_start=start,
            evaluation_end=end,
            account_policy=policy,
            metric_contract=metrics,
            estimated_cost=cost,
            cache_generation=int(self.cache.diagnostics["generation"]),
            runtime_id=self.runtime_id,
            runtime_generation=self.generation,
            binding_fingerprint=binding_fingerprint,
            native_binding=native_binding,
        )

    def evaluate(
        self,
        bindings: Sequence[NativePreparedEvaluationBindingV1],
    ) -> NativePreparedEvaluationResultV1:
        """Execute one typed native batch and adapt scalar SoA on the cold path."""

        self._assert_open()
        entries = tuple(bindings)
        if not entries:
            raise ValueError("prepared evaluation requires at least one binding")
        self._validate_bindings(entries)
        unique_requests = {binding.request.signature: binding.request for binding in entries}
        native_bytes = _shared_native_memory_bytes(unique_requests.values())
        max_bars = max(_request_bars(binding.request) for binding in entries)
        audit_rows = sum(1 for binding in entries if _request_output_profile(binding.request) == "audit")
        self.runtime_budget.require_preflight(
            bars=max_bars,
            workers=self.workers,
            native_memory_bytes=native_bytes,
            metric_rows=len(entries),
            audit_rows=audit_rows,
        )
        with self._lock:
            self._assert_open_locked()
            if self._active_batches:
                raise RuntimeError("prepared evaluation runtime already has an active batch")
            self._active_batches = 1
        started = perf_counter_ns()
        try:
            matrix = self._native_runtime.execute_score([entry.native_binding for entry in entries])
            payload = dict(matrix.as_dict())
            return _adapt_native_matrix(
                entries,
                payload,
                native_bytes=native_bytes,
                execution_seconds=(perf_counter_ns() - started) / 1_000_000_000.0,
                runtime=self,
            )
        finally:
            with self._lock:
                self._active_batches = 0

    def evaluate_score_columns(
        self,
        bindings: Sequence[NativePreparedEvaluationBindingV1],
    ) -> NativePreparedScoreColumnsV1:
        """Execute one batch through the scalar-only Rust/Python boundary.

        It intentionally does not call ``as_dict()`` or instantiate
        :class:`NativePreparedEvaluationRowV1`.  Public callers requiring
        fingerprints, all metrics, or dataframe conversion keep using
        :meth:`evaluate` on the cold/audit path.
        """

        self._assert_open()
        entries = tuple(bindings)
        if not entries:
            raise ValueError("prepared evaluation requires at least one binding")
        self._validate_bindings(entries)
        unique_requests = {binding.request.signature: binding.request for binding in entries}
        native_bytes = _shared_native_memory_bytes(unique_requests.values())
        max_bars = max(_request_bars(binding.request) for binding in entries)
        audit_rows = sum(1 for binding in entries if _request_output_profile(binding.request) == "audit")
        self.runtime_budget.require_preflight(
            bars=max_bars,
            workers=self.workers,
            native_memory_bytes=native_bytes,
            metric_rows=len(entries),
            audit_rows=audit_rows,
        )
        with self._lock:
            self._assert_open_locked()
            if self._active_batches:
                raise RuntimeError("prepared evaluation runtime already has an active batch")
            self._active_batches = 1
        started = perf_counter_ns()
        try:
            matrix = self._native_runtime.execute_score([entry.native_binding for entry in entries])
            score_columns = getattr(matrix, "score_columns", None)
            if score_columns is None:
                raise RuntimeError(
                    "installed quantbt-native extension lacks the scalar-columns prepared-score API; "
                    "install a matching native wheel or use the explicit compatibility scorer"
                )
            raw_columns = score_columns()
            errors = tuple(str(value) for value in matrix.errors())
            return _adapt_native_score_columns(
                entries,
                raw_columns,
                errors=errors,
                native_bytes=native_bytes,
                execution_seconds=(perf_counter_ns() - started) / 1_000_000_000.0,
                runtime=self,
            )
        finally:
            with self._lock:
                self._active_batches = 0

    def cancel(self, reason: str = "requested") -> None:
        """Cancel queued native requests at a candidate-task safe point."""

        self._cancel.cancel(reason)
        self._native_runtime.cancel()

    def reset(self) -> None:
        """Clear cancellation and invalidate bindings without rebuilding workers."""

        with self._lock:
            self._assert_open_locked()
            if self._active_batches:
                raise RuntimeError("cannot reset a prepared evaluation runtime while work is active")
            self._native_runtime.reset()
            self._cancel.clear()
            self._identity = self._identity.next_generation()

    def close(self) -> None:
        """Deterministically release Rust workers while leaving detached rows valid."""

        with self._lock:
            if self._closed:
                return
            if self._active_batches:
                raise RuntimeError("cannot close a prepared evaluation runtime while work is active")
            self._native_runtime.close()
            self._closed = True

    def diagnostics(self) -> Mapping[str, object]:
        """Cold-path ownership/scheduler counters; no market payload is retained."""

        native = dict(self._native_runtime.diagnostics())
        with self._lock:
            return {
                "runtime": "native_prepared_evaluation_v1",
                "native_runtime": native.get("runtime"),
                "closed": self._closed,
                "active_batches": self._active_batches,
                "worker_pool_creations": int(native.get("worker_pool_creations", 0)),
                "score_batches": int(native.get("score_batches", 0)),
                "native_request_executions": int(native.get("native_entry_calls", 0)),
                "failed_rows": int(native.get("failed_rows", 0)),
                "poisoned": bool(native.get("poisoned", False)),
                "poison_recoveries": int(native.get("poison_recoveries", 0)),
                "native_runtime_id": int(native.get("runtime_id", 0)),
                "native_runtime_generation": int(native.get("runtime_generation", 0)),
                "runtime_id": self.runtime_id,
                "runtime_generation": self.generation,
                "cache_generation": int(self.cache.diagnostics["generation"]),
                "canceled": self._cancel.canceled,
                "cancellation_reason": self._cancel.reason,
                "parallelism": asdict(self.parallelism_plan),
                "runtime_budget": asdict(self.runtime_budget),
            }

    def _validate_bindings(self, bindings: Iterable[NativePreparedEvaluationBindingV1]) -> None:
        seen: set[tuple[int, int, int]] = set()
        cache_generation = int(self.cache.diagnostics["generation"])
        for binding in bindings:
            if not isinstance(binding, NativePreparedEvaluationBindingV1):
                raise TypeError("evaluate() accepts NativePreparedEvaluationBindingV1 instances only")
            if binding.runtime_id != self.runtime_id:
                raise ValueError("prepared evaluation binding belongs to a different runtime")
            if binding.runtime_generation != self.generation:
                raise ValueError("prepared evaluation binding belongs to an earlier runtime generation")
            if binding.cache_generation != cache_generation:
                raise ValueError("prepared evaluation binding was invalidated by prepared-cache clear/reset")
            if binding.native_binding is None:
                raise RuntimeError("prepared evaluation binding lacks its typed native handle")
            identity = (binding.candidate_id, binding.fold_id, binding.scenario_id)
            if identity in seen:
                raise ValueError("prepared evaluation candidate/fold/scenario identities must be unique")
            seen.add(identity)

    def _assert_open(self) -> None:
        with self._lock:
            self._assert_open_locked()

    def _assert_open_locked(self) -> None:
        if self._closed:
            raise RuntimeError("prepared evaluation runtime is closed")


def _adapt_native_matrix(
    bindings: tuple[NativePreparedEvaluationBindingV1, ...],
    payload: Mapping[str, object],
    *,
    native_bytes: int,
    execution_seconds: float,
    runtime: NativePreparedEvaluationRuntimeV1,
) -> NativePreparedEvaluationResultV1:
    """Turn one native SoA payload into immutable Python scalar rows."""

    count = len(bindings)
    columns = {
        key: _column(payload, key, count)
        for key in (
            "candidate_id",
            "fold_id",
            "scenario_id",
            "status",
            "final_equity",
            "total_fee",
            "total_funding",
            "turnover",
            "total_return",
            "sharpe",
            "sortino",
            "max_drawdown",
            "cagr",
            "calmar",
            "omega",
            "profit_factor",
            "average_gross_exposure",
            "native_metric_contract_version",
            "native_metric_annualization_factor",
            "fill_count",
            "report_trade_count",
            "event_count",
            "rejected_count",
            "canceled_count",
            "sample_count",
            "liquidated",
            "request_fingerprint",
            "terminal_fingerprint",
            "error_slot",
        )
    }
    by_identity = {
        (binding.candidate_id, binding.fold_id, binding.scenario_id): binding for binding in bindings
    }
    rows: list[NativePreparedEvaluationRowV1] = []
    for index in range(count):
        identity = (
            int(columns["candidate_id"][index]),
            int(columns["fold_id"][index]),
            int(columns["scenario_id"][index]),
        )
        binding = by_identity.pop(identity, None)
        if binding is None:
            raise RuntimeError("native prepared evaluation returned an unknown or duplicate row identity")
        status = _STATUS_BY_CODE.get(int(columns["status"][index]))
        if status is None:
            raise RuntimeError("native prepared evaluation returned an unknown row status")
        row = NativePreparedEvaluationRowV1(
            candidate_id=identity[0],
            fold_id=identity[1],
            scenario_id=identity[2],
            status=status,
            final_equity=float(columns["final_equity"][index]),
            total_fee=float(columns["total_fee"][index]),
            total_funding=float(columns["total_funding"][index]),
            turnover=float(columns["turnover"][index]),
            total_return=float(columns["total_return"][index]),
            sharpe=float(columns["sharpe"][index]),
            sortino=float(columns["sortino"][index]),
            max_drawdown=float(columns["max_drawdown"][index]),
            cagr=float(columns["cagr"][index]),
            calmar=float(columns["calmar"][index]),
            omega=float(columns["omega"][index]),
            profit_factor=float(columns["profit_factor"][index]),
            average_gross_exposure=float(columns["average_gross_exposure"][index]),
            native_metric_contract_version=int(columns["native_metric_contract_version"][index]),
            native_metric_annualization_factor=float(
                columns["native_metric_annualization_factor"][index]
            ),
            fill_count=int(columns["fill_count"][index]),
            report_trade_count=int(columns["report_trade_count"][index]),
            event_count=int(columns["event_count"][index]),
            rejected_count=int(columns["rejected_count"][index]),
            canceled_count=int(columns["canceled_count"][index]),
            sample_count=int(columns["sample_count"][index]),
            liquidated=bool(columns["liquidated"][index]),
            request_fingerprint=str(columns["request_fingerprint"][index]),
            terminal_fingerprint=str(columns["terminal_fingerprint"][index]),
            metric_contract_fingerprint=binding.metric_contract.fingerprint,
            error_slot=int(columns["error_slot"][index]),
        )
        if row.status == _SUCCESS:
            _validate_success_row(binding, row)
        rows.append(row)
    if by_identity:
        raise RuntimeError("native prepared evaluation omitted a requested row")
    rows.sort(key=lambda row: (row.candidate_id, row.fold_id, row.scenario_id))
    native = runtime.diagnostics()
    return NativePreparedEvaluationResultV1(
        rows=tuple(rows),
        errors=tuple(str(value) for value in payload.get("errors", ())),
        metadata={
            "runtime": "native_prepared_evaluation_v1",
            "native_runtime": native["native_runtime"],
            "worker_pool_creations": native["worker_pool_creations"],
            "score_batches": native["score_batches"],
            "native_request_executions": native["native_request_executions"],
            "native_boundary_calls": 1,
            "native_execution_passes": 1,
            "poison_recoveries": int(native["poison_recoveries"]),
            "runtime_id": runtime.runtime_id,
            "runtime_generation": runtime.generation,
            "native_runtime_id": native["native_runtime_id"],
            "native_runtime_generation": native["native_runtime_generation"],
            "cache_generation": int(runtime.cache.diagnostics["generation"]),
            "scheduler": "cost_descending_dynamic_queue_v1",
            "rows_sorted_by": "candidate_id,fold_id,scenario_id",
            "prepared_market_copies_per_execution": 0,
            "prepared_intent_copies_per_execution": 0,
            "native_memory_bytes_preflight": int(native_bytes),
            "execution_seconds": float(execution_seconds),
            "cancellation_scope": "candidate_task_safe_point_v1",
            "parallelism": asdict(runtime.parallelism_plan),
            "runtime_budget": asdict(runtime.runtime_budget),
        },
    )


def _adapt_native_score_columns(
    bindings: tuple[NativePreparedEvaluationBindingV1, ...],
    raw_columns: object,
    *,
    errors: tuple[str, ...],
    native_bytes: int,
    execution_seconds: float,
    runtime: NativePreparedEvaluationRuntimeV1,
) -> NativePreparedScoreColumnsV1:
    """Validate the compact score boundary without materializing row objects.

    The result deliberately carries only fields consumed by public WFO scoring.
    Identity and status checks remain as strict as the cold ``as_dict`` adapter:
    a fast boundary is never allowed to silently reorder, omit, or duplicate a
    candidate/fold/scenario result.
    """

    names = (
        "candidate_id",
        "fold_id",
        "scenario_id",
        "status",
        "total_return",
        "sharpe",
        "max_drawdown",
        "profit_factor",
        "report_trade_count",
        "error_slot",
    )
    if not isinstance(raw_columns, tuple) or len(raw_columns) != len(names):
        raise RuntimeError(
            "native prepared score boundary must return the fixed scalar-column tuple"
        )
    count = len(bindings)
    columns = {
        name: _score_column(value, name, count)
        for name, value in zip(names, raw_columns, strict=True)
    }
    expected = {
        (binding.candidate_id, binding.fold_id, binding.scenario_id)
        for binding in bindings
    }
    actual: set[tuple[int, int, int]] = set()
    for row in range(count):
        identity = (
            int(columns["candidate_id"][row]),
            int(columns["fold_id"][row]),
            int(columns["scenario_id"][row]),
        )
        if identity in actual:
            raise RuntimeError("native prepared score returned a duplicate row identity")
        actual.add(identity)
        if _STATUS_BY_CODE.get(int(columns["status"][row])) is None:
            raise RuntimeError("native prepared score returned an unknown row status")
        error_slot = int(columns["error_slot"][row])
        if error_slot != _ERROR_SENTINEL and not 0 <= error_slot < len(errors):
            raise RuntimeError("native prepared score returned an invalid error slot")
    if actual != expected:
        raise RuntimeError("native prepared score identities differ from requested bindings")

    native = runtime.diagnostics()
    return NativePreparedScoreColumnsV1(
        candidate_id=columns["candidate_id"],
        fold_id=columns["fold_id"],
        scenario_id=columns["scenario_id"],
        status=columns["status"],
        total_return=columns["total_return"],
        sharpe=columns["sharpe"],
        max_drawdown=columns["max_drawdown"],
        profit_factor=columns["profit_factor"],
        report_trade_count=columns["report_trade_count"],
        error_slot=columns["error_slot"],
        errors=errors,
        metadata={
            "runtime": "native_prepared_evaluation_v1",
            "native_runtime": native["native_runtime"],
            "worker_pool_creations": native["worker_pool_creations"],
            "score_batches": native["score_batches"],
            "native_request_executions": native["native_request_executions"],
            "native_boundary_calls": 1,
            "native_execution_passes": 1,
            "poison_recoveries": int(native["poison_recoveries"]),
            "runtime_id": runtime.runtime_id,
            "runtime_generation": runtime.generation,
            "native_runtime_id": native["native_runtime_id"],
            "native_runtime_generation": native["native_runtime_generation"],
            "cache_generation": int(runtime.cache.diagnostics["generation"]),
            "scheduler": "cost_descending_dynamic_queue_v1",
            "prepared_market_copies_per_execution": 0,
            "prepared_intent_copies_per_execution": 0,
            "native_memory_bytes_preflight": int(native_bytes),
            "execution_seconds": float(execution_seconds),
            "cancellation_scope": "candidate_task_safe_point_v1",
            "parallelism": asdict(runtime.parallelism_plan),
            "runtime_budget": asdict(runtime.runtime_budget),
            "adapter": "scalar_columns_v1",
            "python_row_objects": 0,
            "python_dict_materialized": False,
        },
    )


def _column(payload: Mapping[str, object], key: str, count: int) -> np.ndarray:
    if key not in payload:
        raise RuntimeError(f"native prepared evaluation omitted scalar column {key!r}")
    values = np.asarray(payload[key])
    if values.ndim != 1 or len(values) != count:
        raise RuntimeError(
            f"native prepared evaluation column {key!r} must have exactly {count} scalar rows"
        )
    return values


def _score_column(value: object, name: str, count: int) -> np.ndarray:
    """Validate a one-dimensional NumPy view from the PyO3 scalar tuple."""

    values = np.asarray(value)
    if values.ndim != 1 or len(values) != count:
        raise RuntimeError(
            f"native prepared score column {name!r} must have exactly {count} scalar rows"
        )
    return values


def _validate_success_row(
    binding: NativePreparedEvaluationBindingV1,
    row: NativePreparedEvaluationRowV1,
) -> None:
    if row.native_metric_contract_version != binding.metric_contract.native_metric_contract_version:
        raise RuntimeError(
            "native prepared metric contract version mismatch: "
            f"expected={binding.metric_contract.native_metric_contract_version}, "
            f"actual={row.native_metric_contract_version}"
        )
    if not np.isclose(
        row.native_metric_annualization_factor,
        float(binding.metric_contract.trading_days),
        rtol=0.0,
        atol=0.0,
    ):
        raise RuntimeError(
            "native prepared metric annualization mismatch: "
            f"expected={binding.metric_contract.trading_days}, "
            f"actual={row.native_metric_annualization_factor}"
        )
    if not row.request_fingerprint or not row.terminal_fingerprint:
        raise RuntimeError("native prepared evaluation omitted successful request/terminal provenance")
    for value in (
        row.final_equity,
        row.total_fee,
        row.total_funding,
        row.turnover,
        row.total_return,
    ):
        if not np.isfinite(value):
            raise RuntimeError("native prepared evaluation emitted non-finite accounting/metric scalar")


def _binding_fingerprint(**payload: object) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()


def _request_bars(request: NativePreparedRequest) -> int:
    if request.template is not None:
        return int(request.template.core.bars)
    bars = getattr(request.core, "bars", None)
    if bars is None:
        raise TypeError(f"prepared request {request.workload!r} does not expose a bar count")
    return int(bars)


def _shared_native_memory_bytes(requests: Iterable[NativePreparedRequest]) -> int:
    """Charge each shared market/template once and each immutable request once."""

    markets: dict[str, int] = {}
    templates: dict[str, int] = {}
    request_bytes = 0
    for request in requests:
        if request.template is not None:
            market_key = request.market_signature or request.template.market.signature
            markets.setdefault(market_key, int(request.template.market.prepared_bytes))
            templates.setdefault(request.template.signature, int(request.template.model_bytes))
        else:
            market_key = request.market_signature or request.signature
            markets.setdefault(market_key, int(getattr(request.core, "source_market_bytes", 0)))
        request_bytes += int(request.request_bytes)
    return int(sum(markets.values()) + sum(templates.values()) + request_bytes)


def _request_output_profile(request: NativePreparedRequest) -> str:
    return str(getattr(request.core, "output_profile", "score")).lower().strip()


__all__ = [
    "NativeEvaluationMetricContractV1",
    "NativePreparedEvaluationBindingV1",
    "NativePreparedEvaluationResultV1",
    "NativePreparedEvaluationRowV1",
    "NativePreparedScoreColumnsV1",
    "NativePreparedEvaluationRuntimeV1",
    "NativePreparedWorkloadV1",
    "native_prepared_evaluation_support_matrix",
]
