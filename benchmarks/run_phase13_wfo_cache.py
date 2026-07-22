#!/usr/bin/env python3
"""
Phase 13A WFO prepared market-cache benchmark.

This runner verifies that portfolio WFO endpoint scoring can reuse prepared
market arrays across Optuna trials without changing selected params, objective,
or final backtest equity.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Dict

import numpy as np
import pandas as pd

PACKAGE_DIR = Path(__file__).resolve().parents[1]
PROJECT_DIR = PACKAGE_DIR.parent
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from quantbt import QuantBTEndpoint  # noqa: E402


def run_benchmark(rows: int = 720, trials: int = 16) -> Dict:
    data = _make_data(rows)
    _run_wfo(data, trials=max(2, min(int(trials), 4)), use_cache=True)
    _run_wfo(data, trials=max(2, min(int(trials), 4)), use_cache=False)
    cached_seconds, cached = _time_run(data, trials=trials, use_cache=True)
    uncached_seconds, uncached = _time_run(data, trials=trials, use_cache=False)
    cached_wf = cached.metadata["walk_forward"]
    uncached_wf = uncached.metadata["walk_forward"]
    cache_meta = cached_wf.get("prepared_scoring_cache", {})
    final_equity_diff = float(abs(cached.equity.iloc[-1] - uncached.equity.iloc[-1]))
    objective_diff = float(abs(cached_wf["best_trial"]["objective"] - uncached_wf["best_trial"]["objective"]))
    params_match = cached_wf["params"] == uncached_wf["params"]
    speedup = float(uncached_seconds / cached_seconds) if cached_seconds > 0.0 else 0.0
    status = "pass" if final_equity_diff <= 1e-9 and objective_diff <= 1e-12 and params_match else "fail"
    return {
        "status": status,
        "rows": int(rows),
        "trials": int(trials),
        "cached_seconds": float(cached_seconds),
        "uncached_seconds": float(uncached_seconds),
        "speedup": speedup,
        "final_equity_diff": final_equity_diff,
        "objective_diff": objective_diff,
        "params_match": bool(params_match),
        "selected_params": cached_wf["params"],
        "cache_metadata": cache_meta,
    }


def make_markdown(report: Dict) -> str:
    cache = report["cache_metadata"]
    lines = [
        "# Phase 13A WFO Prepared Market Cache",
        "",
        f"Status: **{report['status']}**",
        "",
        f"- Rows: `{report['rows']}`",
        f"- Optuna trials: `{report['trials']}`",
        f"- Cached seconds: `{report['cached_seconds']:.6f}`",
        f"- Uncached seconds: `{report['uncached_seconds']:.6f}`",
        f"- Speedup: `{report['speedup']:.3f}x`",
        f"- Final equity diff: `{report['final_equity_diff']}`",
        f"- Objective diff: `{report['objective_diff']}`",
        f"- Params match: `{report['params_match']}`",
        f"- Selected params: `{report['selected_params']}`",
        "",
        "## Cache Metadata",
        "",
        f"- Enabled: `{cache.get('enabled')}`",
        f"- Prepared runs: `{cache.get('prepared_runs')}`",
        f"- Fallback runs: `{cache.get('fallback_runs')}`",
        f"- Market cache hits: `{cache.get('market_cache_hits')}`",
        f"- Market cache misses: `{cache.get('market_cache_misses')}`",
        f"- Market cache entries: `{cache.get('market_cache_entries')}`",
        "",
        "The benchmark is a deterministic parity/reuse guard, not a universal speed claim.",
        "Full WFO runtime can still be dominated by Optuna and report construction.",
    ]
    return "\n".join(lines) + "\n"


def _time_run(data: Dict[str, pd.DataFrame], *, trials: int, use_cache: bool):
    start = time.perf_counter()
    result = _run_wfo(data, trials=trials, use_cache=use_cache)
    return time.perf_counter() - start, result


def _run_wfo(data: Dict[str, pd.DataFrame], *, trials: int, use_cache: bool):
    def strategy(data, params, train_index, test_index, fold):
        scale = float(params["scale"])
        return pd.DataFrame({"BTC": scale, "ETH": -scale}, index=test_index)

    endpoint = QuantBTEndpoint.train_test_split(
        strategy_class=strategy,
        test_start="2022-01-01",
        target_mode="portfolio",
        portfolio_mode="longshort",
        optimization_mode="mode_1_decay",
        optimization_config={
            "scoring_backend": "endpoint",
            "use_prepared_scoring_cache": bool(use_cache),
        },
        optuna_trials=int(trials),
        random_seed=123,
        initial_capital=100_000.0,
        leverage=5.0,
        alloc_per_trade=1_000.0,
        fee=0.0,
        use_funding=False,
    )
    return endpoint.backtest(data=data, param_ranges={"scale": (0.5, 1.5, 0.05)})


def _make_data(rows: int) -> Dict[str, pd.DataFrame]:
    idx = pd.date_range("2021-01-01", periods=int(rows), freq="1D", tz="UTC")
    x = np.linspace(0.0, 16.0, len(idx))
    btc_close = 100.0 + np.sin(x) * 2.0 + np.arange(len(idx)) * 0.01
    eth_close = 50.0 + np.cos(x) * 1.5 + np.arange(len(idx)) * 0.005
    return {
        "BTC": _frame(idx, btc_close),
        "ETH": _frame(idx, eth_close),
    }


def _frame(idx: pd.DatetimeIndex, close: np.ndarray) -> pd.DataFrame:
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
    parser.add_argument("--rows", type=int, default=720)
    parser.add_argument("--trials", type=int, default=16)
    parser.add_argument("--json", type=Path, default=PACKAGE_DIR / "benchmarks" / "phase13_wfo_cache.json")
    parser.add_argument("--markdown", type=Path, default=PACKAGE_DIR / "benchmarks" / "phase13_wfo_cache.md")
    args = parser.parse_args()
    report = run_benchmark(rows=args.rows, trials=args.trials)
    args.json.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    args.markdown.write_text(make_markdown(report))
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
