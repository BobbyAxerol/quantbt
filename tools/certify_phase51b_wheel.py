#!/usr/bin/env python3
"""Certify an isolated Phase 51B core/native wheel installation."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
import _quantbt_native

import quantbt
from quantbt import (
    AccountConfig,
    ExecutionConfig,
    NativeEventBackend,
    NativeEventConfig,
    OrderCommand,
    OrderSide,
    OrderType,
    TraceReplayer,
    assert_native_accounting_invariants,
    compare_canonical_traces,
    native_event_semantic_descriptor,
)
from quantbt.backends._native_event_rust import probe_native_event_rust_extension
from quantbt.core.event_contracts import EVENT_LIFECYCLE_V3_NEXT_OPEN


def _run(backend: str):
    index = pd.date_range("2026-01-01", periods=8, freq="1h", tz="UTC")
    close = np.asarray([100.0, 102.0, 104.0, 101.0, 98.0, 103.0, 106.0, 105.0])
    frame = pd.DataFrame(
        {
            "open": close - 0.5,
            "high": close + 2.0,
            "low": close - 2.0,
            "close": close,
        },
        index=index,
    )
    commands = (
        OrderCommand(
            timestamp=index[1],
            symbol="BTC",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            qty=2.0,
            order_id="entry",
        ),
        OrderCommand(
            timestamp=index[4],
            symbol="BTC",
            side=OrderSide.SELL,
            order_type=OrderType.LIMIT,
            qty=1.0,
            price=100.0,
            order_id="reduce",
        ),
        OrderCommand(
            timestamp=index[7],
            symbol="BTC",
            side=OrderSide.SELL,
            order_type=OrderType.MARKET,
            qty=1.0,
            order_id="close",
        ),
    )
    engine = NativeEventBackend(
        NativeEventConfig(
            account=AccountConfig(initial_capital=10_000.0, leverage=5.0),
            execution=ExecutionConfig(slippage_bps=3.0),
            fee_rate=0.0005,
            report_level="audit",
            native_backend=backend,
            execution_contract=EVENT_LIFECYCLE_V3_NEXT_OPEN,
        )
    )
    return engine.run_order_commands(
        index,
        commands,
        closes={"BTC": frame["close"]},
        highs={"BTC": frame["high"]},
        lows={"BTC": frame["low"]},
        opens={"BTC": frame["open"]},
        symbols=["BTC"],
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--expected-site",
        type=Path,
        required=True,
        help="Directory containing the isolated wheel installation.",
    )
    args = parser.parse_args()
    expected_site = args.expected_site.resolve()

    package_path = Path(quantbt.__file__).resolve()
    native_module_path = Path(_quantbt_native.__file__).resolve()
    if expected_site not in package_path.parents:
        raise RuntimeError(f"quantbt imported from {package_path}, not {expected_site}")
    if expected_site not in native_module_path.parents:
        raise RuntimeError(
            f"_quantbt_native imported from {native_module_path}, not {expected_site}"
        )

    status = probe_native_event_rust_extension()
    if not (status.available and status.compatible and status.executable):
        raise RuntimeError(f"native extension failed capability gate: {status}")
    if status.semantic_descriptor != native_event_semantic_descriptor():
        raise RuntimeError("native semantic descriptor differs from the Python contract")

    python_result = _run("python")
    rust_result = _run("rust")
    python_audit = assert_native_accounting_invariants(python_result)
    rust_audit = assert_native_accounting_invariants(rust_result)
    trace_parity = compare_canonical_traces(
        python_result.metadata["canonical_trace_v1"],
        rust_result.metadata["canonical_trace_v1"],
    )
    python_replay = TraceReplayer().replay(python_result.metadata["canonical_trace_v1"])
    rust_replay = TraceReplayer().replay(rust_result.metadata["canonical_trace_v1"])

    report = {
        "certification": "phase51b-installed-wheel-v1",
        "quantbt_path": str(package_path),
        "native_module_path": str(native_module_path),
        "api_version": status.api_version,
        "semantic_descriptor": status.semantic_descriptor,
        "python_accounting_passed": python_audit.invariants["passed"],
        "rust_accounting_passed": rust_audit.invariants["passed"],
        "trace_parity_passed": trace_parity["passed"],
        "trace_fingerprint": python_result.metadata["canonical_trace_fingerprint"],
        "python_replay_passed": python_replay.passed,
        "rust_replay_passed": rust_replay.passed,
        "final_equity": float(python_result.equity.iloc[-1]),
        "passed": bool(
            python_audit.invariants["passed"]
            and rust_audit.invariants["passed"]
            and trace_parity["passed"]
            and python_replay.passed
            and rust_replay.passed
        ),
    }
    print(json.dumps(report, indent=2, sort_keys=True))
    if not report["passed"]:
        raise RuntimeError("Phase 51B installed-wheel certification failed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
