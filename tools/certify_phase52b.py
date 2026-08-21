#!/usr/bin/env python3
"""Produce repeatable Phase 52B boundary, parity, and RSS evidence."""

from __future__ import annotations

import argparse
import gc
import json
import os
from dataclasses import replace
from pathlib import Path
from statistics import median
import time

import numpy as np
import pandas as pd

import quantbt
from quantbt import CallbackSchedule, QuantBTEndpoint, StrategyContextRequirements, TimeInForce
from quantbt.preparation import ResetScope


def bars(count: int) -> pd.DataFrame:
    index = pd.date_range("2026-01-01", periods=count, freq="15min", tz="UTC")
    wave = np.sin(np.arange(count, dtype=np.float64) / 23.0) * 2.0
    close = 100.0 + wave + np.arange(count, dtype=np.float64) * 0.002
    return pd.DataFrame(
        {
            "open": close - 0.05,
            "high": close + 0.75,
            "low": close - 0.75,
            "close": close,
            "volume": 1_000.0 + np.arange(count, dtype=np.float64) % 17,
        },
        index=index,
    )


class NumericRoundTrip:
    quantbt_requirements = StrategyContextRequirements(
        market=("close",),
        account=("equity", "liquidated"),
        positions=("qty",),
        fills="none",
        events="none",
        active_orders="none",
        context_mode="numeric",
    )

    def __init__(self, exit_bar: int):
        self.exit_bar = int(exit_bar)

    def on_bar_close(self, context, out):
        if context.bar_index == 2:
            out.market(0, 1, 1.0, order_handle=1, tif=TimeInForce.IOC)
        elif context.bar_index == self.exit_bar:
            out.market(0, -1, 1.0, order_handle=2, tif=TimeInForce.IOC, reduce_only=True)


class SparseNoOp:
    _requirements = StrategyContextRequirements(
        market=("close",),
        account=("equity", "liquidated"),
        positions=(),
        fills="none",
        events="none",
        active_orders="none",
        context_mode="numeric",
    )

    def __init__(self, wake_bars: tuple[int, ...]):
        self.quantbt_requirements = replace(
            self._requirements,
            callback=CallbackSchedule(
                every_n_bars=None,
                explicit_bars=wake_bars,
                on_fill=False,
                on_order_event=False,
                on_liquidation=True,
            ),
        )

    def on_bar_close(self, context, out):
        return None


def endpoint(backend: str, *, report_level: str = "minimal") -> QuantBTEndpoint:
    return QuantBTEndpoint.native_event_strategy(
        initial_capital=10_000.0,
        leverage=5.0,
        maintenance_ratio=0.0,
        fee_rate=0.0002,
        slippage=0.0001,
        use_funding=False,
        native_backend=backend,
        reactive_kernel_mode="single_pass",
        audit_mode="native_trace",
        report_level=report_level,
        audit_sink="memory" if report_level == "audit" else "none",
    )


def rss_bytes() -> int:
    fields = Path("/proc/self/statm").read_text(encoding="ascii").split()
    return int(fields[1]) * int(os.sysconf("SC_PAGE_SIZE"))


def timed_runs(prepared, count: int, exit_bar: int) -> list[float]:
    values = []
    for _ in range(count):
        started = time.perf_counter_ns()
        prepared.run(NumericRoundTrip(exit_bar), report_level="minimal")
        values.append((time.perf_counter_ns() - started) / 1_000_000.0)
    return values


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bars", type=int, default=2_000)
    parser.add_argument("--timing-runs", type=int, default=7)
    parser.add_argument("--reset-runs", type=int, default=2_000)
    parser.add_argument("--rss-budget-mib", type=float, default=32.0)
    parser.add_argument(
        "--expected-site",
        type=Path,
        help="Require quantbt to resolve from an installed wheel site-packages directory.",
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.expected_site is not None:
        expected_site = args.expected_site.resolve()
        module_path = Path(quantbt.__file__).resolve()
        try:
            module_path.relative_to(expected_site)
        except ValueError as exc:
            raise RuntimeError(
                f"quantbt resolved from {module_path}, not expected installed site {expected_site}"
            ) from exc
    frame = bars(args.bars)
    exit_bar = args.bars - 4

    python_prepared = endpoint("python", report_level="audit").prepare_native_event_strategy(
        data=frame, symbols=["BTC"]
    )
    rust_prepared = endpoint("rust", report_level="audit").prepare_native_event_strategy(
        data=frame, symbols=["BTC"]
    )
    python_result = python_prepared.run(NumericRoundTrip(exit_bar), report_level="audit")
    rust_result = rust_prepared.run(NumericRoundTrip(exit_bar), report_level="audit")

    parity = {
        "equity": bool(np.array_equal(rust_result.equity.to_numpy(), python_result.equity.to_numpy())),
        "positions": bool(np.array_equal(rust_result.positions.to_numpy(), python_result.positions.to_numpy())),
        "fees": bool(np.array_equal(rust_result.fees.to_numpy(), python_result.fees.to_numpy())),
        "funding": bool(np.array_equal(rust_result.funding.to_numpy(), python_result.funding.to_numpy())),
        "margin": bool(np.array_equal(rust_result.margin.to_numpy(), python_result.margin.to_numpy())),
        "trace_fingerprint": (
            rust_result.metadata["canonical_trace_fingerprint"]
            == python_result.metadata["canonical_trace_fingerprint"]
        ),
    }

    rust_minimal = rust_prepared.run(NumericRoundTrip(exit_bar), report_level="minimal")
    boundary = rust_minimal.metadata["strategy_boundary"]
    counters = rust_minimal.metadata["execution_counters"]
    sparse_wake_bars = tuple(bar for bar in (0, 500, 1_000, 1_500) if bar < args.bars)
    sparse = rust_prepared.run(SparseNoOp(sparse_wake_bars), report_level="minimal")

    memory_frame = bars(32)
    memory_prepared = endpoint("rust", report_level="audit").prepare_native_event_strategy(
        data=memory_frame, symbols=["BTC"]
    )
    captured = []
    original_factory = memory_prepared.backend._create_reactive_session

    def capture(**kwargs):
        session = original_factory(**kwargs)
        captured.append(session)
        return session

    memory_prepared.backend._create_reactive_session = capture
    reset_result = memory_prepared.run(NumericRoundTrip(28), report_level="audit")
    session = captured[-1]
    commands = tuple(reset_result.metadata["emitted_command_tape"])

    def rerun() -> None:
        session.reset(ResetScope.ACCOUNT_AND_ORDERS)
        for command in commands:
            bar = int(session.idx.searchsorted(pd.Timestamp(command.timestamp), side="left"))
            session.schedule(bar, (command,))
        session.process_bar(len(session.idx) - 1)

    for _ in range(100):
        rerun()
    gc.collect()
    rss_start = rss_bytes()
    for _ in range(args.reset_runs):
        rerun()
    gc.collect()
    rss_end = rss_bytes()
    rss_growth = max(0, rss_end - rss_start)

    python_times = timed_runs(python_prepared, args.timing_runs, exit_bar)
    rust_times = timed_runs(rust_prepared, args.timing_runs, exit_bar)
    observability = rust_minimal.metadata["observability"]
    checks = {
        "python_rust_exact_parity": all(parity.values()),
        "rust_single_authoritative_state": (
            rust_minimal.metadata["state_owner"] == "rust"
            and rust_minimal.metadata["authoritative_mutable_state_count"] == 1
            and rust_minimal.metadata["python_shadow_accounting"] is False
        ),
        "numeric_writer_zero_order_objects": (
            boundary["writer_command_rows"] == 2
            and boundary["writer_materialized_command_objects"] == 0
            and counters["primitive_command_rows"] == 2
        ),
        "numeric_minimal_no_active_snapshots": (
            counters["active_snapshot_materializations"] == 0
        ),
        "native_audit_single_primary_run": (
            rust_result.metadata["primary_engine_runs"] == 1
            and rust_result.metadata["oracle_engine_runs"] == 0
        ),
        "sparse_callback_schedule": (
            sparse.metadata["strategy_boundary"]["python_callbacks"] == len(sparse_wake_bars)
            and sparse.metadata["strategy_callback_count"] == len(sparse_wake_bars)
        ),
        "reset_rerun_exact": bool(
            np.array_equal(session.equity_path, reset_result.equity.to_numpy())
        ),
        "reset_rss_plateau": rss_growth <= int(args.rss_budget_mib * 1024 * 1024),
        "phase_timings_present": all(
            key in observability
            for key in (
                "planning_ns", "market_prepare_ns", "strategy_prepare_ns",
                "command_compile_ns", "engine_run_ns", "result_adapt_ns", "report_build_ns",
            )
        ),
    }
    report = {
        "certification": "phase52b-strategy-rust-ownership-v1",
        "quantbt_path": str(Path(quantbt.__file__).resolve()),
        "bars": int(args.bars),
        "parity": parity,
        "boundary": boundary,
        "execution_counters": counters,
        "observability_ns": observability,
        "timing_ms": {
            "python_median": round(median(python_times), 6),
            "rust_median": round(median(rust_times), 6),
            "runs": int(args.timing_runs),
            "workload": f"{args.bars:,}-bar every-bar numeric Python callback",
        },
        "memory": {
            "reset_runs": int(args.reset_runs),
            "warmup_runs": 100,
            "rss_start_bytes": int(rss_start),
            "rss_end_bytes": int(rss_end),
            "rss_growth_bytes": int(rss_growth),
            "rss_budget_bytes": int(args.rss_budget_mib * 1024 * 1024),
        },
        "checks": checks,
        "passed": all(checks.values()),
    }
    payload = json.dumps(report, indent=2, sort_keys=True)
    print(payload)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload + "\n", encoding="utf-8")
    if not report["passed"]:
        raise RuntimeError("Phase 52B certification failed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
