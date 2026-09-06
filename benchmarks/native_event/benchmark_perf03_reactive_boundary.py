#!/usr/bin/env python3
"""PERF-03 reactive callback-boundary benchmark.

This is a development measurement harness, not a backend-promotion gate.  It
keeps the public native-event facade in the timed path and reports the Python
decision residual separately from Rust accounting.  Dynamic and run-stable
callback binding are verified for financial parity before their timed samples
are collected.

The workload labels map to the PERF-03 guide:

* B-02: repeated numeric context getters;
* B-03: many primitive writer rows per callback;
* B-04: Python-heavy decision work;
* B-05: declared sparse wakes; and
* B-06: frequent grid-like enter/reduce commands.

The no-op route is included as a control rather than a separate registered
benchmark class.
"""

from __future__ import annotations

import argparse
import json
import resource
import sys
import time
from pathlib import Path
from statistics import median
from typing import Any, Callable

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
for candidate in (SRC, ROOT):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

from quantbt import (  # noqa: E402
    ExecutionConfig,
    OrderSide,
    QuantBTEndpoint,
    StrategyContextRequirements,
)
from quantbt.strategies import WakePlanV1  # noqa: E402


NUMERIC_REQUIREMENTS = StrategyContextRequirements(
    market=("open", "high", "low", "close"),
    account=("equity", "available_equity"),
    positions=("qty",),
    fills="none",
    events="none",
    active_orders="none",
    context_mode="numeric",
)


def _rss_mb() -> float:
    status = Path("/proc/self/status")
    if status.exists():
        for line in status.read_text(encoding="utf-8").splitlines():
            if line.startswith("VmRSS:"):
                return float(line.split()[1]) / 1024.0
    value = float(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    return value / 1024.0 if sys.platform == "linux" else value / (1024.0 * 1024.0)


def _peak_rss_mb() -> float:
    value = float(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    return value / 1024.0 if sys.platform == "linux" else value / (1024.0 * 1024.0)


def _frame(bars: int) -> pd.DataFrame:
    index = pd.date_range("2026-01-01", periods=bars, freq="1h", tz="UTC")
    phase = np.arange(bars, dtype=np.float64)
    close = 100.0 + 0.025 * phase + 1.25 * np.sin(phase / 19.0)
    open_ = np.r_[close[0], close[:-1]]
    return pd.DataFrame(
        {
            "open": open_,
            "high": np.maximum(open_, close) + 0.75,
            "low": np.minimum(open_, close) - 0.75,
            "close": close,
            "volume": np.full(bars, 5_000.0),
        },
        index=index,
    )


def _endpoint(*, runtime: str, report_level: str) -> QuantBTEndpoint:
    return QuantBTEndpoint.native_event_strategy(
        initial_capital=100_000.0,
        leverage=4.0,
        maintenance_ratio=0.005,
        fee_rate=0.0004,
        qty_step=0.25,
        min_qty=0.25,
        min_notional=10.0,
        use_funding=False,
        report_level=report_level,
        audit_sink="memory" if report_level == "audit" else "none",
        native_backend="rust",
        reactive_kernel_mode="single_pass",
        reactive_runtime=runtime,
        reactive_gil_policy="held_for_session",
        execution_contract="event_lifecycle_v3_next_open",
        execution=ExecutionConfig(slippage_bps=0.0),
    )


class _RunStableMixin:
    quantbt_reactive_callback_binding_v1 = "run_stable"


class _EveryBarBase:
    quantbt_reactive_numeric_v1 = True
    quantbt_requirements = NUMERIC_REQUIREMENTS


class NoOpEveryBar(_EveryBarBase):
    def on_bar_close(self, context, out) -> None:
        return None


class GetterEveryBar(_EveryBarBase):
    def __init__(self, repeats: int = 12) -> None:
        self.repeats = int(repeats)
        self.accumulator = 0.0

    def on_bar_close(self, context, out) -> None:
        value = 0.0
        for _ in range(self.repeats):
            value += (
                context.open(0)
                + context.high(0)
                + context.low(0)
                + context.close(0)
                + context.equity
                + context.available_equity
                + context.position_qty(0)
            )
        self.accumulator += value


class CommandBurstEveryBar(_EveryBarBase):
    def __init__(self, *, bars: int, rows: int = 8) -> None:
        self.bars = int(bars)
        self.rows = int(rows)

    def on_bar_close(self, context, out) -> None:
        if context.bar_index == 0:
            for _ in range(self.rows):
                out.market(0, OrderSide.BUY, 0.25, tif="ioc")
        elif context.bar_index == self.bars // 2:
            for _ in range(self.rows):
                out.market(0, OrderSide.SELL, 0.25, tif="ioc", reduce_only=True)


class PythonHeavyEveryBar(_EveryBarBase):
    def __init__(self, repeats: int = 600) -> None:
        self.repeats = int(repeats)
        self.accumulator = 0.0

    def on_bar_close(self, context, out) -> None:
        value = context.close(0)
        for offset in range(self.repeats):
            value = (value * 1.0000001) + ((offset % 7) - 3) * 0.000001
        self.accumulator += value


class GridLikeEveryBar(_EveryBarBase):
    def on_bar_close(self, context, out) -> None:
        bar = int(context.bar_index)
        if bar % 16 == 0:
            out.market(0, OrderSide.BUY, 0.25, tif="ioc")
        elif bar % 16 == 8:
            out.market(0, OrderSide.SELL, 0.25, tif="ioc", reduce_only=True)


class SparseClock:
    quantbt_reactive_sparse_v1 = True
    quantbt_sparse_shadow_certified_v1 = True
    quantbt_requirements = NUMERIC_REQUIREMENTS

    def __init__(self, *, bars: int) -> None:
        self.bars = int(bars)

    def on_wake(self, context, out) -> WakePlanV1:
        if context.bar_index == 0:
            return WakePlanV1(next_bar=self.bars - 2)
        return WakePlanV1()


def _stable_factory(factory: Callable[[], object]) -> Callable[[], object]:
    def build():
        instance = factory()
        # A dynamic subclass would make benchmark provenance harder to read;
        # the marker is deliberately attached to this one fresh instance only.
        instance.quantbt_reactive_callback_binding_v1 = "run_stable"
        return instance

    return build


def _run(
    frame: pd.DataFrame,
    *,
    runtime: str,
    strategy: object,
    report_level: str,
):
    return _endpoint(runtime=runtime, report_level=report_level).simulate(
        data=frame,
        strategy=strategy,
        symbols=["BTC"],
    )


def _assert_financial_parity(left, right) -> None:
    for field in ("equity", "positions", "fees", "funding", "margin"):
        np.testing.assert_allclose(
            getattr(left, field).to_numpy(),
            getattr(right, field).to_numpy(),
            rtol=0.0,
            atol=1e-12,
        )
    assert left.liquidated is right.liquidated
    assert left.liquidation_bar == right.liquidation_bar


def _timed_case(
    *,
    name: str,
    workload: str,
    frame: pd.DataFrame,
    runtime: str,
    factory: Callable[[], object],
    repeats: int,
) -> dict[str, Any]:
    # Warm the extension and verify that callback binding is only an access
    # optimization. Audit mode is intentionally outside the timed samples.
    dynamic = _run(
        frame,
        runtime=runtime,
        strategy=factory(),
        report_level="audit",
    )
    pinned = _run(
        frame,
        runtime=runtime,
        strategy=_stable_factory(factory)(),
        report_level="audit",
    )
    _assert_financial_parity(dynamic, pinned)

    builders = {
        "dynamic": factory,
        "run_stable": _stable_factory(factory),
    }
    for build in builders.values():
        _run(frame, runtime=runtime, strategy=build(), report_level="minimal")

    elapsed_by_binding: dict[str, list[int]] = {binding: [] for binding in builders}
    last_observability: dict[str, dict[str, Any]] = {binding: {} for binding in builders}
    rss_before = _rss_mb()
    # Alternate the first route in each pair so cache/thermal drift cannot be
    # mistaken for a callback-binding speedup.
    for repeat in range(repeats):
        order = ("dynamic", "run_stable") if repeat % 2 == 0 else ("run_stable", "dynamic")
        for binding in order:
            build = builders[binding]
            started = time.perf_counter_ns()
            result = _run(frame, runtime=runtime, strategy=build(), report_level="minimal")
            elapsed_by_binding[binding].append(time.perf_counter_ns() - started)
            last_observability[binding] = dict(result.metadata["reactive_numeric_observability"])

    rss_after = _rss_mb()
    samples: list[dict[str, Any]] = []
    for binding in ("dynamic", "run_stable"):
        elapsed_ns = elapsed_by_binding[binding]
        observability = last_observability[binding]
        elapsed_median = median(elapsed_ns)
        samples.append(
            {
                "binding": binding,
                "median_wall_ms": elapsed_median / 1_000_000.0,
                "min_wall_ms": min(elapsed_ns) / 1_000_000.0,
                "max_wall_ms": max(elapsed_ns) / 1_000_000.0,
                "bars_per_second": len(frame) / (elapsed_median / 1_000_000_000.0),
                "rss_delta_mb": rss_after - rss_before,
                "callback_binding_mode": observability["callback_binding_mode"],
                "callback_plan_compile_ns": int(observability["callback_plan_compile_ns"]),
                "callback_lookup_ns": int(observability["callback_lookup_ns"]),
                "callback_dynamic_lookup_count": int(
                    observability["callback_dynamic_lookup_count"]
                ),
                "python_callback_calls": int(observability["python_callback_calls"]),
                "context_projection_count": int(observability["context_projection_count"]),
                "context_getter_calls": int(observability["context_getter_calls"]),
                "command_writer_calls": int(observability["command_writer_calls"]),
                "command_rows": int(observability["command_rows"]),
                "command_rows_dropped": int(observability["command_rows_dropped"]),
                "command_staged_rows_discarded": int(
                    observability["command_staged_rows_discarded"]
                ),
                "engine_ns": int(observability["engine_ns"]),
                "callback_ns": int(observability["callback_ns"]),
            }
        )
    return {
        "name": name,
        "workload": workload,
        "runtime": runtime,
        "bars": len(frame),
        "repeats": repeats,
        "sample_order": "alternating_dynamic_run_stable",
        "rss_before_timed_mb": rss_before,
        "rss_after_timed_mb": rss_after,
        "audit_dynamic_pinned_parity": True,
        "samples": samples,
    }


def _render(payload: dict[str, Any]) -> str:
    lines = [
        "# PERF-03 Reactive Boundary Benchmark",
        "",
        "This is a development measurement from one local machine. It reports full public-facade time; it is not a universal backend promotion claim.",
        "",
        "Process RSS for the complete same-process run: initial `{initial_rss_mb:.2f}` MiB, post-run `{post_run_rss_mb:.2f}` MiB, peak `{peak_rss_mb:.2f}` MiB. Per-row RSS delta is sampled only across that case's timed pair after its audit/warm-up run, so it is not a substitute for the complete-process figure.".format(**payload),
        "",
        "| Workload | Binding | Median ms | Bars/s | Dynamic lookups | Projections | Getters | Writer calls | Rows | RSS delta MB |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for case in payload["cases"]:
        for sample in case["samples"]:
            lines.append(
                "| {workload} | {binding} | {median_wall_ms:.3f} | {bars_per_second:.1f} | {callback_dynamic_lookup_count} | {context_projection_count} | {context_getter_calls} | {command_writer_calls} | {command_rows} | {rss_delta_mb:.2f} |".format(
                    workload=case["workload"], **sample
                )
            )
    lines.extend(
        [
            "",
            "Dynamic binding is the compatibility default. `run_stable` is valid only when the strategy does not replace lifecycle callbacks while one run is active.",
            "Business admission remains per command; callback exceptions discard only unsubmitted staged rows and poison the reusable session until reset.",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bars", type=int, default=2_000)
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument(
        "--json-output",
        type=Path,
        default=ROOT / "benchmarks/native_event/results/perf_03_reactive_boundary.json",
    )
    parser.add_argument(
        "--markdown-output",
        type=Path,
        default=ROOT / "benchmarks/native_event/results/perf_03_reactive_boundary.md",
    )
    args = parser.parse_args()
    if args.bars < 32:
        raise SystemExit("--bars must be at least 32")
    if args.repeats <= 0:
        raise SystemExit("--repeats must be positive")

    frame = _frame(args.bars)
    cases = (
        ("noop_every_bar", "control no-op callback", "numeric_every_bar_v1", lambda: NoOpEveryBar()),
        ("many_getters", "B-02 many getters", "numeric_every_bar_v1", lambda: GetterEveryBar()),
        (
            "command_burst",
            "B-03 many commands/callback",
            "numeric_every_bar_v1",
            lambda: CommandBurstEveryBar(bars=args.bars),
        ),
        (
            "python_heavy",
            "B-04 Python-heavy decision",
            "numeric_every_bar_v1",
            lambda: PythonHeavyEveryBar(),
        ),
        (
            "sparse_clock",
            "B-05 declared sparse wake",
            "numeric_sparse_wake_v1",
            lambda: SparseClock(bars=args.bars),
        ),
        ("grid_like", "B-06 high-churn grid-like", "numeric_every_bar_v1", lambda: GridLikeEveryBar()),
    )
    payload = {
        "schema_version": "quantbt-perf-03-reactive-boundary-v1",
        "bars": args.bars,
        "repeats": args.repeats,
        "initial_rss_mb": _rss_mb(),
        "cases": [
            _timed_case(
                name=name,
                workload=workload,
                frame=frame,
                runtime=runtime,
                factory=factory,
                repeats=args.repeats,
            )
            for name, workload, runtime, factory in cases
        ],
    }
    payload["post_run_rss_mb"] = _rss_mb()
    payload["peak_rss_mb"] = _peak_rss_mb()
    args.json_output.parent.mkdir(parents=True, exist_ok=True)
    args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
    args.json_output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    args.markdown_output.write_text(_render(payload), encoding="utf-8")
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
