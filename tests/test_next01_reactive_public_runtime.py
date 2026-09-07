"""NEXT-01 public reactive callback, audit, and lifetime locks.

These tests exercise the ordinary Python callback route.  They deliberately do
not use the opt-in numeric/Rust co-runtime as a substitute for compatibility
strategy behavior.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from quantbt import (
    CallbackSchedule,
    OrderCommand,
    OrderSide,
    OrderType,
    QuantBTEndpoint,
    StrategyContextRequirements,
    TimeInForce,
)
from quantbt.core.execution_trace import TraceReplayer, build_canonical_execution_trace
from quantbt.strategies.driver import PreparedStrategyAdapter


def _frame(bars: int = 9) -> pd.DataFrame:
    index = pd.date_range("2026-09-07", periods=bars, freq="h", tz="UTC")
    close = 100.0 + np.arange(bars, dtype=np.float64)
    open_ = np.r_[close[0], close[:-1]]
    return pd.DataFrame(
        {
            "open": open_,
            "high": np.maximum(open_, close) + 0.75,
            "low": np.minimum(open_, close) - 0.75,
            "close": close,
            "volume": np.full(bars, 100.0),
        },
        index=index,
    )


def _endpoint(*, report_level: str = "audit"):
    return QuantBTEndpoint.native_event_strategy(
        initial_capital=20_000.0,
        leverage=3.0,
        maintenance_ratio=0.005,
        fee_rate=0.0004,
        use_funding=False,
        report_level=report_level,
        audit_sink="memory",
        native_backend="python",
        reactive_kernel_mode="single_pass",
        execution_contract="event_lifecycle_v3_next_open",
    )


class _DynamicReplacementStrategy:
    def __init__(self) -> None:
        self.calls: list[tuple[str, int]] = []
        self.retained_context = None
        self.raw_timestamp = None

    def on_bar_close(self, context):
        self.calls.append(("original", int(context.bar_index)))
        if context.bar_index == 0:
            self.retained_context = context
            self.raw_timestamp = object.__getattribute__(context, "timestamp")

            def replacement(next_context):
                self.calls.append(("replacement", int(next_context.bar_index)))
                if next_context.bar_index == 1:
                    return (
                        OrderCommand(
                            timestamp=next_context.timestamp,
                            symbol="BTC",
                            side=OrderSide.BUY,
                            order_type=OrderType.MARKET,
                            qty=1.0,
                            tif=TimeInForce.IOC,
                            order_id="dynamic-entry",
                        ),
                    )
                return ()

            self.on_bar_close = replacement
        return ()


class _PinnedReplacementStrategy(_DynamicReplacementStrategy):
    quantbt_reactive_callback_binding_v1 = "run_stable"


def test_dynamic_callback_replacement_and_lazy_timestamp_snapshot_are_preserved():
    frame = _frame()
    strategy = _DynamicReplacementStrategy()
    result = _endpoint().simulate(data=frame, strategy=strategy, symbols=["BTC"])

    assert strategy.calls[0] == ("original", 0)
    assert strategy.calls[1:] == [("replacement", bar) for bar in range(1, len(frame))]
    assert isinstance(strategy.raw_timestamp, (int, np.integer))
    assert strategy.retained_context.timestamp == frame.index[0]
    assert isinstance(strategy.retained_context.timestamp, pd.Timestamp)
    assert result.metadata["strategy_boundary"]["callback_binding_mode"] == "dynamic_compatibility_v1"
    assert result.metadata["strategy_boundary"]["callback_dynamic_lookup_count"] == len(frame) + 2
    assert result.metadata["strategy_boundary"]["callback_plan_compile_lookup_count"] == 0
    counters = result.metadata["execution_counters"]
    assert counters["timestamp_contexts_deferred"] == len(frame) + 1
    assert counters["timestamp_objects_materialized_during_run"] == 1
    assert [fill.order_id for fill in result.fills] == ["dynamic-entry"]


def test_explicit_run_stable_callback_binding_pins_only_the_opt_in_strategy():
    frame = _frame()
    strategy = _PinnedReplacementStrategy()
    result = _endpoint(report_level="minimal").simulate(data=frame, strategy=strategy, symbols=["BTC"])

    assert strategy.calls == [("original", bar) for bar in range(len(frame))]
    boundary = result.metadata["strategy_boundary"]
    assert boundary["callback_binding_mode"] == "run_stable_pinned_v1"
    assert boundary["callback_dynamic_lookup_count"] == 0
    assert boundary["callback_plan_compile_lookup_count"] == 3
    assert not result.fills


def test_declared_sparse_callback_skips_context_and_dynamic_lookup_until_a_real_wake():
    class SparseDynamic:
        quantbt_requirements = StrategyContextRequirements(
            market=("close",),
            account=("equity", "liquidated"),
            positions=(),
            fills="none",
            events="none",
            active_orders="none",
            callback=CallbackSchedule(
                every_n_bars=None,
                explicit_bars=(0, 5),
                on_fill=False,
                on_order_event=False,
                on_liquidation=False,
            ),
            context_mode="compatibility",
        )

        def __init__(self) -> None:
            self.calls: list[tuple[str, int]] = []

        def on_bar_close(self, context):
            self.calls.append(("original", int(context.bar_index)))
            if context.bar_index == 0:
                self.on_bar_close = self._replacement
            return ()

        def _replacement(self, context):
            self.calls.append(("replacement", int(context.bar_index)))
            return ()

    frame = _frame()
    strategy = SparseDynamic()
    result = _endpoint(report_level="minimal").simulate(data=frame, strategy=strategy, symbols=["BTC"])

    assert strategy.calls == [("original", 0), ("replacement", 5)]
    boundary = result.metadata["strategy_boundary"]
    assert boundary["python_callbacks"] == 2
    assert boundary["skipped_callbacks"] == len(frame) - 2
    assert boundary["callback_dynamic_lookup_count"] == 4  # initialize, two wakes, finalize
    assert boundary["callback_schedule_check_count"] == len(frame)
    assert boundary["callback_suppressed_without_lookup_count"] == len(frame) - 2
    counters = result.metadata["execution_counters"]
    # initialize, the two declared wakes, plus terminal context for finalize.
    assert counters["contexts_materialized"] == 4


def test_direct_column_replay_matches_public_dataframe_replay_exactly():
    class Bracket:
        def on_bar_close(self, context):
            if context.bar_index == 0:
                return (
                    OrderCommand(
                        timestamp=context.timestamp,
                        symbol="BTC",
                        side=OrderSide.BUY,
                        order_type=OrderType.MARKET,
                        qty=1.0,
                        tif=TimeInForce.IOC,
                        order_id="entry",
                    ),
                )
            if context.bar_index == 3:
                return (
                    OrderCommand(
                        timestamp=context.timestamp,
                        symbol="BTC",
                        side=OrderSide.SELL,
                        order_type=OrderType.MARKET,
                        qty=1.0,
                        reduce_only=True,
                        tif=TimeInForce.IOC,
                        order_id="exit",
                    ),
                )
            return ()

    result = _endpoint().simulate(data=_frame(), strategy=Bracket(), symbols=["BTC"])
    artifact = build_canonical_execution_trace(result)
    assert artifact.column_store is not None
    direct = TraceReplayer().replay_columns(artifact.column_store)
    dataframe = TraceReplayer().replay(artifact.trace)
    assert direct == dataframe
    assert result.metadata["canonical_trace_replay_v1"]["passed"]


def test_invalid_callback_binding_marker_fails_before_financial_mutation():
    class Invalid:
        quantbt_reactive_callback_binding_v1 = "sometimes"

    with pytest.raises(ValueError, match="run_stable"):
        PreparedStrategyAdapter.prepare(Invalid())
