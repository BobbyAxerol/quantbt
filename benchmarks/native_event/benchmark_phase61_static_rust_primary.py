"""Phase 61 static-event Rust-primary performance and RSS evidence.

This benchmark uses the promoted 10,000-bar explicit-command workload.  It
reports immutable preparation, direct typed-kernel, cold report adaptation, and
the real public optimize facade independently.  Python remains the accounting
oracle/comparator; API 0.4 compatibility is deliberately excluded from the
promotion comparison because it is an explicit rollback path, not a candidate
for automatic routing.
"""

from __future__ import annotations

import argparse
import gc
import json
import os
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
    OrderCommand,
    OrderSide,
    OrderType,
    QuantBTEndpoint,
)
from quantbt.backends._native_event_rust import RustFullAuditResult
from quantbt.core.native_event_parity import assert_native_event_full_parity


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = ROOT / "benchmarks/native_event/results/phase61_static_rust_primary.json"


def _rss_bytes() -> int:
    """Return current Linux RSS rather than a process-lifetime high watermark."""

    status = Path("/proc/self/status")
    if status.exists():
        for line in status.read_text(encoding="utf-8").splitlines():
            if line.startswith("VmRSS:"):
                return int(line.split()[1]) * 1024
    return 0


def _frame(bars: int) -> pd.DataFrame:
    index = pd.date_range("2026-03-01", periods=bars, freq="1h", tz="UTC")
    phase = np.arange(bars, dtype=np.float64)
    close = 100.0 + 0.015 * phase + 1.5 * np.sin(phase / 29.0)
    open_ = np.r_[close[0], close[:-1]] + 0.03 * np.cos(phase / 7.0)
    return pd.DataFrame(
        {
            "open": open_,
            "high": np.maximum(open_, close) + 1.0,
            "low": np.minimum(open_, close) - 1.0,
            "close": close,
            "volume": 1_000.0,
            "funding_rate": np.where(phase % 24 == 0, 0.0001, 0.0),
        },
        index=index,
    )


def _commands(index: pd.DatetimeIndex) -> tuple[OrderCommand, ...]:
    bars = len(index)
    points = np.linspace(1, bars - 2, num=24, dtype=np.int64)
    commands: list[OrderCommand] = []
    for ordinal, bar in enumerate(points):
        commands.append(
            OrderCommand(
                timestamp=index[int(bar)],
                symbol="BTC",
                side=OrderSide.BUY if ordinal % 2 == 0 else OrderSide.SELL,
                order_type=OrderType.MARKET,
                qty=0.25,
                order_id=f"phase61-{ordinal}",
            )
        )
    return tuple(commands)


def _backend(*, native_backend: str) -> NativeEventBackend:
    return NativeEventBackend(
        NativeEventConfig(
            account=AccountConfig(initial_capital=20_000.0, leverage=5.0, maintenance_ratio=0.005),
            execution=ExecutionConfig(slippage_bps=2.0),
            fee_rate=0.0002,
            use_funding=True,
            native_backend=native_backend,
            execution_contract="event_lifecycle_v3_next_open",
            native_static_abi="0.5",
            report_level="score",
        )
    )


def _prepare_rust(frame: pd.DataFrame, commands: tuple[OrderCommand, ...]):
    backend = _backend(native_backend="rust")
    runner = backend.prepare_rust_batched_runner(
        frame.index,
        closes={"BTC": frame["close"]},
        highs={"BTC": frame["high"]},
        lows={"BTC": frame["low"]},
        opens={"BTC": frame["open"]},
        funding_rate={"BTC": frame["funding_rate"]},
        symbols=["BTC"],
        contract_size=1.0,
    )
    compiled = backend.compile_order_commands(frame.index, commands, symbols=["BTC"])
    return backend, runner, compiled


def _measure(call: Callable[[], Any], *, repeats: int) -> tuple[dict[str, float | int], Any]:
    """Warm one call, then report median wall time and RSS delta."""

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


def _summary(stats: dict[str, float | int], *, bars: int) -> dict[str, float | int]:
    result = dict(stats)
    seconds = float(result["median_seconds"])
    result["median_milliseconds"] = seconds * 1_000.0
    result["bars_per_second"] = float(bars) / seconds if seconds else 0.0
    return result


def _public_endpoint(*, backend: str) -> QuantBTEndpoint:
    return QuantBTEndpoint.event_driven(
        input_mode="orders",
        backend=backend,
        profile="optimize",
        execution_contract="event_lifecycle_v3_next_open",
        initial_capital=20_000.0,
        leverage=5.0,
        fee_rate=0.0002,
        slippage_bps=2.0,
        use_funding=True,
        native_static_abi="0.5",
    )


def run(*, bars: int, repeats: int) -> dict[str, Any]:
    if bars < 10_000:
        raise ValueError("Phase 61 public promotion benchmark requires bars >= 10000")
    if repeats <= 0:
        raise ValueError("repeats must be > 0")
    frame = _frame(bars)
    commands = _commands(frame.index)

    prepare_stats, prepared = _measure(lambda: _prepare_rust(frame, commands), repeats=repeats)
    _prepared_backend, runner, compiled = prepared
    try:
        typed_score_stats, score = _measure(
            lambda: runner.run_tape_typed(compiled, profile="score"), repeats=repeats
        )
        if hasattr(score, "equity") or hasattr(score, "fill_bar"):
            raise AssertionError("typed score retained compact or audit arrays")
        typed_compact = runner.run_tape_typed(compiled, profile="compact")
        adapter_stats, adapted = _measure(
            lambda: RustFullAuditResult.from_compact_payload(
                typed_compact,
                n_bars=bars,
                n_symbols=1,
                id_values=tuple(compiled.id_values),
            ).to_backtest_result(
                datetime_index=frame.index,
                closes=np.ascontiguousarray(frame[["close"]].to_numpy(dtype=np.float64)),
                symbols=["BTC"],
                initial_capital=20_000.0,
                leverage=5.0,
                include_audit_reports=False,
            ),
            repeats=repeats,
        )
        assert len(adapted.equity) == bars
        counters = dict(runner.cache_info())
    finally:
        runner.clear_caches()

    # This is the promoted A4 score capability: market and command tape have
    # already been prepared, so both backends execute the exact same immutable
    # input without report/frame construction in the timed region.
    prepared_python_backend = _backend(native_backend="python")
    prepared_python_market = prepared_python_backend.prepare_market_arrays(
        frame.index,
        closes={"BTC": frame["close"]},
        highs={"BTC": frame["high"]},
        lows={"BTC": frame["low"]},
        funding_rate={"BTC": frame["funding_rate"]},
        symbols=["BTC"],
    )
    prepared_rust_score_stats, prepared_rust_score = _measure(
        lambda: _prepared_backend.run_compiled_tape_score(
            frame.index,
            compiled,
            market_arrays=runner.market_arrays,
            opens={"BTC": frame["open"]},
        ),
        repeats=repeats,
    )
    prepared_python_score_stats, prepared_python_score = _measure(
        lambda: prepared_python_backend.run_compiled_tape_score(
            frame.index,
            compiled,
            market_arrays=prepared_python_market,
            opens={"BTC": frame["open"]},
        ),
        repeats=repeats,
    )
    np.testing.assert_allclose(
        prepared_rust_score.final_equity,
        prepared_python_score.final_equity,
        rtol=0.0,
        atol=1e-12,
    )
    np.testing.assert_allclose(
        prepared_rust_score.final_positions,
        prepared_python_score.final_positions,
        rtol=0.0,
        atol=1e-12,
    )
    assert prepared_rust_score.metadata["native_static_abi"] == "0.5"
    assert prepared_rust_score.metadata["native_static_execution_boundary_calls"] == 1
    assert prepared_rust_score.metadata["rust_audit_replay"] is False

    rust_endpoint = _public_endpoint(backend="rust")
    python_endpoint = _public_endpoint(backend="python")
    public_rust_stats, public_rust = _measure(
        lambda: rust_endpoint.simulate(data=frame, order_commands=commands, symbols=["BTC"]),
        repeats=repeats,
    )
    public_python_stats, public_python = _measure(
        lambda: python_endpoint.simulate(data=frame, order_commands=commands, symbols=["BTC"]),
        repeats=repeats,
    )
    assert_native_event_full_parity(public_rust, public_python, require_full=False)
    if public_rust.metadata["native_static_abi_resolved"] != "0.5":
        raise AssertionError("public benchmark did not use the typed ABI 0.5 route")
    if public_rust.metadata["rust_audit_replay"]:
        raise AssertionError("public compact route replayed audit execution")

    rust_public = _summary(public_rust_stats, bars=bars)
    python_public = _summary(public_python_stats, bars=bars)
    typed_score = _summary(typed_score_stats, bars=bars)
    prepared_rust = _summary(prepared_rust_score_stats, bars=bars)
    prepared_python = _summary(prepared_python_score_stats, bars=bars)
    prepared_rust_faster = float(prepared_rust["median_seconds"]) < float(prepared_python["median_seconds"])
    plateau_limit = max(8 * 1024 * 1024, int(_rss_bytes() * 0.10))
    return {
        "phase": "61",
        "workload": "static_command_tape_v2_v3_promoted_score",
        "bars": bars,
        "commands": len(commands),
        "repeats": repeats,
        "parity": {
            "python_rust_public": True,
            "contract": "event_lifecycle_v3_next_open",
            "rust_audit_replay": False,
        },
        "prepare": _summary(prepare_stats, bars=bars),
        "typed_kernel_score": typed_score,
        "cold_compact_adaptation": _summary(adapter_stats, bars=bars),
        "prepared_static_score": {
            "rust_abi_05": prepared_rust,
            "python_oracle": prepared_python,
            "rust_vs_python_speedup": (
                float(prepared_python["median_seconds"]) / float(prepared_rust["median_seconds"])
            ),
            "native_static_execution_boundary_calls": 1,
            "audit_replay": False,
        },
        "public_optimize": {
            "rust_abi_05": rust_public,
            "python_oracle": python_public,
            "rust_vs_python_speedup": (
                float(python_public["median_seconds"]) / float(rust_public["median_seconds"])
            ),
        },
        "prepared_counters": counters,
        "rss": {
            "current_bytes": _rss_bytes(),
            "plateau_limit_bytes": plateau_limit,
            "typed_score_delta_bytes": int(typed_score_stats["rss_delta_bytes"]),
            "prepared_rust_score_delta_bytes": int(prepared_rust_score_stats["rss_delta_bytes"]),
            "prepared_python_score_delta_bytes": int(prepared_python_score_stats["rss_delta_bytes"]),
            "public_rust_delta_bytes": int(public_rust_stats["rss_delta_bytes"]),
            "public_python_delta_bytes": int(public_python_stats["rss_delta_bytes"]),
        },
        "gates": {
            "one_main_native_boundary": counters.get("typed_boundary_calls_total", 0) >= repeats + 2,
            "score_has_no_dense_output": not hasattr(score, "equity"),
            "prepared_rust_faster_than_python": prepared_rust_faster,
            "typed_prepared_reuse": counters.get("typed_request_entries", 0) >= 2,
        },
    }


def _markdown(evidence: dict[str, Any]) -> str:
    public = evidence["public_optimize"]
    prepared = evidence["prepared_static_score"]
    rust = public["rust_abi_05"]
    python = public["python_oracle"]
    prepared_rust = prepared["rust_abi_05"]
    prepared_python = prepared["python_oracle"]
    score = evidence["typed_kernel_score"]
    adapt = evidence["cold_compact_adaptation"]
    return "\n".join(
        (
            "# Phase 61 Static Event Rust-Primary Evidence",
            "",
            "Exact public Python/Rust accounting parity passed before timing.",
            "",
            "| Scope | Bars | Median | Throughput | RSS delta |",
            "|---|---:|---:|---:|---:|",
            f"| Typed Rust score kernel | {evidence['bars']:,} | {score['median_seconds']:.6f}s | {score['bars_per_second']:,.0f} bars/s | {score['rss_delta_bytes'] / (1024 * 1024):.2f} MiB |",
            f"| Cold compact adaptation | {evidence['bars']:,} | {adapt['median_seconds']:.6f}s | {adapt['bars_per_second']:,.0f} bars/s | {adapt['rss_delta_bytes'] / (1024 * 1024):.2f} MiB |",
            f"| Prepared static score Rust ABI 0.5 | {evidence['bars']:,} | {prepared_rust['median_seconds']:.6f}s | {prepared_rust['bars_per_second']:,.0f} bars/s | {prepared_rust['rss_delta_bytes'] / (1024 * 1024):.2f} MiB |",
            f"| Prepared static score Python oracle | {evidence['bars']:,} | {prepared_python['median_seconds']:.6f}s | {prepared_python['bars_per_second']:,.0f} bars/s | {prepared_python['rss_delta_bytes'] / (1024 * 1024):.2f} MiB |",
            f"| Public optimize Rust ABI 0.5 | {evidence['bars']:,} | {rust['median_seconds']:.6f}s | {rust['bars_per_second']:,.0f} bars/s | {rust['rss_delta_bytes'] / (1024 * 1024):.2f} MiB |",
            f"| Public optimize Python oracle | {evidence['bars']:,} | {python['median_seconds']:.6f}s | {python['bars_per_second']:,.0f} bars/s | {python['rss_delta_bytes'] / (1024 * 1024):.2f} MiB |",
            "",
            f"Prepared Rust/Python score speedup: `{prepared['rust_vs_python_speedup']:.2f}x`.",
            f"Public facade Rust/Python ratio: `{public['rust_vs_python_speedup']:.2f}x` (informational; it includes pandas/result adaptation).",
            "A4 promotion gate uses the prepared score contract. Static command execution crosses Python-to-Rust once per run; metrics, report frames, and audit output are cold-path adaptation only.",
        )
    ) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bars", type=int, default=10_000)
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    evidence = run(bars=args.bars, repeats=args.repeats)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    args.output.with_suffix(".md").write_text(_markdown(evidence), encoding="utf-8")
    print(json.dumps(evidence, indent=2, sort_keys=True))
    return 0 if all(evidence["gates"].values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
