from __future__ import annotations

import argparse
import json
import os
import resource
import sys
import time
from pathlib import Path
from statistics import mean

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from quantbt import AccountConfig, ExecutionConfig, NativeEventBackend, NativeEventConfig, OrderCommand, OrderSide, OrderType, QuantBTEndpoint, TimeInForce  # noqa: E402


def _rss_mb() -> float:
    status = Path("/proc/self/status")
    if status.exists():
        for line in status.read_text().splitlines():
            if line.startswith("VmRSS:"):
                return float(line.split()[1]) / 1024.0
    return float(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss) / 1024.0


def _bars(n: int, *, symbols: tuple[str, ...] = ("BTC",)):
    idx = pd.date_range("2024-01-01", periods=n, freq="1min", tz="UTC")
    x = np.arange(n, dtype=np.float64)
    base = 100.0 + np.sin(x / 41.0) * 2.0 + x * 0.0002
    out = {}
    for j, symbol in enumerate(symbols):
        scale = 1.0 + j * 0.17
        close = pd.Series(base * scale, index=idx)
        out[symbol] = pd.DataFrame(
            {
                "open": close.shift(1).fillna(close.iloc[0]),
                "high": close + 1.25 * scale,
                "low": close - 1.25 * scale,
                "close": close,
                "volume": 10_000.0 + x,
            },
            index=idx,
        )
    return out[symbols[0]] if len(symbols) == 1 else out


class PeriodicStrategy:
    def __init__(self, *, every: int, hold: int, symbols: tuple[str, ...] = ("BTC",), bracket: bool = False, gtd: bool = False):
        self.every = int(every)
        self.hold = int(hold)
        self.symbols = symbols
        self.bracket = bool(bracket)
        self.gtd = bool(gtd)

    def on_bar_close(self, context):
        commands = []
        bar = int(context.bar_index)
        for j, symbol in enumerate(self.symbols):
            if bar % self.every == 0:
                oid = f"{symbol}-entry-{bar}"
                commands.append(
                    OrderCommand(
                        timestamp=context.timestamp,
                        symbol=symbol,
                        side=OrderSide.BUY if j % 2 == 0 else OrderSide.SELL,
                        order_type=OrderType.MARKET,
                        qty=0.25,
                        tif=TimeInForce.IOC,
                        order_id=oid,
                    )
                )
                if self.bracket:
                    px = float(context.close[j])
                    commands.append(
                        OrderCommand(
                            timestamp=context.timestamp,
                            symbol=symbol,
                            side=OrderSide.SELL if j % 2 == 0 else OrderSide.BUY,
                            order_type=OrderType.LIMIT,
                            qty=0.25,
                            price=px + (0.75 if j % 2 == 0 else -0.75),
                            reduce_only=True,
                            parent_order_id=oid,
                            order_id=f"{symbol}-tp-{bar}",
                        )
                    )
            if bar > 0 and bar % self.every == self.hold:
                commands.append(
                    OrderCommand(
                        timestamp=context.timestamp,
                        symbol=symbol,
                        side=OrderSide.SELL if j % 2 == 0 else OrderSide.BUY,
                        order_type=OrderType.MARKET,
                        qty=0.25,
                        tif=TimeInForce.IOC,
                        reduce_only=True,
                        order_id=f"{symbol}-exit-{bar}",
                    )
                )
            if self.gtd and bar % (self.every * 2) == 1:
                commands.append(
                    OrderCommand(
                        timestamp=context.timestamp,
                        symbol=symbol,
                        side=OrderSide.BUY,
                        order_type=OrderType.LIMIT,
                        qty=0.1,
                        price=1.0,
                        tif=TimeInForce.GTD,
                        expires_at=pd.Timestamp(context.timestamp) + pd.Timedelta(minutes=5),
                        order_id=f"{symbol}-gtd-{bar}",
                    )
                )
        return commands


class R1PeriodicStrategy:
    """Single-symbol GTC-only workload inside the PyO3 R1 support contract."""

    def __init__(self, *, every: int, hold: int):
        self.every = int(every)
        self.hold = int(hold)

    def on_bar_close(self, context):
        bar = int(context.bar_index)
        if bar % self.every == 0:
            return [
                OrderCommand(
                    timestamp=context.timestamp,
                    symbol="BTC",
                    side=OrderSide.BUY,
                    order_type=OrderType.MARKET,
                    qty=0.05,
                    tif=TimeInForce.GTC,
                    order_id=f"r1-entry-{bar}",
                )
            ]
        if bar > 0 and bar % self.every == self.hold:
            return [
                OrderCommand(
                    timestamp=context.timestamp,
                    symbol="BTC",
                    side=OrderSide.SELL,
                    order_type=OrderType.MARKET,
                    qty=0.05,
                    tif=TimeInForce.GTC,
                    order_id=f"r1-exit-{bar}",
                )
            ]
        return []


def _run_case(
    name: str,
    n_bars: int,
    strategy,
    symbols: tuple[str, ...] = ("BTC",),
    repeats: int = 1,
    prepared_score: bool = False,
    backend: str = "python",
):
    data = _bars(n_bars, symbols=symbols)
    endpoint = QuantBTEndpoint.native_event_strategy(
        initial_capital=100_000,
        leverage=5,
        maintenance_ratio=0.0 if backend == "rust" else 0.005,
        use_funding=False,
        fee_rate=0.0002,
        report_level="minimal" if prepared_score else "audit",
        reactive_kernel_mode="single_pass",
    )
    rss_before = _rss_mb()
    t0 = time.perf_counter()
    c0 = time.process_time()
    result = None
    if prepared_score:
        prepared = endpoint.prepare_native_event_strategy(data=data, symbols=list(symbols))
        scores = []
        for _ in range(repeats):
            score = prepared.score(strategy)
            scores.append(float(score.equity[-1]))
        event_count = 0
        command_count = 0
        fill_count = 0
        max_active_orders = 0
        final_equity = mean(scores)
    elif len(symbols) > 1:
        idx = next(iter(data.values())).index
        commands = []
        for bar in range(1, n_bars - 1, 250):
            for j, symbol in enumerate(symbols):
                commands.append(
                    OrderCommand(
                        timestamp=idx[bar],
                        symbol=symbol,
                        side=OrderSide.BUY if j % 2 == 0 else OrderSide.SELL,
                        order_type=OrderType.MARKET,
                        qty=0.25,
                        tif=TimeInForce.IOC,
                        order_id=f"{symbol}-entry-{bar}",
                    )
                )
                exit_bar = min(bar + 20, n_bars - 1)
                commands.append(
                    OrderCommand(
                        timestamp=idx[exit_bar],
                        symbol=symbol,
                        side=OrderSide.SELL if j % 2 == 0 else OrderSide.BUY,
                        order_type=OrderType.MARKET,
                        qty=0.25,
                        tif=TimeInForce.IOC,
                        reduce_only=True,
                        order_id=f"{symbol}-exit-{exit_bar}",
                    )
                )
        backend = NativeEventBackend(
            NativeEventConfig(
                account=AccountConfig(initial_capital=100_000, leverage=5),
                execution=ExecutionConfig(slippage_bps=0.0),
                fee_rate=0.0002,
                use_funding=False,
                report_level="audit",
            )
        )
        result = backend.run_order_commands(
            idx,
            commands,
            closes={symbol: frame["close"] for symbol, frame in data.items()},
            highs={symbol: frame["high"] for symbol, frame in data.items()},
            lows={symbol: frame["low"] for symbol, frame in data.items()},
            symbols=list(symbols),
        )
        counters = result.metadata.get("lifecycle_counters", {})
        command_count = int(len(commands))
        event_count = int(counters.get("event_count", 0))
        fill_count = int(counters.get("fill_count", 0))
        max_active_orders = int(len(result.metadata.get("active_orders", ())))
        final_equity = float(result.equity.iloc[-1])
    else:
        result = endpoint.simulate(data=data, strategy=strategy, symbols=list(symbols))
        counters = result.metadata.get("lifecycle_counters", {})
        command_count = int(counters.get("filled_command_count", 0) + counters.get("pending_command_count", 0) + counters.get("rejected_count", 0) + counters.get("canceled_count", 0))
        event_count = int(counters.get("event_count", 0))
        fill_count = int(counters.get("fill_count", 0))
        max_active_orders = int(len(result.metadata.get("active_orders", ())))
        final_equity = float(result.equity.iloc[-1])
    cpu = time.process_time() - c0
    wall = time.perf_counter() - t0
    rss_after = _rss_mb()
    return {
        "name": name,
        "bars": n_bars,
        "symbols": len(symbols),
        "repeats": repeats,
        "wall_seconds": wall,
        "cpu_seconds": cpu,
        "peak_rss_mb": float(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss) / 1024.0,
        "post_run_rss_mb": rss_after,
        "rss_delta_mb": rss_after - rss_before,
        "command_count": command_count,
        "event_count": event_count,
        "fill_count": fill_count,
        "max_active_orders": max_active_orders,
        "final_equity": final_equity,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark Python or PyO3 native-event reactive session paths")
    parser.add_argument("--backend", choices=("python", "rust"), default="python")
    parser.add_argument("--r1-only", action="store_true", help="run only the single-symbol R1-compatible comparison cases")
    args = parser.parse_args()
    os.environ["QUANTBT_NATIVE_BACKEND"] = args.backend

    cases = [
        ("25k_low_orders", 25_000, PeriodicStrategy(every=2_000, hold=20), ("BTC",), 1, False),
        ("25k_high_churn", 25_000, PeriodicStrategy(every=40, hold=8), ("BTC",), 1, False),
        ("100k_low_orders", 100_000, PeriodicStrategy(every=8_000, hold=20), ("BTC",), 1, False),
        ("100k_high_churn", 100_000, PeriodicStrategy(every=200, hold=20), ("BTC",), 1, False),
        ("parent_oco_heavy", 25_000, PeriodicStrategy(every=80, hold=16, bracket=True), ("BTC",), 1, False),
        ("gtd_heavy", 25_000, PeriodicStrategy(every=120, hold=12, gtd=True), ("BTC",), 1, False),
        ("multi_symbol", 25_000, PeriodicStrategy(every=250, hold=20, symbols=("BTC", "ETH")), ("BTC", "ETH"), 1, False),
        ("prepared_100_scores", 5_000, PeriodicStrategy(every=500, hold=20), ("BTC",), 100, True),
    ]
    if args.backend == "rust":
        cases = [
            ("r1_25k_low_orders", 25_000, R1PeriodicStrategy(every=2_000, hold=20), ("BTC",), 1, False),
            ("r1_25k_high_churn", 25_000, R1PeriodicStrategy(every=40, hold=8), ("BTC",), 1, False),
        ]
    elif args.r1_only:
        cases = [
            ("r1_25k_low_orders", 25_000, R1PeriodicStrategy(every=2_000, hold=20), ("BTC",), 1, False),
            ("r1_25k_high_churn", 25_000, R1PeriodicStrategy(every=40, hold=8), ("BTC",), 1, False),
        ]
    results = [_run_case(*case, backend=args.backend) for case in cases]
    payload = {"benchmark": f"native_event_reactive_session_{args.backend}", "results": results}
    suffix = "r1_python" if args.backend == "python" and args.r1_only else ("baseline" if args.backend == "python" else "r1_rust")
    out_json = Path(__file__).with_name(f"reactive_session_{suffix}.json")
    out_md = Path(__file__).with_name(f"reactive_session_{suffix}.md")
    out_json.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    lines = ["# Native Event Reactive Session Baseline", "", "| Case | Bars | Symbols | Wall s | CPU s | Peak RSS MB | Commands | Events | Fills |", "|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for row in results:
        lines.append(
            "| {name} | {bars} | {symbols} | {wall_seconds:.4f} | {cpu_seconds:.4f} | {peak_rss_mb:.2f} | {command_count} | {event_count} | {fill_count} |".format(
                **row
            )
        )
    out_md.write_text("\n".join(lines) + "\n")
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
