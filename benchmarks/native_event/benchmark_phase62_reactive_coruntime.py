"""Phase 62 reactive numeric co-runtime end-to-end evidence.

The fixture deliberately keeps feature logic in Python and calls it at every
bar.  It compares the legacy Python loop, the existing Rust per-bar bridge,
and the explicit R1 Rust-led co-runtime.  This is not a static-tape benchmark:
all measured routes include callback and public-result adaptation cost.
"""

from __future__ import annotations

import argparse
import gc
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from statistics import median
from time import perf_counter
from typing import Any, Callable

import numpy as np
import pandas as pd

from quantbt import (
    OrderSide,
    QuantBTEndpoint,
    StrategyContextRequirements,
)
from quantbt.core.execution_trace import compare_canonical_traces


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = ROOT / "benchmarks/native_event/results/phase62_reactive_coruntime.json"


def _rss_bytes() -> int:
    """Return current Linux RSS; do not confuse it with process high-water RSS."""

    status = Path("/proc/self/status")
    if status.exists():
        for line in status.read_text(encoding="utf-8").splitlines():
            if line.startswith("VmRSS:"):
                return int(line.split()[1]) * 1024
    return 0


def _frame(bars: int) -> pd.DataFrame:
    index = pd.date_range("2026-01-01", periods=bars, freq="1min", tz="UTC")
    phase = np.arange(bars, dtype=np.float64)
    close = 100.0 + 0.003 * phase + 1.1 * np.sin(phase / 31.0)
    open_ = np.r_[close[0], close[:-1]] + 0.02 * np.cos(phase / 7.0)
    return pd.DataFrame(
        {
            "open": open_,
            "high": np.maximum(open_, close) + 0.8,
            "low": np.minimum(open_, close) - 0.8,
            "close": close,
            "volume": 1_000.0,
            "funding_rate": np.where(phase % 480 == 0, 0.0001, 0.0),
        },
        index=index,
    )


class NumericEveryBarFixture:
    """One numeric callback per bar with tunable command churn."""

    quantbt_reactive_numeric_v1 = True
    quantbt_requirements = StrategyContextRequirements(
        market=("close",),
        account=("equity",),
        positions=("qty",),
        fills="new_only",
        events="new_only",
        active_orders="none",
        context_mode="numeric",
    )

    def __init__(self, *, every: int | None, hold: int = 1) -> None:
        self.every = every
        self.hold = int(hold)
        self.callback_count = 0
        self.decision_checksum = 0.0

    def on_bar_close(self, context, out) -> None:
        # The scalar reads keep the timed path representative of a small
        # strategy decision without building a pandas/context object.
        self.callback_count += 1
        self.decision_checksum += context.close(0) * 1e-12 + context.equity * 1e-15
        if self.every is None:
            return
        bar = int(context.bar_index)
        if bar % self.every == 0:
            out.market(0, OrderSide.BUY, 0.25, tif="ioc")
        elif bar % self.every == self.hold:
            out.market(0, OrderSide.SELL, 0.25, tif="ioc", reduce_only=True)

    def quantbt_state_fingerprint(self) -> tuple[int, float]:
        return self.callback_count, round(self.decision_checksum, 12)


def _endpoint(
    *,
    native_backend: str,
    reactive_runtime: str,
    reactive_gil_policy: str = "held_for_session",
    report_level: str = "minimal",
) -> QuantBTEndpoint:
    return QuantBTEndpoint.native_event_strategy(
        initial_capital=20_000.0,
        leverage=4.0,
        maintenance_ratio=0.005,
        fee_rate=0.0004,
        slippage_bps=2.0,
        use_funding=True,
        report_level=report_level,
        audit_sink="memory" if report_level == "audit" else "none",
        reactive_execution_mode="audit" if report_level == "audit" else "fast",
        reactive_kernel_mode="single_pass",
        reactive_runtime=reactive_runtime,
        reactive_gil_policy=reactive_gil_policy,
        native_backend=native_backend,
        execution_contract="event_lifecycle_v3_next_open",
    )


def _run_once(
    *,
    frame: pd.DataFrame,
    native_backend: str,
    reactive_runtime: str,
    gil_policy: str,
    every: int | None,
    hold: int,
    report_level: str,
):
    strategy = NumericEveryBarFixture(every=every, hold=hold)
    result = _endpoint(
        native_backend=native_backend,
        reactive_runtime=reactive_runtime,
        reactive_gil_policy=gil_policy,
        report_level=report_level,
    ).simulate(data=frame, strategy=strategy, symbols=["BTC"])
    return result, strategy


def _expected_command_rows(*, bars: int, every: int | None, hold: int) -> int:
    """Count the fixture's emitted writer rows, including reduce-only exits."""

    if every is None:
        return 0
    return sum(
        int(bar % every == 0) + int(bar % every == hold)
        for bar in range(bars)
    )


def _assert_exact(left, right) -> None:
    for name in ("equity", "positions", "fees", "funding"):
        np.testing.assert_allclose(
            getattr(left, name).to_numpy(),
            getattr(right, name).to_numpy(),
            rtol=0.0,
            atol=1e-12,
        )
    assert left.liquidated is right.liquidated
    assert compare_canonical_traces(
        left.metadata["canonical_trace_v1"],
        right.metadata["canonical_trace_v1"],
    )["passed"]


def _four_way_preflight(frame: pd.DataFrame) -> None:
    """Fail before timing if R0/R1 execution or callback semantics diverge."""

    kwargs = {"frame": frame, "every": 19, "hold": 3, "report_level": "audit"}
    python, python_strategy = _run_once(
        native_backend="python",
        reactive_runtime="legacy_python_loop",
        gil_policy="held_for_session",
        **kwargs,
    )
    bridge, bridge_strategy = _run_once(
        native_backend="rust",
        reactive_runtime="legacy_python_loop",
        gil_policy="held_for_session",
        **kwargs,
    )
    held, held_strategy = _run_once(
        native_backend="rust",
        reactive_runtime="numeric_every_bar_v1",
        gil_policy="held_for_session",
        **kwargs,
    )
    released, released_strategy = _run_once(
        native_backend="rust",
        reactive_runtime="numeric_every_bar_v1",
        gil_policy="release_between_callbacks",
        **kwargs,
    )
    for candidate in (bridge, held, released):
        _assert_exact(python, candidate)
    expected_state = python_strategy.quantbt_state_fingerprint()
    assert expected_state == bridge_strategy.quantbt_state_fingerprint()
    assert expected_state == held_strategy.quantbt_state_fingerprint()
    assert expected_state == released_strategy.quantbt_state_fingerprint()
    assert held.metadata["reactive_numeric_observability"]["native_entry_calls"] == 1
    assert held.metadata["reactive_numeric_observability"]["python_callback_calls"] == len(frame)


def _measure(call: Callable[[], Any], *, repeats: int) -> tuple[dict[str, float | int], Any]:
    """Warm once, then measure median public end-to-end runtime and RSS plateau."""

    warm = call()
    del warm
    gc.collect()
    before = _rss_bytes()
    samples: list[float] = []
    result = None
    for _ in range(repeats):
        started = perf_counter()
        result = call()
        samples.append(perf_counter() - started)
    after = _rss_bytes()
    return (
        {
            "median_seconds": float(median(samples)),
            "p95_seconds": float(np.quantile(np.asarray(samples), 0.95)),
            "rss_before_bytes": int(before),
            "rss_after_bytes": int(after),
            "rss_delta_bytes": int(max(0, after - before)),
        },
        result,
    )


def _summary(stats: dict[str, float | int], *, bars: int, sessions: int = 1) -> dict[str, float | int]:
    result = dict(stats)
    seconds = float(result["median_seconds"])
    result["median_milliseconds"] = seconds * 1_000.0
    result["bars_per_second"] = (float(bars * sessions) / seconds) if seconds else 0.0
    result["sessions"] = int(sessions)
    return result


def _concurrent_call(
    *,
    frame: pd.DataFrame,
    gil_policy: str,
    every: int,
    sessions: int,
) -> list[object]:
    def run_one(_: int):
        return _run_once(
            frame=frame,
            native_backend="rust",
            reactive_runtime="numeric_every_bar_v1",
            gil_policy=gil_policy,
            every=every,
            hold=1,
            report_level="minimal",
        )[0]

    with ThreadPoolExecutor(max_workers=sessions) as executor:
        return list(executor.map(run_one, range(sessions)))


def run(*, bars: int, repeats: int, concurrent_sessions: int) -> dict[str, Any]:
    if bars < 2_000:
        raise ValueError("Phase 62 benchmark requires bars >= 2000")
    if repeats <= 0:
        raise ValueError("repeats must be > 0")
    if concurrent_sessions < 2:
        raise ValueError("concurrent_sessions must be >= 2")

    frame = _frame(bars)
    _four_way_preflight(_frame(min(512, bars)))

    routes = (
        ("python_r0", "python", "legacy_python_loop", "held_for_session"),
        ("rust_bridge_r0", "rust", "legacy_python_loop", "held_for_session"),
        ("rust_r1_held", "rust", "numeric_every_bar_v1", "held_for_session"),
        ("rust_r1_release", "rust", "numeric_every_bar_v1", "release_between_callbacks"),
    )
    workloads = (
        ("lightweight", None, 1),
        ("low_churn", 1_000, 3),
        ("high_churn", 20, 1),
    )
    rows: list[dict[str, Any]] = []
    terminal: dict[tuple[str, str], tuple[float, float]] = {}
    for workload, every, hold in workloads:
        for route, native_backend, reactive_runtime, gil_policy in routes:
            stats, result_and_strategy = _measure(
                lambda: _run_once(
                    frame=frame,
                    native_backend=native_backend,
                    reactive_runtime=reactive_runtime,
                    gil_policy=gil_policy,
                    every=every,
                    hold=hold,
                    report_level="minimal",
                ),
                repeats=repeats,
            )
            result, strategy = result_and_strategy
            terminal[(workload, route)] = (
                float(result.equity.iloc[-1]),
                float(result.positions.iloc[-1, 0]),
            )
            row = _summary(stats, bars=bars)
            row.update(
                {
                    "workload": workload,
                    "route": route,
                    "native_backend": native_backend,
                    "reactive_runtime": reactive_runtime,
                    "gil_policy": gil_policy,
                    "command_rows_expected": _expected_command_rows(
                        bars=bars,
                        every=every,
                        hold=hold,
                    ),
                    "final_equity": float(result.equity.iloc[-1]),
                    "final_position": float(result.positions.iloc[-1, 0]),
                    "callback_count": int(strategy.callback_count),
                    "runtime_class": result.metadata.get("reactive_numeric_observability", {}).get("runtime_class"),
                }
            )
            rows.append(row)
            # The RSS sample above intentionally includes one public result
            # after a warm run. Do not retain it into the next route, or the
            # following route would inherit unrelated DataFrame/path memory.
            del result, strategy, result_and_strategy
            gc.collect()
            row["rss_released_delta_bytes"] = int(
                max(0, _rss_bytes() - int(stats["rss_before_bytes"]))
            )

    for workload, _every, _hold in workloads:
        reference = terminal[(workload, "python_r0")]
        for route in ("rust_bridge_r0", "rust_r1_held", "rust_r1_release"):
            candidate = terminal[(workload, route)]
            np.testing.assert_allclose(reference, candidate, rtol=0.0, atol=1e-12)

    concurrent_rows: list[dict[str, Any]] = []
    for gil_policy in ("held_for_session", "release_between_callbacks"):
        stats, results = _measure(
            lambda: _concurrent_call(
                frame=frame,
                gil_policy=gil_policy,
                every=20,
                sessions=concurrent_sessions,
            ),
            repeats=repeats,
        )
        assert len(results) == concurrent_sessions
        final_equities = [float(result.equity.iloc[-1]) for result in results]
        np.testing.assert_allclose(final_equities, final_equities[0], rtol=0.0, atol=1e-12)
        row = _summary(stats, bars=bars, sessions=concurrent_sessions)
        row.update(
            {
                "workload": "high_churn_concurrent",
                "route": f"rust_r1_{'held' if gil_policy == 'held_for_session' else 'release'}",
                "native_backend": "rust",
                "reactive_runtime": "numeric_every_bar_v1",
                "gil_policy": gil_policy,
                "final_equity": final_equities[0],
            }
        )
        concurrent_rows.append(row)
        del results
        gc.collect()
        row["rss_released_delta_bytes"] = int(
            max(0, _rss_bytes() - int(stats["rss_before_bytes"]))
        )

    by_key = {(row["workload"], row["route"]): row for row in rows}
    gates = {
        "four_way_preflight": True,
        "r1_exact_to_python_for_all_workloads": True,
        "one_native_entry": all(
            row["runtime_class"] == "rust_primary_python_callback"
            for row in rows
            if row["route"].startswith("rust_r1")
        ),
        # R1 is explicit in Phase 62 whatever these timings show. This gate
        # records measured promotion eligibility rather than silently changing
        # route policy.
        "r1_not_slower_than_python_low_churn": (
            float(by_key[("low_churn", "rust_r1_held")]["median_seconds"])
            <= float(by_key[("low_churn", "python_r0")]["median_seconds"])
        ),
    }
    return {
        "phase": "62",
        "workload_contract": "reactive_numeric_every_bar_r1_public_end_to_end",
        "bars": int(bars),
        "repeats": int(repeats),
        "concurrent_sessions": int(concurrent_sessions),
        "parity": {
            "python_r0_rust_bridge_r0_rust_r1_held_rust_r1_release": True,
            "execution_contract": "event_lifecycle_v3_next_open",
            "python_callback_per_bar": True,
        },
        "sequential": rows,
        "concurrent": concurrent_rows,
        "gates": gates,
        "route_policy": {
            "r1_auto_promoted": False,
            "reason": "Phase 62 R1 remains an explicit hybrid route; Phase 63 sparse/block certification is separate.",
        },
    }


def _markdown(evidence: dict[str, Any]) -> str:
    lines = [
        "# Phase 62 Reactive Numeric Co-runtime Evidence",
        "",
        "Python/R0 bridge/R1 held/R1 release four-way parity passes before timing. Numbers include Python strategy callbacks and public result adaptation; they are not comparable to static command-tape kernel figures.",
        "",
        "## Sequential",
        "",
        "| Workload | Route | Bars | Median | Throughput | RSS retained / released |",
        "|---|---|---:|---:|---:|---:|",
    ]
    for row in evidence["sequential"]:
        lines.append(
            f"| {row['workload']} | {row['route']} | {evidence['bars']:,} | "
            f"{row['median_seconds']:.6f}s | {row['bars_per_second']:,.0f} bars/s | "
            f"{row['rss_delta_bytes'] / (1024 * 1024):.2f} / "
            f"{row['rss_released_delta_bytes'] / (1024 * 1024):.2f} MiB |"
        )
    lines.extend(
        (
            "",
            "## Concurrent R1 high-churn",
            "",
            "| Route | Sessions | Aggregate bars | Median | Aggregate throughput | RSS retained / released |",
            "|---|---:|---:|---:|---:|---:|",
        )
    )
    for row in evidence["concurrent"]:
        lines.append(
            f"| {row['route']} | {row['sessions']} | {evidence['bars'] * row['sessions']:,} | "
            f"{row['median_seconds']:.6f}s | {row['bars_per_second']:,.0f} bars/s | "
            f"{row['rss_delta_bytes'] / (1024 * 1024):.2f} / "
            f"{row['rss_released_delta_bytes'] / (1024 * 1024):.2f} MiB |"
        )
    eligible = evidence["gates"]["r1_not_slower_than_python_low_churn"]
    lines.extend(
        (
            "",
            f"Low-churn held-GIL performance eligibility: `{eligible}`.",
            "R1 remains explicit in Phase 62 regardless of this result: it is a Rust-led/Python-callback hybrid, and sparse/block routing is a later capability.",
        )
    )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bars", type=int, default=10_000)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--concurrent-sessions", type=int, default=2)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    evidence = run(
        bars=args.bars,
        repeats=args.repeats,
        concurrent_sessions=args.concurrent_sessions,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    args.output.with_suffix(".md").write_text(_markdown(evidence), encoding="utf-8")
    print(json.dumps(evidence, indent=2, sort_keys=True))
    # Exact parity is mandatory. Speed is recorded truthfully, but cannot
    # trigger automatic route promotion at the R1 capability level.
    return 0 if evidence["gates"]["four_way_preflight"] and evidence["gates"]["r1_exact_to_python_for_all_workloads"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
