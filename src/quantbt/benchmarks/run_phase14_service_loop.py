#!/usr/bin/env python3
"""
Phase 14C real WFO and service-loop benchmark.

This runner measures the remaining higher-level performance debt without
changing engine semantics.  It is intentionally a benchmark/certification
artifact, not an optimization pass.
"""

from __future__ import annotations

import argparse
import gc
import json
import statistics
import sys
import time
import tracemalloc
from dataclasses import asdict
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

PACKAGE_DIR = Path(__file__).resolve().parents[1]
PROJECT_DIR = PACKAGE_DIR.parent
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from quantbt import (  # noqa: E402
    AccountConfig,
    ArbExecutionPolicy,
    ArbitrageLeg,
    BasisArbitrageSpec,
    ContractType,
    ExecutionConfig,
    HedgePolicy,
    HedgePolicyKind,
    NativeEventBackend,
    NativeEventConfig,
    NativeVectorizedBackend,
    NativeVectorizedConfig,
    OrderIntent,
    OrderSide,
    OrderType,
    PackageExecutionKind,
    QuantBTEndpoint,
    SizingPolicy,
    SizingPolicyKind,
    TimeInForce,
    build_arbitrage_domain_audit,
    compare_native_arbitrage_results,
)
from quantbt.benchmarks.profile_phase7 import profile_native_event, profile_native_vectorized  # noqa: E402
from quantbt.benchmarks.run_phase7 import BenchmarkProfile, _make_market_frames, _make_orders  # noqa: E402
from quantbt.benchmarks.run_phase12_benchmark_nautilus_cert import _benchmark_native_portfolio  # noqa: E402


def run_benchmark(
    *,
    rows: int = 720,
    symbols: int = 4,
    trials: int = 8,
    folds: int = 1,
    order_count: Optional[int] = None,
    repeats: int = 2,
) -> Dict:
    order_count = int(order_count if order_count is not None else max(20, rows // 3))
    stage_profile = BenchmarkProfile(
        name="phase14b",
        bars=int(rows),
        symbols=max(2, int(symbols)),
        order_count=order_count,
        repeats=max(1, int(repeats)),
    )

    vectorized_profile = profile_native_vectorized(stage_profile)
    event_profile = profile_native_event(stage_profile)
    portfolio_profile = _benchmark_native_portfolio(
        rows=int(rows),
        symbols=max(2, int(symbols)),
        repeats=max(1, int(repeats)),
    )
    single_wfo = _single_symbol_wfo_benchmark(rows=rows, trials=trials, repeats=repeats)
    portfolio_wfo = _portfolio_wfo_benchmark(rows=rows, trials=trials, repeats=repeats)
    event_replay = _native_event_replay_benchmark(rows=rows, symbols=symbols, order_count=order_count, repeats=repeats)
    arbitrage_sweep = _arbitrage_package_sweep(rows=rows, repeats=repeats)
    report_cost = _report_level_benchmark(rows=rows, symbols=symbols, repeats=repeats)

    parity = {
        "single_symbol_wfo": single_wfo["parity_passed"],
        "portfolio_wfo": portfolio_wfo["parity_passed"],
        "native_event_replay": event_replay["parity_passed"],
        "arbitrage_package_sweep": arbitrage_sweep["parity_passed"],
        "report_heavy_vs_light": report_cost["parity_passed"],
    }
    pure_kernel_share_pct = max(
        _stage_share(vectorized_profile, "pure_numba_kernel"),
        _stage_share(event_profile, "pure_numba_kernel"),
        float(portfolio_profile["stages"]["pure_kernel_share_pct"]),
    )
    status = "pass" if all(parity.values()) and portfolio_profile["status"] == "pass" else "fail"
    return {
        "status": status,
        "rows": int(rows),
        "symbols": max(2, int(symbols)),
        "trials": int(trials),
        "folds": int(folds),
        "order_count": order_count,
        "repeats": int(repeats),
        "decomposition": {
            "native_vectorized": asdict(vectorized_profile),
            "native_event": asdict(event_profile),
            "native_portfolio": portfolio_profile,
        },
        "service_loops": {
            "single_symbol_wfo": single_wfo,
            "portfolio_wfo": portfolio_wfo,
            "native_event_replay": event_replay,
            "arbitrage_package_sweep": arbitrage_sweep,
            "report_heavy_vs_light": report_cost,
        },
        "parity": parity,
        "cython_cpp_recommendation": _cython_cpp_recommendation(pure_kernel_share_pct),
        "next_optimization_targets": _next_targets(vectorized_profile, event_profile, portfolio_profile),
    }


def make_markdown(report: Dict) -> str:
    loops = report["service_loops"]
    lines = [
        "# Phase 14C Prepared Cache And Report-Level Benchmark",
        "",
        f"Status: **{report['status']}**",
        "",
        "## Profile",
        "",
        f"- Rows: `{report['rows']}`",
        f"- Symbols: `{report['symbols']}`",
        f"- Optuna trials: `{report['trials']}`",
        f"- Order count: `{report['order_count']}`",
        f"- Repeats: `{report['repeats']}`",
        "",
        "## Service Loop Timings",
        "",
        "| workload | cold/full seconds | prepared/light seconds | speedup | peak MB | parity | notes |",
        "| --- | ---: | ---: | ---: | ---: | --- | --- |",
    ]
    for key, label in (
        ("single_symbol_wfo", "single-symbol WFO"),
        ("portfolio_wfo", "portfolio WFO"),
        ("native_event_replay", "native-event replay"),
        ("arbitrage_package_sweep", "arbitrage sweep"),
        ("report_heavy_vs_light", "portfolio report levels"),
    ):
        item = loops[key]
        lines.append(
            "| {label} | `{cold:.6f}` | `{prepared:.6f}` | `{speedup:.3f}x` | `{peak:.3f}` | `{parity}` | {notes} |".format(
                label=label,
                cold=float(item.get("full_seconds", item.get("cold_seconds", 0.0))),
                prepared=float(item.get("prepared_seconds", item.get("light_seconds", 0.0))),
                speedup=float(item.get("speedup", 0.0)),
                peak=float(item.get("peak_memory_mb", 0.0)),
                parity=bool(item.get("parity_passed", False)),
                notes=item.get("notes", ""),
            )
        )

    lines.extend(
        [
            "",
            "## Stage Decomposition",
            "",
            "| backend | stage | seconds | share |",
            "| --- | --- | ---: | ---: |",
        ]
    )
    for backend in ("native_vectorized", "native_event"):
        record = report["decomposition"][backend]
        for stage in record["stages"]:
            lines.append(
                f"| `{backend}` | `{stage['stage']}` | `{stage['seconds']:.6f}` | `{stage['percent_of_profile']:.2f}%` |"
            )
    p = report["decomposition"]["native_portfolio"]["stages"]
    for stage, label in (
        ("array_preparation_seconds", "array_preparation"),
        ("pure_numba_kernel_seconds", "pure_numba_kernel"),
        ("report_construction_estimate_seconds", "report_construction_estimate"),
    ):
        share_key = {
            "array_preparation_seconds": "array_preparation_share_pct",
            "pure_numba_kernel_seconds": "pure_kernel_share_pct",
            "report_construction_estimate_seconds": "report_construction_share_pct",
        }[stage]
        lines.append(f"| `native_portfolio` | `{label}` | `{p[stage]:.6f}` | `{p[share_key]:.2f}%` |")

    lines.extend(
        [
            "",
            "## Parity Guards",
            "",
        ]
    )
    for name, passed in report["parity"].items():
        lines.append(f"- `{name}`: `{passed}`")

    lines.extend(
        [
            "",
            "## Next Optimization Targets",
            "",
        ]
    )
    for target in report["next_optimization_targets"]:
        lines.append(f"- {target}")

    lines.extend(
        [
            "",
            "## Cython/C++ Decision",
            "",
            report["cython_cpp_recommendation"],
            "",
            "This report is a measurement artifact. It must not be used to justify changing accounting, fill policy, margin, or report semantics.",
        ]
    )
    return "\n".join(lines) + "\n"


def _single_symbol_wfo_benchmark(*, rows: int, trials: int, repeats: int) -> Dict:
    _quiet_optuna()
    data = _single_frame(rows)

    def run_once(use_cache: bool):
        endpoint = QuantBTEndpoint.train_test_split(
            strategy_class=_single_wfo_strategy,
            test_start=data.index[max(20, len(data) // 2)],
            target_mode="signal_notional",
            backend="native_vectorized",
            optimization_mode="mode_5_full_robust",
            optimization_config={
                "scoring_backend": "endpoint",
                "use_prepared_scoring_cache": bool(use_cache),
                "candidate_selection_metric": "full_plateau_robust",
                "top_is_fraction": 0.3,
                "scoring_trading_days": 365,
                "use_numba": True,
            },
            optuna_trials=max(2, int(trials)),
            random_seed=42,
            initial_capital=20_000.0,
            leverage=3.0,
            alloc_per_trade=5_000.0,
            fee_rate=0.0001,
            use_funding=False,
            use_pyramiding=False,
        )
        return endpoint.backtest(data=data, param_ranges={"threshold": (0.2, 1.2, 0.1)})

    cached = run_once(True)
    uncached = run_once(False)
    cached_seconds = _timeit(lambda: run_once(True), repeats)
    uncached_seconds = _timeit(lambda: run_once(False), repeats)
    peak_memory_mb = _peak_memory_mb(lambda: run_once(True))
    equity_diff = float(abs(cached.equity.iloc[-1] - uncached.equity.iloc[-1]))
    objective_diff = float(abs(cached.metadata["walk_forward"]["best_trial"]["objective"] - uncached.metadata["walk_forward"]["best_trial"]["objective"]))
    return {
        "full_seconds": float(uncached_seconds),
        "prepared_seconds": float(cached_seconds),
        "speedup": float(uncached_seconds / cached_seconds) if cached_seconds > 0.0 else 0.0,
        "parity_passed": bool(equity_diff <= 1e-9 and objective_diff <= 1e-12),
        "peak_memory_mb": peak_memory_mb,
        "final_equity_diff": equity_diff,
        "objective_diff": objective_diff,
        "cache_metadata": cached.metadata["walk_forward"].get("prepared_scoring_cache", {}),
        "best_params": cached.metadata["walk_forward"].get("params", {}),
        "notes": "compares uncached vs prepared single-symbol native-vectorized WFO endpoint scoring",
    }


def _portfolio_wfo_benchmark(*, rows: int, trials: int, repeats: int) -> Dict:
    _quiet_optuna()
    data = _portfolio_data(rows, 2)

    def run_once(use_cache: bool):
        endpoint = QuantBTEndpoint.train_test_split(
            strategy_class=_portfolio_wfo_strategy,
            test_start=next(iter(data.values())).index[max(20, rows // 2)],
            target_mode="portfolio",
            portfolio_mode="longshort",
            optimization_mode="mode_1_decay",
            optimization_config={
                "scoring_backend": "endpoint",
                "use_prepared_scoring_cache": bool(use_cache),
                "top_is_fraction": 0.3,
            },
            optuna_trials=max(2, int(trials)),
            random_seed=7,
            initial_capital=100_000.0,
            leverage=4.0,
            alloc_per_trade=1_000.0,
            fee=0.0,
            use_funding=False,
        )
        return endpoint.backtest(data=data, param_ranges={"scale": (0.5, 1.5, 0.1)})

    cached = run_once(True)
    uncached = run_once(False)
    cached_seconds = _timeit(lambda: run_once(True), repeats)
    uncached_seconds = _timeit(lambda: run_once(False), repeats)
    peak_memory_mb = _peak_memory_mb(lambda: run_once(True))
    equity_diff = float(abs(cached.equity.iloc[-1] - uncached.equity.iloc[-1]))
    objective_diff = float(abs(cached.metadata["walk_forward"]["best_trial"]["objective"] - uncached.metadata["walk_forward"]["best_trial"]["objective"]))
    return {
        "full_seconds": float(uncached_seconds),
        "prepared_seconds": float(cached_seconds),
        "speedup": float(uncached_seconds / cached_seconds) if cached_seconds > 0.0 else 0.0,
        "parity_passed": bool(equity_diff <= 1e-9 and objective_diff <= 1e-12),
        "peak_memory_mb": peak_memory_mb,
        "final_equity_diff": equity_diff,
        "objective_diff": objective_diff,
        "cache_metadata": cached.metadata["walk_forward"].get("prepared_scoring_cache", {}),
        "notes": "compares uncached vs prepared portfolio WFO endpoint scoring",
    }


def _native_event_replay_benchmark(*, rows: int, symbols: int, order_count: int, repeats: int) -> Dict:
    idx, frames = _make_market_frames(int(rows), max(2, int(symbols)))
    symbols_list = list(frames.keys())
    orders = _make_orders(idx, int(order_count), len(symbols_list))
    closes = {symbol: frame["close"] for symbol, frame in frames.items()}
    highs = {symbol: frame["high"] for symbol, frame in frames.items()}
    lows = {symbol: frame["low"] for symbol, frame in frames.items()}
    backend = NativeEventBackend(
        NativeEventConfig(
            account=AccountConfig(initial_capital=100_000.0, leverage=5.0),
            execution=ExecutionConfig(slippage_bps=0.0),
            fee_rate=0.0,
            use_funding=False,
        )
    )
    market = backend.prepare_market_arrays(idx, closes=closes, highs=highs, lows=lows, symbols=symbols_list)
    compiled = backend.compile_orders(idx, orders=orders, symbols=symbols_list)

    def cold():
        return backend.run_orders(idx, orders, closes, highs=highs, lows=lows, symbols=symbols_list)

    def prepared():
        return backend.run_orders(
            idx,
            orders,
            closes,
            highs=highs,
            lows=lows,
            symbols=symbols_list,
            market_arrays=market,
            compiled_orders=compiled,
        )

    cold_result = cold()
    prepared_result = prepared()
    cold_seconds = _timeit(cold, repeats)
    prepared_seconds = _timeit(prepared, repeats)
    peak_memory_mb = _peak_memory_mb(prepared)
    equity_diff = float(np.max(np.abs(cold_result.equity.to_numpy() - prepared_result.equity.to_numpy())))
    positions_diff = float(np.max(np.abs(cold_result.positions.to_numpy() - prepared_result.positions.to_numpy())))
    return {
        "cold_seconds": float(cold_seconds),
        "prepared_seconds": float(prepared_seconds),
        "speedup": float(cold_seconds / prepared_seconds) if prepared_seconds > 0.0 else 0.0,
        "parity_passed": bool(equity_diff <= 1e-12 and positions_diff <= 1e-12),
        "peak_memory_mb": peak_memory_mb,
        "equity_diff": equity_diff,
        "positions_diff": positions_diff,
        "orders": int(len(orders)),
        "notes": "prepared replay reuses market arrays and compiled order arrays",
    }


def _arbitrage_package_sweep(*, rows: int, repeats: int) -> Dict:
    idx = pd.date_range("2023-01-01", periods=int(rows), freq="1h", tz="UTC")
    x = np.linspace(0.0, 8.0, len(idx))
    perp = pd.Series(100.0 + np.sin(x) * 2.0 + np.arange(len(idx)) * 0.01, index=idx)
    quarterly = pd.Series(perp.to_numpy() + 1.5 + np.cos(x) * 0.5, index=idx)
    closes = {"PERP": perp, "QUARTERLY": quarterly}
    signal = pd.Series(0.0, index=idx)
    signal.iloc[len(idx) // 4 : len(idx) // 2] = 1.0
    signal.iloc[-3:] = 0.0
    spec = BasisArbitrageSpec(
        arb_id="PHASE14B_BASIS",
        legs=(
            ArbitrageLeg("PERP", 1.0, role="perp", contract_type=ContractType.LINEAR, funding_enabled=True),
            ArbitrageLeg("QUARTERLY", -1.0, role="quarterly", contract_type=ContractType.LINEAR),
        ),
        hedge_policy=HedgePolicy(HedgePolicyKind.BASE_QTY_EQUAL, freeze_on_entry=True),
        sizing_policy=SizingPolicy(
            SizingPolicyKind.TARGET_NOTIONAL_TO_BASE_QTY,
            notional=10_000.0,
            reference_symbol="PERP",
        ),
        execution_policy=ArbExecutionPolicy(PackageExecutionKind.ATOMIC_ALL_OR_NONE),
    )
    account = AccountConfig(initial_capital=100_000.0, leverage=5.0)
    event = NativeEventBackend(NativeEventConfig(account=account, fee_rate=0.0001, use_funding=True))
    vector = NativeVectorizedBackend(NativeVectorizedConfig(account=account, fee_rate=0.0001, use_funding=True))
    funding = {"PERP": pd.Series(0.00005, index=idx), "QUARTERLY": 0.0}

    market = event.prepare_market_arrays(idx, closes=closes, highs=closes, lows=closes, funding_rate=funding, symbols=list(closes))

    def run_event():
        return event.run_basis_arbitrage(idx, spec, signal, closes, funding_rate=funding)

    def run_event_prepared():
        return event.run_basis_arbitrage(idx, spec, signal, closes, funding_rate=funding, market_arrays=market)

    def run_vector():
        return vector.run_basis_arbitrage(idx, spec, signal, closes, funding_rate=funding)

    event_result = run_event()
    prepared_result = run_event_prepared()
    vector_result = run_vector()
    audit = build_arbitrage_domain_audit(event_result)
    parity = compare_native_arbitrage_results(event_result, vector_result)
    event_seconds = _timeit(run_event, repeats)
    prepared_seconds = _timeit(run_event_prepared, repeats)
    peak_memory_mb = _peak_memory_mb(run_event_prepared)
    prepared_equity_diff = float(np.max(np.abs(event_result.equity.to_numpy() - prepared_result.equity.to_numpy())))
    return {
        "full_seconds": float(event_seconds),
        "prepared_seconds": float(prepared_seconds),
        "speedup": float(event_seconds / prepared_seconds) if prepared_seconds > 0.0 else 0.0,
        "parity_passed": bool(audit["passed"] and parity["passed"] and prepared_equity_diff <= 1e-10),
        "peak_memory_mb": peak_memory_mb,
        "audit_status": audit["status"],
        "parity_status": parity["status"],
        "max_equity_diff": parity["max_abs_equity_diff"],
        "prepared_equity_diff": prepared_equity_diff,
        "max_package_residual": parity["max_abs_package_residual"],
        "notes": "compares native-event arbitrage package cold vs prepared market-array replay; vectorized parity remains audited",
    }


def _report_level_benchmark(*, rows: int, symbols: int, repeats: int) -> Dict:
    def make_endpoint(report_level: str):
        return QuantBTEndpoint.portfolio(
            portfolio_mode="market_neutral",
            backend="native_portfolio",
            initial_capital=100_000.0,
            leverage=4.0,
            alloc_per_trade=1_000.0,
            fee_rate=0.0,
            use_funding=False,
            report_level=report_level,
        )

    full_endpoint = make_endpoint("full")
    minimal_endpoint = make_endpoint("minimal")
    data = _portfolio_data(rows, max(2, symbols))
    positions = _portfolio_positions(next(iter(data.values())).index, max(2, symbols))

    def run_full():
        return make_endpoint("full").backtest(data=data, positions=positions)

    def run_minimal():
        return make_endpoint("minimal").backtest(data=data, positions=positions)

    full_result = full_endpoint.backtest(data=data, positions=positions)
    minimal_result = minimal_endpoint.backtest(data=data, positions=positions)
    full_seconds = _timeit(run_full, repeats)
    minimal_seconds = _timeit(run_minimal, repeats)
    peak_memory_mb = _peak_memory_mb(run_full)
    equity_diff = float(np.max(np.abs(full_result.equity.to_numpy() - minimal_result.equity.to_numpy())))
    position_diff = float(np.max(np.abs(full_result.positions.to_numpy() - minimal_result.positions.to_numpy())))
    return {
        "full_seconds": float(full_seconds),
        "light_seconds": float(minimal_seconds),
        "speedup": float(full_seconds / minimal_seconds) if minimal_seconds > 0.0 else 0.0,
        "parity_passed": bool(equity_diff <= 1e-10 and position_diff <= 1e-12),
        "peak_memory_mb": peak_memory_mb,
        "equity_diff": equity_diff,
        "position_diff": position_diff,
        "full_reports": sorted(k for k in full_result.metadata if k.endswith("_report")),
        "minimal_reports_omitted": tuple(minimal_result.metadata.get("reports_omitted", ())),
        "notes": "compares native-portfolio report_level='full' vs 'minimal' construction with core accounting parity",
    }


def _legacy_report_heavy_vs_light(*, rows: int, symbols: int, repeats: int) -> Dict:
    endpoint = QuantBTEndpoint.portfolio(
        portfolio_mode="market_neutral",
        backend="native_portfolio",
        initial_capital=100_000.0,
        leverage=4.0,
        alloc_per_trade=1_000.0,
        fee_rate=0.0,
        use_funding=False,
    )
    data = _portfolio_data(rows, max(2, symbols))
    positions = _portfolio_positions(next(iter(data.values())).index, max(2, symbols))
    result = endpoint.backtest(data=data, positions=positions)

    def light():
        return {
            "final_equity": float(result.equity.iloc[-1]),
            "fees": float(result.fees.sum()),
            "funding": float(result.funding.sum()),
            "rows": int(len(result.equity)),
        }

    def heavy():
        return result.full_report(scope="full")

    light_summary = light()
    heavy_report = heavy()
    light_seconds = _timeit(light, repeats)
    heavy_seconds = _timeit(heavy, repeats)
    peak_memory_mb = _peak_memory_mb(heavy)
    return {
        "full_seconds": float(heavy_seconds),
        "light_seconds": float(light_seconds),
        "speedup": float(heavy_seconds / light_seconds) if light_seconds > 0.0 else 0.0,
        "parity_passed": bool(abs(light_summary["final_equity"] - heavy_report["final_equity"]) <= 1e-9),
        "peak_memory_mb": peak_memory_mb,
        "final_equity": light_summary["final_equity"],
        "notes": "legacy measurement of metrics/report export cost",
    }


def _single_wfo_strategy(data, params, train_index, test_index, fold):
    threshold = float(params["threshold"])
    frame = data.loc[: test_index[-1]]
    ret = frame["close"].pct_change().fillna(0.0)
    signal = np.where(ret > threshold / 10_000.0, 1.0, np.where(ret < -threshold / 10_000.0, -1.0, 0.0))
    return pd.Series(signal, index=frame.index).reindex(test_index).fillna(0.0)


def _portfolio_wfo_strategy(data, params, train_index, test_index, fold):
    scale = float(params["scale"])
    return pd.DataFrame({"SYM000": scale, "SYM001": -scale}, index=test_index)


def _single_frame(rows: int) -> pd.DataFrame:
    idx = pd.date_range("2021-01-01", periods=int(rows), freq="1h", tz="UTC")
    x = np.linspace(0.0, 14.0, len(idx))
    close = 100.0 + np.cumsum(np.sin(x) * 0.05 + np.cos(x / 2.0) * 0.03)
    return pd.DataFrame(
        {
            "open": close,
            "high": close * 1.002,
            "low": close * 0.998,
            "close": close,
            "volume": 1_000.0,
        },
        index=idx,
    )


def _portfolio_data(rows: int, symbols: int) -> Dict[str, pd.DataFrame]:
    idx = pd.date_range("2021-01-01", periods=int(rows), freq="1h", tz="UTC")
    out = {}
    for j in range(int(symbols)):
        x = np.linspace(0.0, 10.0 + j, len(idx))
        close = 100.0 + j * 3.0 + np.cumsum(np.sin(x) * 0.03 + 0.01)
        out[f"SYM{j:03d}"] = pd.DataFrame(
            {
                "open": close,
                "high": close * 1.002,
                "low": close * 0.998,
                "close": close,
                "volume": 1_000.0 + j,
            },
            index=idx,
        )
    return out


def _portfolio_positions(idx: pd.DatetimeIndex, symbols: int) -> Dict[str, pd.Series]:
    grid = np.arange(len(idx))
    out = {}
    for j in range(int(symbols)):
        active = np.where(((grid // (18 + j % 5)) + j) % 4 == 0, 1.0, 0.0)
        out[f"SYM{j:03d}"] = pd.Series(active * (1.0 if j % 2 == 0 else -1.0), index=idx)
    return out


def _stage_share(profile, stage_name: str) -> float:
    for stage in profile.stages:
        if stage.stage == stage_name:
            return float(stage.percent_of_profile)
    return 0.0


def _quiet_optuna() -> None:
    try:
        import optuna

        optuna.logging.set_verbosity(optuna.logging.WARNING)
    except Exception:
        return


def _largest_stage(profile) -> str:
    stage = max(profile.stages, key=lambda item: item.seconds)
    return f"{profile.backend}: `{stage.stage}` ({stage.percent_of_profile:.1f}%)"


def _next_targets(vectorized_profile, event_profile, portfolio_profile: Dict) -> List[str]:
    p = portfolio_profile["stages"]
    return [
        _largest_stage(vectorized_profile),
        _largest_stage(event_profile),
        "native_portfolio: `report_construction_estimate` ({:.1f}%)".format(
            float(p["report_construction_share_pct"])
        ),
        "Next step should be real workload profiling before considering Cython/C++; Phase 14C moved the main cache/report controls into opt-in APIs.",
    ]


def _cython_cpp_recommendation(pure_kernel_share_pct: float) -> str:
    if pure_kernel_share_pct >= 35.0:
        return (
            "Pure Numba kernel share is now large enough to investigate Cython/C++ "
            "after adding parity locks around the target kernel."
        )
    return (
        "Cython/C++ is not justified yet. The measured bottleneck remains in "
        "facade/report/preparation layers. Phase 14C added opt-in cache "
        "threading and report-level controls; larger real service-loop profiles "
        "should come before any Cython/C++ decision."
    )


def _timeit(fn, repeats: int) -> float:
    samples: List[float] = []
    for _ in range(max(1, int(repeats))):
        start = time.perf_counter()
        fn()
        samples.append(time.perf_counter() - start)
    return float(statistics.mean(samples))


def _peak_memory_mb(fn) -> float:
    gc.collect()
    tracemalloc.start()
    try:
        fn()
        _current, peak = tracemalloc.get_traced_memory()
        return float(peak / (1024 * 1024))
    finally:
        tracemalloc.stop()


def _json_default(value):
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    raise TypeError(f"{type(value).__name__} is not JSON serializable")


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rows", type=int, default=720)
    parser.add_argument("--symbols", type=int, default=4)
    parser.add_argument("--trials", type=int, default=8)
    parser.add_argument("--folds", type=int, default=1)
    parser.add_argument("--order-count", type=int, default=None)
    parser.add_argument("--repeats", type=int, default=2)
    parser.add_argument("--json-out", type=Path, default=PACKAGE_DIR / "benchmarks" / "phase14_service_loop.json")
    parser.add_argument("--md-out", type=Path, default=PACKAGE_DIR / "benchmarks" / "phase14_service_loop.md")
    args = parser.parse_args(argv)
    report = run_benchmark(
        rows=args.rows,
        symbols=args.symbols,
        trials=args.trials,
        folds=args.folds,
        order_count=args.order_count,
        repeats=args.repeats,
    )
    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.md_out.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.write_text(json.dumps(report, indent=2, sort_keys=True, default=_json_default) + "\n", encoding="utf-8")
    args.md_out.write_text(make_markdown(report), encoding="utf-8")
    print(make_markdown(report))
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
