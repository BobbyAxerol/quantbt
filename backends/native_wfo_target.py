"""Direct-target Rust walk-forward runtime kept separate from signal WFO.

The target route has an execution clock and account contract distinct from
``strategy_ir_signal_target_v1``.  Keeping it in a focused module prevents the
signal WFO facade from becoming a mixed-domain owner while preserving the
historic ``quantbt.backends.native_wfo`` re-export for callers.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
import importlib
from typing import Any, Mapping, Sequence

import numpy as np

from ..preparation.native_execution import NativePreparedTemplate
from ..core.runtime_governance import ParallelismPlanV1, RuntimeBudgetV1, RuntimeIdentityV1
from ._native_event_rust import NativeEventRustBackendError, probe_native_event_rust_extension
from .native_strategy_ir import NativeIRFold
from .native_wfo_support import _candidate_ids
from .native_wfo import NativeWfoMetricMatrixV2


_TARGET_KIND_CODES = {
    "units": 0,
    "target_units": 0,
    "notional": 1,
    "target_notional": 1,
    "weight": 2,
    "target_weight": 2,
    "equity_fraction": 3,
    "pct_equity": 3,
}
_TARGET_TIMING_CODES = {
    "close_target_v2_same_close": 0,
    "close_target_v2": 0,
    "same_close": 0,
    "next_open_v1": 1,
    "next_open": 1,
    "event_lifecycle_v3_next_open": 1,
    "next_close": 2,
    "event_lifecycle_v2_next_bar_close": 2,
}
_TARGET_INVALID_POLICY_CODES = {"reject_run": 0}
_PORTFOLIO_ADMISSION_POLICY_CODES = {
    "sequential_legacy": 0,
    "sequential": 0,
    "reduce_first_then_increase": 1,
    "reduce_first": 1,
    "pro_rata_to_available_margin": 2,
    "pro_rata": 2,
    "all_or_none_rebalance": 3,
    "all_or_none": 3,
}


@dataclass(slots=True)
class NativeWfoPreparedTargetBatchV1:
    """Immutable Rust-owned direct-target WFO ingress.

    A batch is bound to exactly one immutable market/account/fold plan.  It
    carries raw target intent only; Rust resolves target units, costs, margin
    and account state during score/audit execution without a command tape.
    """

    _core: Any | None
    _plan_fingerprint: str
    _runtime_id: str

    def _require_open(self) -> Any:
        if self._core is None:
            raise RuntimeError("prepared native target WFO batch is closed")
        return self._core

    @property
    def closed(self) -> bool:
        return self._core is None

    def close(self) -> None:
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
    def symbols(self) -> int:
        return int(self._require_open().symbols)

    @property
    def fold_count(self) -> int:
        return int(self._require_open().fold_count)

    @property
    def per_fold(self) -> bool:
        return bool(self._require_open().per_fold)


class NativeTargetWfoRuntimeV2:
    """Explicit Rust WFO runtime for direct close-target intent tapes.

    This companion route accepts already-generated target matrices and uses
    the frozen ``close_target_v2_same_close`` execution clock.  It does not
    coerce targets into signal or command tapes, does not share mutable account
    state across folds, and does not automatically replace callback WFO.

    The historic direct-target route remains single-symbol.  Set an explicit
    ``admission_policy`` to execute a multi-symbol target matrix through the
    Rust shared-account portfolio executor.  Each fold still receives a fresh
    shared account: this runtime is a causal candidate scorer, not a stitched
    portfolio account or a generic portfolio-endpoint promotion.

    ``workers`` is intentionally fixed to one in V1. The detached Rust batch
    owns execution, but an actual bounded parallel target scheduler has not
    been certified and therefore cannot be requested accidentally.
    """

    def __init__(
        self,
        template: NativePreparedTemplate,
        folds: Sequence[NativeIRFold],
        *,
        target_kind: str = "units",
        timing: str = "close_target_v2_same_close",
        invalid_target_policy: str = "reject_run",
        admission_policy: str | None = None,
        tradable: np.ndarray | Sequence[Sequence[bool]] | None = None,
        stale: np.ndarray | Sequence[Sequence[bool]] | None = None,
        qty_step: np.ndarray | Sequence[float] | None = None,
        min_qty: np.ndarray | Sequence[float] | None = None,
        min_notional: np.ndarray | Sequence[float] | None = None,
        equity_fraction: np.ndarray | Sequence[float] | None = None,
        workers: int = 1,
        max_metric_rows: int = 1_000_000,
        max_error_rows: int = 64,
        runtime_budget: RuntimeBudgetV1 | None = None,
        parallelism_plan: ParallelismPlanV1 | None = None,
    ) -> None:
        if not isinstance(template, NativePreparedTemplate):
            raise TypeError("template must be NativePreparedTemplate from NativeExecutionPreparationCache")
        if not folds:
            raise ValueError("native target WFO runtime requires at least one causal fold")
        if int(workers) != 1:
            raise ValueError(
                "native target WFO V1 is deliberately serial; workers must be 1 until a "
                "bounded parallel target scheduler is certified"
            )
        if int(max_metric_rows) <= 0 or int(max_error_rows) <= 0:
            raise ValueError("native target WFO metric/error budgets must be > 0")
        target_kind_code = _resolve_target_code(target_kind, _TARGET_KIND_CODES, "target_kind")
        timing_code = _resolve_target_code(timing, _TARGET_TIMING_CODES, "timing")
        if timing_code != 0:
            raise NotImplementedError(
                "native target WFO certifies only 'close_target_v2_same_close'; "
                "next-open and next-close target clocks are not promoted"
            )
        policy_code = _resolve_target_code(
            invalid_target_policy,
            _TARGET_INVALID_POLICY_CODES,
            "invalid_target_policy",
        )
        self.template = template
        self.folds = tuple(folds)
        bars = int(template.core.bars)
        symbols = int(template.core.symbols)
        admission_policy_code = (
            None
            if admission_policy is None
            else _resolve_target_code(
                admission_policy,
                _PORTFOLIO_ADMISSION_POLICY_CODES,
                "admission_policy",
            )
        )
        if symbols != 1 and admission_policy_code is None:
            raise NotImplementedError(
                "native target WFO without admission_policy is single-symbol only; set an "
                "explicit shared-account admission_policy for multi-symbol target WFO"
            )
        for fold in self.folds:
            if not isinstance(fold, NativeIRFold):
                raise TypeError("native target WFO folds must be NativeIRFold instances")
            fold.validate_for_bars(bars)
        self.target_kind = _canonical_target_kind(target_kind_code)
        self.timing = "close_target_v2_same_close"
        self.invalid_target_policy = "reject_run"
        self.admission_policy = (
            None
            if admission_policy_code is None
            else _canonical_admission_policy(admission_policy_code)
        )
        self.runtime_budget = runtime_budget or RuntimeBudgetV1(
            max_workers=1,
            max_metric_rows=int(max_metric_rows),
            max_error_rows=int(max_error_rows),
        )
        self.parallelism_plan = parallelism_plan or ParallelismPlanV1.resolve(
            rust_workers=1,
            max_rust_workers=self.runtime_budget.max_workers,
        )
        if self.parallelism_plan.rust_workers != 1:
            raise ValueError("native target WFO V1 requires an effective rust_workers value of 1")
        self.workers = 1
        self.max_metric_rows = int(self.runtime_budget.max_metric_rows)
        self.max_error_rows = int(self.runtime_budget.max_error_rows)
        self._identity = RuntimeIdentityV1.create()
        self.runtime_budget.require_preflight(
            bars=bars,
            workers=1,
            native_memory_bytes=_template_native_bytes(template),
        )
        self._module = _require_native_target_wfo_module(
            shared_account=admission_policy_code is not None,
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
        self._core = self._module.NativeTargetWfoRuntimeV2.from_template(
            template.core,
            fold_array,
            target_kind=target_kind_code,
            timing=timing_code,
            invalid_target_policy=policy_code,
            admission_policy=admission_policy_code,
            tradable=_target_mask(tradable, bars=bars, symbols=symbols, default=True, name="tradable"),
            stale=_target_mask(stale, bars=bars, symbols=symbols, default=False, name="stale"),
            qty_step=_target_vector(qty_step, symbols=symbols, default=0.0, name="qty_step"),
            min_qty=_target_vector(min_qty, symbols=symbols, default=0.0, name="min_qty"),
            min_notional=_target_vector(
                min_notional,
                symbols=symbols,
                default=0.0,
                name="min_notional",
            ),
            equity_fraction=_target_vector(
                equity_fraction,
                symbols=symbols,
                default=1.0,
                name="equity_fraction",
            ),
            workers=self.workers,
            max_metric_rows=self.max_metric_rows,
            max_error_rows=self.max_error_rows,
            **self.runtime_budget.as_native_kwargs(),
        )

    @property
    def plan_fingerprint(self) -> str:
        return str(self._core.plan_fingerprint)

    @property
    def closed(self) -> bool:
        return bool(self._core.closed)

    def diagnostics(self) -> Mapping[str, Any]:
        """Return ownership/copy counters for this direct target WFO route."""

        return {
            **dict(self._core.diagnostics()),
            "session_id": self._identity.session_id,
            "worker_generation": self._identity.generation,
            "runtime_budget": asdict(self.runtime_budget),
            "parallelism": asdict(self.parallelism_plan),
        }

    def reset(self) -> None:
        """Assert the runtime is reusable; no account state is retained across runs."""

        self._core.reset()
        self._identity = self._identity.next_generation()

    def cancel(self) -> None:
        self._core.cancel()

    def clear_cancellation(self) -> None:
        self._core.clear_cancellation()

    def close(self) -> None:
        """Close the immutable runtime deterministically."""

        self._core.close()

    def score_shared(
        self,
        targets: np.ndarray | Sequence[Sequence[Sequence[float]]],
        *,
        candidate_ids: Sequence[int] | np.ndarray | None = None,
    ) -> NativeWfoMetricMatrixV2:
        """Score a shared ``(candidates, bars, symbols)`` target tape."""

        return self.score_prepared_batch(self.prepare_shared(targets, candidate_ids=candidate_ids))

    def score_per_fold(
        self,
        targets: np.ndarray | Sequence[Sequence[Sequence[Sequence[float]]]],
        *,
        candidate_ids: Sequence[int] | np.ndarray | None = None,
    ) -> NativeWfoMetricMatrixV2:
        """Score a fold-specific ``(folds, candidates, bars, symbols)`` tape."""

        return self.score_prepared_batch(self.prepare_per_fold(targets, candidate_ids=candidate_ids))

    def prepare_shared(
        self,
        targets: np.ndarray | Sequence[Sequence[Sequence[float]]],
        *,
        candidate_ids: Sequence[int] | np.ndarray | None = None,
    ) -> NativeWfoPreparedTargetBatchV1:
        matrix = self._shared_targets(targets)
        self._check_batch_budget(matrix, audit=False)
        identifiers = _candidate_ids(candidate_ids, expected_size=matrix.shape[0])
        return NativeWfoPreparedTargetBatchV1(
            self._core.prepare_shared(identifiers, matrix),
            self.plan_fingerprint,
            self._identity.session_id,
        )

    def prepare_per_fold(
        self,
        targets: np.ndarray | Sequence[Sequence[Sequence[Sequence[float]]]],
        *,
        candidate_ids: Sequence[int] | np.ndarray | None = None,
    ) -> NativeWfoPreparedTargetBatchV1:
        cube = self._per_fold_targets(targets)
        self._check_batch_budget(cube, audit=False)
        identifiers = _candidate_ids(candidate_ids, expected_size=cube.shape[1])
        return NativeWfoPreparedTargetBatchV1(
            self._core.prepare_per_fold(identifiers, cube),
            self.plan_fingerprint,
            self._identity.session_id,
        )

    def score_prepared_batch(
        self,
        batch: NativeWfoPreparedTargetBatchV1,
    ) -> NativeWfoMetricMatrixV2:
        self._validate_prepared_batch(batch)
        return self._adapt_matrix(self._core.score_prepared(batch._require_open()))

    def audit_shared(
        self,
        targets: np.ndarray | Sequence[Sequence[Sequence[float]]],
        *,
        candidate_ids: Sequence[int] | np.ndarray,
        selected_candidate_ids: Sequence[int] | np.ndarray,
        expected_intent_fingerprint: str,
    ) -> NativeWfoMetricMatrixV2:
        batch = self.prepare_shared(targets, candidate_ids=candidate_ids)
        return self.audit_prepared_batch(
            batch,
            selected_candidate_ids=selected_candidate_ids,
            expected_intent_fingerprint=expected_intent_fingerprint,
        )

    def audit_per_fold(
        self,
        targets: np.ndarray | Sequence[Sequence[Sequence[Sequence[float]]]],
        *,
        candidate_ids: Sequence[int] | np.ndarray,
        selected_candidate_ids: Sequence[int] | np.ndarray,
        expected_intent_fingerprint: str,
    ) -> NativeWfoMetricMatrixV2:
        batch = self.prepare_per_fold(targets, candidate_ids=candidate_ids)
        return self.audit_prepared_batch(
            batch,
            selected_candidate_ids=selected_candidate_ids,
            expected_intent_fingerprint=expected_intent_fingerprint,
        )

    def audit_prepared_batch(
        self,
        batch: NativeWfoPreparedTargetBatchV1,
        *,
        selected_candidate_ids: Sequence[int] | np.ndarray,
        expected_intent_fingerprint: str,
    ) -> NativeWfoMetricMatrixV2:
        self._validate_prepared_batch(batch)
        selected = _candidate_ids(selected_candidate_ids, expected_size=None)
        self.runtime_budget.require_preflight(
            bars=int(self.template.core.bars),
            workers=1,
            native_memory_bytes=_template_native_bytes(self.template) + batch.intent_ingest_bytes,
            metric_rows=len(selected) * len(self.folds),
            audit_rows=len(selected) * len(self.folds),
        )
        return self._adapt_matrix(
            self._core.audit_prepared(
                batch._require_open(), selected, str(expected_intent_fingerprint)
            )
        )

    def _shared_targets(self, targets: object) -> np.ndarray:
        matrix = np.ascontiguousarray(np.asarray(targets, dtype=np.float64))
        expected = (None, int(self.template.core.bars), int(self.template.core.symbols))
        if matrix.ndim != 3 or matrix.shape[1:] != expected[1:]:
            raise ValueError(
                "shared native target WFO inputs must have shape (candidates, prepared_market_bars, symbols)"
            )
        if not np.isfinite(matrix).all():
            raise ValueError("native target WFO targets must be finite")
        return matrix

    def _per_fold_targets(self, targets: object) -> np.ndarray:
        cube = np.ascontiguousarray(np.asarray(targets, dtype=np.float64))
        expected = (
            len(self.folds),
            None,
            int(self.template.core.bars),
            int(self.template.core.symbols),
        )
        if cube.ndim != 4 or cube.shape[0] != expected[0] or cube.shape[2:] != expected[2:]:
            raise ValueError(
                "per-fold native target WFO inputs must have shape "
                "(folds, candidates, prepared_market_bars, symbols)"
            )
        if not np.isfinite(cube).all():
            raise ValueError("native target WFO targets must be finite")
        return cube

    def _adapt_matrix(self, core: Any) -> NativeWfoMetricMatrixV2:
        matrix = NativeWfoMetricMatrixV2._from_core(core)
        metadata = {
            **dict(matrix.metadata),
            "intent_kind": "direct_target_v1",
            "target_kind": self.target_kind,
            "target_timing": self.timing,
            "invalid_target_policy": self.invalid_target_policy,
            "portfolio_admission_policy": self.admission_policy,
            "shared_account": self.admission_policy is not None,
            "native_target_no_order_arena": True,
            "native_target_wfo_serial_v1": True,
            "execution_authority": (
                "rust_shared_portfolio_target_v1"
                if self.admission_policy is not None
                else "rust_direct_target_v1"
            ),
        }
        return replace(matrix, metadata=metadata)

    def _validate_prepared_batch(self, batch: NativeWfoPreparedTargetBatchV1) -> None:
        if not isinstance(batch, NativeWfoPreparedTargetBatchV1):
            raise TypeError("batch must be NativeWfoPreparedTargetBatchV1")
        if self.closed:
            raise RuntimeError("native target WFO runtime is closed")
        batch._require_open()
        if batch._plan_fingerprint != self.plan_fingerprint:
            raise ValueError("prepared native target WFO batch belongs to a different immutable runtime plan")
        if batch._runtime_id != self._identity.session_id:
            raise ValueError("prepared native target WFO batch belongs to a different runtime session")

    def _check_batch_budget(self, values: np.ndarray, *, audit: bool) -> None:
        rows = int(values.shape[1] if values.ndim == 4 else values.shape[0]) * len(self.folds)
        self.runtime_budget.require_preflight(
            bars=int(self.template.core.bars),
            workers=1,
            native_memory_bytes=_template_native_bytes(self.template) + int(values.nbytes),
            metric_rows=rows,
            audit_rows=rows if audit else 0,
        )


def _require_native_target_wfo_module(*, shared_account: bool = False):
    try:
        module = importlib.import_module("_quantbt_native")
    except Exception as exc:  # pragma: no cover - optional wheel boundary
        raise NativeEventRustBackendError(
            "native target WFO requires an installed compatible quantbt-native wheel"
        ) from exc
    required = ("NativeTargetWfoRuntimeV2", "NativeWfoPreparedTargetBatchV1")
    missing = [name for name in required if not hasattr(module, name)]
    if missing:
        raise NativeEventRustBackendError(
            "installed quantbt-native wheel lacks direct target WFO capability: " + ", ".join(missing)
        )
    status = probe_native_event_rust_extension(module=module)
    if not status.available or not status.compatible:
        raise NativeEventRustBackendError(
            "native target WFO requires a compatible quantbt-native wheel: "
            + str(status.reason or "unknown compatibility failure")
        )
    required_capabilities = [
        "rust_direct_target_v1",
        "native_wfo_prepared_target_v1",
        "native_wfo_direct_target_score_v1",
        "native_wfo_direct_target_audit_v1",
    ]
    if shared_account:
        required_capabilities.extend(
            (
                "rust_shared_portfolio_target_v1",
                "native_wfo_shared_portfolio_target_v1",
            )
        )
    missing_capabilities = [
        capability for capability in required_capabilities if not status.capabilities.get(capability, False)
    ]
    if missing_capabilities:
        raise NativeEventRustBackendError(
            "installed quantbt-native wheel lacks direct target WFO capabilities: "
            + ", ".join(missing_capabilities)
        )
    return module


def _template_native_bytes(template: NativePreparedTemplate) -> int:
    return int(template.market.prepared_bytes) + int(template.model_bytes)


def _resolve_target_code(value: object, codes: Mapping[str, int], name: str) -> int:
    if isinstance(value, (int, np.integer)) and not isinstance(value, (bool, np.bool_)):
        code = int(value)
        if code in codes.values():
            return code
    else:
        code = codes.get(str(value).strip().lower())
        if code is not None:
            return int(code)
    supported = ", ".join(sorted(codes))
    raise ValueError(f"unsupported native target WFO {name}={value!r}; supported: {supported}")


def _canonical_target_kind(code: int) -> str:
    return {0: "units", 1: "notional", 2: "weight", 3: "equity_fraction"}[int(code)]


def _canonical_admission_policy(code: int) -> str:
    return {
        0: "sequential_legacy",
        1: "reduce_first_then_increase",
        2: "pro_rata_to_available_margin",
        3: "all_or_none_rebalance",
    }[int(code)]


def _target_mask(value: object, *, bars: int, symbols: int, default: bool, name: str) -> np.ndarray:
    if value is None:
        return np.full((bars, symbols), default, dtype=np.bool_)
    result = np.ascontiguousarray(np.asarray(value, dtype=np.bool_))
    if result.shape != (bars, symbols):
        raise ValueError(f"native target WFO {name} must have shape (prepared_market_bars, symbols)")
    return result


def _target_vector(value: object, *, symbols: int, default: float, name: str) -> np.ndarray:
    if value is None:
        return np.full(symbols, default, dtype=np.float64)
    result = np.ascontiguousarray(np.asarray(value, dtype=np.float64))
    if result.shape != (symbols,) or not np.isfinite(result).all() or (result < 0.0).any():
        raise ValueError(f"native target WFO {name} must be finite, non-negative, and match symbols")
    return result


__all__ = ["NativeTargetWfoRuntimeV2", "NativeWfoPreparedTargetBatchV1"]
