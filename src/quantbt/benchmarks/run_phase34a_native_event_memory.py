from __future__ import annotations

import argparse
import json
import resource
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

from quantbt import AccountConfig, ExecutionConfig, NativeEventBackend, NativeEventConfig
from quantbt.core.orders import OrderAction, OrderCommand
from quantbt.core.schema import OrderSide, OrderType, TimeInForce


def _rss_mb() -> float:
    value = float(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    if sys.platform == "darwin":
        return value / (1024.0 * 1024.0)
    return value / 1024.0


def _market(rows: int):
    idx = pd.date_range("2020-01-01", periods=rows, freq="15min", tz="UTC")
    x = np.arange(rows, dtype=np.float64)
    close = pd.Series(100.0 + np.sin(x / 17.0) * 2.0 + x * 0.0001, index=idx)
    high = close + 1.2
    low = close - 1.2
    return idx, {"BTC": close}, {"BTC": high}, {"BTC": low}


def _commands(idx: pd.DatetimeIndex, levels: int, cycle: int):
    commands = []
    order_id = 0
    for bar in range(1, len(idx), cycle):
        commands.append(OrderCommand(timestamp=idx[bar], action=OrderAction.CANCEL_ALL, symbol="BTC"))
        anchor = 100.0 + np.sin(bar / 17.0) * 2.0 + bar * 0.0001
        for level in range(1, levels + 1):
            commands.append(
                OrderCommand(
                    timestamp=idx[bar],
                    symbol="BTC",
                    side=OrderSide.BUY,
                    order_type=OrderType.LIMIT,
                    qty=0.01,
                    price=float(anchor - 0.08 * level),
                    tif=TimeInForce.GTC,
                    order_id=f"entry-{order_id}",
                    tag=f"GRID-C{bar}-L{level}",
                    metadata={"campaign_id": f"C{bar}", "level_id": str(level)},
                )
            )
            order_id += 1
            commands.append(
                OrderCommand(
                    timestamp=idx[bar],
                    symbol="BTC",
                    side=OrderSide.SELL,
                    order_type=OrderType.LIMIT,
                    qty=0.01,
                    price=float(anchor + 0.08 * level),
                    tif=TimeInForce.GTC,
                    reduce_only=True,
                    order_id=f"exit-{order_id}",
                    tag=f"GRID-C{bar}-X{level}",
                    metadata={"campaign_id": f"C{bar}", "level_id": str(level), "leg_role": "take_profit"},
                )
            )
            order_id += 1
    return tuple(commands)


def _run_child(args) -> dict:
    idx, close, high, low = _market(args.rows)
    commands = _commands(idx, levels=args.levels, cycle=args.cycle)
    backend = NativeEventBackend(
        NativeEventConfig(
            account=AccountConfig(initial_capital=100_000.0, leverage=10.0),
            execution=ExecutionConfig(slippage_bps=0.0),
            fee_rate=0.0,
            use_funding=False,
            report_level=args.report_level,
            audit_sink=args.audit_sink,
            audit_sink_path=args.audit_sink_path,
        )
    )
    start = time.perf_counter()
    result = backend.run_order_commands(idx, commands, close, high, low, symbols=["BTC"])
    elapsed = time.perf_counter() - start
    payload = {
        "report_level": result.metadata["report_level"],
        "audit_sink": result.metadata["audit_sink"],
        "rows": int(args.rows),
        "levels": int(args.levels),
        "commands": int(len(commands)),
        "fills": int(result.metadata["lifecycle_counters"]["fill_count"]),
        "events": int(result.metadata["lifecycle_counters"]["event_count"]),
        "seconds": float(elapsed),
        "peak_rss_mb": float(_rss_mb()),
        "command_report_rows": int(len(result.metadata["command_report"])),
        "order_event_rows": int(len(result.metadata["order_events"])),
        "fills_materialized": int(len(result.fills)),
        "orders_materialized": int(len(result.orders)),
        "final_equity": float(result.equity.iloc[-1]),
    }
    print(json.dumps(payload, sort_keys=True))
    return payload


def _run_parent(args) -> list[dict]:
    rows = []
    for level in ("minimal", "standard", "audit"):
        cmd = [
            sys.executable,
            __file__,
            "--child",
            "--rows",
            str(args.rows),
            "--levels",
            str(args.levels),
            "--cycle",
            str(args.cycle),
            "--report-level",
            level,
        ]
        completed = subprocess.run(cmd, check=True, capture_output=True, text=True)
        rows.append(json.loads(completed.stdout.strip().splitlines()[-1]))
    if args.json_out:
        Path(args.json_out).write_text(json.dumps(rows, indent=2, sort_keys=True) + "\n")
    if args.md_out:
        lines = [
            "# Phase 34A Native Event Artifact Memory Benchmark",
            "",
            "| report_level | seconds | peak RSS MB | commands | fills | events | command rows | event rows | fills obj | orders obj |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
        for row in rows:
            lines.append(
                "| {report_level} | {seconds:.6f} | {peak_rss_mb:.3f} | {commands} | {fills} | {events} | "
                "{command_report_rows} | {order_event_rows} | {fills_materialized} | {orders_materialized} |".format(**row)
            )
        lines.extend(
            [
                "",
                "Notes:",
                "",
                "- Each row runs in a fresh subprocess.",
                "- Peak RSS includes Python import, pandas, and Numba/cache overhead; on small workloads it is not expected to be monotonic by artifact level.",
                "- The artifact contract is verified by command/event row counts and materialized Python object counts; larger command-heavy runs are needed for stable RSS deltas.",
            ]
        )
        Path(args.md_out).write_text("\n".join(lines) + "\n")
    print(json.dumps(rows, indent=2, sort_keys=True))
    return rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--child", action="store_true")
    parser.add_argument("--rows", type=int, default=5_000)
    parser.add_argument("--levels", type=int, default=15)
    parser.add_argument("--cycle", type=int, default=50)
    parser.add_argument("--report-level", default="audit")
    parser.add_argument("--audit-sink", default="memory")
    parser.add_argument("--audit-sink-path", default=None)
    parser.add_argument("--json-out", default="benchmarks/phase34a_native_event_memory.json")
    parser.add_argument("--md-out", default="benchmarks/phase34a_native_event_memory.md")
    args = parser.parse_args()
    if args.child:
        _run_child(args)
    else:
        _run_parent(args)


if __name__ == "__main__":
    main()
