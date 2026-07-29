from __future__ import annotations

import argparse
import json
import resource
import time
from pathlib import Path

import numpy as np
import pandas as pd

from quantbt import OrderCommand, QuantBTEndpoint
from quantbt.core.schema import OrderSide, OrderType, TimeInForce


def _rss_mb() -> float:
    return float(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss) / 1024.0


def _bars(rows: int) -> pd.DataFrame:
    idx = pd.date_range("2020-01-01", periods=rows, freq="1h", tz="UTC")
    x = np.arange(rows, dtype=np.float64)
    close = pd.Series(100.0 + np.sin(x / 9.0) * 3.0 + np.cos(x / 23.0) * 1.5, index=idx)
    return pd.DataFrame(
        {
            "open": close.shift(1).fillna(close.iloc[0]),
            "high": close + 2.5,
            "low": close - 2.5,
            "close": close,
            "volume": 1_000.0 + (x % 50.0),
        },
        index=idx,
    )


class CyclicStrategy:
    def __init__(self, entry_mod: int, hold: int, qty: float):
        self.entry_mod = int(entry_mod)
        self.hold = int(hold)
        self.qty = float(qty)
        self.open_bar = -1

    def on_bar_close(self, context):
        symbol = context.symbols[0]
        if context.positions[symbol] == 0.0 and context.bar_index % self.entry_mod == 0:
            self.open_bar = int(context.bar_index)
            return [
                OrderCommand(
                    timestamp=context.timestamp,
                    symbol=symbol,
                    side=OrderSide.BUY,
                    order_type=OrderType.MARKET,
                    qty=self.qty,
                    tif=TimeInForce.IOC,
                    order_id=f"entry-{context.bar_index}",
                )
            ]
        if context.positions[symbol] > 0.0 and self.open_bar >= 0 and context.bar_index - self.open_bar >= self.hold:
            self.open_bar = -1
            return [
                OrderCommand(
                    timestamp=context.timestamp,
                    symbol=symbol,
                    side=OrderSide.SELL,
                    order_type=OrderType.MARKET,
                    qty=abs(context.positions[symbol]),
                    tif=TimeInForce.IOC,
                    reduce_only=True,
                    order_id=f"exit-{context.bar_index}",
                )
            ]
        return []


def _params(trials: int):
    return [
        {
            "entry_mod": 4 + (i % 9),
            "hold": 2 + (i % 6),
            "qty": 0.1 + (i % 5) * 0.025,
        }
        for i in range(trials)
    ]


def _accounting_tuple(result) -> tuple:
    return (
        tuple(np.round(result.equity.to_numpy(dtype=np.float64), 12)),
        tuple(np.round(result.returns.to_numpy(dtype=np.float64), 12)),
        tuple(np.round(result.positions.to_numpy(dtype=np.float64).ravel(), 12)),
        tuple(np.round(result.fees.to_numpy(dtype=np.float64), 12)),
        tuple(np.round(result.funding.to_numpy(dtype=np.float64), 12)),
        tuple(np.round(result.margin.to_numpy(dtype=np.float64).ravel(), 12)),
        bool(result.liquidated),
        int(result.liquidation_bar),
    )


def run(rows: int, trials: int) -> dict:
    df = _bars(rows)
    params = _params(trials)
    kwargs = dict(
        initial_capital=50_000,
        leverage=10,
        use_funding=False,
        fee_rate=0.0002,
        report_level="minimal",
    )

    replay_endpoint = QuantBTEndpoint.native_event_strategy(**kwargs, reactive_kernel_mode="replay_certified")
    start = time.perf_counter()
    replay_fingerprints = []
    replay_static_replays = 0
    for param in params:
        result = replay_endpoint.simulate(data=df, strategy=CyclicStrategy(**param), symbols=["BTC"])
        replay_fingerprints.append(_accounting_tuple(result))
        replay_static_replays += int(result.metadata.get("reactive_static_replay_count", 0))
    replay_seconds = time.perf_counter() - start

    single_endpoint = QuantBTEndpoint.native_event_strategy(**kwargs, reactive_kernel_mode="single_pass")
    start = time.perf_counter()
    single_fingerprints = []
    single_static_replays = 0
    for param in params:
        result = single_endpoint.simulate(data=df, strategy=CyclicStrategy(**param), symbols=["BTC"])
        single_fingerprints.append(_accounting_tuple(result))
        single_static_replays += int(result.metadata.get("reactive_static_replay_count", 0))
    single_seconds = time.perf_counter() - start

    return {
        "rows": int(rows),
        "trials": int(trials),
        "replay_certified_seconds": float(replay_seconds),
        "single_pass_seconds": float(single_seconds),
        "speedup": float(replay_seconds / single_seconds) if single_seconds > 0.0 else np.inf,
        "replay_certified_static_replays": int(replay_static_replays),
        "single_pass_static_replays": int(single_static_replays),
        "accounting_parity": bool(replay_fingerprints == single_fingerprints),
        "peak_rss_mb": float(_rss_mb()),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rows", type=int, default=1_000)
    parser.add_argument("--trials", type=int, default=20)
    parser.add_argument("--json-out", default="benchmarks/phase34c_native_event_single_pass.json")
    parser.add_argument("--md-out", default="benchmarks/phase34c_native_event_single_pass.md")
    args = parser.parse_args()
    payload = run(rows=args.rows, trials=args.trials)
    json_path = Path(args.json_out)
    md_path = Path(args.md_out)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    lines = [
        "# Phase 34C Native Event Single-Pass Benchmark",
        "",
        f"- Rows: `{payload['rows']}`",
        f"- Trials: `{payload['trials']}`",
        f"- Replay-certified seconds: `{payload['replay_certified_seconds']:.6f}`",
        f"- Single-pass seconds: `{payload['single_pass_seconds']:.6f}`",
        f"- Speedup: `{payload['speedup']:.3f}x`",
        f"- Replay-certified static replays: `{payload['replay_certified_static_replays']}`",
        f"- Single-pass static replays: `{payload['single_pass_static_replays']}`",
        f"- Accounting parity: `{payload['accounting_parity']}`",
        f"- Peak RSS MB: `{payload['peak_rss_mb']:.3f}`",
        "",
        "This benchmark isolates the Phase 34C mode switch: `single_pass` materializes accounting from the reactive session for minimal/score runs and skips the final static replay.",
    ]
    md_path.write_text("\n".join(lines) + "\n")
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
