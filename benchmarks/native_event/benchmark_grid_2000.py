#!/usr/bin/env python3
"""Process-isolated Phase 47C Grid runtime/RSS benchmark.

The external Grid alpha is loaded read-only. A scalar benchmark first creates
one audit reference for its parity fingerprint, then measures only fresh
prepared score calls. Each CLI invocation owns one backend process so Python
and Rust imports/caches cannot contaminate one another.
"""

from __future__ import annotations

import argparse
import gc
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import resource
import subprocess
import sys
import time
from typing import Any

import numpy as np
import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_GRID_DIR = Path("/root/bobby/pool_alpha/alphas_storage/TA")

for candidate in (REPO_ROOT, REPO_ROOT / "src"):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))


def _load_grid_module(module_dir: Path):
    path = module_dir / "dynamic_grid_quantbt_native_event.py"
    if not path.exists():
        raise FileNotFoundError(f"Grid module not found: {path}")
    spec = importlib.util.spec_from_file_location("phase47c_benchmark_grid", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import Grid module: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _synthetic_data(bars: int) -> pd.DataFrame:
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


def _load_market(path: str | None, bars: int) -> pd.DataFrame:
    if path is None:
        data = _synthetic_data(bars)
    else:
        source = Path(path)
        data = pd.read_csv(source, compression="infer")
        lower = {str(column).lower(): column for column in data.columns}
        time_column = next(
            (lower[name] for name in ("timestamp", "datetime", "date", "time") if name in lower),
            None,
        )
        if time_column is not None:
            index = pd.to_datetime(data.pop(time_column), utc=True)
        else:
            index = pd.to_datetime(data.index, utc=True)
        data.index = index
        rename = {}
        for required in ("open", "high", "low", "close", "volume"):
            if required in lower:
                rename[lower[required]] = required
        data = data.rename(columns=rename)
        if "volume" not in data:
            data["volume"] = 0.0
        required = ["open", "high", "low", "close", "volume"]
        missing = [column for column in required if column not in data]
        if missing:
            raise ValueError(f"market data is missing columns: {missing}")
        data = data[required].sort_index()
        if data.index.has_duplicates:
            raise ValueError("market data index must not contain duplicates")
        data = data.iloc[-int(bars):].copy()
    if len(data) != int(bars):
        raise ValueError(f"expected exactly {bars} bars, received {len(data)}")
    if not data.index.is_monotonic_increasing or data.index.has_duplicates:
        raise ValueError("market data must be sorted and unique")
    return data.astype(np.float64)


def _grid_params(grid_mode: str) -> dict[str, Any]:
    return {
        "grid_mode": grid_mode,
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
        "campaign_id": "PHASE47C_BENCH",
    }


def _execution(grid, backend: str, mode: str):
    audit = mode == "audit"
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
        native_backend=backend,
        reactive_execution_mode="audit" if audit else "fast",
        reactive_kernel_mode=(
            "replay_certified" if backend == "replay_certified" else "single_pass"
        ),
        report_level="audit" if audit else "score",
        audit_sink="memory" if audit else "none",
    )


def _jsonable(value: Any):
    if isinstance(value, (np.integer, int)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return float(value)
    if isinstance(value, pd.Timestamp):
        return int(value.value)
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if value is pd.NaT or pd.isna(value):
        return None
    return value


def _digest_update_array(digest, name: str, values) -> None:
    array = np.ascontiguousarray(np.asarray(values))
    digest.update(name.encode("utf-8"))
    digest.update(str(array.dtype).encode("ascii"))
    digest.update(repr(array.shape).encode("ascii"))
    digest.update(array.tobytes())


def _audit_fingerprint(run) -> str:
    digest = hashlib.sha256()
    for command in run.command_tape:
        payload = {
            "timestamp": int(pd.Timestamp(command.timestamp).value),
            "action": command.action.value,
            "symbol": command.symbol,
            "side": None if command.side is None else command.side.value,
            "order_type": None if command.order_type is None else command.order_type.value,
            "qty": float(command.qty or 0.0),
            "price": None if command.price is None else float(command.price),
            "trigger_price": None if command.trigger_price is None else float(command.trigger_price),
            "tif": command.tif.value,
            "reduce_only": bool(command.reduce_only),
            "order_id": command.order_id,
            "target_order_id": command.target_order_id,
            "parent_order_id": command.parent_order_id,
            "group_id": command.group_id,
            "oco_group_id": command.oco_group_id,
            "expires_at": None if command.expires_at is None else int(pd.Timestamp(command.expires_at).value),
            "metadata": _jsonable(dict(command.metadata or {})),
        }
        digest.update(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    event_frame = run.order_events.reset_index(drop=True)
    digest.update(event_frame.to_json(orient="split", date_format="iso").encode("utf-8"))
    result = run.result
    _digest_update_array(digest, "equity", result.equity)
    _digest_update_array(digest, "positions", result.positions)
    _digest_update_array(digest, "fees", result.fees)
    _digest_update_array(digest, "funding", result.funding)
    _digest_update_array(digest, "margin", result.margin)
    for fill in run.result.fills:
        payload = (
            int(pd.Timestamp(fill.timestamp).value),
            str(fill.symbol),
            getattr(fill.side, "value", str(fill.side)),
            float(fill.qty),
            float(fill.price),
            float(fill.fee),
            fill.order_id,
        )
        digest.update(repr(payload).encode("utf-8"))
    digest.update(repr((bool(result.liquidated), int(result.liquidation_bar))).encode("ascii"))
    return digest.hexdigest()


def _rss_kb() -> int | None:
    try:
        for line in Path("/proc/self/status").read_text().splitlines():
            if line.startswith("VmRSS:"):
                return int(line.split()[1])
    except (OSError, ValueError):
        return None
    return None


def _peak_rss_kb() -> int:
    return int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)


def _git_revision() -> str | None:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=REPO_ROOT,
            text=True,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def _run_once(grid, data, params, execution, mode):
    if mode == "audit":
        return grid.run_grid_backtest(data, params, execution)
    endpoint, prepared = grid.prepare_grid_score_runner(df=data, execution=execution)
    score = grid.score_grid_params(
        prepared_runner=prepared,
        df=data,
        params=params,
        execution=execution,
    )
    if not hasattr(score, "final_equity"):
        raise AssertionError("scalar benchmark returned a dense score result")
    return score


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--grid-module-dir", type=Path, default=DEFAULT_GRID_DIR)
    parser.add_argument("--data", type=str, default=None, help="optional OHLCV CSV/CSV.GZ")
    parser.add_argument("--backend", choices=("python", "rust", "replay_certified"), required=True)
    parser.add_argument("--mode", choices=("audit", "scalar"), required=True)
    parser.add_argument("--grid-mode", choices=("long_only", "long_short"), default="long_only")
    parser.add_argument("--bars", type=int, default=2000)
    parser.add_argument("--warmup", type=int, default=1)
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    if args.bars <= 0 or args.warmup < 0 or args.runs <= 0:
        parser.error("bars, runs must be > 0 and warmup must be >= 0")
    if args.mode == "scalar" and args.backend == "replay_certified":
        parser.error("replay_certified is an audit oracle, not a scalar backend")

    grid = _load_grid_module(args.grid_module_dir)
    data = _load_market(args.data, args.bars)
    params = _grid_params(args.grid_mode)
    execution = _execution(grid, args.backend, args.mode)
    audit_reference_fingerprint = None
    if args.mode == "scalar":
        audit_run = grid.run_grid_backtest(
            data,
            params,
            _execution(grid, args.backend, "audit"),
        )
        audit_reference_fingerprint = _audit_fingerprint(audit_run)

    for _ in range(args.warmup):
        _run_once(grid, data, params, execution, args.mode)

    runtimes = []
    cpu_times = []
    post_rss = []
    first_result = None
    for _ in range(args.runs):
        start = time.perf_counter()
        cpu_start = time.process_time()
        result = _run_once(grid, data, params, execution, args.mode)
        cpu_times.append(time.process_time() - cpu_start)
        runtimes.append(time.perf_counter() - start)
        if first_result is None:
            first_result = result
        else:
            del result
        gc.collect()
        post_rss.append(_rss_kb())

    peak = _peak_rss_kb()
    numeric_rss = [value for value in post_rss if value is not None]
    slope = 0.0
    if len(numeric_rss) >= 2:
        slope = float(np.polyfit(np.arange(len(numeric_rss), dtype=np.float64), numeric_rss, 1)[0])
    if args.mode == "audit":
        fingerprint = _audit_fingerprint(first_result)
        final_equity = float(first_result.result.equity.iloc[-1])
        fill_count = int(len(first_result.result.fills))
        total_fee = float(first_result.result.fees.sum())
        total_funding = float(first_result.result.funding.sum())
        resolved = first_result.result.metadata.get("native_event_backend_resolved")
    else:
        fingerprint = audit_reference_fingerprint
        final_equity = float(first_result.final_equity)
        fill_count = int(first_result.fill_count)
        total_fee = float(first_result.total_fee)
        total_funding = float(first_result.metadata.get("total_funding", 0.0))
        resolved = first_result.metadata.get("native_event_backend_resolved")
    if args.backend == "rust" and resolved != "rust":
        raise RuntimeError(f"explicit Rust benchmark resolved to {resolved!r}")

    payload = {
        "phase": "47C",
        "grid_module_version": getattr(grid, "MODULE_VERSION", None),
        "git_revision": _git_revision(),
        "backend_requested": args.backend,
        "backend_resolved": resolved,
        "mode": args.mode,
        "grid_mode": args.grid_mode,
        "bars": int(args.bars),
        "warmup_runs": int(args.warmup),
        "measured_runs": int(args.runs),
        "runtime_seconds": [float(value) for value in runtimes],
        "runtime_median_seconds": float(np.median(runtimes)),
        "runtime_p95_seconds": float(np.percentile(runtimes, 95)),
        "cpu_seconds": [float(value) for value in cpu_times],
        "cpu_median_seconds": float(np.median(cpu_times)),
        "peak_rss_kb": int(peak),
        "post_run_rss_kb": post_rss,
        "post_run_rss_median_kb": None if not numeric_rss else float(np.median(numeric_rss)),
        "post_run_rss_slope_kb_per_run": slope,
        "fingerprint": fingerprint,
        "audit_reference_fingerprint": audit_reference_fingerprint,
        "final_equity": final_equity,
        "fill_count": fill_count,
        "total_fee": total_fee,
        "total_funding": total_funding,
        "rss_gate": {
            "accepted_baseline_note": "approximately 180 MB; no 10-15% regression and no linear leak",
            "linear_leak_observed": bool(slope > max(1024.0, peak * 0.01)),
            "pass": bool(slope <= max(1024.0, peak * 0.01)),
        },
        "policy": {
            "python_default": True,
            "rust_explicit_fail_fast": args.backend == "rust",
            "auto_promoted": False,
            "replay_is_oracle": True,
        },
    }
    rendered = json.dumps(payload, indent=2, sort_keys=True)
    print(rendered)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
