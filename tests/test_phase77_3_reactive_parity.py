"""Phase 77.3 parity lock for reusable reactive R2 hot state.

The tests intentionally exercise the public Python strategy boundary.  Rust
still owns the market clock, lifecycle, funding, fills, account and metrics;
the only change under test is how no-decision gaps are scheduled and observed.
"""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import subprocess
import sys
from threading import Thread
import time
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from quantbt import (
    CandidateWakePlansV1,
    ExecutionConfig,
    OrderSide,
    QuantBTEndpoint,
    StrategyContextRequirements,
)
from quantbt.backends.reactive_wfo_workers import (
    ForkReactiveWfoWorkerV1,
    ReactiveScalarSessionPoolV1,
    fork_reactive_wfo_worker_safe,
    fork_reactive_wfo_worker_supported,
)
from quantbt.core.runtime_governance import ParallelismPlanV1, RuntimeBudgetError
from quantbt.strategies import WakePlanV1


pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("_quantbt_native") is None,
    reason="quantbt-native extension is not installed in this environment",
)


_REQUIREMENTS = StrategyContextRequirements(
    market=("open", "high", "low", "close"),
    account=("equity", "available_equity", "initial_margin", "maintenance_margin", "liquidated"),
    positions=("qty",),
    fills="new_only",
    events="new_only",
    active_orders="snapshot",
    context_mode="numeric",
)


def _frame(*, bars: int = 160) -> pd.DataFrame:
    index = pd.date_range("2025-03-01", periods=bars, freq="1h", tz="UTC")
    phase = np.arange(bars, dtype=np.float64)
    close = 100.0 + 0.13 * phase + 0.9 * np.sin(phase / 7.0)
    return pd.DataFrame(
        {
            "open": np.r_[close[0], close[:-1]],
            "high": close + 0.6,
            "low": close - 0.6,
            "close": close,
            "volume": np.full(bars, 10_000.0),
            "funding_rate": np.where((phase.astype(np.int64) % 11) == 0, 0.0001, 0.0),
        },
        index=index,
    )


def _endpoint(frame: pd.DataFrame, *, gil_policy: str = "release_between_callbacks"):
    return QuantBTEndpoint.native_event_strategy(
        initial_capital=20_000.0,
        leverage=3.0,
        maintenance_ratio=0.005,
        fee_rate=0.0004,
        use_funding=True,
        funding_rate=frame["funding_rate"],
        qty_step=0.25,
        min_qty=0.5,
        min_notional=25.0,
        report_level="audit",
        native_backend="rust",
        reactive_kernel_mode="single_pass",
        reactive_runtime="numeric_sparse_wake_v1",
        reactive_gil_policy=gil_policy,
        execution_contract="event_lifecycle_v3_next_open",
        execution=ExecutionConfig(slippage_bps=1.0),
    )


class _WireOnlyPlan:
    """Prove the optimized native route does not need a dict wake payload."""

    def __init__(self, plan: WakePlanV1) -> None:
        self._plan = plan

    def as_native_wire(self):
        return self._plan.as_native_wire()

    def as_native_payload(self):  # pragma: no cover - must never be called.
        raise AssertionError("typed R2 wire unexpectedly fell back to a dict payload")


class _SparseWire:
    quantbt_reactive_sparse_v1 = True
    quantbt_sparse_shadow_certified_v1 = True
    quantbt_requirements = _REQUIREMENTS

    def on_wake(self, context, out):
        bar = int(context.bar_index)
        if bar == 0:
            out.market(0, OrderSide.BUY, 1.0)
            return _WireOnlyPlan(WakePlanV1(next_bar=48, on_funding=True))
        if bar == 48:
            out.market(0, OrderSide.SELL, 1.0, reduce_only=True)
            return _WireOnlyPlan(WakePlanV1(next_bar=96))
        return _WireOnlyPlan(WakePlanV1())


class _SparsePayload:
    quantbt_reactive_sparse_v1 = True
    quantbt_sparse_shadow_certified_v1 = True
    quantbt_requirements = _REQUIREMENTS

    def on_wake(self, context, out) -> WakePlanV1:
        bar = int(context.bar_index)
        if bar == 0:
            out.market(0, OrderSide.BUY, 1.0)
            return WakePlanV1(next_bar=48, on_funding=True)
        if bar == 48:
            out.market(0, OrderSide.SELL, 1.0, reduce_only=True)
            return WakePlanV1(next_bar=96)
        return WakePlanV1()


class _LegacyPayloadOnlyPlan:
    """An older external protocol object remains callable through the adapter."""

    def __init__(self, plan: WakePlanV1) -> None:
        self._plan = plan

    def as_native_payload(self):
        return self._plan.as_native_payload()


class _SparseLegacyPayload(_SparsePayload):
    def on_wake(self, context, out):
        return _LegacyPayloadOnlyPlan(super().on_wake(context, out))


class _PoolAdapter:
    """Small WFO-compatible adapter used to prove deadline propagation."""

    def build_strategy(self, *, params, task):
        del params, task
        return _SparseWire()


class _BatchSparse:
    quantbt_reactive_candidate_batch_v1 = True
    quantbt_requirements = _REQUIREMENTS

    def on_wake_batch(self, context_batch, out_batch) -> CandidateWakePlansV1:
        plans = {}
        bar = int(context_batch.bar_index)
        for candidate_id in context_batch.candidate_ids.tolist():
            candidate = int(candidate_id)
            writer = out_batch.writer(candidate)
            if bar == 0:
                writer.market(0, OrderSide.BUY, 1.0)
                plans[candidate] = WakePlanV1(next_bar=48)
            elif bar == 48:
                writer.market(0, OrderSide.SELL, 1.0, reduce_only=True)
                plans[candidate] = WakePlanV1()
            else:
                plans[candidate] = WakePlanV1()
        return CandidateWakePlansV1(plans)


def _assert_account_parity(left, right) -> None:
    for name in ("equity", "fees", "funding"):
        np.testing.assert_allclose(
            getattr(left, name).to_numpy(dtype=np.float64),
            getattr(right, name).to_numpy(dtype=np.float64),
            rtol=0.0,
            atol=1e-10,
        )
    np.testing.assert_allclose(
        left.positions.to_numpy(dtype=np.float64),
        right.positions.to_numpy(dtype=np.float64),
        rtol=0.0,
        atol=1e-10,
    )
    assert left.full_report() == right.full_report()


def test_phase77_3_typed_sparse_wire_matches_payload_adapter_and_reuses_native_gap_buffers():
    frame = _frame()
    typed = _endpoint(frame).simulate(data=frame, strategy=_SparseWire(), symbols=["BTC"])
    payload = _endpoint(frame).simulate(data=frame, strategy=_SparsePayload(), symbols=["BTC"])
    _assert_account_parity(typed, payload)

    telemetry = typed.metadata["reactive_numeric_observability"]
    assert telemetry["wake_observation_buffer_allocations"] == 2
    assert telemetry["wake_observation_refreshes"] == len(frame)
    assert telemetry["native_gap_runs"] >= 1
    assert telemetry["native_gap_bars"] == len(frame) - 1
    assert telemetry["native_cancellation_checks"] >= 1
    assert telemetry["gil_policy"] == "release_between_callbacks"
    assert telemetry["gil_acquisitions"] == telemetry["python_callback_calls"] + 1


def test_phase77_3_legacy_payload_adapter_remains_exactly_compatible():
    frame = _frame()
    typed = _endpoint(frame).simulate(data=frame, strategy=_SparseWire(), symbols=["BTC"])
    legacy = _endpoint(frame).simulate(data=frame, strategy=_SparseLegacyPayload(), symbols=["BTC"])
    _assert_account_parity(typed, legacy)


def test_phase77_3_native_cancellation_rejects_a_partial_score_and_reset_recovers():
    frame = _frame(bars=256)
    endpoint = _endpoint(frame)
    prepared = endpoint.prepare_native_event_strategy(data=frame, symbols=["BTC"])
    strategy = _SparseWire()
    runner, _requirements = prepared.prepare_reactive_scalar_score(strategy, trading_days=365)
    token = runner.cancellation_token
    assert token is not None

    token.cancel()
    with pytest.raises(RuntimeError, match="canceled at a certified bar boundary"):
        runner.run_scalar_window(
            strategy,
            start_bar=0,
            end_bar=len(frame),
            gil_policy="release_between_callbacks",
        )

    runner.reset()
    payload = runner.run_scalar_window(
        _SparseWire(),
        start_bar=0,
        end_bar=len(frame),
        gil_policy="release_between_callbacks",
    )
    assert payload["score_metrics_present"] is True
    assert int(payload["bars_processed"]) == len(frame)
    assert int(payload["native_cancellation_checks"]) >= 1


def test_phase77_3_native_gap_cancellation_interrupts_active_work_and_does_not_publish_a_score():
    frame = _frame(bars=100_000)
    endpoint = _endpoint(frame)
    prepared = endpoint.prepare_native_event_strategy(data=frame, symbols=["BTC"])
    runner, _requirements = prepared.prepare_reactive_scalar_score(_SparseWire(), trading_days=365)
    token = runner.cancellation_token
    assert token is not None

    trigger = Thread(target=lambda: (time.sleep(0.001), token.cancel()), daemon=True)
    trigger.start()
    started = time.perf_counter()
    with pytest.raises(RuntimeError, match="canceled at a certified bar boundary"):
        runner.run_scalar_window(
            _SparseWire(),
            start_bar=0,
            end_bar=len(frame),
            gil_policy="release_between_callbacks",
        )
    trigger.join(timeout=1.0)
    assert not trigger.is_alive()
    assert time.perf_counter() - started < 0.5

    # A canceled score has no payload to adapt. The next independent window is
    # explicitly reset and remains a valid fresh account run.
    runner.reset()
    payload = runner.run_scalar_window(
        _SparseWire(),
        start_bar=0,
        end_bar=256,
        gil_policy="release_between_callbacks",
    )
    assert payload["score_metrics_present"] is True
    assert int(payload["bars_processed"]) == 256


def test_phase77_3_native_deadline_is_enforced_inside_active_scalar_and_batch_work():
    frame = _frame(bars=20_000)
    endpoint = _endpoint(frame)
    prepared = endpoint.prepare_native_event_strategy(data=frame, symbols=["BTC"])
    runner, _requirements = prepared.prepare_reactive_scalar_score(_SparseWire(), trading_days=365)
    runner.set_deadline_ms(1)
    started = time.perf_counter()
    with pytest.raises(RuntimeError, match="deadline exceeded at a certified bar boundary"):
        runner.run_scalar_window(
            _SparseWire(),
            start_bar=0,
            end_bar=len(frame),
            gil_policy="release_between_callbacks",
        )
    assert time.perf_counter() - started < 0.5

    runner.reset()
    runner.set_deadline_ms(None)
    recovered = runner.run_scalar_window(
        _SparseWire(),
        start_bar=0,
        end_bar=256,
        gil_policy="release_between_callbacks",
    )
    assert recovered["score_metrics_present"] is True

    # The WFO scalar pool forwards the public RuntimeBudgetV1 deadline to the
    # already-prepared native runner and preserves a typed budget failure.
    pool = ReactiveScalarSessionPoolV1(
        adapter=_PoolAdapter(),
        prepared_runner=prepared,
        trading_days=365,
        max_wall_time_ms=1,
    )
    marker = SimpleNamespace(
        params={},
        task=SimpleNamespace(start_bar=0, end_bar=len(frame), candidate_id="deadline", fold_id=0, stage="is"),
    )
    try:
        with pytest.raises(RuntimeBudgetError) as error:
            pool.score(marker)
        assert error.value.code == "MAX_WALL_TIME"
        assert pool.metadata()["max_wall_time_ms"] == 1
    finally:
        pool.close()

    batch, _requirements = prepared.prepare_reactive_candidate_batch_score(
        _BatchSparse(),
        candidate_count=2,
        trading_days=365,
    )
    batch.set_deadline_ms(1)
    with pytest.raises(RuntimeError, match="deadline exceeded at a certified bar boundary"):
        batch.run_window(
            _BatchSparse(),
            start_bar=0,
            end_bar=len(frame),
            gil_policy="release_between_callbacks",
        )
    batch.reset()
    batch.set_deadline_ms(None)
    batch_payload = batch.run_window(
        _BatchSparse(),
        start_bar=0,
        end_bar=256,
        gil_policy="release_between_callbacks",
    )
    assert len(batch_payload["candidate_outputs"]) == 2


@pytest.mark.skipif(
    not fork_reactive_wfo_worker_supported(),
    reason="Phase 77.3 process deadline check requires POSIX fork transport",
)
def test_phase77_3_process_worker_deadline_discards_active_child():
    """Run in a clean one-thread parent before creating the COW child.

    The in-process and R3B tests above prove active native enforcement. This
    probe verifies that the public process transport preserves the typed budget
    error and tears the child down instead of retaining a timed-out account.
    """

    source = Path(__file__).resolve()
    code = (
        "import runpy; "
        f"namespace = runpy.run_path({str(source)!r}); "
        "namespace['_phase77_3_clean_process_deadline'](); "
        "print('phase77-3-clean-process-deadline-ok')"
    )
    environment = dict(os.environ)
    environment.update(
        {
            "OPENBLAS_NUM_THREADS": "1",
            "OMP_NUM_THREADS": "1",
            "MKL_NUM_THREADS": "1",
            "NUMEXPR_NUM_THREADS": "1",
            "NUMBA_NUM_THREADS": "1",
            "PYTHONPATH": str(Path.cwd() / "src"),
        }
    )
    completed = subprocess.run(
        [sys.executable, "-c", code],
        cwd=Path.cwd(),
        env=environment,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + "\n" + completed.stderr
    assert "phase77-3-clean-process-deadline-ok" in completed.stdout


def _phase77_3_clean_process_deadline() -> None:
    """Subprocess entry point for the process-worker deadline contract."""

    assert fork_reactive_wfo_worker_safe()
    frame = _frame(bars=20_000)
    prepared = _endpoint(frame).prepare_native_event_strategy(data=frame, symbols=["BTC"])
    marker = SimpleNamespace(
        params={},
        task=SimpleNamespace(
            start_bar=0,
            end_bar=len(frame),
            candidate_id="process-deadline",
            fold_id=0,
            stage="is",
        ),
    )
    worker = ForkReactiveWfoWorkerV1(
        adapter=_PoolAdapter(),
        prepared_runner=prepared,
        trading_days=365,
        parallelism_plan=ParallelismPlanV1.resolve(python_processes=1, rust_workers=1),
        max_inflight_tasks=1,
        max_wall_time_ms=1,
    )
    try:
        with pytest.raises(RuntimeBudgetError) as error:
            worker.score(marker, canceled=lambda: False)
        assert error.value.code == "MAX_WALL_TIME"
        assert worker.metadata()["worker_pid"] is None
    finally:
        worker.close()
