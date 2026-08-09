#!/usr/bin/env python3
"""Phase 49B apples-to-apples WFO performance and parity benchmark."""

from __future__ import annotations

import argparse
import gc
import json
import os
from pathlib import Path
import resource
import subprocess
import sys
import threading
import time
from typing import Any, Dict

import numpy as np
import pandas as pd

SOURCE_ROOT = Path(__file__).resolve().parents[2]
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from quantbt import QuantBTEndpoint


def _frame(rows: int, *, scale: float = 1.0) -> pd.DataFrame:
    idx = pd.date_range("2020-01-01", periods=rows, freq="1D", tz="UTC")
    phase = np.arange(rows, dtype=np.float64)
    close = scale * (100.0 + phase * 0.015 + 1.7 * np.sin(phase / 19.0))
    return pd.DataFrame(
        {
            "open": close,
            "high": close * 1.002,
            "low": close * 0.998,
            "close": close,
            "volume": 1_000.0 + phase,
        },
        index=idx,
    )


def _optimization_flags(optimized: bool) -> Dict[str, Any]:
    return {
        "use_prepared_scoring_cache": True,
        "use_prepared_wfo_context": bool(optimized),
        "use_scalar_trial_scoring": bool(optimized),
        "compact_trial_ledger": bool(optimized),
        "profile_walkforward": True,
    }


def _run_portfolio(rows: int, trials: int, optimized: bool):
    data = {"BTC": _frame(rows), "ETH": _frame(rows, scale=0.55)}

    def strategy(data, params, train_index, test_index, fold):
        del data, train_index, fold
        scale = float(params["scale"])
        return pd.DataFrame({"BTC": scale, "ETH": -scale}, index=test_index)

    endpoint = QuantBTEndpoint.train_test_split(
        strategy_class=strategy,
        test_start=data["BTC"].index[int(rows * 0.70)],
        target_mode="portfolio",
        portfolio_mode="longshort",
        optimization_mode="mode_1_decay",
        optimization_config={
            **_optimization_flags(optimized),
            "scoring_backend": "endpoint",
            "top_is_fraction": 0.25,
        },
        optuna_trials=trials,
        random_seed=123,
        initial_capital=100_000.0,
        leverage=5.0,
        alloc_per_trade=5_000.0,
        fee_rate=0.0002,
        use_funding=False,
    )
    return endpoint.backtest(data=data, param_ranges={"scale": (0.25, 2.0, 0.025)})


def _run_single_per_fold(rows: int, trials: int, optimized: bool):
    data = _frame(rows)
    first_oos = data.index[max(365, int(rows * 0.52))]

    def strategy(data, params, train_index, test_index, fold):
        del data, train_index, fold
        period = float(params["period"])
        phase = np.arange(len(test_index), dtype=np.float64)
        return pd.Series(np.sign(np.sin(phase / period)), index=test_index)

    endpoint = QuantBTEndpoint.walk_forward(
        strategy_class=strategy,
        split_mode=first_oos,
        split_frequency="quarterly",
        window_mode="rolling",
        train_window="365D",
        target_mode="signal_notional",
        optimization_mode="mode_4_is_only_robust",
        optimization_schedule="per_fold_causal",
        optimization_config={
            **_optimization_flags(optimized),
            "scoring_backend": "endpoint",
            "candidate_selection_metric": "is_only_robust",
            "top_is_fraction": 0.25,
            "flat_eps": 0.3,
            "flat_min_samples": 2,
            "is_subperiods": 3,
        },
        optuna_trials=trials,
        random_seed=321,
        initial_capital=20_000.0,
        leverage=3.0,
        alloc_per_trade=2_000.0,
        fee_rate=0.0002,
        use_funding=False,
    )
    return endpoint.backtest(data=data, symbols=["BTC"], param_ranges={"period": (3.0, 25.0, 0.5)})


def _run(scenario: str, rows: int, trials: int, optimized: bool):
    if scenario == "portfolio_global":
        return _run_portfolio(rows, trials, optimized)
    if scenario == "single_per_fold_causal":
        return _run_single_per_fold(rows, trials, optimized)
    raise ValueError(f"unknown scenario={scenario!r}")


def _timed(scenario: str, rows: int, trials: int, optimized: bool):
    started = time.perf_counter()
    result = _run(scenario, rows, trials, optimized)
    return time.perf_counter() - started, result


def _parity(optimized, reference) -> Dict[str, Any]:
    opt = optimized.metadata["walk_forward"]
    ref = reference.metadata["walk_forward"]
    equity_diff = float(np.max(np.abs(optimized.equity.to_numpy() - reference.equity.to_numpy())))
    position_diff = float(np.max(np.abs(optimized.positions.to_numpy() - reference.positions.to_numpy())))
    trial_equal = bool(opt["trial_table"].equals(ref["trial_table"]))
    candidate_equal = bool(opt["candidate_table"].equals(ref["candidate_table"]))
    best_equal = opt["best_trial"] == ref["best_trial"]
    params_equal = opt["params"] == ref["params"]
    passed = (
        equity_diff == 0.0
        and position_diff == 0.0
        and trial_equal
        and candidate_equal
        and best_equal
        and params_equal
    )
    return {
        "passed": bool(passed),
        "equity_max_abs_diff": equity_diff,
        "position_max_abs_diff": position_diff,
        "trial_table_equal": trial_equal,
        "candidate_table_equal": candidate_equal,
        "best_trial_equal": bool(best_equal),
        "selected_params_equal": bool(params_equal),
    }


def _rss_worker(scenario: str, rows: int, trials: int, optimized: bool) -> Dict[str, Any]:
    import optuna

    optuna.logging.set_verbosity(optuna.logging.WARNING)
    _run(scenario, rows, min(3, trials), optimized)
    gc.collect()
    baseline_rss = _current_rss_mb()
    stop = threading.Event()
    samples = [baseline_rss]

    def sample_rss() -> None:
        while not stop.wait(0.002):
            samples.append(_current_rss_mb())

    sampler = threading.Thread(target=sample_rss, daemon=True)
    sampler.start()
    seconds, result = _timed(scenario, rows, trials, optimized)
    stop.set()
    sampler.join()
    samples.append(_current_rss_mb())
    wf = result.metadata["walk_forward"]
    return {
        "seconds": float(seconds),
        "process_peak_rss_mb": float(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0),
        "warm_baseline_rss_mb": float(baseline_rss),
        "workload_peak_rss_mb": float(max(samples)),
        "workload_incremental_rss_mb": float(max(samples) - baseline_rss),
        "final_equity": float(result.equity.iloc[-1]),
        "trial_rows": int(wf["n_optuna_trial_rows"]),
    }


def _current_rss_mb() -> float:
    status = Path("/proc/self/status").read_text()
    for line in status.splitlines():
        if line.startswith("VmRSS:"):
            return float(line.split()[1]) / 1024.0
    raise RuntimeError("/proc/self/status does not contain VmRSS")


def _isolated_rss(scenario: str, rows: int, trials: int, optimized: bool) -> Dict[str, Any]:
    command = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--rss-worker",
        "--scenario",
        scenario,
        "--rows",
        str(rows),
        "--trials",
        str(trials),
        "--optimized" if optimized else "--reference",
    ]
    completed = subprocess.run(command, check=True, capture_output=True, text=True)
    return json.loads(completed.stdout.strip().splitlines()[-1])


def _scenario_report(scenario: str, rows: int, trials: int) -> Dict[str, Any]:
    # Compile/warm both mathematical paths before measuring framework overhead.
    _run(scenario, rows, min(3, trials), False)
    _run(scenario, rows, min(3, trials), True)
    gc.collect()
    reference_seconds, reference = _timed(scenario, rows, trials, False)
    gc.collect()
    optimized_seconds, optimized = _timed(scenario, rows, trials, True)
    reference_wf = reference.metadata["walk_forward"]
    optimized_wf = optimized.metadata["walk_forward"]
    reference_rss = _isolated_rss(scenario, rows, trials, False)
    optimized_rss = _isolated_rss(scenario, rows, trials, True)
    return {
        "scenario": scenario,
        "rows": int(rows),
        "trials_per_study": int(trials),
        "studies": int(optimized_wf["n_studies"]),
        "optuna_trial_rows": int(optimized_wf["n_optuna_trial_rows"]),
        "reference_seconds": float(reference_seconds),
        "optimized_seconds": float(optimized_seconds),
        "speedup": float(reference_seconds / optimized_seconds),
        "reference_trials_per_second": float(reference_wf["n_optuna_trial_rows"] / reference_seconds),
        "optimized_trials_per_second": float(optimized_wf["n_optuna_trial_rows"] / optimized_seconds),
        "reference_peak_rss_mb": float(reference_rss["workload_peak_rss_mb"]),
        "optimized_peak_rss_mb": float(optimized_rss["workload_peak_rss_mb"]),
        "reference_incremental_rss_mb": float(reference_rss["workload_incremental_rss_mb"]),
        "optimized_incremental_rss_mb": float(optimized_rss["workload_incremental_rss_mb"]),
        "reference_process_peak_rss_mb": float(reference_rss["process_peak_rss_mb"]),
        "optimized_process_peak_rss_mb": float(optimized_rss["process_peak_rss_mb"]),
        "peak_rss_change_pct": float(
            (optimized_rss["workload_peak_rss_mb"] / reference_rss["workload_peak_rss_mb"] - 1.0) * 100.0
        ),
        "parity": _parity(optimized, reference),
        "performance_profile": optimized_wf.get("performance_profile", {}),
        "prepared_context": optimized_wf.get("prepared_wfo_context", {}),
        "prepared_scorer": optimized_wf.get("prepared_scoring_cache", {}),
    }


def run_benchmark(rows: int = 720, trials: int = 16) -> Dict[str, Any]:
    import optuna

    optuna.logging.set_verbosity(optuna.logging.WARNING)
    reports = [
        _scenario_report("portfolio_global", rows, trials),
        _scenario_report("single_per_fold_causal", rows, trials),
    ]
    status = "pass" if all(report["parity"]["passed"] for report in reports) else "fail"
    return {
        "status": status,
        "benchmark_contract": "same bars, folds, trials, strategy, seed, account, and kernels",
        "cold_compile_policy": "isolated RSS workers include import/compile; warm runtime excludes explicit warm-up",
        "scenarios": reports,
    }


def make_markdown(report: Dict[str, Any]) -> str:
    lines = [
        "# Phase 49B WFO Prepared Context And Scalar Scoring",
        "",
        f"Status: **{report['status']}**",
        "",
        "All comparisons use identical bars, folds, trials, strategy, seed, account, and accounting kernels.",
        "Warm runtime excludes explicit warm-up; peak RSS is measured in isolated child processes.",
        "",
        "| Scenario | Bars | Studies x trials | Reference | Optimized | Speedup | Reference RSS | Optimized RSS |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for item in report["scenarios"]:
        lines.append(
            f"| `{item['scenario']}` | {item['rows']} | {item['studies']} x {item['trials_per_study']} | "
            f"{item['reference_seconds']:.4f}s | {item['optimized_seconds']:.4f}s | "
            f"{item['speedup']:.2f}x | {item['reference_peak_rss_mb']:.1f} MB | "
            f"{item['optimized_peak_rss_mb']:.1f} MB |"
        )
    lines.extend(["", "## Parity", ""])
    for item in report["scenarios"]:
        parity = item["parity"]
        lines.append(
            f"- `{item['scenario']}`: pass=`{parity['passed']}`, equity diff=`{parity['equity_max_abs_diff']}`, "
            f"position diff=`{parity['position_max_abs_diff']}`, params/trial/candidate order unchanged."
        )
    lines.extend(
        [
            "",
            "The reference is the Phase 49A prepared-market path with public result/report construction and full Optuna user attrs.",
            "The optimized path adds run-local prepared WFO slicing, array-first scalar reports, and compact post-selection ledgers.",
            "Strategy code is still executed for every trial; QuantBT does not cache arbitrary user indicators or signals.",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rows", type=int, default=720)
    parser.add_argument("--trials", type=int, default=16)
    parser.add_argument("--scenario", choices=("portfolio_global", "single_per_fold_causal"))
    parser.add_argument("--rss-worker", action="store_true")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--optimized", action="store_true")
    mode.add_argument("--reference", action="store_true")
    parser.add_argument("--json", type=Path, default=Path("benchmarks/phase49b_wfo_performance.json"))
    parser.add_argument("--markdown", type=Path, default=Path("benchmarks/phase49b_wfo_performance.md"))
    args = parser.parse_args()
    if args.rss_worker:
        if args.scenario is None:
            parser.error("--rss-worker requires --scenario")
        print(json.dumps(_rss_worker(args.scenario, args.rows, args.trials, args.optimized), sort_keys=True))
        return 0
    report = run_benchmark(rows=args.rows, trials=args.trials)
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.markdown.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    args.markdown.write_text(make_markdown(report))
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
