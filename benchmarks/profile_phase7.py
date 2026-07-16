#!/usr/bin/env python3
"""
Phase 7 profiling follow-up.

This script decomposes the two Phase 7 threshold misses into timing buckets so
optimization work can target the real layer: pandas normalization, ndarray
packing, order-array construction, pure Numba kernels, or result/report
construction.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple


PACKAGE_DIR = Path(__file__).resolve().parents[1]
PROJECT_DIR = PACKAGE_DIR.parent
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from quantbt.benchmarks.run_phase7 import PROFILES, BenchmarkProfile, _make_market_frames, _make_orders, _make_signals


@dataclass(frozen=True)
class ProfileStage:
    backend: str
    profile: str
    stage: str
    seconds: float
    percent_of_profile: float
    repeats: int
    notes: str = ""


@dataclass(frozen=True)
class BackendProfile:
    backend: str
    profile: str
    bars: int
    symbols: int
    orders: int
    total_seconds: float
    stages: List[ProfileStage]


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Profile QuantBT Phase 7 backend layers.")
    parser.add_argument("--profile", choices=sorted(PROFILES), default="smoke")
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--json-out", type=Path, default=PACKAGE_DIR / "benchmarks" / "out" / "phase7_profile.json")
    parser.add_argument("--md-out", type=Path, default=PACKAGE_DIR / "benchmarks" / "out" / "phase7_profile.md")
    args = parser.parse_args(argv)

    base = PROFILES[args.profile]
    profile = BenchmarkProfile(
        name=base.name,
        bars=base.bars,
        symbols=base.symbols,
        order_count=base.order_count,
        repeats=max(1, int(args.repeats)),
    )
    records = [profile_native_vectorized(profile), profile_native_event(profile)]
    write_outputs(records, args.json_out, args.md_out)
    for record in records:
        print(f"{record.backend}: total={record.total_seconds:.6f}s")
        for stage in record.stages:
            print(f"  {stage.stage}: {stage.seconds:.6f}s ({stage.percent_of_profile:.1f}%)")
    return 0


def profile_native_vectorized(profile: BenchmarkProfile) -> BackendProfile:
    import numpy as np
    import pandas as pd

    from quantbt import AccountConfig, ExecutionConfig
    from quantbt.core.preprocessor import align_series, build_arrays, prepare_funding, validate_datetime
    from quantbt.core.results import BacktestResultV2
    from quantbt.core.vectorized import _engine_units_v2
    from quantbt.sizing.modes import compute_target_units

    idx, frames = _make_market_frames(profile.bars, profile.symbols)
    signals = _make_signals(idx, profile.symbols)
    symbols = list(frames.keys())
    account = AccountConfig(initial_capital=1_000_000.0, leverage=10.0)
    execution = ExecutionConfig()

    def normalize():
        local_idx = validate_datetime(idx)
        closes = {symbol: frames[symbol]["close"] for symbol in symbols}
        highs = {symbol: frames[symbol]["high"] for symbol in symbols}
        lows = {symbol: frames[symbol]["low"] for symbol in symbols}
        close_dict = align_series(closes, symbols, local_idx)
        high_dict = align_series(highs, symbols, local_idx, fallback=close_dict)
        low_dict = align_series(lows, symbols, local_idx, fallback=close_dict)
        signal_dict = align_series(signals, symbols, local_idx, fill_val=0.0)
        funding_dict = prepare_funding(0.0, symbols, local_idx)
        return local_idx, close_dict, high_dict, low_dict, signal_dict, funding_dict

    idx_n, close_dict, high_dict, low_dict, signal_dict, funding_dict = normalize()

    def size_targets():
        return {
            symbol: compute_target_units(
                hedge_type="signal_notional",
                signal=signal_dict[symbol],
                close=close_dict[symbol],
                alloc=10_000.0,
                use_pyramiding=True,
            )
            for symbol in symbols
        }

    target_units = size_targets()

    def pack_arrays():
        return build_arrays(
            symbols=symbols,
            idx=idx_n,
            closes_dict=close_dict,
            highs_dict=high_dict,
            lows_dict=low_dict,
            signals_dict=target_units,
            funding_dict=funding_dict,
        )

    closes_m, highs_m, lows_m, target_m, funding_m, is_funding = pack_arrays()
    leverages = np.full(len(symbols), account.leverage, dtype=np.float64)
    fee_rates = np.zeros(len(symbols), dtype=np.float64)
    contract_sizes = np.ones(len(symbols), dtype=np.float64)

    def kernel():
        return _engine_units_v2(
            n_bars=len(idx_n),
            n_syms=len(symbols),
            highs=highs_m,
            lows=lows_m,
            closes=closes_m,
            target_units=target_m,
            funding_rates=funding_m,
            is_funding_bar=is_funding,
            init_capital=account.initial_capital,
            leverages=leverages,
            maint_ratio=account.maintenance_ratio,
            fee_rates=fee_rates,
            contract_sizes=contract_sizes,
            slippage=execution.slippage_rate,
            use_funding=False,
        )

    kernel_out = kernel()

    def build_result():
        (
            equity_arr,
            pos_arr,
            fee_arr,
            turnover_arr,
            funding_arr,
            init_margin_arr,
            maint_margin_arr,
            rejected_arr,
            reject_code_arr,
            liq_flag,
            liq_idx,
            _liq_reason,
        ) = kernel_out
        equity = pd.Series(equity_arr, index=idx_n, name="equity")
        return BacktestResultV2(
            equity=equity,
            returns=equity.pct_change().fillna(0.0),
            positions=pd.DataFrame({f"Position_{s}": pos_arr[:, j] for j, s in enumerate(symbols)}, index=idx_n),
            closes=pd.DataFrame({f"Close_{s}": closes_m[:, j] for j, s in enumerate(symbols)}, index=idx_n),
            symbols=symbols,
            initial_capital=account.initial_capital,
            leverage=account.leverage,
            liquidated=bool(liq_flag),
            liquidation_bar=int(liq_idx),
            fees=pd.Series(fee_arr, index=idx_n, name="fees"),
            funding=pd.Series(funding_arr, index=idx_n, name="funding"),
            margin=pd.DataFrame({"initial_margin": init_margin_arr, "maintenance_margin": maint_margin_arr}, index=idx_n),
            diagnostics=pd.DataFrame(
                {"turnover": turnover_arr, "rejected_orders": rejected_arr, "reject_code": reject_code_arr},
                index=idx_n,
            ),
            metadata={"backend": "native_vectorized", "engine": "units_v2_profile"},
        )

    stage_defs = [
        ("data_normalization", normalize, "validate_datetime + align OHLC/signals/funding"),
        ("target_sizing", size_targets, "compute signal_notional target units"),
        ("pandas_to_ndarray", pack_arrays, "build contiguous kernel arrays"),
        ("pure_numba_kernel", kernel, "compiled _engine_units_v2 only"),
        ("result_report_construction", build_result, "Series/DataFrame/BacktestResultV2 construction"),
    ]
    return _profile_backend("native_vectorized", profile, profile.order_count, stage_defs)


def profile_native_event(profile: BenchmarkProfile) -> BackendProfile:
    import numpy as np
    import pandas as pd

    from quantbt import AccountConfig, ExecutionConfig
    from quantbt.core.event import ORDER_TYPE_LIMIT, ORDER_TYPE_MARKET, ORDER_TYPE_STOP_LIMIT, ORDER_TYPE_STOP_MARKET
    from quantbt.core.event import TIF_FOK, TIF_GTC, TIF_GTD, TIF_IOC, _engine_event_v1
    from quantbt.core.preprocessor import align_series, build_arrays, prepare_funding, validate_datetime
    from quantbt.core.results import BacktestResultV2
    from quantbt.core.schema import OrderSide, OrderType, TimeInForce

    idx, frames = _make_market_frames(profile.bars, profile.symbols)
    orders = _make_orders(idx, profile.order_count, profile.symbols)
    symbols = list(frames.keys())
    account = AccountConfig(initial_capital=1_000_000.0, leverage=10.0)
    execution = ExecutionConfig()

    def normalize():
        local_idx = validate_datetime(idx)
        closes = {symbol: frames[symbol]["close"] for symbol in symbols}
        highs = {symbol: frames[symbol]["high"] for symbol in symbols}
        lows = {symbol: frames[symbol]["low"] for symbol in symbols}
        close_dict = align_series(closes, symbols, local_idx)
        high_dict = align_series(highs, symbols, local_idx, fallback=close_dict)
        low_dict = align_series(lows, symbols, local_idx, fallback=close_dict)
        zero_signals = {symbol: pd.Series(0.0, index=local_idx) for symbol in symbols}
        funding_dict = prepare_funding(0.0, symbols, local_idx)
        return local_idx, close_dict, high_dict, low_dict, zero_signals, funding_dict

    idx_n, close_dict, high_dict, low_dict, zero_signals, funding_dict = normalize()

    def pack_arrays():
        return build_arrays(
            symbols=symbols,
            idx=idx_n,
            closes_dict=close_dict,
            highs_dict=high_dict,
            lows_dict=low_dict,
            signals_dict=zero_signals,
            funding_dict=funding_dict,
        )

    closes_m, highs_m, lows_m, _, funding_m, is_funding = pack_arrays()
    symbol_to_col = {symbol: j for j, symbol in enumerate(symbols)}

    def bar_index(timestamp) -> int:
        ts = pd.Timestamp(timestamp)
        if ts.tz is None:
            ts = ts.tz_localize("UTC")
        else:
            ts = ts.tz_convert("UTC")
        pos = idx_n.searchsorted(ts, side="left")
        if pos >= len(idx_n):
            raise ValueError("order timestamp is after the available data")
        return int(pos)

    def side_code(side) -> int:
        return 1 if side is OrderSide.BUY else -1

    def order_type_code(order_type) -> int:
        mapping = {
            OrderType.MARKET: ORDER_TYPE_MARKET,
            OrderType.LIMIT: ORDER_TYPE_LIMIT,
            OrderType.STOP_MARKET: ORDER_TYPE_STOP_MARKET,
            OrderType.STOP_LIMIT: ORDER_TYPE_STOP_LIMIT,
        }
        return mapping[order_type]

    def tif_code(tif) -> int:
        mapping = {
            TimeInForce.GTC: TIF_GTC,
            TimeInForce.IOC: TIF_IOC,
            TimeInForce.FOK: TIF_FOK,
            TimeInForce.GTD: TIF_GTD,
        }
        return mapping[tif]

    def build_order_arrays():
        sorted_orders = sorted(enumerate(orders), key=lambda item: bar_index(item[1].timestamp))
        n_orders = len(sorted_orders)
        order_bar = np.zeros(n_orders, dtype=np.int64)
        order_symbol = np.zeros(n_orders, dtype=np.int64)
        order_side = np.zeros(n_orders, dtype=np.int64)
        order_type = np.zeros(n_orders, dtype=np.int64)
        order_qty = np.zeros(n_orders, dtype=np.float64)
        order_price = np.zeros(n_orders, dtype=np.float64)
        order_tif = np.zeros(n_orders, dtype=np.int64)
        original_index = np.zeros(n_orders, dtype=np.int64)
        for k, (orig_idx, order) in enumerate(sorted_orders):
            order_bar[k] = bar_index(order.timestamp)
            order_symbol[k] = symbol_to_col[order.symbol]
            order_side[k] = side_code(order.side)
            order_type[k] = order_type_code(order.order_type)
            order_qty[k] = float(order.qty)
            order_price[k] = 0.0 if order.price is None else float(order.price)
            order_tif[k] = tif_code(order.tif)
            original_index[k] = orig_idx
        order_ptr = np.zeros(len(idx_n) + 1, dtype=np.int64)
        for bar in order_bar:
            order_ptr[bar + 1] += 1
        for i in range(1, len(order_ptr)):
            order_ptr[i] += order_ptr[i - 1]
        return sorted_orders, order_ptr, order_symbol, order_side, order_type, order_qty, order_price, order_tif, original_index

    order_arrays = build_order_arrays()
    leverages = np.full(len(symbols), account.leverage, dtype=np.float64)
    fee_rates = np.zeros(len(symbols), dtype=np.float64)
    contract_sizes = np.ones(len(symbols), dtype=np.float64)

    def kernel():
        _, order_ptr, order_symbol, order_side, order_type, order_qty, order_price, order_tif, _ = order_arrays
        return _engine_event_v1(
            n_bars=len(idx_n),
            n_syms=len(symbols),
            n_orders=len(orders),
            order_ptr=order_ptr,
            order_symbol=order_symbol,
            order_side=order_side,
            order_type=order_type,
            order_qty=order_qty,
            order_price=order_price,
            order_tif=order_tif,
            highs=highs_m,
            lows=lows_m,
            closes=closes_m,
            funding_rates=funding_m,
            is_funding_bar=is_funding,
            init_capital=account.initial_capital,
            leverages=leverages,
            maint_ratio=account.maintenance_ratio,
            fee_rates=fee_rates,
            contract_sizes=contract_sizes,
            slippage=execution.slippage_rate,
            use_funding=False,
        )

    kernel_out = kernel()

    def build_result():
        (
            equity_arr,
            pos_arr,
            fee_arr,
            turnover_arr,
            funding_arr,
            init_margin_arr,
            maint_margin_arr,
            rejected_bar,
            canceled_bar,
            order_status,
            reject_code,
            fill_bar,
            fill_qty,
            fill_price,
            fill_fee,
            liq_flag,
            liq_idx,
            _liq_reason,
        ) = kernel_out
        _, _, _, _, _, _, _, _, original_index = order_arrays
        equity = pd.Series(equity_arr, index=idx_n, name="equity")
        order_report = pd.DataFrame(
            {
                "original_index": original_index,
                "status": order_status,
                "reject_code": reject_code,
                "fill_bar": fill_bar,
                "fill_qty": fill_qty,
                "fill_price": fill_price,
                "fill_fee": fill_fee,
            }
        ).sort_values("original_index", kind="stable")
        return BacktestResultV2(
            equity=equity,
            returns=equity.pct_change().fillna(0.0),
            positions=pd.DataFrame({f"Position_{s}": pos_arr[:, j] for j, s in enumerate(symbols)}, index=idx_n),
            closes=pd.DataFrame({f"Close_{s}": closes_m[:, j] for j, s in enumerate(symbols)}, index=idx_n),
            symbols=symbols,
            initial_capital=account.initial_capital,
            leverage=account.leverage,
            liquidated=bool(liq_flag),
            liquidation_bar=int(liq_idx),
            orders=tuple(orders),
            fees=pd.Series(fee_arr, index=idx_n, name="fees"),
            funding=pd.Series(funding_arr, index=idx_n, name="funding"),
            margin=pd.DataFrame({"initial_margin": init_margin_arr, "maintenance_margin": maint_margin_arr}, index=idx_n),
            diagnostics=pd.DataFrame(
                {"turnover": turnover_arr, "rejected_orders": rejected_bar, "canceled_orders": canceled_bar},
                index=idx_n,
            ),
            metadata={"backend": "native_event", "engine": "event_v1_profile", "order_report": order_report},
        )

    stage_defs = [
        ("data_normalization", normalize, "validate_datetime + align OHLC/funding"),
        ("pandas_to_ndarray", pack_arrays, "build contiguous market arrays"),
        ("order_array_construction", build_order_arrays, "sort orders, map enums, build order_ptr"),
        ("pure_numba_kernel", kernel, "compiled _engine_event_v1 only"),
        ("result_report_construction", build_result, "order report + Series/DataFrame/BacktestResultV2"),
    ]
    return _profile_backend("native_event", profile, len(orders), stage_defs)


def _profile_backend(
    backend: str,
    profile: BenchmarkProfile,
    orders: int,
    stage_defs: Sequence[Tuple[str, object, str]],
) -> BackendProfile:
    raw: List[Tuple[str, float, str]] = []
    for name, fn, notes in stage_defs:
        fn()
        timings = []
        for _ in range(profile.repeats):
            start = time.perf_counter()
            fn()
            timings.append(time.perf_counter() - start)
        raw.append((name, statistics.mean(timings), notes))
    total = sum(seconds for _, seconds, _ in raw)
    stages = [
        ProfileStage(
            backend=backend,
            profile=profile.name,
            stage=name,
            seconds=seconds,
            percent_of_profile=(seconds / total * 100.0) if total > 0.0 else 0.0,
            repeats=profile.repeats,
            notes=notes,
        )
        for name, seconds, notes in raw
    ]
    return BackendProfile(
        backend=backend,
        profile=profile.name,
        bars=profile.bars,
        symbols=profile.symbols,
        orders=orders,
        total_seconds=total,
        stages=stages,
    )


def write_outputs(records: Sequence[BackendProfile], json_out: Path, md_out: Path) -> None:
    json_out.parent.mkdir(parents=True, exist_ok=True)
    md_out.parent.mkdir(parents=True, exist_ok=True)
    payload = {"records": [asdict(record) for record in records]}
    json_out.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    md_out.write_text(markdown_report(records), encoding="utf-8")


def markdown_report(records: Sequence[BackendProfile]) -> str:
    lines = [
        "# Phase 7 Profiling Results",
        "",
        "| backend | stage | seconds | share | notes |",
        "| --- | --- | ---: | ---: | --- |",
    ]
    for record in records:
        for stage in record.stages:
            lines.append(
                f"| `{stage.backend}` | `{stage.stage}` | {_fmt(stage.seconds)} | {stage.percent_of_profile:.1f}% | {stage.notes} |"
            )
    lines.extend(
        [
            "",
            "Interpretation rule: optimize the largest measured bucket first. Cython/C++ is only justified after pure Numba kernel profiling remains the bottleneck.",
        ]
    )
    return "\n".join(lines) + "\n"


def _fmt(value: Optional[float]) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "-"
    return f"{value:.6f}"


if __name__ == "__main__":
    raise SystemExit(main())
