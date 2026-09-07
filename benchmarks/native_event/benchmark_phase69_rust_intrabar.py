#!/usr/bin/env python3
"""Phase 69 Rust intrabar authority benchmark and parity evidence.

This measures only the explicit bounded, single-symbol ``intrabar_bracket_v1``
contract. It keeps the Python oracle and Numba kernel outside the promotion
decision: the score request measures Rust execution only, compact exposes the
typed SoA-to-Python adaptation cost, and the public endpoint remains explicit.
It is not a benchmark of generic event callbacks, L2/depth matching, grid/DCA,
portfolio cross-margin, or arbitrary multi-symbol execution.
"""

from __future__ import annotations

import argparse
import gc
import importlib
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
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from tools.measurement_contract import (  # noqa: E402
    build_work_counters,
    capture_measurement_identity,
    typed_array_sha256,
)

from quantbt.backends.native_intrabar_rust import run_rust_intrabar_kernel  # noqa: E402
from quantbt.core.execution_contract import ExecutionContract  # noqa: E402
from quantbt.core.intrabar_kernel import run_intrabar_kernel  # noqa: E402
from quantbt.core.intrabar_reference import IntrabarIntentTape  # noqa: E402
from quantbt.core.market_tape import prepare_market_tape  # noqa: E402
from quantbt.core.schema import AccountConfig  # noqa: E402
from quantbt.preparation.native_execution import NativeExecutionPreparationCache  # noqa: E402


DEFAULT_OUTPUT = ROOT / "benchmarks/native_event/results/phase69_rust_intrabar.json"


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


def _fixture(bars: int) -> tuple[pd.DataFrame, IntrabarIntentTape]:
    if bars < 128:
        raise ValueError("bars must be >= 128")
    index = pd.date_range("2024-01-01", periods=bars, freq="1h", tz="UTC")
    phase = np.arange(bars, dtype=np.float64)
    close = 100.0 + 0.005 * phase + 2.5 * np.sin(phase / 31.0) + 1.1 * np.sin(phase / 7.0)
    opening = np.r_[close[0], close[:-1] + 0.15 * np.sin(phase[:-1] / 9.0)]
    high = np.maximum(opening, close) + 0.45 + 0.25 * np.abs(np.sin(phase / 5.0))
    low = np.minimum(opening, close) - 0.45 - 0.25 * np.abs(np.cos(phase / 6.0))
    funding = np.zeros(bars, dtype=np.float64)
    funding[::8] = 0.00005
    funding[0] = 0.0
    frame = pd.DataFrame(
        {"open": opening, "high": high, "low": low, "close": close, "volume": 100_000.0, "funding_rate": funding},
        index=index,
    )
    side = np.zeros(bars, dtype=np.int8)
    size = np.zeros(bars, dtype=np.float64)
    side[::41] = 1
    side[20::41] = -1
    size[side != 0] = 1.25
    stop = np.full(bars, np.nan, dtype=np.float64)
    take_profit = np.full(bars, np.nan, dtype=np.float64)
    trailing = np.full(bars, np.nan, dtype=np.float64)
    stop[side != 0] = 0.018
    take_profit[side != 0] = 0.032
    trailing[side != 0] = 0.014
    technical_exit = np.zeros(bars, dtype=np.bool_)
    technical_exit[31::83] = True
    return frame, IntrabarIntentTape.from_arrays(
        entry_side=side,
        entry_size=size,
        stop_value=stop,
        take_profit_value=take_profit,
        trailing_value=trailing,
        technical_exit=technical_exit,
    )


def _prepared_market(cache: NativeExecutionPreparationCache, tape):
    return cache.prepare_market(
        timestamps_ns=np.ascontiguousarray(tape.timestamps_ns, dtype=np.int64),
        opens=np.ascontiguousarray(tape.opens, dtype=np.float64),
        highs=np.ascontiguousarray(tape.highs, dtype=np.float64),
        lows=np.ascontiguousarray(tape.lows, dtype=np.float64),
        closes=np.ascontiguousarray(tape.closes, dtype=np.float64),
        volumes=np.ascontiguousarray(tape.volumes, dtype=np.float64),
        funding=np.ascontiguousarray(tape.funding_rates, dtype=np.float64),
        funding_mask=np.ascontiguousarray(tape.funding_event_mask, dtype=np.bool_),
        symbols=tape.symbols,
    )


def _request(native: Any, prepared: Any, intent: IntrabarIntentTape, *, profile: int):
    n = len(intent.entry_side)
    return native.NativeIntrabarRequestCore.from_prepared(
        prepared,
        np.ascontiguousarray(intent.entry_side, dtype=np.int8),
        np.ascontiguousarray(intent.entry_size, dtype=np.float64),
        np.ascontiguousarray(intent.stop_value, dtype=np.float64),
        np.ascontiguousarray(intent.take_profit_value, dtype=np.float64),
        np.ascontiguousarray(intent.trailing_value, dtype=np.float64),
        np.ascontiguousarray(intent.exit_long if intent.exit_long is not None else intent.technical_exit, dtype=np.bool_),
        np.ascontiguousarray(intent.exit_short if intent.exit_short is not None else intent.technical_exit, dtype=np.bool_),
        level_mode=3,
        initial_capital=20_000.0,
        leverage=3.0,
        maintenance_ratio=0.005,
        margin_buffer=0.0,
        contract_size=1.0,
        fee_rate=0.0005,
        slippage_rate=0.0002,
        sizing_mode=1,
        fixed_notional=0.0,
        equity_fraction=0.0,
        risk_fraction=0.0,
        qty_step=0.0,
        min_qty=0.0,
        min_notional=0.0,
        tick_size=0.0,
        bar_timestamp_semantics=1,
        same_bar_policy=1,
        take_profit_gap_policy=1,
        close_on_last_bar=True,
        output_profile=profile,
        audit_detail_limit=n * 4 + 4,
    )


def _assert_parity(numba, score: dict[str, Any], compact: dict[str, Any], public) -> None:
    for field, expected in (
        ("final_equity", float(numba.equity.iloc[-1])),
        ("final_position", float(numba.position.iloc[-1])),
        ("total_fee", float(numba.fees.sum())),
        ("total_funding", float(numba.funding.sum())),
        ("fill_count", int(numba.fill_count)),
        ("ambiguity_count", int(numba.ambiguity_count)),
        ("rejected_count", int(numba.rejected_count)),
    ):
        np.testing.assert_allclose(score[field], expected, rtol=0.0, atol=1.0e-9)
        np.testing.assert_allclose(compact[field], expected, rtol=0.0, atol=1.0e-9)
    for field, expected in (
        ("equity", numba.equity.to_numpy(dtype=np.float64)),
        ("position", numba.position.to_numpy(dtype=np.float64)),
        ("fees", numba.fees.to_numpy(dtype=np.float64)),
        ("funding", numba.funding.to_numpy(dtype=np.float64)),
    ):
        np.testing.assert_allclose(np.asarray(compact[field]), expected, rtol=0.0, atol=1.0e-9)
    np.testing.assert_allclose(public.equity.to_numpy(), numba.equity.to_numpy(), rtol=0.0, atol=1.0e-9)
    np.testing.assert_allclose(public.position.to_numpy(), numba.position.to_numpy(), rtol=0.0, atol=1.0e-9)


def _markdown(payload: dict[str, Any]) -> str:
    timing = payload["timing_seconds"]
    throughput = payload["throughput_bars_per_second"]
    rss = payload["rss_mb"]
    return "\n".join(
        (
            "# Phase 69 Rust Intrabar Benchmark",
            "",
            "This evidence measures the explicit single-symbol `intrabar_bracket_v1`",
            "OHLC path contract only. It is not evidence for L2 matching, generic event",
            "callbacks, grid/DCA state machines, or shared portfolio margin.",
            "",
            "| Workload | Median seconds | Bars/s |",
            "|---|---:|---:|",
            f"| Warm Numba standard/path comparator | {timing['numba_warm']:0.6f} | {throughput['numba_warm']:,.0f} |",
            f"| Rust prepared score kernel | {timing['rust_score_warm']:0.6f} | {throughput['rust_score_warm']:,.0f} |",
            f"| Rust prepared compact kernel | {timing['rust_compact_kernel_warm']:0.6f} | {throughput['rust_compact_kernel_warm']:,.0f} |",
            f"| Rust full adapter, compact result | {timing['rust_adapter_compact_warm']:0.6f} | {throughput['rust_adapter_compact_warm']:,.0f} |",
            f"| Rust cold prepare + score request | {timing['rust_cold_prepare_score']:0.6f} | {throughput['rust_cold_prepare_score']:,.0f} |",
            "",
            f"- Fixture: `{payload['fixture']['bars']}` one-hour bars, deterministic long/short entries, SL/TP/trailing, technical exits, fee/slippage, and close-timestamp funding.",
            f"- Parity: `{payload['evidence']['terminal_and_path_parity']}`; score keeps no dense paths: `{payload['evidence']['score_has_no_dense_paths']}`.",
            f"- Rust boundary calls: `{payload['evidence']['boundary_calls']}`; Python callbacks: `{payload['evidence']['python_callbacks']}`.",
            f"- RSS start / prepared / profiles: `{rss['process_start']:.2f}` / `{rss['after_prepared_market']:.2f}` / `{rss['after_profiles']:.2f}` MiB.",
            "",
            "`score` is a typed native request with scalar output only. `compact` is shown",
            "separately because SoA transfer and pandas result adaptation are cold-path work.",
            "The public route remains explicit; Numba remains the version-pinned rollback",
            "comparator for at least one stable release.",
        )
    ) + "\n"


def run(*, bars: int, repeats: int) -> dict[str, Any]:
    if repeats < 1:
        raise ValueError("repeats must be >= 1")
    native = importlib.import_module("_quantbt_native")
    if not hasattr(native, "NativeIntrabarRequestCore"):
        raise RuntimeError("installed quantbt-native lacks NativeIntrabarRequestCore")
    gc.collect()
    work_counters = build_work_counters(
        supplied_market_bars=bars,
        candidate_count=1,
        scenario_count=1,
        symbol_count=1,
        folds=({"fold_id": 0, "test_start": 0, "test_end": bars},),
    )
    rss_start = _rss_mb()
    frame, intent = _fixture(bars)
    tape = prepare_market_tape(
        data=frame,
        symbols=["BTCUSDT"],
        funding_rate=frame["funding_rate"],
        use_funding=True,
        bar_timestamp_semantics="close",
    )
    account = AccountConfig(initial_capital=20_000.0, leverage=3.0, maintenance_ratio=0.005)
    contract = ExecutionContract.intrabar_bracket(close_on_last_bar=True)
    cache = NativeExecutionPreparationCache()
    prepared = _prepared_market(cache, tape)
    rss_after_prepared = _rss_mb()
    score_request = _request(native, prepared.core, intent, profile=0)
    compact_request = _request(native, prepared.core, intent, profile=1)
    # Warm each route before timing. Rust is ahead-of-time compiled; this only
    # removes allocation/cache noise from the median steady-state measurement.
    score_warm = dict(score_request.execute())
    compact_warm = dict(compact_request.execute())
    numba_warm = run_intrabar_kernel(
        tape=tape,
        intent=intent,
        account=account,
        contract=contract,
        fee_rate=0.0005,
        slippage_rate=0.0002,
        report_level="standard",
    )
    rust_public_warm = run_rust_intrabar_kernel(
        tape=tape,
        intent=intent,
        account=account,
        contract=contract,
        fee_rate=0.0005,
        slippage_rate=0.0002,
        report_level="standard",
        native_preparation_cache=cache,
    )
    _assert_parity(numba_warm, score_warm, compact_warm, rust_public_warm)
    assert "equity" not in score_warm
    assert "position" not in score_warm

    numba_seconds, _ = _timed(
        lambda: run_intrabar_kernel(
            tape=tape,
            intent=intent,
            account=account,
            contract=contract,
            fee_rate=0.0005,
            slippage_rate=0.0002,
            report_level="standard",
        ),
        repeats,
    )
    score_seconds, score = _timed(lambda: dict(score_request.execute()), repeats)
    compact_seconds, compact = _timed(lambda: dict(compact_request.execute()), repeats)
    adapter_seconds, public = _timed(
        lambda: run_rust_intrabar_kernel(
            tape=tape,
            intent=intent,
            account=account,
            contract=contract,
            fee_rate=0.0005,
            slippage_rate=0.0002,
            report_level="standard",
            native_preparation_cache=cache,
        ),
        repeats,
    )
    _assert_parity(numba_warm, score, compact, public)
    rss_after_profiles = _rss_mb()

    cold_cache = NativeExecutionPreparationCache()

    def cold_prepare_score() -> dict[str, Any]:
        cold_cache.clear(force=True)
        cold_market = _prepared_market(cold_cache, tape)
        return dict(_request(native, cold_market.core, intent, profile=0).execute())

    cold_seconds, cold_score = _timed(cold_prepare_score, repeats)
    np.testing.assert_allclose(cold_score["final_equity"], score["final_equity"], rtol=0.0, atol=1.0e-9)
    timings = {
        "numba_warm": numba_seconds,
        "rust_score_warm": score_seconds,
        "rust_compact_kernel_warm": compact_seconds,
        "rust_adapter_compact_warm": adapter_seconds,
        "rust_cold_prepare_score": cold_seconds,
    }
    payload: dict[str, Any] = {
        "schema": "quantbt-phase69-rust-intrabar-benchmark-v1",
        "fixture": {"bars": bars, "symbols": 1, "timeframe": "1h", "contract": "intrabar_bracket_v1"},
        "timing_seconds": timings,
        "throughput_bars_per_second": {key: float(bars / value) for key, value in timings.items()},
        "work_counters": work_counters,
        "rss_mb": {
            "process_start": rss_start,
            "after_prepared_market": rss_after_prepared,
            "after_profiles": rss_after_profiles,
        },
        "evidence": {
            "terminal_and_path_parity": True,
            "score_has_no_dense_paths": True,
            "boundary_calls": 1,
            "python_callbacks": 0,
            "prepared_market_signature": prepared.signature,
            "prepared_market_copy_bytes": int(prepared.ingress_copied_bytes),
            "numba_comparator": "run_intrabar_kernel standard profile",
            "rust_public_route": "run_rust_intrabar_kernel explicit route",
        },
        "measurement_identity": capture_measurement_identity(
            root=ROOT,
            warmup_procedure="warm prepared market and score/compact/public intrabar profiles before repeated median timing",
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
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bars", type=int, default=2_000)
    parser.add_argument("--repeats", type=int, default=5)
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
