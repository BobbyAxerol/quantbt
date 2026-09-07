#!/usr/bin/env python3
"""Phase 77 matched Rust boundary and result-adapter performance evidence.

The benchmark separates three things that used to be conflated:

* native numeric execution;
* repeated immutable market/request preparation; and
* public ``BacktestResultV2`` construction.

It is deliberately limited to the two routes changed in Phase 77: direct
close-target execution and bounded single-symbol intrabar execution.  It does
not claim a generic callback, portfolio, package, or WFO promotion result.
"""

from __future__ import annotations

import argparse
import gc
import json
from pathlib import Path
from statistics import median
import sys
from time import perf_counter
from typing import Any, Callable

import numpy as np


ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOT = ROOT / "src"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from benchmarks.native_event.benchmark_phase66_rust_target_vectorized import run as run_target  # noqa: E402
from benchmarks.native_event.benchmark_phase69_rust_intrabar import _fixture  # noqa: E402
from quantbt import ExecutionContract, QuantBTEndpoint, prepare_market_tape  # noqa: E402
from quantbt.backends.native_intrabar_rust import (  # noqa: E402
    prepare_rust_intrabar_market,
    run_rust_intrabar_kernel,
)
from quantbt.core.intrabar_kernel import run_intrabar_kernel  # noqa: E402
from quantbt.core.schema import AccountConfig  # noqa: E402
from quantbt.preparation.native_execution import NativeExecutionPreparationCache  # noqa: E402
from tools.measurement_contract import (  # noqa: E402
    build_work_counters,
    capture_measurement_identity,
    typed_array_sha256,
)


DEFAULT_OUTPUT = ROOT / "benchmarks/native_event/results/phase77_native_performance_closure.json"


def _rss_mb() -> float:
    status = Path("/proc/self/status")
    if not status.is_file():
        return 0.0
    for line in status.read_text(encoding="utf-8").splitlines():
        if line.startswith("VmRSS:"):
            return float(line.split()[1]) / 1024.0
    return 0.0


def _timed(call: Callable[[], Any], repeats: int) -> tuple[dict[str, float], Any]:
    samples: list[float] = []
    result: Any = None
    for _ in range(repeats):
        started = perf_counter()
        result = call()
        samples.append(perf_counter() - started)
    ordered = sorted(samples)
    p95_index = min(len(ordered) - 1, max(0, int(np.ceil(len(ordered) * 0.95)) - 1))
    return {"median_seconds": float(median(samples)), "p95_seconds": float(ordered[p95_index])}, result


def _rate(bars: int, timing: dict[str, float]) -> float:
    return float(bars / timing["median_seconds"])


def _assert_kernel_parity(left, right) -> None:
    for field in (
        "equity",
        "position",
        "average_entry",
        "active_stop",
        "active_take_profit",
        "fees",
        "funding",
        "event_flags",
        "initial_margin",
        "maintenance_margin",
    ):
        np.testing.assert_allclose(
            getattr(left, field).to_numpy(),
            getattr(right, field).to_numpy(),
            rtol=0.0,
            atol=1.0e-9,
        )
    assert left.fills == right.fills
    assert left.fills_report.equals(right.fills_report)
    # The Numba oracle intentionally does not expose a Rust-native terminal
    # fingerprint. Compare that provenance only when both results are Rust
    # adapters; numerical paths and fill records above remain the cross-engine
    # correctness evidence.
    left_fingerprint = left.metadata.get("native_execution_terminal_fingerprint")
    right_fingerprint = right.metadata.get("native_execution_terminal_fingerprint")
    if left_fingerprint is not None and right_fingerprint is not None:
        assert left_fingerprint == right_fingerprint


def _assert_public_parity(left, right) -> None:
    for field in ("equity", "fees", "funding"):
        np.testing.assert_allclose(
            getattr(left, field).to_numpy(),
            getattr(right, field).to_numpy(),
            rtol=0.0,
            atol=1.0e-9,
        )
    np.testing.assert_allclose(left.positions.to_numpy(), right.positions.to_numpy(), rtol=0.0, atol=1.0e-9)
    left_fingerprint = left.metadata.get("native_execution_terminal_fingerprint")
    right_fingerprint = right.metadata.get("native_execution_terminal_fingerprint")
    if left_fingerprint is not None and right_fingerprint is not None:
        assert left_fingerprint == right_fingerprint


def _endpoint(frame, *, runtime: str):
    factory = {
        "numba": QuantBTEndpoint.intrabar_bracket,
        "rust": QuantBTEndpoint.intrabar_bracket_rust,
    }.get(runtime)
    if factory is None:
        raise ValueError("runtime must be 'numba' or 'rust'")
    return factory(
        initial_capital=20_000.0,
        leverage=3.0,
        maintenance_ratio=0.005,
        fee_rate=0.0005,
        slippage_bps=2.0,
        use_funding=True,
        funding_rate=frame["funding_rate"],
        execution_contract=ExecutionContract.intrabar_bracket(close_on_last_bar=True),
        report_level="standard",
    )


def _markdown(payload: dict[str, Any]) -> str:
    intrabar = payload["intrabar"]
    target = payload["target"]
    timings = intrabar["timings"]
    rates = intrabar["throughput_bars_per_second"]
    return "\n".join(
        (
            "# Phase 77 Rust Kernel And Result-Adapter Performance Closure",
            "",
            "This artifact measures matching 1-hour, single-symbol intrabar compact/standard",
            "results before and after prepared ownership. It keeps Numba as a path-bearing",
            "rollback comparator. The direct-target row is measured with the same one-symbol",
            "close-target fixture and is reported separately.",
            "",
            "| Route | Median | P95 | Throughput |",
            "|---|---:|---:|---:|",
            f"| Numba intrabar standard/path | {timings['numba_standard']['median_seconds'] * 1_000:.3f} ms | {timings['numba_standard']['p95_seconds'] * 1_000:.3f} ms | {rates['numba_standard']:,.0f} bars/s |",
            f"| Numba intrabar one-shot public endpoint | {timings['numba_one_shot_endpoint']['median_seconds'] * 1_000:.3f} ms | {timings['numba_one_shot_endpoint']['p95_seconds'] * 1_000:.3f} ms | {rates['numba_one_shot_endpoint']:,.0f} bars/s |",
            f"| Numba intrabar prepared public runner | {timings['numba_prepared_runner']['median_seconds'] * 1_000:.3f} ms | {timings['numba_prepared_runner']['p95_seconds'] * 1_000:.3f} ms | {rates['numba_prepared_runner']:,.0f} bars/s |",
            f"| Rust intrabar one-shot adapter | {timings['rust_one_shot_adapter']['median_seconds'] * 1_000:.3f} ms | {timings['rust_one_shot_adapter']['p95_seconds'] * 1_000:.3f} ms | {rates['rust_one_shot_adapter']:,.0f} bars/s |",
            f"| Rust intrabar prepared adapter | {timings['rust_prepared_adapter']['median_seconds'] * 1_000:.3f} ms | {timings['rust_prepared_adapter']['p95_seconds'] * 1_000:.3f} ms | {rates['rust_prepared_adapter']:,.0f} bars/s |",
            f"| Rust intrabar one-shot public endpoint | {timings['rust_one_shot_endpoint']['median_seconds'] * 1_000:.3f} ms | {timings['rust_one_shot_endpoint']['p95_seconds'] * 1_000:.3f} ms | {rates['rust_one_shot_endpoint']:,.0f} bars/s |",
            f"| Rust intrabar prepared public runner | {timings['rust_prepared_runner']['median_seconds'] * 1_000:.3f} ms | {timings['rust_prepared_runner']['p95_seconds'] * 1_000:.3f} ms | {rates['rust_prepared_runner']:,.0f} bars/s |",
            "",
            f"- Prepared adapter improvement over one-shot adapter: `{intrabar['ratios']['prepared_adapter_vs_one_shot_adapter']:.2f}x`.",
            f"- Prepared runner improvement over one-shot endpoint: `{intrabar['ratios']['prepared_runner_vs_one_shot_endpoint']:.2f}x`.",
            f"- Rust prepared runner / matching Numba prepared runner: `{intrabar['ratios']['rust_prepared_runner_vs_numba_prepared_runner']:.2f}x`.",
            f"- Exact terminal/path/fill parity: `{intrabar['evidence']['kernel_parity']}`; public parity: `{intrabar['evidence']['public_parity']}`.",
            f"- Prepared request cache policy: `{intrabar['evidence']['prepared_request_cache_policy']}`. Dynamic intent validation remains enabled.",
            f"- RSS start / prepared market / after warm: `{intrabar['rss_mb']['process_start']:.2f}` / `{intrabar['rss_mb']['after_prepared_market']:.2f}` / `{intrabar['rss_mb']['after_warm']:.2f}` MiB.",
            f"- Prepared-runner RSS change over `{intrabar['rss_mb']['steady_runs']}` additional runs: `{intrabar['rss_mb']['prepared_runner_steady_delta']:.3f}` MiB; final-half change: `{intrabar['rss_mb']['prepared_runner_final_half_delta']:.3f}` MiB. This is a same-process retention probe, not a cold-process peak claim.",
            "",
            "## Direct Target",
            "",
            f"- Rust prepared score: `{target['throughput_bars_per_second']['rust_prepared_score']:,.0f}` bars/s.",
            f"- Numba warmed kernel: `{target['throughput_bars_per_second']['numba_warmed_kernel']:,.0f}` bars/s.",
            f"- Rust public compact: `{target['throughput_bars_per_second']['rust_public_compact']:,.0f}` bars/s; Numba public compact: `{target['throughput_bars_per_second']['numba_public_compact']:,.0f}` bars/s.",
            f"- Exact accounting parity: `{target['evidence']['exact_accounting_parity']}`; no order arena: `{not target['evidence']['generic_order_arena_used']}`.",
            f"- Target RSS is governed by the standalone Phase 66 artifact; this embedded target run shares the intrabar process and does not claim an independent process baseline.",
            "",
            "The prepared intrabar route is an opt-in `prepare_intrabar(...).run(intent)`",
            "service/WFO surface. One-shot endpoints still validate and content-address the full",
            "market/request input. No automatic backend promotion is changed by this evidence.",
        )
    ) + "\n"


def run(*, bars: int, repeats: int) -> dict[str, Any]:
    if bars < 128:
        raise ValueError("bars must be >= 128")
    if repeats < 3:
        raise ValueError("repeats must be >= 3")

    gc.collect()
    frame, intent = _fixture(bars)
    tape = prepare_market_tape(
        data=frame,
        symbols=["BTCUSDT"],
        funding_rate=frame["funding_rate"],
        use_funding=True,
        bar_timestamp_semantics="close",
    )
    kwargs = {
        "tape": tape,
        "intent": intent,
        "account": AccountConfig(initial_capital=20_000.0, leverage=3.0, maintenance_ratio=0.005),
        "contract": ExecutionContract.intrabar_bracket(close_on_last_bar=True),
        "fee_rate": 0.0005,
        "slippage_rate": 0.0002,
        "report_level": "standard",
    }
    cache = NativeExecutionPreparationCache()
    rss_start = _rss_mb()
    prepared_market = prepare_rust_intrabar_market(tape=tape, native_preparation_cache=cache)
    rss_after_prepared_market = _rss_mb()

    one_shot_call = lambda: run_rust_intrabar_kernel(**kwargs, native_preparation_cache=cache)
    prepared_call = lambda: run_rust_intrabar_kernel(
        **kwargs,
        prepared_market=prepared_market,
        reuse_request=False,
    )
    numba_call = lambda: run_intrabar_kernel(**kwargs)

    one_shot_warm = one_shot_call()
    prepared_warm = prepared_call()
    numba_warm = numba_call()
    _assert_kernel_parity(one_shot_warm, prepared_warm)
    _assert_kernel_parity(numba_warm, prepared_warm)

    numba_plain_endpoint = _endpoint(frame, runtime="numba")
    numba_prepared_endpoint = _endpoint(frame, runtime="numba")
    rust_plain_endpoint = _endpoint(frame, runtime="rust")
    rust_prepared_endpoint = _endpoint(frame, runtime="rust")
    numba_plain_warm = numba_plain_endpoint.backtest(data=frame, intent=intent, symbols=["BTCUSDT"])
    numba_prepared_runner = numba_prepared_endpoint.prepare_intrabar(data=frame, symbols=["BTCUSDT"])
    numba_prepared_warm = numba_prepared_runner.run(intent)
    plain_warm = rust_plain_endpoint.backtest(data=frame, intent=intent, symbols=["BTCUSDT"])
    prepared_runner = rust_prepared_endpoint.prepare_intrabar(data=frame, symbols=["BTCUSDT"])
    prepared_public_warm = prepared_runner.run(intent)
    _assert_public_parity(numba_plain_warm, numba_prepared_warm)
    _assert_public_parity(numba_plain_warm, plain_warm)
    _assert_public_parity(numba_plain_warm, prepared_public_warm)
    if prepared_public_warm.metadata["request_cache_policy"] != "ephemeral_validated":
        raise AssertionError("prepared runner unexpectedly content-hashed its one-shot intent")
    rss_after_warm = _rss_mb()
    steady_runs = 96
    steady_checkpoints = (1, 8, 16, 32, 64, 96)
    steady_rss_samples: dict[str, float] = {}
    for run_number in range(1, steady_runs + 1):
        prepared_runner.run(intent)
        if run_number in steady_checkpoints:
            gc.collect()
            steady_rss_samples[str(run_number)] = _rss_mb()
    gc.collect()
    rss_after_prepared_steady = _rss_mb()

    numba_timing, _ = _timed(numba_call, repeats)
    one_shot_timing, one_shot = _timed(one_shot_call, repeats)
    prepared_timing, prepared = _timed(prepared_call, repeats)
    numba_plain_endpoint_timing, numba_plain = _timed(
        lambda: numba_plain_endpoint.backtest(data=frame, intent=intent, symbols=["BTCUSDT"]),
        repeats,
    )
    numba_prepared_runner_timing, numba_prepared_public = _timed(
        lambda: numba_prepared_runner.run(intent),
        repeats,
    )
    plain_endpoint_timing, plain = _timed(
        lambda: rust_plain_endpoint.backtest(data=frame, intent=intent, symbols=["BTCUSDT"]),
        repeats,
    )
    prepared_runner_timing, prepared_public = _timed(lambda: prepared_runner.run(intent), repeats)
    _assert_kernel_parity(one_shot, prepared)
    _assert_public_parity(numba_plain, numba_prepared_public)
    _assert_public_parity(numba_plain, plain)
    _assert_public_parity(plain, prepared_public)

    target = run_target(bars=bars, repeats=repeats)
    target["rss_interpretation"] = {
        "scope": "same_process_after_intrabar",
        "standalone_artifact": "benchmarks/native_event/results/phase66_rust_target_vectorized.json",
        "claim": "read direct-target RSS from the standalone Phase 66 process artifact",
    }
    timings = {
        "numba_standard": numba_timing,
        "numba_one_shot_endpoint": numba_plain_endpoint_timing,
        "numba_prepared_runner": numba_prepared_runner_timing,
        "rust_one_shot_adapter": one_shot_timing,
        "rust_prepared_adapter": prepared_timing,
        "rust_one_shot_endpoint": plain_endpoint_timing,
        "rust_prepared_runner": prepared_runner_timing,
    }
    return {
        "schema": "quantbt-phase77-native-performance-closure-v1",
        "fixture": {"bars": bars, "symbols": 1, "timeframe": "1h", "repeats": repeats},
        "work_counters": build_work_counters(
            supplied_market_bars=bars,
            candidate_count=1,
            scenario_count=1,
            symbol_count=1,
            folds=({"fold_id": 0, "test_start": 0, "test_end": bars},),
        ),
        "intrabar": {
            "timings": timings,
            "throughput_bars_per_second": {name: _rate(bars, timing) for name, timing in timings.items()},
            "ratios": {
                "prepared_adapter_vs_one_shot_adapter": float(
                    one_shot_timing["median_seconds"] / prepared_timing["median_seconds"]
                ),
                "prepared_runner_vs_one_shot_endpoint": float(
                    plain_endpoint_timing["median_seconds"] / prepared_runner_timing["median_seconds"]
                ),
                "rust_prepared_runner_vs_numba_prepared_runner": float(
                    numba_prepared_runner_timing["median_seconds"]
                    / prepared_runner_timing["median_seconds"]
                ),
            },
            "rss_mb": {
                "process_start": rss_start,
                "after_prepared_market": rss_after_prepared_market,
                "after_warm": rss_after_warm,
                "steady_runs": steady_runs,
                "prepared_runner_steady_samples": steady_rss_samples,
                "after_prepared_runner_steady": rss_after_prepared_steady,
                "prepared_runner_steady_delta": rss_after_prepared_steady - rss_after_warm,
                "prepared_runner_final_half_delta": (
                    rss_after_prepared_steady - steady_rss_samples.get("32", rss_after_warm)
                ),
            },
            "evidence": {
                "kernel_parity": True,
                "public_parity": True,
                "prepared_market_signature": prepared_market.market.signature,
                "prepared_request_cache_policy": prepared.metadata["request_cache_policy"],
                "one_shot_request_cache_policy": one_shot.metadata["request_cache_policy"],
                "native_boundary_calls": int(prepared.metadata["boundary_calls"]),
                "python_callbacks": int(prepared.metadata["python_callbacks"]),
            },
        },
        "target": target,
        "measurement_identity": capture_measurement_identity(
            root=ROOT,
            warmup_procedure=(
                "warm matched Numba, Rust one-shot, Rust prepared, and public runner paths before "
                "median/p95 timing; target benchmark warms its typed score and public compact routes"
            ),
            data_sha256=typed_array_sha256(
                tape.timestamps_ns,
                tape.opens,
                tape.highs,
                tape.lows,
                tape.closes,
                tape.volumes,
                tape.funding_rates,
                tape.funding_event_mask,
            ),
            intent_sha256=typed_array_sha256(
                intent.entry_side,
                intent.entry_size,
                intent.stop_value,
                intent.take_profit_value,
                intent.trailing_value,
                intent.exit_long,
                intent.exit_short,
            ),
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bars", type=int, default=20_000)
    parser.add_argument("--repeats", type=int, default=7)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    payload = run(bars=args.bars, repeats=args.repeats)
    output = args.output if args.output.is_absolute() else ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    output.with_suffix(".md").write_text(_markdown(payload), encoding="utf-8")
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
