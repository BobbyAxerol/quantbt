"""Phase 46D ownership/order-table benchmark.

This benchmark intentionally measures the Rust-owned prepared market and
static command tape after Python fixture construction. It is not a total
process RSS claim; import floor and Python DataFrame construction are reported
separately by Phase 46C/46B evidence.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict
import gc
import json
import os
from pathlib import Path
import resource
import time

import numpy as np
import pandas as pd

from quantbt import (
    AccountConfig,
    ExecutionConfig,
    NativeEventBackend,
    NativeEventConfig,
    OrderAction,
    OrderCommand,
    OrderSide,
    OrderType,
    TimeInForce,
)
from quantbt.backends._native_event_rust import RustBatchedRunner


PROJECT_ROOT = Path(__file__).resolve().parents[2]
PAGE_SIZE = os.sysconf("SC_PAGE_SIZE")


def _rss_bytes() -> int:
    with Path("/proc/self/statm").open(encoding="utf-8") as handle:
        return int(handle.read().split()[1]) * PAGE_SIZE


def _peak_rss_bytes() -> int:
    return int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss) * 1024


def _fixture(n_bars: int, churn: str):
    index = pd.date_range("2024-01-01", periods=n_bars, freq="1h", tz="UTC")
    close = pd.Series(100.0 + np.arange(n_bars, dtype=np.float64) * 0.01, index=index)
    frame = pd.DataFrame(
        {
            "open": close,
            "high": close + 1.0,
            "low": close - 1.0,
            "close": close,
            "volume": 1_000.0,
        },
        index=index,
    )
    backend = NativeEventBackend(
        NativeEventConfig(
            account=AccountConfig(initial_capital=10_000.0, leverage=5.0, maintenance_ratio=0.0),
            execution=ExecutionConfig(slippage_bps=2.0),
            fee_rate=0.0002,
            use_funding=False,
        )
    )
    market = backend.prepare_market_arrays(
        datetime_index=index,
        closes={"BTC": frame["close"]},
        highs={"BTC": frame["high"]},
        lows={"BTC": frame["low"]},
        symbols=["BTC"],
    )
    commands: list[OrderCommand] = []
    if churn == "low":
        for bar in range(1, n_bars, max(1, n_bars // 20)):
            order_id = f"low-{bar}"
            commands.append(
                OrderCommand(
                    timestamp=index[bar],
                    symbol="BTC",
                    side=OrderSide.BUY,
                    order_type=OrderType.LIMIT,
                    qty=1.0,
                    price=1.0,
                    tif=TimeInForce.GTC,
                    order_id=order_id,
                )
            )
            commands.append(
                OrderCommand(
                    timestamp=index[min(bar + 1, n_bars - 1)],
                    action=OrderAction.CANCEL,
                    target_order_id=order_id,
                )
            )
    elif churn == "high":
        for bar in range(n_bars):
            order_id = f"high-{bar}"
            commands.append(
                OrderCommand(
                    timestamp=index[bar],
                    symbol="BTC",
                    side=OrderSide.BUY,
                    order_type=OrderType.LIMIT,
                    qty=1.0,
                    price=1.0,
                    tif=TimeInForce.GTC,
                    order_id=order_id,
                )
            )
            if bar:
                commands.append(
                    OrderCommand(
                        timestamp=index[bar],
                        action=OrderAction.CANCEL,
                        target_order_id=f"high-{bar - 1}",
                    )
                )
    else:
        raise ValueError("churn must be low or high")
    compiled = backend.compile_order_commands(index, commands, symbols=["BTC"])
    runner = RustBatchedRunner(
        idx=index,
        symbols=["BTC"],
        market_arrays=market,
        contract_size=1.0,
        leverage=5.0,
        fee_rate=0.0002,
        initial_capital=10_000.0,
        slippage=0.0002,
        use_funding=False,
    )
    return runner, compiled


def _profile(n_bars: int, churn: str, repeats: int):
    runner, compiled = _fixture(n_bars, churn)
    before = _rss_bytes()
    first_start = time.perf_counter()
    first = runner.run_tape_score(compiled)
    first_seconds = time.perf_counter() - first_start
    after_first = _rss_bytes()
    repeat_start = time.perf_counter()
    last = None
    for _ in range(repeats):
        last = runner.run_tape_score(compiled)
    repeat_seconds = time.perf_counter() - repeat_start
    after_repeats = _rss_bytes()
    assert last is not None
    order_count = int(compiled.command_action.size)
    scalar_fields = (
        "final_equity",
        "final_position",
        "total_fee",
        "total_turnover",
        "fill_count",
        "event_count",
        "rejected_count",
        "canceled_count",
        "max_initial_margin",
        "max_maintenance_margin",
        "bars",
    )
    parity = all(getattr(first, field) == getattr(last, field) for field in scalar_fields)
    sparse = runner.open_sparse_session(compiled)
    first_chunk = sparse.run_until(n_bars - 1, wake_on_fill=False, wake_on_order_event=False)
    reset_start = _rss_bytes()
    reset_last = first_chunk
    for _ in range(repeats):
        sparse.reset()
        reset_last = sparse.run_until(n_bars - 1, wake_on_fill=False, wake_on_order_event=False)
    reset_end = _rss_bytes()
    session_reset_parity = all(
        getattr(first_chunk, field) == getattr(reset_last, field)
        for field in scalar_fields
        if hasattr(first_chunk, field)
    )
    cached_bytes = runner.tape_cache_bytes
    max_cached_bytes = runner.max_tape_cache_bytes
    runner.clear_tape_cache()
    cleared = runner.tape_cache_bytes == 0
    del runner, compiled
    gc.collect()
    return {
        "bars": n_bars,
        "churn": churn,
        "orders": order_count,
        "tape_cache_bytes_before_clear": cached_bytes,
        "max_tape_cache_bytes": max_cached_bytes,
        "first_seconds": first_seconds,
        "repeat_seconds": repeat_seconds,
        "repeat_seconds_per_run": repeat_seconds / max(repeats, 1),
        "rss_before_first_score": before,
        "rss_after_first_score": after_first,
        "rss_after_repeats": after_repeats,
        "incremental_first_score_rss": after_first - before,
        "incremental_repeat_rss": after_repeats - after_first,
        "peak_rss_bytes": _peak_rss_bytes(),
        "tape_cache_cleared": cleared,
        "reset_scalar_parity": parity,
        "session_reset_parity": session_reset_parity,
        "session_reset_rss_delta": reset_end - reset_start,
        "score_metadata": asdict(first),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bars", type=int, default=2_000)
    parser.add_argument("--repeats", type=int, default=100)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = {
        "phase": "46D",
        "bars": args.bars,
        "repeats": args.repeats,
        "low": _profile(args.bars, "low", args.repeats),
        "high": _profile(args.bars, "high", args.repeats),
    }
    report["passed"] = bool(
        report["low"]["reset_scalar_parity"]
        and report["high"]["reset_scalar_parity"]
        and report["low"]["session_reset_parity"]
        and report["high"]["session_reset_parity"]
        and report["low"]["tape_cache_cleared"]
        and report["high"]["tape_cache_cleared"]
    )
    payload = json.dumps(report, indent=2, sort_keys=True) + "\n"
    print(payload, end="")
    if args.output:
        args.output.write_text(payload, encoding="utf-8")
    if not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
