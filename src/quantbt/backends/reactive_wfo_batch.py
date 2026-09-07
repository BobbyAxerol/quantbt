"""R3B fixed-candidate scheduling for reactive walk-forward evaluation.

The scheduler is deliberately not an Optuna sampler.  It batches a declared,
fixed candidate matrix over same fold/window bindings and returns scalar metric
rows.  That keeps `throughput_batch_v1` an explicit algorithmic contract while
the normal TPE route remains certified sequential ask/evaluate/tell.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

import numpy as np

from ..core.runtime_governance import RuntimeBudgetError, RuntimeCanceledError
from ..strategies.reactive_wfo import PreparedReactiveWfoStrategyAdapterV1


class ReactiveWfoBatchError(RuntimeError):
    """One candidate-local R3B batch failure with deterministic attribution."""


def reactive_wfo_marker_key(marker) -> tuple[str, int, str, int, int]:
    """Stable small key for one candidate/fold/stage absolute market window."""

    task = marker.task
    return (
        str(task.candidate_id),
        int(task.fold_id),
        str(task.stage),
        int(task.start_bar),
        int(task.end_bar),
    )


@dataclass(frozen=True, slots=True)
class ReactiveCandidateBatchTelemetryV1:
    batch_size: int = 0
    batches: int = 0
    candidates: int = 0
    callbacks: int = 0
    wake_candidate_dispatches: int = 0
    runner_creations: int = 0
    candidate_failures: int = 0
    native_cancel_requests: int = 0

    def as_dict(self) -> dict[str, int | str]:
        return {
            "schema": "quantbt-reactive-wfo-candidate-batch-v1",
            "batch_size": int(self.batch_size),
            "batches": int(self.batches),
            "candidates": int(self.candidates),
            "callbacks": int(self.callbacks),
            "wake_candidate_dispatches": int(self.wake_candidate_dispatches),
            "runner_creations": int(self.runner_creations),
            "candidate_failures": int(self.candidate_failures),
            "native_cancel_requests": int(self.native_cancel_requests),
            "market_copies_per_candidate": 0,
            "market_ipc_bytes_per_candidate": 0,
        }


class ReactiveWfoCandidateBatchSchedulerV1:
    """Reuse one prepared Rust market core across R3B same-window batches."""

    def __init__(
        self,
        *,
        adapter: PreparedReactiveWfoStrategyAdapterV1,
        prepared_runner,
        trading_days: int,
        batch_size: int,
        max_wall_time_ms: int | None = None,
    ) -> None:
        self._adapter = adapter
        self._prepared_runner = prepared_runner
        self._trading_days = int(trading_days)
        self._batch_size = int(batch_size)
        self._max_wall_time_ms = (
            None if max_wall_time_ms is None else int(max_wall_time_ms)
        )
        if not 1 <= self._batch_size <= 64:
            raise ValueError("reactive WFO candidate batch_size must be in 1..=64")
        self._runners: dict[tuple[int, str], object] = {}
        self._telemetry = ReactiveCandidateBatchTelemetryV1(batch_size=self._batch_size)
        self._failures: dict[tuple[str, int, str, int, int], dict[str, object]] = {}
        self._active_runner: object | None = None
        self._native_cancel_requests = 0
        self._closed = False

    @property
    def telemetry(self) -> ReactiveCandidateBatchTelemetryV1:
        return self._telemetry

    @property
    def failures(self) -> dict[tuple[str, int, str, int, int], dict[str, object]]:
        """Return candidate-local native failures accumulated for this run.

        A malformed command or wake plan is attributable to one candidate by
        the R3B core.  Its peers complete their own independent account runs;
        callers convert the failed candidate into a pruned WFO trial.  A Python
        exception raised by the shared batch callback itself remains a batch
        failure because no independent peer-safety proof exists in that case.
        """

        return {key: dict(value) for key, value in self._failures.items()}

    def cancel_active(self) -> None:
        """Ask only the currently active native batch to stop safely."""

        request_cancel = getattr(self._active_runner, "request_cancel", None)
        if callable(request_cancel):
            request_cancel()
            self._native_cancel_requests += 1

    def score_markers(self, markers: Sequence[object]) -> dict[tuple[str, int, str, int, int], dict[str, float]]:
        """Score a fixed matrix without per-candidate market packing.

        All members of a native callback batch share fold, stage and absolute
        window.  Candidate-specific account/state remains inside Rust and only
        the compact score row crosses back to Python.
        """

        if self._closed:
            raise RuntimeError("reactive WFO candidate batch scheduler is closed")
        result: dict[tuple[str, int, str, int, int], dict[str, float]] = {}
        groups: dict[tuple[int, str, int, int], list[object]] = {}
        for marker in markers:
            task = marker.task
            groups.setdefault(
                (int(task.fold_id), str(task.stage), int(task.start_bar), int(task.end_bar)),
                [],
            ).append(marker)
        for group in groups.values():
            for start in range(0, len(group), self._batch_size):
                chunk = group[start : start + self._batch_size]
                rows = self._score_chunk(chunk)
                for marker, row in zip(chunk, rows, strict=True):
                    key = reactive_wfo_marker_key(marker)
                    if key in result:
                        raise ReactiveWfoBatchError("reactive WFO candidate matrix contains a duplicate task binding")
                    result[key] = row
        return result

    def _score_chunk(self, markers: Sequence[object]) -> list[dict[str, float]]:
        if not markers:
            return []
        first = markers[0].task
        if any(
            (int(marker.task.fold_id), str(marker.task.stage), int(marker.task.start_bar), int(marker.task.end_bar))
            != (int(first.fold_id), str(first.stage), int(first.start_bar), int(first.end_bar))
            for marker in markers
        ):
            raise ValueError("reactive WFO candidate batch requires one fold/stage/window")
        strategy = self._adapter.build_candidate_batch(
            params_matrix=[marker.params for marker in markers],
            tasks=[marker.task for marker in markers],
        )
        requirements_key = repr(getattr(strategy, "quantbt_requirements", None))
        runner_key = (len(markers), requirements_key)
        runner = self._runners.get(runner_key)
        if runner is None:
            runner, _requirements = self._prepared_runner.prepare_reactive_candidate_batch_score(
                strategy,
                candidate_count=len(markers),
                trading_days=self._trading_days,
            )
            self._runners[runner_key] = runner
            self._telemetry = ReactiveCandidateBatchTelemetryV1(
                batch_size=self._batch_size,
                batches=self._telemetry.batches,
                candidates=self._telemetry.candidates,
                callbacks=self._telemetry.callbacks,
                wake_candidate_dispatches=self._telemetry.wake_candidate_dispatches,
                runner_creations=self._telemetry.runner_creations + 1,
                candidate_failures=self._telemetry.candidate_failures,
                native_cancel_requests=self._native_cancel_requests,
            )
        else:
            runner.reset()
        if self._max_wall_time_ms is not None:
            set_deadline_ms = getattr(runner, "set_deadline_ms", None)
            if not callable(set_deadline_ms):
                raise ReactiveWfoBatchError(
                    "prepared reactive candidate batch cannot enforce runtime_budget.max_wall_time_ms"
                )
            set_deadline_ms(self._max_wall_time_ms)
        self._active_runner = runner
        try:
            payload = runner.run_window(
                strategy,
                start_bar=int(first.start_bar),
                end_bar=int(first.end_bar),
            )
        except BaseException as exc:
            message = str(exc)
            if "reactive native execution canceled at a certified bar boundary" in message:
                raise RuntimeCanceledError("reactive WFO canceled during an active native candidate batch") from exc
            if "reactive native execution deadline exceeded at a certified bar boundary" in message:
                raise RuntimeBudgetError(
                    "MAX_WALL_TIME",
                    "reactive WFO native candidate batch exceeded runtime_budget.max_wall_time_ms",
                ) from exc
            raise
        finally:
            self._active_runner = None
        error_codes = np.asarray(payload["candidate_error_codes"], dtype=np.int64)
        outputs = list(payload["candidate_outputs"])
        if len(error_codes) != len(markers) or len(outputs) != len(markers):
            raise ReactiveWfoBatchError("reactive WFO candidate batch returned an invalid candidate output shape")
        rows: list[dict[str, float]] = []
        failures = 0
        for local_id, (marker, output, error_code) in enumerate(zip(markers, outputs, error_codes, strict=True)):
            key = reactive_wfo_marker_key(marker)
            if int(error_code) == 0:
                rows.append(_score_row_from_payload(output))
                continue
            failure = {
                "schema": "quantbt-reactive-wfo-candidate-error-v1",
                "candidate_id": str(marker.task.candidate_id),
                "fold_id": int(marker.task.fold_id),
                "stage": str(marker.task.stage),
                "start_bar": int(marker.task.start_bar),
                "end_bar": int(marker.task.end_bar),
                "candidate_local_id": int(local_id),
                "error_code": int(error_code),
                "error_class": "native_candidate_command_or_wake_plan",
            }
            prior = self._failures.get(key)
            if prior is not None and prior != failure:
                raise ReactiveWfoBatchError(
                    "reactive WFO candidate batch reported conflicting failures for one task binding"
                )
            self._failures[key] = failure
            rows.append(_failed_score_row())
            failures += 1
        callback_counts = np.asarray(payload.get("batch_callback_candidate_count", ()), dtype=np.int64)
        self._telemetry = ReactiveCandidateBatchTelemetryV1(
            batch_size=self._batch_size,
            batches=self._telemetry.batches + 1,
            candidates=self._telemetry.candidates + len(markers),
            callbacks=self._telemetry.callbacks + int(payload.get("batch_callback_count", 0)),
            wake_candidate_dispatches=self._telemetry.wake_candidate_dispatches + int(callback_counts.sum()),
            runner_creations=self._telemetry.runner_creations,
            candidate_failures=self._telemetry.candidate_failures + int(failures),
            native_cancel_requests=self._native_cancel_requests,
        )
        return rows

    def close(self) -> None:
        if self._closed:
            return
        for runner in self._runners.values():
            reset = getattr(runner, "reset", None)
            if callable(reset):
                reset()
        self._runners.clear()
        self._active_runner = None
        self._closed = True


def _score_row_from_payload(payload: Mapping[str, object]) -> dict[str, float]:
    if not bool(payload.get("score_metrics_present", False)):
        raise ReactiveWfoBatchError("reactive WFO candidate scalar output omitted streaming metrics")
    return {
        "sharpe": float(payload["score_sharpe"]),
        "turnover": float(payload["total_turnover"]),
        "trade_count": float(payload["score_num_trades"]),
        "mean_return": float(payload["score_total_return_pct"]) / 100.0,
        "volatility": 0.0,
        "max_drawdown_pct": float(payload["score_max_drawdown_pct"]),
        "profit_factor": float(payload["score_profit_factor"]),
    }


def _failed_score_row() -> dict[str, float]:
    """Finite placeholder consumed only until the WFO trial is marked pruned.

    The generic WFO math requires numeric rows while assembling a fold ledger.
    A deliberately finite floor avoids injecting NaNs into pandas/Optuna; the
    exact failure record is kept separately and the enclosing trial is then
    excluded from every selector before it can influence ranking.
    """

    return {
        "sharpe": -1.0e12,
        "turnover": 0.0,
        "trade_count": 0.0,
        "mean_return": 0.0,
        "volatility": 0.0,
        "max_drawdown_pct": 100.0,
        "profit_factor": 0.0,
    }


__all__ = [
    "ReactiveCandidateBatchTelemetryV1",
    "ReactiveWfoBatchError",
    "ReactiveWfoCandidateBatchSchedulerV1",
    "reactive_wfo_marker_key",
]
