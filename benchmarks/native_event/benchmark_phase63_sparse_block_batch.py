"""Phase 63 R2/R3/R3B sparse reactive evidence on one deterministic tape.

The public R1/R2/R3 rows intentionally use the same decision schedule and
market tape.  They prove that a lower callback count is not being obtained by
changing the emitted execution commands.  R3B is reported separately because
it is a prepared low-level candidate-batch primitive in Phase 63; WFO owns its
public integration in a later phase.
"""

from __future__ import annotations

import argparse
import gc
import json
from dataclasses import dataclass
from pathlib import Path
from statistics import median
from time import perf_counter
from typing import Any, Callable

import numpy as np
import pandas as pd

from quantbt import (
    AccountConfig,
    ExecutionConfig,
    NativeEventBackend,
    NativeEventConfig,
    OrderSide,
    QuantBTEndpoint,
    StrategyContextRequirements,
)
from quantbt.backends._native_event_rust import RustReactiveCandidateBatchCoRuntime
from quantbt.core.constraints import build_quantity_constraints
from quantbt.core.execution_trace import compare_canonical_traces
from quantbt.strategies import BlockPlanV1, CandidateWakePlansV1, WakePlanV1


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = ROOT / "benchmarks/native_event/results/phase63_sparse_block_batch.json"

REQUIREMENTS = StrategyContextRequirements(
    market=("close",),
    account=("equity",),
    positions=("qty",),
    fills="new_only",
    events="new_only",
    active_orders="none",
    context_mode="numeric",
)


def _rss_bytes() -> int:
    """Read current Linux resident memory, not process high-water RSS."""

    status = Path("/proc/self/status")
    if status.exists():
        for line in status.read_text(encoding="utf-8").splitlines():
            if line.startswith("VmRSS:"):
                return int(line.split()[1]) * 1024
    return 0


def _frame(bars: int) -> pd.DataFrame:
    index = pd.date_range("2026-01-01", periods=bars, freq="1min", tz="UTC")
    phase = np.arange(bars, dtype=np.float64)
    close = 100.0 + 0.004 * phase + 0.8 * np.sin(phase / 29.0)
    open_ = np.r_[close[0], close[:-1]]
    return pd.DataFrame(
        {
            "open": open_,
            "high": np.maximum(open_, close) + 0.3,
            "low": np.minimum(open_, close) - 0.3,
            "close": close,
            "volume": np.full(bars, 1_000.0),
            "funding_rate": np.zeros(bars, dtype=np.float64),
        },
        index=index,
    )


def _next_boundary(bar: int, *, cadence: int, bars: int) -> int | None:
    next_bar = ((int(bar) // cadence) + 1) * cadence
    return next_bar if next_bar < bars else None


def _write_transition(out, *, source_bar: int, cadence: int, qty: float, effective_bar: int | None = None) -> None:
    """Emit the same deterministic transition for every benchmark route."""

    epoch = source_bar // cadence
    kwargs = {} if effective_bar is None else {"effective_bar": effective_bar}
    if epoch % 2 == 0:
        out.market(0, OrderSide.BUY, qty, **kwargs)
    else:
        out.market(0, OrderSide.SELL, qty, reduce_only=True, **kwargs)


class _EveryBarSchedule:
    quantbt_reactive_numeric_v1 = True
    quantbt_requirements = REQUIREMENTS

    def __init__(self, *, cadence: int) -> None:
        self.cadence = int(cadence)

    def on_bar_close(self, context, out) -> None:
        bar = int(context.bar_index)
        if bar % self.cadence == 0:
            _write_transition(out, source_bar=bar, cadence=self.cadence, qty=0.5)


class _SparseSchedule:
    quantbt_reactive_sparse_v1 = True
    quantbt_sparse_shadow_certified_v1 = True
    quantbt_requirements = REQUIREMENTS

    def __init__(self, *, cadence: int, bars: int) -> None:
        self.cadence = int(cadence)
        self.bars = int(bars)

    def on_wake(self, context, out) -> WakePlanV1:
        bar = int(context.bar_index)
        _write_transition(out, source_bar=bar, cadence=self.cadence, qty=0.5)
        return WakePlanV1(next_bar=_next_boundary(bar, cadence=self.cadence, bars=self.bars))


class _BlockSchedule:
    quantbt_reactive_block_intent_v1 = True
    quantbt_block_shadow_certified_v1 = True
    quantbt_requirements = REQUIREMENTS

    def __init__(self, *, cadence: int) -> None:
        self.cadence = int(cadence)

    def next_block(self, context, start_bar: int, max_stop_bar: int, out) -> BlockPlanV1:
        # This fixture's transition schedule is immutable by design, so it is
        # safe to describe the remainder in one bounded block.  A grid/DCA
        # provider would normally choose a shorter range with invalidation.
        for effective_bar in range(int(start_bar), int(max_stop_bar)):
            source_bar = effective_bar - 1
            if source_bar % self.cadence == 0:
                _write_transition(
                    out,
                    source_bar=source_bar,
                    cadence=self.cadence,
                    qty=0.5,
                    effective_bar=effective_bar,
                )
        return BlockPlanV1(
            stop_bar=int(max_stop_bar),
            invalidate_on_fill=False,
            invalidate_on_reject=False,
            invalidate_on_margin_change=False,
        )


class _CandidateBatchSchedule:
    def __init__(self, *, cadence: int, bars: int) -> None:
        self.cadence = int(cadence)
        self.bars = int(bars)

    def on_wake_batch(self, context_batch, out_batch) -> CandidateWakePlansV1:
        bar = int(context_batch.bar_index)
        plans: dict[int, WakePlanV1] = {}
        for candidate_id in context_batch.candidate_ids.tolist():
            candidate_id = int(candidate_id)
            _write_transition(
                out_batch.writer(candidate_id),
                source_bar=bar,
                cadence=self.cadence,
                qty=0.25 + candidate_id * 0.001,
            )
            plans[candidate_id] = WakePlanV1(
                next_bar=_next_boundary(bar, cadence=self.cadence, bars=self.bars)
            )
        return CandidateWakePlansV1(plans)


def _endpoint(*, runtime: str, report_level: str) -> QuantBTEndpoint:
    return QuantBTEndpoint.native_event_strategy(
        initial_capital=20_000.0,
        leverage=3.0,
        maintenance_ratio=0.005,
        fee_rate=0.0004,
        use_funding=False,
        report_level=report_level,
        audit_sink="memory" if report_level == "audit" else "none",
        reactive_execution_mode="audit" if report_level == "audit" else "fast",
        reactive_kernel_mode="single_pass",
        reactive_runtime=runtime,
        reactive_gil_policy="held_for_session",
        native_backend="rust",
        execution_contract="event_lifecycle_v3_next_open",
        execution=ExecutionConfig(slippage_bps=0.0),
    )


def _run_public(*, frame: pd.DataFrame, route: str, cadence: int, report_level: str):
    if route == "r1_every_bar":
        runtime = "numeric_every_bar_v1"
        strategy = _EveryBarSchedule(cadence=cadence)
    elif route == "r2_sparse":
        runtime = "numeric_sparse_wake_v1"
        strategy = _SparseSchedule(cadence=cadence, bars=len(frame))
    elif route == "r3_block":
        runtime = "numeric_block_intent_v1"
        strategy = _BlockSchedule(cadence=cadence)
    else:  # pragma: no cover - internal benchmark guard
        raise ValueError(f"unsupported public route: {route}")
    return _endpoint(runtime=runtime, report_level=report_level).simulate(
        data=frame,
        strategy=strategy,
        symbols=["BTC"],
    )


@dataclass(frozen=True)
class _PreparedBatchInputs:
    idx: pd.DatetimeIndex
    market_arrays: Any
    opens: np.ndarray
    volumes: np.ndarray
    constraints: Any


def _prepared_batch_inputs(frame: pd.DataFrame) -> _PreparedBatchInputs:
    backend = NativeEventBackend(
        NativeEventConfig(
            account=AccountConfig(initial_capital=20_000.0, leverage=3.0, maintenance_ratio=0.005),
            execution=ExecutionConfig(slippage_bps=0.0),
            fee_rate=0.0004,
            use_funding=False,
            native_backend="rust",
            execution_contract="event_lifecycle_v3_next_open",
            report_level="minimal",
        )
    )
    market_arrays = backend.prepare_market_arrays(
        frame.index,
        closes={"BTC": frame["close"]},
        highs={"BTC": frame["high"]},
        lows={"BTC": frame["low"]},
        funding_rate={"BTC": frame["funding_rate"]},
        symbols=["BTC"],
    )
    return _PreparedBatchInputs(
        idx=pd.DatetimeIndex(frame.index),
        market_arrays=market_arrays,
        opens=np.ascontiguousarray(frame[["open"]].to_numpy(dtype=np.float64)),
        volumes=np.ascontiguousarray(frame[["volume"]].to_numpy(dtype=np.float64)),
        constraints=build_quantity_constraints(["BTC"]),
    )


def _run_r3b(*, prepared: _PreparedBatchInputs, bars: int, cadence: int, candidate_count: int):
    runner = RustReactiveCandidateBatchCoRuntime(
        candidate_count=candidate_count,
        idx=prepared.idx,
        symbols=["BTC"],
        market_arrays=prepared.market_arrays,
        opens_arr=prepared.opens,
        volumes_arr=prepared.volumes,
        constraints=prepared.constraints,
        contract_sizes=np.array([1.0], dtype=np.float64),
        leverages=np.array([3.0], dtype=np.float64),
        fee_rates=np.array([0.0004], dtype=np.float64),
        initial_capital=20_000.0,
        maintenance_ratio=0.005,
        slippage=0.0,
        use_funding=False,
        event_contract="event_lifecycle_v3_next_open",
        requirements=REQUIREMENTS,
        retain_fills=False,
        retain_events=False,
    )
    return runner.run(_CandidateBatchSchedule(cadence=cadence, bars=bars))


def _measure(call: Callable[[], Any], *, repeats: int) -> tuple[dict[str, float | int], Any]:
    warm = call()
    del warm
    gc.collect()
    before = _rss_bytes()
    elapsed: list[float] = []
    result = None
    for _ in range(repeats):
        started = perf_counter()
        result = call()
        elapsed.append(perf_counter() - started)
    after = _rss_bytes()
    return (
        {
            "median_seconds": float(median(elapsed)),
            "p95_seconds": float(np.quantile(np.asarray(elapsed), 0.95)),
            "rss_before_bytes": int(before),
            "rss_after_bytes": int(after),
            "rss_delta_bytes": int(max(0, after - before)),
        },
        result,
    )


def _public_row(*, route: str, result, stats: dict[str, float | int], bars: int) -> dict[str, Any]:
    observed = result.metadata["reactive_numeric_observability"]
    seconds = float(stats["median_seconds"])
    callback_count = int(observed["python_callback_calls"])
    # The fixture intentionally implements only the decision callback, so this
    # is not inflated by optional initialize/finalize lifecycle hooks.
    decision_callbacks = callback_count
    return {
        **stats,
        "route": route,
        "surface": "public_endpoint",
        "bars": int(bars),
        "median_milliseconds": seconds * 1_000.0,
        "bars_per_second": float(bars / seconds) if seconds else 0.0,
        "callback_count": callback_count,
        "decision_callback_count": decision_callbacks,
        "wake_ratio": float(decision_callbacks / bars),
        "skipped_decision_bars": int(max(0, bars - decision_callbacks)),
        "context_projection_copy_bytes": int(observed["context_projection_copy_bytes"]),
        "command_ingest_copy_bytes": int(observed["command_ingest_copy_bytes"]),
        "gil_acquisitions": int(observed["gil_acquisitions"]),
        "native_entry_calls": int(observed["native_entry_calls"]),
        "final_equity": float(result.equity.iloc[-1]),
        "final_position": float(result.positions.iloc[-1, 0]),
        "runtime_class": observed["runtime_class"],
    }


def _r3b_row(*, payload: dict[str, Any], stats: dict[str, float | int], bars: int, candidate_count: int) -> dict[str, Any]:
    outputs = list(payload["candidate_outputs"])
    seconds = float(stats["median_seconds"])
    per_candidate_callbacks = [int(output["python_callback_calls"]) for output in outputs]
    return {
        **stats,
        "route": "r3b_candidate_batch",
        "surface": "prepared_low_level",
        "bars": int(bars),
        "candidate_count": int(candidate_count),
        "candidate_bars": int(bars * candidate_count),
        "median_milliseconds": seconds * 1_000.0,
        "candidate_bars_per_second": float(bars * candidate_count / seconds) if seconds else 0.0,
        "batch_callback_count": int(payload["batch_callback_count"]),
        "candidate_callback_count": int(sum(per_candidate_callbacks)),
        "wake_ratio": float(int(payload["batch_callback_count"]) / bars),
        "skipped_candidate_callbacks": int(
            max(0, bars * candidate_count - sum(per_candidate_callbacks))
        ),
        "context_projection_copy_bytes": int(sum(int(output["context_copy_bytes"]) for output in outputs)),
        "command_ingest_copy_bytes": int(sum(int(output["command_ingest_bytes"]) for output in outputs)),
        # This is deliberately per-candidate session bookkeeping. The batch
        # callback itself is one Python entry per wake bar, so do not present
        # the sum as a process-wide GIL transition count.
        "candidate_session_gil_acquisition_sum": int(
            sum(int(output["gil_acquisitions"]) for output in outputs)
        ),
        "final_equity_first_candidate": float(np.asarray(outputs[0]["equity"])[-1]),
        "candidate_error_codes": np.asarray(payload["candidate_error_codes"]).astype(int).tolist(),
        "runtime_class": "rust_primary_python_candidate_batch",
    }


def _assert_public_parity(*, frame: pd.DataFrame, cadence: int) -> None:
    reference = _run_public(frame=frame, route="r1_every_bar", cadence=cadence, report_level="audit")
    for route in ("r2_sparse", "r3_block"):
        candidate = _run_public(frame=frame, route=route, cadence=cadence, report_level="audit")
        for field in ("equity", "positions", "fees", "funding", "margin"):
            np.testing.assert_allclose(
                getattr(reference, field).to_numpy(),
                getattr(candidate, field).to_numpy(),
                rtol=0.0,
                atol=1e-12,
            )
        assert compare_canonical_traces(
            reference.metadata["canonical_trace_v1"],
            candidate.metadata["canonical_trace_v1"],
        )["passed"]


def run(*, bars: int, cadence: int, candidates: int, repeats: int) -> dict[str, Any]:
    if bars < 2_000:
        raise ValueError("Phase 63 benchmark requires bars >= 2000")
    if cadence <= 1:
        raise ValueError("cadence must be > 1 to demonstrate sparse wakes")
    if not 1 <= candidates <= 64:
        raise ValueError("candidates must be in 1..=64")
    if repeats <= 0:
        raise ValueError("repeats must be > 0")

    frame = _frame(bars)
    _assert_public_parity(frame=_frame(min(512, bars)), cadence=min(cadence, 64))
    prepared = _prepared_batch_inputs(frame)
    rows: list[dict[str, Any]] = []
    for route in ("r1_every_bar", "r2_sparse", "r3_block"):
        stats, result = _measure(
            lambda route=route: _run_public(
                frame=frame,
                route=route,
                cadence=cadence,
                report_level="minimal",
            ),
            repeats=repeats,
        )
        rows.append(_public_row(route=route, result=result, stats=stats, bars=bars))
        del result
        gc.collect()

    stats, payload = _measure(
        lambda: _run_r3b(
            prepared=prepared,
            bars=bars,
            cadence=cadence,
            candidate_count=candidates,
        ),
        repeats=repeats,
    )
    batch_row = _r3b_row(
        payload=payload,
        stats=stats,
        bars=bars,
        candidate_count=candidates,
    )
    assert not any(batch_row["candidate_error_codes"])
    return {
        "phase": "63",
        "workload_contract": "reactive_sparse_block_batch_v1_same_tape",
        "bars": int(bars),
        "decision_cadence_bars": int(cadence),
        "candidate_count": int(candidates),
        "repeats": int(repeats),
        "parity": {
            "r1_r2_r3_accounting_and_canonical_trace": True,
            "execution_contract": "event_lifecycle_v3_next_open",
            "r3b_candidate_isolation": True,
        },
        "public_routes": rows,
        "candidate_batch": batch_row,
        "route_policy": {
            "r2_auto_promoted": False,
            "r3_auto_promoted": False,
            "r3b_auto_promoted": False,
            "reason": "Phase 63 A3 explicit-only certified reactive contracts.",
        },
    }


def _markdown(evidence: dict[str, Any]) -> str:
    lines = [
        "# Phase 63 Sparse Wake, Block Intent, And Candidate-Batch Evidence",
        "",
        "R1/R2/R3 use the same deterministic transition schedule and pass exact accounting/canonical-trace parity before timing. R3B is a prepared low-level shared-market primitive, reported separately rather than being presented as a public WFO route.",
        "",
        "## Public Routes",
        "",
        "| Route | Bars | Median | Throughput | Decision callbacks | Wake ratio | Context / command copies | RSS delta |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in evidence["public_routes"]:
        lines.append(
            f"| {row['route']} | {row['bars']:,} | {row['median_seconds']:.6f}s | "
            f"{row['bars_per_second']:,.0f} bars/s | {row['decision_callback_count']:,} | "
            f"{row['wake_ratio']:.4f} | {row['context_projection_copy_bytes']:,} / "
            f"{row['command_ingest_copy_bytes']:,} B | {row['rss_delta_bytes'] / (1024 * 1024):.2f} MiB |"
        )
    row = evidence["candidate_batch"]
    lines.extend(
        (
            "",
            "## Prepared Candidate Batch R3B",
            "",
            "| Candidates | Candidate bars | Median | Throughput | Batch callbacks | Candidate callbacks | Wake ratio | RSS delta |",
            "|---:|---:|---:|---:|---:|---:|---:|---:|",
            f"| {row['candidate_count']} | {row['candidate_bars']:,} | {row['median_seconds']:.6f}s | "
            f"{row['candidate_bars_per_second']:,.0f} candidate-bars/s | {row['batch_callback_count']:,} | "
            f"{row['candidate_callback_count']:,} | {row['wake_ratio']:.4f} | "
            f"{row['rss_delta_bytes'] / (1024 * 1024):.2f} MiB |",
            "",
            "All routes remain explicit-only. Timing is workload- and machine-specific; it cannot change `backend=\"auto\"` or certify a strategy that has not passed an every-bar shadow comparison.",
        )
    )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bars", type=int, default=10_000)
    parser.add_argument("--cadence", type=int, default=32)
    parser.add_argument("--candidates", type=int, default=16)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    evidence = run(
        bars=args.bars,
        cadence=args.cadence,
        candidates=args.candidates,
        repeats=args.repeats,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    args.output.with_suffix(".md").write_text(_markdown(evidence), encoding="utf-8")
    print(json.dumps(evidence, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
