#!/usr/bin/env python3
"""Certify Phase 52A planning/preparation surfaces from an installed wheel."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd

import quantbt
from quantbt import OrderCommand, OrderSide, OrderType, QuantBTEndpoint
from quantbt.planning import BacktestRequest, RunProfile, StrategyMode, WorkloadClass, resolve_execution_plan


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected-site", type=Path, required=True)
    args = parser.parse_args()
    expected_site = args.expected_site.resolve()
    package_path = Path(quantbt.__file__).resolve()
    if expected_site not in package_path.parents:
        raise RuntimeError(f"quantbt imported from {package_path}, not {expected_site}")

    index = pd.date_range("2026-01-01", periods=6, freq="1h", tz="UTC")
    close = np.asarray([100.0, 102.0, 101.0, 104.0, 103.0, 105.0])
    frame = pd.DataFrame(
        {
            "open": close - 0.25,
            "high": close + 1.0,
            "low": close - 1.0,
            "close": close,
            "volume": 1_000.0,
        },
        index=index,
    )
    commands = (
        OrderCommand(
            timestamp=index[1], symbol="BTC", side=OrderSide.BUY,
            order_type=OrderType.MARKET, qty=1.0, order_id="entry",
        ),
        OrderCommand(
            timestamp=index[4], symbol="BTC", side=OrderSide.SELL,
            order_type=OrderType.MARKET, qty=1.0, order_id="exit",
        ),
    )
    endpoint = QuantBTEndpoint.native_event_lifecycle(
        initial_capital=10_000.0,
        leverage=3.0,
        fee_rate=0.0005,
        slippage_bps=1.0,
        use_funding=False,
        native_backend="python",
        execution_contract="event_lifecycle_v3_next_open",
    )
    result = endpoint.simulate(data=frame, order_commands=commands, symbols=["BTC"])
    metadata = result.metadata
    diagnostics = metadata["preparation_diagnostics_v1"]

    probe_calls = 0

    def forbidden_native_probe():
        nonlocal probe_calls
        probe_calls += 1
        raise AssertionError("auto planning must not probe the optional native module")

    auto_plan = resolve_execution_plan(
        BacktestRequest(
            endpoint_mode="orders",
            input_mode="orders",
            requested_backend="auto",
            execution_contract_id="event_lifecycle_v2_next_bar_close",
            strategy_mode=StrategyMode.STATIC_COMMANDS,
            workload=WorkloadClass.STATIC_COMMAND_TAPE,
            profile=RunProfile.MINIMAL,
            report_level="minimal",
            audit_sink="none",
            symbols=("BTC",),
        ),
        rust_capability_loader=forbidden_native_probe,
    )
    checks = {
        "wheel_module_path": expected_site in package_path.parents,
        "lifecycle_pipeline": metadata.get("p1_execution_route")
        == "plan_prepare_legacy_public_adapter_v1",
        "plan_fingerprint": len(metadata.get("execution_plan_fingerprint", "")) == 64,
        "prepared_fingerprint": len(metadata["prepared_run_keys_v1"]["combined"]) == 64,
        "one_market_normalization": diagnostics["market_normalizations"] == 1,
        "one_instrument_normalization": diagnostics["instrument_normalizations"] == 1,
        "one_command_compilation": diagnostics["command_compilations"] == 1,
        "one_backend_resolution": diagnostics["backend_resolutions"] == 1,
        "one_output_projection": diagnostics["output_projections"] == 1,
        "auto_native_lazy": probe_calls == 0 and auto_plan.backend.value == "python",
        "native_module_not_eager": "_quantbt_native" not in sys.modules,
        "accounting_audit": bool(metadata["accounting_invariants_v1"]["passed"]),
        "trace_replay": bool(metadata["canonical_trace_replay_v1"]["passed"]),
    }
    report = {
        "certification": "phase52a-installed-wheel-v1",
        "quantbt_path": str(package_path),
        "plan_fingerprint": metadata["execution_plan_fingerprint"],
        "prepared_fingerprint": metadata["prepared_run_keys_v1"]["combined"],
        "final_equity": float(result.equity.iloc[-1]),
        "checks": checks,
        "passed": all(checks.values()),
    }
    print(json.dumps(report, indent=2, sort_keys=True))
    if not report["passed"]:
        raise RuntimeError("Phase 52A installed-wheel certification failed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
