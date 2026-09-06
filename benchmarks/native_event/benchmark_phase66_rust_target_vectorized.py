#!/usr/bin/env python3
"""Phase 66 direct Rust target/vectorized authority evidence.

This benchmark compares the frozen same-close target-units contract only. It
keeps Numba as a warmed reproducibility comparator and separates prepared Rust
score, Python-to-Rust ingestion, and public compact-result adaptation. It does
not present the full facade as a pure-kernel number.
"""

from __future__ import annotations

import argparse
import gc
import json
from pathlib import Path
import platform
from statistics import median
import sys
from time import perf_counter
from typing import Any, Callable

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOT = ROOT / "src"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from tools.measurement_contract import (  # noqa: E402
    build_work_counters,
    capture_measurement_identity,
    typed_array_sha256,
)

from quantbt.backends.native_vectorized import NativeVectorizedBackend, NativeVectorizedConfig  # noqa: E402
from quantbt.core.schema import AccountConfig, ExecutionConfig  # noqa: E402
from quantbt.core.vectorized import _engine_units_v2  # noqa: E402
from quantbt.preparation.native_execution import NativeExecutionPreparationCache  # noqa: E402


DEFAULT_OUTPUT = ROOT / "benchmarks/native_event/results/phase66_rust_target_vectorized.json"


def _rss_mb() -> float:
    """Return current Linux RSS instead of a process high-water mark."""

    status = Path("/proc/self/status")
    if not status.is_file():
        return 0.0
    for line in status.read_text(encoding="utf-8").splitlines():
        if line.startswith("VmRSS:"):
            return float(line.split()[1]) / 1024.0
    return 0.0


def _fixture(bars: int) -> dict[str, Any]:
    if bars < 128:
        raise ValueError("bars must be >= 128")
    index = pd.date_range("2022-01-01", periods=bars, freq="1h", tz="UTC")
    phase = np.arange(bars, dtype=np.float64)
    close = 100.0 + 0.004 * phase + 2.4 * np.sin(phase / 27.0) + 0.8 * np.sin(phase / 5.0)
    close = np.ascontiguousarray(close.reshape(-1, 1), dtype=np.float64)
    high = np.ascontiguousarray(close + 0.8, dtype=np.float64)
    low = np.ascontiguousarray(close - 0.8, dtype=np.float64)
    target = np.ascontiguousarray(
        np.where(np.sin(phase / 41.0) >= 0.25, 1.75, np.where(np.sin(phase / 41.0) <= -0.25, -1.25, 0.0))
        .reshape(-1, 1),
        dtype=np.float64,
    )
    target[0, 0] = 0.0
    funding = np.zeros_like(close)
    funding[::8, 0] = 0.00005
    funding_mask = np.zeros(bars, dtype=np.bool_)
    funding_mask[::8] = True
    funding_mask[0] = False
    return {
        "index": index,
        "close": close,
        "high": high,
        "low": low,
        "target": target,
        "funding": np.ascontiguousarray(funding),
        "funding_mask": np.ascontiguousarray(funding_mask),
        "contract_sizes": np.array([1.0], dtype=np.float64),
        "leverages": np.array([3.0], dtype=np.float64),
        "fee_rates": np.array([0.0005], dtype=np.float64),
        "qty_step": np.array([0.25], dtype=np.float64),
        "min_qty": np.array([0.25], dtype=np.float64),
        "min_notional": np.array([10.0], dtype=np.float64),
    }


def _prepared_request(cache: NativeExecutionPreparationCache, fixture: dict[str, Any], *, profile: int):
    market = cache.prepare_market(
        timestamps_ns=np.ascontiguousarray(fixture["index"].view("int64"), dtype=np.int64),
        opens=fixture["close"],
        highs=fixture["high"],
        lows=fixture["low"],
        closes=fixture["close"],
        volumes=np.ones_like(fixture["close"]),
        funding=fixture["funding"],
        funding_mask=fixture["funding_mask"],
        symbols=["BTCUSDT"],
    )
    template = cache.prepare_template(
        market,
        contract_sizes=fixture["contract_sizes"],
        leverages=fixture["leverages"],
        fee_rates=fixture["fee_rates"],
        initial_capital=20_000.0,
        maintenance_ratio=0.005,
        slippage_rate=0.0002,
        use_funding=True,
    )
    return cache.direct_target_request(
        template,
        targets=fixture["target"],
        target_kind="units",
        timing="close_target_v2_same_close",
        invalid_target_policy="reject_run",
        qty_step=fixture["qty_step"],
        min_qty=fixture["min_qty"],
        min_notional=fixture["min_notional"],
        output_profile=profile,
    )


def _timed(call: Callable[[], Any], *, repeats: int) -> tuple[float, Any]:
    samples: list[float] = []
    result: Any = None
    for _ in range(repeats):
        started = perf_counter()
        result = call()
        samples.append(perf_counter() - started)
    return float(median(samples)), result


def _numba_call(fixture: dict[str, Any]):
    return _engine_units_v2(
        n_bars=len(fixture["index"]),
        n_syms=1,
        highs=fixture["high"],
        lows=fixture["low"],
        closes=fixture["close"],
        target_units=fixture["target"],
        funding_rates=fixture["funding"],
        is_funding_bar=fixture["funding_mask"],
        init_capital=20_000.0,
        leverages=fixture["leverages"],
        maint_ratio=0.005,
        fee_rates=fixture["fee_rates"],
        contract_sizes=fixture["contract_sizes"],
        slippage=0.0002,
        use_funding=True,
    )


def _public_backend(runtime: str) -> NativeVectorizedBackend:
    return NativeVectorizedBackend(
        NativeVectorizedConfig(
            account=AccountConfig(initial_capital=20_000.0, leverage=3.0, maintenance_ratio=0.005),
            execution=ExecutionConfig(slippage_bps=2.0),
            fee_rate=0.0005,
            use_funding=True,
            target_runtime=runtime,
        )
    )


def _public_call(backend: NativeVectorizedBackend, fixture: dict[str, Any]):
    index = fixture["index"]
    return backend.run_target_units(
        datetime_index=index,
        target_units={"BTCUSDT": pd.Series(fixture["target"][:, 0], index=index)},
        closes={"BTCUSDT": pd.Series(fixture["close"][:, 0], index=index)},
        highs={"BTCUSDT": pd.Series(fixture["high"][:, 0], index=index)},
        lows={"BTCUSDT": pd.Series(fixture["low"][:, 0], index=index)},
        funding_rate={"BTCUSDT": pd.Series(fixture["funding"][:, 0], index=index)},
        contract_size=1.0,
        leverage=3.0,
        qty_step=0.25,
        min_qty=0.25,
        min_notional=10.0,
        symbols=["BTCUSDT"],
    )


def _assert_parity(fixture: dict[str, Any], compact_payload: dict[str, Any], rust_public, numba_public) -> None:
    numba_raw = _numba_call(fixture)
    np.testing.assert_allclose(compact_payload["equity"], numba_raw[0], rtol=0.0, atol=1.0e-11)
    np.testing.assert_allclose(
        np.asarray(compact_payload["positions"]).reshape(fixture["close"].shape),
        numba_raw[1],
        rtol=0.0,
        atol=1.0e-12,
    )
    for field in ("equity", "positions", "fees", "funding", "margin", "diagnostics"):
        np.testing.assert_allclose(
            getattr(rust_public, field).to_numpy(),
            getattr(numba_public, field).to_numpy(),
            rtol=0.0,
            atol=1.0e-11,
        )


def _markdown(payload: dict[str, Any]) -> str:
    timing = payload["timings_seconds"]
    rows = "\n".join(f"| `{name}` | {value:.6f} |" for name, value in timing.items())
    evidence = payload["evidence"]
    return "\n".join(
        (
            "# Phase 66 Rust Direct Target Benchmark",
            "",
            "This is a same-fixture, warmed comparison of the narrow",
            "`close_target_v2_same_close` target-units contract. It is not a",
            "generic endpoint, callback, grid, portfolio, or full-report benchmark.",
            "",
            "| Phase | Median seconds |",
            "|---|---:|",
            rows,
            "",
            f"- Bars: `{payload['fixture']['bars']}`",
            f"- Symbols: `{payload['fixture']['symbols']}`",
            f"- Repeats: `{payload['fixture']['repeats']}`",
            f"- Rust prepared score throughput: `{payload['throughput_bars_per_second']['rust_prepared_score']:.1f}` bars/s",
            f"- Numba warmed kernel throughput: `{payload['throughput_bars_per_second']['numba_warmed_kernel']:.1f}` bars/s",
            f"- Rust prepared / Numba kernel ratio: `{payload['ratios']['rust_prepared_vs_numba_kernel']:.3f}x`",
            f"- Rust public compact / Numba public compact ratio: `{payload['ratios']['rust_public_vs_numba_public']:.3f}x`",
            f"- Exact accounting parity: `{evidence['exact_accounting_parity']}`",
            f"- Score retains path arrays: `{evidence['score_retains_paths']}`",
            f"- Score native passes / boundary calls: `{evidence['native_execution_passes']}` / `{evidence['boundary_calls']}`",
            f"- Generic order arena used: `{evidence['generic_order_arena_used']}`",
            f"- Prepared market cache entries: `{evidence['prepared_market_entries']}`",
            f"- RSS process start / score-warm / score-timed: `{payload['rss_mb']['process_start']:.2f}` / `{payload['rss_mb']['after_score_warmup']:.2f}` / `{payload['rss_mb']['after_score_timing']:.2f}` MiB",
            f"- Score steady-state RSS delta: `{payload['rss_mb']['score_timing_delta']:.2f}` MiB",
            f"- RSS after public compact benchmark: `{payload['rss_mb']['after_public_compact']:.2f}` MiB",
            "",
            "`rust_prepared_score` times one typed Rust execution request after its",
            "market/template/request ingestion. Its steady-state RSS delta is measured",
            "only after native/Numba warm-up, so extension loading and public result",
            "construction are not misreported as score-mode retention. `rust_public_compact`",
            "includes pandas normalization and `BacktestResultV2` materialization, which",
            "is why it must not be interpreted as a pure-kernel figure.",
        )
    ) + "\n"


def run(*, bars: int, repeats: int) -> dict[str, Any]:
    fixture = _fixture(bars)
    work_counters = build_work_counters(
        supplied_market_bars=bars,
        candidate_count=1,
        scenario_count=1,
        symbol_count=1,
        folds=({"fold_id": 0, "test_start": 0, "test_end": bars},),
    )
    gc.collect()
    rss_process_start = _rss_mb()

    # Ingestion is measured separately. Reuse of this cache is the service/WFO
    # route; a score call below has no pandas or DataFrame construction.
    started = perf_counter()
    cache = NativeExecutionPreparationCache()
    score_request = _prepared_request(cache, fixture, profile=0)
    compact_request = _prepared_request(cache, fixture, profile=1)
    ingest_seconds = perf_counter() - started

    # Warm the pure score paths before their memory/time measurement. The
    # score result is scalar-only and the native extension/load cost belongs
    # to process setup, not per-score retention.
    _numba_call(fixture)
    score_request.core.execute_typed()
    compact_payload = dict(compact_request.core.execute_typed().as_dict())
    gc.collect()
    rss_after_score_warmup = _rss_mb()

    rust_score_seconds, typed_score = _timed(score_request.core.execute_typed, repeats=repeats)
    numba_seconds, _ = _timed(lambda: _numba_call(fixture), repeats=repeats)
    gc.collect()
    rss_after_score_timing = _rss_mb()
    score_payload = dict(typed_score.as_dict())
    if "equity" in score_payload or "positions" in score_payload:
        raise AssertionError("direct Rust score unexpectedly retained compact paths")
    if score_payload.get("native_execution_passes") != 1:
        raise AssertionError("direct Rust score did not execute in one native pass")
    if score_payload.get("boundary_calls") != 1:
        raise AssertionError("direct Rust score did not preserve one typed boundary call")

    rust_backend = _public_backend("rust")
    numba_backend = _public_backend("numba")
    _public_call(rust_backend, fixture)
    _public_call(numba_backend, fixture)
    rust_public_seconds, rust_public = _timed(lambda: _public_call(rust_backend, fixture), repeats=repeats)
    numba_public_seconds, numba_public = _timed(lambda: _public_call(numba_backend, fixture), repeats=repeats)
    _assert_parity(fixture, compact_payload, rust_public, numba_public)
    if rust_public.metadata["native_target_execution"]["native_target_no_order_arena"] is not True:
        raise AssertionError("direct target public route reported a generic order arena")

    cache_diagnostics = cache.diagnostics
    gc.collect()
    rss_after_public_compact = _rss_mb()
    return {
        "schema": "quantbt-phase66-rust-target-vectorized-v1",
        "fixture": {"bars": bars, "symbols": 1, "repeats": repeats, "contract": "close_target_v2_same_close"},
        "timings_seconds": {
            "rust_ingestion_market_template_request": float(ingest_seconds),
            "rust_prepared_score": float(rust_score_seconds),
            "numba_warmed_kernel": float(numba_seconds),
            "rust_public_compact": float(rust_public_seconds),
            "numba_public_compact": float(numba_public_seconds),
        },
        "throughput_bars_per_second": {
            "rust_prepared_score": float(bars / rust_score_seconds),
            "numba_warmed_kernel": float(bars / numba_seconds),
            "rust_public_compact": float(bars / rust_public_seconds),
            "numba_public_compact": float(bars / numba_public_seconds),
        },
        "work_counters": work_counters,
        "ratios": {
            "rust_prepared_vs_numba_kernel": float(numba_seconds / rust_score_seconds),
            "rust_public_vs_numba_public": float(numba_public_seconds / rust_public_seconds),
        },
        "evidence": {
            "exact_accounting_parity": True,
            "score_retains_paths": False,
            "native_execution_passes": int(score_payload["native_execution_passes"]),
            "boundary_calls": int(score_payload["boundary_calls"]),
            "generic_order_arena_used": False,
            "prepared_market_entries": int(cache_diagnostics["tiers"]["market"]["entry_count"]),
            "prepared_request_entries": int(cache_diagnostics["tiers"]["request"]["entry_count"]),
            "prepared_market_copy_per_score": 0,
            "pandas_in_prepared_score": False,
        },
        "rss_mb": {
            "process_start": float(rss_process_start),
            "after_score_warmup": float(rss_after_score_warmup),
            "after_score_timing": float(rss_after_score_timing),
            "score_timing_delta": float(rss_after_score_timing - rss_after_score_warmup),
            "after_public_compact": float(rss_after_public_compact),
        },
        "environment": {"python": sys.version.split()[0], "platform": platform.platform()},
        "measurement_identity": capture_measurement_identity(
            root=ROOT,
            warmup_procedure="warm Numba and typed Rust score/compact requests before repeated median timing",
            data_sha256=typed_array_sha256(
                fixture["index"].view("int64"),
                fixture["close"],
                fixture["high"],
                fixture["low"],
                fixture["funding"],
                fixture["funding_mask"],
            ),
            intent_sha256=typed_array_sha256(
                fixture["target"],
                fixture["contract_sizes"],
                fixture["leverages"],
                fixture["fee_rates"],
                fixture["qty_step"],
                fixture["min_qty"],
                fixture["min_notional"],
            ),
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bars", type=int, default=20_000)
    parser.add_argument("--repeats", type=int, default=9)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--no-write", action="store_true")
    args = parser.parse_args()
    if args.repeats <= 0:
        raise ValueError("repeats must be > 0")
    payload = run(bars=args.bars, repeats=args.repeats)
    if not args.no_write:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        args.output.with_suffix(".md").write_text(_markdown(payload), encoding="utf-8")
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
