#!/usr/bin/env python3
"""Benchmark the Phase 48C facade without mixing it into the grid baseline.

The common case measures the same 2,000-bar single-symbol tape through the
legacy native-event constructor and the new stable facade. The reactive Grid
case is reported separately because indicator preparation and callback state
are part of that workload. Every case runs in a fresh process so RSS and
backend imports are not shared between measurements.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import resource
import subprocess
import sys
import time
from typing import Any

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_GRID_DIR = Path("/root/bobby/pool_alpha/alphas_storage/TA")
MARKER = "PHASE48C_RESULT="

for candidate in (ROOT, ROOT / "src"):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))


def _bars(n: int = 2_000) -> pd.DataFrame:
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


class PeriodicStrategy:
    """Small deterministic reactive strategy for the common 2,000-bar case."""

    def __init__(self, every: int = 37, hold: int = 11) -> None:
        self.every = int(every)
        self.hold = int(hold)

    def initialize(self, context):
        return ()

    def on_bar_close(self, context):
        from quantbt import OrderCommand, OrderSide, OrderType, TimeInForce

        bar = int(context.bar_index)
        if bar % self.every == 0:
            return [
                OrderCommand(
                    timestamp=context.timestamp,
                    symbol="BTC",
                    side=OrderSide.BUY,
                    order_type=OrderType.MARKET,
                    qty=0.25,
                    tif=TimeInForce.IOC,
                    order_id=f"entry-{bar}",
                )
            ]
        if bar > 0 and bar % self.every == self.hold:
            return [
                OrderCommand(
                    timestamp=context.timestamp,
                    symbol="BTC",
                    side=OrderSide.SELL,
                    order_type=OrderType.MARKET,
                    qty=0.25,
                    tif=TimeInForce.IOC,
                    reduce_only=True,
                    order_id=f"exit-{bar}",
                )
            ]
        return ()

    def finalize(self, context):
        return ()


def _load_grid_module(module_dir: Path):
    path = module_dir / "dynamic_grid_quantbt_native_event.py"
    if not path.exists():
        raise FileNotFoundError(f"Grid fixture not found: {path}")
    spec = importlib.util.spec_from_file_location("phase48c_grid_fixture", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import Grid fixture: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _grid_data(n: int = 2_000) -> pd.DataFrame:
    index = pd.date_range("2023-01-01", periods=n, freq="h", tz="UTC")
    x = np.arange(n, dtype=np.float64)
    close = 100.0 + 5.0 * np.sin(x / 11.0) + 0.01 * x + 1.5 * np.sin(x / 47.0)
    open_ = close + 0.2 * np.sin(x / 3.0)
    return pd.DataFrame(
        {
            "open": open_,
            "high": np.maximum(open_, close) + 1.5,
            "low": np.minimum(open_, close) - 1.5,
            "close": close,
            "volume": np.full(n, 1_000.0),
        },
        index=index,
    )


def _grid_params() -> dict[str, Any]:
    return {
        "grid_mode": "long_only",
        "ma_type": "EMA",
        "ma_len": 8,
        "ema_len_short": 3,
        "logic": "ATR",
        "band_mult": 0.25,
        "zone_smoothing_len": 2,
        "warmup_bars": 12,
        "pyramiding": 3,
        "neutral_position_mode": "hold",
        "one_entry_fill_per_bar": True,
        "one_exit_fill_per_bar": True,
        "campaign_id": "PHASE48C_BENCH",
    }


def _grid_execution(grid, backend: str = "python"):
    return grid.GridExecutionConfig(
        symbol="ETHUSDT",
        initial_capital=20_000.0,
        cash_per_entry=1_000.0,
        leverage=5.0,
        maintenance_ratio=0.005,
        contract_size=1.0,
        fee_rate=0.0005,
        slippage_bps=2.0,
        use_funding=True,
        funding_rate=0.0001,
        native_backend=backend,
        reactive_execution_mode="audit",
        reactive_kernel_mode="replay_certified",
        report_level="audit",
        audit_sink="memory",
    )


def _digest_array(digest, name: str, values) -> None:
    array = np.ascontiguousarray(np.asarray(values, dtype=np.float64))
    digest.update(name.encode("ascii"))
    digest.update(repr(array.shape).encode("ascii"))
    digest.update(array.tobytes())


def _fingerprint(result) -> str:
    digest = hashlib.sha256()
    _digest_array(digest, "equity", result.equity)
    _digest_array(digest, "positions", result.positions)
    _digest_array(digest, "fees", result.fees)
    _digest_array(digest, "funding", result.funding)
    _digest_array(digest, "margin", result.margin)
    for fill in result.fills:
        digest.update(
            repr(
                (
                    int(pd.Timestamp(fill.timestamp).value),
                    str(fill.symbol),
                    getattr(fill.side, "value", str(fill.side)),
                    float(fill.qty),
                    float(fill.price),
                    float(fill.fee),
                    fill.order_id,
                )
            ).encode("utf-8")
        )
    counters = result.metadata.get("lifecycle_counters", {})
    digest.update(json.dumps(counters, sort_keys=True, default=str).encode("utf-8"))
    digest.update(repr(bool(result.liquidated)).encode("ascii"))
    digest.update(repr(int(result.liquidation_bar)).encode("ascii"))
    return digest.hexdigest()


def _peak_rss_mb() -> float:
    # Linux reports KiB for ru_maxrss; macOS reports bytes. The benchmark is
    # run on Linux CI/VPS, but retaining the branch makes the script portable.
    value = float(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    return value / 1024.0 if sys.platform == "linux" else value / (1024.0 * 1024.0)


def _endpoint_kwargs() -> dict[str, Any]:
    return {
        "initial_capital": 20_000.0,
        "leverage": 5.0,
        "maintenance_ratio": 0.005,
        "fee_rate": 0.0005,
        "slippage_bps": 2.0,
        "use_funding": False,
        "symbols": ["BTC"],
    }


def _run_common(case: str, bars: int, runs: int) -> dict[str, Any]:
    from quantbt import QuantBTEndpoint

    if case == "direct":
        endpoint = QuantBTEndpoint.native_event_strategy(
            native_backend="python",
            reactive_execution_mode="fast",
            reactive_kernel_mode="single_pass",
            report_level="minimal",
            audit_sink="none",
            **_endpoint_kwargs(),
        )
    else:
        endpoint = QuantBTEndpoint.event_driven(
            input_mode="strategy",
            profile="research",
            backend="python",
            **_endpoint_kwargs(),
        )

    data = _bars(bars)
    for _ in range(1):
        endpoint.simulate(data=data, strategy=PeriodicStrategy(), symbols=["BTC"])

    times = []
    result = None
    for _ in range(runs):
        start = time.perf_counter()
        result = endpoint.simulate(data=data, strategy=PeriodicStrategy(), symbols=["BTC"])
        times.append(time.perf_counter() - start)

    assert result is not None
    counters = result.metadata.get("lifecycle_counters", {})
    return {
        "route": "native_event_strategy" if case == "direct" else "event_driven_facade",
        "bars": bars,
        "symbols": 1,
        "runs": runs,
        "runtime_median_seconds": float(np.median(times)),
        "runtime_p95_seconds": float(np.percentile(times, 95)),
        "throughput_bars_per_second": float(bars / np.median(times)),
        "peak_rss_mb": _peak_rss_mb(),
        "final_equity": float(result.equity.iloc[-1]),
        "fill_count": int(counters.get("fill_count", len(result.fills))),
        "fingerprint": _fingerprint(result),
    }


def _run_grid(case: str, bars: int, runs: int, grid_dir: Path) -> dict[str, Any]:
    from quantbt import QuantBTEndpoint

    grid = _load_grid_module(grid_dir)
    data = _grid_data(bars)
    params = _grid_params()
    execution = _grid_execution(grid)
    if case == "grid_direct":
        build_endpoint = grid.build_grid_endpoint
    else:
        def build_endpoint(config):
            return QuantBTEndpoint.event_driven(
                input_mode="strategy",
                profile="audit",
                backend="python",
                initial_capital=config.initial_capital,
                leverage=config.leverage,
                maintenance_ratio=config.maintenance_ratio,
                contract_size=config.contract_size,
                fee_rate=config.fee_rate,
                slippage_bps=config.slippage_bps,
                use_funding=config.use_funding,
                funding_rate=config.funding_rate,
                qty_step=config.qty_step,
                lot_size=config.lot_size,
                slot_size=config.slot_size,
                min_qty=config.min_qty,
                min_notional=config.min_notional,
                symbols=[config.symbol],
            )

    for _ in range(1):
        strategy = grid.build_grid_strategy(df=data, params=params, execution=execution)
        build_endpoint(execution).simulate(data=data, strategy=strategy, symbols=[execution.symbol])

    times = []
    result = None
    for _ in range(runs):
        strategy = grid.build_grid_strategy(df=data, params=params, execution=execution)
        endpoint = build_endpoint(execution)
        start = time.perf_counter()
        result = endpoint.simulate(data=data, strategy=strategy, symbols=[execution.symbol])
        times.append(time.perf_counter() - start)

    assert result is not None
    counters = result.metadata.get("lifecycle_counters", {})
    return {
        "route": "grid_native_event_strategy" if case == "grid_direct" else "grid_event_driven_facade",
        "bars": bars,
        "symbols": 1,
        "runs": runs,
        "runtime_median_seconds": float(np.median(times)),
        "runtime_p95_seconds": float(np.percentile(times, 95)),
        "throughput_bars_per_second": float(bars / np.median(times)),
        "peak_rss_mb": _peak_rss_mb(),
        "final_equity": float(result.equity.iloc[-1]),
        "fill_count": int(counters.get("fill_count", len(result.fills))),
        "num_trades": int(result.metadata.get("num_trades") or counters.get("fill_count", len(result.fills))),
        "fingerprint": _fingerprint(result),
    }


def _worker(args) -> int:
    if args.case in {"direct", "facade"}:
        payload = _run_common(args.case, args.bars, args.runs)
    else:
        payload = _run_grid(args.case, args.bars, args.runs, args.grid_module_dir)
    print(MARKER + json.dumps(payload, sort_keys=True))
    return 0


def _run_worker(case: str, args) -> dict[str, Any]:
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join((str(ROOT / "src"), str(ROOT), env.get("PYTHONPATH", "")))
    env.setdefault("MPLCONFIGDIR", "/tmp")
    command = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--worker",
        "--case",
        case,
        "--bars",
        str(args.bars),
        "--runs",
        str(args.runs),
        "--grid-module-dir",
        str(args.grid_module_dir),
    ]
    completed = subprocess.run(command, check=True, capture_output=True, text=True, env=env)
    for line in reversed(completed.stdout.splitlines()):
        if line.startswith(MARKER):
            return json.loads(line[len(MARKER) :])
    raise RuntimeError(f"worker did not emit {MARKER}: {completed.stdout[-1000:]}")


def _render_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Phase 48C Event-Driven Facade Benchmark",
        "",
        f"Workload: **{payload['bars']:,} bars**, one symbol, fresh process per route.",
        "The common table is the release baseline; the Grid table is a separate reactive workload.",
        "",
        "## Common 2,000-Bar Baseline",
        "",
        "| Route | Median s | P95 s | Bars/s | Peak RSS MB | Final Equity | Fills |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for row in payload["common"]["routes"]:
        lines.append(
            f"| `{row['route']}` | {row['runtime_median_seconds']:.6f} | "
            f"{row['runtime_p95_seconds']:.6f} | {row['throughput_bars_per_second']:,.0f} | "
            f"{row['peak_rss_mb']:.1f} | {row['final_equity']:,.6f} | {row['fill_count']} |"
        )
    lines.extend(
        [
            "",
            f"Accounting parity: **{'PASS' if payload['common']['parity'] else 'FAIL'}**.",
            f"Facade runtime overhead versus direct constructor: **{payload['common']['facade_overhead_pct']:+.2f}%**.",
            "The facade is a resolver/delegator; it is not expected to speed up the accounting kernel.",
            "",
            "## Reactive Grid 2,000-Bar Workload",
            "",
            "| Route | Median s | P95 s | Bars/s | Peak RSS MB | Final Equity | Fills | Trades |",
            "|---|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for row in payload["grid"]["routes"]:
        lines.append(
            f"| `{row['route']}` | {row['runtime_median_seconds']:.6f} | "
            f"{row['runtime_p95_seconds']:.6f} | {row['throughput_bars_per_second']:,.0f} | "
            f"{row['peak_rss_mb']:.1f} | {row['final_equity']:,.6f} | {row['fill_count']} | {row['num_trades']} |"
        )
    lines.extend(
        [
            "",
            f"Grid accounting parity: **{'PASS' if payload['grid']['parity'] else 'FAIL'}**.",
            "Grid runtime includes external indicator preparation and the reactive callback; it is intentionally not merged into the common baseline.",
            "",
            "## Interpretation",
            "",
            "- The new facade changes endpoint declaration and profile resolution only.",
            "- Equal fingerprints, equity, fees, funding, positions, margin, and fill counts are the domain gate.",
            "- `backend=auto` remains governed by the package release policy; this benchmark explicitly uses Python.",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker", action="store_true")
    parser.add_argument("--case", choices=("direct", "facade", "grid_direct", "grid_facade"))
    parser.add_argument("--bars", type=int, default=2_000)
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--grid-module-dir", type=Path, default=DEFAULT_GRID_DIR)
    parser.add_argument("--json-output", type=Path, default=None)
    parser.add_argument("--markdown-output", type=Path, default=None)
    args = parser.parse_args()
    if args.bars != 2_000:
        parser.error("Phase 48C release baseline must use exactly 2,000 bars")
    if args.runs <= 0:
        parser.error("--runs must be > 0")
    if args.worker:
        if args.case is None:
            parser.error("--worker requires --case")
        return _worker(args)

    common_routes = [_run_worker(case, args) for case in ("direct", "facade")]
    grid_routes = [_run_worker(case, args) for case in ("grid_direct", "grid_facade")]
    common_direct, common_facade = common_routes
    grid_direct, grid_facade = grid_routes
    common_parity = common_direct["fingerprint"] == common_facade["fingerprint"]
    grid_parity = grid_direct["fingerprint"] == grid_facade["fingerprint"]
    if not common_parity or not grid_parity:
        raise AssertionError("Phase 48C facade fingerprint parity failed")

    payload = {
        "benchmark": "phase48c_event_driven_facade",
        "bars": args.bars,
        "runs": args.runs,
        "common": {
            "routes": common_routes,
            "parity": common_parity,
            "facade_overhead_pct": (common_facade["runtime_median_seconds"] / common_direct["runtime_median_seconds"] - 1.0) * 100.0,
        },
        "grid": {
            "routes": grid_routes,
            "parity": grid_parity,
            "facade_overhead_pct": (grid_facade["runtime_median_seconds"] / grid_direct["runtime_median_seconds"] - 1.0) * 100.0,
        },
        "policy": {
            "common_baseline_bars": 2_000,
            "grid_reported_separately": True,
            "fresh_process_per_route": True,
            "domain_parity_required": True,
        },
    }
    rendered = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    print(rendered, end="")
    if args.json_output is not None:
        args.json_output.parent.mkdir(parents=True, exist_ok=True)
        args.json_output.write_text(rendered)
    if args.markdown_output is not None:
        args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
        args.markdown_output.write_text(_render_markdown(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
