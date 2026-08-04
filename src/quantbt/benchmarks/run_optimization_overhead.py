#!/usr/bin/env python3
"""Phase 32C optimization overhead and prepared-evaluator benchmark."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time

import numpy as np
import pandas as pd

PACKAGE_DIR = Path(__file__).resolve().parents[1]
PROJECT_DIR = PACKAGE_DIR.parent
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from quantbt import (  # noqa: E402
    GenericEndpointEvaluator,
    IntrabarIntentTape,
    ObjectiveResult,
    OptimizationConfig,
    OptunaOptimizer,
    PreparedSignalEvaluator,
    QuantBTEndpoint,
    SamplerConfig,
)


def run_benchmark(rows: int = 360, trials: int = 24, loops: int = 24) -> dict:
    df = _frame(rows)
    optimizer_seconds = _optimizer_overhead(trials)
    normal_seconds, prepared_seconds, signal_diff = _signal_replay_benchmark(df, loops)
    first_intrabar, warm_intrabar, intrabar_diff = _intrabar_compile_benchmark(df)
    status = "pass" if signal_diff <= 1e-9 and intrabar_diff <= 1e-9 else "fail"
    return {
        "status": status,
        "rows": int(rows),
        "trials": int(trials),
        "loops": int(loops),
        "optimizer_overhead_seconds": float(optimizer_seconds),
        "optimizer_overhead_per_trial_seconds": float(optimizer_seconds / max(1, trials)),
        "normal_signal_replay_seconds": float(normal_seconds),
        "prepared_signal_replay_seconds": float(prepared_seconds),
        "prepared_signal_speedup": float(normal_seconds / prepared_seconds) if prepared_seconds > 0 else 0.0,
        "signal_final_equity_diff": float(signal_diff),
        "intrabar_first_run_seconds": float(first_intrabar),
        "intrabar_warm_run_seconds": float(warm_intrabar),
        "intrabar_compile_to_warm_ratio": float(first_intrabar / warm_intrabar) if warm_intrabar > 0 else 0.0,
        "intrabar_final_equity_diff": float(intrabar_diff),
    }


def make_markdown(report: dict) -> str:
    return "\n".join(
        [
            "# Phase 32C Optimization Overhead Benchmark",
            "",
            f"Status: **{report['status']}**",
            "",
            "| Measurement | Value |",
            "|---|---:|",
            f"| Optimizer overhead | `{report['optimizer_overhead_seconds']:.6f}s` |",
            f"| Optimizer overhead / trial | `{report['optimizer_overhead_per_trial_seconds']:.6f}s` |",
            f"| Normal signal replays | `{report['normal_signal_replay_seconds']:.6f}s` |",
            f"| Prepared signal replays | `{report['prepared_signal_replay_seconds']:.6f}s` |",
            f"| Prepared signal speedup | `{report['prepared_signal_speedup']:.3f}x` |",
            f"| Intrabar first run | `{report['intrabar_first_run_seconds']:.6f}s` |",
            f"| Intrabar warm run | `{report['intrabar_warm_run_seconds']:.6f}s` |",
            f"| Intrabar first/warm ratio | `{report['intrabar_compile_to_warm_ratio']:.3f}x` |",
            "",
            "Parity checks:",
            "",
            f"- Signal final equity diff: `{report['signal_final_equity_diff']}`",
            f"- Intrabar final equity diff: `{report['intrabar_final_equity_diff']}`",
            "",
            "This benchmark measures facade/optimizer overhead, not strategy quality.",
        ]
    ) + "\n"


def _optimizer_overhead(trials: int) -> float:
    evaluator = GenericEndpointEvaluator(
        build_run_inputs=lambda params: {"value": float(params["x"])},
        run_func=lambda value: value,
        objective_builder=lambda result, params: ObjectiveResult.scalar(float(result), metrics={"score": float(result)}),
    )
    optimizer = OptunaOptimizer(
        evaluator=evaluator,
        config=OptimizationConfig(
            study_name=f"phase32c_overhead_{time.time_ns()}",
            n_trials=int(trials),
            seed=42,
            show_progress_bar=False,
            duplicate_policy="allow",
        ),
        sampler_config=SamplerConfig(name="random"),
    )
    start = time.perf_counter()
    optimizer.optimize(param_ranges={"x": (0.0, 1.0)})
    return time.perf_counter() - start


def _signal_replay_benchmark(df: pd.DataFrame, loops: int):
    endpoint = QuantBTEndpoint.signal_notional(
        backend="native_vectorized",
        initial_capital=20_000.0,
        leverage=5.0,
        alloc_per_trade=1_000.0,
        fee_rate=0.0,
        use_funding=False,
    )
    signal = pd.Series(np.where(df["close"].diff().fillna(0.0) > 0.0, 1.0, 0.0), index=df.index)
    normal = endpoint.backtest(data=df, signal=signal, symbols=["BTC"])
    prepared = endpoint.prepare_service_context(data=df, symbols=["BTC"])
    prepared_result = prepared.backtest(signal=signal)
    diff = abs(float(normal.equity.iloc[-1]) - float(prepared_result.equity.iloc[-1]))

    start = time.perf_counter()
    for _ in range(int(loops)):
        endpoint.backtest(data=df, signal=signal, symbols=["BTC"])
    normal_seconds = time.perf_counter() - start

    evaluator = PreparedSignalEvaluator(
        prepared_context=prepared,
        strategy_func=lambda params: signal,
        objective_builder=lambda result, params: ObjectiveResult.scalar(float(result.equity.iloc[-1])),
    )
    start = time.perf_counter()
    for _ in range(int(loops)):
        evaluator.evaluate({})
    prepared_seconds = time.perf_counter() - start
    return normal_seconds, prepared_seconds, diff


def _intrabar_compile_benchmark(df: pd.DataFrame):
    endpoint = QuantBTEndpoint.intrabar_bracket(
        initial_capital=20_000.0,
        leverage=5.0,
        fee_rate=0.0,
        slippage_bps=0.0,
        use_funding=False,
        report_level="minimal",
    )
    runner = endpoint.prepare_intrabar(data=df, symbols=["BTC"])
    entry = np.zeros(len(df))
    entry[0] = 1.0
    intent = IntrabarIntentTape.from_arrays(entry_side=entry, entry_size=np.abs(entry))

    start = time.perf_counter()
    first = runner.run(intent, report_level="minimal")
    first_seconds = time.perf_counter() - start
    start = time.perf_counter()
    warm = runner.run(intent, report_level="minimal")
    warm_seconds = time.perf_counter() - start
    diff = abs(float(first.equity.iloc[-1]) - float(warm.equity.iloc[-1]))
    return first_seconds, warm_seconds, diff


def _frame(rows: int) -> pd.DataFrame:
    idx = pd.date_range("2024-01-01", periods=int(rows), freq="1h", tz="UTC")
    x = np.linspace(0.0, 16.0, len(idx))
    close = 100.0 + np.sin(x) * 2.0 + np.arange(len(idx)) * 0.01
    return pd.DataFrame(
        {
            "open": close,
            "high": close * 1.01,
            "low": close * 0.99,
            "close": close,
            "volume": 1_000.0,
        },
        index=idx,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rows", type=int, default=360)
    parser.add_argument("--trials", type=int, default=24)
    parser.add_argument("--loops", type=int, default=24)
    parser.add_argument("--json", type=Path, default=PACKAGE_DIR / "benchmarks" / "results" / "optimization_overhead.json")
    parser.add_argument("--markdown", type=Path, default=PACKAGE_DIR / "benchmarks" / "results" / "optimization_overhead.md")
    args = parser.parse_args()
    report = run_benchmark(rows=args.rows, trials=args.trials, loops=args.loops)
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    args.markdown.write_text(make_markdown(report))
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
