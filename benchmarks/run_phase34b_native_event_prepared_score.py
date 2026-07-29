from __future__ import annotations

import argparse
import json
import resource
import time
from pathlib import Path

import numpy as np
import pandas as pd

from quantbt import QuantBTEndpoint
from quantbt.core.orders import OrderCommand
from quantbt.core.schema import OrderSide, OrderType, TimeInForce


def _rss_mb() -> float:
    return float(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss) / 1024.0


def _bars(rows: int) -> pd.DataFrame:
    idx = pd.date_range("2020-01-01", periods=rows, freq="1h", tz="UTC")
    x = np.arange(rows, dtype=np.float64)
    close = pd.Series(100.0 + np.sin(x / 11.0) * 2.0 + x * 0.001, index=idx)
    return pd.DataFrame(
        {
            "open": close,
            "high": close + 2.0,
            "low": close - 2.0,
            "close": close,
            "volume": 1_000.0,
        },
        index=idx,
    )


class TimedStrategy:
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
            "entry_mod": 5 + (i % 7),
            "hold": 2 + (i % 5),
            "qty": 0.1 + (i % 4) * 0.05,
        }
        for i in range(trials)
    ]


def _metrics_subset(report: dict) -> dict:
    return {
        "sharpe": report["sharpe"],
        "max_drawdown_pct": report["max_drawdown_pct"],
        "profit_factor": report["profit_factor"],
        "num_trades": report["num_trades"],
        "final_equity": report["final_equity"],
        "liquidated": report["liquidated"],
    }


def run(rows: int, trials: int) -> dict:
    df = _bars(rows)
    params = _params(trials)
    public_endpoint = QuantBTEndpoint.native_event_strategy(
        initial_capital=50_000,
        leverage=10,
        use_funding=False,
        fee_rate=0.0002,
        report_level="audit",
    )
    start = time.perf_counter()
    public_reports = []
    for param in params:
        result = public_endpoint.simulate(data=df, strategy=TimedStrategy(**param), symbols=["BTC"])
        public_reports.append(_metrics_subset(result.full_report(scope="full")))
    public_seconds = time.perf_counter() - start

    prepared_endpoint = QuantBTEndpoint.native_event_strategy(
        initial_capital=50_000,
        leverage=10,
        use_funding=False,
        fee_rate=0.0002,
        report_level="audit",
    )
    prepared = prepared_endpoint.prepare_native_event_strategy(data=df, symbols=["BTC"])
    start = time.perf_counter()
    score_reports = []
    for param in params:
        score = prepared.score(TimedStrategy(**param))
        score_reports.append(_metrics_subset(score.metrics))
    prepared_seconds = time.perf_counter() - start

    parity = public_reports == score_reports
    return {
        "rows": int(rows),
        "trials": int(trials),
        "public_audit_seconds": float(public_seconds),
        "prepared_score_seconds": float(prepared_seconds),
        "speedup": float(public_seconds / prepared_seconds) if prepared_seconds > 0.0 else np.inf,
        "peak_rss_mb": float(_rss_mb()),
        "metric_parity": bool(parity),
        "prepared_scores": int(prepared.metadata["scores"]),
        "public_last_report_level": public_endpoint.result.metadata["report_level"],
        "prepared_endpoint_result_retained": prepared_endpoint.result is not None,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rows", type=int, default=1_000)
    parser.add_argument("--trials", type=int, default=20)
    parser.add_argument("--json-out", default="benchmarks/phase34b_native_event_prepared_score.json")
    parser.add_argument("--md-out", default="benchmarks/phase34b_native_event_prepared_score.md")
    args = parser.parse_args()
    payload = run(rows=args.rows, trials=args.trials)
    Path(args.json_out).write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    lines = [
        "# Phase 34B Native Event Prepared Score Benchmark",
        "",
        f"- Rows: `{payload['rows']}`",
        f"- Trials: `{payload['trials']}`",
        f"- Public audit seconds: `{payload['public_audit_seconds']:.6f}`",
        f"- Prepared score seconds: `{payload['prepared_score_seconds']:.6f}`",
        f"- Speedup: `{payload['speedup']:.3f}x`",
        f"- Peak RSS MB: `{payload['peak_rss_mb']:.3f}`",
        f"- Metric parity: `{payload['metric_parity']}`",
        f"- Prepared endpoint result retained: `{payload['prepared_endpoint_result_retained']}`",
        "",
        "Prepared score reuses market arrays and returns `NativeEventScoreResult` rather than storing full public artifacts on the endpoint.",
    ]
    Path(args.md_out).write_text("\n".join(lines) + "\n")
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
