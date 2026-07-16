#!/usr/bin/env python3
"""Compare Phase 9 optimized paths against legacy-equivalent construction."""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Dict, Optional

import numpy as np
import pandas as pd


PACKAGE_DIR = Path(__file__).resolve().parents[1]
PROJECT_DIR = PACKAGE_DIR.parent
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from quantbt import AccountConfig, BacktestEngineV2, OrderIntent, OrderSide, OrderType, TimeInForce
from quantbt.core.order_compiler import compile_order_intents
from quantbt.sizing.fast import scale_signal_notional_matrix
from quantbt.sizing.modes import compute_target_units


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Run Phase 9 parity checks.")
    parser.add_argument("--json-out", type=Path, default=PACKAGE_DIR / "benchmarks" / "out" / "phase9_parity.json")
    parser.add_argument("--md-out", type=Path, default=PACKAGE_DIR / "benchmarks" / "out" / "phase9_parity.md")
    args = parser.parse_args(argv)

    report = run_parity()
    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    args.md_out.write_text(markdown_report(report), encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["passed"] else 1


def run_parity() -> Dict:
    idx, data, signals = _market()
    symbols = ["A", "B"]
    alloc = {"A": 10_000.0, "B": 5_000.0}

    target_diff = _target_unit_diff(data, signals, symbols, alloc)
    vectorized_diff = _vectorized_result_diff(data, signals, alloc)
    order_diff = _order_array_diff(idx)
    event_diff = _event_result_diff(data, idx)

    report = {
        "target_unit_max_abs_diff": target_diff,
        "vectorized_equity_max_abs_diff": vectorized_diff["equity"],
        "vectorized_position_max_abs_diff": vectorized_diff["positions"],
        "order_array_max_abs_diff": order_diff,
        "event_equity_max_abs_diff": event_diff["equity"],
        "event_order_report_max_abs_diff": event_diff["order_report"],
        "event_fill_count_diff": event_diff["fill_count"],
        "event_fill_price_max_abs_diff": event_diff["fill_price"],
    }
    report["passed"] = all(
        [
            report["target_unit_max_abs_diff"] <= 1e-12,
            report["vectorized_equity_max_abs_diff"] <= 1e-10,
            report["vectorized_position_max_abs_diff"] <= 1e-12,
            report["order_array_max_abs_diff"] <= 0.0,
            report["event_equity_max_abs_diff"] <= 1e-10,
            report["event_order_report_max_abs_diff"] <= 1e-12,
            report["event_fill_count_diff"] == 0,
            report["event_fill_price_max_abs_diff"] <= 1e-12,
        ]
    )
    return report


def _market():
    idx = pd.date_range("2024-01-01", periods=128, freq="15min", tz="UTC")
    grid = np.arange(len(idx), dtype=float)
    close_a = pd.Series(100.0 + np.sin(grid / 7.0) * 2.0 + grid * 0.01, index=idx)
    close_b = pd.Series(50.0 + np.cos(grid / 11.0) * 1.5 + grid * 0.005, index=idx)
    data = {
        "A": pd.DataFrame({"open": close_a, "high": close_a + 0.8, "low": close_a - 0.8, "close": close_a, "volume": 1_000.0}),
        "B": pd.DataFrame({"open": close_b, "high": close_b + 0.5, "low": close_b - 0.5, "close": close_b, "volume": 1_000.0}),
    }
    sig_a = np.where((grid.astype(int) // 9) % 4 == 0, 1.0, np.where((grid.astype(int) // 9) % 4 == 2, -0.5, 0.0))
    sig_b = np.where((grid.astype(int) // 13) % 3 == 0, -1.0, np.where((grid.astype(int) // 13) % 3 == 1, 0.5, 0.0))
    signals = {"A": pd.Series(sig_a, index=idx), "B": pd.Series(sig_b, index=idx)}
    return idx, data, signals


def _orders(idx):
    return [
        OrderIntent(idx[5], "A", OrderSide.BUY, OrderType.MARKET, qty=1.0, tif=TimeInForce.IOC),
        OrderIntent(idx[12], "B", OrderSide.SELL, OrderType.LIMIT, qty=2.0, price=52.0, tif=TimeInForce.GTC),
        OrderIntent(idx[12], "A", OrderSide.SELL, OrderType.MARKET, qty=0.5, tif=TimeInForce.IOC),
        OrderIntent(idx[40], "B", OrderSide.BUY, OrderType.MARKET, qty=2.0, tif=TimeInForce.IOC),
        OrderIntent(idx[90], "A", OrderSide.SELL, OrderType.LIMIT, qty=0.5, price=102.0, tif=TimeInForce.GTC),
    ]


def _target_unit_diff(data, signals, symbols, alloc):
    closes_m = np.column_stack([data[s]["close"].to_numpy(dtype=float) for s in symbols])
    signals_m = np.column_stack([signals[s].to_numpy(dtype=float) for s in symbols])
    allocs = np.array([alloc[s] for s in symbols], dtype=np.float64)
    fast = scale_signal_notional_matrix(signals_m, closes_m, allocs, use_pyramiding=True)
    legacy = np.column_stack(
        [
            compute_target_units("signal_notional", signals[s], data[s]["close"], alloc[s], True).to_numpy()
            for s in symbols
        ]
    )
    return float(np.max(np.abs(fast - legacy)))


def _vectorized_result_diff(data, signals, alloc):
    account = AccountConfig(initial_capital=100_000.0, leverage=5.0)
    fast = BacktestEngineV2(
        data=data,
        signals=signals,
        backend="native_vectorized",
        account=account,
        alloc_per_trade=alloc,
        hedge_type="signal_notional",
        use_funding=False,
    ).result
    target_units = {
        s: compute_target_units("signal_notional", signals[s], data[s]["close"], alloc[s], True)
        for s in signals
    }
    legacy_route = BacktestEngineV2(
        data=data,
        target_units=target_units,
        backend="native_vectorized",
        account=account,
        use_funding=False,
    ).result
    return {
        "equity": float(np.max(np.abs(fast.equity.to_numpy() - legacy_route.equity.to_numpy()))),
        "positions": float(np.max(np.abs(fast.positions.to_numpy() - legacy_route.positions.to_numpy()))),
    }


def _order_array_diff(idx):
    orders = _orders(idx)
    symbol_to_col = {"A": 0, "B": 1}
    compiled = compile_order_intents(idx, orders, symbol_to_col)
    legacy = _legacy_order_arrays(idx, orders, symbol_to_col)
    diffs = [
        np.max(np.abs(compiled.order_ptr - legacy[0])),
        np.max(np.abs(compiled.order_symbol - legacy[1])),
        np.max(np.abs(compiled.order_side - legacy[2])),
        np.max(np.abs(compiled.order_type - legacy[3])),
        np.max(np.abs(compiled.order_qty - legacy[4])),
        np.max(np.abs(compiled.order_price - legacy[5])),
        np.max(np.abs(compiled.order_tif - legacy[6])),
        np.max(np.abs(compiled.original_index - legacy[7])),
    ]
    return float(max(diffs))


def _event_result_diff(data, idx):
    orders = _orders(idx)
    result = BacktestEngineV2(
        data=data,
        orders=orders,
        backend="native_event",
        account=AccountConfig(initial_capital=100_000.0, leverage=5.0),
        use_funding=False,
    ).result
    rerun = BacktestEngineV2(
        data=data,
        orders=orders,
        backend="native_event",
        account=AccountConfig(initial_capital=100_000.0, leverage=5.0),
        use_funding=False,
    ).result
    report = result.metadata["order_report"].sort_values("original_index")
    rerun_report = rerun.metadata["order_report"].sort_values("original_index")
    fill_prices = np.array([fill.price for fill in result.fills], dtype=float)
    rerun_fill_prices = np.array([fill.price for fill in rerun.fills], dtype=float)
    fill_price_diff = 0.0
    if len(fill_prices) or len(rerun_fill_prices):
        if len(fill_prices) != len(rerun_fill_prices):
            fill_price_diff = math.inf
        else:
            fill_price_diff = float(np.max(np.abs(fill_prices - rerun_fill_prices)))
    return {
        "equity": float(np.max(np.abs(result.equity.to_numpy() - rerun.equity.to_numpy()))),
        "order_report": float(np.max(np.abs(report.to_numpy(dtype=float) - rerun_report.to_numpy(dtype=float)))),
        "fill_count": int(len(result.fills) - len(rerun.fills)),
        "fill_price": fill_price_diff,
    }


def _legacy_order_arrays(idx, orders, symbol_to_col):
    def bar_index(timestamp):
        ts = pd.Timestamp(timestamp)
        if ts.tz is None:
            ts = ts.tz_localize("UTC")
        else:
            ts = ts.tz_convert("UTC")
        pos = idx.searchsorted(ts, side="left")
        if pos >= len(idx):
            raise ValueError("order timestamp is after the available data")
        return int(pos)

    sorted_orders = sorted(enumerate(orders), key=lambda item: bar_index(item[1].timestamp))
    n = len(sorted_orders)
    order_bar = np.zeros(n, dtype=np.int64)
    order_symbol = np.zeros(n, dtype=np.int64)
    order_side = np.zeros(n, dtype=np.int64)
    order_type = np.zeros(n, dtype=np.int64)
    order_qty = np.zeros(n, dtype=np.float64)
    order_price = np.zeros(n, dtype=np.float64)
    order_tif = np.zeros(n, dtype=np.int64)
    original_index = np.zeros(n, dtype=np.int64)
    for k, (orig_idx, order) in enumerate(sorted_orders):
        order_bar[k] = bar_index(order.timestamp)
        order_symbol[k] = symbol_to_col[order.symbol]
        order_side[k] = 1 if order.side is OrderSide.BUY else -1
        order_type[k] = 0 if order.order_type is OrderType.MARKET else 1
        order_qty[k] = order.qty
        order_price[k] = 0.0 if order.price is None else order.price
        order_tif[k] = {TimeInForce.GTC: 0, TimeInForce.IOC: 1, TimeInForce.FOK: 2, TimeInForce.GTD: 3}[order.tif]
        original_index[k] = orig_idx
    order_ptr = np.zeros(len(idx) + 1, dtype=np.int64)
    for bar in order_bar:
        order_ptr[bar + 1] += 1
    for i in range(1, len(order_ptr)):
        order_ptr[i] += order_ptr[i - 1]
    return order_ptr, order_symbol, order_side, order_type, order_qty, order_price, order_tif, original_index


def markdown_report(report: Dict) -> str:
    lines = [
        "# Phase 9 Optimization Parity Report",
        "",
        f"Passed: `{report['passed']}`",
        "",
        "| check | value |",
        "| --- | ---: |",
    ]
    for key, value in report.items():
        if key == "passed":
            continue
        lines.append(f"| `{key}` | {value} |")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
