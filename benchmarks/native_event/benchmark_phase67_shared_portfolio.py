#!/usr/bin/env python3
"""Phase 67 shared-account portfolio score/RSS evidence.

This benchmark intentionally measures the explicit Rust portfolio-target
contract only.  It reports preparation, direct score, compact retention, and
prepared target-WFO separately so a scalar native loop is never compared to a
Python report-building facade as though they were the same workload.
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
import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOT = ROOT / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from quantbt.backends.native_strategy_ir import NativeIRFold  # noqa: E402
from quantbt.backends.native_wfo import NativeTargetWfoRuntimeV2  # noqa: E402
from quantbt.preparation.native_execution import NativeExecutionPreparationCache  # noqa: E402


DEFAULT_OUTPUT = ROOT / "benchmarks/native_event/results/phase67_shared_portfolio.json"


def _rss_mb() -> float:
    status = Path("/proc/self/status")
    if not status.is_file():
        return 0.0
    for line in status.read_text(encoding="utf-8").splitlines():
        if line.startswith("VmRSS:"):
            return float(line.split()[1]) / 1024.0
    return 0.0


def _timed(call: Callable[[], Any], repeats: int) -> tuple[float, Any]:
    samples: list[float] = []
    result: Any = None
    for _ in range(repeats):
        started = perf_counter()
        result = call()
        samples.append(perf_counter() - started)
    return float(median(samples)), result


def _fixture(bars: int, symbols: int) -> dict[str, Any]:
    if bars < 128 or symbols not in {1, 2, 8, 20}:
        raise ValueError("bars must be >= 128 and symbols must be one of 1, 2, 8, 20")
    phase = np.arange(bars, dtype=np.float64)
    base = 100.0 + 0.003 * phase + 2.0 * np.sin(phase / 31.0)
    offsets = np.arange(symbols, dtype=np.float64) * 7.0
    closes = np.ascontiguousarray(base.reshape(-1, 1) + offsets.reshape(1, -1))
    targets = np.ascontiguousarray(
        np.where(
            np.sin(phase / 43.0).reshape(-1, 1) > 0.30,
            0.75,
            np.where(np.sin(phase / 43.0).reshape(-1, 1) < -0.30, -0.75, 0.0),
        )
        * np.where(np.arange(symbols) % 2 == 0, 1.0, -1.0).reshape(1, -1),
        dtype=np.float64,
    )
    targets[0] = 0.0
    funding = np.zeros_like(closes)
    funding[::8] = 0.00005
    funding_mask = np.zeros(bars, dtype=np.bool_)
    funding_mask[::8] = True
    funding_mask[0] = False
    return {
        "index": pd.date_range("2024-01-01", periods=bars, freq="1h", tz="UTC"),
        "closes": closes,
        "highs": np.ascontiguousarray(closes + 0.8),
        "lows": np.ascontiguousarray(closes - 0.8),
        "targets": targets,
        "funding": np.ascontiguousarray(funding),
        "funding_mask": funding_mask,
        "symbols": tuple(f"S{symbol:02d}" for symbol in range(symbols)),
    }


def _prepare(cache: NativeExecutionPreparationCache, fixture: dict[str, Any], profile: int):
    symbols = len(fixture["symbols"])
    market = cache.prepare_market(
        timestamps_ns=np.ascontiguousarray(fixture["index"].view("int64"), dtype=np.int64),
        opens=fixture["closes"],
        highs=fixture["highs"],
        lows=fixture["lows"],
        closes=fixture["closes"],
        volumes=np.ones_like(fixture["closes"]),
        funding=fixture["funding"],
        funding_mask=fixture["funding_mask"],
        symbols=fixture["symbols"],
    )
    template = cache.prepare_template(
        market,
        contract_sizes=np.ones(symbols, dtype=np.float64),
        leverages=np.full(symbols, 3.0, dtype=np.float64),
        fee_rates=np.full(symbols, 0.0005, dtype=np.float64),
        initial_capital=1_000_000.0,
        maintenance_ratio=0.005,
        slippage_rate=0.0002,
        use_funding=True,
    )
    return template, cache.shared_portfolio_target_request(
        template,
        targets=fixture["targets"],
        target_kind="units",
        admission_policy="reduce_first_then_increase",
        output_profile=profile,
    )


def _folds(bars: int) -> tuple[NativeIRFold, ...]:
    first = bars // 3
    second = 2 * bars // 3
    return (
        NativeIRFold(1, 0, 0, first, first, second),
        NativeIRFold(2, 0, 0, second, second, bars),
    )


def _markdown(payload: dict[str, Any]) -> str:
    timing = payload["timing_seconds"]
    rows = "\n".join(f"| `{name}` | {seconds:.6f} |" for name, seconds in timing.items())
    return "\n".join(
        (
            "# Phase 67 Rust Shared-Account Portfolio Benchmark",
            "",
            "This evidence measures only the explicit linear gross-cross,",
            "same-close portfolio-target contract. It does not benchmark generic",
            "portfolio planning, pandas reports, risk parity, packages, or callbacks.",
            "",
            "| Workload phase | Median seconds |",
            "|---|---:|",
            rows,
            "",
            f"- Bars/symbols: `{payload['fixture']['bars']}` / `{payload['fixture']['symbols']}`",
            f"- Score throughput: `{payload['throughput_bar_symbols_per_second']['prepared_score']:.1f}` bar-symbols/s",
            f"- WFO throughput: `{payload['throughput_bar_symbols_per_second']['prepared_wfo_score']:.1f}` bar-symbol-candidate-folds/s",
            f"- WFO candidates/folds: `{payload['fixture']['candidates']}` / `{payload['fixture']['folds']}`",
            f"- Score/compact terminal parity: `{payload['evidence']['score_compact_terminal_parity']}`",
            f"- WFO prepared parity: `{payload['evidence']['wfo_prepared_parity']}`",
            f"- Shared-account policy: `{payload['evidence']['admission_policy']}`",
            f"- Generic order arena used: `{payload['evidence']['generic_order_arena_used']}`",
            f"- RSS start / prepared / score / WFO: `{payload['rss_mb']['process_start']:.2f}` / `{payload['rss_mb']['after_prepare']:.2f}` / `{payload['rss_mb']['after_score']:.2f}` / `{payload['rss_mb']['after_wfo']:.2f}` MiB",
            "",
            "`prepared_score` is a repeat execution of an immutable Rust request after",
            "market/template/request preparation. `prepared_wfo_score` includes the",
            "native candidate-fold execution and metric matrix, but not Python strategy",
            "generation. Compact retention is intentionally listed separately from score.",
        )
    ) + "\n"


def run(*, bars: int, symbols: int, candidates: int, repeats: int) -> dict[str, Any]:
    fixture = _fixture(bars, symbols)
    gc.collect()
    rss_start = _rss_mb()
    cache = NativeExecutionPreparationCache()
    started = perf_counter()
    template, score_request = _prepare(cache, fixture, profile=0)
    _, compact_request = _prepare(cache, fixture, profile=1)
    prepare_seconds = perf_counter() - started
    rss_after_prepare = _rss_mb()

    # Warm the native request and score path before the timed samples.
    score_warm = dict(score_request.core.execute())
    compact_warm = dict(compact_request.core.execute())
    np.testing.assert_allclose(score_warm["final_equity"], compact_warm["final_equity"], rtol=0.0, atol=1e-11)
    score_seconds, score = _timed(lambda: dict(score_request.core.execute()), repeats)
    rss_after_score = _rss_mb()
    compact_seconds, compact = _timed(lambda: dict(compact_request.core.execute()), repeats)
    np.testing.assert_allclose(score["final_equity"], compact["final_equity"], rtol=0.0, atol=1e-11)

    folds = _folds(bars)
    runtime = NativeTargetWfoRuntimeV2(
        template,
        folds,
        admission_policy="reduce_first_then_increase",
    )
    try:
        ids = np.arange(1, candidates + 1, dtype=np.uint64)
        cube = np.repeat(fixture["targets"][np.newaxis, ...], candidates, axis=0)
        prepared = runtime.prepare_shared(cube, candidate_ids=ids)
        warm_matrix = runtime.score_prepared_batch(prepared)
        wfo_seconds, wfo = _timed(lambda: runtime.score_prepared_batch(prepared), repeats)
        np.testing.assert_allclose(warm_matrix.final_equity, wfo.final_equity, rtol=0.0, atol=1e-12)
        assert warm_matrix.terminal_fingerprint == wfo.terminal_fingerprint
        assert wfo.metadata["market_copy_bytes"] == 0
    finally:
        runtime.close()
    rss_after_wfo = _rss_mb()
    bar_symbols = bars * symbols
    wfo_bar_symbols = bar_symbols * candidates * len(folds)
    return {
        "schema": "phase67-shared-portfolio-benchmark-v1",
        "fixture": {"bars": bars, "symbols": symbols, "candidates": candidates, "folds": len(folds), "repeats": repeats},
        "timing_seconds": {
            "request_preparation": prepare_seconds,
            "prepared_score": score_seconds,
            "prepared_compact": compact_seconds,
            "prepared_wfo_score": wfo_seconds,
        },
        "throughput_bar_symbols_per_second": {
            "prepared_score": bar_symbols / score_seconds,
            "prepared_wfo_score": wfo_bar_symbols / wfo_seconds,
        },
        "rss_mb": {
            "process_start": rss_start,
            "after_prepare": rss_after_prepare,
            "after_score": rss_after_score,
            "after_wfo": rss_after_wfo,
        },
        "evidence": {
            "score_compact_terminal_parity": True,
            "wfo_prepared_parity": True,
            "admission_policy": "reduce_first_then_increase",
            "generic_order_arena_used": False,
            "wfo_market_copy_bytes": int(wfo.metadata["market_copy_bytes"]),
            "prepared_cache": cache.diagnostics,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bars", type=int, default=5_000)
    parser.add_argument("--symbols", type=int, default=8, choices=(1, 2, 8, 20))
    parser.add_argument("--candidates", type=int, default=16)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    payload = run(bars=args.bars, symbols=args.symbols, candidates=args.candidates, repeats=args.repeats)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    args.output.with_suffix(".md").write_text(_markdown(payload), encoding="utf-8")
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
