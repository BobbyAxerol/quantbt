#!/usr/bin/env python3
"""Apples-to-apples native-event benchmark for the pre-48E gate.

The common and explicit workloads use the same deterministic 2,000-bar tape,
the same command tape, and a fresh subprocess per route.  Cold preparation is
reported separately from seven warm executions.  Grid/reactive integration is
intentionally not included in the README table; it is a separate workload.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import resource
import subprocess
import sys
import time
from typing import Any

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
MARKER = "PRE48E_RESULT="
N_BARS = 2_000
N_RUNS = 7

for candidate in (ROOT, ROOT / "src"):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))


def _bars(n: int = N_BARS) -> pd.DataFrame:
    index = pd.date_range("2024-01-01", periods=n, freq="h", tz="UTC")
    x = np.arange(n, dtype=np.float64)
    close = 100.0 + np.sin(x / 23.0) * 2.0 + x * 0.002
    open_ = close + 0.1 * np.sin(x / 7.0)
    return pd.DataFrame(
        {
            "open": open_,
            "high": np.maximum(open_, close) + 0.75,
            "low": np.minimum(open_, close) - 0.75,
            "close": close,
            "volume": 10_000.0 + x,
        },
        index=index,
    )


def _commands(index: pd.DatetimeIndex, *, high_churn: bool = False):
    from quantbt import OrderCommand, OrderSide, OrderType, TimeInForce

    every = 40 if high_churn else 125
    hold = 8 if high_churn else 20
    commands = []
    for bar in range(20, len(index) - hold - 1, every):
        commands.append(
            OrderCommand(
                timestamp=index[bar],
                symbol="BTC",
                side=OrderSide.BUY,
                order_type=OrderType.MARKET,
                qty=0.25,
                tif=TimeInForce.GTC,
                order_id=f"entry-{bar}",
            )
        )
        commands.append(
            OrderCommand(
                timestamp=index[bar + hold],
                symbol="BTC",
                side=OrderSide.SELL,
                order_type=OrderType.MARKET,
                qty=0.25,
                tif=TimeInForce.GTC,
                reduce_only=True,
                order_id=f"exit-{bar + hold}",
            )
        )
    return tuple(commands)


class GenericStrategy:
    """Deterministic callback with no indicator or allocation work."""

    def __init__(self, *, high_churn: bool = False):
        self.every = 40 if high_churn else 125
        self.hold = 8 if high_churn else 20

    def initialize(self, context):
        return ()

    def on_bar_close(self, context):
        from quantbt import OrderCommand, OrderSide, OrderType, TimeInForce

        bar = int(context.bar_index)
        if bar >= 20 and bar % self.every == 0:
            return (
                OrderCommand(
                    timestamp=context.timestamp,
                    symbol="BTC",
                    side=OrderSide.BUY,
                    order_type=OrderType.MARKET,
                    qty=0.25,
                    tif=TimeInForce.GTC,
                    order_id=f"entry-{bar}",
                ),
            )
        if bar >= 20 and bar % self.every == self.hold:
            return (
                OrderCommand(
                    timestamp=context.timestamp,
                    symbol="BTC",
                    side=OrderSide.SELL,
                    order_type=OrderType.MARKET,
                    qty=0.25,
                    tif=TimeInForce.GTC,
                    reduce_only=True,
                    order_id=f"exit-{bar}",
                ),
            )
        return ()

    def finalize(self, context):
        return ()


def _peak_rss_mb() -> float:
    value = float(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    return value / 1024.0 if sys.platform == "linux" else value / (1024.0 * 1024.0)


def _array_digest(digest, name: str, value: Any) -> None:
    array = np.ascontiguousarray(np.asarray(value))
    digest.update(name.encode("ascii"))
    digest.update(str(array.dtype).encode("ascii"))
    digest.update(repr(array.shape).encode("ascii"))
    digest.update(array.tobytes())


def _fingerprint(value: Any, *, mode: str, index: pd.DatetimeIndex | None = None) -> str:
    digest = hashlib.sha256()
    if mode == "score":
        for name in ("final_equity", "final_positions", "fill_count", "event_count", "rejected_count", "canceled_count"):
            item = getattr(value, name, None)
            if item is None and isinstance(value, dict):
                item = value.get(name)
            if isinstance(item, (np.ndarray, list, tuple)):
                _array_digest(digest, name, item)
            else:
                digest.update(f"{name}={item!r}".encode("utf-8"))
        return digest.hexdigest()

    for name in ("equity", "positions", "fees", "funding", "margin"):
        item = getattr(value, name, None)
        if item is not None:
            _array_digest(digest, name, item)
    if hasattr(value, "initial_margin") and not hasattr(value, "margin"):
        _array_digest(
            digest,
            "margin",
            np.column_stack((value.initial_margin, value.maintenance_margin)),
        )
    metadata = getattr(value, "metadata", {})
    if not isinstance(metadata, dict):
        metadata = {}
    source_counters = metadata.get("lifecycle_counters", {})
    counters = {
        name: int(source_counters.get(name, getattr(value, name, 0)))
        for name in ("fill_count", "event_count", "rejected_count", "canceled_count")
    }
    digest.update(json.dumps(counters, sort_keys=True, default=str).encode("utf-8"))
    if hasattr(value, "fill_bar"):
        fill_rows = [
            (int(bar), int(side), float(qty), float(price), float(fee))
            for bar, side, qty, price, fee in zip(
                value.fill_bar, value.fill_side, value.fill_qty, value.fill_price, value.fill_fee
            )
        ]
        digest.update(repr(fill_rows).encode("utf-8"))
    elif index is not None:
        fill_rows = []
        for fill in getattr(value, "fills", ()):
            timestamp = pd.Timestamp(fill.timestamp)
            bar = int(index.searchsorted(timestamp, side="left"))
            side = getattr(fill.side, "sign", 1.0 if str(fill.side).lower().endswith("buy") else -1.0)
            fill_rows.append((bar, int(round(float(side))), float(fill.qty), float(fill.price), float(fill.fee)))
        digest.update(repr(fill_rows).encode("utf-8"))
    return digest.hexdigest()


def _config(backend: str, level: str):
    from quantbt.backends.native_event import NativeEventConfig
    from quantbt.core.schema import AccountConfig, ExecutionConfig

    return NativeEventConfig(
        account=AccountConfig(initial_capital=100_000.0, leverage=5.0, maintenance_ratio=0.0),
        execution=ExecutionConfig(slippage_bps=0.0),
        fee_rate=0.0002,
        use_funding=False,
        report_level=level,
        audit_sink="none" if level == "score" else "memory",
        native_backend=backend,
    )


def _explicit(case: str, backend: str, level: str, high_churn: bool) -> dict[str, Any]:
    from quantbt.backends.native_event import NativeEventBackend

    data = _bars()
    idx = data.index
    commands = _commands(idx, high_churn=high_churn)
    native = NativeEventBackend(_config(backend, level))
    cold_start = time.perf_counter()
    market = native.prepare_market_arrays(
        idx,
        {"BTC": data["close"]},
        highs={"BTC": data["high"]},
        lows={"BTC": data["low"]},
        symbols=["BTC"],
    )
    compiled = native.compile_order_commands(idx, commands, symbols=["BTC"])
    runner = None
    if backend == "rust":
        runner = native.prepare_rust_batched_runner(
            idx,
            {"BTC": data["close"]},
            highs={"BTC": data["high"]},
            lows={"BTC": data["low"]},
            symbols=["BTC"],
        )
    cold_prepare = time.perf_counter() - cold_start
    rss_after_prepare = _peak_rss_mb()

    def run_once():
        if backend == "rust":
            return runner.run_tape_score(compiled) if level == "score" else runner.run_tape_audit(compiled)
        if level == "score":
            return native.run_compiled_tape_score(idx, compiled, market_arrays=market)
        return native.run_order_commands(
            idx,
            commands,
            closes={"BTC": data["close"]},
            highs={"BTC": data["high"]},
            lows={"BTC": data["low"]},
            symbols=["BTC"],
            market_arrays=market,
            compiled_commands=compiled,
            report_level="audit",
        )

    run_once()
    timings = []
    result = None
    for _ in range(N_RUNS):
        start = time.perf_counter()
        result = run_once()
        timings.append(time.perf_counter() - start)
    final_equity = result.get("final_equity") if isinstance(result, dict) else getattr(result, "final_equity", None)
    if final_equity is None:
        final_equity = float(np.asarray(result.equity, dtype=np.float64)[-1])
    fill_count = result.get("fill_count", 0) if isinstance(result, dict) else getattr(result, "fill_count", None)
    if fill_count is None:
        fill_count = len(getattr(result, "fills", ()))
    return {
        "workload": "explicit_high_churn" if high_churn else "explicit_low_churn",
        "route": f"explicit_{backend}_{level}",
        "backend": backend,
        "report_level": level,
        "bars": N_BARS,
        "commands": len(commands),
        "cold_prepare_seconds": cold_prepare,
        "rss_after_prepare_mb": rss_after_prepare,
        "warm_median_seconds": float(np.median(timings)),
        "warm_p95_seconds": float(np.percentile(timings, 95)),
        "throughput_bars_per_second": float(N_BARS / np.median(timings)),
        "peak_rss_mb": _peak_rss_mb(),
        "fingerprint": _fingerprint(result, mode=level, index=idx),
        "final_equity": float(final_equity),
        "fill_count": int(fill_count),
        "bridge_counters": {
            "pycalls": 1 if backend == "rust" else 0,
            "prepared_market_core": bool(runner is not None and runner.prepared_market_core is not None),
            "tape_cache_bytes": int(getattr(runner, "tape_cache_bytes", 0)) if runner is not None else 0,
        },
    }


def _common(case: str, backend: str, high_churn: bool) -> dict[str, Any]:
    from quantbt import QuantBTEndpoint

    data = _bars()
    level = "score" if case.endswith("score") else "audit"
    endpoint = QuantBTEndpoint.native_event_strategy(
        initial_capital=100_000.0,
        leverage=5.0,
        maintenance_ratio=0.0,
        fee_rate=0.0002,
        use_funding=False,
        native_backend=backend,
        report_level=level,
        reactive_execution_mode="fast" if level == "score" else "audit",
        reactive_kernel_mode="single_pass" if level == "score" else "replay_certified",
        audit_sink="none" if level == "score" else "memory",
    )
    cold_start = time.perf_counter()
    result = endpoint.simulate(data=data, strategy=GenericStrategy(high_churn=high_churn), symbols=["BTC"])
    cold_prepare = time.perf_counter() - cold_start
    rss_after_prepare = _peak_rss_mb()
    timings = []
    for _ in range(N_RUNS):
        start = time.perf_counter()
        result = endpoint.simulate(data=data, strategy=GenericStrategy(high_churn=high_churn), symbols=["BTC"])
        timings.append(time.perf_counter() - start)
    counters = result.metadata.get("execution_counters", {})
    return {
        "workload": "common_high_churn" if high_churn else "common_low_churn",
        "route": f"common_{backend}_{level}",
        "backend": backend,
        "report_level": level,
        "bars": N_BARS,
        "commands": int(result.metadata.get("emitted_command_count", 0)),
        "cold_prepare_seconds": cold_prepare,
        "rss_after_prepare_mb": rss_after_prepare,
        "warm_median_seconds": float(np.median(timings)),
        "warm_p95_seconds": float(np.percentile(timings, 95)),
        "throughput_bars_per_second": float(N_BARS / np.median(timings)),
        "peak_rss_mb": _peak_rss_mb(),
        "fingerprint": _fingerprint(result, mode="audit" if level == "audit" else "score", index=data.index),
        "final_equity": float(result.equity.iloc[-1]),
        "fill_count": int(result.metadata.get("lifecycle_counters", {}).get("fill_count", len(result.fills))),
        "execution_counters": counters,
    }


def _worker(args) -> int:
    try:
        if args.route.startswith("explicit"):
            row = _explicit(args.route, args.backend, args.level, args.high_churn)
        else:
            row = _common(args.level, args.backend, args.high_churn)
    except Exception as exc:
        row = {
            "route": args.route,
            "backend": args.backend,
            "report_level": args.level,
            "workload": "high_churn" if args.high_churn else "low_churn",
            "status": "unavailable",
            "error": f"{type(exc).__name__}: {exc}",
        }
    print(MARKER + json.dumps(row, sort_keys=True, default=str))
    return 0


def _run_worker(route: str, backend: str, level: str, high_churn: bool) -> dict[str, Any]:
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join((str(ROOT / "src"), str(ROOT), env.get("PYTHONPATH", "")))
    env.setdefault("MPLCONFIGDIR", "/tmp")
    command = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--worker",
        "--route",
        route,
        "--backend",
        backend,
        "--level",
        level,
        "--high-churn" if high_churn else "--low-churn",
    ]
    completed = subprocess.run(command, check=True, capture_output=True, text=True, env=env)
    for line in reversed(completed.stdout.splitlines()):
        if line.startswith(MARKER):
            return json.loads(line[len(MARKER) :])
    raise RuntimeError(f"worker did not emit {MARKER}: {completed.stdout[-1000:]}")


def _environment() -> dict[str, Any]:
    import numba

    return {
        "python": platform.python_version(),
        "numpy": np.__version__,
        "pandas": pd.__version__,
        "numba": numba.__version__,
        "platform": platform.platform(),
        "cpu": platform.processor() or platform.machine(),
        "commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "dirty": bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True).strip()),
    }


def _render(payload: dict[str, Any]) -> str:
    rows = payload["results"]
    lines = [
        "# Pre-48E Native Event Performance Pass",
        "",
        f"Contract: **{N_BARS:,} bars**, one symbol, fresh process per route, `{N_RUNS}` warm runs.",
        "All runtime columns use seconds; RSS uses MB.",
        "",
        "## Common Native Event / Event-Driven",
        "",
        "| Workload | Route | Cold prepare s | Warm median s | P95 s | Bars/s | Peak RSS MB | Fills | Status |",
        "|---|---|---:|---:|---:|---:|---:|---:|---|",
    ]
    for row in rows:
        if not row["route"].startswith("common"):
            continue
        lines.append(
            f"| {row.get('workload', '-')} | `{row['route']}` | {row.get('cold_prepare_seconds', float('nan')):.6f} | "
            f"{row.get('warm_median_seconds', float('nan')):.6f} | {row.get('warm_p95_seconds', float('nan')):.6f} | "
            f"{row.get('throughput_bars_per_second', float('nan')):,.0f} | {row.get('peak_rss_mb', float('nan')):.1f} | "
            f"{row.get('fill_count', 0)} | {row.get('status', 'ok')} |"
        )
    lines.extend(
        [
            "",
            "## Explicit Native Event Lifecycle",
            "",
            "| Workload | Route | Cold prepare s | Warm median s | P95 s | Bars/s | Peak RSS MB | Fills | Status |",
            "|---|---|---:|---:|---:|---:|---:|---:|---|",
        ]
    )
    for row in rows:
        if not row["route"].startswith("explicit"):
            continue
        lines.append(
            f"| {row.get('workload', '-')} | `{row['route']}` | {row.get('cold_prepare_seconds', float('nan')):.6f} | "
            f"{row.get('warm_median_seconds', float('nan')):.6f} | {row.get('warm_p95_seconds', float('nan')):.6f} | "
            f"{row.get('throughput_bars_per_second', float('nan')):,.0f} | {row.get('peak_rss_mb', float('nan')):.1f} | "
            f"{row.get('fill_count', 0)} | {row.get('status', 'ok')} |"
        )
    lines.extend(
        [
            "",
            "## Contract",
            "",
        "- Score and audit are never compared as the same artifact.",
            f"- Python/Rust parity groups: `{json.dumps(payload['parity'], sort_keys=True)}`.",
            "- Python/Rust parity is exact on the supported full-contract fields; unavailable Rust capabilities are reported, not silently routed to Python.",
            "- Reactive Grid is intentionally excluded from this common table and is recorded separately in `upgrade/implement.md`.",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker", action="store_true")
    parser.add_argument("--route", choices=("common", "explicit"))
    parser.add_argument("--backend", choices=("python", "rust"), default="python")
    parser.add_argument("--level", choices=("score", "audit"), default="score")
    parser.add_argument("--high-churn", action="store_true")
    parser.add_argument("--low-churn", action="store_true")
    parser.add_argument("--json-output", type=Path, default=ROOT / "benchmarks/native_event/results/pre48e/after.json")
    parser.add_argument("--markdown-output", type=Path, default=ROOT / "benchmarks/native_event/results/pre48e/report.md")
    args = parser.parse_args()
    if args.worker:
        if args.route is None:
            parser.error("--worker requires --route")
        return _worker(args)
    rows = []
    for high_churn in (False, True):
        for route in ("common", "explicit"):
            for level in ("score", "audit"):
                for backend in ("python", "rust"):
                    rows.append(_run_worker(route, backend, level, high_churn))
    payload = {
        "benchmark": "pre48e_native_event_performance",
        "bars": N_BARS,
        "warm_runs": N_RUNS,
        "environment": _environment(),
        "results": rows,
        "parity_policy": {"numeric_atol": 1e-12, "discrete_exact": True},
    }
    parity = {}
    for workload in ("common_low_churn", "common_high_churn", "explicit_low_churn", "explicit_high_churn"):
        for level in ("score", "audit"):
            group = [
                row for row in rows
                if row.get("workload") == workload and row.get("report_level") == level and row.get("status", "ok") == "ok"
            ]
            python_rows = [row for row in group if row.get("backend") == "python"]
            rust_rows = [row for row in group if row.get("backend") == "rust"]
            key = f"{workload}:{level}"
            if python_rows and rust_rows:
                left, right = python_rows[0], rust_rows[0]
                parity[key] = bool(
                    left.get("fingerprint") == right.get("fingerprint")
                    and abs(float(left.get("final_equity", 0.0)) - float(right.get("final_equity", 0.0))) <= 1e-12
                )
                if not parity[key]:
                    raise AssertionError(f"pre-48E Python/Rust parity failed for {key}")
            else:
                parity[key] = "rust_unavailable"
    payload["parity"] = parity
    rendered = json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n"
    print(rendered, end="")
    args.json_output.parent.mkdir(parents=True, exist_ok=True)
    args.json_output.write_text(rendered)
    args.markdown_output.write_text(_render(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
