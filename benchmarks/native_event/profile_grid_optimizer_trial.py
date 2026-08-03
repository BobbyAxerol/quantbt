"""Profile one Grid optimizer trial by ownership boundary.

This is intentionally a process-local diagnostic rather than a speed claim for
the Rust static tape.  It measures the external Grid alpha preparation,
stateful strategy construction, prepared scalar execution, and the public
objective facade separately so Phase 47D can target the real bottleneck.

Example::

    PYTHONPATH=. poetry run python \
      benchmarks/native_event/profile_grid_optimizer_trial.py \
      --grid-module-dir /root/bobby/pool_alpha/alphas_storage/TA \
      --bars 2000 --repeats 5 --output /tmp/grid_profile.json
"""

from __future__ import annotations

import argparse
import gc
import importlib.util
import json
import sys
import time
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_GRID_DIR = Path("/root/bobby/pool_alpha/alphas_storage/TA")
GRID_FILENAME = "dynamic_grid_quantbt_native_event.py"


def _load_grid(grid_module_dir: Path):
    path = grid_module_dir / GRID_FILENAME
    if not path.exists():
        raise FileNotFoundError(path)
    spec = importlib.util.spec_from_file_location("phase47d_grid_profile", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load Grid module: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _data(bars: int) -> pd.DataFrame:
    index = pd.date_range("2023-01-01", periods=bars, freq="h", tz="UTC")
    x = np.arange(bars, dtype=np.float64)
    close = 100.0 + 5.0 * np.sin(x / 11.0) + 0.01 * x + 1.5 * np.sin(x / 47.0)
    open_ = close + 0.2 * np.sin(x / 3.0)
    return pd.DataFrame(
        {
            "open": open_,
            "high": np.maximum(open_, close) + 1.5,
            "low": np.minimum(open_, close) - 1.5,
            "close": close,
            "volume": np.full(bars, 1000.0),
        },
        index=index,
    )


def _params() -> dict:
    return {
        "grid_mode": "long_only",
        "ma_type": "EMA",
        "ma_len": 8,
        "ema_len_short": 3,
        "logic": "ATR",
        "band_mult": 0.25,
        "zone_smoothing_len": 2,
        "warmup_bars": 12,
        "pyramiding": 3,
        "neutral_position_mode": "hold",
        "one_entry_fill_per_bar": True,
        "one_exit_fill_per_bar": True,
        "campaign_id": "PHASE47D",
    }


def _execution(grid):
    return grid.GridExecutionConfig(
        symbol="ETHUSDT",
        initial_capital=20_000.0,
        cash_per_entry=1_000.0,
        leverage=5.0,
        maintenance_ratio=0.005,
        contract_size=1.0,
        fee_rate=0.0005,
        slippage_bps=2.0,
        use_funding=True,
        funding_rate=0.0001,
        native_backend="python",
        reactive_execution_mode="fast",
        reactive_kernel_mode="single_pass",
        report_level="score",
        audit_sink="none",
    )


def _median(rows: list[dict]) -> dict:
    frame = pd.DataFrame(rows)
    return {
        key: float(frame[key].median())
        for key in frame.select_dtypes(include=[np.number]).columns
    }


def _profile_prepared_scalar(grid, data, params, execution, repeats: int):
    endpoint, prepared = grid.prepare_grid_score_runner(df=data, execution=execution)
    rows = []
    score_execution = replace(
        execution,
        collect_diagnostics=False,
    )
    for _ in range(repeats):
        started = time.perf_counter()
        alpha_frame = grid.prepare_grid_alpha_frame(
            data,
            dict(params),
            include_diagnostic_aliases=False,
        )
        after_alpha = time.perf_counter()
        strategy = grid.ReactiveDynamicGridStrategy(
            alpha_frame=alpha_frame,
            params=dict(params),
            execution=score_execution,
        )
        after_strategy = time.perf_counter()
        requirements = grid.NativeEventScoreRequirements.from_strategy(
            strategy,
            base=grid.NativeEventScoreRequirements.scalar_score_contract(),
        )
        score = prepared.score(
            strategy,
            trading_days=365,
            score_requirements=requirements,
        )
        after_score = time.perf_counter()
        rows.append(
            {
                "alpha_seconds": after_alpha - started,
                "strategy_init_seconds": after_strategy - after_alpha,
                "engine_score_seconds": after_score - after_strategy,
                "total_seconds": after_score - started,
                "fill_count": int(score.fill_count),
                "num_trades": int(score.metrics["num_trades"]),
            }
        )
    return rows, prepared, endpoint


def _profile_public_objective(grid, data, params, execution, repeats: int):
    rows = []
    for _ in range(repeats):
        started = time.perf_counter()
        run = grid.run_grid_backtest(data, params, execution)
        after_run = time.perf_counter()
        report = run.result.full_report(trading_days=365)
        after_report = time.perf_counter()
        rows.append(
            {
                "run_seconds": after_run - started,
                "report_seconds": after_report - after_run,
                "total_seconds": after_report - started,
                "fill_count": int(len(run.result.fills)),
                "num_trades": int(report["num_trades"]),
            }
        )
        del run, report
        gc.collect()
    return rows


def _add_percentages(median: dict, keys: tuple[str, ...], total_key: str = "total_seconds"):
    total = median.get(total_key, 0.0)
    if total <= 0.0:
        return
    for key in keys:
        median[f"{key}_pct"] = 100.0 * median.get(key, 0.0) / total


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--grid-module-dir", type=Path, default=DEFAULT_GRID_DIR)
    parser.add_argument("--bars", type=int, default=2000)
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    if args.bars <= 0 or args.repeats <= 0:
        parser.error("bars and repeats must be > 0")

    grid = _load_grid(args.grid_module_dir)
    data = _data(args.bars)
    params = _params()
    execution = _execution(grid)

    public_rows = _profile_public_objective(grid, data, params, execution, args.repeats)
    scalar_rows, prepared, endpoint = _profile_prepared_scalar(
        grid, data, params, execution, args.repeats
    )
    public_median = _median(public_rows)
    scalar_median = _median(scalar_rows)
    _add_percentages(public_median, ("run_seconds", "report_seconds"))
    _add_percentages(
        scalar_median,
        ("alpha_seconds", "strategy_init_seconds", "engine_score_seconds"),
    )
    payload = {
        "phase": "47D",
        "grid_module": str(args.grid_module_dir / GRID_FILENAME),
        "bars": args.bars,
        "repeats": args.repeats,
        "backend": execution.native_backend,
        "public_objective": {"samples": public_rows, "median": public_median},
        "prepared_scalar": {"samples": scalar_rows, "median": scalar_median},
        "gate": {
            "scores": int(prepared.scores),
            "runs": int(prepared.runs),
            "endpoint_result_is_none": endpoint.result is None,
        },
        "note": (
            "Public objective includes result/report facade. Prepared scalar is "
            "the optimizer path and includes alpha/strategy timing by boundary."
        ),
    }
    encoded = json.dumps(payload, indent=2, default=str)
    print(encoded)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
