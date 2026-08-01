#!/usr/bin/env python3
"""
Phase 12B benchmark follow-up and Nautilus portfolio certification runner.

The runner keeps production claims narrow and auditable:

* benchmark stages separate full facade time from array preparation, pure
  Numba portfolio kernel time, and report-construction residual time;
* Nautilus portfolio validation is optional because it depends on the external
  NautilusTrader package and venue adapter state;
* all-or-none basket package semantics are certified through the deterministic
  QuantBT depth preflight used before Nautilus package replay.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

PACKAGE_DIR = Path(__file__).resolve().parents[1]
PROJECT_DIR = PACKAGE_DIR.parent
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from quantbt import (  # noqa: E402
    AccountConfig,
    NautilusExecutionDepthConfig,
    OrderIntent,
    OrderSide,
    OrderType,
    PortfolioBacktestEngine,
    QuantBTEndpoint,
    TimeInForce,
    simulate_nautilus_order_package_depth,
)
from quantbt.backends import NativePortfolioBackend, NativePortfolioConfig  # noqa: E402
from quantbt.core.engine import _engine_portfolio  # noqa: E402
from quantbt.core.preprocessor import align_series, build_market_arrays, build_signal_matrix, prepare_funding, validate_datetime  # noqa: E402
from quantbt.sizing.fast import scale_signal_notional_matrix  # noqa: E402


def run_certification(
    *,
    rows: int = 2_000,
    symbols: int = 6,
    repeats: int = 3,
    include_nautilus: bool = False,
) -> Dict:
    benchmark = _benchmark_native_portfolio(rows=rows, symbols=symbols, repeats=repeats)
    all_or_none = _all_or_none_basket_depth_smoke()
    nautilus = _optional_real_nautilus_portfolio(include_nautilus=include_nautilus)
    passed = (
        benchmark["status"] == "pass"
        and all_or_none["status"] == "pass"
        and nautilus["status"] in {"pass", "skipped", "diff"}
    )
    return {
        "status": "pass" if passed else "fail",
        "benchmark_followup": benchmark,
        "all_or_none_basket": all_or_none,
        "nautilus_portfolio": nautilus,
        "cython_cpp_recommendation": _cython_cpp_recommendation(benchmark),
    }


def make_markdown(report: Dict) -> str:
    bench = report["benchmark_followup"]
    lines = [
        "# Phase 12B Benchmark And Nautilus Portfolio Certification",
        "",
        f"Status: **{report['status']}**",
        "",
        "## Benchmark Follow-Up",
        "",
        f"- Bars: `{bench['rows']}`",
        f"- Symbols: `{bench['symbols']}`",
        f"- Repeats: `{bench['repeats']}`",
        f"- Full facade seconds: `{bench['stages']['full_facade_seconds']:.6f}`",
        f"- Prepared reuse facade seconds: `{bench['stages']['prepared_reuse_facade_seconds']:.6f}`",
        f"- Prepared reuse speedup: `{bench['stages']['prepared_reuse_speedup']:.3f}x`",
        f"- Array preparation seconds: `{bench['stages']['array_preparation_seconds']:.6f}`",
        f"- Pure Numba kernel seconds: `{bench['stages']['pure_numba_kernel_seconds']:.6f}`",
        f"- Report construction residual seconds: `{bench['stages']['report_construction_estimate_seconds']:.6f}`",
        f"- Pure kernel share: `{bench['stages']['pure_kernel_share_pct']:.2f}%`",
        "",
        "## Nautilus Portfolio",
        "",
        f"- Status: `{report['nautilus_portfolio']['status']}`",
        f"- Validation status: `{report['nautilus_portfolio'].get('validation_status')}`",
        f"- Equity tolerance profile: `{report['nautilus_portfolio'].get('equity_tolerance')}`",
        f"- Position tolerance profile: `{report['nautilus_portfolio'].get('position_tolerance')}`",
        f"- Final equity diff: `{report['nautilus_portfolio'].get('final_equity_diff')}`",
        f"- Max position diff: `{report['nautilus_portfolio'].get('max_abs_position_diff')}`",
        "",
        "## All-Or-None Basket",
        "",
        f"- Status: `{report['all_or_none_basket']['status']}`",
        f"- Input orders: `{report['all_or_none_basket']['input_orders']}`",
        f"- Accepted orders: `{report['all_or_none_basket']['accepted_orders']}`",
        f"- Rejected orders: `{report['all_or_none_basket']['rejected_orders']}`",
        f"- Depth model: `{report['all_or_none_basket']['depth_model']}`",
        "",
        "## Cython/C++ Decision",
        "",
        report["cython_cpp_recommendation"],
    ]
    return "\n".join(lines) + "\n"


def _benchmark_native_portfolio(rows: int, symbols: int, repeats: int) -> Dict:
    idx, positions, closes, highs, lows = _make_portfolio_fixture(rows, symbols)
    account = AccountConfig(initial_capital=250_000.0, leverage=5.0, maintenance_ratio=0.005)
    alloc = 10_000.0
    fee_rate = 0.0002
    fee_oneway = fee_rate / 2.0

    def full_facade():
        return PortfolioBacktestEngine(
            positions=positions,
            closes=closes,
            highs=highs,
            lows=lows,
            datetime_index=idx,
            mode="longshort",
            backend="native_portfolio",
            account=account,
            fee_rate=fee_rate,
            alloc_per_trade=alloc,
            hedge_type="signal_notional",
            use_funding=False,
        ).result

    backend = NativePortfolioBackend(NativePortfolioConfig(account=account, fee_rate=fee_oneway, use_funding=False))
    symbol_list = list(positions.keys())
    prepared_market = backend.prepare_market_arrays(
        datetime_index=idx,
        closes=closes,
        highs=highs,
        lows=lows,
        funding_rate=0.0,
        symbols=symbol_list,
    )
    prepared_signals = backend.prepare_signal_matrix(positions, idx, symbol_list)

    def prepared_reuse():
        return backend.run_signals(
            positions=None,
            closes=closes,
            highs=highs,
            lows=lows,
            datetime_index=idx,
            mode="longshort",
            alloc_per_trade=alloc,
            contract_size=1.0,
            hedge_type="signal_notional",
            funding_rate=0.0,
            leverage=account.leverage,
            maintenance_ratio=account.maintenance_ratio,
            symbols=symbol_list,
            use_pyramiding=True,
            market_arrays=prepared_market,
            raw_signal_matrix=prepared_signals,
        )

    prepared = _prepare_portfolio_arrays(idx, positions, closes, highs, lows, account, alloc, fee_oneway)
    _kernel_portfolio(prepared)
    full_facade()
    prepared_reuse()

    prep_seconds = _timeit(lambda: _prepare_portfolio_arrays(idx, positions, closes, highs, lows, account, alloc, fee_oneway), repeats)
    kernel_seconds = _timeit(lambda: _kernel_portfolio(prepared), repeats)
    full_seconds = _timeit(full_facade, repeats)
    prepared_reuse_seconds = _timeit(prepared_reuse, repeats)
    report_seconds = max(0.0, full_seconds - prep_seconds - kernel_seconds)
    status = "pass" if full_seconds > 0.0 and kernel_seconds > 0.0 else "fail"
    return {
        "status": status,
        "rows": int(rows),
        "symbols": int(symbols),
        "bar_symbols": int(rows * symbols),
        "repeats": int(repeats),
        "stages": {
            "full_facade_seconds": float(full_seconds),
            "prepared_reuse_facade_seconds": float(prepared_reuse_seconds),
            "array_preparation_seconds": float(prep_seconds),
            "pure_numba_kernel_seconds": float(kernel_seconds),
            "report_construction_estimate_seconds": float(report_seconds),
            "prepared_reuse_speedup": float(full_seconds / prepared_reuse_seconds) if prepared_reuse_seconds > 0.0 else 0.0,
            "array_preparation_share_pct": float(prep_seconds / full_seconds * 100.0) if full_seconds > 0.0 else 0.0,
            "pure_kernel_share_pct": float(kernel_seconds / full_seconds * 100.0) if full_seconds > 0.0 else 0.0,
            "report_construction_share_pct": float(report_seconds / full_seconds * 100.0) if full_seconds > 0.0 else 0.0,
        },
        "notes": (
            "Prepared-array cache targets WFO/service loops. Pure Numba kernel "
            "remains separated from pandas normalization and report construction."
        ),
    }


def _optional_real_nautilus_portfolio(include_nautilus: bool) -> Dict:
    if not include_nautilus:
        return {"status": "skipped", "reason": "run with --include-nautilus"}
    try:
        from quantbt.adapters.nautilus import NautilusBackendConfig, NautilusBacktestEngine

        NautilusBacktestEngine.check_available()
        idx, raw_positions, raw_closes, raw_highs, raw_lows = _make_portfolio_fixture(rows=96, symbols=2)
        symbols = ["BTCUSDT-PERP.BINANCE", "ETHUSDT-PERP.BINANCE"]
        raw_symbols = list(raw_positions.keys())
        positions = {symbols[i]: raw_positions[raw_symbols[i]] for i in range(2)}
        closes = {symbols[i]: raw_closes[raw_symbols[i]] for i in range(2)}
        highs = {symbols[i]: raw_highs[raw_symbols[i]] for i in range(2)}
        lows = {symbols[i]: raw_lows[raw_symbols[i]] for i in range(2)}
        data = {
            symbol: pd.DataFrame(
                {
                    "open": closes[symbol],
                    "high": highs[symbol],
                    "low": lows[symbol],
                    "close": closes[symbol],
                    "volume": 1_000.0,
                },
                index=idx,
            )
            for symbol in symbols
        }
        endpoint = QuantBTEndpoint.portfolio(
            portfolio_mode="market_neutral",
            backend="nautilus",
            initial_capital=100_000.0,
            leverage=3.0,
            fee_rate=0.0002,
            use_funding=False,
            hedge_type="signal_notional",
            alloc_per_trade={symbols[0]: 1_000_000.0, symbols[1]: 750_000.0},
            metadata={
                "portfolio_nautilus_equity_tolerance": 1.0,
                "portfolio_nautilus_position_tolerance": 0.005,
            },
            nautilus_config=NautilusBackendConfig(instrument_id=symbols[0], timeframe="1h", bypass_risk=True),
        )
        result = endpoint.simulate(data=data, positions=pd.DataFrame(positions), symbols=symbols)
        validation = result.metadata.get("portfolio_nautilus_validation_report", {})
        return {
            "status": "pass" if validation.get("status") == "pass" else "diff",
            "validation_status": validation.get("status"),
            "checks": validation.get("checks", {}),
            "equity_tolerance": validation.get("equity_tolerance"),
            "position_tolerance": validation.get("position_tolerance"),
            "expected_order_count": validation.get("expected_order_count"),
            "nautilus_orders": validation.get("nautilus_orders"),
            "nautilus_fills": validation.get("nautilus_fills"),
            "final_equity_diff": validation.get("final_equity_diff"),
            "max_abs_position_diff": validation.get("max_abs_position_diff"),
        }
    except Exception as exc:
        return {"status": "skipped", "reason": f"{type(exc).__name__}: {exc}"}


def _all_or_none_basket_depth_smoke() -> Dict:
    idx = pd.date_range("2024-01-01", periods=4, freq="1h", tz="UTC")
    data = {
        "BTC": _depth_frame(idx, close=100.0, high=101.0, low=95.0),
        "ETH": _depth_frame(idx, close=50.0, high=51.0, low=49.0),
    }
    meta = {"package_id": "PHASE12-BASKET", "package_type": "basket_package"}
    orders = (
        OrderIntent(idx[1], "BTC", OrderSide.BUY, OrderType.LIMIT, qty=1.0, price=96.0, tif=TimeInForce.GTC, metadata=meta),
        OrderIntent(idx[1], "ETH", OrderSide.BUY, OrderType.LIMIT, qty=1.0, price=45.0, tif=TimeInForce.GTC, metadata=meta),
    )
    result = simulate_nautilus_order_package_depth(
        orders,
        data,
        NautilusExecutionDepthConfig(all_or_none_packages=True),
    )
    package_status = result.package_report["status"].tolist() if not result.package_report.empty else []
    passed = len(result.orders) == 0 and result.metadata.get("rejected_orders") == 2 and package_status == ["rejected"]
    return {
        "status": "pass" if passed else "fail",
        "input_orders": int(result.metadata.get("input_orders", len(orders))),
        "accepted_orders": int(result.metadata.get("accepted_orders", len(result.orders))),
        "rejected_orders": int(result.metadata.get("rejected_orders", 0)),
        "package_status": package_status,
        "depth_model": result.metadata.get("depth_model"),
    }


def _make_portfolio_fixture(rows: int, symbols: int, symbol_prefix: str = "SYM"):
    idx = pd.date_range("2022-01-01", periods=rows, freq="1h", tz="UTC")
    grid = np.arange(rows)
    base = 100.0 + np.cumsum(np.sin(grid / 19.0) * 0.08 + np.cos(grid / 37.0) * 0.02)
    positions = {}
    closes = {}
    highs = {}
    lows = {}
    for j in range(symbols):
        symbol = f"{symbol_prefix}{j:03d}" if symbol_prefix.endswith("SYM") else f"{symbol_prefix}{j}"
        close = pd.Series(base * (1.0 + j * 0.015) + j * 3.0, index=idx)
        raw = np.where(((grid // (18 + j % 4)) + j) % 4 == 0, 1.0, 0.0)
        sign = 1.0 if j % 2 == 0 else -1.0
        positions[symbol] = pd.Series(raw * sign, index=idx)
        closes[symbol] = close
        highs[symbol] = close * 1.002
        lows[symbol] = close * 0.998
    return idx, positions, closes, highs, lows


def _prepare_portfolio_arrays(idx, positions, closes, highs, lows, account, alloc, fee_rate):
    idx = validate_datetime(idx)
    symbols = list(positions.keys())
    close_dict = align_series(closes, symbols, idx)
    high_dict = align_series(highs, symbols, idx, fallback=close_dict)
    low_dict = align_series(lows, symbols, idx, fallback=close_dict)
    pos_dict = align_series(positions, symbols, idx, fill_val=0.0)
    funding_dict = prepare_funding(0.0, symbols, idx)
    market = build_market_arrays(symbols, idx, close_dict, high_dict, low_dict, funding_dict)
    raw_signals = build_signal_matrix(symbols, idx, pos_dict)
    alloc_arr = np.full(len(symbols), float(alloc), dtype=np.float64)
    contract_sizes = np.ones(len(symbols), dtype=np.float64)
    leverages = np.full(len(symbols), float(account.leverage), dtype=np.float64)
    target_units = scale_signal_notional_matrix(raw_signals, market.closes, alloc_arr, use_pyramiding=True)
    return {
        "n_bars": len(idx),
        "n_syms": len(symbols),
        "highs": market.highs,
        "lows": market.lows,
        "closes": market.closes,
        "target_units": target_units,
        "funding": market.funding,
        "is_funding_bar": market.is_funding_bar,
        "initial_capital": float(account.initial_capital),
        "leverages": leverages,
        "maintenance_ratio": float(account.maintenance_ratio),
        "fee_rate": float(fee_rate),
        "slippage_rate": 0.0,
        "contract_sizes": contract_sizes,
        "tradable": np.ones_like(market.closes, dtype=np.bool_),
    }


def _kernel_portfolio(prepared: Dict):
    return _engine_portfolio(
        n_bars=prepared["n_bars"],
        n_syms=prepared["n_syms"],
        highs=prepared["highs"],
        lows=prepared["lows"],
        closes=prepared["closes"],
        target_pos=prepared["target_units"],
        funding_rates=prepared["funding"],
        is_funding_bar=prepared["is_funding_bar"],
        init_capital=prepared["initial_capital"],
        leverages=prepared["leverages"],
        maint_ratio=prepared["maintenance_ratio"],
        fee_rate=prepared["fee_rate"],
        slippage_rate=prepared["slippage_rate"],
        contract_sizes=prepared["contract_sizes"],
        use_funding=False,
        tradable=prepared["tradable"],
    )


def _depth_frame(idx, close: float, high: float, low: float) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "open": close,
            "high": high,
            "low": low,
            "close": close,
            "volume": 100.0,
        },
        index=idx,
    )


def _timeit(fn, repeats: int) -> float:
    samples: List[float] = []
    for _ in range(max(1, int(repeats))):
        start = time.perf_counter()
        fn()
        samples.append(time.perf_counter() - start)
    return float(statistics.mean(samples))


def _cython_cpp_recommendation(benchmark: Dict) -> str:
    share = benchmark.get("stages", {}).get("pure_kernel_share_pct", 100.0)
    if share >= 35.0:
        return "Pure kernel share is large enough to justify investigating Cython/C++ after correctness locks."
    return "Cython/C++ is not justified yet; optimize cached array preparation and report construction first."


def _json_default(value):
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    raise TypeError(f"{type(value).__name__} is not JSON serializable")


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rows", type=int, default=2_000)
    parser.add_argument("--symbols", type=int, default=6)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--include-nautilus", action="store_true")
    parser.add_argument("--json-out", type=Path, default=PACKAGE_DIR / "benchmarks" / "phase12_benchmark_nautilus_cert.json")
    parser.add_argument("--md-out", type=Path, default=PACKAGE_DIR / "benchmarks" / "phase12_benchmark_nautilus_cert.md")
    args = parser.parse_args(argv)
    report = run_certification(rows=args.rows, symbols=args.symbols, repeats=args.repeats, include_nautilus=args.include_nautilus)
    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.md_out.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.write_text(json.dumps(report, indent=2, default=_json_default) + "\n", encoding="utf-8")
    args.md_out.write_text(make_markdown(report), encoding="utf-8")
    print(make_markdown(report))
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
