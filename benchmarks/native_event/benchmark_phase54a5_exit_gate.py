"""Phase 54A.5.6 reproducible native execution exit-gate evidence.

This is deliberately a workload matrix, not a marketing aggregate.  It
measures only the native boundaries that actually execute today (E0, E3, E6)
and records E1/E2/E4/E5 as non-promotion scope.  Every measured row performs a
same-process parity assertion before timing and records engine/adaptation time
separately.
"""

from __future__ import annotations

import argparse
from hashlib import sha256
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
    OrderCommand,
    OrderSide,
    OrderType,
    RustNativeIRRunner,
)
from quantbt.backends._native_event_rust import RustFullRunner
from quantbt.preparation import CachePolicy, NativeExecutionPreparationCache


ROOT = Path(__file__).resolve().parents[2]
PHASE = "54A.5.6"
EVENT_CONTRACT_CODE = 3  # event_lifecycle_v3_next_open


def _rss_bytes() -> int:
    """Return current Linux RSS, using max RSS only when /proc is unavailable."""

    status = Path("/proc/self/status")
    if status.exists():
        for line in status.read_text(encoding="utf-8").splitlines():
            if line.startswith("VmRSS:"):
                return int(line.split()[1]) * 1024
    return int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss) * 1024


def _peak_rss_bytes() -> int:
    return int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss) * 1024


def _fingerprint(*values: object) -> str:
    digest = sha256()
    for value in values:
        if isinstance(value, np.ndarray):
            array = np.ascontiguousarray(value)
            digest.update(str(array.dtype).encode("ascii"))
            digest.update(repr(array.shape).encode("ascii"))
            digest.update(array.tobytes())
        else:
            digest.update(repr(value).encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


def _measure(function, adapt, repeats: int) -> tuple[dict[str, float | int], object]:
    """Measure warm engine work and explicit cold adaptation independently."""

    function()
    engine_samples: list[float] = []
    adaptation_samples: list[float] = []
    rss_before = _rss_bytes()
    result = None
    for _ in range(repeats):
        started = perf_counter()
        result = function()
        engine_samples.append(perf_counter() - started)
        adaptation_started = perf_counter()
        adapt(result)
        adaptation_samples.append(perf_counter() - adaptation_started)
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


def _static_fixture(bars: int, churn: str):
    index = pd.date_range("2026-01-01", periods=bars, freq="1h", tz="UTC")
    phase = np.arange(bars, dtype=np.float64)
    close = 100.0 + 0.01 * phase + np.sin(phase / 17.0)
    open_ = close + 0.03 * np.cos(phase / 11.0)
    frame = pd.DataFrame(
        {
            "open": open_,
            "high": np.maximum(open_, close) + 0.5,
            "low": np.minimum(open_, close) - 0.5,
            "close": close,
            "volume": np.full(bars, 1_000.0),
        },
        index=index,
    )
    if churn == "low":
        bars_to_trade = range(1, bars - 1, max(2, bars // 20))
    elif churn == "high":
        bars_to_trade = range(1, bars)
    else:
        raise ValueError(f"unsupported churn={churn!r}")
    commands = tuple(
        OrderCommand(
            timestamp=index[bar],
            symbol="BTC",
            side=OrderSide.BUY if sequence % 2 == 0 else OrderSide.SELL,
            order_type=OrderType.MARKET,
            qty=0.1,
            order_id=f"{churn}-{sequence}",
        )
        for sequence, bar in enumerate(bars_to_trade)
    )
    backend = NativeEventBackend(
        NativeEventConfig(
            account=AccountConfig(initial_capital=20_000.0, leverage=5.0),
            execution=ExecutionConfig(slippage_bps=2.0),
            fee_rate=0.0002,
            use_funding=False,
            native_backend="rust",
            execution_contract="event_lifecycle_v3_next_open",
        )
    )
    market = backend.prepare_market_arrays(
        index,
        closes={"BTC": frame["close"]},
        highs={"BTC": frame["high"]},
        lows={"BTC": frame["low"]},
        symbols=["BTC"],
    )
    compiled = backend.compile_order_commands(index, commands, symbols=["BTC"])
    full_runner = RustFullRunner(
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
        event_contract="event_lifecycle_v3_next_open",
        opens_arr=frame["open"].to_numpy(dtype=np.float64).reshape(-1, 1),
        volumes_arr=frame["volume"].to_numpy(dtype=np.float64).reshape(-1, 1),
    )
    ptr, codes, values, expiry = full_runner._tape_arrays(compiled)
    import _quantbt_native

    direct = _quantbt_native.NativeExecutionRequestCore.from_command_tape(
        full_runner.prepared_market_core,
        ptr,
        codes,
        values,
        expiry,
        np.array([1.0], dtype=np.float64),
        np.array([5.0], dtype=np.float64),
        np.array([0.0002], dtype=np.float64),
        20_000.0,
        0.005,
        0.0002,
        False,
        event_contract_code=EVENT_CONTRACT_CODE,
        output_profile=0,
    )
    cache = NativeExecutionPreparationCache(CachePolicy(max_bytes=32 * 1024 * 1024, max_entries=8))
    prepared_market = cache.prepare_market(
        timestamps_ns=np.ascontiguousarray(index.asi8, dtype=np.int64),
        opens=np.ascontiguousarray(frame["open"].to_numpy(dtype=np.float64).reshape(-1, 1)),
        highs=np.ascontiguousarray(market.highs, dtype=np.float64),
        lows=np.ascontiguousarray(market.lows, dtype=np.float64),
        closes=np.ascontiguousarray(market.closes, dtype=np.float64),
        volumes=np.ascontiguousarray(frame["volume"].to_numpy(dtype=np.float64).reshape(-1, 1)),
        funding=np.ascontiguousarray(market.funding, dtype=np.float64),
        funding_mask=np.ascontiguousarray(market.is_funding_bar, dtype=np.bool_),
        symbols=["BTC"],
    )
    template = cache.prepare_template(
        prepared_market,
        contract_sizes=np.array([1.0]),
        leverages=np.array([5.0]),
        fee_rates=np.array([0.0002]),
        initial_capital=20_000.0,
        maintenance_ratio=0.005,
        slippage_rate=0.0002,
        use_funding=False,
        event_contract_code=EVENT_CONTRACT_CODE,
    )
    prepared = cache.command_request(
        template,
        command_ptr=ptr,
        command_codes=codes,
        command_values=values,
        command_expiry=expiry,
        output_profile=0,
    )
    return full_runner, direct, cache, prepared, len(commands)


def _score_summary(result) -> dict[str, object]:
    return {
        "final_equity": float(result.final_equity),
        "total_fee": float(result.total_fee),
        "total_turnover": float(result.total_turnover),
        "fill_count": int(result.fill_count),
        "event_count": int(result.event_count),
        "rejected_count": int(result.rejected_count),
        "canceled_count": int(result.canceled_count),
        "fingerprint": _fingerprint(
            float(result.final_equity),
            float(result.total_fee),
            float(result.total_turnover),
            np.asarray(result.final_positions),
        ),
    }


def _e0(bars: int, churn: str, repeats: int) -> dict:
    full_runner, direct, cache, prepared, commands = _static_fixture(bars, churn)
    direct_times, direct_output = _measure(direct.execute_typed, lambda result: result.as_dict(), repeats)
    prepared_runner = cache.new_runner(prepared)
    prepared_times, prepared_output = _measure(prepared_runner.execute_typed, lambda result: result.as_dict(), repeats)
    direct_summary = _score_summary(direct_output)
    prepared_summary = _score_summary(prepared_output)
    assert direct_summary == prepared_summary
    assert direct_output.as_dict()["native_execution_passes"] == 1
    assert prepared_output.as_dict()["native_execution_passes"] == 1
    cache_diagnostics = cache.diagnostics
    return {
        "workload": "E0_STATIC_EXPLICIT_COMMAND_TAPE",
        "bars": bars,
        "symbols": 1,
        "commands": commands,
        "churn": churn,
        "direct_typed_score": {
            **direct_times,
            "bars_per_second": bars / direct_times["engine_median_seconds"],
            "python_to_rust_calls_per_run": 1,
            "python_callbacks_per_run": 0,
            "input_copies_per_run": 0,
            **direct_summary,
        },
        "prepared_runner_score": {
            **prepared_times,
            "bars_per_second": bars / prepared_times["engine_median_seconds"],
            "python_to_rust_calls_per_run": 1,
            "python_callbacks_per_run": 0,
            "input_copies_per_run": 0,
            "cache_ingress_copy_count": int(cache_diagnostics["ingress_copy_count"]),
            "cache_resident_bytes": int(cache_diagnostics["resident_bytes"]),
            **prepared_summary,
        },
        "parity": {"direct_vs_prepared_score_exact": True, "audit_replay_forced": False},
    }


def _ir_fixture(bars: int):
    index = pd.date_range("2026-02-01", periods=bars, freq="1h", tz="UTC")
    phase = np.arange(bars, dtype=np.float64)
    close = pd.Series(100.0 + 0.005 * phase + np.sin(phase / 11.0), index=index)
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
        closes={"BTC": close},
        highs={"BTC": close + 0.5},
        lows={"BTC": close - 0.5},
        symbols=["BTC"],
    )
    program = NativeStrategyIR(
        NativeStrategyKind.GRID_LEVEL,
        "BTC",
        parameters=NativeStrategyParameters(quantity=0.25),
    )
    signal = np.where(
        (np.arange(bars) // 23) % 4 == 0,
        2.0,
        np.where((np.arange(bars) // 23) % 4 == 1, 1.0, np.where((np.arange(bars) // 23) % 4 == 2, -1.0, -2.0)),
    ).astype(np.float64)
    return index, close, backend, RustNativeIRRunner(full_runner, program), signal


def _e3(bars: int, repeats: int) -> dict:
    index, close, backend, runner, signal = _ir_fixture(bars)
    reference = runner.program.reference_tape(index, signal, close)
    compiled = backend.compile_order_commands(index, reference.commands, symbols=["BTC"])
    market = backend.prepare_market_arrays(
        index, closes={"BTC": close}, highs={"BTC": close + 0.5}, lows={"BTC": close - 0.5}, symbols=["BTC"]
    )

    def python_oracle():
        return backend.run_order_commands(
            index,
            reference.commands,
            closes={"BTC": close},
            highs={"BTC": close + 0.5},
            lows={"BTC": close - 0.5},
            symbols=["BTC"],
            market_arrays=market,
            compiled_commands=compiled,
            report_level="minimal",
            _force_python_backend=True,
        )

    python_times, python_result = _measure(python_oracle, lambda result: result.full_report(), repeats)
    rust_times, rust_result = _measure(lambda: runner.run_score(signal), lambda result: result.payload, repeats)
    audit = runner.run_audit(signal).payload
    np.testing.assert_allclose(audit["equity"], python_result.equity.to_numpy(dtype=np.float64), rtol=0.0, atol=1e-12)
    np.testing.assert_allclose(audit["positions"][:, 0], python_result.positions["Position_BTC"].to_numpy(dtype=np.float64), rtol=0.0, atol=1e-12)
    rust_summary = {
        "final_equity": float(rust_result.final_equity),
        "total_fee": float(rust_result.payload["total_fee"]),
        "fingerprint": _fingerprint(
            float(rust_result.final_equity),
            float(rust_result.payload["total_fee"]),
        ),
    }
    return {
        "workload": "E3_NATIVE_STRATEGY_IR",
        "bars": bars,
        "strategy_kind": runner.program.kind.value,
        "commands": int(audit["strategy_ir_command_count"]),
        "python_reference": {
            **python_times,
            "bars_per_second": bars / python_times["engine_median_seconds"],
            "python_to_rust_calls_per_run": 0,
            "python_callbacks_per_run": 0,
            "result_fingerprint": _fingerprint(python_result.equity.to_numpy(dtype=np.float64)),
        },
        "rust_ir_score": {
            **rust_times,
            "bars_per_second": bars / rust_times["engine_median_seconds"],
            "python_to_rust_calls_per_run": 1,
            "python_callbacks_per_run": 0,
            "input_copies_per_run": 0,
            **rust_summary,
        },
        "parity": {"python_oracle_vs_rust_audit": True, "audit_replay_forced": False},
    }


def _e6(bars: int, scenarios: int, repeats: int) -> dict:
    _, _, _, runner, signal = _ir_fixture(bars)
    signals = np.vstack([np.roll(signal, row * 5) for row in range(scenarios)]).astype(np.float64)
    parameters = np.zeros((scenarios, 4), dtype=np.float64)
    parameters[:, 0] = 0.10 + 0.01 * (np.arange(scenarios) % 8)

    def serial():
        return np.asarray(
            [runner.run_score(signals[row], parameters=parameters[row]).final_equity for row in range(scenarios)],
            dtype=np.float64,
        )

    def batch():
        return runner.run_batch_score(signals, parameter_matrix=parameters, workers=2, chunk_size=16)

    serial_times, serial_result = _measure(serial, lambda result: result.copy(), repeats)
    batch_times, batch_result = _measure(batch, lambda result: result.final_equity.copy(), repeats)
    np.testing.assert_allclose(batch_result.final_equity, serial_result, rtol=0.0, atol=1e-12)
    return {
        "workload": "E6_BATCH_OPTIMIZER_WFO",
        "bars": bars,
        "scenarios": scenarios,
        "serial_native_scenarios": {
            **serial_times,
            "simulated_bars_per_second": scenarios * bars / serial_times["engine_median_seconds"],
            "python_to_rust_calls_per_batch": scenarios,
            "python_callbacks_per_run": 0,
            "result_fingerprint": _fingerprint(serial_result),
        },
        "shared_native_batch": {
            **batch_times,
            "simulated_bars_per_second": scenarios * bars / batch_times["engine_median_seconds"],
            "python_to_rust_calls_per_batch": int(batch_result.metadata["boundary_calls"]),
            "python_callbacks_per_run": 0,
            "shared_market_copies_per_scenario": int(batch_result.metadata["shared_market_copies_per_scenario"]),
            "requested_workers": int(batch_result.metadata["requested_workers"]),
            "actual_workers": int(batch_result.metadata["actual_workers"]),
            "result_fingerprint": _fingerprint(batch_result.final_equity),
        },
        "parity": {"serial_vs_shared_batch_exact": True, "selected_audit_deferred": True},
    }


def _not_promoted_workloads() -> dict[str, dict[str, object]]:
    return {
        "E1_CALLBACK": {
            "measurement_status": "not_native_promotion_scope",
            "reason": "Arbitrary every-bar Python callbacks retain an intentional Python callback boundary.",
        },
        "E2_SPARSE_CALLBACK": {
            "measurement_status": "not_native_promotion_scope",
            "reason": "Sparse callback/session behavior is compatibility infrastructure, not a one-call typed score route.",
        },
        "E4_PORTFOLIO": {
            "measurement_status": "not_native_promotion_scope",
            "reason": "Typed portfolio preflight has parity tests, but no promoted endpoint-level full native portfolio execution benchmark.",
        },
        "E5_PACKAGE": {
            "measurement_status": "not_native_promotion_scope",
            "reason": "Typed package preflight has parity tests, but no promoted endpoint-level package execution benchmark.",
        },
    }


def _markdown(payload: dict) -> str:
    lines = [
        "# Phase 54A.5.6 Native Execution Exit Evidence",
        "",
        "This artifact is machine-specific evidence, not an automatic backend promotion.",
        "Only E0, E3, and E6 execute a native one-call score path in this phase.",
        "",
        "| Workload | Scope | Parity | Native boundary |",
        "| --- | --- | --- | --- |",
    ]
    for churn, row in payload["e0"].items():
        parity = ", ".join(name for name, value in row["parity"].items() if value)
        lines.append(
            f"| {row['workload']} ({churn}) | measured | {parity} | recorded in JSON |"
        )
    for key in ("e3", "e6"):
        row = payload[key]
        parity = ", ".join(name for name, value in row["parity"].items() if value)
        lines.append(f"| {row['workload']} | measured | {parity} | recorded in JSON |")
    lines.extend(["", "## Non-promotion workloads", ""])
    for key, row in payload["not_promoted_workloads"].items():
        lines.append(f"- **{key}**: {row['reason']}")
    lines.extend(
        [
            "",
            "The score paths retain no dense audit ledger and do not invoke an audit replay. "
            "Rust remains explicit/experimental until a later workload-specific promotion gate passes.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bars", type=int, default=2_000)
    parser.add_argument("--scenarios", type=int, default=64)
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "benchmarks/native_event/results/phase54a5/exit_gate.json",
    )
    args = parser.parse_args()
    if args.bars < 8 or args.scenarios < 2 or args.repeats < 3:
        parser.error("requires bars >= 8, scenarios >= 2, and repeats >= 3")
    payload = {
        "schema_version": 1,
        "phase": PHASE,
        "method": "warm prepared native workloads; median wall time; engine and explicit cold adaptation recorded separately",
        "promotion_eligible": False,
        "promotion_reason": "Phase 54A.5.6 closes differential evidence only; workload-specific Phase 54B promotion gates remain required.",
        "e0": {"low_churn": _e0(args.bars, "low", args.repeats), "high_churn": _e0(args.bars, "high", args.repeats)},
        "e3": _e3(args.bars, args.repeats),
        "e6": _e6(args.bars, args.scenarios, args.repeats),
        "not_promoted_workloads": _not_promoted_workloads(),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    args.output.with_suffix(".md").write_text(_markdown(payload), encoding="utf-8")
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
