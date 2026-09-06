"""Prepared native walk-forward execution for bounded Strategy-IR workloads.

This module is deliberately an opt-in companion to :mod:`quantbt.walkforward`.
The existing pandas/callback engine remains the W0 compatibility oracle.  The
classes here accept a causally prepared, numeric signal tape and move repeated
``candidate x fold`` simulation into one persistent Rust runtime.

Only ``strategy_ir_signal_target_v1`` with a fresh account per OOS fold is
certified in this module.  A generic Python callback, portfolio target,
package, carry/replay account policy, or dynamic reactive lifecycle must stay
on its own explicitly declared route; none is silently coerced into this
runtime.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Callable, Mapping, Protocol, Sequence, runtime_checkable

import numpy as np
import pandas as pd

from ..optimization.space import suggest_params
from ..core.runtime_governance import (
    ParallelismPlanV1,
    RuntimeBudgetV1,
    RuntimeIdentityV1,
)
from ..preparation.native_execution import NativePreparedTemplate
from ._native_event_rust import NativeEventRustBackendError, RustFullRunner, probe_native_event_rust_extension
from .native_strategy_ir import NativeIRFold, RustNativeIRRunner
from .native_wfo_support import (
    _assert_selected_score_replay,
    _candidate_ids,
    _coerce_batch_intent,
    _coerce_signal_intent,
    _combine_native_parameters,
    _concat_metric_matrices,
    _default_objective,
    _estimated_runner_market_bytes,
    _native_parameter_matrix,
    _normalize_schedule,
    _resolve_adapter,
)


_NATIVE_WFO_CAPABILITIES = frozenset(
    {
        "native_strategy_ir_v1",
        "native_strategy_ir_batch_v1",
        "native_wfo_runtime_v2",
        "native_wfo_prepared_signal_v2",
        "native_wfo_metric_matrix_v2",
        "native_wfo_audit_rerun_v2",
    }
)
_SUCCESS_STATUS = np.uint16(0)
_DEFAULT_FAILURE_OBJECTIVE = -1.0e12
@runtime_checkable
class PreparedWfoStrategyV1(Protocol):
    """W1 contract for causal, parameter-independent strategy preparation.

    ``prepare_wfo`` belongs to the alpha/research layer. Its return object may
    cache features constructed from the complete *declared* market tape only.
    ``generate`` must return a full-tape signal aligned to the runtime market;
    Rust executes only the fold's declared OOS bar interval.
    """

    def generate(self, *, params: Mapping[str, Any], fold_id: int) -> np.ndarray | Mapping[str, Any]:
        """Return one full-tape, finite signal row for one candidate/fold."""


@runtime_checkable
class BatchedPreparedWfoStrategyV1(PreparedWfoStrategyV1, Protocol):
    """W2 contract: generate every candidate signal for one fold in one call."""

    def generate_batch(
        self,
        *,
        params_matrix: Sequence[Mapping[str, Any]],
        fold_id: int,
    ) -> np.ndarray | Mapping[str, Any]:
        """Return a finite matrix shaped ``(candidates, prepared_market_bars)``."""


@dataclass(frozen=True, slots=True)
class NativeWfoMetricMatrixV2:
    """Rust scalar output for one score or selected-candidate audit pass.

    The arrays are stable candidate/fold rows sorted by ``candidate_id`` then
    ``fold_id``. No account path, fill table, or pandas object is retained for
    an optimization pass. Use :meth:`to_frame` only for cold-path inspection.
    """

    candidate_id: np.ndarray
    fold_id: np.ndarray
    scenario_id: np.ndarray
    status: np.ndarray
    final_equity: np.ndarray
    fold_return: np.ndarray
    fold_sharpe: np.ndarray
    fold_sortino: np.ndarray
    max_drawdown: np.ndarray
    turnover: np.ndarray
    total_fee: np.ndarray
    total_funding: np.ndarray
    fill_rate: np.ndarray
    fill_count: np.ndarray
    rejected_count: np.ndarray
    liquidated: np.ndarray
    request_fingerprint: tuple[str, ...]
    terminal_fingerprint: tuple[str, ...]
    error_slot: np.ndarray
    errors: tuple[str, ...]
    metadata: Mapping[str, Any]

    @property
    def intent_fingerprint(self) -> str:
        """Return the exact prepared-input fingerprint needed for audit replay."""

        if self.metadata.get("intent_fingerprint_scope", "single_batch") != "single_batch":
            raise ValueError(
                "an aggregate native WFO matrix has multiple prepared intent fingerprints; "
                "use its per-batch provenance for audit replay"
            )
        return str(self.metadata["intent_fingerprint"])

    @property
    def plan_fingerprint(self) -> str:
        """Return immutable market/fold/account plan provenance."""

        return str(self.metadata["plan_fingerprint"])

    @property
    def audit(self) -> bool:
        """Whether this matrix was produced by selected-candidate audit rerun."""

        return bool(self.metadata["audit"])

    def rows_for(self, candidate_id: int) -> "NativeWfoMetricMatrixV2":
        """Return a compact view of one candidate's causal fold rows."""

        mask = self.candidate_id == np.uint64(candidate_id)
        return self._slice(mask)

    def aggregate(
        self,
        reducer: Callable[[np.ndarray], float] | None = None,
        *,
        field: str = "fold_sharpe",
        failure_value: float = _DEFAULT_FAILURE_OBJECTIVE,
    ) -> dict[int, float]:
        """Aggregate one scalar metric per candidate without a pandas table.

        Failed, canceled, or liquidated rows receive ``failure_value``. The
        default score is mean finite fold Sharpe; callers may inject their own
        robust selection formula while retaining the native row provenance.
        """

        if not hasattr(self, field):
            raise ValueError(f"unknown native WFO metric field: {field}")
        values = np.asarray(getattr(self, field), dtype=np.float64)
        reducer = np.mean if reducer is None else reducer
        result: dict[int, float] = {}
        for candidate in self.candidate_id:
            candidate_value = int(candidate)
            if candidate_value in result:
                continue
            mask = self.candidate_id == candidate
            valid = (
                (self.status[mask] == _SUCCESS_STATUS)
                & ~self.liquidated[mask]
                & np.isfinite(values[mask])
            )
            result[candidate_value] = (
                float(reducer(values[mask][valid])) if valid.any() else float(failure_value)
            )
        return result

    def assert_audit_parity(self, score: "NativeWfoMetricMatrixV2") -> None:
        """Assert audit rows replay exact terminal states from a score matrix."""

        if not self.audit:
            raise ValueError("assert_audit_parity requires a selected-candidate audit matrix")
        if self.plan_fingerprint != score.plan_fingerprint:
            raise AssertionError("native WFO audit and score plan fingerprints differ")
        lookup = {
            (int(candidate), int(fold)): terminal
            for candidate, fold, terminal in zip(
                score.candidate_id,
                score.fold_id,
                score.terminal_fingerprint,
                strict=True,
            )
        }
        for candidate, fold, terminal in zip(
            self.candidate_id,
            self.fold_id,
            self.terminal_fingerprint,
            strict=True,
        ):
            expected = lookup.get((int(candidate), int(fold)))
            if expected is None:
                raise AssertionError("native WFO audit row was absent from score matrix")
            if terminal != expected:
                raise AssertionError("native WFO audit terminal fingerprint differs from score")

    def to_frame(self) -> pd.DataFrame:
        """Build a pandas inspection table only after score/audit completion."""

        return pd.DataFrame(
            {
                "candidate_id": self.candidate_id,
                "fold_id": self.fold_id,
                "scenario_id": self.scenario_id,
                "status": self.status,
                "final_equity": self.final_equity,
                "fold_return": self.fold_return,
                "fold_sharpe": self.fold_sharpe,
                "fold_sortino": self.fold_sortino,
                "max_drawdown": self.max_drawdown,
                "turnover": self.turnover,
                "total_fee": self.total_fee,
                "total_funding": self.total_funding,
                "fill_rate": self.fill_rate,
                "fill_count": self.fill_count,
                "rejected_count": self.rejected_count,
                "liquidated": self.liquidated,
                "request_fingerprint": self.request_fingerprint,
                "terminal_fingerprint": self.terminal_fingerprint,
                "error_slot": self.error_slot,
            }
        )

    def _slice(self, mask: np.ndarray) -> "NativeWfoMetricMatrixV2":
        return NativeWfoMetricMatrixV2(
            candidate_id=self.candidate_id[mask],
            fold_id=self.fold_id[mask],
            scenario_id=self.scenario_id[mask],
            status=self.status[mask],
            final_equity=self.final_equity[mask],
            fold_return=self.fold_return[mask],
            fold_sharpe=self.fold_sharpe[mask],
            fold_sortino=self.fold_sortino[mask],
            max_drawdown=self.max_drawdown[mask],
            turnover=self.turnover[mask],
            total_fee=self.total_fee[mask],
            total_funding=self.total_funding[mask],
            fill_rate=self.fill_rate[mask],
            fill_count=self.fill_count[mask],
            rejected_count=self.rejected_count[mask],
            liquidated=self.liquidated[mask],
            request_fingerprint=tuple(
                value for value, keep in zip(self.request_fingerprint, mask, strict=True) if keep
            ),
            terminal_fingerprint=tuple(
                value for value, keep in zip(self.terminal_fingerprint, mask, strict=True) if keep
            ),
            error_slot=self.error_slot[mask],
            errors=self.errors,
            metadata=self.metadata,
        )

    @classmethod
    def _from_core(cls, core) -> "NativeWfoMetricMatrixV2":
        payload = core.as_dict()

        def array(name: str, dtype) -> np.ndarray:
            return np.ascontiguousarray(np.asarray(payload[name]), dtype=dtype)

        metadata = {
            key: value
            for key, value in payload.items()
            if key
            not in {
                "candidate_id", "fold_id", "scenario_id", "status", "final_equity", "fold_return",
                "fold_sharpe", "fold_sortino", "max_drawdown", "turnover", "total_fee",
                "total_funding", "fill_rate", "fill_count", "rejected_count", "liquidated",
                "request_fingerprint", "terminal_fingerprint", "error_slot", "errors",
            }
        }
        metadata["intent_fingerprint_scope"] = "single_batch"
        return cls(
            candidate_id=array("candidate_id", np.uint64),
            fold_id=array("fold_id", np.uint32),
            scenario_id=array("scenario_id", np.uint32),
            status=array("status", np.uint16),
            final_equity=array("final_equity", np.float64),
            fold_return=array("fold_return", np.float64),
            fold_sharpe=array("fold_sharpe", np.float64),
            fold_sortino=array("fold_sortino", np.float64),
            max_drawdown=array("max_drawdown", np.float64),
            turnover=array("turnover", np.float64),
            total_fee=array("total_fee", np.float64),
            total_funding=array("total_funding", np.float64),
            fill_rate=array("fill_rate", np.float64),
            fill_count=array("fill_count", np.uint64),
            rejected_count=array("rejected_count", np.uint64),
            liquidated=array("liquidated", bool),
            request_fingerprint=tuple(str(value) for value in payload["request_fingerprint"]),
            terminal_fingerprint=tuple(str(value) for value in payload["terminal_fingerprint"]),
            error_slot=array("error_slot", np.uint32),
            errors=tuple(str(value) for value in payload["errors"]),
            metadata=metadata,
        )


@dataclass(slots=True)
class NativeWfoPreparedSignalBatchV2:
    """One immutable Rust-owned prepared WFO signal buffer.

    This is the explicit, controlled Python-to-Rust ingestion object.  It is
    valid only for a runtime with the same immutable plan fingerprint and may
    be scored or audit-rerun repeatedly without another O(T) input copy.
    """

    _core: Any | None
    _plan_fingerprint: str
    _runtime_id: str

    def _require_open(self) -> Any:
        if self._core is None:
            raise RuntimeError("prepared native WFO batch is closed")
        return self._core

    @property
    def closed(self) -> bool:
        return self._core is None

    def close(self) -> None:
        """Release this handle's Arc reference to its native intent buffer."""

        self._core = None

    @property
    def intent_fingerprint(self) -> str:
        return str(self._require_open().intent_fingerprint)

    @property
    def intent_ingest_bytes(self) -> int:
        return int(self._require_open().intent_ingest_bytes)

    @property
    def rows(self) -> int:
        return int(self._require_open().rows)

    @property
    def bars(self) -> int:
        return int(self._require_open().bars)

    @property
    def per_fold(self) -> bool:
        return bool(self._require_open().per_fold)


@dataclass(frozen=True, slots=True)
class NativeWfoOptimizationResultV2:
    """Python-controlled Optuna lifecycle with Rust-owned candidate scoring."""

    schedule: str
    study: Any
    params_by_candidate: Mapping[int, Mapping[str, Any]]
    score_matrix: NativeWfoMetricMatrixV2
    objective_by_candidate: Mapping[int, float]
    audit_matrix: NativeWfoMetricMatrixV2 | None
    metadata: Mapping[str, Any]

    @property
    def best_candidate_id(self) -> int:
        return int(self.study.best_trial.number)

    @property
    def best_params(self) -> dict[str, Any]:
        return dict(self.study.best_params)

    @property
    def best_value(self) -> float:
        return float(self.study.best_value)


@dataclass(frozen=True, slots=True)
class _OptimizationSourceBatchV2:
    """Small retained provenance needed to replay only selected audit batches.

    Full signal matrices are intentionally not retained across the Optuna run.
    The source candidate IDs and parameter mappings are enough to regenerate
    the original bounded batch.  Its fingerprint must then match the score
    batch before the audit is allowed to execute.
    """

    candidate_ids: tuple[int, ...]
    params: tuple[Mapping[str, Any], ...]
    intent_fingerprint: str


class NativeWfoRuntimeV2:
    """One persistent Rust WFO runtime for bounded Strategy-IR signal tapes.

    Each fold starts from a fresh account/order state. The supplied signal is
    aligned to the complete prepared tape so a strategy may retain causal
    indicator warm-up, but Rust executes exactly ``test_start:test_end``.
    """

    def __init__(
        self,
        runner: RustNativeIRRunner,
        folds: Sequence[NativeIRFold],
        *,
        optimizer_schedule: str = "certified_sequential_v1",
        workers: int = 1,
        max_metric_rows: int = 1_000_000,
        max_error_rows: int = 64,
        runtime_budget: RuntimeBudgetV1 | None = None,
        parallelism_plan: ParallelismPlanV1 | None = None,
    ) -> None:
        if not isinstance(runner, RustNativeIRRunner):
            raise TypeError("runner must be RustNativeIRRunner")
        if not folds:
            raise ValueError("native WFO runtime requires at least one causal fold")
        if int(workers) <= 0 or int(max_metric_rows) <= 0 or int(max_error_rows) <= 0:
            raise ValueError("native WFO workers and budgets must be > 0")
        self.runner = runner
        self.folds = tuple(folds)
        for fold in self.folds:
            if not isinstance(fold, NativeIRFold):
                raise TypeError("native WFO folds must be NativeIRFold instances")
            fold.validate_for_bars(len(runner.full_runner.idx))
        self.optimizer_schedule = _normalize_schedule(optimizer_schedule)
        self.runtime_budget = runtime_budget or RuntimeBudgetV1(
            max_workers=int(workers),
            max_metric_rows=int(max_metric_rows),
            max_error_rows=int(max_error_rows),
        )
        self.parallelism_plan = parallelism_plan or ParallelismPlanV1.resolve(
            rust_workers=int(workers),
            max_rust_workers=self.runtime_budget.max_workers,
        )
        self.workers = int(self.parallelism_plan.rust_workers)
        self.max_metric_rows = int(self.runtime_budget.max_metric_rows)
        self.max_error_rows = int(self.runtime_budget.max_error_rows)
        self._identity = RuntimeIdentityV1.create()
        estimated_market_bytes = _estimated_runner_market_bytes(runner)
        self.runtime_budget.require_preflight(
            bars=len(runner.full_runner.idx),
            workers=self.workers,
            native_memory_bytes=estimated_market_bytes,
        )
        module = runner.full_runner._module
        status = probe_native_event_rust_extension(module=module)
        missing = sorted(
            capability
            for capability in _NATIVE_WFO_CAPABILITIES
            if not status.capabilities.get(capability, False)
        )
        required_types = ("NativeWfoRuntimeV2", "NativeWfoPreparedSignalBatchV2")
        absent = [name for name in required_types if not hasattr(module, name)]
        if missing or absent:
            detail = ", ".join(missing + absent)
            raise NativeEventRustBackendError(
                "installed _quantbt_native wheel lacks prepared native WFO V2 capabilities: " + detail
            )
        template = runner.full_runner._typed_template
        if template is None:
            raise NativeEventRustBackendError(
                "native WFO V2 requires a RustFullRunner with native_static_abi='0.5'"
            )
        fold_array = np.ascontiguousarray(
            np.asarray(
                [
                    (
                        fold.fold_id,
                        fold.warmup_start,
                        fold.train_start,
                        fold.train_end,
                        fold.test_start,
                        fold.test_end,
                    )
                    for fold in self.folds
                ],
                dtype=np.uint32,
            )
        )
        self._core = module.NativeWfoRuntimeV2.from_template(
            template,
            runner._core,
            fold_array,
            intent_kind="strategy_ir_signal_target_v1",
            optimizer_schedule=self.optimizer_schedule,
            workers=self.workers,
            max_metric_rows=self.max_metric_rows,
            max_error_rows=self.max_error_rows,
            **self.runtime_budget.as_native_kwargs(),
        )

    @classmethod
    def from_full_runner(
        cls,
        full_runner: RustFullRunner,
        program,
        folds: Sequence[NativeIRFold],
        **kwargs: Any,
    ) -> "NativeWfoRuntimeV2":
        """Build the runtime from a prepared full-contract Rust runner."""

        return cls(RustNativeIRRunner(full_runner, program), folds, **kwargs)

    @property
    def plan_fingerprint(self) -> str:
        """Return immutable market/fold/account execution provenance."""

        return str(self._core.plan_fingerprint)

    @property
    def closed(self) -> bool:
        """Whether the persistent native worker pool has been closed."""

        return bool(self._core.closed)

    def diagnostics(self) -> Mapping[str, Any]:
        """Return cold-path ownership and worker-pool counters."""
        native = dict(self._core.diagnostics())
        return {
            **native,
            "session_id": self._identity.session_id,
            "worker_generation": self._identity.generation,
            "runtime_budget": asdict(self.runtime_budget),
            "parallelism": asdict(self.parallelism_plan),
        }

    def score_shared(
        self,
        signals: np.ndarray | Sequence[Sequence[float]],
        *,
        candidate_ids: Sequence[int] | np.ndarray | None = None,
        parameter_matrix: np.ndarray | Sequence[Sequence[float]] | None = None,
    ) -> NativeWfoMetricMatrixV2:
        """Score one full-tape signal matrix shared by every causal fold."""

        return self.score_prepared_batch(
            self.prepare_shared(signals, candidate_ids=candidate_ids, parameter_matrix=parameter_matrix)
        )

    def score_per_fold(
        self,
        signals: np.ndarray | Sequence[Sequence[Sequence[float]]],
        *,
        candidate_ids: Sequence[int] | np.ndarray | None = None,
        parameter_matrix: np.ndarray | Sequence[Sequence[float]] | None = None,
    ) -> NativeWfoMetricMatrixV2:
        """Score a fold-specific signal cube shaped ``(folds, candidates, bars)``."""

        return self.score_prepared_batch(
            self.prepare_per_fold(signals, candidate_ids=candidate_ids, parameter_matrix=parameter_matrix)
        )

    def prepare_shared(
        self,
        signals: np.ndarray | Sequence[Sequence[float]],
        *,
        candidate_ids: Sequence[int] | np.ndarray | None = None,
        parameter_matrix: np.ndarray | Sequence[Sequence[float]] | None = None,
    ) -> NativeWfoPreparedSignalBatchV2:
        """Ingest one shared full-tape signal matrix into a Rust-owned buffer."""

        identifiers, matrix, parameters = self._shared_inputs(signals, candidate_ids, parameter_matrix)
        self._check_batch_budget(matrix, audit=False)
        return NativeWfoPreparedSignalBatchV2(
            self._core.prepare_shared(identifiers, matrix, parameters),
            self.plan_fingerprint,
            self._identity.session_id,
        )

    def prepare_per_fold(
        self,
        signals: np.ndarray | Sequence[Sequence[Sequence[float]]],
        *,
        candidate_ids: Sequence[int] | np.ndarray | None = None,
        parameter_matrix: np.ndarray | Sequence[Sequence[float]] | None = None,
    ) -> NativeWfoPreparedSignalBatchV2:
        """Ingest one fold-specific signal cube into a Rust-owned buffer."""

        identifiers, cube, parameters = self._per_fold_inputs(signals, candidate_ids, parameter_matrix)
        self._check_batch_budget(cube, audit=False)
        return NativeWfoPreparedSignalBatchV2(
            self._core.prepare_per_fold(identifiers, cube, parameters),
            self.plan_fingerprint,
            self._identity.session_id,
        )

    def score_prepared_batch(
        self, batch: NativeWfoPreparedSignalBatchV2
    ) -> NativeWfoMetricMatrixV2:
        """Run a previously ingested signal batch without another input copy."""

        self._validate_prepared_batch(batch)
        return NativeWfoMetricMatrixV2._from_core(
            self._core.score_prepared(batch._require_open())
        )

    def audit_shared(
        self,
        signals: np.ndarray | Sequence[Sequence[float]],
        *,
        candidate_ids: Sequence[int] | np.ndarray,
        selected_candidate_ids: Sequence[int] | np.ndarray,
        expected_intent_fingerprint: str,
        parameter_matrix: np.ndarray | Sequence[Sequence[float]] | None = None,
    ) -> NativeWfoMetricMatrixV2:
        """Rerun selected shared-tape candidates with exact intent provenance."""

        batch = self.prepare_shared(signals, candidate_ids=candidate_ids, parameter_matrix=parameter_matrix)
        return self.audit_prepared_batch(
            batch,
            selected_candidate_ids=selected_candidate_ids,
            expected_intent_fingerprint=expected_intent_fingerprint,
        )

    def audit_per_fold(
        self,
        signals: np.ndarray | Sequence[Sequence[Sequence[float]]],
        *,
        candidate_ids: Sequence[int] | np.ndarray,
        selected_candidate_ids: Sequence[int] | np.ndarray,
        expected_intent_fingerprint: str,
        parameter_matrix: np.ndarray | Sequence[Sequence[float]] | None = None,
    ) -> NativeWfoMetricMatrixV2:
        """Rerun selected fold-specific candidates with exact intent provenance."""

        batch = self.prepare_per_fold(signals, candidate_ids=candidate_ids, parameter_matrix=parameter_matrix)
        return self.audit_prepared_batch(
            batch,
            selected_candidate_ids=selected_candidate_ids,
            expected_intent_fingerprint=expected_intent_fingerprint,
        )

    def audit_prepared_batch(
        self,
        batch: NativeWfoPreparedSignalBatchV2,
        *,
        selected_candidate_ids: Sequence[int] | np.ndarray,
        expected_intent_fingerprint: str,
    ) -> NativeWfoMetricMatrixV2:
        """Audit selected candidates from the exact prepared score batch."""

        self._validate_prepared_batch(batch)
        selected = _candidate_ids(selected_candidate_ids, expected_size=None)
        self.runtime_budget.require_preflight(
            bars=len(self.runner.full_runner.idx),
            workers=self.workers,
            native_memory_bytes=(
                _estimated_runner_market_bytes(self.runner) + batch.intent_ingest_bytes
            ),
            metric_rows=len(selected) * len(self.folds),
            audit_rows=len(selected) * len(self.folds),
        )
        return NativeWfoMetricMatrixV2._from_core(
            self._core.audit_prepared(
                batch._require_open(), selected, str(expected_intent_fingerprint)
            )
        )

    def score_prepared(
        self,
        prepared: PreparedWfoStrategyV1,
        params_by_candidate: Sequence[Mapping[str, Any]],
        *,
        candidate_ids: Sequence[int] | np.ndarray | None = None,
        parameter_matrix: np.ndarray | Sequence[Sequence[float]] | None = None,
        adapter: str = "auto",
    ) -> NativeWfoMetricMatrixV2:
        """Generate W1/W2 intent once, then run all candidate/fold scores in Rust.

        W2 is selected only when ``prepared.generate_batch`` is available and
        requested. A W1 implementation stays valid but may retain Python
        candidate-generation cost; execution/accounting is still one native
        score boundary for the complete matrix.
        """

        params = tuple(dict(value) for value in params_by_candidate)
        if not params:
            raise ValueError("native WFO prepared scoring requires at least one candidate")
        identifiers = _candidate_ids(candidate_ids, expected_size=len(params))
        cube, generated_parameters = _prepared_signal_cube(self, prepared, params, adapter=adapter)
        native_parameters = _combine_native_parameters(
            parameter_matrix,
            generated_parameters,
            candidates=len(params),
        )
        return self.score_per_fold(
            cube,
            candidate_ids=identifiers,
            parameter_matrix=native_parameters,
        )

    def optimize_prepared(
        self,
        prepared: PreparedWfoStrategyV1,
        *,
        param_ranges: Mapping[str, Any],
        n_trials: int,
        fixed_params: Mapping[str, Any] | None = None,
        seed: int | None = None,
        schedule: str | None = None,
        batch_size: int = 8,
        objective: Callable[[NativeWfoMetricMatrixV2], Mapping[int, float]] | None = None,
        top_k_audit: int = 0,
        parameter_matrix_builder: Callable[[Sequence[Mapping[str, Any]]], np.ndarray | None] | None = None,
        reference_best_objective: float | None = None,
    ) -> NativeWfoOptimizationResultV2:
        """Run explicit Optuna ask/evaluate/tell schedules over prepared WFO intent.

        ``certified_sequential_v1`` asks and tells exactly one trial at a
        time. ``throughput_batch_v1`` asks a full batch before tells and is
        deterministic for its seed/batch size, but deliberately does not
        claim the sequential TPE candidate sequence.  A batch quality regret
        is emitted only when an independently obtained reference objective is
        supplied; this runtime never invents a quality claim from a different
        candidate sequence.
        """

        try:
            import optuna
        except ImportError as exc:  # pragma: no cover - package dependency guard
            raise ImportError("optimize_prepared requires optuna") from exc
        if int(n_trials) <= 0:
            raise ValueError("n_trials must be > 0")
        active_schedule = _normalize_schedule(schedule or self.optimizer_schedule)
        if active_schedule != self.optimizer_schedule:
            raise ValueError(
                "runtime optimizer_schedule is immutable; construct a runtime with the requested schedule"
            )
        if active_schedule == "throughput_batch_v1" and int(batch_size) <= 1:
            raise ValueError("throughput_batch_v1 requires batch_size > 1")
        if active_schedule == "fixed_matrix_v1":
            raise ValueError("fixed_matrix_v1 has no adaptive Optuna lifecycle; call score_prepared directly")
        if reference_best_objective is not None and not np.isfinite(float(reference_best_objective)):
            raise ValueError("reference_best_objective must be finite when provided")
        sampler = optuna.samplers.TPESampler(seed=seed)
        # A candidate is reported only after every fold has completed.  A
        # step-wise pruner has no valid intermediate signal here, and Optuna's
        # default MedianPruner can otherwise turn an already-scored candidate
        # into PRUNED.  Keep the ask/evaluate/tell contract deterministic and
        # aligned with QuantBT's public optimizer.
        study = optuna.create_study(
            direction="maximize",
            sampler=sampler,
            pruner=optuna.pruners.NopPruner(),
        )
        params_by_candidate: dict[int, Mapping[str, Any]] = {}
        all_matrices: list[NativeWfoMetricMatrixV2] = []
        objective_by_candidate: dict[int, float] = {}
        source_by_candidate: dict[int, _OptimizationSourceBatchV2] = {}
        objective = _default_objective if objective is None else objective
        remaining = int(n_trials)
        while remaining:
            count = 1 if active_schedule == "certified_sequential_v1" else min(int(batch_size), remaining)
            trials = [study.ask() for _ in range(count)]
            params = [suggest_params(trial, param_ranges, fixed_params) for trial in trials]
            candidate_ids = np.ascontiguousarray(np.asarray([trial.number for trial in trials], dtype=np.uint64))
            native_parameters = (
                parameter_matrix_builder(params) if parameter_matrix_builder is not None else None
            )
            matrix = self.score_prepared(
                prepared,
                params,
                candidate_ids=candidate_ids,
                parameter_matrix=native_parameters,
            )
            values = dict(objective(matrix))
            for trial, candidate_id, candidate_params in zip(trials, candidate_ids, params, strict=True):
                value = float(values.get(int(candidate_id), _DEFAULT_FAILURE_OBJECTIVE))
                if not np.isfinite(value):
                    value = _DEFAULT_FAILURE_OBJECTIVE
                trial.report(value, step=0)
                if trial.should_prune():
                    study.tell(trial, state=optuna.trial.TrialState.PRUNED)
                else:
                    study.tell(trial, value)
                params_by_candidate[int(candidate_id)] = dict(candidate_params)
                objective_by_candidate[int(candidate_id)] = value
            all_matrices.append(matrix)
            source = _OptimizationSourceBatchV2(
                candidate_ids=tuple(int(candidate_id) for candidate_id in candidate_ids),
                params=tuple(dict(candidate_params) for candidate_params in params),
                intent_fingerprint=matrix.intent_fingerprint,
            )
            source_by_candidate.update(
                {int(candidate_id): source for candidate_id in candidate_ids}
            )
            remaining -= count
        score_matrix = _concat_metric_matrices(all_matrices)
        audit_matrix = None
        if int(top_k_audit) > 0:
            top_ids = np.asarray(
                [
                    candidate_id
                    for candidate_id, _ in sorted(
                        objective_by_candidate.items(), key=lambda item: (-item[1], item[0])
                    )[: int(top_k_audit)]
                ],
                dtype=np.uint64,
            )
            sources: dict[tuple[int, ...], list[int]] = {}
            for candidate_id in top_ids:
                source = source_by_candidate[int(candidate_id)]
                sources.setdefault(source.candidate_ids, []).append(int(candidate_id))
            audits: list[NativeWfoMetricMatrixV2] = []
            for source_ids, selected_ids in sources.items():
                source = source_by_candidate[source_ids[0]]
                source_id_array = np.asarray(source.candidate_ids, dtype=np.uint64)
                source_signals, generated_parameters = _prepared_signal_cube(
                    self,
                    prepared,
                    source.params,
                    adapter="auto",
                )
                source_parameters = _combine_native_parameters(
                    (
                        parameter_matrix_builder(source.params)
                        if parameter_matrix_builder is not None
                        else None
                    ),
                    generated_parameters,
                    candidates=len(source.params),
                )
                replayed_source_score = self.score_per_fold(
                    source_signals,
                    candidate_ids=source_id_array,
                    parameter_matrix=source_parameters,
                )
                if replayed_source_score.intent_fingerprint != source.intent_fingerprint:
                    raise AssertionError(
                        "prepared WFO strategy regenerated a different source intent during audit replay"
                    )
                _assert_selected_score_replay(score_matrix, replayed_source_score)
                source_audit = self.audit_per_fold(
                    source_signals,
                    candidate_ids=source_id_array,
                    selected_candidate_ids=np.asarray(selected_ids, dtype=np.uint64),
                    expected_intent_fingerprint=source.intent_fingerprint,
                    parameter_matrix=source_parameters,
                )
                source_audit.assert_audit_parity(replayed_source_score)
                audits.append(source_audit)
            audit_matrix = _concat_metric_matrices(audits)
        diagnostics = self.diagnostics()
        best_observed_objective = max(objective_by_candidate.values(), default=_DEFAULT_FAILURE_OBJECTIVE)
        quality_regret = (
            None
            if reference_best_objective is None
            else float(max(0.0, float(reference_best_objective) - best_observed_objective))
        )
        return NativeWfoOptimizationResultV2(
            schedule=active_schedule,
            study=study,
            params_by_candidate=params_by_candidate,
            score_matrix=score_matrix,
            objective_by_candidate=objective_by_candidate,
            audit_matrix=audit_matrix,
            metadata={
                "optimizer_schedule": active_schedule,
                "pruner_contract": "nop_pruner_complete_fold_scalar_v1",
                "candidate_sequence_equivalent_to_sequential": active_schedule == "certified_sequential_v1",
                "throughput_batch_size": int(batch_size) if active_schedule == "throughput_batch_v1" else 1,
                "quality_reference_status": (
                    "not_applicable_sequential"
                    if active_schedule == "certified_sequential_v1"
                    else "not_evaluated_without_explicit_reference"
                    if reference_best_objective is None
                    else "evaluated_against_explicit_reference"
                ),
                "quality_regret_vs_reference": quality_regret,
                "worker_pool_creations": diagnostics["worker_pool_creations"],
                "score_batches": diagnostics["score_batches"],
                "audit_batches": diagnostics["audit_batches"],
                "plan_fingerprint": self.plan_fingerprint,
            },
        )

    def cancel(self) -> None:
        """Request bounded cancellation; queued rows become typed canceled rows."""

        self._core.cancel()

    def clear_cancellation(self) -> None:
        """Allow the next independently reset score batch to execute."""

        self._core.clear_cancellation()

    def reset(self) -> None:
        """Reset retained worker session scratch while preserving immutable plan data."""

        self._core.reset()
        self._identity = self._identity.next_generation()

    def close(self) -> None:
        """Close the persistent worker pool deterministically."""

        self._core.close()

    def _shared_inputs(self, signals, candidate_ids, parameter_matrix):
        matrix = np.ascontiguousarray(np.asarray(signals, dtype=np.float64))
        if matrix.ndim != 2 or matrix.shape[1] != len(self.runner.full_runner.idx):
            raise ValueError("shared signals must have shape (candidates, prepared_market_bars)")
        if not np.isfinite(matrix).all():
            raise ValueError("native WFO signals must be finite")
        identifiers = _candidate_ids(candidate_ids, expected_size=matrix.shape[0])
        return identifiers, matrix, _native_parameter_matrix(parameter_matrix, matrix.shape[0])

    def _per_fold_inputs(self, signals, candidate_ids, parameter_matrix):
        cube = np.ascontiguousarray(np.asarray(signals, dtype=np.float64))
        expected = (len(self.folds), None, len(self.runner.full_runner.idx))
        if cube.ndim != 3 or cube.shape[0] != expected[0] or cube.shape[2] != expected[2]:
            raise ValueError("per-fold signals must have shape (folds, candidates, prepared_market_bars)")
        if not np.isfinite(cube).all():
            raise ValueError("native WFO signals must be finite")
        identifiers = _candidate_ids(candidate_ids, expected_size=cube.shape[1])
        return identifiers, cube, _native_parameter_matrix(parameter_matrix, cube.shape[1])

    def _validate_prepared_batch(self, batch: NativeWfoPreparedSignalBatchV2) -> None:
        if not isinstance(batch, NativeWfoPreparedSignalBatchV2):
            raise TypeError("batch must be NativeWfoPreparedSignalBatchV2")
        if self.closed:
            raise RuntimeError("native WFO runtime is closed")
        batch._require_open()
        if batch._plan_fingerprint != self.plan_fingerprint:
            raise ValueError("prepared native WFO batch belongs to a different immutable runtime plan")
        if batch._runtime_id != self._identity.session_id:
            raise ValueError("prepared native WFO batch belongs to a different runtime session")

    def _check_batch_budget(self, values: np.ndarray, *, audit: bool) -> None:
        # Shared input is (candidates, bars); per-fold input is
        # (folds, candidates, bars).  Budget rows always mean one scalar
        # metric record per candidate/fold execution, never folds squared.
        candidates = int(values.shape[0] if values.ndim == 2 else values.shape[1])
        rows = candidates * len(self.folds)
        self.runtime_budget.require_preflight(
            bars=len(self.runner.full_runner.idx),
            workers=self.workers,
            native_memory_bytes=_estimated_runner_market_bytes(self.runner) + int(values.nbytes),
            metric_rows=rows,
            audit_rows=rows if audit else 0,
        )


def _prepared_signal_cube(
    runtime: NativeWfoRuntimeV2,
    prepared: PreparedWfoStrategyV1,
    params: Sequence[Mapping[str, Any]],
    *,
    adapter: str,
) -> tuple[np.ndarray, np.ndarray | None]:
    mode = _resolve_adapter(prepared, adapter)
    cube = np.empty((len(runtime.folds), len(params), len(runtime.runner.full_runner.idx)), dtype=np.float64)
    native_parameters: np.ndarray | None = None
    for fold_index, fold in enumerate(runtime.folds):
        if mode == "w2":
            generated = prepared.generate_batch(params_matrix=params, fold_id=int(fold.fold_id))
            signal_matrix, fold_parameters = _coerce_batch_intent(
                generated, candidates=len(params), bars=cube.shape[2]
            )
            cube[fold_index] = signal_matrix
            if fold_parameters is not None:
                if native_parameters is not None and not np.array_equal(native_parameters, fold_parameters):
                    raise ValueError("prepared WFO native parameter rows must not change across folds")
                native_parameters = fold_parameters
        else:
            fold_parameters: np.ndarray | None = None
            for candidate_index, candidate_params in enumerate(params):
                generated = prepared.generate(params=candidate_params, fold_id=int(fold.fold_id))
                signal, row = _coerce_signal_intent(generated, bars=cube.shape[2])
                cube[fold_index, candidate_index] = signal
                if row is not None:
                    if fold_parameters is None:
                        fold_parameters = np.full((len(params), 4), np.nan, dtype=np.float64)
                    fold_parameters[candidate_index] = row
            if fold_parameters is not None:
                if not np.isfinite(fold_parameters).all():
                    raise ValueError(
                        "when one W1 candidate returns native_parameters, every candidate must return one"
                    )
                if native_parameters is not None and not np.array_equal(native_parameters, fold_parameters):
                    raise ValueError("prepared WFO native parameter rows must not change across folds")
                native_parameters = fold_parameters
    return cube, native_parameters


from .native_wfo_target import NativeTargetWfoRuntimeV2, NativeWfoPreparedTargetBatchV1


__all__ = [
    "BatchedPreparedWfoStrategyV1",
    "NativeWfoMetricMatrixV2",
    "NativeWfoOptimizationResultV2",
    "NativeWfoPreparedSignalBatchV2",
    "NativeWfoRuntimeV2",
    "NativeWfoPreparedTargetBatchV1",
    "NativeTargetWfoRuntimeV2",
    "PreparedWfoStrategyV1",
]
