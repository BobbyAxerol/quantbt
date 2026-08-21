#!/usr/bin/env python3
"""Phase 54B.3 E4/E5 bounded native portfolio/package evidence.

This benchmark is intentionally scoped to the only new Rust-first domain
contracts: V2 `target_units` all-or-none market rows and one same-bar atomic
market package.  It performs a Python event-oracle audit comparison before
timing, then reports score execution and cold audit adaptation separately.
It is not a benchmark for the general native portfolio, basket, arbitrage, or
callback engines.
"""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import resource
from statistics import median
from time import perf_counter
from typing import Any, Callable

import numpy as np
import pandas as pd

from quantbt.backends import run_atomic_package_market, run_portfolio_target_market
from quantbt.backends.native_event import NativeEventBackend, NativeEventConfig
from quantbt.core.orders import OrderCommand
from quantbt.core.schema import AccountConfig, ExecutionConfig, OrderSide, OrderType
from quantbt.preparation import CachePolicy, NativeExecutionPreparationCache


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = ROOT / "benchmarks/native_event/results/phase54b3/portfolio_package.json"
INITIAL_CAPITAL = 100_000.0
LEVERAGE = 5.0
FEE_RATE = 0.0002
SLIPPAGE_RATE = 0.0001


def _rss_bytes() -> int:
    """Return current Linux RSS, falling back to process peak when needed."""

    status = Path("/proc/self/status")
    if status.exists():
        for line in status.read_text(encoding="utf-8").splitlines():
            if line.startswith("VmRSS:"):
                return int(line.split()[1]) * 1024
    return int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss) * 1024


def _peak_rss_bytes() -> int:
    return int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss) * 1024


def _measure(call: Callable[[], Any], adapt: Callable[[Any], None], repeats: int) -> tuple[dict[str, float | int], Any]:
    """Warm `call`, then measure engine and explicit cold adaptation separately."""

    call()
    engine_samples: list[float] = []
    adaptation_samples: list[float] = []
    rss_before = _rss_bytes()
    result: Any = None
    for _ in range(repeats):
        started = perf_counter()
        result = call()
        engine_samples.append(perf_counter() - started)
        started = perf_counter()
        adapt(result)
        adaptation_samples.append(perf_counter() - started)
    assert result is not None
    rss_after = _rss_bytes()
    return (
        {
            "engine_median_seconds": float(median(engine_samples)),
            "adaptation_median_seconds": float(median(adaptation_samples)),
            "rss_before_bytes": int(rss_before),
            "rss_steady_bytes": int(rss_after),
            "rss_delta_bytes": int(max(0, rss_after - rss_before)),
            "rss_peak_process_bytes": int(_peak_rss_bytes()),
        },
        result,
    )


def _fixture(bars: int, n_symbols: int) -> tuple[pd.DatetimeIndex, tuple[str, ...], dict[str, object], pd.DataFrame]:
    """Build deterministic multi-symbol OHLCV/funding arrays and a close frame."""

    index = pd.date_range("2024-01-01", periods=bars, freq="1h", tz="UTC")
    symbols = tuple(f"ASSET{column:02d}" for column in range(n_symbols))
    phase = np.arange(bars, dtype=np.float64)[:, None]
    offsets = np.arange(n_symbols, dtype=np.float64)[None, :]
    closes = 80.0 + offsets * 7.0 + 0.015 * phase + 1.5 * np.sin((phase + offsets * 5.0) / 31.0)
    opens = np.ascontiguousarray(closes + 0.03 * np.cos((phase + offsets) / 11.0), dtype=np.float64)
    highs = np.ascontiguousarray(np.maximum(opens, closes) + 0.8, dtype=np.float64)
    lows = np.ascontiguousarray(np.minimum(opens, closes) - 0.8, dtype=np.float64)
    funding = np.ascontiguousarray(np.full_like(closes, 0.00001), dtype=np.float64)
    funding_mask = np.ascontiguousarray(np.asarray(index.hour % 8 == 0, dtype=np.bool_))
    close_frame = pd.DataFrame(closes, index=index, columns=symbols)
    common: dict[str, object] = {
        "timestamps_ns": np.ascontiguousarray(index.asi8, dtype=np.int64),
        "opens": opens,
        "highs": highs,
        "lows": lows,
        "closes": np.ascontiguousarray(closes, dtype=np.float64),
        "volumes": np.ascontiguousarray(np.full_like(closes, 1_000.0), dtype=np.float64),
        "funding": funding,
        "funding_mask": funding_mask,
        "symbols": symbols,
        "contract_sizes": np.ones(n_symbols, dtype=np.float64),
        "leverages": np.full(n_symbols, LEVERAGE, dtype=np.float64),
        "fee_rates": np.full(n_symbols, FEE_RATE, dtype=np.float64),
        "initial_capital": INITIAL_CAPITAL,
        "maintenance_ratio": 0.005,
        "slippage_rate": SLIPPAGE_RATE,
        "use_funding": True,
    }
    return index, symbols, common, close_frame


def _target_tape(bars: int, n_symbols: int) -> np.ndarray:
    """Create a persistent target tape with deterministic reversal rows."""

    targets = np.zeros((bars, n_symbols), dtype=np.float64)
    current = np.zeros(n_symbols, dtype=np.float64)
    cadence = max(8, bars // 24)
    for bar in range(1, bars):
        if bar % cadence == 1:
            cycle = bar // cadence
            current = 0.5 * (((cycle + np.arange(n_symbols)) % 3) - 1).astype(np.float64)
        targets[bar] = current
    return np.ascontiguousarray(targets, dtype=np.float64)


def _target_commands(index: pd.DatetimeIndex, symbols: tuple[str, ...], targets: np.ndarray) -> tuple[OrderCommand, ...]:
    """Compile the accepted unconstrained target fixture into Python oracle orders."""

    previous = targets[0].copy()
    commands: list[OrderCommand] = []
    for bar in range(1, len(index)):
        for column, delta in enumerate(targets[bar] - previous):
            if abs(float(delta)) <= 1e-12:
                continue
            commands.append(
                OrderCommand(
                    timestamp=index[bar],
                    symbol=symbols[column],
                    side=OrderSide.BUY if delta > 0.0 else OrderSide.SELL,
                    order_type=OrderType.MARKET,
                    qty=abs(float(delta)),
                    order_id=f"target-{bar}-{column}",
                )
            )
        previous = targets[bar].copy()
    return tuple(commands)


def _python_backend() -> NativeEventBackend:
    return NativeEventBackend(
        NativeEventConfig(
            account=AccountConfig(
                initial_capital=INITIAL_CAPITAL,
                leverage=LEVERAGE,
                maintenance_ratio=0.005,
            ),
            execution=ExecutionConfig(slippage_bps=SLIPPAGE_RATE * 10_000.0),
            fee_rate=FEE_RATE,
            use_funding=True,
            native_backend="python",
            execution_contract="event_lifecycle_v2_next_bar_close",
        )
    )


def _python_oracle(
    index: pd.DatetimeIndex,
    symbols: tuple[str, ...],
    common: dict[str, object],
    commands: tuple[OrderCommand, ...],
    *,
    report_level: str,
):
    closes = np.asarray(common["closes"], dtype=np.float64)
    highs = np.asarray(common["highs"], dtype=np.float64)
    lows = np.asarray(common["lows"], dtype=np.float64)
    funding = np.asarray(common["funding"], dtype=np.float64)
    return _python_backend().run_order_commands(
        datetime_index=index,
        commands=commands,
        closes={symbol: pd.Series(closes[:, column], index=index) for column, symbol in enumerate(symbols)},
        highs={symbol: pd.Series(highs[:, column], index=index) for column, symbol in enumerate(symbols)},
        lows={symbol: pd.Series(lows[:, column], index=index) for column, symbol in enumerate(symbols)},
        funding_rate={symbol: pd.Series(funding[:, column], index=index) for column, symbol in enumerate(symbols)},
        contract_size={symbol: 1.0 for symbol in symbols},
        leverage={symbol: LEVERAGE for symbol in symbols},
        fee_rate={symbol: FEE_RATE for symbol in symbols},
        symbols=list(symbols),
        report_level=report_level,
    )


def _assert_target_parity(
    index: pd.DatetimeIndex,
    symbols: tuple[str, ...],
    common: dict[str, object],
    targets: np.ndarray,
) -> dict[str, object]:
    """Prove V2 target accounting against the Python event oracle once."""

    rust = run_portfolio_target_market(target_units=targets, report_level="audit", **common)
    python = _python_oracle(index, symbols, common, _target_commands(index, symbols, targets), report_level="audit")
    np.testing.assert_allclose(rust.payload["equity"], python.equity.to_numpy(), rtol=0.0, atol=1e-12)
    np.testing.assert_allclose(
        np.asarray(rust.payload["positions"]).reshape(len(index), len(symbols)),
        python.positions[[f"Position_{symbol}" for symbol in symbols]].to_numpy(),
        rtol=0.0,
        atol=1e-12,
    )
    np.testing.assert_allclose(rust.payload["fees"], python.fees.to_numpy(), rtol=0.0, atol=1e-12)
    np.testing.assert_allclose(rust.payload["funding"], python.funding.to_numpy(), rtol=0.0, atol=1e-12)
    return {
        "final_equity": float(rust.payload["final_equity"]),
        "total_fee": float(rust.payload["total_fee"]),
        "total_funding": float(rust.payload["total_funding"]),
        "fill_count": int(rust.payload["fill_count"]),
        "python_callbacks": int(rust.payload["python_callbacks"]),
        "boundary_calls": int(rust.payload["boundary_calls"]),
        "parity": "exact_atol_1e-12",
    }


def _package_kwargs(n_symbols: int) -> dict[str, object]:
    """Build one deterministic all-or-none package with ordered cross legs."""

    signed_qty = np.asarray([0.4 if column % 2 == 0 else -0.4 for column in range(n_symbols)], dtype=np.float64)
    return {
        "command_bar": 1,
        "package_id": 54_003,
        "order_ids": np.arange(54_100, 54_100 + n_symbols, dtype=np.int64),
        "symbol_ids": np.arange(n_symbols, dtype=np.uint32),
        "signed_qty": signed_qty,
        "source_age_ns": np.zeros(n_symbols, dtype=np.int64),
        "venue_codes": np.ones(n_symbols, dtype=np.uint16),
        "venue_sequence": np.arange(n_symbols, dtype=np.uint32),
        "max_staleness_ns": 0,
    }


def _package_commands(index: pd.DatetimeIndex, symbols: tuple[str, ...], package: dict[str, object]) -> tuple[OrderCommand, ...]:
    signed = np.asarray(package["signed_qty"], dtype=np.float64)
    ids = np.asarray(package["order_ids"], dtype=np.int64)
    return tuple(
        OrderCommand(
            timestamp=index[1],
            symbol=symbol,
            side=OrderSide.BUY if signed[column] > 0.0 else OrderSide.SELL,
            order_type=OrderType.MARKET,
            qty=abs(float(signed[column])),
            order_id=str(int(ids[column])),
        )
        for column, symbol in enumerate(symbols)
    )


def _assert_package_parity(
    index: pd.DatetimeIndex,
    symbols: tuple[str, ...],
    common: dict[str, object],
    package: dict[str, object],
) -> dict[str, object]:
    """Prove same-bar atomic package accounting against the Python event oracle."""

    rust = run_atomic_package_market(**package, report_level="audit", **common)
    python = _python_oracle(index, symbols, common, _package_commands(index, symbols, package), report_level="audit")
    np.testing.assert_allclose(rust.payload["equity"], python.equity.to_numpy(), rtol=0.0, atol=1e-12)
    np.testing.assert_allclose(
        np.asarray(rust.payload["positions"]).reshape(len(index), len(symbols)),
        python.positions[[f"Position_{symbol}" for symbol in symbols]].to_numpy(),
        rtol=0.0,
        atol=1e-12,
    )
    np.testing.assert_allclose(rust.payload["fees"], python.fees.to_numpy(), rtol=0.0, atol=1e-12)
    np.testing.assert_allclose(rust.payload["funding"], python.funding.to_numpy(), rtol=0.0, atol=1e-12)
    assert rust.payload["package_accepted"].tolist() == [True] * len(symbols)
    return {
        "final_equity": float(rust.payload["final_equity"]),
        "total_fee": float(rust.payload["total_fee"]),
        "total_funding": float(rust.payload["total_funding"]),
        "fill_count": int(rust.payload["fill_count"]),
        "package_atomicity_model": "bar_transaction",
        "python_callbacks": int(rust.payload["python_callbacks"]),
        "boundary_calls": int(rust.payload["boundary_calls"]),
        "parity": "exact_atol_1e-12",
    }


def _stats(stats: dict[str, float | int], *, bars: int, extra: dict[str, object]) -> dict[str, object]:
    """Add normalized throughput and explicit route metadata."""

    result: dict[str, object] = dict(stats)
    seconds = float(stats["engine_median_seconds"])
    result["bars_per_second"] = float(bars) / seconds
    result.update(extra)
    return result


def run(*, bars: int, symbols: int, repeats: int) -> dict[str, object]:
    """Run bounded E4/E5 parity and timing evidence."""

    if bars < 2_000:
        raise ValueError("E4 target benchmark requires bars >= 2000")
    if symbols < 2:
        raise ValueError("portfolio/package benchmark requires at least two symbols")
    index, symbol_names, common, close_frame = _fixture(bars, symbols)
    targets = _target_tape(bars, symbols)
    package = _package_kwargs(symbols)
    target_parity = _assert_target_parity(index, symbol_names, common, targets)
    package_parity = _assert_package_parity(index, symbol_names, common, package)
    cache = NativeExecutionPreparationCache(CachePolicy(max_bytes=128 * 1024 * 1024, max_entries=16))

    target_score_stats, _ = _measure(
        lambda: run_portfolio_target_market(target_units=targets, report_level="score", cache=cache, **common),
        lambda _result: None,
        repeats,
    )
    target_audit_stats, target_audit = _measure(
        lambda: run_portfolio_target_market(target_units=targets, report_level="audit", cache=cache, **common),
        lambda result: result.to_audit_result().to_backtest_result(
            datetime_index=index,
            closes=close_frame,
            symbols=symbol_names,
            initial_capital=INITIAL_CAPITAL,
            leverage=LEVERAGE,
        ),
        repeats,
    )
    package_score_stats, _ = _measure(
        lambda: run_atomic_package_market(**package, report_level="score", cache=cache, **common),
        lambda _result: None,
        repeats,
    )
    package_audit_stats, package_audit = _measure(
        lambda: run_atomic_package_market(**package, report_level="audit", cache=cache, **common),
        lambda result: result.to_audit_result().to_backtest_result(
            datetime_index=index,
            closes=close_frame,
            symbols=symbol_names,
            initial_capital=INITIAL_CAPITAL,
            leverage=LEVERAGE,
        ),
        repeats,
    )
    target_python_stats, _ = _measure(
        lambda: _python_oracle(
            index, symbol_names, common, _target_commands(index, symbol_names, targets), report_level="score"
        ),
        lambda _result: None,
        repeats,
    )
    package_python_stats, _ = _measure(
        lambda: _python_oracle(
            index, symbol_names, common, _package_commands(index, symbol_names, package), report_level="score"
        ),
        lambda _result: None,
        repeats,
    )
    fingerprint = sha256(
        json.dumps(
            {
                "target": target_parity,
                "package": package_parity,
                "bars": bars,
                "symbols": symbol_names,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return {
        "schema": "quantbt-native-phase54b3-benchmark-v1",
        "scope": {
            "portfolio": "linear_quote_settled_gross_cross target_units all_or_none V2 market",
            "package": "same_bar_atomic_market bar_transaction V2",
            "not_claimed": [
                "generic_native_portfolio",
                "target_weight_or_notional",
                "risk_parity",
                "cross_currency_or_cross_margin",
                "sequential_best_effort_or_hedge_after_primary",
                "partial_fill_or_l2_queue",
            ],
        },
        "fixture": {"bars": bars, "symbols": list(symbol_names), "repeats": repeats},
        "parity": {"portfolio_target": target_parity, "package_atomic": package_parity},
        "performance": {
            "e4_portfolio_target_score": _stats(
                target_score_stats,
                bars=bars,
                extra={"profile": "score", "python_callbacks": 0, "boundary_calls": 1},
            ),
            "e4_portfolio_target_audit": _stats(
                target_audit_stats,
                bars=bars,
                extra={
                    "profile": "audit",
                    "python_callbacks": int(target_audit.payload["python_callbacks"]),
                    "boundary_calls": int(target_audit.payload["boundary_calls"]),
                    "cold_report_adaptation_included": True,
                },
            ),
            "e4_python_event_oracle_score": _stats(target_python_stats, bars=bars, extra={"profile": "score"}),
            "e5_package_atomic_score": _stats(
                package_score_stats,
                bars=bars,
                extra={"profile": "score", "python_callbacks": 0, "boundary_calls": 1},
            ),
            "e5_package_atomic_audit": _stats(
                package_audit_stats,
                bars=bars,
                extra={
                    "profile": "audit",
                    "python_callbacks": int(package_audit.payload["python_callbacks"]),
                    "boundary_calls": int(package_audit.payload["boundary_calls"]),
                    "cold_report_adaptation_included": True,
                },
            ),
            "e5_python_event_oracle_score": _stats(package_python_stats, bars=bars, extra={"profile": "score"}),
        },
        "prepared_cache": cache.diagnostics,
        "fingerprint": fingerprint,
    }


def main() -> int:
    """Run the benchmark and write a deterministic JSON artifact."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bars", type=int, default=2_000)
    parser.add_argument("--symbols", type=int, default=8)
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    result = run(bars=args.bars, symbols=args.symbols, repeats=args.repeats)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
