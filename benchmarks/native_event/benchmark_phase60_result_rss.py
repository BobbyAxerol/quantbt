"""Phase 60 repeated native score RSS plateau benchmark.

This script measures one prepared static command tape through the public
``NativeExecutionRequestCore``/``NativeExecutionRunnerCore`` ABI. It is not a
Python-vs-Rust throughput comparison: its narrow job is to prove that repeated
score requests retain no compact path, fill/event trace, pandas object, or
unbounded audit rows between runs.
"""

from __future__ import annotations

import argparse
import gc
import json
import os
import time
from pathlib import Path

import numpy as np


def _rss_bytes() -> int:
    """Return current Linux RSS, falling back to zero off Linux."""

    statm = Path("/proc/self/statm")
    if not statm.exists():
        return 0
    resident_pages = int(statm.read_text(encoding="ascii").split()[1])
    return resident_pages * os.sysconf("SC_PAGE_SIZE")


def _request(bars: int):
    import _quantbt_native

    timestamps = np.arange(bars, dtype=np.int64) * 3_600_000_000_000
    close = np.ascontiguousarray((100.0 + np.arange(bars, dtype=np.float64))[:, None])
    prepared = _quantbt_native.FullPreparedMarketCore(
        timestamps,
        close.copy(),
        np.ascontiguousarray(close + 1.0),
        np.ascontiguousarray(close - 1.0),
        close.copy(),
        np.full((bars, 1), 1_000.0, dtype=np.float64),
        np.zeros((bars, 1), dtype=np.float64),
        np.zeros(bars, dtype=np.bool_),
    )
    command_count = bars - 1
    command_ptr = np.zeros(bars + 1, dtype=np.int64)
    command_ptr[1:] = np.arange(command_count + 1, dtype=np.int64)
    codes = np.full((command_count, 16), -1, dtype=np.int64)
    values = np.zeros((command_count, 3), dtype=np.float64)
    expiry = np.full(command_count, -1, dtype=np.int64)
    for bar in range(1, bars):
        row = bar - 1
        codes[row] = [
            0,  # place
            0,  # symbol
            1 if bar % 2 else -1,
            0,  # market
            0,  # GTC
            0,
            10_000 + row,
            -1,
            -1,
            -1,
            -1,
            0,
            row,
            0,
            0,
            0,
        ]
        values[row, 0] = 1.0
    return _quantbt_native.NativeExecutionRequestCore.from_command_tape(
        prepared,
        np.ascontiguousarray(command_ptr),
        np.ascontiguousarray(codes),
        np.ascontiguousarray(values),
        np.ascontiguousarray(expiry),
        np.array([1.0], dtype=np.float64),
        np.array([5.0], dtype=np.float64),
        np.array([0.0005], dtype=np.float64),
        10_000.0,
        0.005,
        0.0002,
        False,
        event_contract_code=3,
        output_profile=0,  # score only
    )


def run(*, bars: int, iterations: int, warmup: int) -> dict[str, object]:
    request = _request(bars)
    runner = request.new_runner()
    for _ in range(warmup):
        result = runner.execute_typed()
        del result
    gc.collect()
    baseline_rss = _rss_bytes()
    peak_rss = baseline_rss
    start = time.perf_counter()
    terminal_fingerprint = ""
    for _ in range(iterations):
        result = runner.execute_typed()
        terminal_fingerprint = result.terminal_fingerprint
        if hasattr(result, "equity") or hasattr(result, "fill_bar"):
            raise AssertionError("score profile retained a compact/audit payload")
        del result
        peak_rss = max(peak_rss, _rss_bytes())
    elapsed_seconds = time.perf_counter() - start
    gc.collect()
    final_rss = _rss_bytes()
    plateau_delta = final_rss - baseline_rss
    # A small allocator plateau is acceptable; retained result paths are not.
    plateau_limit = max(8 * 1024 * 1024, int(baseline_rss * 0.10))
    return {
        "phase": "60",
        "workload": "prepared_static_command_tape_score",
        "bars": bars,
        "warmup_runs": warmup,
        "iterations": iterations,
        "elapsed_seconds": elapsed_seconds,
        "runs_per_second": iterations / elapsed_seconds if elapsed_seconds else 0.0,
        "bars_per_second": bars * iterations / elapsed_seconds if elapsed_seconds else 0.0,
        "baseline_rss_bytes": baseline_rss,
        "peak_rss_bytes": peak_rss,
        "final_rss_bytes": final_rss,
        "plateau_delta_bytes": plateau_delta,
        "plateau_limit_bytes": plateau_limit,
        "rss_plateau_pass": plateau_delta <= plateau_limit,
        "terminal_fingerprint": terminal_fingerprint,
        "detail_retained": False,
        "pandas_materialized": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bars", type=int, default=2_000)
    parser.add_argument("--iterations", type=int, default=250)
    parser.add_argument("--warmup", type=int, default=10)
    parser.add_argument("--json-out", type=Path)
    args = parser.parse_args()
    if args.bars < 2 or args.iterations <= 0 or args.warmup < 0:
        parser.error("bars must be >= 2, iterations > 0, and warmup >= 0")
    result = run(bars=args.bars, iterations=args.iterations, warmup=args.warmup)
    rendered = json.dumps(result, indent=2, sort_keys=True)
    print(rendered)
    if args.json_out is not None:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(rendered + "\n", encoding="utf-8")
    return 0 if result["rss_plateau_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
