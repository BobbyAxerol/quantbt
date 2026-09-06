"""Process ownership for the public W3 reactive WFO route.

This module intentionally has one narrow responsibility: a persistent Linux
``fork`` worker executes many scalar candidate windows while the prepared
market remains copy-on-write immutable.  The parent sends only an opaque task
binding over IPC; market arrays, prepared strategy features, and native market
cores are never pickled per candidate.

The certified Optuna schedule remains sequential.  A worker is therefore a
runtime isolation and retention boundary, not a claim that Python callback
compute suddenly becomes parallel.
"""

from __future__ import annotations

from dataclasses import asdict
import multiprocessing as mp
import os
from pathlib import Path
import threading
import traceback
from typing import Callable, Mapping

from ..core.runtime_governance import (
    ParallelismPlanV1,
    RuntimeBudgetError,
    RuntimeCanceledError,
    RuntimeIdentityV1,
)
from ..strategies import resolve_strategy_requirements


class ReactiveWfoWorkerError(RuntimeError):
    """A candidate worker failed; its process has been discarded."""


def fork_reactive_wfo_worker_supported() -> bool:
    """Whether this host can provide the certified COW worker transport."""

    return os.name == "posix" and "fork" in mp.get_all_start_methods()


def _parent_os_thread_count() -> int:
    """Return the kernel-visible thread count without trusting Python alone."""

    task_directory = Path("/proc/self/task")
    try:
        return sum(1 for _entry in task_directory.iterdir())
    except OSError:
        # Non-Linux POSIX platforms have no procfs.  The route is already
        # Linux-oriented because its performance claim depends on fork/COW;
        # Python's visible thread count remains the conservative fallback.
        return int(threading.active_count())


def fork_reactive_wfo_worker_safe() -> bool:
    """Return whether this parent can safely create a COW child.

    Forking a multi-threaded Python process can duplicate a locked runtime
    mutex into the child.  COW avoids tape copies, but never justifies taking
    that risk.  Threaded notebooks/services therefore use the certified
    in-process route or launch a dedicated single-thread worker process.
    """

    return (
        fork_reactive_wfo_worker_supported()
        and threading.active_count() == 1
        and _parent_os_thread_count() == 1
    )


def _memory_snapshot(pid: int | None) -> dict[str, int]:
    """Read Linux RSS/PSS without summing shared pages into unique memory."""

    if pid is None or int(pid) <= 0:
        return {"rss_bytes": 0, "pss_bytes": 0, "shared_bytes": 0, "private_bytes": 0}
    path = Path(f"/proc/{int(pid)}/smaps_rollup")
    if not path.exists():
        return {"rss_bytes": 0, "pss_bytes": 0, "shared_bytes": 0, "private_bytes": 0}
    values: dict[str, int] = {}
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            label, _, rest = line.partition(":")
            fields = rest.split()
            if fields and fields[0].isdigit():
                values[label] = int(fields[0]) * 1024
    except OSError:
        return {"rss_bytes": 0, "pss_bytes": 0, "shared_bytes": 0, "private_bytes": 0}
    shared = int(values.get("Shared_Clean", 0)) + int(values.get("Shared_Dirty", 0))
    private = int(values.get("Private_Clean", 0)) + int(values.get("Private_Dirty", 0))
    return {
        "rss_bytes": int(values.get("Rss", 0)),
        "pss_bytes": int(values.get("Pss", 0)),
        "shared_bytes": shared,
        "private_bytes": private,
    }


def _score_row(metrics: Mapping[str, object]) -> dict[str, float]:
    return {
        "sharpe": float(metrics["sharpe"]),
        "turnover": float(metrics["total_turnover"]),
        "trade_count": float(metrics["num_trades"]),
        "mean_return": float(metrics["total_return_pct"]) / 100.0,
        "volatility": 0.0,
        "max_drawdown_pct": float(metrics["max_drawdown_pct"]),
        "profit_factor": float(metrics["profit_factor"]),
    }


def _score_row_from_scalar_payload(payload: Mapping[str, object]) -> dict[str, float]:
    """Adapt Rust's scalar wire fields without materializing a result object."""

    if not bool(payload.get("score_metrics_present", False)):
        raise ReactiveWfoWorkerError("reactive scalar session omitted streaming score metrics")
    return {
        "sharpe": float(payload["score_sharpe"]),
        "turnover": float(payload["total_turnover"]),
        "trade_count": float(payload["score_num_trades"]),
        "mean_return": float(payload["score_total_return_pct"]) / 100.0,
        "volatility": 0.0,
        "max_drawdown_pct": float(payload["score_max_drawdown_pct"]),
        "profit_factor": float(payload["score_profit_factor"]),
    }


class ReactiveScalarSessionPoolV1:
    """Run-scoped reusable Rust scalar sessions keyed by numeric projection.

    The prepared runner owns the immutable market core. This pool owns only
    resettable account/command scratch, so candidate/fold lifecycle state can
    never be retained by a later score. The same pool is used by direct and
    COW-worker WFO routes.
    """

    def __init__(
        self,
        *,
        adapter,
        prepared_runner,
        trading_days: int,
        max_wall_time_ms: int | None = None,
    ) -> None:
        self._adapter = adapter
        self._prepared_runner = prepared_runner
        self._trading_days = int(trading_days)
        self._max_wall_time_ms = (
            None if max_wall_time_ms is None else int(max_wall_time_ms)
        )
        self._sessions: dict[str, tuple[object, object]] = {}
        self._runs = 0
        self._creations = 0
        self._poison_discards = 0
        self._python_callback_calls = 0
        self._python_callback_ns = 0
        self._gil_acquisitions = 0
        self._active_runner: object | None = None
        self._native_cancel_requests = 0
        self._closed = False

    @staticmethod
    def _requirements_key(requirements: object) -> str:
        return repr(requirements)

    def score(self, marker) -> tuple[dict[str, float], object]:
        if self._closed:
            raise RuntimeError("reactive scalar session pool is closed")
        strategy = self._adapter.build_strategy(params=marker.params, task=marker.task)
        requirements = resolve_strategy_requirements(strategy)
        if requirements.context_mode != "numeric":
            raise ReactiveWfoWorkerError("reactive WFO scalar sessions require numeric StrategyContextRequirements")
        key = self._requirements_key(requirements)
        entry = self._sessions.get(key)
        if entry is None:
            runner, prepared_requirements = self._prepared_runner.prepare_reactive_scalar_score(
                strategy,
                trading_days=self._trading_days,
            )
            if prepared_requirements != requirements:
                raise ReactiveWfoWorkerError("prepared reactive scalar session requirements changed during construction")
            self._sessions[key] = (runner, requirements)
            self._creations += 1
        else:
            runner, prepared_requirements = entry
            if prepared_requirements != requirements:
                raise ReactiveWfoWorkerError("reactive scalar session requirement key collision")
        self._active_runner = runner
        try:
            runner.reset()
            if self._max_wall_time_ms is not None:
                set_deadline_ms = getattr(runner, "set_deadline_ms", None)
                if not callable(set_deadline_ms):
                    raise ReactiveWfoWorkerError(
                        "prepared reactive scalar runner cannot enforce runtime_budget.max_wall_time_ms"
                    )
                set_deadline_ms(self._max_wall_time_ms)
            payload = runner.run_scalar_window(
                strategy,
                start_bar=int(marker.task.start_bar),
                end_bar=int(marker.task.end_bar),
            )
            row = _score_row_from_scalar_payload(payload)
        except BaseException as exc:
            if bool(getattr(runner, "poisoned", True)):
                self._sessions.pop(key, None)
                self._poison_discards += 1
            if "reactive native execution canceled at a certified bar boundary" in str(exc):
                raise RuntimeCanceledError("reactive WFO canceled during an active native score") from exc
            if "reactive native execution deadline exceeded at a certified bar boundary" in str(exc):
                raise RuntimeBudgetError(
                    "MAX_WALL_TIME",
                    "reactive WFO native score exceeded runtime_budget.max_wall_time_ms",
                ) from exc
            raise
        finally:
            self._active_runner = None
        self._runs += 1
        self._python_callback_calls += int(payload.get("python_callback_calls", 0))
        self._python_callback_ns += int(payload.get("python_callback_ns", 0))
        self._gil_acquisitions += int(payload.get("gil_acquisitions", 0))
        fingerprint = getattr(strategy, "quantbt_state_fingerprint", None)
        return row, fingerprint() if callable(fingerprint) else None

    def cancel_active(self) -> None:
        """Signal the currently running native score without touching its state.

        This is meaningful for a release-GIL reactive gap. Process-worker
        cancellation retains its existing discard-and-recover boundary.
        """

        runner = self._active_runner
        request_cancel = getattr(runner, "request_cancel", None)
        if callable(request_cancel):
            request_cancel()
            self._native_cancel_requests += 1

    def close(self) -> None:
        if self._closed:
            return
        for runner, _requirements in self._sessions.values():
            reset = getattr(runner, "reset", None)
            if callable(reset):
                reset()
            release = getattr(runner, "release_excess_capacity", None)
            if callable(release):
                release(0)
        self._sessions.clear()
        self._closed = True

    def metadata(self) -> dict[str, int | bool | str]:
        return {
            "schema": "quantbt-reactive-scalar-session-pool-v1",
            "session_creations": int(self._creations),
            "session_runs": int(self._runs),
            "session_poison_discards": int(self._poison_discards),
            "python_callback_calls": int(self._python_callback_calls),
            "python_callback_ns": int(self._python_callback_ns),
            "gil_acquisitions": int(self._gil_acquisitions),
            "native_cancel_requests": int(self._native_cancel_requests),
            "max_wall_time_ms": self._max_wall_time_ms,
            "active_native_score": bool(self._active_runner is not None),
            "session_count": int(len(self._sessions)),
            "closed": bool(self._closed),
        }


def _fork_score_worker_main(
    adapter,
    prepared_runner,
    request_connection,
    response_connection,
    *,
    trading_days: int,
    max_wall_time_ms: int | None,
    environment: Mapping[str, str],
) -> None:
    """Run in a forked child with inherited, immutable prepared tape state."""

    for key, value in environment.items():
        os.environ[str(key)] = str(value)
    sessions = ReactiveScalarSessionPoolV1(
        adapter=adapter,
        prepared_runner=prepared_runner,
        trading_days=int(trading_days),
        max_wall_time_ms=max_wall_time_ms,
    )
    try:
        while True:
            request = request_connection.recv()
            if request is None or request.get("kind") == "close":
                response_connection.send({"kind": "closed", "scalar_sessions": sessions.metadata()})
                return
            request_id = int(request["request_id"])
            marker = request["marker"]
            try:
                row, fingerprint = sessions.score(marker)
                response_connection.send(
                    {
                        "kind": "score",
                        "request_id": request_id,
                        "row": row,
                        "state_fingerprint": fingerprint,
                        "scalar_sessions": sessions.metadata(),
                        "worker_memory": _memory_snapshot(os.getpid()),
                    }
                )
            except BaseException as exc:  # Process boundary must return one typed failure row.
                response_connection.send(
                    {
                        "kind": "error",
                        "request_id": request_id,
                        "error_type": type(exc).__name__,
                        "error_code": getattr(exc, "code", None),
                        "message": str(exc),
                        "traceback": traceback.format_exc(limit=12)[-8_192:],
                        "scalar_sessions": sessions.metadata(),
                        "worker_memory": _memory_snapshot(os.getpid()),
                    }
                )
                # A failed callback may have poisoned native or strategy scratch.
                # Exit rather than let a later candidate inherit uncertain state.
                return
    finally:
        sessions.close()


class ForkReactiveWfoWorkerV1:
    """One persistent, deterministic COW child for sequential reactive WFO.

    The object owns only queues/process handles.  It never owns the market
    itself; the inherited market belongs to the parent WFO runtime and remains
    immutable.  This makes an accounting of shared PSS meaningful rather than
    claiming copied RSS as new retained tape memory.
    """

    def __init__(
        self,
        *,
        adapter,
        prepared_runner,
        trading_days: int,
        parallelism_plan: ParallelismPlanV1,
        max_inflight_tasks: int,
        max_wall_time_ms: int | None = None,
    ) -> None:
        if not fork_reactive_wfo_worker_supported():
            raise NotImplementedError(
                "reactive WFO worker_mode='process' requires Linux/POSIX fork copy-on-write transport; "
                "use worker_mode='inprocess' on this platform"
            )
        self._adapter = adapter
        self._prepared_runner = prepared_runner
        self._trading_days = int(trading_days)
        self._max_wall_time_ms = (
            None if max_wall_time_ms is None else int(max_wall_time_ms)
        )
        self._parallelism_plan = parallelism_plan
        self._max_inflight_tasks = int(max_inflight_tasks)
        if self._max_inflight_tasks != 1:
            raise ValueError(
                "certified sequential reactive WFO permits max_inflight_tasks=1; "
                "throughput batching is a separately versioned schedule"
            )
        self._context = mp.get_context("fork")
        self._identity = RuntimeIdentityV1.create()
        self._request_connection = None
        self._response_connection = None
        self._process = None
        self._next_request_id = 1
        self._pool_creations = 0
        self._task_count = 0
        self._poison_recoveries = 0
        self._last_worker_memory = _memory_snapshot(None)
        self._last_scalar_sessions: dict[str, object] = {}
        self._closed = False

    @property
    def identity(self) -> RuntimeIdentityV1:
        return self._identity

    def _start(self) -> None:
        if self._closed:
            raise RuntimeError("reactive WFO worker is closed")
        if self._process is not None and self._process.is_alive():
            return
        if not fork_reactive_wfo_worker_safe():
            raise RuntimeError(
                "reactive WFO worker_mode='process' refuses to fork a multi-threaded parent; "
                "use worker_mode='inprocess' or launch a dedicated single-thread worker process"
            )
        self._discard(join_timeout=0.0)
        request_recv, request_send = self._context.Pipe(duplex=False)
        response_recv, response_send = self._context.Pipe(duplex=False)
        self._request_connection = request_send
        self._response_connection = response_recv
        self._process = self._context.Process(
            target=_fork_score_worker_main,
            args=(self._adapter, self._prepared_runner, request_recv, response_send),
            kwargs={
                "trading_days": self._trading_days,
                "max_wall_time_ms": self._max_wall_time_ms,
                "environment": self._parallelism_plan.environment,
            },
            daemon=True,
            name="quantbt-reactive-wfo-v1",
        )
        self._process.start()
        self._pool_creations += 1
        self._identity = self._identity.next_generation()

    def score(self, marker, *, canceled: Callable[[], bool]) -> dict[str, float]:
        self._start()
        if canceled():
            self._cancel_and_discard()
            raise RuntimeCanceledError("reactive WFO canceled before worker task dispatch")
        request_id = self._next_request_id
        self._next_request_id += 1
        assert self._request_connection is not None
        assert self._response_connection is not None
        self._request_connection.send({"kind": "score", "request_id": request_id, "marker": marker})
        while True:
            if canceled():
                self._cancel_and_discard()
                raise RuntimeCanceledError("reactive WFO canceled while worker task was active")
            if not self._response_connection.poll(0.05):
                if self._process is None or not self._process.is_alive():
                    self._discard(join_timeout=0.0)
                    raise ReactiveWfoWorkerError("reactive WFO worker exited without a response")
                continue
            try:
                response = self._response_connection.recv()
            except EOFError:
                self._discard(join_timeout=0.0)
                raise ReactiveWfoWorkerError("reactive WFO worker closed its response channel") from None
            if int(response.get("request_id", request_id)) != request_id:
                self._discard(join_timeout=0.0)
                raise ReactiveWfoWorkerError("reactive WFO worker returned an out-of-order response")
            memory = response.get("worker_memory")
            if isinstance(memory, Mapping):
                self._last_worker_memory = {key: int(value) for key, value in memory.items()}
            scalar_sessions = response.get("scalar_sessions")
            if isinstance(scalar_sessions, Mapping):
                self._last_scalar_sessions = dict(scalar_sessions)
            if response.get("kind") == "score":
                self._task_count += 1
                return {key: float(value) for key, value in dict(response["row"]).items()}
            self._poison_recoveries += 1
            self._discard(join_timeout=0.2)
            error_type = str(response.get("error_type", ""))
            error_code = response.get("error_code")
            message = str(response.get("message", ""))
            if error_type == "RuntimeBudgetError" and error_code == "MAX_WALL_TIME":
                raise RuntimeBudgetError(
                    "MAX_WALL_TIME",
                    "reactive WFO native worker score exceeded runtime_budget.max_wall_time_ms",
                )
            if error_type == "RuntimeCanceledError":
                raise RuntimeCanceledError("reactive WFO canceled during an active worker score")
            if "reactive native execution deadline exceeded at a certified bar boundary" in message:
                raise RuntimeBudgetError(
                    "MAX_WALL_TIME",
                    "reactive WFO native worker score exceeded runtime_budget.max_wall_time_ms",
                )
            if "reactive native execution canceled at a certified bar boundary" in message:
                raise RuntimeCanceledError("reactive WFO canceled during an active worker score")
            raise ReactiveWfoWorkerError(
                "reactive WFO worker candidate failed: "
                f"{error_type or 'WorkerError'}: {message}"
            )

    def _cancel_and_discard(self) -> None:
        self._discard(join_timeout=0.1, terminate=True)

    def _discard(self, *, join_timeout: float, terminate: bool = False) -> None:
        process = self._process
        if process is not None:
            if terminate and process.is_alive():
                process.terminate()
            process.join(timeout=max(0.0, float(join_timeout)))
            if process.is_alive():
                process.terminate()
                process.join(timeout=1.0)
        for connection in (self._request_connection, self._response_connection):
            if connection is not None:
                connection.close()
        self._process = None
        self._request_connection = None
        self._response_connection = None

    def close(self) -> None:
        if self._closed:
            return
        if self._process is not None and self._process.is_alive() and self._request_connection is not None:
            try:
                self._request_connection.send({"kind": "close"})
            except Exception:
                pass
        self._discard(join_timeout=1.0)
        self._closed = True

    def metadata(self) -> dict[str, object]:
        pid = None if self._process is None else self._process.pid
        current = _memory_snapshot(pid)
        memory = current if any(current.values()) else dict(self._last_worker_memory)
        return {
            "worker_mode": "process",
            "worker_transport": "fork_copy_on_write_v1",
            "worker_pid": None if pid is None else int(pid),
            "worker_pool_creations": int(self._pool_creations),
            "worker_generation": int(self._identity.generation),
            "worker_tasks_completed": int(self._task_count),
            "worker_poison_recoveries": int(self._poison_recoveries),
            "worker_market_ipc_bytes_per_task": 0,
            "worker_metric_ipc": "small_scalar_row_v1",
            "max_wall_time_ms": self._max_wall_time_ms,
            "fork_parent_thread_contract": "one_kernel_thread_before_fork_v1",
            "fork_parent_os_threads": int(_parent_os_thread_count()),
            "worker_scalar_sessions": dict(self._last_scalar_sessions),
            "worker_memory": memory,
            "parallelism": asdict(self._parallelism_plan),
            "closed": bool(self._closed),
        }


__all__ = [
    "ForkReactiveWfoWorkerV1",
    "ReactiveScalarSessionPoolV1",
    "ReactiveWfoWorkerError",
    "fork_reactive_wfo_worker_safe",
    "fork_reactive_wfo_worker_supported",
]
