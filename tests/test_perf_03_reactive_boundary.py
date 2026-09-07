"""PERF-03 reactive callback-boundary and command-staging certification.

The numeric co-runtime remains hybrid: Python owns strategy state and Rust owns
the clock/account. These tests pin the boundary optimizations to A/B/C/D
economic parity while making dynamic Python callback mutation an explicit
compatibility route.
"""

from __future__ import annotations

import importlib.util

import numpy as np
import pandas as pd
import pytest

from quantbt import (
    AccountConfig,
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
from quantbt.strategies import BlockPlanV1, WakePlanV1


pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("_quantbt_native") is None,
    reason="quantbt-native extension is not installed in this environment",
)


REQUIREMENTS = StrategyContextRequirements(
    market=("open", "high", "low", "close"),
    account=("equity", "available_equity"),
    positions=("qty",),
    fills="new_only",
    events="new_only",
    active_orders="none",
    context_mode="numeric",
)


def _frame(*, bars: int = 24) -> pd.DataFrame:
    index = pd.date_range("2026-10-01", periods=bars, freq="1h", tz="UTC")
    phase = np.arange(bars, dtype=np.float64)
    close = 100.0 + 0.2 * phase + 0.7 * np.sin(phase / 3.0)
    open_ = np.r_[close[0], close[:-1]]
    return pd.DataFrame(
        {
            "open": open_,
            "high": np.maximum(open_, close) + 0.5,
            "low": np.minimum(open_, close) - 0.5,
            "close": close,
            "volume": np.full(bars, 100.0),
            "funding_rate": np.where(phase % 8 == 0, 0.0001, 0.0),
        },
        index=index,
    )


def _endpoint(*, backend: str, runtime: str = "legacy_python_loop") -> QuantBTEndpoint:
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
        native_backend=backend,
        reactive_kernel_mode="single_pass",
        reactive_runtime=runtime,
        execution_contract="event_lifecycle_v3_next_open",
        execution=ExecutionConfig(slippage_bps=0.0),
    )


class _BoundaryStrategy:
    quantbt_reactive_numeric_v1 = True
    quantbt_requirements = REQUIREMENTS

    def __init__(self) -> None:
        self.calls: list[tuple[str, int, float]] = []

    def initialize(self, context, out) -> None:
        self.calls.append(("initialize", int(context.bar_index), float(context.equity)))

    def on_bar_close(self, context, out) -> None:
        bar = int(context.bar_index)
        # Exercise numeric getters without changing the economic decision.
        _ = context.open(0) + context.high(0) + context.low(0) + context.close(0)
        _ = context.equity + context.available_equity + context.position_qty(0)
        self.calls.append(("bar", bar, float(context.close(0))))
        if bar == 0:
            out.market(0, OrderSide.BUY, 1.0, tif="ioc")
        elif bar == 8:
            out.market(0, OrderSide.SELL, 1.0, tif="ioc", reduce_only=True)

    def finalize(self, context, out) -> None:
        self.calls.append(("finalize", int(context.bar_index), float(context.equity)))

    def quantbt_state_fingerprint(self):
        return tuple(self.calls)


class _PinnedBoundaryStrategy(_BoundaryStrategy):
    # The strategy explicitly promises not to monkey-patch lifecycle methods
    # while this run is active. The co-runtime can bind them once.
    quantbt_reactive_callback_binding_v1 = "run_stable"


def _run(strategy, *, backend: str, runtime: str = "legacy_python_loop"):
    return _endpoint(backend=backend, runtime=runtime).simulate(
        data=_frame(), strategy=strategy, symbols=["BTC"]
    )


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


def _assert_trace_parity(left, right) -> None:
    assert compare_canonical_traces(
        left.metadata["canonical_trace_v1"], right.metadata["canonical_trace_v1"]
    )["passed"]


def _execution_account_trace(trace: pd.DataFrame) -> pd.DataFrame:
    result = trace.loc[
        trace["event_kind"].isin(("FILL_ACCOUNTING", "ACCOUNT_SNAPSHOT"))
    ].copy()
    result["sequence"] = np.arange(len(result), dtype=np.int64)
    return result.reset_index(drop=True)


def test_perf03_four_way_parity_and_pinned_callback_plan():
    """A/B/C/D stays exact while run-stable binding removes dynamic lookup."""

    python_strategy = _BoundaryStrategy()
    bridge_strategy = _BoundaryStrategy()
    dynamic_strategy = _BoundaryStrategy()
    pinned_strategy = _PinnedBoundaryStrategy()
    oracle = _run(python_strategy, backend="python")
    bridge = _run(bridge_strategy, backend="rust")
    optimized_dynamic = _run(
        dynamic_strategy, backend="rust", runtime="numeric_every_bar_v1"
    )
    optimized_pinned = _run(
        pinned_strategy, backend="rust", runtime="numeric_every_bar_v1"
    )

    for candidate in (bridge, optimized_dynamic, optimized_pinned):
        _assert_accounting_parity(oracle, candidate)
        _assert_trace_parity(oracle, candidate)
    assert python_strategy.quantbt_state_fingerprint() == bridge_strategy.quantbt_state_fingerprint()
    assert python_strategy.quantbt_state_fingerprint() == dynamic_strategy.quantbt_state_fingerprint()
    assert python_strategy.quantbt_state_fingerprint() == pinned_strategy.quantbt_state_fingerprint()

    dynamic_obs = optimized_dynamic.metadata["reactive_numeric_observability"]
    pinned_obs = optimized_pinned.metadata["reactive_numeric_observability"]
    assert dynamic_obs["callback_binding_mode"] == "dynamic_compatibility_v1"
    assert dynamic_obs["callback_dynamic_lookup_count"] == dynamic_obs["python_callback_calls"]
    assert pinned_obs["callback_binding_mode"] == "run_stable_pinned_v1"
    assert pinned_obs["callback_dynamic_lookup_count"] == 0
    assert pinned_obs["callback_plan_compile_lookup_count"] == 5
    assert pinned_obs["context_getter_calls"] > pinned_obs["python_callback_calls"]
    assert pinned_obs["command_writer_calls"] == 2
    assert pinned_obs["command_callbacks_completed"] == pinned_obs["python_callback_calls"]

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
    ).simulate(
        data=_frame(),
        order_commands=optimized_pinned.metadata["emitted_command_tape"],
        symbols=["BTC"],
    )
    _assert_accounting_parity(optimized_pinned, static)
    assert compare_canonical_traces(
        _execution_account_trace(optimized_pinned.metadata["canonical_trace_v1"]),
        _execution_account_trace(static.metadata["canonical_trace_v1"]),
    )["passed"]


def test_perf03_dynamic_callback_mutation_keeps_compatibility_route():
    """No opt-in means per-bar getattr still observes a Python monkey patch."""

    class DynamicMutation:
        quantbt_reactive_numeric_v1 = True
        quantbt_requirements = REQUIREMENTS

        def __init__(self) -> None:
            self.calls: list[tuple[str, int]] = []

        def on_bar_close(self, context, out) -> None:
            self.calls.append(("before", int(context.bar_index)))
            if context.bar_index == 0:
                self.on_bar_close = self._after  # type: ignore[method-assign]

        def _after(self, context, out) -> None:
            self.calls.append(("after", int(context.bar_index)))

    strategy = DynamicMutation()
    result = _run(strategy, backend="rust", runtime="numeric_every_bar_v1")
    assert strategy.calls[0] == ("before", 0)
    assert all(label == "after" for label, _ in strategy.calls[1:])
    observability = result.metadata["reactive_numeric_observability"]
    assert observability["callback_binding_mode"] == "dynamic_compatibility_v1"
    assert observability["callback_dynamic_lookup_count"] == len(_frame()) + 2


def test_perf03_silent_every_bar_callback_still_advances_private_state():
    """No emitted command is never evidence that an every-bar callback is idle."""

    class StatefulNoOrderPrefix:
        quantbt_reactive_numeric_v1 = True
        quantbt_requirements = REQUIREMENTS

        def __init__(self) -> None:
            self.counter = 0

        def on_bar_close(self, context, out) -> None:
            self.counter += 1
            if context.bar_index == 7 and self.counter == 8:
                out.market(0, OrderSide.BUY, 1.0)

    strategy = StatefulNoOrderPrefix()
    result = _run(strategy, backend="rust", runtime="numeric_every_bar_v1")
    assert strategy.counter == len(_frame())
    assert result.metadata["reactive_numeric_observability"]["python_callback_calls"] == len(_frame())
    assert result.metadata["reactive_numeric_observability"]["command_rows"] == 1
    assert result.positions.iloc[-1, 0] == pytest.approx(1.0)


def test_perf03_future_ohlc_suffix_cannot_change_prior_effective_command():
    """A next-open order cannot observe a later bar's high/low range."""

    class FirstBarIntent:
        quantbt_reactive_numeric_v1 = True
        quantbt_requirements = REQUIREMENTS

        def __init__(self) -> None:
            self.first_observation: tuple[float, float, float, float] | None = None

        def on_bar_close(self, context, out) -> None:
            if context.bar_index == 0:
                self.first_observation = (
                    context.open(0),
                    context.high(0),
                    context.low(0),
                    context.close(0),
                )
                out.market(0, OrderSide.BUY, 1.0)

    baseline = _frame()
    perturbed = baseline.copy()
    # Keep all bar-0 and open/close values unchanged. The altered intrabar
    # suffix would be a look-ahead leak if it could change the bar-0 decision.
    perturbed.loc[perturbed.index[1]:, "high"] += 50_000.0
    perturbed.loc[perturbed.index[1]:, "low"] -= 50_000.0

    left_strategy = FirstBarIntent()
    right_strategy = FirstBarIntent()
    left = _endpoint(backend="rust", runtime="numeric_every_bar_v1").simulate(
        data=baseline, strategy=left_strategy, symbols=["BTC"]
    )
    right = _endpoint(backend="rust", runtime="numeric_every_bar_v1").simulate(
        data=perturbed, strategy=right_strategy, symbols=["BTC"]
    )
    assert left_strategy.first_observation == right_strategy.first_observation
    _assert_accounting_parity(left, right)
    _assert_trace_parity(left, right)
    assert len(left.metadata["emitted_command_tape"]) == len(right.metadata["emitted_command_tape"]) == 1


def test_perf03_run_stable_plan_preserves_r2_and_r3_economics():
    """The shared access plan is exercised by sparse and block runtimes too."""

    class SparsePlan:
        quantbt_reactive_sparse_v1 = True
        quantbt_sparse_shadow_certified_v1 = True
        quantbt_requirements = REQUIREMENTS

        def on_wake(self, context, out):
            if context.bar_index == 0:
                out.market(0, OrderSide.BUY, 1.0)
                return WakePlanV1(next_bar=8)
            if context.bar_index == 8:
                out.market(0, OrderSide.SELL, 1.0, reduce_only=True)
            return WakePlanV1()

    class BlockPlan:
        quantbt_reactive_block_intent_v1 = True
        quantbt_block_shadow_certified_v1 = True
        quantbt_requirements = REQUIREMENTS

        def next_block(self, context, start_bar, max_stop_bar, out):
            if context.bar_index == 0:
                out.market(0, OrderSide.BUY, 1.0, effective_bar=start_bar)
                out.market(0, OrderSide.SELL, 1.0, effective_bar=8, reduce_only=True)
            return BlockPlanV1(stop_bar=max_stop_bar, invalidate_on_fill=False)

    for runtime, factory in (
        ("numeric_sparse_wake_v1", SparsePlan),
        ("numeric_block_intent_v1", BlockPlan),
    ):
        dynamic = _run(factory(), backend="rust", runtime=runtime)
        pinned = factory()
        pinned.quantbt_reactive_callback_binding_v1 = "run_stable"
        optimized = _run(pinned, backend="rust", runtime=runtime)
        _assert_accounting_parity(dynamic, optimized)
        _assert_trace_parity(dynamic, optimized)
        assert (
            optimized.metadata["reactive_numeric_observability"]["callback_binding_mode"]
            == "run_stable_pinned_v1"
        )
        assert (
            optimized.metadata["reactive_numeric_observability"]["callback_dynamic_lookup_count"]
            == 0
        )


def _direct_runner(*, command_initial_capacity: int = 2, command_hard_limit: int = 8):
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
        funding_rate={"BTC": frame["funding_rate"]},
        symbols=["BTC"],
    )
    return RustReactiveNumericCoRuntime(
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
        requirements=REQUIREMENTS,
        retain_fills=True,
        retain_events=True,
        command_initial_capacity=command_initial_capacity,
        command_hard_limit=command_hard_limit,
    )


def test_perf03_exception_discards_unsubmitted_staged_rows_and_requires_reset():
    class WritesThenRaises:
        quantbt_reactive_numeric_v1 = True
        quantbt_requirements = REQUIREMENTS

        def on_bar_close(self, context, out) -> None:
            if context.bar_index == 0:
                out.market(0, OrderSide.BUY, 1.0)
                raise RuntimeError("stop after staging")

    runner = _direct_runner()
    with pytest.raises(RuntimeError, match="stop after staging"):
        runner.run(WritesThenRaises())
    diagnostics = runner.session_diagnostics()
    assert diagnostics["poisoned"] is True
    assert diagnostics["last_callback_state_dirty"] is True
    assert diagnostics["last_callback_staged_rows_discarded"] == 1
    assert diagnostics["scheduled_command_buckets"] == 0

    runner.reset()
    recovered, _ = runner.run(_BoundaryStrategy())
    assert recovered.fill_count == 1
    assert runner.session_diagnostics()["poisoned"] is False


def test_perf03_invalid_return_and_envelope_discard_the_entire_staged_batch():
    class WritesThenReturnsValue:
        quantbt_reactive_numeric_v1 = True
        quantbt_requirements = REQUIREMENTS

        def on_bar_close(self, context, out):
            if context.bar_index == 0:
                out.market(0, OrderSide.BUY, 1.0)
                return "not-none"

    class WritesInvalidEnvelope:
        quantbt_reactive_numeric_v1 = True
        quantbt_requirements = REQUIREMENTS

        def on_bar_close(self, context, out):
            if context.bar_index == 0:
                out.market(0, OrderSide.BUY, 1.0)
                out.market(0, OrderSide.BUY, 1.0, effective_bar=0)

    for strategy, error in (
        (WritesThenReturnsValue(), "return None"),
        (WritesInvalidEnvelope(), "must be after its callback bar"),
    ):
        runner = _direct_runner()
        with pytest.raises(Exception, match=error):
            runner.run(strategy)
        diagnostics = runner.session_diagnostics()
        assert diagnostics["poisoned"] is True
        assert diagnostics["last_callback_state_dirty"] is True
        assert diagnostics["scheduled_command_buckets"] == 0
        assert diagnostics["last_callback_staged_rows_discarded"] in {1, 2}


def test_perf03_business_rejection_remains_per_command_not_callback_atomicity():
    class MixedAdmission:
        quantbt_reactive_numeric_v1 = True
        quantbt_reactive_callback_binding_v1 = "run_stable"
        quantbt_requirements = REQUIREMENTS

        def on_bar_close(self, context, out) -> None:
            if context.bar_index == 0:
                # Accepted writer row but a business-level quantity rejection.
                out.market(0, OrderSide.BUY, 0.1)
                out.market(0, OrderSide.BUY, 1.0)

    result = _run(MixedAdmission(), backend="rust", runtime="numeric_every_bar_v1")
    obs = result.metadata["reactive_numeric_observability"]
    assert obs["callback_state_dirty"] is False
    assert obs["command_staged_rows_discarded"] == 0
    assert obs["command_rows"] == 2
    assert obs["command_rows_dropped"] == 1
    assert len(result.metadata["emitted_command_tape"]) == 1
    assert result.positions.iloc[-1, 0] == pytest.approx(1.0)


def test_perf03_absent_optional_lifecycle_callbacks_do_not_materialize_context():
    class EveryBarOnly:
        quantbt_reactive_numeric_v1 = True
        quantbt_requirements = REQUIREMENTS

        def on_bar_close(self, context, out) -> None:
            _ = context.close(0)

    result = _run(EveryBarOnly(), backend="rust", runtime="numeric_every_bar_v1")
    obs = result.metadata["reactive_numeric_observability"]
    assert obs["python_callback_calls"] == len(_frame())
    assert obs["context_projection_count"] == len(_frame())
    assert obs["context_getter_calls"] >= len(_frame())
