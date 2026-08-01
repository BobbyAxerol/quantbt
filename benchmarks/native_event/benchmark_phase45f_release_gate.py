"""Process-isolated Phase45F speed/RSS certification gate.

Each backend is executed in a fresh child process.  This prevents the Rust
prepared market and the Python prepared market from coexisting in one RSS
sample and records the gate result without changing backend rollout policy.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import resource
import subprocess
import sys
import time

os.environ.setdefault("MPLCONFIGDIR", "/tmp")

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from quantbt import (  # noqa: E402
    AccountConfig,
    ExecutionConfig,
    NativeEventBackend,
    NativeEventConfig,
    OrderCommand,
    OrderSide,
    OrderType,
)


def _rss_mb() -> float:
    status_path = Path("/proc/self/status")
    if status_path.exists():
        for line in status_path.read_text(encoding="utf-8").splitlines():
            if line.startswith("VmRSS:"):
                return float(line.split()[1]) / 1024.0
    return float(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss) / 1024.0


def _fixture(n_bars: int, scenario: str):
    index = pd.date_range("2020-01-01", periods=n_bars, freq="1h", tz="UTC")
    close = pd.Series(100.0 + np.sin(np.arange(n_bars, dtype=np.float64) / 17.0), index=index)
    frame = pd.DataFrame(
        {"open": close, "high": close + 1.0, "low": close - 1.0, "close": close},
        index=index,
    )
    backend = NativeEventBackend(
        NativeEventConfig(
            account=AccountConfig(initial_capital=20_000.0, leverage=5.0, maintenance_ratio=0.0),
            execution=ExecutionConfig(slippage_bps=2.0),
            fee_rate=0.0002,
            use_funding=False,
        )
    )
    closes = {"BTC": frame["close"]}
    highs = {"BTC": frame["high"]}
    lows = {"BTC": frame["low"]}
    market = backend.prepare_market_arrays(index, closes, highs, lows, symbols=["BTC"])
    commands: list[OrderCommand] = []
    if scenario == "low_churn":
        entries = range(1, n_bars - 1_000, max(1, n_bars // 20))
    elif scenario == "high_churn":
        entries = range(1, n_bars - 2, max(1, n_bars // 1_500))
    else:
        raise ValueError(f"unsupported scenario={scenario!r}")
    for cycle, entry in enumerate(entries):
        exit_bar = min(entry + 1, n_bars - 1) if scenario == "high_churn" else min(entry + 1_000, n_bars - 1)
        commands.extend(
            (
                OrderCommand(
                    timestamp=index[entry],
                    symbol="BTC",
                    side=OrderSide.BUY,
                    order_type=OrderType.MARKET,
                    qty=1.0,
                    order_id=f"entry-{cycle}",
                ),
                OrderCommand(
                    timestamp=index[exit_bar],
                    symbol="BTC",
                    side=OrderSide.SELL,
                    order_type=OrderType.MARKET,
                    qty=1.0,
                    reduce_only=True,
                    order_id=f"exit-{cycle}",
                ),
            )
        )
    compiled = backend.compile_order_commands(index, commands, symbols=["BTC"])
    runner = backend.prepare_rust_batched_runner(index, closes, highs, lows, symbols=["BTC"])
    return backend, index, closes, highs, lows, market, commands, compiled, runner


def _run_child(backend_name: str, scenario: str, n_bars: int, repetitions: int) -> dict[str, object]:
    backend, index, closes, highs, lows, market, commands, compiled, runner = _fixture(n_bars, scenario)
    if backend_name == "rust":
        runner.run_tape_score(compiled)
        fn = lambda: runner.run_tape_score(compiled)
    elif backend_name == "python":
        backend.run_order_commands(
            index,
            commands,
            closes,
            highs,
            lows,
            symbols=["BTC"],
            market_arrays=market,
            compiled_commands=compiled,
            report_level="minimal",
        )

        def fn():
            return backend.run_order_commands(
                index,
                commands,
                closes,
                highs,
                lows,
                symbols=["BTC"],
                market_arrays=market,
                compiled_commands=compiled,
                report_level="minimal",
            )

    else:
        raise ValueError(f"unsupported backend={backend_name!r}")

    samples: list[float] = []
    rss_samples: list[float] = []
    last = None
    for _ in range(repetitions):
        started = time.perf_counter()
        last = fn()
        samples.append(time.perf_counter() - started)
        rss_samples.append(_rss_mb())
    if backend_name == "rust":
        final_equity = float(last.final_equity)
        fill_count = int(last.fill_count)
    else:
        final_equity = float(last.equity.iloc[-1])
        fill_count = int(last.metadata["lifecycle_counters"]["fill_count"])
    return {
        "backend": backend_name,
        "scenario": scenario,
        "bars": n_bars,
        "commands": len(commands),
        "repetitions": repetitions,
        "seconds": [float(value) for value in samples],
        "median_seconds": float(np.median(samples)),
        "rss_samples_mb": rss_samples,
        "post_run_rss_mb": float(rss_samples[-1]),
        "peak_rss_mb": float(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss) / 1024.0,
        "final_equity": final_equity,
        "fill_count": fill_count,
    }


def _child_main(args: argparse.Namespace) -> None:
    result = _run_child(args.backend, args.scenario, args.bars, args.repetitions)
    print(json.dumps(result, sort_keys=True))


def _run_isolated(backend: str, scenario: str, bars: int, repetitions: int) -> dict[str, object]:
    command = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--child",
        "--backend",
        backend,
        "--scenario",
        scenario,
        "--bars",
        str(bars),
        "--repetitions",
        str(repetitions),
    ]
    env = dict(os.environ)
    env.setdefault("MPLCONFIGDIR", "/tmp")
    completed = subprocess.run(command, cwd=ROOT, env=env, check=True, capture_output=True, text=True)
    return json.loads(completed.stdout.strip().splitlines()[-1])


def _parent_main(args: argparse.Namespace) -> None:
    results = {
        scenario: {
            backend: _run_isolated(backend, scenario, args.bars, args.repetitions)
            for backend in ("python", "rust")
        }
        for scenario in ("low_churn", "high_churn")
    }
    comparisons = {}
    for scenario, values in results.items():
        python_result = values["python"]
        rust_result = values["rust"]
        speedup = python_result["median_seconds"] / rust_result["median_seconds"]
        rss_reduction = (python_result["peak_rss_mb"] - rust_result["peak_rss_mb"]) / python_result["peak_rss_mb"]
        parity = (
            abs(python_result["final_equity"] - rust_result["final_equity"]) <= 1e-12
            and python_result["fill_count"] == rust_result["fill_count"]
        )
        comparisons[scenario] = {
            "speedup_python_over_rust": float(speedup),
            "peak_rss_reduction": float(rss_reduction),
            "parity": bool(parity),
            "high_churn_speed_gate": bool(speedup >= 2.0) if scenario == "high_churn" else None,
        }
    plateau = all(
        max(values[backend]["rss_samples_mb"][-3:]) - min(values[backend]["rss_samples_mb"][-3:]) <= 16.0
        for values in results.values()
        for backend in ("python", "rust")
    )
    all_parity = all(value["parity"] for value in comparisons.values())
    median_speed = float(np.median([value["speedup_python_over_rust"] for value in comparisons.values()]))
    min_rss_reduction = float(min(value["peak_rss_reduction"] for value in comparisons.values()))
    release_ready = bool(
        all_parity
        and median_speed >= 1.5
        and comparisons["high_churn"]["high_churn_speed_gate"]
        and min_rss_reduction >= 0.40
        and plateau
    )
    payload = {
        "phase": "45F",
        "bars": args.bars,
        "repetitions": args.repetitions,
        "process_isolated": True,
        "results": results,
        "comparisons": comparisons,
        "gate": {
            "parity": all_parity,
            "median_end_to_end_speedup": median_speed,
            "minimum_peak_rss_reduction": min_rss_reduction,
            "repeated_run_rss_plateau": plateau,
            "release_ready": release_ready,
        },
        "policy": "Rust remains explicit experimental and auto remains Python when release_ready is false.",
    }
    output_path = Path(args.output) if args.output else Path(__file__).with_name("phase45f_release_gate.json")
    output_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--child", action="store_true")
    parser.add_argument("--backend", choices=("python", "rust"), default="python")
    parser.add_argument("--scenario", choices=("low_churn", "high_churn"), default="low_churn")
    parser.add_argument("--bars", type=int, default=100_000)
    parser.add_argument("--repetitions", type=int, default=5)
    parser.add_argument("--output")
    args = parser.parse_args()
    if args.repetitions < 5:
        parser.error("Phase45F requires at least five measured repetitions")
    if args.child:
        _child_main(args)
    else:
        _parent_main(args)


if __name__ == "__main__":
    main()
