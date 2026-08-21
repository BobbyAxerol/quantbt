"""Phase 53A E0 static-tape profile benchmark.

This deliberately measures one prepared static command tape through the three
Rust retention profiles. It is a kernel/ownership benchmark, not a claim about
Python callbacks, strategy IR, portfolio, packages, or WFO batch performance.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import resource
from statistics import median
from time import perf_counter

import numpy as np
import pandas as pd

from quantbt import (
    AccountConfig,
    ExecutionConfig,
    NativeEventBackend,
    NativeEventConfig,
    OrderCommand,
    OrderSide,
    OrderType,
    TimeInForce,
)
from quantbt.backends._native_event_rust import RustFullRunner


ROOT = Path(__file__).resolve().parents[2]


def _rss_bytes() -> int:
    status = Path("/proc/self/status")
    if status.exists():
        for line in status.read_text(encoding="utf-8").splitlines():
            if line.startswith("VmRSS:"):
                return int(line.split()[1]) * 1024
    return int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss) * 1024


def _fixture(bars: int, churn: str):
    index = pd.date_range("2024-01-01", periods=bars, freq="1h", tz="UTC")
    phase = np.arange(bars, dtype=np.float64)
    close = 100.0 + phase * 0.01 + np.sin(phase / 17.0)
    open_ = close + 0.03 * np.cos(phase / 11.0)
    frame = pd.DataFrame(
        {
            "open": open_,
            "high": np.maximum(open_, close) + 0.5,
            "low": np.minimum(open_, close) - 0.5,
            "close": close,
            "volume": 1_000.0,
        },
        index=index,
    )
    if churn == "low":
        entry_bars = range(1, bars - 1, max(2, bars // 20))
    elif churn == "high":
        entry_bars = range(1, bars)
    else:
        raise ValueError(f"unsupported churn={churn!r}")
    commands = tuple(
        OrderCommand(
            timestamp=index[bar],
            symbol="BTC",
            side=OrderSide.BUY if sequence % 2 == 0 else OrderSide.SELL,
            order_type=OrderType.MARKET,
            qty=0.1,
            tif=TimeInForce.GTC,
            order_id=f"{churn}-{sequence}",
        )
        for sequence, bar in enumerate(entry_bars)
    )
    backend = NativeEventBackend(
        NativeEventConfig(
            account=AccountConfig(initial_capital=20_000.0, leverage=5.0),
            execution=ExecutionConfig(slippage_bps=2.0),
            fee_rate=0.0002,
            use_funding=False,
            native_backend="rust",
        )
    )
    closes = {"BTC": frame["close"]}
    highs = {"BTC": frame["high"]}
    lows = {"BTC": frame["low"]}
    market = backend.prepare_market_arrays(index, closes, highs, lows, symbols=["BTC"])
    compiled = backend.compile_order_commands(index, commands, symbols=["BTC"])
    runner = RustFullRunner(
        idx=index,
        symbols=["BTC"],
        market_arrays=market,
        contract_sizes=np.array([1.0], dtype=np.float64),
        leverages=np.array([5.0], dtype=np.float64),
        fee_rates=np.array([0.0002], dtype=np.float64),
        initial_capital=20_000.0,
        maintenance_ratio=0.005,
        slippage=0.0002,
        use_funding=False,
        opens_arr=frame["open"].to_numpy(dtype=np.float64).reshape(-1, 1),
        volumes_arr=frame["volume"].to_numpy(dtype=np.float64).reshape(-1, 1),
    )
    return compiled, runner, len(commands)


def _result_bytes(result: object, profile: str) -> int:
    if profile == "score":
        return 0
    if profile == "compact":
        return sum(
            int(np.asarray(result[key]).nbytes)
            for key in ("equity", "positions", "fees", "turnover", "funding", "initial_margin", "maintenance_margin")
        )
    return sum(
        int(np.asarray(getattr(result, key)).nbytes)
        for key in (
            "equity", "positions", "fees", "turnover", "funding", "initial_margin", "maintenance_margin",
            "fill_bar", "fill_order_id", "fill_symbol", "fill_side", "fill_qty", "fill_price", "fill_fee",
            "event_bar", "event_kind", "event_status", "event_order_id", "event_target_id", "event_symbol",
        )
    )


def _summary(result: object, profile: str) -> dict[str, float | int]:
    if profile == "audit":
        return {
            "final_equity": float(result.final_equity),
            "fill_count": int(result.fill_count),
            "event_count": int(result.event_count),
        }
    return {
        "final_equity": float(result["final_equity"]),
        "fill_count": int(result["fill_count"]),
        "event_count": int(result["event_count"]),
    }


def _measure_profile(compiled, runner: RustFullRunner, profile: str, repeats: int) -> tuple[dict, object]:
    function = {
        "score": runner.run_tape_score,
        "compact": runner.run_tape_compact,
        "audit": runner.run_tape_audit,
    }[profile]
    function(compiled)  # warm-up and compiled tape/cache preparation.
    elapsed: list[float] = []
    output = None
    rss_before = _rss_bytes()
    for _ in range(repeats):
        started = perf_counter()
        output = function(compiled)
        elapsed.append(perf_counter() - started)
    assert output is not None
    summary = _summary(output, profile)
    return (
        {
            "profile": profile,
            "median_seconds": float(median(elapsed)),
            "pyo3_calls_per_run": 1,
            "python_callbacks_per_run": 0,
            "retained_output_bytes": _result_bytes(output, profile),
            "rss_delta_bytes": max(0, _rss_bytes() - rss_before),
            **summary,
        },
        output,
    )


def _measure_workload(bars: int, churn: str, repeats: int) -> dict:
    compiled, runner, commands = _fixture(bars, churn)
    rows: dict[str, dict] = {}
    results: dict[str, object] = {}
    for profile in ("score", "compact", "audit"):
        rows[profile], results[profile] = _measure_profile(compiled, runner, profile, repeats)
        rows[profile]["bars_per_second"] = bars / rows[profile]["median_seconds"]
    score = rows["score"]
    compact = rows["compact"]
    audit = rows["audit"]
    np.testing.assert_allclose(compact["final_equity"], score["final_equity"], rtol=0.0, atol=1e-12)
    np.testing.assert_allclose(audit["final_equity"], score["final_equity"], rtol=0.0, atol=1e-12)
    assert compact["fill_count"] == audit["fill_count"] == score["fill_count"]
    assert compact["event_count"] == audit["event_count"] == score["event_count"]
    np.testing.assert_allclose(results["compact"]["equity"], results["audit"].equity, rtol=0.0, atol=1e-12)
    np.testing.assert_allclose(results["compact"]["positions"], results["audit"].positions, rtol=0.0, atol=1e-12)
    return {
        "workload": "E0_STATIC_EXPLICIT_COMMAND_TAPE",
        "bars": bars,
        "symbols": 1,
        "commands": commands,
        "churn": churn,
        "profiles": rows,
        "parity": {
            "score_compact_audit_accounting": True,
            "compact_audit_paths": True,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bars", type=int, default=2_000)
    parser.add_argument("--repeats", type=int, default=7)
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "benchmarks/native_event/results/phase53a/e0_profiles.json",
    )
    args = parser.parse_args()
    if args.bars < 3 or args.repeats < 3:
        parser.error("Phase 53A E0 requires at least 3 bars and 3 measured repeats")
    payload = {
        "schema_version": 1,
        "phase": "53A",
        "method": "warm prepared static tape; one PyO3 call per run; median wall time",
        "profiles": ["score", "compact", "audit"],
        "results": [_measure_workload(args.bars, churn, args.repeats) for churn in ("low", "high")],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
