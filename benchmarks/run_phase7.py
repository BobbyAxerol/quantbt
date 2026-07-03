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

    records = run_all(profile=profile, include_nautilus=args.include_nautilus)
    write_outputs(records=records, profile=profile, json_out=args.json_out, md_out=args.md_out)
    for record in records:
        print(_record_line(record))
    return 0 if all(r.status in {"passed", "skipped"} for r in records) else 1


def run_all(profile: BenchmarkProfile, include_nautilus: bool = False) -> List[BenchmarkRecord]:
    records = [
        run_native_vectorized(profile),
        run_native_event(profile),
    ]
    if include_nautilus:
        records.append(run_nautilus(profile))
    else:
        records.append(_skipped("nautilus", profile, "pass --include-nautilus to run optional backend"))
    return records


def run_native_vectorized(profile: BenchmarkProfile) -> BenchmarkRecord:
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
        )
    except Exception as exc:
        return _failed("native_vectorized", profile, exc)


def run_native_event(profile: BenchmarkProfile) -> BenchmarkRecord:
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
        )
    except Exception as exc:
        return _failed("native_event", profile, exc)


def run_nautilus(profile: BenchmarkProfile) -> BenchmarkRecord:
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
) -> BenchmarkRecord:
    gc.collect()
    rss_before = _rss_mb()
    tracemalloc.start()
    warmup_start = time.perf_counter()
    workload()
    warmup_seconds = time.perf_counter() - warmup_start
    current, peak = tracemalloc.get_traced_memory()
    del current

    runtimes: List[float] = []
    for _ in range(profile.repeats):
        start = time.perf_counter()
        workload()
        runtimes.append(time.perf_counter() - start)
    current, peak = tracemalloc.get_traced_memory()
    del current
    tracemalloc.stop()
    rss_after = _rss_mb()

    return BenchmarkRecord(
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
        runtime_seconds=statistics.mean(runtimes),
        runtime_min_seconds=min(runtimes),
        runtime_max_seconds=max(runtimes),
        peak_memory_mb=peak / (1024 * 1024),
        rss_delta_mb=max(0.0, rss_after - rss_before),
    )


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
    }
    json_out.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    md_out.write_text(_markdown_report(records, profile), encoding="utf-8")


def _markdown_report(records: List[BenchmarkRecord], profile: BenchmarkProfile) -> str:
    lines = [
        "# Phase 7 Benchmark Results",
        "",
        f"Profile: `{profile.name}`",
        "",
        "| backend | status | bars | symbols | orders | events | warmup s | runtime s | peak MB | note |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for record in records:
        lines.append(
            "| {backend} | {status} | {bars} | {symbols} | {orders} | {events} | {warmup} | {runtime} | {peak} | {note} |".format(
                backend=record.backend,
                status=record.status,
                bars=record.bars,
                symbols=record.symbols,
                orders=record.order_count,
                events=record.event_count,
                warmup=_fmt(record.warmup_seconds),
                runtime=_fmt(record.runtime_seconds),
                peak=_fmt(record.peak_memory_mb),
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


if __name__ == "__main__":
    raise SystemExit(main())
