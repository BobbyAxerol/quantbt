"""Phase 62 R1 reactive numeric co-runtime certification.

The R1 route is deliberately an explicit hybrid runtime: Python owns only a
stateful strategy decision while Rust owns the bar clock, command ingestion,
matching, accounting, and result buffers.  These tests keep the legacy Python
loop and the existing Rust per-bar bridge as independent comparators.
"""

from __future__ import annotations

import importlib.util

import numpy as np
import pandas as pd
import pytest

from quantbt import (
    AccountConfig,
    CallbackSchedule,
    ExecutionConfig,
    NativeEventBackend,
    NativeEventConfig,
    OrderSide,
    QuantBTEndpoint,
    StrategyContextRequirements,
)
from quantbt.backends._native_event_rust import RustReactiveNumericCoRuntime
from quantbt.core.constraints import build_quantity_constraints
from quantbt.core.execution_trace import compare_canonical_traces
from quantbt.core.reactive import NativeEventStrategyError


pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("_quantbt_native") is None,
    reason="quantbt-native extension is not installed in this environment",
)


def _frame(*, bars: int = 32) -> pd.DataFrame:
    index = pd.date_range("2026-09-01", periods=bars, freq="1h", tz="UTC")
    phase = np.arange(bars, dtype=np.float64)
    close = 100.0 + 0.14 * phase + 1.25 * np.sin(phase / 4.0)
    return pd.DataFrame(
        {
            "open": np.r_[close[0], close[:-1]] + 0.05,
            "high": close + 0.9,
            "low": close - 0.9,
            "close": close,
            "volume": np.full(bars, 100.0),
            "funding_rate": np.where(phase % 8 == 0, 0.0001, 0.0),
        },
        index=index,
    )


class StatefulGridFixture:
    """Small Grid/MRS-like Python strategy shared by every certification route."""

    quantbt_reactive_numeric_v1 = True
    quantbt_requirements = StrategyContextRequirements(
        market=("open", "high", "low", "close"),
        account=("equity", "available_equity", "initial_margin", "maintenance_margin", "liquidated"),
        positions=("qty",),
        fills="new_only",
        events="new_only",
        active_orders="snapshot",
        context_mode="numeric",
    )

    def __init__(self) -> None:
        self.callbacks: list[tuple[object, ...]] = []
        self.handles: dict[str, int] = {}
        self.retained_context = None
        self.retained_writer = None

    def initialize(self, context, out) -> None:
        self.callbacks.append(("initialize", context.bar_index, round(context.equity, 10)))

    def on_bar_close(self, context, out) -> None:
        self.callbacks.append(
            (
                "bar",
                context.bar_index,
                round(context.open(0), 10),
                round(context.high(0), 10),
                round(context.low(0), 10),
                round(context.close(0), 10),
                round(context.equity, 10),
                round(context.position_qty(0), 10),
            )
        )
        if context.bar_index == 0:
            self.retained_context = context
            self.retained_writer = out
            self.handles["entry"] = out.market(0, OrderSide.BUY, 1.13, tif="ioc")
        elif context.bar_index == 3:
            self.handles["take_profit"] = out.limit(
                0,
                OrderSide.SELL,
                1.13,
                101.75,
                reduce_only=True,
            )
        elif context.bar_index == 7:
            out.market(0, OrderSide.BUY, 1.13, tif="ioc")
        elif context.bar_index == 11:
            # This may be an already-filled order. The rejection is intentional
            # and exercises control-command lifecycle provenance.
            out.cancel(self.handles["take_profit"])
        elif context.bar_index == 15:
            out.market(0, OrderSide.SELL, 2.26, tif="ioc", reduce_only=True)

    def finalize(self, context, out) -> None:
        self.callbacks.append(("finalize", context.bar_index, round(context.equity, 10)))

    def quantbt_state_fingerprint(self) -> tuple[tuple[object, ...], ...]:
        return tuple(self.callbacks)


def _endpoint(
    *,
    backend: str,
    runtime: str = "legacy_python_loop",
    gil_policy: str = "held_for_session",
    audit_mode: str | None = None,
):
    frame = _frame()
    return QuantBTEndpoint.native_event_strategy(
        initial_capital=20_000.0,
        leverage=4.0,
        maintenance_ratio=0.005,
        fee_rate=0.0004,
        use_funding=True,
        funding_rate=frame["funding_rate"],
        qty_step=0.25,
        min_qty=0.5,
        min_notional=25.0,
        report_level="audit",
        audit_sink="memory",
        reactive_execution_mode="audit",
        reactive_kernel_mode="single_pass",
        reactive_runtime=runtime,
        reactive_gil_policy=gil_policy,
        audit_mode=audit_mode,
        native_backend=backend,
        execution_contract="event_lifecycle_v3_next_open",
    )


def _run(*, backend: str, runtime: str = "legacy_python_loop", gil_policy: str = "held_for_session"):
    frame = _frame()
    strategy = StatefulGridFixture()
    result = _endpoint(backend=backend, runtime=runtime, gil_policy=gil_policy).simulate(
        data=frame,
        strategy=strategy,
        symbols=["BTC"],
    )
    return result, strategy


def _assert_accounting_parity(left, right) -> None:
    for field in ("equity", "positions", "fees", "funding", "margin"):
        np.testing.assert_allclose(
            getattr(left, field).to_numpy(),
            getattr(right, field).to_numpy(),
            rtol=0.0,
            atol=1e-12,
        )
    assert left.liquidated is right.liquidated
    assert left.liquidation_bar == right.liquidation_bar
    left_fills = tuple(left.fills)
    right_fills = tuple(right.fills)
    assert len(left_fills) == len(right_fills)
    for lhs, rhs in zip(left_fills, right_fills):
        assert lhs.timestamp == rhs.timestamp
        assert lhs.order_id == rhs.order_id
        assert lhs.symbol == rhs.symbol
        assert lhs.side == rhs.side
        assert lhs.signed_qty == pytest.approx(rhs.signed_qty, abs=1e-12)
        assert lhs.price == pytest.approx(rhs.price, abs=1e-12)
        assert lhs.fee == pytest.approx(rhs.fee, abs=1e-12)


def _execution_account_trace(trace: pd.DataFrame) -> pd.DataFrame:
    """Keep the backend-neutral accounting portion of a richer static trace."""

    selected = trace.loc[
        trace["event_kind"].isin(("FILL_ACCOUNTING", "ACCOUNT_SNAPSHOT"))
    ].copy()
    selected["sequence"] = np.arange(len(selected), dtype=np.int64)
    return selected.reset_index(drop=True)


def test_r1_four_way_python_bridge_coruntime_and_static_replay_are_exact():
    """A/B/C/D locks callback state, command tape, execution and accounting."""

    python, python_strategy = _run(backend="python")
    bridge, bridge_strategy = _run(backend="rust")
    coruntime, coruntime_strategy = _run(
        backend="rust",
        runtime="numeric_every_bar_v1",
    )

    for result in (bridge, coruntime):
        _assert_accounting_parity(python, result)
        assert compare_canonical_traces(
            python.metadata["canonical_trace_v1"],
            result.metadata["canonical_trace_v1"],
        )["passed"]

    assert python_strategy.quantbt_state_fingerprint() == bridge_strategy.quantbt_state_fingerprint()
    assert python_strategy.quantbt_state_fingerprint() == coruntime_strategy.quantbt_state_fingerprint()

    emitted = coruntime.metadata["emitted_command_tape"]
    assert len(emitted) == 5
    assert all(command.timestamp in _frame().index for command in emitted)
    static = QuantBTEndpoint.native_event_lifecycle(
        initial_capital=20_000.0,
        leverage=4.0,
        maintenance_ratio=0.005,
        fee_rate=0.0004,
        use_funding=True,
        funding_rate=_frame()["funding_rate"],
        qty_step=0.25,
        min_qty=0.5,
        min_notional=25.0,
        report_level="audit",
        audit_sink="memory",
        native_backend="rust",
        execution_contract="event_lifecycle_v3_next_open",
    ).simulate(data=_frame(), order_commands=emitted, symbols=["BTC"])

    _assert_accounting_parity(coruntime, static)
    assert compare_canonical_traces(
        _execution_account_trace(coruntime.metadata["canonical_trace_v1"]),
        _execution_account_trace(static.metadata["canonical_trace_v1"]),
    )["passed"]
    assert coruntime.metadata["reactive_numeric_observability"]["native_entry_calls"] == 1
    assert coruntime.metadata["state_owner"] == "rust"
    assert coruntime.metadata["python_shadow_accounting"] is False
    assert coruntime.metadata["single_pass_replay_certified"] is False


def test_r1_context_writer_are_ephemeral_and_diagnostics_are_truthful():
    result, strategy = _run(backend="rust", runtime="numeric_every_bar_v1")
    observability = result.metadata["reactive_numeric_observability"]

    assert observability["native_entry_calls"] == 1
    assert observability["python_callback_calls"] == len(_frame()) + 2
    assert observability["gil_acquisitions"] == 1
    assert observability["command_writer_python_objects"] == 0
    assert observability["context_pandas_allocations"] == 0
    assert observability["context_dataclass_allocations"] == 0
    assert observability["command_rows_quantized"] >= 1
    assert observability["command_rows"] == 5
    assert result.metadata["quantity_preflight"]["changed_count"] >= 1

    with pytest.raises(RuntimeError, match="no longer valid"):
        _ = strategy.retained_context.equity
    with pytest.raises(RuntimeError, match="only writable during"):
        strategy.retained_writer.market(0, OrderSide.BUY, 1.0)


def test_r1_gil_policy_preserves_parity_and_exposes_real_transition_count():
    held, held_strategy = _run(
        backend="rust",
        runtime="numeric_every_bar_v1",
        gil_policy="held_for_session",
    )
    released, released_strategy = _run(
        backend="rust",
        runtime="numeric_every_bar_v1",
        gil_policy="release_between_callbacks",
    )

    _assert_accounting_parity(held, released)
    assert compare_canonical_traces(
        held.metadata["canonical_trace_v1"],
        released.metadata["canonical_trace_v1"],
    )["passed"]
    assert held_strategy.quantbt_state_fingerprint() == released_strategy.quantbt_state_fingerprint()
    held_observability = held.metadata["reactive_numeric_observability"]
    released_observability = released.metadata["reactive_numeric_observability"]
    assert held_observability["gil_policy"] == "held_for_session"
    assert released_observability["gil_policy"] == "release_between_callbacks"
    assert held_observability["gil_acquisitions"] == 1
    assert released_observability["gil_acquisitions"] > held_observability["gil_acquisitions"]


def test_r1_rejects_hidden_oracle_and_unsupported_sparse_schedule():
    frame = _frame(bars=8)
    with pytest.raises(NotImplementedError, match="exactly one Rust-owned session"):
        _endpoint(
            backend="rust",
            runtime="numeric_every_bar_v1",
            audit_mode="verify_against_oracle",
        ).simulate(
            data=frame,
            strategy=StatefulGridFixture(),
            symbols=["BTC"],
        )

    # Build a second endpoint because Phase 62 must not silently reinterpret
    # a sparse schedule as numeric-every-bar.
    endpoint = QuantBTEndpoint.native_event_strategy(
        initial_capital=20_000.0,
        leverage=4.0,
        fee_rate=0.0004,
        native_backend="rust",
        execution_contract="event_lifecycle_v3_next_open",
        reactive_runtime="numeric_every_bar_v1",
        reactive_kernel_mode="single_pass",
        report_level="minimal",
    )

    class Sparse(StatefulGridFixture):
        quantbt_requirements = StrategyContextRequirements(
            context_mode="numeric",
            callback=CallbackSchedule(every_n_bars=2),
        )

    with pytest.raises(NotImplementedError, match="every_n_bars=1"):
        endpoint.simulate(data=frame, strategy=Sparse(), symbols=["BTC"])


def test_r1_callback_exception_is_wrapped_once_with_location():
    class InvalidCommand(StatefulGridFixture):
        def on_bar_close(self, context, out) -> None:
            if context.bar_index == 0:
                out.market(0, OrderSide.BUY, 0.0)

    with pytest.raises(NativeEventStrategyError, match=r"on_bar_close.*bar_index=0.*qty > 0"):
        _endpoint(backend="rust", runtime="numeric_every_bar_v1").simulate(
            data=_frame(bars=8),
            strategy=InvalidCommand(),
            symbols=["BTC"],
        )


def test_r1_strategy_exception_is_wrapped_once_with_callback_location():
    class Explodes(StatefulGridFixture):
        def on_bar_close(self, context, out) -> None:
            if context.bar_index == 2:
                raise RuntimeError("fixture strategy failure")

    with pytest.raises(
        NativeEventStrategyError,
        match=r"on_bar_close.*bar_index=2.*fixture strategy failure",
    ):
        _endpoint(backend="rust", runtime="numeric_every_bar_v1").simulate(
            data=_frame(bars=8),
            strategy=Explodes(),
            symbols=["BTC"],
        )


def test_r1_direct_runner_reset_reuses_prepared_market_without_state_leakage():
    frame = _frame()
    backend = NativeEventBackend(
        NativeEventConfig(
            account=AccountConfig(initial_capital=20_000.0, leverage=4.0, maintenance_ratio=0.005),
            execution=ExecutionConfig(slippage_bps=0.0),
            fee_rate=0.0004,
            use_funding=True,
            native_backend="rust",
            execution_contract="event_lifecycle_v3_next_open",
            report_level="audit",
        )
    )
    market = backend.prepare_market_arrays(
        frame.index,
        closes={"BTC": frame["close"]},
        highs={"BTC": frame["high"]},
        lows={"BTC": frame["low"]},
        funding_rate={"BTC": frame["funding_rate"]},
        symbols=["BTC"],
    )
    runner = RustReactiveNumericCoRuntime(
        idx=frame.index,
        symbols=["BTC"],
        market_arrays=market,
        opens_arr=np.ascontiguousarray(frame[["open"]].to_numpy(dtype=np.float64)),
        volumes_arr=np.ascontiguousarray(frame[["volume"]].to_numpy(dtype=np.float64)),
        constraints=build_quantity_constraints(
            ["BTC"], qty_step=0.25, min_qty=0.5, min_notional=25.0
        ),
        contract_sizes=np.array([1.0], dtype=np.float64),
        leverages=np.array([4.0], dtype=np.float64),
        fee_rates=np.array([0.0004], dtype=np.float64),
        initial_capital=20_000.0,
        maintenance_ratio=0.005,
        slippage=0.0,
        use_funding=True,
        event_contract="event_lifecycle_v3_next_open",
        requirements=StatefulGridFixture.quantbt_requirements,
        retain_fills=True,
        retain_events=True,
    )
    first, _ = runner.run(StatefulGridFixture())
    runner.reset()
    second, _ = runner.run(StatefulGridFixture())
    np.testing.assert_allclose(first.equity, second.equity, rtol=0.0, atol=1e-12)
    np.testing.assert_allclose(first.positions, second.positions, rtol=0.0, atol=1e-12)
    np.testing.assert_allclose(first.fees, second.fees, rtol=0.0, atol=1e-12)
    assert first.fill_count == second.fill_count
    assert first.event_count == second.event_count
    runner.release_excess_capacity(8)


def test_r1_direct_runner_rejects_command_capacity_exhaustion_deterministically():
    class CapacityFixture(StatefulGridFixture):
        def on_bar_close(self, context, out) -> None:
            if context.bar_index == 0:
                out.market(0, OrderSide.BUY, 1.0)
                out.market(0, OrderSide.BUY, 1.0)

    frame = _frame(bars=8)
    backend = NativeEventBackend(
        NativeEventConfig(
            account=AccountConfig(initial_capital=20_000.0, leverage=4.0),
            execution=ExecutionConfig(slippage_bps=0.0),
            fee_rate=0.0004,
            native_backend="rust",
            execution_contract="event_lifecycle_v3_next_open",
        )
    )
    market = backend.prepare_market_arrays(
        frame.index,
        closes={"BTC": frame["close"]},
        highs={"BTC": frame["high"]},
        lows={"BTC": frame["low"]},
        symbols=["BTC"],
    )
    runner = RustReactiveNumericCoRuntime(
        idx=frame.index,
        symbols=["BTC"],
        market_arrays=market,
        opens_arr=np.ascontiguousarray(frame[["open"]].to_numpy(dtype=np.float64)),
        volumes_arr=np.ascontiguousarray(frame[["volume"]].to_numpy(dtype=np.float64)),
        constraints=build_quantity_constraints(["BTC"]),
        contract_sizes=np.array([1.0], dtype=np.float64),
        leverages=np.array([4.0], dtype=np.float64),
        fee_rates=np.array([0.0004], dtype=np.float64),
        initial_capital=20_000.0,
        maintenance_ratio=0.005,
        slippage=0.0,
        use_funding=False,
        event_contract="event_lifecycle_v3_next_open",
        requirements=StatefulGridFixture.quantbt_requirements,
        retain_fills=False,
        retain_events=False,
        command_initial_capacity=1,
        command_hard_limit=1,
    )
    with pytest.raises(RuntimeError, match="command capacity exceeded: 1"):
        runner.run(CapacityFixture())
    assert runner.poisoned is True
