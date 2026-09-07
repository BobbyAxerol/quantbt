"""Private validation and scalar-matrix helpers for native WFO V2.

Keeping these allocation-free helpers outside the runtime facade keeps the
public execution owner focused on plan lifetime, worker ownership, and Optuna
lifecycle.  This module deliberately imports the public result type lazily so
the facade can re-export the helpers for compatibility without an import cycle.
"""

from __future__ import annotations

from typing import Any, Mapping, TYPE_CHECKING, Sequence

import numpy as np

if TYPE_CHECKING:
    from .native_wfo import NativeWfoMetricMatrixV2


def _normalize_schedule(value: str) -> str:
    normalized = str(value).strip().lower()
    supported = {"certified_sequential_v1", "throughput_batch_v1", "fixed_matrix_v1"}
    if normalized not in supported:
        raise ValueError("optimizer_schedule must be certified_sequential_v1, throughput_batch_v1, or fixed_matrix_v1")
    return normalized


def _candidate_ids(values, *, expected_size: int | None) -> np.ndarray:
    if values is None:
        if expected_size is None:
            raise ValueError("candidate_ids are required")
        values = np.arange(expected_size, dtype=np.uint64)
    raw = np.asarray(values)
    if raw.ndim != 1 or (expected_size is not None and len(raw) != expected_size):
        raise ValueError("candidate_ids must be a one-dimensional array matching candidate rows")
    if raw.dtype.kind == "b":
        raise ValueError("candidate_ids must be non-negative integer identifiers, not booleans")
    try:
        numeric = np.asarray(raw, dtype=np.float64)
    except (TypeError, ValueError) as exc:
        raise ValueError("candidate_ids must be finite non-negative integer identifiers") from exc
    if not np.isfinite(numeric).all() or np.any(numeric < 0.0) or np.any(numeric != np.floor(numeric)):
        raise ValueError("candidate_ids must be finite non-negative integer identifiers")
    if np.any(numeric > np.iinfo(np.uint64).max):
        raise ValueError("candidate_ids exceed the native uint64 range")
    identifiers = np.ascontiguousarray(numeric.astype(np.uint64, copy=False))
    if len(np.unique(identifiers)) != len(identifiers):
        raise ValueError("candidate_ids must be unique")
    return identifiers


def _native_parameter_matrix(values, candidates: int) -> np.ndarray | None:
    if values is None:
        return None
    matrix = np.ascontiguousarray(np.asarray(values, dtype=np.float64))
    if matrix.shape != (int(candidates), 4) or not np.isfinite(matrix).all():
        raise ValueError("native parameter_matrix must be finite with shape (candidates, 4)")
    return matrix


def _resolve_adapter(prepared, adapter: str) -> str:
    requested = str(adapter).lower().strip()
    if requested == "auto":
        return "w2" if callable(getattr(prepared, "generate_batch", None)) else "w1"
    if requested == "w2" and not callable(getattr(prepared, "generate_batch", None)):
        raise TypeError("adapter='w2' requires prepared.generate_batch")
    if requested not in {"w1", "w2"}:
        raise ValueError("adapter must be auto, w1, or w2")
    return requested


def _coerce_signal_intent(value: Any, *, bars: int) -> tuple[np.ndarray, np.ndarray | None]:
    native_parameters = None
    if isinstance(value, Mapping):
        if "signal" not in value:
            raise ValueError("prepared WFO intent mapping must include 'signal'")
        native_parameters = value.get("native_parameters")
        value = value["signal"]
    signal = np.ascontiguousarray(np.asarray(value, dtype=np.float64))
    if signal.shape != (int(bars),) or not np.isfinite(signal).all():
        raise ValueError("prepared WFO signal must be finite with shape (prepared_market_bars,)")
    parameters = None if native_parameters is None else _native_parameter_matrix([native_parameters], 1)[0]
    return signal, parameters


def _coerce_batch_intent(
    value: Any,
    *,
    candidates: int,
    bars: int,
) -> tuple[np.ndarray, np.ndarray | None]:
    native_parameters = None
    if isinstance(value, Mapping):
        if "signal" not in value:
            raise ValueError("prepared WFO batch mapping must include 'signal'")
        native_parameters = value.get("native_parameters")
        value = value["signal"]
    matrix = np.ascontiguousarray(np.asarray(value, dtype=np.float64))
    if matrix.shape != (int(candidates), int(bars)) or not np.isfinite(matrix).all():
        raise ValueError("prepared WFO signal batch must be finite with shape (candidates, prepared_market_bars)")
    parameters = None if native_parameters is None else _native_parameter_matrix(native_parameters, candidates)
    return matrix, parameters


def _combine_native_parameters(
    explicit: np.ndarray | Sequence[Sequence[float]] | None,
    generated: np.ndarray | None,
    *,
    candidates: int,
) -> np.ndarray | None:
    explicit_matrix = _native_parameter_matrix(explicit, candidates)
    if generated is None:
        return explicit_matrix
    generated_matrix = _native_parameter_matrix(generated, candidates)
    if explicit_matrix is not None and not np.array_equal(explicit_matrix, generated_matrix):
        raise ValueError(
            "explicit native parameter_matrix differs from the prepared strategy's generated rows"
        )
    return generated_matrix


def _assert_selected_score_replay(
    all_scores: "NativeWfoMetricMatrixV2",
    selected_scores: "NativeWfoMetricMatrixV2",
) -> None:
    lookup = {
        (int(candidate), int(fold)): terminal
        for candidate, fold, terminal in zip(
            all_scores.candidate_id,
            all_scores.fold_id,
            all_scores.terminal_fingerprint,
            strict=True,
        )
    }
    for candidate, fold, terminal in zip(
        selected_scores.candidate_id,
        selected_scores.fold_id,
        selected_scores.terminal_fingerprint,
        strict=True,
    ):
        if lookup.get((int(candidate), int(fold))) != terminal:
            raise AssertionError("selected native WFO score did not replay the original terminal state")


def _default_objective(matrix: "NativeWfoMetricMatrixV2") -> Mapping[int, float]:
    return matrix.aggregate(field="fold_sharpe")


def _estimated_runner_market_bytes(runner) -> int:
    market = runner.full_runner.market_arrays
    values = (
        getattr(market, "highs", None),
        getattr(market, "lows", None),
        getattr(market, "closes", None),
        getattr(market, "funding", None),
        getattr(market, "is_funding_bar", None),
    )
    return int(sum(int(getattr(value, "nbytes", 0)) for value in values))


def _concat_metric_matrices(matrices: Sequence["NativeWfoMetricMatrixV2"]) -> "NativeWfoMetricMatrixV2":
    """Join score batches while preserving bounded local error-table slots."""

    # Delayed import: native_wfo imports this support module to re-export its
    # compatibility helpers, while this function needs the facade result type
    # only when a cold aggregate is actually assembled.
    from .native_wfo import NativeWfoMetricMatrixV2

    if not matrices:
        raise ValueError("native WFO optimizer produced no score batches")
    first = matrices[0]
    if len(matrices) == 1:
        return first
    if any(
        matrix.plan_fingerprint != first.plan_fingerprint or matrix.audit != first.audit
        for matrix in matrices
    ):
        raise ValueError("native WFO score matrices have incompatible provenance")

    def concatenate(name: str) -> np.ndarray:
        return np.ascontiguousarray(np.concatenate([getattr(matrix, name) for matrix in matrices]))

    # Error slots are local to each Rust score batch. Optimization retains a
    # compact concatenated matrix, so remap non-sentinel slots into one bounded
    # global side table instead of silently pointing a later row at an earlier
    # batch's diagnostic text.
    error_slots: list[np.ndarray] = []
    errors: list[str] = []
    error_sentinel = np.iinfo(np.uint32).max
    for matrix in matrices:
        local_slots = np.ascontiguousarray(np.asarray(matrix.error_slot, dtype=np.uint32)).copy()
        offset = len(errors)
        assigned = local_slots != error_sentinel
        if assigned.any():
            if offset + int(local_slots[assigned].max()) > error_sentinel - 1:
                raise OverflowError("native WFO error side table exceeds uint32 address space")
            local_slots[assigned] = local_slots[assigned] + np.uint32(offset)
        error_slots.append(local_slots)
        errors.extend(matrix.errors)

    intent_fingerprints = tuple(dict.fromkeys(matrix.intent_fingerprint for matrix in matrices))
    metadata = {
        **first.metadata,
        "worker_pool_batches": max(int(matrix.metadata["worker_pool_batches"]) for matrix in matrices),
        "optimizer_score_batches": len(matrices),
        "intent_fingerprint_scope": "single_batch" if len(intent_fingerprints) == 1 else "aggregate_batches",
        "intent_fingerprints": intent_fingerprints,
    }
    if len(intent_fingerprints) == 1:
        metadata["intent_fingerprint"] = intent_fingerprints[0]
    else:
        metadata.pop("intent_fingerprint", None)

    return NativeWfoMetricMatrixV2(
        candidate_id=concatenate("candidate_id"),
        fold_id=concatenate("fold_id"),
        scenario_id=concatenate("scenario_id"),
        status=concatenate("status"),
        final_equity=concatenate("final_equity"),
        fold_return=concatenate("fold_return"),
        fold_sharpe=concatenate("fold_sharpe"),
        fold_sortino=concatenate("fold_sortino"),
        max_drawdown=concatenate("max_drawdown"),
        turnover=concatenate("turnover"),
        total_fee=concatenate("total_fee"),
        total_funding=concatenate("total_funding"),
        fill_rate=concatenate("fill_rate"),
        fill_count=concatenate("fill_count"),
        rejected_count=concatenate("rejected_count"),
        liquidated=concatenate("liquidated"),
        request_fingerprint=tuple(
            value for matrix in matrices for value in matrix.request_fingerprint
        ),
        terminal_fingerprint=tuple(
            value for matrix in matrices for value in matrix.terminal_fingerprint
        ),
        error_slot=np.ascontiguousarray(np.concatenate(error_slots), dtype=np.uint32),
        errors=tuple(errors),
        metadata=metadata,
    )
