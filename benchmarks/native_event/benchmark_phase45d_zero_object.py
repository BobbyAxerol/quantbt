"""Fresh-process benchmark for the Phase 45D Python score contracts.

The benchmark separates the compatibility ndarray score from the scalar
zero-retention score and the audit oracle.  It intentionally warms each mode
before timing so first-use imports/Numba compilation are not misreported as
execution speed.
"""

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

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from quantbt import NativeCommandBatch, NativeEventScoreRequirements, OrderCommand, OrderSide, OrderType, QuantBTEndpoint, TimeInForce  # noqa: E402


def _rss_mb() -> float:
    status = Path("/proc/self/status")
    if status.exists():
        for line in status.read_text().splitlines():
            if line.startswith("VmHWM:"):
                return float(line.split()[1]) / 1024.0
    return float(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss) / 1024.0


def _data(rows: int) -> pd.DataFrame:
    idx = pd.date_range("2024-01-01", periods=rows, freq="1min", tz="UTC")
    x = np.arange(rows, dtype=np.float64)
    close = pd.Series(100.0 + np.sin(x / 41.0) * 2.0 + x * 0.0002, index=idx)
    return pd.DataFrame(
        {
            "open": close,
            "high": close + 1.25,
            "low": close - 1.25,
            "close": close,
            "volume": 10_000.0 + x,
        },
        index=idx,
    )


class HighChurnStrategy:
    # This workload does not inspect callback payloads, so it opts out of
    # transient fill/event/order snapshot objects for the scalar score.
    native_context_requirements = {
        "fills": False,
        "events": False,
        "active_orders": False,
        "positions": False,
        "margin": False,
    }

    def on_bar_close(self, context):
        bar = int(context.bar_index)
        if bar % 20 == 0:
            return NativeCommandBatch.from_commands(
                (
                    OrderCommand(
                        timestamp=context.timestamp,
                        symbol="BTC",
                        side=OrderSide.BUY,
                        order_type=OrderType.MARKET,
                        qty=0.05,
                        tif=TimeInForce.IOC,
                        order_id=f"entry-{bar}",
                    ),
                )
            )
        if bar % 20 == 5:
            return (
                OrderCommand(
                    timestamp=context.timestamp,
                    symbol="BTC",
                    side=OrderSide.SELL,
                    order_type=OrderType.MARKET,
                    qty=0.05,
                    reduce_only=True,
                    tif=TimeInForce.IOC,
                    order_id=f"exit-{bar}",
                ),
            )
        return ()


def _child(mode: str, rows: int, repeats: int) -> dict:
    endpoint = QuantBTEndpoint.native_event_strategy(
        initial_capital=50_000,
        leverage=5,
        maintenance_ratio=0.005,
        use_funding=False,
        fee_rate=0.0002,
        report_level="audit",
        reactive_kernel_mode="single_pass",
    )
    prepared = endpoint.prepare_native_event_strategy(data=_data(rows), symbols=["BTC"])

    def run_once():
        strategy = HighChurnStrategy()
        if mode == "audit":
            return float(prepared.run(strategy, report_level="audit").equity.iloc[-1])
        if mode == "compat_score":
            return float(prepared.score(strategy).metrics["final_equity"])
        requirements = NativeEventScoreRequirements.from_strategy(
            strategy,
            base=NativeEventScoreRequirements.scalar_score_contract(),
        )
        return float(prepared.score(strategy, score_requirements=requirements).metrics["final_equity"])

    run_once()  # warm imports, allocator, and Numba path
    start = time.perf_counter()
    final_equity = 0.0
    for _ in range(int(repeats)):
        final_equity = run_once()
    return {
        "mode": mode,
        "rows": int(rows),
        "repeats": int(repeats),
        "seconds": float(time.perf_counter() - start),
        "peak_rss_mb": float(_rss_mb()),
        "final_equity": final_equity,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--child", action="store_true")
    parser.add_argument("--mode", choices=("audit", "compat_score", "scalar_score"), default="scalar_score")
    parser.add_argument("--rows", type=int, default=100_000)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--json-out", default="benchmarks/native_event/phase45d_zero_object.json")
    args = parser.parse_args()
    if args.child:
        print(json.dumps(_child(args.mode, args.rows, args.repeats), sort_keys=True))
        return

    runs = []
    for mode in ("audit", "compat_score", "scalar_score"):
        completed = subprocess.run(
            [
                sys.executable,
                __file__,
                "--child",
                "--mode",
                mode,
                "--rows",
                str(args.rows),
                "--repeats",
                str(args.repeats),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        runs.append(json.loads(completed.stdout.strip().splitlines()[-1]))
    by_mode = {row["mode"]: row for row in runs}
    audit_equity = by_mode["audit"]["final_equity"]
    scalar_equity = by_mode["scalar_score"]["final_equity"]
    payload = {
        "runs": runs,
        "parity": bool(np.isclose(audit_equity, scalar_equity, rtol=0.0, atol=1e-12)),
        "scalar_faster_than_compat": bool(
            by_mode["scalar_score"]["seconds"] < by_mode["compat_score"]["seconds"]
        ),
        "scalar_rss_below_compat": bool(
            by_mode["scalar_score"]["peak_rss_mb"] < by_mode["compat_score"]["peak_rss_mb"]
        ),
    }
    Path(args.json_out).write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
