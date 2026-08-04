"""Fresh-process RSS and parity gate for prepared native-event scoring."""

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

from quantbt import QuantBTEndpoint
from quantbt.core.orders import OrderCommand
from quantbt.core.schema import OrderSide, OrderType, TimeInForce


def _rss_mb() -> float:
    status = Path("/proc/self/status")
    if status.exists():
        for line in status.read_text().splitlines():
            if line.startswith("VmHWM:"):
                return float(line.split()[1]) / 1024.0
    return float(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss) / 1024.0


def _data(rows: int) -> pd.DataFrame:
    index = pd.date_range("2024-01-01", periods=rows, freq="1min", tz="UTC")
    values = 100.0 + np.sin(np.arange(rows) / 17.0) + np.arange(rows) * 0.0001
    close = pd.Series(values, index=index)
    return pd.DataFrame({"open": close, "high": close + 1.0, "low": close - 1.0, "close": close, "volume": 1_000.0}, index=index)


class _Strategy:
    def on_bar_close(self, context):
        symbol = context.symbols[0]
        if context.bar_index % 20 == 0:
            return [OrderCommand(timestamp=context.timestamp, symbol=symbol, side=OrderSide.BUY, order_type=OrderType.MARKET, qty=0.1, tif=TimeInForce.IOC, order_id=f"b-{context.bar_index}")]
        if context.bar_index % 20 == 5 and context.positions[symbol] > 0.0:
            return [OrderCommand(timestamp=context.timestamp, symbol=symbol, side=OrderSide.SELL, order_type=OrderType.MARKET, qty=0.1, reduce_only=True, tif=TimeInForce.IOC, order_id=f"s-{context.bar_index}")]
        return []


def _child(rows: int, repeats: int, mode: str) -> dict:
    endpoint = QuantBTEndpoint.native_event_strategy(initial_capital=50_000, leverage=5, use_funding=False, fee_rate=0.0002, reactive_kernel_mode="single_pass")
    prepared = endpoint.prepare_native_event_strategy(data=_data(rows), symbols=["BTC"])
    # Compile/cache warm-up is outside measurements by contract.
    prepared.score(_Strategy())
    start = time.perf_counter()
    final_equity = 0.0
    for _ in range(repeats):
        if mode == "score":
            final_equity = float(prepared.score(_Strategy()).metrics["final_equity"])
        else:
            final_equity = float(prepared.run(_Strategy(), report_level="audit").equity.iloc[-1])
    return {"mode": mode, "rows": rows, "repeats": repeats, "seconds": time.perf_counter() - start, "peak_rss_mb": _rss_mb(), "final_equity": final_equity, "endpoint_result_retained": endpoint.result is not None}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--child", action="store_true")
    parser.add_argument("--mode", choices=("score", "audit"), default="score")
    parser.add_argument("--rows", type=int, default=2_000)
    parser.add_argument("--repeats", type=int, default=100)
    parser.add_argument("--json-out", default="benchmarks/phase45b_native_event_score_rss.json")
    args = parser.parse_args()
    if args.child:
        print(json.dumps(_child(args.rows, args.repeats, args.mode), sort_keys=True))
        return
    rows = []
    for mode in ("score", "audit"):
        completed = subprocess.run([sys.executable, __file__, "--child", "--mode", mode, "--rows", str(args.rows), "--repeats", str(args.repeats)], check=True, capture_output=True, text=True)
        rows.append(json.loads(completed.stdout.strip().splitlines()[-1]))
    score, audit = rows
    payload = {"runs": rows, "parity": bool(np.isclose(score["final_equity"], audit["final_equity"], rtol=0.0, atol=1e-12)), "score_faster_than_audit": bool(score["seconds"] < audit["seconds"]), "score_rss_not_higher_than_audit": bool(score["peak_rss_mb"] <= audit["peak_rss_mb"])}
    Path(args.json_out).write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
