"""Phase 53B native strategy IR, batch/WFO, and memory evidence.

This benchmark intentionally keeps the comparison narrow and honest:

* E3 compares the Python reference command tape plus canonical Python event
  oracle with one-call Rust native-IR score/audit execution.
* E6 compares one PyO3 call per scenario with a one-call shared-market Rust
  batch. It does not claim to benchmark arbitrary Python strategy callbacks.

Portfolio/package preflight and typed-tape lifecycle parity are covered by the
contract tests. They are not presented here as generic end-to-end portfolio or
arbitrage performance claims.
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
    NativeStrategyIR,
    NativeStrategyKind,
    NativeStrategyParameters,
    RustNativeIRRunner,
)


ROOT = Path(__file__).resolve().parents[2]


def _rss_bytes() -> int:
    """Return current RSS on Linux, with a portable high-water fallback."""

    status = Path("/proc/self/status")
    if status.exists():
        for line in status.read_text(encoding="utf-8").splitlines():
            if line.startswith("VmRSS:"):
                return int(line.split()[1]) * 1024
    return int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss) * 1024


def _fixture(bars: int) -> tuple[pd.DataFrame, NativeEventBackend, RustNativeIRRunner]:
    index = pd.date_range("2024-01-01", periods=bars, freq="1h", tz="UTC")
    phase = np.arange(bars, dtype=np.float64)
    close = 100.0 + phase * 0.005 + np.sin(phase / 11.0)
    open_ = close + 0.02 * np.cos(phase / 7.0)
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
    backend = NativeEventBackend(
        NativeEventConfig(
            account=AccountConfig(initial_capital=20_000.0, leverage=5.0),
            execution=ExecutionConfig(slippage_bps=2.0),
            fee_rate=0.0002,
            use_funding=False,
        )
    )
    full_runner = backend.prepare_rust_batched_runner(
        index,
        closes={"BTC": frame["close"]},
        highs={"BTC": frame["high"]},
        lows={"BTC": frame["low"]},
        symbols=["BTC"],
        contract_size=1.0,
    )
    program = NativeStrategyIR(
        NativeStrategyKind.GRID_LEVEL,
        "BTC",
        parameters=NativeStrategyParameters(quantity=0.25),
    )
    return frame, backend, RustNativeIRRunner(full_runner, program)


def _signal(bars: int, offset: int = 0) -> np.ndarray:
    phase = np.arange(bars, dtype=np.int64) + int(offset)
    return np.where((phase // 23) % 4 == 0, 2.0, np.where((phase // 23) % 4 == 1, 1.0, np.where((phase // 23) % 4 == 2, -1.0, -2.0))).astype(np.float64)


def _timed(function, repeats: int):
    samples: list[float] = []
    result = None
    for _ in range(repeats):
        started = perf_counter()
        result = function()
        samples.append(perf_counter() - started)
    return float(median(samples)), result


def _e3(frame: pd.DataFrame, backend: NativeEventBackend, runner: RustNativeIRRunner, repeats: int) -> dict:
    signal = _signal(len(frame))
    reference = runner.program.reference_tape(frame.index, signal, frame["close"])
    compiled = backend.compile_order_commands(frame.index, reference.commands, symbols=["BTC"])
    market = backend.prepare_market_arrays(
        frame.index,
        closes={"BTC": frame["close"]},
        highs={"BTC": frame["high"]},
        lows={"BTC": frame["low"]},
        symbols=["BTC"],
    )

    def python_oracle():
        return backend.run_order_commands(
            frame.index,
            reference.commands,
            closes={"BTC": frame["close"]},
            highs={"BTC": frame["high"]},
            lows={"BTC": frame["low"]},
            symbols=["BTC"],
            contract_size=1.0,
            market_arrays=market,
            compiled_commands=compiled,
            report_level="minimal",
            _force_python_backend=True,
        )

    python_oracle()
    runner.run_score(signal)
    runner.run_audit(signal)
    python_seconds, python_result = _timed(python_oracle, repeats)
    rust_seconds, rust_result = _timed(lambda: runner.run_score(signal), repeats)
    audit = runner.run_audit(signal)
    payload = audit.payload
    np.testing.assert_allclose(
        payload["equity"], python_result.equity.to_numpy(dtype=np.float64), rtol=0.0, atol=1e-12
    )
    np.testing.assert_allclose(
        payload["positions"][:, 0],
        python_result.positions["Position_BTC"].to_numpy(dtype=np.float64),
        rtol=0.0,
        atol=1e-12,
    )
    return {
        "workload": "E3_NATIVE_STRATEGY_IR",
        "bars": len(frame),
        "commands": int(payload["strategy_ir_command_count"]),
        "strategy_kind": runner.program.kind.value,
        "fingerprint": runner.fingerprint,
        "python_reference_oracle": {
            "median_seconds": python_seconds,
            "bars_per_second": len(frame) / python_seconds,
            "pyo3_calls_per_run": 0,
            "python_callbacks_per_run": 0,
        },
        "rust_native_ir_score": {
            "median_seconds": rust_seconds,
            "bars_per_second": len(frame) / rust_seconds,
            "pyo3_calls_per_run": 1,
            "python_callbacks_per_run": 0,
            "boundary_calls": int(rust_result.payload["boundary_calls"]),
        },
        "parity": {
            "python_reference_vs_rust_audit": True,
            "final_equity": float(rust_result.final_equity),
            "fill_count": int(payload["fill_count"]),
        },
        "speedup_python_reference_over_rust": python_seconds / rust_seconds,
    }


def _e6(runner: RustNativeIRRunner, bars: int, scenarios: int, repeats: int) -> dict:
    signals = np.vstack([_signal(bars, offset=row * 5) for row in range(scenarios)])
    parameters = np.zeros((scenarios, 4), dtype=np.float64)
    parameters[:, 0] = 0.10 + 0.01 * (np.arange(scenarios) % 8)
    rss_before = _rss_bytes()
    baseline_seconds, baseline_rows = _timed(
        lambda: np.asarray(
            [
                runner.run_score(signals[row], parameters=parameters[row]).final_equity
                for row in range(scenarios)
            ],
            dtype=np.float64,
        ),
        repeats,
    )
    rows: dict[str, dict] = {
        "single_call_per_scenario": {
            "median_seconds": baseline_seconds,
            "scenario_runs_per_second": scenarios / baseline_seconds,
            "simulated_bars_per_second": scenarios * bars / baseline_seconds,
            "pyo3_calls_per_batch": scenarios,
        }
    }
    for workers in (1, 2, 4, 8):
        runner.run_batch_score(signals, parameter_matrix=parameters, workers=workers, chunk_size=16)
        elapsed, result = _timed(
            lambda: runner.run_batch_score(
                signals,
                parameter_matrix=parameters,
                workers=workers,
                chunk_size=16,
            ),
            repeats,
        )
        np.testing.assert_allclose(result.final_equity, baseline_rows, rtol=0.0, atol=1e-12)
        rows[f"batch_workers_{workers}"] = {
            "median_seconds": elapsed,
            "scenario_runs_per_second": scenarios / elapsed,
            "simulated_bars_per_second": scenarios * bars / elapsed,
            "pyo3_calls_per_batch": int(result.metadata["boundary_calls"]),
            "requested_workers": int(result.metadata["requested_workers"]),
            "actual_workers": int(result.metadata["actual_workers"]),
            "shared_market_copies_per_scenario": int(
                result.metadata["shared_market_copies_per_scenario"]
            ),
            "audit_materialized": bool(result.metadata["audit_materialized"]),
            "speedup_vs_single_boundary": baseline_seconds / elapsed,
        }
    return {
        "workload": "E6_BATCH_OPTIMIZER_WFO",
        "bars": bars,
        "scenarios": scenarios,
        "parameter_width": 4,
        "rows": rows,
        "rss_delta_bytes": max(0, _rss_bytes() - rss_before),
        "parity": {
            "single_vs_batch_exact": True,
            "worker_counts_exact": True,
            "selected_audit_is_deferred": True,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bars", type=int, default=2_000)
    parser.add_argument("--scenarios", type=int, default=64)
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "benchmarks/native_event/results/phase53b/native_drivers.json",
    )
    args = parser.parse_args()
    if args.bars < 3 or args.scenarios < 1 or args.repeats < 3:
        parser.error("requires bars >= 3, scenarios >= 1, and repeats >= 3")
    frame, backend, runner = _fixture(args.bars)
    payload = {
        "schema_version": 1,
        "phase": "53B",
        "method": "warm prepared market; median wall time; direct native IR only",
        "promotion_scope": "opt-in experimental native strategy IR and batch driver",
        "e3": _e3(frame, backend, runner, args.repeats),
        "e6": _e6(runner, args.bars, args.scenarios, args.repeats),
        "non_claims": [
            "No arbitrary Python callback speed claim.",
            "No full generic portfolio/arbitrage endpoint promotion claim.",
            "Portfolio/package accounting parity is a separate contract-test artifact.",
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
