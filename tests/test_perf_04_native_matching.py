"""PERF-04 matching/index specialization and lifecycle parity locks."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from quantbt.backends import NativeEventBackend, NativeEventConfig
from quantbt.core.event_contracts import EVENT_LIFECYCLE_V3_NEXT_OPEN
from quantbt.core.native_event_parity import assert_native_event_full_parity
from quantbt.core.orders import OrderCommand
from quantbt.core.schema import AccountConfig, ExecutionConfig, OrderSide, OrderType
from quantbt.preparation import CachePolicy, NativeExecutionPreparationCache


pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("_quantbt_native") is None,
    reason="quantbt-native extension is not installed in this environment",
)


ROOT = Path(__file__).resolve().parents[1]
PERF04_REGISTRY = ROOT / "benchmarks" / "native_event" / "registries" / "perf_04_specialization_registry_v1.json"


def _market(bars: int = 22) -> tuple[pd.DatetimeIndex, pd.DataFrame]:
    index = pd.date_range("2026-09-01", periods=bars, freq="1h", tz="UTC")
    close = 100.0 + np.sin(np.arange(bars, dtype=np.float64) / 3.0)
    frame = pd.DataFrame(
        {
            "open": close,
            "high": close + 1.0,
            "low": close - 1.0,
            "close": close,
            "volume": np.full(bars, 50_000.0),
        },
        index=index,
    )
    return index, frame


def _high_churn_commands(index: pd.DatetimeIndex, *, orders: int = 16, cycles: int = 4) -> tuple[OrderCommand, ...]:
    commands: list[OrderCommand] = []
    for cycle in range(cycles):
        place_bar = 1 + cycle * 4
        for ordinal in range(orders):
            original = f"p-{cycle}-{ordinal}"
            replacement = f"r-{cycle}-{ordinal}"
            commands.append(
                OrderCommand(
                    timestamp=index[place_bar],
                    symbol="BTC",
                    side=OrderSide.BUY,
                    order_type=OrderType.LIMIT,
                    qty=1.0,
                    price=10.0,
                    order_id=original,
                )
            )
            commands.append(
                OrderCommand(
                    timestamp=index[place_bar + 1],
                    action="amend",
                    target_order_id=original,
                    price=9.0,
                )
            )
            commands.append(
                OrderCommand(
                    timestamp=index[place_bar + 2],
                    action="replace",
                    target_order_id=original,
                    symbol="BTC",
                    side=OrderSide.BUY,
                    order_type=OrderType.LIMIT,
                    qty=1.0,
                    price=8.0,
                    order_id=replacement,
                )
            )
        commands.append(
            OrderCommand(
                timestamp=index[place_bar + 3],
                action="cancel_all",
                order_id=f"cancel-all-{cycle}",
            )
        )
    return tuple(commands)


def _backend(native_backend: str) -> NativeEventBackend:
    return NativeEventBackend(
        NativeEventConfig(
            account=AccountConfig(initial_capital=20_000.0, leverage=4.0),
            execution=ExecutionConfig(slippage_bps=0.0),
            fee_rate=0.0005,
            use_funding=False,
            native_backend=native_backend,
            execution_contract=EVENT_LIFECYCLE_V3_NEXT_OPEN,
            diagnostics=True,
        )
    )


def _run_public(native_backend: str):
    index, frame = _market()
    commands = _high_churn_commands(index)
    return _backend(native_backend).run_order_commands(
        datetime_index=index,
        commands=commands,
        closes={"BTC": frame["close"]},
        highs={"BTC": frame["high"]},
        lows={"BTC": frame["low"]},
        opens={"BTC": frame["open"]},
        symbols=["BTC"],
        report_level="audit",
    )


def _raw_high_churn_tape(
    *, bars: int, orders: int = 16, cycles: int = 4
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    by_bar: list[list[tuple[np.ndarray, np.ndarray, int]]] = [[] for _ in range(bars)]
    next_id = 1
    command_index = 0
    for cycle in range(cycles):
        place_bar = 1 + cycle * 4
        originals: list[int] = []
        for _ in range(orders):
            original = next_id
            next_id += 1
            originals.append(original)
            code = np.full(16, -1, dtype=np.int64)
            code[[0, 1, 2, 3, 4, 5, 6, 11, 12]] = (
                0,
                0,
                1,
                1,
                0,
                0,
                original,
                0,
                command_index,
            )
            command_index += 1
            by_bar[place_bar].append((code, np.array([1.0, 10.0, 0.0]), -1))

        for original in originals:
            code = np.full(16, -1, dtype=np.int64)
            code[[0, 1, 7, 12]] = (3, 0, original, command_index)
            command_index += 1
            by_bar[place_bar + 1].append((code, np.array([0.0, 9.0, 0.0]), -1))

        for original in originals:
            replacement = next_id
            next_id += 1
            code = np.full(16, -1, dtype=np.int64)
            code[[0, 1, 2, 3, 4, 5, 6, 7, 11, 12]] = (
                2,
                0,
                1,
                1,
                0,
                0,
                replacement,
                original,
                0,
                command_index,
            )
            command_index += 1
            by_bar[place_bar + 2].append((code, np.array([1.0, 8.0, 0.0]), -1))

        cancel_all = np.full(16, -1, dtype=np.int64)
        cancel_all[[0, 1, 2, 6, 12]] = (4, -1, 0, next_id, command_index)
        next_id += 1
        command_index += 1
        by_bar[place_bar + 3].append((cancel_all, np.zeros(3, dtype=np.float64), -1))

    ptr = np.zeros(bars + 1, dtype=np.int64)
    codes: list[np.ndarray] = []
    values: list[np.ndarray] = []
    expiry: list[int] = []
    for bar, rows in enumerate(by_bar):
        for code, value, expire in rows:
            codes.append(code)
            values.append(value)
            expiry.append(expire)
        ptr[bar + 1] = len(codes)
    return (
        np.ascontiguousarray(ptr),
        np.ascontiguousarray(np.asarray(codes, dtype=np.int64)),
        np.ascontiguousarray(np.asarray(values, dtype=np.float64)),
        np.ascontiguousarray(np.asarray(expiry, dtype=np.int64)),
    )


def _prepared_runner():
    index, frame = _market()
    bars = len(frame)
    cache = NativeExecutionPreparationCache(CachePolicy(max_bytes=8 * 1024 * 1024, max_entries=8))
    close = np.ascontiguousarray(frame[["close"]].to_numpy(dtype=np.float64))
    market = cache.prepare_market(
        timestamps_ns=np.ascontiguousarray(index.asi8, dtype=np.int64),
        opens=np.ascontiguousarray(frame[["open"]].to_numpy(dtype=np.float64)),
        highs=np.ascontiguousarray(frame[["high"]].to_numpy(dtype=np.float64)),
        lows=np.ascontiguousarray(frame[["low"]].to_numpy(dtype=np.float64)),
        closes=close,
        volumes=np.ascontiguousarray(frame[["volume"]].to_numpy(dtype=np.float64)),
        funding=np.zeros_like(close),
        funding_mask=np.zeros(bars, dtype=np.bool_),
        symbols=["BTC"],
    )
    template = cache.prepare_template(
        market,
        contract_sizes=np.ones(1, dtype=np.float64),
        leverages=np.full(1, 4.0, dtype=np.float64),
        fee_rates=np.full(1, 0.0005, dtype=np.float64),
        initial_capital=20_000.0,
        maintenance_ratio=0.005,
        slippage_rate=0.0,
        use_funding=False,
        event_contract_code=3,
    )
    ptr, codes, values, expiry = _raw_high_churn_tape(bars=bars)
    request = cache.command_request(
        template,
        command_ptr=ptr,
        command_codes=codes,
        command_values=values,
        command_expiry=expiry,
        output_profile=2,
    )
    return request, cache.new_runner(request)


def test_perf04_public_high_churn_lifecycle_preserves_python_rust_parity() -> None:
    python = _run_public("python")
    rust = _run_public("rust")
    certificate = assert_native_event_full_parity(python, rust)
    assert certificate["passed"] is True
    np.testing.assert_allclose(rust.equity.to_numpy(), 20_000.0, rtol=0.0, atol=1e-12)
    np.testing.assert_allclose(rust.positions.to_numpy(), 0.0, rtol=0.0, atol=1e-12)
    assert len(rust.fills) == 0
    assert rust.metadata["lifecycle_counters"]["canceled_count"] == 64


def test_perf04_prepared_runner_reuses_and_releases_matching_scratch() -> None:
    request, runner = _prepared_runner()
    first = runner.execute_typed()
    diagnostics = dict(runner.diagnostics())
    assert diagnostics["matching_scan_count"] >= 64
    assert diagnostics["matching_candidate_capacity"] >= 16
    assert diagnostics["lifecycle_candidate_capacity"] >= 16
    assert diagnostics["active_external_alias_count"] == 0
    assert diagnostics["terminal_orders_removed"] == 128
    np.testing.assert_allclose(first.final_equity, 20_000.0, rtol=0.0, atol=1e-12)
    np.testing.assert_allclose(first.final_positions, [0.0], rtol=0.0, atol=1e-12)

    runner.reset("result_buffers", max_capacity=0)
    released = dict(runner.diagnostics())
    assert released["matching_candidate_capacity"] == 0
    assert released["lifecycle_candidate_capacity"] == 0

    second = runner.execute_typed()
    np.testing.assert_allclose(second.equity, first.equity, rtol=0.0, atol=1e-12)
    np.testing.assert_allclose(second.positions, first.positions, rtol=0.0, atol=1e-12)
    assert second.execution_generation == first.execution_generation + 1
    assert request.workload == "command_tape_v5"


def test_perf04_specialization_registry_keeps_shared_accounting_boundaries_explicit() -> None:
    registry = json.loads(PERF04_REGISTRY.read_text(encoding="utf-8"))
    assert registry["schema"] == "quantbt-perf-04-specialization-registry-v1"
    assert registry["matching"]["candidate_source"] == "LifecycleIndexes.active_by_sequence"
    assert registry["matching"]["same_phase_child_policy"].startswith("Append")
    assert registry["ownership"]["order_authority"] == "FullSession.OrderArena<OrderState>"
    ids = {row["id"] for row in registry["workloads"]}
    assert ids == {
        "linear_target_score",
        "static_orders_score_compact_audit",
        "reactive_linear_compact",
        "shared_account_portfolio_rebalance",
        "bounded_package_audit",
    }
    assert "equity-dependent sizing" in registry["decision_rules"]["runtime_dynamic_state"]
