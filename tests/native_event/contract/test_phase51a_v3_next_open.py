from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from quantbt import QuantBTEndpoint
from quantbt.backends import NativeEventBackend, NativeEventConfig
from quantbt.core.event_contracts import (
    EVENT_LIFECYCLE_V2_NEXT_BAR_CLOSE,
    EVENT_LIFECYCLE_V3_NEXT_OPEN,
    NATIVE_EVENT_CONTRACT_FINGERPRINT,
)
from quantbt.core.native_event_parity import assert_native_event_full_parity
from quantbt.core.orders import OrderCommand
from quantbt.core.schema import AccountConfig, ExecutionConfig, OrderSide, OrderType


def _market():
    index = pd.date_range("2026-01-01", periods=5, freq="1h", tz="UTC")
    frame = pd.DataFrame(
        {
            "open": [100.0, 108.0, 103.0, 96.0, 104.0],
            "high": [103.0, 114.0, 110.0, 106.0, 110.0],
            "low": [98.0, 104.0, 99.0, 91.0, 99.0],
            "close": [101.0, 112.0, 105.0, 103.0, 102.0],
            "volume": [1000.0, 1200.0, 900.0, 1800.0, 1500.0],
        },
        index=index,
    )
    return index, frame


def _backend(backend: str, contract: str, *, diagnostics: bool = False):
    return NativeEventBackend(
        NativeEventConfig(
            account=AccountConfig(initial_capital=10_000.0, leverage=5.0),
            execution=ExecutionConfig(slippage_bps=10.0),
            fee_rate=0.0005,
            use_funding=False,
            native_backend=backend,
            execution_contract=contract,
            diagnostics=diagnostics,
        )
    )


def _run(backend: str, contract: str, commands, *, frame=None, diagnostics=False):
    default_index, default_frame = _market()
    frame = default_frame if frame is None else frame
    index = default_index if frame is default_frame else pd.DatetimeIndex(frame.index)
    maps = {name: {"TEST": frame[name]} for name in ("open", "high", "low", "close")}
    return _backend(backend, contract, diagnostics=diagnostics).run_order_commands(
        datetime_index=index,
        commands=commands,
        closes=maps["close"],
        highs=maps["high"],
        lows=maps["low"],
        opens=maps["open"],
        symbols=["TEST"],
    )


@pytest.mark.parametrize(("side", "multiplier"), [(OrderSide.BUY, 1.001), (OrderSide.SELL, 0.999)])
def test_v3_market_uses_actual_open_in_python_and_rust(side, multiplier) -> None:
    index, _ = _market()
    commands = (
        OrderCommand(
            timestamp=index[1],
            symbol="TEST",
            side=side,
            order_type=OrderType.MARKET,
            qty=1.0,
            order_id=f"market-{side.value}",
        ),
    )
    python = _run("python", EVENT_LIFECYCLE_V3_NEXT_OPEN, commands, diagnostics=True)
    rust = _run("rust", EVENT_LIFECYCLE_V3_NEXT_OPEN, commands)

    expected = 108.0 * multiplier
    assert python.fills[0].price == pytest.approx(expected)
    assert rust.fills[0].price == pytest.approx(expected)
    assert_native_event_full_parity(python, rust)
    assert python.metadata["execution_contract_id"] == EVENT_LIFECYCLE_V3_NEXT_OPEN
    diagnostics = python.metadata["engine_diagnostics_v1"]
    assert diagnostics["bars_processed"] == 5
    assert diagnostics["commands_processed"] == 1
    assert diagnostics["fills_emitted"] == 1
    assert rust.metadata["event_clock_contract"]["registry_fingerprint"] == NATIVE_EVENT_CONTRACT_FINGERPRINT


def test_v2_is_frozen_at_close_and_does_not_read_open() -> None:
    index, frame = _market()
    commands = (
        OrderCommand(
            timestamp=index[1], symbol="TEST", side=OrderSide.BUY,
            order_type=OrderType.MARKET, qty=1.0, order_id="legacy-market",
        ),
    )
    baseline = _run("python", EVENT_LIFECYCLE_V2_NEXT_BAR_CLOSE, commands, frame=frame)
    changed = frame.copy()
    changed["open"] = changed["open"] * 0.5
    changed_open = _run("python", EVENT_LIFECYCLE_V2_NEXT_BAR_CLOSE, commands, frame=changed)
    assert baseline.fills[0].price == pytest.approx(112.112)
    assert changed_open.fills[0].price == baseline.fills[0].price
    np.testing.assert_array_equal(baseline.equity.to_numpy(), changed_open.equity.to_numpy())


def test_v3_open_is_causally_material_to_market_fill() -> None:
    index, frame = _market()
    command = (
        OrderCommand(
            timestamp=index[1], symbol="TEST", side=OrderSide.BUY,
            order_type=OrderType.MARKET, qty=1.0, order_id="v3-market",
        ),
    )
    baseline = _run("python", EVENT_LIFECYCLE_V3_NEXT_OPEN, command, frame=frame)
    changed = frame.copy()
    changed.loc[index[1], "open"] = 110.0
    changed.loc[index[1], "high"] = 115.0
    changed_open = _run("python", EVENT_LIFECYCLE_V3_NEXT_OPEN, command, frame=changed)
    assert baseline.fills[0].price == pytest.approx(108.108)
    assert changed_open.fills[0].price == pytest.approx(110.11)
    assert changed_open.fills[0].price != baseline.fills[0].price


@pytest.mark.parametrize("backend", ["python", "rust"])
def test_v3_limit_improvement_and_adverse_stop_gap(backend: str) -> None:
    index, _ = _market()
    limit = (
        OrderCommand(
            timestamp=index[3], symbol="TEST", side=OrderSide.BUY,
            order_type=OrderType.LIMIT, qty=1.0, price=100.0, order_id="gap-limit",
        ),
    )
    stop = (
        OrderCommand(
            timestamp=index[1], symbol="TEST", side=OrderSide.BUY,
            order_type=OrderType.STOP_MARKET, qty=1.0, trigger_price=105.0, order_id="gap-stop",
        ),
    )
    limit_result = _run(backend, EVENT_LIFECYCLE_V3_NEXT_OPEN, limit)
    stop_result = _run(backend, EVENT_LIFECYCLE_V3_NEXT_OPEN, stop)
    assert limit_result.fills[0].price == 96.0
    assert stop_result.fills[0].price == pytest.approx(108.108)


@pytest.mark.parametrize("backend", ["python", "rust"])
def test_v3_stop_limit_ambiguous_bar_arms_then_fills_next_open(backend: str) -> None:
    index, _ = _market()
    commands = (
        OrderCommand(
            timestamp=index[1], symbol="TEST", side=OrderSide.BUY,
            order_type=OrderType.STOP_LIMIT, qty=1.0,
            trigger_price=110.0, price=109.0, order_id="stop-limit",
        ),
    )
    result = _run(backend, EVENT_LIFECYCLE_V3_NEXT_OPEN, commands)
    assert len(result.fills) == 1
    assert result.fills[0].timestamp == index[2]
    assert result.fills[0].price == 103.0
    if backend == "rust":
        fills_report = result.metadata["fills_report"]
        assert int(fills_report.iloc[0]["fill_reason_code"]) == 9
        assert int(fills_report.iloc[0]["fill_ambiguity_code"]) == 0
    else:
        diagnostics = result.metadata["fill_policy_diagnostics"]
        assert bool(diagnostics.iloc[0]["trigger_armed"])


def test_v3_rejects_missing_open_tape() -> None:
    index, frame = _market()
    command = (
        OrderCommand(
            timestamp=index[1], symbol="TEST", side=OrderSide.BUY,
            order_type=OrderType.MARKET, qty=1.0, order_id="needs-open",
        ),
    )
    with pytest.raises(ValueError, match="requires explicit open prices"):
        _backend("python", EVENT_LIFECYCLE_V3_NEXT_OPEN).run_order_commands(
            datetime_index=index,
            commands=command,
            closes={"TEST": frame["close"]},
            highs={"TEST": frame["high"]},
            lows={"TEST": frame["low"]},
            symbols=["TEST"],
        )


def test_public_event_driven_facade_routes_v3_and_emits_diagnostics() -> None:
    index, frame = _market()
    endpoint = QuantBTEndpoint.event_driven(
        input_mode="orders",
        profile="audit",
        backend="python",
        execution_contract=EVENT_LIFECYCLE_V3_NEXT_OPEN,
        initial_capital=10_000.0,
        leverage=5.0,
    )
    command = (
        OrderCommand(
            timestamp=index[1], symbol="asset", side=OrderSide.BUY,
            order_type=OrderType.MARKET, qty=1.0, order_id="facade-v3",
        ),
    )
    result = endpoint.simulate(data=frame, order_commands=command, symbols=["asset"])
    assert result.fills[0].price == 108.0
    assert result.metadata["execution_contract_id"] == EVENT_LIFECYCLE_V3_NEXT_OPEN


def test_audit_phase_trace_and_lifecycle_projection_are_explicit() -> None:
    index, _ = _market()
    commands = (
        OrderCommand(
            timestamp=index[1], symbol="TEST", side=OrderSide.BUY,
            order_type=OrderType.MARKET, qty=1.0, order_id="entry",
        ),
        OrderCommand(timestamp=index[2], action="cancel", target_order_id="entry"),
    )
    result = _run("python", EVENT_LIFECYCLE_V3_NEXT_OPEN, commands)

    phase_trace = result.metadata["event_phase_trace_v1"]
    assert phase_trace.columns.tolist() == ["bar", "timestamp_ns", "phase", "sequence"]
    assert phase_trace.iloc[0].to_dict() == {
        "bar": 0,
        "timestamp_ns": index[0].value,
        "phase": "BAR_ZERO_INITIAL_STATE",
        "sequence": 0,
    }
    assert phase_trace["sequence"].tolist() == list(range(len(phase_trace)))
    assert "MATCH_NEXT_BAR_OPEN_AND_INTRABAR" in set(phase_trace["phase"])

    outcomes = result.metadata["command_outcome_report_v1"]
    assert outcomes.loc[outcomes["action"] == "place", "command_outcome"].iloc[0] == "ACCEPTED"
    assert outcomes.loc[outcomes["action"] == "place", "order_status"].iloc[0] == "FILLED"
    assert outcomes.loc[outcomes["action"] == "cancel", "command_outcome"].iloc[0] == "REJECTED"
    lifecycle = result.metadata["lifecycle_event_report_v1"]
    assert {"PLACE", "FILL", "REJECT"}.issubset(set(lifecycle["lifecycle_event_kind"]))


@pytest.mark.parametrize("backend", ["python", "rust"])
def test_bar_zero_explicit_command_is_reported_outside_tape_without_fill(backend: str) -> None:
    index, _ = _market()
    commands = (
        OrderCommand(
            timestamp=index[0], symbol="TEST", side=OrderSide.BUY,
            order_type=OrderType.MARKET, qty=1.0, order_id="bar-zero",
        ),
    )
    result = _run(backend, EVENT_LIFECYCLE_V3_NEXT_OPEN, commands)
    assert len(result.fills) == 0
    np.testing.assert_array_equal(result.positions.to_numpy(), 0.0)
    if backend == "python":
        outcomes = result.metadata["command_outcome_report_v1"]
        assert outcomes.iloc[0]["command_outcome"] == "OUTSIDE_TAPE"


def test_one_bar_and_empty_tape_boundaries_are_deterministic() -> None:
    index, frame = _market()
    one = frame.iloc[:1]
    result = _run("python", EVENT_LIFECYCLE_V3_NEXT_OPEN, (), frame=one)
    assert result.equity.tolist() == [10_000.0]
    assert result.metadata["event_phase_trace_v1"]["phase"].tolist() == ["BAR_ZERO_INITIAL_STATE"]

    backend = _backend("python", EVENT_LIFECYCLE_V3_NEXT_OPEN)
    with pytest.raises(ValueError, match="at least one market bar"):
        backend.run_order_commands(
            datetime_index=pd.DatetimeIndex([], tz="UTC"),
            commands=(),
            closes={"TEST": pd.Series(dtype=float)},
            highs={"TEST": pd.Series(dtype=float)},
            lows={"TEST": pd.Series(dtype=float)},
            opens={"TEST": pd.Series(dtype=float)},
            symbols=["TEST"],
        )


@pytest.mark.parametrize(
    ("backend", "expected"),
    [
        ("python", (4, 4, 1)),
        ("rust", (3, 4, 1)),
    ],
)
def test_engine_diagnostics_have_exact_tiny_fixture_scan_counts(backend: str, expected) -> None:
    index, _ = _market()
    command = (
        OrderCommand(
            timestamp=index[1], symbol="TEST", side=OrderSide.BUY,
            order_type=OrderType.MARKET, qty=1.0, order_id="scan-count",
        ),
    )
    without = _run(backend, EVENT_LIFECYCLE_V3_NEXT_OPEN, command, diagnostics=False)
    with_diagnostics = _run(backend, EVENT_LIFECYCLE_V3_NEXT_OPEN, command, diagnostics=True)
    assert "engine_diagnostics_v1" not in without.metadata
    np.testing.assert_array_equal(without.equity.to_numpy(), with_diagnostics.equity.to_numpy())
    counters = with_diagnostics.metadata["engine_diagnostics_v1"]
    assert (
        counters["expiry_scan_count"],
        counters["matching_scan_count"],
        counters["relationship_scan_count"],
    ) == expected


@pytest.mark.parametrize("backend", ["python", "rust"])
def test_prepared_reactive_v3_accepts_open_array_and_replay_matches(backend: str) -> None:
    index, frame = _market()

    class Strategy:
        def initialize(self, context):
            return (
                OrderCommand(
                    timestamp=context.timestamp,
                    symbol="TEST",
                    side=OrderSide.BUY,
                    order_type=OrderType.MARKET,
                    qty=1.0,
                    order_id="reactive-open",
                ),
            )

        def on_bar_close(self, context):
            return ()

    event_backend = _backend(backend, EVENT_LIFECYCLE_V3_NEXT_OPEN)
    market = event_backend.prepare_market_arrays(
        datetime_index=index,
        closes={"TEST": frame["close"]},
        highs={"TEST": frame["high"]},
        lows={"TEST": frame["low"]},
        symbols=["TEST"],
    )
    result = event_backend.run_strategy(
        datetime_index=index,
        strategy=Strategy(),
        closes={"TEST": frame["close"]},
        highs={"TEST": frame["high"]},
        lows={"TEST": frame["low"]},
        market_arrays=market,
        opens_arr=np.ascontiguousarray(frame[["open"]].to_numpy()),
        volumes_arr=np.ascontiguousarray(frame[["volume"]].to_numpy()),
        symbols=["TEST"],
        execution_mode="audit",
        reactive_kernel_mode="replay_certified",
    )
    assert result.fills[0].price == pytest.approx(108.108)
    assert result.metadata["execution_contract_id"] == EVENT_LIFECYCLE_V3_NEXT_OPEN
