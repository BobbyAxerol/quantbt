"""Phase 51A end-to-end contract and diagnostics benchmark."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from statistics import median
from time import perf_counter

import numpy as np
import pandas as pd

from quantbt.backends import NativeEventBackend, NativeEventConfig
from quantbt.core.event_contracts import (
    EVENT_LIFECYCLE_V2_NEXT_BAR_CLOSE,
    EVENT_LIFECYCLE_V3_NEXT_OPEN,
    NATIVE_EVENT_CONTRACT_FINGERPRINT,
)
from quantbt.core.orders import OrderCommand
from quantbt.core.schema import AccountConfig, ExecutionConfig, OrderSide, OrderType


def fixture(bars: int):
    idx = pd.date_range("2025-01-01", periods=bars, freq="15min", tz="UTC")
    x = np.arange(bars, dtype=np.float64)
    close = 100.0 + 0.02 * x + np.sin(x / 13.0)
    open_ = close + 0.15 * np.cos(x / 7.0)
    high = np.maximum(open_, close) + 0.6
    low = np.minimum(open_, close) - 0.6
    commands = []
    order_id = 0
    for bar in range(1, bars - 2, 20):
        commands.append(
            OrderCommand(
                timestamp=idx[bar], symbol="TEST", side=OrderSide.BUY,
                order_type=OrderType.MARKET, qty=0.25, order_id=f"o-{order_id}",
            )
        )
        order_id += 1
        commands.append(
            OrderCommand(
                timestamp=idx[bar + 1], symbol="TEST", side=OrderSide.SELL,
                order_type=OrderType.MARKET, qty=0.25, order_id=f"o-{order_id}",
            )
        )
        order_id += 1
    return idx, open_, high, low, close, tuple(commands)


def measure(backend_name: str, contract: str, diagnostics: bool, bars: int, repeats: int) -> dict:
    idx, open_, high, low, close, commands = fixture(bars)
    series = lambda values: {"TEST": pd.Series(values, index=idx)}
    backend = NativeEventBackend(
        NativeEventConfig(
            account=AccountConfig(initial_capital=20_000.0, leverage=5.0),
            execution=ExecutionConfig(slippage_bps=2.0),
            fee_rate=0.0005,
            use_funding=False,
            report_level="audit",
            native_backend=backend_name,
            execution_contract=contract,
            diagnostics=diagnostics,
        )
    )

    def run_once():
        return backend.run_order_commands(
            datetime_index=idx,
            commands=commands,
            closes=series(close),
            highs=series(high),
            lows=series(low),
            opens=series(open_),
            symbols=["TEST"],
        )

    run_once()
    elapsed = []
    result = None
    for _ in range(repeats):
        started = perf_counter()
        result = run_once()
        elapsed.append(perf_counter() - started)
    seconds = median(elapsed)
    return {
        "backend": backend_name,
        "contract": contract,
        "diagnostics": diagnostics,
        "bars": bars,
        "commands": len(commands),
        "median_seconds": seconds,
        "bars_per_second": bars / seconds,
        "final_equity": float(result.equity.iloc[-1]),
        "fills": int(result.metadata["lifecycle_counters"]["fill_count"]),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bars", type=int, default=2_000)
    parser.add_argument("--repeats", type=int, default=7)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("benchmarks/native_event/results/phase51a/contracts.json"),
    )
    args = parser.parse_args()

    rows = []
    for backend in ("python", "rust"):
        for contract in (EVENT_LIFECYCLE_V2_NEXT_BAR_CLOSE, EVENT_LIFECYCLE_V3_NEXT_OPEN):
            for diagnostics in (False, True):
                rows.append(measure(backend, contract, diagnostics, args.bars, args.repeats))
    lookup = {(row["backend"], row["contract"], row["diagnostics"]): row for row in rows}
    overhead = {}
    for backend in ("python", "rust"):
        for contract in (EVENT_LIFECYCLE_V2_NEXT_BAR_CLOSE, EVENT_LIFECYCLE_V3_NEXT_OPEN):
            base = lookup[(backend, contract, False)]["median_seconds"]
            enabled = lookup[(backend, contract, True)]["median_seconds"]
            overhead[f"{backend}:{contract}"] = enabled / base - 1.0
    payload = {
        "schema_version": 1,
        "contract_registry_fingerprint": NATIVE_EVENT_CONTRACT_FINGERPRINT,
        "workload": "public run_order_commands end-to-end; warm JIT; audit report",
        "results": rows,
        "diagnostics_overhead_ratio": overhead,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n")
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
