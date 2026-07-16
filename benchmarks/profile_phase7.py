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
    from quantbt.sizing.fast import scale_signal_notional_matrix

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

    def pack_arrays():
        return build_arrays(
            symbols=symbols,
            idx=idx_n,
            closes_dict=close_dict,
            highs_dict=high_dict,
            lows_dict=low_dict,
            signals_dict=signal_dict,
            funding_dict=funding_dict,
        )

    closes_m, highs_m, lows_m, signals_m, funding_m, is_funding = pack_arrays()
    allocs = np.full(len(symbols), 10_000.0, dtype=np.float64)

    def size_targets():
        return scale_signal_notional_matrix(signals_m, closes_m, allocs, use_pyramiding=True)

    target_m = size_targets()
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
        ("pandas_to_ndarray", pack_arrays, "build contiguous market/signal arrays"),
        ("target_sizing", size_targets, "compute fast signal_notional target-unit matrix"),
        ("pure_numba_kernel", kernel, "compiled _engine_units_v2 only"),
        ("result_report_construction", build_result, "Series/DataFrame/BacktestResultV2 construction"),
    ]
    return _profile_backend("native_vectorized", profile, profile.order_count, stage_defs)


def profile_native_event(profile: BenchmarkProfile) -> BackendProfile:
    import numpy as np
    import pandas as pd

    from quantbt import AccountConfig, ExecutionConfig
    from quantbt.core.event import _engine_event_v1
    from quantbt.core.order_compiler import compile_order_intents
    from quantbt.core.preprocessor import align_series, build_arrays, prepare_funding, validate_datetime
    from quantbt.core.results import BacktestResultV2

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

    def build_order_arrays():
        return compile_order_intents(idx=idx_n, orders=orders, symbol_to_col=symbol_to_col)

    order_arrays = build_order_arrays()
    leverages = np.full(len(symbols), account.leverage, dtype=np.float64)
    fee_rates = np.zeros(len(symbols), dtype=np.float64)
    contract_sizes = np.ones(len(symbols), dtype=np.float64)

    def kernel():
        return _engine_event_v1(
            n_bars=len(idx_n),
            n_syms=len(symbols),
            n_orders=len(orders),
            order_ptr=order_arrays.order_ptr,
            order_symbol=order_arrays.order_symbol,
            order_side=order_arrays.order_side,
            order_type=order_arrays.order_type,
            order_qty=order_arrays.order_qty,
            order_price=order_arrays.order_price,
            order_tif=order_arrays.order_tif,
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
        equity = pd.Series(equity_arr, index=idx_n, name="equity")
        order_report = pd.DataFrame(
            {
                "original_index": order_arrays.original_index,
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
        ("order_array_construction", build_order_arrays, "compile orders with vectorized timestamp mapping"),
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
