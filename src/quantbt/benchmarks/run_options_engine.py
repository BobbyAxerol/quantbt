#!/usr/bin/env python3
"""Phase 10 options-engine benchmark and parity guard."""

from __future__ import annotations

import argparse
import json
import sys
import time
import tracemalloc
from pathlib import Path
from typing import Dict, Sequence

import numpy as np
import pandas as pd

PACKAGE_DIR = Path(__file__).resolve().parents[1]
PROJECT_DIR = PACKAGE_DIR.parent
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from quantbt import (  # noqa: E402
    ExerciseStyle,
    NativeOptionBackend,
    NativeOptionConfig,
    OptionInstrumentRegistry,
    OptionInstrumentSpec,
    OptionKind,
    OptionPackageIntent,
    OptionPackageLeg,
    OptionPreparedRunCache,
    OrderSide,
    PremiumConvention,
    SettlementStyle,
)


def run_benchmark(*, snapshots: int, contracts: int, packages: int, repeats: int, seed: int) -> Dict:
    rng = np.random.default_rng(seed)
    registry = _registry(contracts)
    chain = _chain(registry, snapshots=snapshots, rng=rng)
    package_list = _packages(registry, chain, packages=packages)
    config = NativeOptionConfig(initial_balances={"USD": 100_000.0}, reporting_currency="USD", random_seed=seed)
    backend = NativeOptionBackend(config)

    uncached = backend.run(chain=chain, instruments=registry, packages=package_list)
    cache = OptionPreparedRunCache.from_chain(chain, registry)
    cached = backend.run(chain=chain, instruments=registry, packages=package_list, prepared_cache=cache)
    parity = _parity(uncached, cached)

    uncached_seconds = _timeit(lambda: backend.run(chain=chain, instruments=registry, packages=package_list), repeats)
    cached_seconds = _timeit(lambda: backend.run(chain=chain, instruments=registry, packages=package_list, prepared_cache=cache), repeats)
    peak_mb = _peak_memory_mb(lambda: backend.run(chain=chain, instruments=registry, packages=package_list, prepared_cache=cache))
    return {
        "phase": "options_phase10",
        "status": "pass" if parity["passed"] else "fail",
        "seed": int(seed),
        "snapshots": int(snapshots),
        "contracts": int(contracts),
        "quotes": int(len(chain)),
        "packages": int(len(package_list)),
        "fills": int(len(cached.fills_report)),
        "hedges": 0,
        "memory_peak_mb": float(peak_mb),
        "uncached_seconds": float(uncached_seconds),
        "cached_seconds": float(cached_seconds),
        "cache_speedup": float(uncached_seconds / cached_seconds) if cached_seconds > 0.0 else 0.0,
        "package_cache_size": int(cache.package_cache_size),
        "parity": parity,
        "run_manifest": cached.run_manifest,
        "cython_cpp_recommendation": (
            "not_recommended_yet: Phase 10 benchmark still targets pandas/tape/package facade and cache reuse; "
            "collect pure-kernel profile evidence before Cython/C++."
        ),
    }


def make_markdown(report: Dict) -> str:
    lines = [
        "# Options Engine Phase 10 Benchmark",
        "",
        f"Status: **{report['status']}**",
        "",
        "| metric | value |",
        "| --- | ---: |",
        f"| snapshots | `{report['snapshots']}` |",
        f"| contracts | `{report['contracts']}` |",
        f"| quotes | `{report['quotes']}` |",
        f"| packages | `{report['packages']}` |",
        f"| fills | `{report['fills']}` |",
        f"| hedges | `{report['hedges']}` |",
        f"| peak memory MB | `{report['memory_peak_mb']:.3f}` |",
        f"| uncached seconds | `{report['uncached_seconds']:.6f}` |",
        f"| cached seconds | `{report['cached_seconds']:.6f}` |",
        f"| cache speedup | `{report['cache_speedup']:.3f}x` |",
        f"| package cache size | `{report['package_cache_size']}` |",
        "",
        "## Parity Guard",
        "",
        f"- Passed: `{report['parity']['passed']}`",
        f"- Final equity abs diff: `{report['parity']['final_equity_abs_diff']:.12f}`",
        f"- Position max abs diff: `{report['parity']['position_max_abs_diff']:.12f}`",
        f"- Fills equal: `{report['parity']['fills_equal']}`",
        "",
        "## Manifest",
        "",
        f"- Data hash: `{report['run_manifest'].get('data_hash')}`",
        f"- Margin model: `{report['run_manifest'].get('margin_model')}`",
        f"- Pricing model: `{report['run_manifest'].get('pricing_model')}`",
        f"- Fidelity: `{report['run_manifest'].get('fidelity_manifest')}`",
        "",
        "## Cython / C++ Decision",
        "",
        report["cython_cpp_recommendation"],
        "",
    ]
    return "\n".join(lines)


def _registry(contracts: int) -> OptionInstrumentRegistry:
    expiry = int(pd.Timestamp("2026-03-01 08:00:00", tz="UTC").value)
    specs = []
    for i in range(contracts):
        strike = 80_000.0 + 1_000.0 * i
        kind = OptionKind.CALL if i % 2 == 0 else OptionKind.PUT
        specs.append(
            OptionInstrumentSpec(
                symbol=f"BTC-O{i:04d}.TEST",
                venue="test",
                underlying_id="BTC-PERP.TEST",
                underlying_index_id="BTC-INDEX.TEST",
                option_kind=kind,
                exercise_style=ExerciseStyle.EUROPEAN,
                premium_convention=PremiumConvention.LINEAR_QUOTE,
                settlement_style=SettlementStyle.CASH,
                strike=strike,
                expiry_ns=expiry,
                settlement_currency="USD",
                premium_currency="USD",
                quote_currency="USD",
                multiplier=1.0,
                contract_size=1.0,
                qty_step=1.0,
                tick_size=0.01,
                convention_version="phase10_linear_benchmark_v1",
            )
        )
    return OptionInstrumentRegistry.from_iterable(specs)


def _chain(registry: OptionInstrumentRegistry, *, snapshots: int, rng) -> pd.DataFrame:
    start = pd.Timestamp("2026-01-01 00:00:00", tz="UTC")
    rows = []
    for t in range(snapshots):
        ts = int((start + pd.Timedelta(minutes=15 * t)).value)
        index_price = 100_000.0 + 100.0 * np.sin(t / 10.0)
        for code, spec in enumerate(registry.instruments):
            intrinsic = max(index_price - spec.strike, 0.0) if spec.option_kind is OptionKind.CALL else max(spec.strike - index_price, 0.0)
            time_value = 500.0 + 5.0 * code + float(rng.normal(0.0, 1.0))
            mark = max(intrinsic + time_value, 1.0)
            rows.append(
                {
                    "timestamp_ns": ts,
                    "instrument_id": spec.symbol,
                    "venue": "TEST",
                    "underlying_id": spec.underlying_id,
                    "expiry_ns": spec.expiry_ns,
                    "strike": spec.strike,
                    "option_kind": spec.option_kind.value,
                    "bid_price": mark * 0.995,
                    "bid_size": 50.0,
                    "ask_price": mark * 1.005,
                    "ask_size": 50.0,
                    "mark_price": mark,
                    "last_price": mark,
                    "index_price": index_price,
                    "forward_price": index_price,
                    "mark_iv": 0.6,
                    "bid_iv": 0.59,
                    "ask_iv": 0.61,
                    "delta": 0.5 if spec.option_kind is OptionKind.CALL else -0.5,
                    "gamma": 0.0001,
                    "vega": 100.0,
                    "theta": -10.0,
                    "open_interest": 1000.0,
                    "volume": 100.0,
                    "quote_currency": "USD",
                    "settlement_currency": "USD",
                    "sequence_id": code,
                    "source_latency_ns": 1_000_000,
                }
            )
    return pd.DataFrame(rows)


def _packages(registry: OptionInstrumentRegistry, chain: pd.DataFrame, *, packages: int) -> Sequence[OptionPackageIntent]:
    timestamps = sorted(chain["timestamp_ns"].unique())
    symbols = list(registry.symbols)
    out = []
    for i in range(packages):
        ts = int(timestamps[i % len(timestamps)])
        symbol = symbols[i % len(symbols)]
        side = OrderSide.BUY if i % 2 == 0 else OrderSide.SELL
        out.append(
            OptionPackageIntent(
                timestamp_ns=ts,
                package_id=f"bench-{i:05d}",
                legs=(OptionPackageLeg(symbol, side, 1.0),),
                quantity=1.0,
            )
        )
    return tuple(out)


def _parity(a, b) -> Dict:
    equity_diff = float(abs(a.equity.iloc[-1] - b.equity.iloc[-1]))
    position_diff = float(np.max(np.abs(a.positions.to_numpy() - b.positions.to_numpy())))
    fills_equal = bool(a.fills_report.equals(b.fills_report))
    return {
        "passed": bool(equity_diff <= 1e-9 and position_diff <= 1e-12 and fills_equal),
        "final_equity_abs_diff": equity_diff,
        "position_max_abs_diff": position_diff,
        "fills_equal": fills_equal,
    }


def _timeit(fn, repeats: int) -> float:
    durations = []
    for _ in range(max(1, repeats)):
        start = time.perf_counter()
        fn()
        durations.append(time.perf_counter() - start)
    return float(min(durations))


def _peak_memory_mb(fn) -> float:
    tracemalloc.start()
    try:
        fn()
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    return peak / 1_000_000.0


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshots", type=int, default=96)
    parser.add_argument("--contracts", type=int, default=48)
    parser.add_argument("--packages", type=int, default=96)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--output-json", type=Path, default=PACKAGE_DIR / "benchmarks" / "options_phase10_baseline.json")
    parser.add_argument("--output-md", type=Path, default=PACKAGE_DIR / "benchmarks" / "options_phase10_baseline.md")
    args = parser.parse_args()

    report = run_benchmark(
        snapshots=args.snapshots,
        contracts=args.contracts,
        packages=args.packages,
        repeats=args.repeats,
        seed=args.seed,
    )
    args.output_json.write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")
    args.output_md.write_text(make_markdown(report), encoding="utf-8")
    print(json.dumps({"status": report["status"], "cache_speedup": report["cache_speedup"]}, indent=2))
    if report["status"] != "pass":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
