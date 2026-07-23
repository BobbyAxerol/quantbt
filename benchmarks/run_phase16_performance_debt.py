#!/usr/bin/env python3
"""
Phase 16 performance-debt closure benchmark.

This runner measures the remaining facade/service-loop overhead after Phase
13/14 and verifies that prepared service contexts do not change accounting.
It is intentionally focused on pandas normalization/report construction, not on
changing domain kernels.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import tracemalloc
from pathlib import Path
from typing import Callable, Dict, List

import numpy as np
import pandas as pd

PACKAGE_DIR = Path(__file__).resolve().parents[1]
PROJECT_DIR = PACKAGE_DIR.parent
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from quantbt import QuantBTEndpoint  # noqa: E402
from quantbt.benchmarks.run_phase14_service_loop import run_benchmark as run_phase14_benchmark  # noqa: E402


def run_phase16_benchmark(
    *,
    rows: int = 1_440,
    symbols: int = 6,
    replays: int = 8,
    repeats: int = 2,
    include_large_wfo: bool = True,
) -> Dict:
    single = _single_service_context_benchmark(rows=rows, replays=replays, repeats=repeats)
    portfolio = _portfolio_service_context_benchmark(rows=rows, symbols=symbols, replays=replays, repeats=repeats)
    report = _portfolio_report_benchmark(rows=rows, symbols=symbols, repeats=repeats)
    large_wfo = (
        run_phase14_benchmark(
            rows=max(rows, 1_440),
            symbols=max(symbols, 6),
            trials=max(8, replays),
            order_count=max(240, rows // 4),
            repeats=max(1, repeats),
        )
        if include_large_wfo
        else {"status": "skipped", "reason": "include_large_wfo=False"}
    )
    parity = {
        "single_service_context": bool(single["parity_passed"]),
        "portfolio_service_context": bool(portfolio["parity_passed"]),
        "portfolio_report_levels": bool(report["parity_passed"]),
        "large_wfo_service_loop": bool(large_wfo.get("status") == "pass") if include_large_wfo else True,
    }
    status = "pass" if all(parity.values()) else "fail"
    return {
        "phase": "16",
        "status": status,
        "rows": int(rows),
        "symbols": int(symbols),
        "replays": int(replays),
        "repeats": int(repeats),
        "service_context": {
            "single_signal_notional": single,
            "native_portfolio": portfolio,
        },
        "report_construction": report,
        "large_wfo_service_loop": _compact_phase14(large_wfo),
        "parity": parity,
        "cython_cpp_recommendation": _cython_cpp_recommendation(large_wfo),
        "closed_debt": [
            "facade-level repeated pandas market normalization can now be avoided with endpoint.prepare_service_context(...)",
            "report construction has an explicit full/minimal benchmark and parity guard",
            "larger WFO/service-loop benchmark is archived before any Cython/C++ decision",
        ],
        "remaining_notes": [
            "normal endpoint.backtest(...) remains backward-compatible and still normalizes defensively per call",
            "prepared service context is opt-in and currently covers native_vectorized signal_notional plus native_portfolio",
            "Cython/C++ should wait until pure kernels, not pandas/report facades, dominate measured runtime",
        ],
    }


def make_markdown(report: Dict) -> str:
    single = report["service_context"]["single_signal_notional"]
    portfolio = report["service_context"]["native_portfolio"]
    rpt = report["report_construction"]
    lines = [
        "# Phase 16 Performance Debt Closure",
        "",
        f"Status: **{report['status']}**",
        "",
        "## Prepared Service Context",
        "",
        "| workload | normal seconds | prepared seconds | speedup | peak MB | parity |",
        "| --- | ---: | ---: | ---: | ---: | --- |",
        _row("single signal_notional", single),
        _row("native portfolio", portfolio),
        "",
        "## Report Construction",
        "",
        "| workload | full seconds | minimal seconds | speedup | parity |",
        "| --- | ---: | ---: | ---: | --- |",
        "| native portfolio reports | `{full_seconds:.6f}` | `{minimal_seconds:.6f}` | `{speedup:.3f}x` | `{parity}` |".format(
            full_seconds=float(rpt["full_seconds"]),
            minimal_seconds=float(rpt["minimal_seconds"]),
            speedup=float(rpt["speedup"]),
            parity=bool(rpt["parity_passed"]),
        ),
        "",
        "## Large WFO / Service Loop",
        "",
        f"- Status: `{report['large_wfo_service_loop'].get('status')}`",
        f"- Rows: `{report['large_wfo_service_loop'].get('rows')}`",
        f"- Symbols: `{report['large_wfo_service_loop'].get('symbols')}`",
        f"- Cython/C++ recommendation: {report['cython_cpp_recommendation']}",
        "",
        "## Closed Debt",
        "",
    ]
    for item in report["closed_debt"]:
        lines.append(f"- {item}")
    lines.extend(["", "## Remaining Notes", ""])
    for item in report["remaining_notes"]:
        lines.append(f"- {item}")
    lines.append("")
    return "\n".join(lines)


def _row(label: str, item: Dict) -> str:
    return "| {label} | `{normal:.6f}` | `{prepared:.6f}` | `{speedup:.3f}x` | `{peak:.3f}` | `{parity}` |".format(
        label=label,
        normal=float(item["normal_seconds"]),
        prepared=float(item["prepared_seconds"]),
        speedup=float(item["speedup"]),
        peak=float(item["peak_memory_mb"]),
        parity=bool(item["parity_passed"]),
    )


def _single_service_context_benchmark(*, rows: int, replays: int, repeats: int) -> Dict:
    data = _single_frame(rows)
    signals = _single_signals(data.index, replays)

    normal_endpoint = _single_endpoint()
    prepared_endpoint = _single_endpoint()
    context = prepared_endpoint.prepare_service_context(data=data, symbols=["BTC"])

    normal_results = _run_single_replays(normal_endpoint, data, signals)
    prepared_results = _run_single_context_replays(context, signals)
    normal_seconds = _timeit(lambda: _run_single_replays(normal_endpoint, data, signals), repeats)
    prepared_seconds = _timeit(lambda: _run_single_context_replays(context, signals), repeats)
    peak = _peak_memory_mb(lambda: _run_single_context_replays(context, signals))
    equity_diff = max(
        float(abs(normal.equity.iloc[-1] - prepared.equity.iloc[-1]))
        for normal, prepared in zip(normal_results, prepared_results)
    )
    position_diff = max(
        float(np.max(np.abs(normal.positions.to_numpy() - prepared.positions.to_numpy())))
        for normal, prepared in zip(normal_results, prepared_results)
    )
    return {
        "normal_seconds": float(normal_seconds),
        "prepared_seconds": float(prepared_seconds),
        "speedup": float(normal_seconds / prepared_seconds) if prepared_seconds > 0.0 else 0.0,
        "peak_memory_mb": float(peak),
        "parity_passed": bool(equity_diff <= 1e-9 and position_diff <= 1e-12),
        "final_equity_max_abs_diff": equity_diff,
        "position_max_abs_diff": position_diff,
        "context_metadata": context.metadata,
    }


def _portfolio_service_context_benchmark(*, rows: int, symbols: int, replays: int, repeats: int) -> Dict:
    data, positions_list, symbol_list = _portfolio_inputs(rows, symbols, replays)
    normal_endpoint = _portfolio_endpoint(symbol_list, report_level="minimal")
    prepared_endpoint = _portfolio_endpoint(symbol_list, report_level="minimal")
    context = prepared_endpoint.prepare_service_context(data=data, symbols=symbol_list)

    normal_results = _run_portfolio_replays(normal_endpoint, data, positions_list, symbol_list)
    prepared_results = _run_portfolio_context_replays(context, positions_list)
    normal_seconds = _timeit(lambda: _run_portfolio_replays(normal_endpoint, data, positions_list, symbol_list), repeats)
    prepared_seconds = _timeit(lambda: _run_portfolio_context_replays(context, positions_list), repeats)
    peak = _peak_memory_mb(lambda: _run_portfolio_context_replays(context, positions_list))
    equity_diff = max(
        float(abs(normal.equity.iloc[-1] - prepared.equity.iloc[-1]))
        for normal, prepared in zip(normal_results, prepared_results)
    )
    margin_diff = max(
        float(np.max(np.abs(normal.margin.to_numpy() - prepared.margin.to_numpy())))
        for normal, prepared in zip(normal_results, prepared_results)
    )
    return {
        "normal_seconds": float(normal_seconds),
        "prepared_seconds": float(prepared_seconds),
        "speedup": float(normal_seconds / prepared_seconds) if prepared_seconds > 0.0 else 0.0,
        "peak_memory_mb": float(peak),
        "parity_passed": bool(equity_diff <= 1e-8 and margin_diff <= 1e-8),
        "final_equity_max_abs_diff": equity_diff,
        "margin_max_abs_diff": margin_diff,
        "context_metadata": context.metadata,
    }


def _portfolio_report_benchmark(*, rows: int, symbols: int, repeats: int) -> Dict:
    data, positions_list, symbol_list = _portfolio_inputs(rows, symbols, 1)
    full_endpoint = _portfolio_endpoint(symbol_list, report_level="full")
    minimal_endpoint = _portfolio_endpoint(symbol_list, report_level="minimal")
    full = full_endpoint.backtest(data=data, positions=positions_list[0], symbols=symbol_list)
    minimal = minimal_endpoint.backtest(data=data, positions=positions_list[0], symbols=symbol_list)
    full_seconds = _timeit(lambda: full_endpoint.backtest(data=data, positions=positions_list[0], symbols=symbol_list), repeats)
    minimal_seconds = _timeit(lambda: minimal_endpoint.backtest(data=data, positions=positions_list[0], symbols=symbol_list), repeats)
    equity_diff = float(np.max(np.abs(full.equity.to_numpy() - minimal.equity.to_numpy())))
    positions_diff = float(np.max(np.abs(full.positions.to_numpy() - minimal.positions.to_numpy())))
    return {
        "full_seconds": float(full_seconds),
        "minimal_seconds": float(minimal_seconds),
        "speedup": float(full_seconds / minimal_seconds) if minimal_seconds > 0.0 else 0.0,
        "parity_passed": bool(equity_diff <= 1e-8 and positions_diff <= 1e-12),
        "equity_max_abs_diff": equity_diff,
        "positions_max_abs_diff": positions_diff,
    }


def _single_endpoint() -> QuantBTEndpoint:
    return QuantBTEndpoint.signal_notional(
        initial_capital=20_000.0,
        leverage=4.0,
        alloc_per_trade=5_000.0,
        fee_rate=0.0002,
        use_funding=False,
        slippage=0.0001,
        use_pyramiding=True,
    )


def _portfolio_endpoint(symbols: List[str], *, report_level: str) -> QuantBTEndpoint:
    return QuantBTEndpoint.portfolio(
        portfolio_mode="market_neutral",
        backend="native_portfolio",
        hedge_type="signal_notional",
        initial_capital=100_000.0,
        leverage=4.0,
        alloc_per_trade={symbol: 5_000.0 for symbol in symbols},
        fee=0.0004,
        use_funding=False,
        report_level=report_level,
    )


def _single_frame(rows: int) -> pd.DataFrame:
    idx = pd.date_range("2021-01-01", periods=int(rows), freq="1h", tz="UTC")
    close = 100.0 + np.cumsum(np.sin(np.linspace(0.0, 32.0, len(idx))) * 0.03 + 0.002)
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


def _single_signals(idx: pd.DatetimeIndex, replays: int) -> List[pd.Series]:
    out = []
    base = np.linspace(0.0, 20.0, len(idx))
    for replay in range(int(replays)):
        out.append(pd.Series(np.sign(np.sin(base + replay * 0.3)), index=idx))
    return out


def _portfolio_inputs(rows: int, symbols: int, replays: int):
    idx = pd.date_range("2021-01-01", periods=int(rows), freq="1h", tz="UTC")
    symbol_list = [f"S{i:02d}" for i in range(int(symbols))]
    data = {}
    for j, symbol in enumerate(symbol_list):
        close = 100.0 + j * 5.0 + np.cumsum(np.sin(np.linspace(0.0, 18.0, len(idx)) + j) * 0.02 + 0.001)
        data[symbol] = pd.DataFrame(
            {
                "open": close,
                "high": close * 1.002,
                "low": close * 0.998,
                "close": close,
                "volume": 1_000.0,
            },
            index=idx,
        )
    positions = []
    base = np.linspace(0.0, 16.0, len(idx))
    for replay in range(int(replays)):
        matrix = {
            symbol: np.sign(np.sin(base + replay * 0.2 + j * 0.5))
            for j, symbol in enumerate(symbol_list)
        }
        positions.append(pd.DataFrame(matrix, index=idx))
    return data, positions, symbol_list


def _run_single_replays(endpoint: QuantBTEndpoint, data: pd.DataFrame, signals: List[pd.Series]):
    return [endpoint.backtest(data=data, signal=signal, symbols=["BTC"]) for signal in signals]


def _run_single_context_replays(context, signals: List[pd.Series]):
    return [context.backtest(signal=signal) for signal in signals]


def _run_portfolio_replays(endpoint: QuantBTEndpoint, data, positions_list, symbols):
    return [endpoint.backtest(data=data, positions=positions, symbols=symbols) for positions in positions_list]


def _run_portfolio_context_replays(context, positions_list):
    return [context.backtest(positions=positions) for positions in positions_list]


def _timeit(func: Callable[[], object], repeats: int) -> float:
    values = []
    for _ in range(max(1, int(repeats))):
        start = time.perf_counter()
        func()
        values.append(time.perf_counter() - start)
    return float(min(values))


def _peak_memory_mb(func: Callable[[], object]) -> float:
    tracemalloc.start()
    func()
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return float(peak / (1024 * 1024))


def _compact_phase14(report: Dict) -> Dict:
    if report.get("status") == "skipped":
        return report
    return {
        "status": report.get("status"),
        "rows": report.get("rows"),
        "symbols": report.get("symbols"),
        "trials": report.get("trials"),
        "order_count": report.get("order_count"),
        "parity": report.get("parity"),
        "cython_cpp_recommendation": report.get("cython_cpp_recommendation"),
        "next_optimization_targets": report.get("next_optimization_targets"),
    }


def _cython_cpp_recommendation(large_wfo: Dict) -> str:
    if large_wfo.get("status") != "pass":
        return "defer; benchmark did not pass all parity/status gates"
    text = str(large_wfo.get("cython_cpp_recommendation", "")).lower()
    if "not justified" in text or "not yet" in text:
        return "not justified yet; facade/report overhead remains the larger measured bucket"
    return large_wfo.get("cython_cpp_recommendation", "defer until pure kernel bottleneck is proven")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rows", type=int, default=1_440)
    parser.add_argument("--symbols", type=int, default=6)
    parser.add_argument("--replays", type=int, default=8)
    parser.add_argument("--repeats", type=int, default=2)
    parser.add_argument("--skip-large-wfo", action="store_true")
    parser.add_argument("--output-json", default=str(PACKAGE_DIR / "benchmarks" / "phase16_performance_debt.json"))
    parser.add_argument("--output-md", default=str(PACKAGE_DIR / "benchmarks" / "phase16_performance_debt.md"))
    args = parser.parse_args()
    report = run_phase16_benchmark(
        rows=args.rows,
        symbols=args.symbols,
        replays=args.replays,
        repeats=args.repeats,
        include_large_wfo=not args.skip_large_wfo,
    )
    json_path = Path(args.output_json)
    md_path = Path(args.output_md)
    json_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    md_path.write_text(make_markdown(report), encoding="utf-8")
    print(json.dumps(report, indent=2, default=str))


if __name__ == "__main__":
    main()
