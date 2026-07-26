#!/usr/bin/env python3
"""
Phase 31D intrabar execution benchmark and certification summary.
"""

from __future__ import annotations

import argparse
import gc
import json
import statistics
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, List

import numpy as np
import pandas as pd


PACKAGE_DIR = Path(__file__).resolve().parents[1]
PROJECT_DIR = PACKAGE_DIR.parent
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from quantbt import (  # noqa: E402
    AccountConfig,
    BacktestEngineV2,
    ExecutionContract,
    FillReplayTape,
    IntrabarIntentTape,
    OrderIntent,
    OrderSide,
    OrderType,
    prepare_market_tape,
    run_fill_replay_kernel,
    run_intrabar_kernel,
    run_intrabar_reference,
)
from quantbt.core.vectorized import _engine_units_v2  # noqa: E402


@dataclass
class Phase31BenchmarkRecord:
    route: str
    rows: int
    symbols: int
    fills_or_orders: int
    warmup_seconds: float
    runtime_seconds: float
    runtime_min_seconds: float
    runtime_max_seconds: float
    bars_per_second: float
    ratio_vs_close_target: float | None = None
    ratio_vs_intrabar_minimal: float | None = None
    speedup_vs_reference: float | None = None
    parity: str = "n/a"
    notes: str = ""


def run_benchmark(*, rows: int = 25_000, repeats: int = 3, seed: int = 31) -> Dict:
    df, intent = _make_intrabar_fixture(rows=rows, seed=seed)
    tape = prepare_market_tape(data=df, symbols=["BTC"], use_funding=False)
    account = AccountConfig(initial_capital=100_000.0, leverage=10.0)
    contract = ExecutionContract.intrabar_bracket(close_on_last_bar=True)

    records: list[Phase31BenchmarkRecord] = []
    close_stats = _measure(lambda: _run_close_target_kernel(tape, intent, account), repeats=repeats)
    records.append(_record("close_target_v2_pure_kernel", rows, 1, 0, close_stats, baseline=close_stats["best"], parity="baseline"))

    minimal_stats = _measure(
        lambda: run_intrabar_kernel(tape=tape, intent=intent, account=account, contract=contract, report_level="minimal"),
        repeats=repeats,
    )
    minimal_result = run_intrabar_kernel(tape=tape, intent=intent, account=account, contract=contract, report_level="minimal")
    records.append(
        _record(
            "intrabar_bracket_v1_minimal",
            rows,
            1,
            minimal_result.fill_count,
            minimal_stats,
            baseline=close_stats["best"],
            parity="oracle_checked_in_tests",
        )
    )

    audit_stats = _measure(
        lambda: run_intrabar_kernel(tape=tape, intent=intent, account=account, contract=contract, report_level="audit"),
        repeats=repeats,
    )
    audit_result = run_intrabar_kernel(tape=tape, intent=intent, account=account, contract=contract, report_level="audit")
    records.append(
        _record(
            "intrabar_bracket_v1_audit",
            rows,
            1,
            audit_result.fill_count,
            audit_stats,
            baseline=close_stats["best"],
            intrabar_minimal=minimal_stats["best"],
            parity="pass" if np.allclose(audit_result.equity, minimal_result.equity, atol=1e-9, rtol=0.0) else "fail",
            notes="two_pass_sparse_fills",
        )
    )

    reference_stats = _measure(
        lambda: run_intrabar_reference(tape=tape, intent=intent, account=account, contract=contract),
        repeats=max(1, min(2, repeats)),
    )
    records.append(
        _record(
            "intrabar_reference_python",
            rows,
            1,
            audit_result.fill_count,
            reference_stats,
            baseline=close_stats["best"],
            intrabar_minimal=minimal_stats["best"],
            parity="truth_model",
        )
    )

    fill_tape = FillReplayTape.from_frame(audit_result.fills_report)
    fill_replay_stats = _measure(
        lambda: run_fill_replay_kernel(tape=tape, fill_tape=fill_tape, account=account),
        repeats=repeats,
    )
    records.append(
        _record(
            "fill_replay_v1_kernel",
            rows,
            1,
            len(fill_tape.bar_index),
            fill_replay_stats,
            baseline=close_stats["best"],
            intrabar_minimal=minimal_stats["best"],
            parity="accounting_only",
        )
    )

    native_event_stats = _measure(lambda: _run_native_event_orders(df, audit_result.fills_report), repeats=max(1, min(2, repeats)))
    records.append(
        _record(
            "native_event_explicit_orders_facade",
            rows,
            1,
            int(len(audit_result.fills_report)),
            native_event_stats,
            baseline=close_stats["best"],
            intrabar_minimal=minimal_stats["best"],
            parity="speed_reference_not_semantic_claim",
            notes="full_facade_order_replay",
        )
    )

    reference = next(r for r in records if r.route == "intrabar_reference_python")
    for record in records:
        if record.route.startswith("intrabar_bracket_v1"):
            record.speedup_vs_reference = reference.runtime_seconds / record.runtime_seconds

    return {
        "rows": rows,
        "repeats": repeats,
        "seed": seed,
        "records": [asdict(record) for record in records],
        "summary": _summary(records),
    }


def make_markdown(report: Dict) -> str:
    lines = [
        "# Phase 31 Intrabar Benchmark",
        "",
        f"- Rows: `{report['rows']}`",
        f"- Repeats: `{report['repeats']}`",
        f"- Seed: `{report['seed']}`",
        "",
        "| Route | Runtime | Bars/s | Ratio vs close-target | Ratio vs intrabar minimal | Speedup vs Python oracle | Fills/orders | Parity | Notes |",
        "|---|---:|---:|---:|---:|---:|---:|---|---|",
    ]
    for record in report["records"]:
        lines.append(
            "| `{route}` | {runtime:.6f}s | {bps:,.0f} | {rclose} | {rmin} | {speedup} | {fills} | {parity} | {notes} |".format(
                route=record["route"],
                runtime=record["runtime_seconds"],
                bps=record["bars_per_second"],
                rclose=_fmt_ratio(record["ratio_vs_close_target"]),
                rmin=_fmt_ratio(record["ratio_vs_intrabar_minimal"]),
                speedup=_fmt_ratio(record["speedup_vs_reference"]),
                fills=record["fills_or_orders"],
                parity=record["parity"],
                notes=record["notes"] or "",
            )
        )
    lines.extend(
        [
            "",
            "## Summary",
            "",
            f"- Fast intrabar minimal vs Python oracle: `{_fmt_ratio(report['summary']['intrabar_minimal_speedup_vs_reference'])}` faster.",
            f"- Fast intrabar audit vs minimal: `{_fmt_ratio(report['summary']['intrabar_audit_ratio_vs_minimal'])}` runtime ratio.",
            f"- Fast intrabar minimal vs close-target pure kernel: `{_fmt_ratio(report['summary']['intrabar_minimal_ratio_vs_close_target'])}` runtime ratio.",
            "",
            "Interpretation: close-target remains the fastest narrow contract. The new intrabar kernel is the fast path for alpha logic that needs next-open entry, intrabar SL/TP/trailing, and audit fills without falling back to Python event loops.",
        ]
    )
    return "\n".join(lines) + "\n"


def _make_intrabar_fixture(*, rows: int, seed: int):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2020-01-01", periods=rows, freq="1h", tz="UTC")
    ret = rng.normal(0.0, 0.0015, size=rows)
    close = 100.0 * np.exp(np.cumsum(ret))
    open_ = np.r_[close[0], close[:-1] * (1.0 + rng.normal(0.0, 0.0002, size=rows - 1))]
    high = np.maximum(open_, close) * (1.0 + rng.uniform(0.0005, 0.006, size=rows))
    low = np.minimum(open_, close) * (1.0 - rng.uniform(0.0005, 0.006, size=rows))
    df = pd.DataFrame({"open": open_, "high": high, "low": low, "close": close, "volume": 100.0}, index=idx)
    entry_side = np.zeros(rows, dtype=np.int8)
    entry_size = np.zeros(rows, dtype=np.float64)
    entry_side[5::50] = 1
    entry_size[5::50] = 1.0
    entry_side[30::50] = -1
    entry_size[30::50] = 1.0
    stop = np.full(rows, 0.012, dtype=np.float64)
    tp = np.full(rows, 0.018, dtype=np.float64)
    trailing = np.full(rows, 0.010, dtype=np.float64)
    technical_exit = np.zeros(rows, dtype=np.bool_)
    technical_exit[45::50] = True
    intent = IntrabarIntentTape.from_arrays(
        entry_side=entry_side,
        entry_size=entry_size,
        stop_value=stop,
        take_profit_value=tp,
        trailing_value=trailing,
        technical_exit=technical_exit,
    )
    return df, intent


def _run_close_target_kernel(tape, intent, account):
    target = np.zeros((tape.n_bars, 1), dtype=np.float64)
    current = 0.0
    for i in range(tape.n_bars):
        if intent.entry_side[i] != 0 and intent.entry_size[i] > 0.0:
            current = float(intent.entry_side[i]) * float(intent.entry_size[i])
        target[i, 0] = current
    return _engine_units_v2(
        tape.n_bars,
        1,
        tape.highs,
        tape.lows,
        tape.closes,
        target,
        tape.funding_rates,
        tape.funding_event_mask,
        account.initial_capital,
        np.array([account.leverage], dtype=np.float64),
        account.maintenance_ratio,
        np.array([0.0], dtype=np.float64),
        np.array([1.0], dtype=np.float64),
        0.0,
        False,
    )[0][-1]


def _run_native_event_orders(df: pd.DataFrame, fills: pd.DataFrame):
    orders = []
    idx = df.index
    for row in fills.itertuples(index=False):
        bar = int(row.bar_index)
        side = OrderSide.BUY if int(row.side) > 0 else OrderSide.SELL
        orders.append(OrderIntent(idx[bar], "BTC", side, OrderType.MARKET, qty=float(row.qty)))
    engine = BacktestEngineV2(
        data=df,
        symbols=["BTC"],
        backend="native_event",
        orders=orders,
        account=AccountConfig(initial_capital=100_000.0, leverage=10.0),
        use_funding=False,
        fee_rate=0.0,
    )
    return engine.result.equity.iloc[-1]


def _measure(workload, *, repeats: int) -> Dict[str, float]:
    gc.collect()
    start = time.perf_counter()
    workload()
    warmup = time.perf_counter() - start
    runtimes = []
    for _ in range(max(1, repeats)):
        gc.collect()
        start = time.perf_counter()
        workload()
        runtimes.append(time.perf_counter() - start)
    return {
        "best": float(min(runtimes)),
        "worst": float(max(runtimes)),
        "median": float(statistics.median(runtimes)),
        "warmup": float(warmup),
    }


def _record(route, rows, symbols, fills, stats, *, baseline, intrabar_minimal=None, parity="n/a", notes=""):
    runtime = stats["best"]
    return Phase31BenchmarkRecord(
        route=route,
        rows=rows,
        symbols=symbols,
        fills_or_orders=int(fills),
        warmup_seconds=float(stats["warmup"]),
        runtime_seconds=float(runtime),
        runtime_min_seconds=float(stats["best"]),
        runtime_max_seconds=float(stats["worst"]),
        bars_per_second=float(rows / runtime) if runtime > 0 else float("inf"),
        ratio_vs_close_target=float(runtime / baseline) if baseline and runtime else None,
        ratio_vs_intrabar_minimal=float(runtime / intrabar_minimal) if intrabar_minimal and runtime else None,
        parity=parity,
        notes=notes,
    )


def _summary(records: List[Phase31BenchmarkRecord]) -> Dict:
    lookup = {record.route: record for record in records}
    minimal = lookup["intrabar_bracket_v1_minimal"]
    audit = lookup["intrabar_bracket_v1_audit"]
    reference = lookup["intrabar_reference_python"]
    close_target = lookup["close_target_v2_pure_kernel"]
    return {
        "intrabar_minimal_speedup_vs_reference": reference.runtime_seconds / minimal.runtime_seconds,
        "intrabar_audit_ratio_vs_minimal": audit.runtime_seconds / minimal.runtime_seconds,
        "intrabar_minimal_ratio_vs_close_target": minimal.runtime_seconds / close_target.runtime_seconds,
    }


def _fmt_ratio(value) -> str:
    if value is None:
        return "-"
    return f"{float(value):.2f}x"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Run Phase 31 intrabar benchmark.")
    parser.add_argument("--rows", type=int, default=25_000)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--seed", type=int, default=31)
    parser.add_argument("--json-out", type=Path, default=PACKAGE_DIR / "benchmarks" / "phase31_intrabar_benchmark.json")
    parser.add_argument("--md-out", type=Path, default=PACKAGE_DIR / "benchmarks" / "phase31_intrabar_benchmark.md")
    args = parser.parse_args(argv)

    report = run_benchmark(rows=args.rows, repeats=args.repeats, seed=args.seed)
    args.json_out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    args.md_out.write_text(make_markdown(report), encoding="utf-8")
    print(make_markdown(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
