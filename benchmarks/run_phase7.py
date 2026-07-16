#!/usr/bin/env python3
"""
Phase 7 benchmark runner.

This is a lightweight stdlib CLI around the public V2 engines. It intentionally
does not require pytest or a benchmark plugin so it can run inside notebooks,
SSH shells, and CI jobs with the same command.
"""

from __future__ import annotations

import argparse
import gc
import json
import math
import resource
import statistics
import sys
import time
import tracemalloc
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple


PACKAGE_DIR = Path(__file__).resolve().parents[1]
PROJECT_DIR = PACKAGE_DIR.parent
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))


@dataclass(frozen=True)
class BenchmarkProfile:
    name: str
    bars: int
    symbols: int
    order_count: int
    repeats: int


@dataclass
class BenchmarkRecord:
    backend: str
    profile: str
    status: str
    bars: int
    symbols: int
    bar_symbols: int
    order_count: int
    event_count: int
    signal_transitions: int
    warmup_seconds: Optional[float]
    runtime_seconds: Optional[float]
    runtime_min_seconds: Optional[float]
    runtime_max_seconds: Optional[float]
    peak_memory_mb: Optional[float]
    rss_delta_mb: Optional[float]
    throughput_bar_symbols_per_second: Optional[float] = None
    throughput_orders_per_second: Optional[float] = None
    threshold_metric: Optional[str] = None
    threshold_value: Optional[float] = None
    threshold_limit: Optional[float] = None
    threshold_passed: Optional[bool] = None
    error: Optional[str] = None


PROFILES = {
    "smoke": BenchmarkProfile(name="smoke", bars=1_000, symbols=4, order_count=500, repeats=2),
    "standard": BenchmarkProfile(name="standard", bars=25_000, symbols=20, order_count=25_000, repeats=5),
    "large": BenchmarkProfile(name="large", bars=100_000, symbols=50, order_count=100_000, repeats=3),
}


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Run quantbt Phase 7 benchmarks.")
    parser.add_argument("--profile", choices=sorted(PROFILES), default="smoke")
    parser.add_argument("--repeats", type=int, default=None)
    parser.add_argument("--include-nautilus", action="store_true")
    parser.add_argument("--no-tracemalloc", action="store_true", help="Measure runtime without Python allocation tracing.")
    parser.add_argument("--json-out", type=Path, default=PACKAGE_DIR / "benchmarks" / "out" / "phase7_results.json")
    parser.add_argument("--md-out", type=Path, default=PACKAGE_DIR / "benchmarks" / "out" / "phase7_results.md")
    args = parser.parse_args(argv)

    profile = PROFILES[args.profile]
    if args.repeats is not None:
        profile = BenchmarkProfile(
            name=profile.name,
            bars=profile.bars,
            symbols=profile.symbols,
            order_count=profile.order_count,
            repeats=max(1, args.repeats),
        )

    records = run_all(profile=profile, include_nautilus=args.include_nautilus, trace_memory=not args.no_tracemalloc)
    write_outputs(records=records, profile=profile, json_out=args.json_out, md_out=args.md_out)
    for record in records:
        print(_record_line(record))
    return 0 if all(r.status in {"passed", "skipped"} for r in records) else 1


def run_all(profile: BenchmarkProfile, include_nautilus: bool = False, trace_memory: bool = True) -> List[BenchmarkRecord]:
    records = [
        run_native_vectorized(profile, trace_memory=trace_memory),
        run_native_event(profile, trace_memory=trace_memory),
        run_native_event_prepared(profile, trace_memory=trace_memory),
        run_portfolio_legacy(profile, trace_memory=trace_memory),
    ]
    if include_nautilus:
        records.append(run_nautilus(profile, trace_memory=trace_memory))
    else:
        records.append(_skipped("nautilus", profile, "pass --include-nautilus to run optional backend"))
    return records


def run_native_vectorized(profile: BenchmarkProfile, trace_memory: bool = True) -> BenchmarkRecord:
    try:
        import pandas as pd

        from quantbt import AccountConfig, BacktestEngineV2

        idx, frames = _make_market_frames(profile.bars, profile.symbols)
        signals = _make_signals(idx, profile.symbols)
        transitions = _count_signal_transitions(signals.values())

        def workload():
            engine = BacktestEngineV2(
                data=frames,
                signals=signals,
                backend="native_vectorized",
                account=AccountConfig(initial_capital=1_000_000.0, leverage=10.0),
                alloc_per_trade=10_000.0,
                hedge_type="signal_notional",
                use_funding=False,
            )
            return engine.result.equity.iloc[-1]

        return _measure(
            backend="native_vectorized",
            profile=profile,
            workload=workload,
            order_count=transitions,
            event_count=profile.bars * profile.symbols,
            signal_transitions=transitions,
            trace_memory=trace_memory,
        )
    except Exception as exc:
        return _failed("native_vectorized", profile, exc)


def run_native_event(profile: BenchmarkProfile, trace_memory: bool = True) -> BenchmarkRecord:
    try:
        from quantbt import AccountConfig, BacktestEngineV2

        idx, frames = _make_market_frames(profile.bars, profile.symbols)
        orders = _make_orders(idx, profile.order_count, profile.symbols)

        def workload():
            engine = BacktestEngineV2(
                data=frames,
                backend="native_event",
                orders=orders,
                account=AccountConfig(initial_capital=1_000_000.0, leverage=10.0),
                use_funding=False,
            )
            return engine.result.equity.iloc[-1]

        return _measure(
            backend="native_event",
            profile=profile,
            workload=workload,
            order_count=len(orders),
            event_count=profile.bars + len(orders),
            signal_transitions=0,
            trace_memory=trace_memory,
        )
    except Exception as exc:
        return _failed("native_event", profile, exc)


def run_native_event_prepared(profile: BenchmarkProfile, trace_memory: bool = True) -> BenchmarkRecord:
    try:
        from quantbt import AccountConfig
        from quantbt.backends import NativeEventBackend, NativeEventConfig

        idx, frames = _make_market_frames(profile.bars, profile.symbols)
        orders = _make_orders(idx, profile.order_count, profile.symbols)
        symbols = list(frames.keys())
        closes = {symbol: frame["close"] for symbol, frame in frames.items()}
        highs = {symbol: frame["high"] for symbol, frame in frames.items()}
        lows = {symbol: frame["low"] for symbol, frame in frames.items()}
        backend = NativeEventBackend(
            NativeEventConfig(
                account=AccountConfig(initial_capital=1_000_000.0, leverage=10.0),
                use_funding=False,
            )
        )
        market_arrays = backend.prepare_market_arrays(
            datetime_index=idx,
            closes=closes,
            highs=highs,
            lows=lows,
            symbols=symbols,
        )
        compiled_orders = backend.compile_orders(datetime_index=idx, orders=orders, symbols=symbols)

        def workload():
            result = backend.run_orders(
                datetime_index=idx,
                orders=orders,
                closes=closes,
                highs=highs,
                lows=lows,
                symbols=symbols,
                market_arrays=market_arrays,
                compiled_orders=compiled_orders,
            )
            return result.equity.iloc[-1]

        return _measure(
            backend="native_event_prepared",
            profile=profile,
            workload=workload,
            order_count=len(orders),
            event_count=profile.bars + len(orders),
            signal_transitions=0,
            trace_memory=trace_memory,
        )
    except Exception as exc:
        return _failed("native_event_prepared", profile, exc)


def run_portfolio_legacy(profile: BenchmarkProfile, trace_memory: bool = True) -> BenchmarkRecord:
    try:
        from quantbt import AccountConfig, PortfolioBacktestEngine

        idx, frames = _make_market_frames(profile.bars, profile.symbols)
        positions = _make_portfolio_positions(idx, profile.symbols)
        closes = {symbol: frame["close"] for symbol, frame in frames.items()}
        transitions = _count_signal_transitions(positions.values())

        def workload():
            engine = PortfolioBacktestEngine(
                positions=positions,
                closes=closes,
                highs=closes,
                lows=closes,
                datetime_index=idx,
                mode="longshort",
                account=AccountConfig(initial_capital=1_000_000.0, leverage=10.0),
                fee_rate=0.0,
                alloc_per_trade=10_000.0,
                use_funding=False,
            )
            return engine.result.equity.iloc[-1]

        return _measure(
            backend="portfolio_legacy",
            profile=profile,
            workload=workload,
            order_count=transitions,
            event_count=profile.bars * profile.symbols,
            signal_transitions=transitions,
            trace_memory=trace_memory,
        )
    except Exception as exc:
        return _failed("portfolio_legacy", profile, exc)


def run_nautilus(profile: BenchmarkProfile, trace_memory: bool = True) -> BenchmarkRecord:
    try:
        from quantbt import AccountConfig, BacktestEngineV2
        from quantbt.adapters.nautilus import NautilusBacktestEngine

        NautilusBacktestEngine.check_available()
        idx, frames = _make_market_frames(min(profile.bars, 10_000), 1)
        symbol, frame = next(iter(frames.items()))
        signal = _make_signals(idx, 1)[symbol]
        transitions = _count_signal_transitions([signal])

        def workload():
            engine = BacktestEngineV2(
                data=frame,
                signals=signal,
                symbols=["BTCUSDT-PERP.BINANCE"],
                backend="nautilus",
                account=AccountConfig(initial_capital=10_000.0, leverage=10.0),
                alloc_per_trade=1_000.0,
                use_funding=False,
            )
            return engine.result.equity.iloc[-1]

        nautilus_profile = BenchmarkProfile(
            name=profile.name,
            bars=len(idx),
            symbols=1,
            order_count=transitions,
            repeats=max(1, min(profile.repeats, 2)),
        )
        return _measure(
            backend="nautilus",
            profile=nautilus_profile,
            workload=workload,
            order_count=transitions,
            event_count=len(idx),
            signal_transitions=transitions,
            trace_memory=trace_memory,
        )
    except ImportError as exc:
        return _skipped("nautilus", profile, str(exc))
    except Exception as exc:
        return _failed("nautilus", profile, exc)


def _measure(
    backend: str,
    profile: BenchmarkProfile,
    workload,
    order_count: int,
    event_count: int,
    signal_transitions: int,
    trace_memory: bool = True,
) -> BenchmarkRecord:
    gc.collect()
    rss_before = _rss_mb()
    if trace_memory:
        tracemalloc.start()
    warmup_start = time.perf_counter()
    workload()
    warmup_seconds = time.perf_counter() - warmup_start

    runtimes: List[float] = []
    for _ in range(profile.repeats):
        start = time.perf_counter()
        workload()
        runtimes.append(time.perf_counter() - start)
    peak = 0
    if trace_memory:
        current, peak = tracemalloc.get_traced_memory()
        del current
        tracemalloc.stop()
    rss_after = _rss_mb()

    runtime = statistics.mean(runtimes)
    record = BenchmarkRecord(
        backend=backend,
        profile=profile.name,
        status="passed",
        bars=profile.bars,
        symbols=profile.symbols,
        bar_symbols=profile.bars * profile.symbols,
        order_count=order_count,
        event_count=event_count,
        signal_transitions=signal_transitions,
        warmup_seconds=warmup_seconds,
        runtime_seconds=runtime,
        runtime_min_seconds=min(runtimes),
        runtime_max_seconds=max(runtimes),
        peak_memory_mb=(peak / (1024 * 1024)) if trace_memory else None,
        rss_delta_mb=max(0.0, rss_after - rss_before),
        throughput_bar_symbols_per_second=(profile.bars * profile.symbols / runtime) if runtime > 0.0 else None,
        throughput_orders_per_second=(order_count / runtime) if runtime > 0.0 and order_count > 0 else None,
    )
    return _attach_threshold(record)


def _make_market_frames(bars: int, symbols: int):
    import numpy as np
    import pandas as pd

    idx = pd.date_range("2020-01-01", periods=bars, freq="1min", tz="UTC")
    base = 100.0 + np.cumsum(np.sin(np.arange(bars) / 37.0) * 0.05)
    frames = {}
    for j in range(symbols):
        close = base + j * 0.25
        frames[f"SYM{j:03d}"] = pd.DataFrame(
            {
                "open": close,
                "high": close * 1.001,
                "low": close * 0.999,
                "close": close,
                "volume": 1_000.0 + j,
            },
            index=idx,
        )
    return idx, frames


def _make_signals(idx, symbols: int):
    import numpy as np
    import pandas as pd

    out = {}
    n = len(idx)
    grid = np.arange(n)
    for j in range(symbols):
        raw = np.where(((grid // (25 + j % 5)) + j) % 4 == 0, 1.0, 0.0)
        out[f"SYM{j:03d}"] = pd.Series(raw, index=idx)
    return out


def _make_portfolio_positions(idx, symbols: int):
    import numpy as np
    import pandas as pd

    out = {}
    n = len(idx)
    grid = np.arange(n)
    for j in range(symbols):
        active = np.where(((grid // (40 + j % 7)) + j) % 5 == 0, 1.0, 0.0)
        sign = 1.0 if j % 2 == 0 else -1.0
        out[f"SYM{j:03d}"] = pd.Series(active * sign, index=idx)
    return out


def _make_orders(idx, order_count: int, symbols: int):
    import numpy as np

    from quantbt import OrderIntent, OrderSide, OrderType, TimeInForce

    if order_count <= 0:
        return []
    positions = np.linspace(1, len(idx) - 1, num=order_count, dtype=int)
    orders = []
    for k, bar in enumerate(positions):
        side = OrderSide.BUY if k % 2 == 0 else OrderSide.SELL
        orders.append(
            OrderIntent(
                timestamp=idx[int(bar)],
                symbol=f"SYM{k % symbols:03d}",
                side=side,
                order_type=OrderType.MARKET,
                qty=1.0,
                tif=TimeInForce.IOC,
            )
        )
    return orders


def _count_signal_transitions(signals: Iterable) -> int:
    count = 0
    for sig in signals:
        values = sig.to_numpy()
        if len(values) > 1:
            count += int((values[1:] != values[:-1]).sum())
    return count


def write_outputs(
    records: List[BenchmarkRecord],
    profile: BenchmarkProfile,
    json_out: Path,
    md_out: Path,
) -> None:
    json_out.parent.mkdir(parents=True, exist_ok=True)
    md_out.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "profile": asdict(profile),
        "records": [asdict(record) for record in records],
        "thresholds": _load_thresholds(),
    }
    json_out.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    md_out.write_text(_markdown_report(records, profile), encoding="utf-8")


def _markdown_report(records: List[BenchmarkRecord], profile: BenchmarkProfile) -> str:
    lines = [
        "# Phase 7 Benchmark Results",
        "",
        f"Profile: `{profile.name}`",
        "",
        "| backend | status | bars | symbols | orders | events | warmup s | runtime s | peak MB | throughput | threshold | note |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |",
    ]
    for record in records:
        threshold = "-"
        if record.threshold_metric is not None:
            verdict = "pass" if record.threshold_passed else "fail"
            threshold = f"{record.threshold_metric}={_fmt(record.threshold_value)} <= {_fmt(record.threshold_limit)} ({verdict})"
        lines.append(
            "| {backend} | {status} | {bars} | {symbols} | {orders} | {events} | {warmup} | {runtime} | {peak} | {throughput} | {threshold} | {note} |".format(
                backend=record.backend,
                status=record.status,
                bars=record.bars,
                symbols=record.symbols,
                orders=record.order_count,
                events=record.event_count,
                warmup=_fmt(record.warmup_seconds),
                runtime=_fmt(record.runtime_seconds),
                peak=_fmt(record.peak_memory_mb),
                throughput=_fmt(record.throughput_bar_symbols_per_second),
                threshold=threshold,
                note=record.error or "",
            )
        )
    lines.append("")
    lines.append("Thresholds: see `benchmarks/phase7_thresholds.json`.")
    return "\n".join(lines) + "\n"


def _record_line(record: BenchmarkRecord) -> str:
    return (
        f"{record.backend}: {record.status} "
        f"warmup={_fmt(record.warmup_seconds)}s runtime={_fmt(record.runtime_seconds)}s "
        f"peak={_fmt(record.peak_memory_mb)}MB {record.error or ''}"
    )


def _fmt(value: Optional[float]) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "-"
    return f"{value:.6f}"


def _rss_mb() -> float:
    try:
        value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    except Exception:
        return 0.0
    if sys.platform == "darwin":
        return value / (1024 * 1024)
    return value / 1024


def _failed(backend: str, profile: BenchmarkProfile, exc: Exception) -> BenchmarkRecord:
    return BenchmarkRecord(
        backend=backend,
        profile=profile.name,
        status="failed",
        bars=profile.bars,
        symbols=profile.symbols,
        bar_symbols=profile.bars * profile.symbols,
        order_count=0,
        event_count=0,
        signal_transitions=0,
        warmup_seconds=None,
        runtime_seconds=None,
        runtime_min_seconds=None,
        runtime_max_seconds=None,
        peak_memory_mb=None,
        rss_delta_mb=None,
        error=f"{type(exc).__name__}: {exc}",
    )


def _skipped(backend: str, profile: BenchmarkProfile, reason: str) -> BenchmarkRecord:
    return BenchmarkRecord(
        backend=backend,
        profile=profile.name,
        status="skipped",
        bars=profile.bars,
        symbols=profile.symbols,
        bar_symbols=profile.bars * profile.symbols,
        order_count=0,
        event_count=0,
        signal_transitions=0,
        warmup_seconds=None,
        runtime_seconds=None,
        runtime_min_seconds=None,
        runtime_max_seconds=None,
        peak_memory_mb=None,
        rss_delta_mb=None,
        error=reason,
    )


def _load_thresholds() -> Dict:
    path = PACKAGE_DIR / "benchmarks" / "phase7_thresholds.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _attach_threshold(record: BenchmarkRecord) -> BenchmarkRecord:
    thresholds = _load_thresholds()
    backend_thresholds = thresholds.get(record.backend, {})
    if record.runtime_seconds is None:
        return record

    metric = None
    value = None
    limit = None
    if record.profile == "smoke" and "smoke_max_runtime_seconds" in backend_thresholds:
        metric = "runtime_seconds"
        value = record.runtime_seconds
        limit = float(backend_thresholds["smoke_max_runtime_seconds"])
    elif record.backend in {"native_vectorized", "portfolio_legacy"}:
        key = f"{record.profile}_max_seconds_per_million_bar_symbols"
        if key in backend_thresholds and record.bar_symbols > 0:
            metric = "seconds_per_million_bar_symbols"
            value = record.runtime_seconds / (record.bar_symbols / 1_000_000.0)
            limit = float(backend_thresholds[key])
    elif record.backend in {"native_event", "native_event_prepared"}:
        key = f"{record.profile}_max_seconds_per_100k_orders"
        if key in backend_thresholds and record.order_count > 0:
            metric = "seconds_per_100k_orders"
            value = record.runtime_seconds / (record.order_count / 100_000.0)
            limit = float(backend_thresholds[key])
    elif record.backend == "nautilus":
        key = f"{record.profile}_max_seconds_per_100k_bars"
        if key in backend_thresholds and record.bars > 0:
            metric = "seconds_per_100k_bars"
            value = record.runtime_seconds / (record.bars / 100_000.0)
            limit = float(backend_thresholds[key])

    record.threshold_metric = metric
    record.threshold_value = value
    record.threshold_limit = limit
    record.threshold_passed = None if value is None or limit is None else bool(value <= limit)
    return record


if __name__ == "__main__":
    raise SystemExit(main())
