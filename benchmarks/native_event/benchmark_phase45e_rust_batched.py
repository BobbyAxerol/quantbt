"""Fresh-process smoke benchmark for the Phase45E Rust full-tape boundary."""

from __future__ import annotations

import json
import resource
import time
from pathlib import Path

import numpy as np
import pandas as pd

from quantbt import AccountConfig, ExecutionConfig, NativeEventBackend, NativeEventConfig, OrderCommand, OrderSide, OrderType


def main() -> None:
    n_bars = 100_000
    index = pd.date_range("2020-01-01", periods=n_bars, freq="1h", tz="UTC")
    close = pd.Series(100.0 + np.sin(np.arange(n_bars) / 17.0), index=index)
    frame = pd.DataFrame(
        {"open": close, "high": close + 1.0, "low": close - 1.0, "close": close},
        index=index,
    )
    backend = NativeEventBackend(
        NativeEventConfig(
            account=AccountConfig(initial_capital=20_000.0, leverage=5.0, maintenance_ratio=0.0),
            execution=ExecutionConfig(slippage_bps=2.0),
            fee_rate=0.0002,
            use_funding=False,
        )
    )
    market = backend.prepare_market_arrays(
        index,
        {"BTC": frame["close"]},
        {"BTC": frame["high"]},
        {"BTC": frame["low"]},
        symbols=["BTC"],
    )
    commands = []
    for cycle, entry in enumerate(range(1, n_bars - 1000, 5000)):
        exit_bar = entry + 1000
        commands.extend(
            (
                OrderCommand(
                    timestamp=index[entry],
                    symbol="BTC",
                    side=OrderSide.BUY,
                    order_type=OrderType.MARKET,
                    qty=1.0,
                    order_id=f"entry-{cycle}",
                ),
                OrderCommand(
                    timestamp=index[exit_bar],
                    symbol="BTC",
                    side=OrderSide.SELL,
                    order_type=OrderType.MARKET,
                    qty=1.0,
                    reduce_only=True,
                    order_id=f"exit-{cycle}",
                ),
            )
        )
    compiled = backend.compile_order_commands(index, commands, symbols=["BTC"])
    runner = backend.prepare_rust_batched_runner(
        index,
        {"BTC": frame["close"]},
        {"BTC": frame["high"]},
        {"BTC": frame["low"]},
        symbols=["BTC"],
    )

    runner.run_tape_score(compiled)
    backend.run_order_commands(
        index,
        commands,
        {"BTC": frame["close"]},
        {"BTC": frame["high"]},
        {"BTC": frame["low"]},
        symbols=["BTC"],
        market_arrays=market,
        compiled_commands=compiled,
        report_level="minimal",
    )

    def timed(fn, repetitions: int = 5):
        samples = []
        last = None
        for _ in range(repetitions):
            started = time.perf_counter()
            last = fn()
            samples.append(time.perf_counter() - started)
        return float(np.median(samples)), last

    rust_seconds, rust = timed(lambda: runner.run_tape_score(compiled))
    python_seconds, python = timed(
        lambda: backend.run_order_commands(
            index,
            commands,
            {"BTC": frame["close"]},
            {"BTC": frame["high"]},
            {"BTC": frame["low"]},
            symbols=["BTC"],
            market_arrays=market,
            compiled_commands=compiled,
            report_level="minimal",
        )
    )
    payload = {
        "phase": "45E",
        "bars": n_bars,
        "commands": len(commands),
        "repetitions": 5,
        "rust_batched_score_seconds_median": rust_seconds,
        "python_v2_seconds_median": python_seconds,
        "speedup_python_over_rust": python_seconds / rust_seconds if rust_seconds else None,
        "rust_final_equity": rust.final_equity,
        "python_final_equity": float(python.equity.iloc[-1]),
        "rust_fill_count": rust.fill_count,
        "python_fill_count": int(python.metadata["lifecycle_counters"]["fill_count"]),
        "maxrss_mb": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0,
        "note": "Rust remains explicit experimental until isolated multi-scenario speed/RSS gates pass.",
    }
    path = Path(__file__).with_name("phase45e_rust_batched.json")
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
