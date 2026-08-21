"""Phase 54B.2 public Rust-first Stage-B benchmark.

The benchmark intentionally measures only routes that the generated promotion
table may select automatically:

* E0 static V2/V3 command tapes at the 10,000-bar threshold;
* E3 bounded Native Strategy IR at the 2,000-bar threshold; and
* E6 shared-market native IR batch/fold scoring.

It performs one exact Python/Rust audit parity check before timing.  The Rust
score path and the cold ``BacktestResultV2`` adaptation are timed separately
for Native IR; public static timing is reported as a facade-inclusive result.
No callback, reactive, portfolio, or package route is benchmarked or promoted
by this script.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import resource
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
    NativeIRFold,
    NativeStrategyIR,
    NativeStrategyKind,
    NativeStrategyParameters,
    OrderCommand,
    OrderSide,
    OrderType,
    QuantBTEndpoint,
)
from quantbt.backends._native_event_rust import probe_native_event_rust_extension
from quantbt.core.native_event_parity import assert_native_event_full_parity


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = ROOT / "benchmarks/native_event/results/phase54b2/public_routes.json"


def _current_rss_bytes() -> int:
    """Return Linux current RSS without confusing it with the process peak."""

    status = Path("/proc/self/status")
    if status.exists():
        for line in status.read_text(encoding="utf-8").splitlines():
            if line.startswith("VmRSS:"):
                return int(line.split()[1]) * 1024
    return int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss) * 1024


def _peak_rss_bytes() -> int:
    return int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss) * 1024


def _measure(call: Callable[[], Any], *, repeats: int) -> tuple[dict[str, float | int], Any]:
    """Warm ``call`` and return median wall time plus current/peak RSS."""

    call()
    samples: list[float] = []
    rss_before = _current_rss_bytes()
    result: Any = None
    for _ in range(repeats):
        started = perf_counter()
        result = call()
        samples.append(perf_counter() - started)
    rss_after = _current_rss_bytes()
    value = float(median(samples))
    return (
        {
            "median_seconds": value,
            "p95_seconds": float(np.quantile(np.asarray(samples), 0.95)),
            "rss_before_bytes": int(rss_before),
            "rss_after_bytes": int(rss_after),
            "rss_delta_bytes": int(max(0, rss_after - rss_before)),
            "rss_peak_process_bytes": int(_peak_rss_bytes()),
        },
        result,
    )


def _frame(bars: int) -> pd.DataFrame:
    index = pd.date_range("2026-01-01", periods=bars, freq="1h", tz="UTC")
    phase = np.arange(bars, dtype=np.float64)
    close = 100.0 + 0.012 * phase + 1.5 * np.sin(phase / 31.0)
    open_ = np.r_[close[0], close[:-1]] + 0.05 * np.cos(phase / 11.0)
    return pd.DataFrame(
        {
            "open": open_,
            "high": np.maximum(open_, close) + 1.25,
            "low": np.minimum(open_, close) - 1.25,
            "close": close,
            "volume": 1_000.0,
        },
        index=index,
    )


def _static_commands(index: pd.DatetimeIndex) -> tuple[OrderCommand, ...]:
    """Build a bounded V3 tape with lifecycle transitions and no randomness."""

    bars = len(index)
    points = np.linspace(1, bars - 2, num=12, dtype=np.int64)
    commands: list[OrderCommand] = []
    for ordinal, bar in enumerate(points):
        side = OrderSide.BUY if ordinal % 2 == 0 else OrderSide.SELL
        commands.append(
            OrderCommand(
                timestamp=index[int(bar)],
                symbol="BTC",
                side=side,
                order_type=OrderType.MARKET,
                qty=0.25,
                order_id=f"stage-b-{ordinal}",
            )
        )
    return tuple(commands)


def _static_endpoint(*, native_backend: str, profile: str = "audit"):
    return QuantBTEndpoint.event_driven(
        input_mode="orders",
        profile=profile,
        backend=native_backend,
        execution_contract="event_lifecycle_v3_next_open",
        initial_capital=20_000.0,
        leverage=5.0,
        fee_rate=0.0002,
        slippage_bps=2.0,
        use_funding=False,
    )


def _ir_backend(*, native_backend: str) -> NativeEventBackend:
    return NativeEventBackend(
        NativeEventConfig(
            account=AccountConfig(initial_capital=20_000.0, leverage=5.0, maintenance_ratio=0.005),
            execution=ExecutionConfig(slippage_bps=2.0),
            fee_rate=0.0002,
            use_funding=False,
            native_backend=native_backend,
            execution_contract="event_lifecycle_v3_next_open",
        )
    )


def _ir_runner(frame: pd.DataFrame, *, native_backend: str):
    backend = _ir_backend(native_backend=native_backend)
    program = NativeStrategyIR(
        NativeStrategyKind.GRID_LEVEL,
        "BTC",
        parameters=NativeStrategyParameters(quantity=0.25),
    )
    return backend.prepare_native_strategy_ir(
        frame.index,
        closes={"BTC": frame["close"]},
        highs={"BTC": frame["high"]},
        lows={"BTC": frame["low"]},
        opens={"BTC": frame["open"]},
        program=program,
        symbols=["BTC"],
    )


def _ms(seconds: float) -> float:
    return round(seconds * 1_000.0, 6)


def _route_summary(stats: dict[str, float | int], *, bars: int, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    value = dict(stats)
    value["median_milliseconds"] = _ms(float(value["median_seconds"]))
    value["bars_per_second"] = float(bars) / float(value["median_seconds"])
    if extra:
        value.update(extra)
    return value


def _assert_static_parity(frame: pd.DataFrame, commands: tuple[OrderCommand, ...]) -> dict[str, Any]:
    auto = _static_endpoint(native_backend="auto").simulate(
        data=frame, order_commands=commands, symbols=["BTC"]
    )
    rust = _static_endpoint(native_backend="rust").simulate(
        data=frame, order_commands=commands, symbols=["BTC"]
    )
    python = _static_endpoint(native_backend="python").simulate(
        data=frame, order_commands=commands, symbols=["BTC"]
    )
    assert_native_event_full_parity(auto, rust)
    assert_native_event_full_parity(auto, python)
    assert auto.metadata["execution_plan_v1"]["backend"] == "rust"
    return {
        "canonical_trace_fingerprint": auto.metadata["canonical_trace_fingerprint"],
        "auto_reason": auto.metadata["native_event_promotion_v1"]["reason"],
        "minimum_bars": auto.metadata["native_event_promotion_v1"]["minimum_bars"],
    }


def _assert_ir_parity(frame: pd.DataFrame, signal: np.ndarray, matrix: np.ndarray) -> dict[str, Any]:
    auto = _ir_runner(frame, native_backend="auto")
    rust = _ir_runner(frame, native_backend="rust")
    python = _ir_runner(frame, native_backend="python")
    auto_audit = auto.backtest(signal, report_level="audit")
    rust_audit = rust.backtest(signal, report_level="audit")
    python_audit = python.backtest(signal, report_level="audit")
    assert_native_event_full_parity(auto_audit, rust_audit)
    assert_native_event_full_parity(auto_audit, python_audit)
    auto_batch = auto.run_batch_score(matrix, workers=2, chunk_size=16)
    python_batch = python.run_batch_score(matrix, workers=1)
    np.testing.assert_allclose(auto_batch.final_equity, python_batch.final_equity, rtol=0.0, atol=1e-12)
    assert auto_batch.metadata["execution_plan_v1"]["backend"] == "rust"
    return {
        "canonical_trace_fingerprint": auto_audit.metadata["canonical_trace_fingerprint"],
        "auto_reason": auto_audit.metadata["native_event_promotion_v1"]["reason"],
        "minimum_bars": auto_audit.metadata["native_event_promotion_v1"]["minimum_bars"],
        "batch_boundary_calls": int(auto_batch.metadata["boundary_calls"]),
        "shared_market_copies_per_scenario": int(auto_batch.metadata["shared_market_copies_per_scenario"]),
    }


def run(*, static_bars: int, ir_bars: int, scenarios: int, repeats: int) -> dict[str, Any]:
    """Run the deterministic Stage-B benchmark and return JSON-safe evidence."""

    status = probe_native_event_rust_extension()
    if not status.executable:
        raise RuntimeError(f"quantbt-native executable extension is required: {status.reason}")
    if static_bars < 10_000 or ir_bars < 2_000:
        raise ValueError("Stage-B public benchmark requires static_bars >= 10000 and ir_bars >= 2000")

    static_frame = _frame(static_bars)
    commands = _static_commands(static_frame.index)
    static_parity = _assert_static_parity(static_frame, commands)
    static_auto = _static_endpoint(native_backend="auto")
    static_python = _static_endpoint(native_backend="python")
    auto_static_stats, auto_static_result = _measure(
        lambda: static_auto.simulate(data=static_frame, order_commands=commands, symbols=["BTC"]), repeats=repeats
    )
    python_static_stats, _ = _measure(
        lambda: static_python.simulate(data=static_frame, order_commands=commands, symbols=["BTC"]), repeats=repeats
    )
    assert auto_static_result.metadata["execution_plan_v1"]["backend"] == "rust"
    static_auto_compact = _static_endpoint(native_backend="auto", profile="optimize")
    static_python_compact = _static_endpoint(native_backend="python", profile="optimize")
    auto_static_compact_stats, auto_static_compact_result = _measure(
        lambda: static_auto_compact.simulate(data=static_frame, order_commands=commands, symbols=["BTC"]),
        repeats=repeats,
    )
    python_static_compact_stats, _ = _measure(
        lambda: static_python_compact.simulate(data=static_frame, order_commands=commands, symbols=["BTC"]),
        repeats=repeats,
    )
    assert auto_static_compact_result.metadata["execution_plan_v1"]["backend"] == "rust"

    ir_frame = _frame(ir_bars)
    phase = np.arange(ir_bars, dtype=np.float64)
    signal = np.where(phase % 120 < 40, 1.0, np.where(phase % 120 < 80, 2.0, 0.0)).astype(np.float64)
    signals = np.vstack([np.roll(signal, shift) for shift in range(scenarios)]).astype(np.float64)
    ir_parity = _assert_ir_parity(ir_frame, signal, signals)
    ir_auto = _ir_runner(ir_frame, native_backend="auto")
    ir_python = _ir_runner(ir_frame, native_backend="python")
    ir_score_stats, _ = _measure(lambda: ir_auto.run_score(signal), repeats=repeats)
    ir_python_score_stats, _ = _measure(lambda: ir_python.run_score(signal), repeats=repeats)
    ir_audit_output = ir_auto.run_audit(signal)
    ir_cold_adapt_stats, _ = _measure(
        lambda: ir_auto._ensure_rust_runner().to_backtest_result(ir_audit_output, signal),  # noqa: SLF001
        repeats=repeats,
    )
    ir_audit_stats, _ = _measure(lambda: ir_auto.backtest(signal, report_level="audit"), repeats=repeats)
    ir_batch_stats, batch_result = _measure(
        lambda: ir_auto.run_batch_score(signals, workers=2, chunk_size=16), repeats=repeats
    )
    fold = NativeIRFold(
        fold_id=0,
        warmup_start=0,
        train_start=0,
        train_end=ir_bars // 2,
        test_start=ir_bars // 2,
        test_end=ir_bars,
    )
    ir_fold_stats, fold_result = _measure(
        lambda: ir_auto.run_fold_batch_score(signals, fold, workers=2, chunk_size=16), repeats=repeats
    )
    assert batch_result.metadata["boundary_calls"] == 1
    assert fold_result.metadata["boundary_calls"] == 1

    return {
        "phase": "54B.2",
        "status": "pass",
        "host_evidence": {
            "extension_version": status.version,
            "extension_api": status.api_version,
            "product_registry_fingerprint": status.product_descriptor.get("product_registry_fingerprint"),
            "platform_scope": "local Linux CPython staged extension",
        },
        "policy": {
            "static_minimum_bars": 10_000,
            "native_ir_minimum_bars": 2_000,
            "promoted_workloads": ["E0 static command tape", "E3 Native Strategy IR", "E6 IR batch/fold"],
            "non_promoted_workloads": ["Python callback", "reactive", "portfolio", "package/arbitrage"],
        },
        "parity": {"static": static_parity, "native_ir": ir_parity},
        "measurements": {
            "static_public_audit": {
                "bars": static_bars,
                "commands": len(commands),
                "auto_rust": _route_summary(
                    auto_static_stats,
                    bars=static_bars,
                    extra={"boundary_calls": 1, "python_callbacks": 0, "audit_replay": False},
                ),
                "python_oracle": _route_summary(python_static_stats, bars=static_bars),
            },
            "static_public_compact": {
                "bars": static_bars,
                "commands": len(commands),
                "auto_rust": _route_summary(
                    auto_static_compact_stats,
                    bars=static_bars,
                    extra={"boundary_calls": 1, "python_callbacks": 0, "audit_replay": False},
                ),
                "python_oracle": _route_summary(python_static_compact_stats, bars=static_bars),
            },
            "native_ir": {
                "bars": ir_bars,
                "score_auto_rust": _route_summary(
                    ir_score_stats,
                    bars=ir_bars,
                    extra={"boundary_calls": 1, "python_callbacks": 0, "audit_replay": False},
                ),
                "score_python_oracle": _route_summary(ir_python_score_stats, bars=ir_bars),
                "cold_audit_adaptation": _route_summary(
                    ir_cold_adapt_stats,
                    bars=ir_bars,
                    extra={"execution_replayed": False, "precomputed_typed_audit_output": True},
                ),
                "public_audit_auto_rust": _route_summary(
                    ir_audit_stats,
                    bars=ir_bars,
                    extra={"cold_report_adaptation_included": True, "audit_replay": False},
                ),
            },
            "native_ir_batch": {
                "bars_per_scenario": ir_bars,
                "scenarios": scenarios,
                "auto_rust": _route_summary(
                    ir_batch_stats,
                    bars=ir_bars * scenarios,
                    extra={"boundary_calls": 1, "shared_market_copies_per_scenario": 0, "workers": 2},
                ),
                "fold_auto_rust": _route_summary(
                    ir_fold_stats,
                    bars=(ir_bars // 2) * scenarios,
                    extra={"boundary_calls": 1, "fresh_state_per_scenario": True, "workers": 2},
                ),
            },
        },
    }


def _markdown(evidence: dict[str, Any]) -> str:
    measurements = evidence["measurements"]
    static = measurements["static_public_audit"]
    static_compact = measurements["static_public_compact"]
    ir = measurements["native_ir"]
    batch = measurements["native_ir_batch"]
    rows = [
        ("Static public audit", static["bars"], static["auto_rust"], static["python_oracle"]),
        ("Static public compact", static_compact["bars"], static_compact["auto_rust"], static_compact["python_oracle"]),
        ("Native IR score", ir["bars"], ir["score_auto_rust"], ir["score_python_oracle"]),
        ("Native IR cold audit adaptation", ir["bars"], ir["cold_audit_adaptation"], None),
        ("Native IR public audit", ir["bars"], ir["public_audit_auto_rust"], None),
        ("Native IR batch", batch["bars_per_scenario"] * batch["scenarios"], batch["auto_rust"], None),
        ("Native IR causal fold", (batch["bars_per_scenario"] // 2) * batch["scenarios"], batch["fold_auto_rust"], None),
    ]
    lines = [
        "# Phase 54B.2 Public Route Benchmark",
        "",
        "Local Stage-B evidence only. Exact Python/Rust audit parity passed before timing.",
        "",
        "| Workload | Bars | Rust median | Rust throughput | Python median | Python throughput | RSS peak |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for name, bars, rust, python in rows:
        python_seconds = "-" if python is None else f"{python['median_seconds']:.6f}s"
        python_rate = "-" if python is None else f"{python['bars_per_second']:,.0f} bars/s"
        lines.append(
            f"| {name} | {bars:,} | {rust['median_seconds']:.6f}s | "
            f"{rust['bars_per_second']:,.0f} bars/s | {python_seconds} | {python_rate} | "
            f"{rust['rss_peak_process_bytes'] / (1024 * 1024):.1f} MiB |"
        )
    lines.extend(
        [
            "",
            "Score is a typed scalar/compact path. Public audit includes cold Python result adaptation from Rust buffers; neither route replays Python execution.",
            "Callbacks, reactive strategies, portfolio, and package/arbitrage are excluded and remain Python compatibility routes.",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--static-bars", type=int, default=10_000)
    parser.add_argument("--ir-bars", type=int, default=2_000)
    parser.add_argument("--scenarios", type=int, default=64)
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    evidence = run(
        static_bars=args.static_bars,
        ir_bars=args.ir_bars,
        scenarios=args.scenarios,
        repeats=args.repeats,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    args.output.with_suffix(".md").write_text(_markdown(evidence), encoding="utf-8")
    print(json.dumps(evidence, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
