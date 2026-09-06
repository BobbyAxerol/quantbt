"""Phase 63 R2/R3 sparse and block-intent co-runtime certification.

The tests intentionally use one compact market fixture.  They compare the
Rust-owned execution/accounting trace with an every-bar oracle where a sparse
decision boundary is declared, and separately assert the R3 future-command
invalidation semantics.  R3B receives its own candidate-isolation suite once
the batch runner is wired below this phase's shared protocol.
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
from quantbt.core.execution_trace import compare_canonical_traces
from quantbt.core.constraints import build_quantity_constraints
from quantbt.backends._native_event_rust import (
    RustReactiveCandidateBatchCoRuntime,
)
from quantbt.strategies import (
    BlockPlanV1,
    CandidateErrorCodeV1,
    CandidateWakePlansV1,
    certify_reactive_shadow_v1,
    EquityThresholdV1,
    MarginMetricV1,
    MarginThresholdV1,
    PositionThresholdV1,
    PriceCrossConditionV1,
    WakePlanV1,
    WakeReasonV1,
)


pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("_quantbt_native") is None,
    reason="quantbt-native extension is not installed in this environment",
)


def _frame(*, bars: int = 12) -> pd.DataFrame:
    index = pd.date_range("2026-09-01", periods=bars, freq="1h", tz="UTC")
    close = 100.0 + np.arange(bars, dtype=np.float64)
    return pd.DataFrame(
        {
            "open": np.r_[close[0], close[:-1]],
            "high": close + 0.75,
            "low": close - 0.75,
            "close": close,
            "volume": np.full(bars, 100.0),
            "funding_rate": np.where(np.arange(bars) == 6, 0.0001, 0.0),
        },
        index=index,
    )


_NUMERIC_REQUIREMENTS = StrategyContextRequirements(
    market=("open", "high", "low", "close"),
    account=("equity", "available_equity", "initial_margin", "maintenance_margin", "liquidated"),
    positions=("qty",),
    fills="new_only",
    events="new_only",
    active_orders="snapshot",
    context_mode="numeric",
)


def _endpoint(*, runtime: str, report_level: str = "audit"):
    frame = _frame()
    return QuantBTEndpoint.native_event_strategy(
        initial_capital=20_000.0,
        leverage=3.0,
        maintenance_ratio=0.005,
        fee_rate=0.0004,
        use_funding=True,
        funding_rate=frame["funding_rate"],
        report_level=report_level,
        audit_sink="memory",
        reactive_execution_mode="audit",
        reactive_kernel_mode="single_pass",
        reactive_runtime=runtime,
        native_backend="rust",
        execution_contract="event_lifecycle_v3_next_open",
        execution=ExecutionConfig(slippage_bps=0.0),
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


class EveryBarSparseOracle:
    """Oracle invokes every bar but changes intent only at certified wakes."""

    quantbt_reactive_numeric_v1 = True
    quantbt_requirements = _NUMERIC_REQUIREMENTS

    def __init__(self) -> None:
        self.decisions: list[tuple[int, int]] = []

    def on_bar_close(self, context, out) -> None:
        if context.bar_index == 0:
            self.decisions.append((context.bar_index, int(WakeReasonV1.INITIAL)))
            out.market(0, OrderSide.BUY, 1.0)
        elif context.bar_index == 4:
            self.decisions.append((context.bar_index, int(WakeReasonV1.TIME)))
            out.market(0, OrderSide.SELL, 1.0, reduce_only=True)

    def quantbt_state_fingerprint(self):
        return tuple(self.decisions)


class SparseWakeFixture:
    quantbt_reactive_sparse_v1 = True
    quantbt_sparse_shadow_certified_v1 = True
    quantbt_requirements = _NUMERIC_REQUIREMENTS

    def __init__(self) -> None:
        self.wakes: list[tuple[int, int, float, float]] = []

    def on_wake(self, context, out) -> WakePlanV1:
        reason = int(context.wake_reason_mask)
        self.wakes.append((context.bar_index, reason, context.equity, context.position_qty(0)))
        if context.bar_index == 0:
            out.market(0, OrderSide.BUY, 1.0)
            # The entry fills at bar 1. Time/fill/order-event must coalesce to
            # one callback at that exact post-lifecycle boundary.
            return WakePlanV1(next_bar=1, on_fill=True, on_order_event=True)
        if context.bar_index == 1:
            return WakePlanV1(next_bar=4, on_fill=True, on_order_event=True)
        if context.bar_index == 4:
            out.market(0, OrderSide.SELL, 1.0, reduce_only=True)
            return WakePlanV1(on_fill=True, on_order_event=True)
        return WakePlanV1()

    def quantbt_state_fingerprint(self):
        return tuple((bar, reason) for bar, reason, _, _ in self.wakes)


def test_r2_sparse_wake_matches_every_bar_oracle_at_declared_decisions():
    frame = _frame()
    oracle = EveryBarSparseOracle()
    sparse = SparseWakeFixture()
    oracle_result = _endpoint(runtime="numeric_every_bar_v1").simulate(
        data=frame,
        strategy=oracle,
        symbols=["BTC"],
    )
    sparse_result = _endpoint(runtime="numeric_sparse_wake_v1").simulate(
        data=frame,
        strategy=sparse,
        symbols=["BTC"],
    )

    _assert_accounting_parity(oracle_result, sparse_result)
    assert compare_canonical_traces(
        oracle_result.metadata["canonical_trace_v1"],
        sparse_result.metadata["canonical_trace_v1"],
    )["passed"]
    certificate = certify_reactive_shadow_v1(
        every_bar_result=oracle_result,
        optimized_result=sparse_result,
        every_bar_decision_trace=oracle.quantbt_state_fingerprint(),
        optimized_decision_trace=tuple(
            (bar, reason)
            for bar, reason, _, _ in sparse.wakes
            if bar in {0, 4}
        ),
    )
    assert certificate.execution_trace_equal
    assert certificate.command_trace_equal
    assert sparse_result.metadata["reactive_runtime"] == "numeric_sparse_wake_v1"
    observability = sparse_result.metadata["reactive_numeric_observability"]
    assert observability["python_callback_calls"] < observability["bars_processed"]
    wake_trace = observability["wake_trace"]
    assert wake_trace["bar"].tolist()[:3] == [0, 1, 4]
    assert int(wake_trace.loc[wake_trace["bar"] == 1, "reason_mask"].iloc[0]) & int(WakeReasonV1.TIME)
    assert int(wake_trace.loc[wake_trace["bar"] == 1, "reason_mask"].iloc[0]) & int(WakeReasonV1.FILL)
    assert int(wake_trace.loc[wake_trace["bar"] == 1, "reason_mask"].iloc[0]) & int(WakeReasonV1.ORDER_EVENT)
    assert [row[0] for row in sparse.wakes] == [0, 1, 4, 5]


def test_r2_rejects_inexact_timestamp_and_missing_shadow_certification():
    frame = _frame()

    class InvalidTimestamp(SparseWakeFixture):
        def on_wake(self, context, out):
            return WakePlanV1(next_timestamp_ns=context.timestamp_ns + 1)

    with pytest.raises(Exception, match="exact prepared market bar"):
        _endpoint(runtime="numeric_sparse_wake_v1").simulate(
            data=frame,
            strategy=InvalidTimestamp(),
            symbols=["BTC"],
        )

    class Uncertified(SparseWakeFixture):
        quantbt_sparse_shadow_certified_v1 = False

    with pytest.raises(TypeError, match="shadow parity"):
        _endpoint(runtime="numeric_sparse_wake_v1").simulate(
            data=frame,
            strategy=Uncertified(),
            symbols=["BTC"],
        )


class MultiConditionSparseFixture:
    quantbt_reactive_sparse_v1 = True
    quantbt_sparse_shadow_certified_v1 = True
    quantbt_requirements = _NUMERIC_REQUIREMENTS

    def __init__(self) -> None:
        self.wakes: list[tuple[int, int]] = []

    def on_wake(self, context, out) -> WakePlanV1:
        self.wakes.append((context.bar_index, int(context.wake_reason_mask)))
        if context.bar_index == 0:
            out.market(0, OrderSide.BUY, 1.0)
        return WakePlanV1(
            on_funding=True,
            price_crosses=(PriceCrossConditionV1(0, 102.5, "up"),),
            position_thresholds=(PositionThresholdV1(0, 0.5, "up"),),
            equity_thresholds=(EquityThresholdV1(20_000.5, "up"),),
            margin_thresholds=(
                MarginThresholdV1(MarginMetricV1.INITIAL_MARGIN, 10.0, "up"),
            ),
        )


def test_r2_evaluates_all_declared_engine_level_wake_conditions():
    result = _endpoint(runtime="numeric_sparse_wake_v1").simulate(
        data=_frame(),
        strategy=MultiConditionSparseFixture(),
        symbols=["BTC"],
    )
    wake_trace = result.metadata["reactive_numeric_observability"]["wake_trace"]
    masks = dict(zip(wake_trace["bar"].astype(int), wake_trace["reason_mask"].astype(int)))
    assert masks[0] == int(WakeReasonV1.INITIAL)
    assert masks[1] & int(WakeReasonV1.POSITION_THRESHOLD)
    assert masks[1] & int(WakeReasonV1.EQUITY_THRESHOLD)
    assert masks[1] & int(WakeReasonV1.MARGIN_THRESHOLD)
    assert any(mask & int(WakeReasonV1.PRICE_CROSS) for mask in masks.values())
    assert any(mask & int(WakeReasonV1.FUNDING) for mask in masks.values())


def test_r2_replaces_rather_than_merges_the_prior_wake_plan():
    """A later plan must remove, not accidentally retain, old triggers."""

    class ReplacePlanFixture:
        quantbt_reactive_sparse_v1 = True
        quantbt_sparse_shadow_certified_v1 = True
        quantbt_requirements = _NUMERIC_REQUIREMENTS

        def on_wake(self, context, out) -> WakePlanV1:
            if context.bar_index == 0:
                # This funding trigger is intentionally superseded at bar 1.
                return WakePlanV1(next_bar=1, on_funding=True)
            if context.bar_index == 1:
                return WakePlanV1(next_bar=4)
            return WakePlanV1()

    result = _endpoint(runtime="numeric_sparse_wake_v1").simulate(
        data=_frame(),
        strategy=ReplacePlanFixture(),
        symbols=["BTC"],
    )
    wake_trace = result.metadata["reactive_numeric_observability"]["wake_trace"]
    assert wake_trace["bar"].astype(int).tolist() == [0, 1, 4]
    assert not any(
        int(mask) & int(WakeReasonV1.FUNDING)
        for mask in wake_trace.loc[wake_trace["bar"] > 1, "reason_mask"].tolist()
    )


def test_r2_coalesces_fill_order_event_and_liquidation_on_one_boundary():
    """Lifecycle collisions must create one wake with every declared reason."""

    frame = _frame(bars=5)
    frame.loc[frame.index[1]:, ["open", "high", "low", "close"]] = (100.0, 101.0, 1.0, 1.0)

    class LiquidationFixture:
        quantbt_reactive_sparse_v1 = True
        quantbt_sparse_shadow_certified_v1 = True
        quantbt_requirements = _NUMERIC_REQUIREMENTS

        def on_wake(self, context, out) -> WakePlanV1:
            if context.bar_index == 0:
                out.market(0, OrderSide.BUY, 500.0)
                return WakePlanV1(on_fill=True, on_order_event=True, on_liquidation=True)
            return WakePlanV1()

    result = _endpoint(runtime="numeric_sparse_wake_v1").simulate(
        data=frame,
        strategy=LiquidationFixture(),
        symbols=["BTC"],
    )
    assert result.liquidated
    # Public results retain the full input clock after a native early stop;
    # terminal state is carried while cost/flow paths remain zero.
    assert len(result.equity) == len(frame)
    np.testing.assert_allclose(result.equity.iloc[1:].to_numpy(), 0.0, rtol=0.0, atol=0.0)
    np.testing.assert_allclose(result.positions.iloc[1:, 0].to_numpy(), 0.0, rtol=0.0, atol=0.0)
    np.testing.assert_allclose(result.fees.iloc[2:].to_numpy(), 0.0, rtol=0.0, atol=0.0)
    np.testing.assert_allclose(result.funding.iloc[2:].to_numpy(), 0.0, rtol=0.0, atol=0.0)
    observability = result.metadata["reactive_numeric_observability"]
    assert observability["bars_processed"] == 2
    assert observability["terminal_path_padded"] is True
    assert observability["terminal_path_original_bars"] == 2
    wake_trace = result.metadata["reactive_numeric_observability"]["wake_trace"]
    mask = int(wake_trace.loc[wake_trace["bar"] == 1, "reason_mask"].iloc[0])
    assert mask & int(WakeReasonV1.FILL)
    assert mask & int(WakeReasonV1.ORDER_EVENT)
    assert mask & int(WakeReasonV1.LIQUIDATION)


class BlockIntentFixture:
    quantbt_reactive_block_intent_v1 = True
    quantbt_block_shadow_certified_v1 = True
    quantbt_requirements = _NUMERIC_REQUIREMENTS

    def __init__(self, *, invalidate_on_fill: bool) -> None:
        self.invalidate_on_fill = invalidate_on_fill
        self.calls: list[tuple[int, int, int, int]] = []

    def next_block(self, context, start_bar, max_stop_bar, out) -> BlockPlanV1:
        self.calls.append((context.bar_index, start_bar, max_stop_bar, int(context.wake_reason_mask)))
        if context.bar_index == 0:
            out.market(0, OrderSide.BUY, 1.0, effective_bar=start_bar)
            out.market(0, OrderSide.SELL, 1.0, effective_bar=start_bar + 3, reduce_only=True)
            return BlockPlanV1(
                stop_bar=min(start_bar + 6, max_stop_bar),
                invalidate_on_fill=self.invalidate_on_fill,
                invalidate_on_reject=True,
            )
        if context.position_qty(0) > 0.0:
            out.market(0, OrderSide.SELL, 1.0, effective_bar=start_bar, reduce_only=True)
        return BlockPlanV1(stop_bar=max_stop_bar, invalidate_on_fill=False, invalidate_on_reject=True)


def test_r3_block_intent_invalidates_only_unexecuted_future_rows():
    frame = _frame()
    strategy = BlockIntentFixture(invalidate_on_fill=True)
    result = _endpoint(runtime="numeric_block_intent_v1").simulate(
        data=frame,
        strategy=strategy,
        symbols=["BTC"],
    )
    report = result.metadata["command_report"]
    assert report["invalidated_before_execution"].sum() == 1
    invalidated = report.loc[report["invalidated_before_execution"]].iloc[0]
    assert invalidated["accepted_by_preflight"]
    assert invalidated["terminal_status"] != 3  # never fabricate a rejection
    assert result.metadata["invalidated_command_count"] == 1
    assert len(result.fills) == 2
    assert strategy.calls[0][:3] == (0, 1, len(frame))
    assert strategy.calls[1][0:2] == (1, 2)
    wake_trace = result.metadata["reactive_numeric_observability"]["wake_trace"]
    assert int(wake_trace.iloc[1]["reason_mask"]) & int(WakeReasonV1.BLOCK_INVALIDATED)


def test_r3_block_range_and_noninvalidating_schedule_are_deterministic():
    frame = _frame()
    planned = BlockIntentFixture(invalidate_on_fill=False)
    result = _endpoint(runtime="numeric_block_intent_v1").simulate(
        data=frame,
        strategy=planned,
        symbols=["BTC"],
    )
    report = result.metadata["command_report"]
    assert not report["invalidated_before_execution"].any()
    assert report["effective_bar"].between(1, len(frame) - 1).all()
    assert len(result.fills) == 2

    class InvalidRange(BlockIntentFixture):
        def next_block(self, context, start_bar, max_stop_bar, out):
            out.market(0, OrderSide.BUY, 1.0, effective_bar=max_stop_bar)
            return BlockPlanV1(stop_bar=max_stop_bar, invalidate_on_fill=False)

    with pytest.raises(Exception, match="outside"):
        _endpoint(runtime="numeric_block_intent_v1").simulate(
            data=frame,
            strategy=InvalidRange(invalidate_on_fill=False),
            symbols=["BTC"],
        )


def test_r3_block_matches_every_bar_oracle_for_a_certified_static_block():
    """A predeclared R3 block must preserve the R1 execution/account trace."""

    class EveryBarBlockOracle:
        quantbt_reactive_numeric_v1 = True
        quantbt_requirements = _NUMERIC_REQUIREMENTS

        def on_bar_close(self, context, out) -> None:
            if context.bar_index == 0:
                out.market(0, OrderSide.BUY, 1.0)
            elif context.bar_index == 3:
                out.market(0, OrderSide.SELL, 1.0, reduce_only=True)

    frame = _frame()
    oracle_result = _endpoint(runtime="numeric_every_bar_v1").simulate(
        data=frame,
        strategy=EveryBarBlockOracle(),
        symbols=["BTC"],
    )
    block_result = _endpoint(runtime="numeric_block_intent_v1").simulate(
        data=frame,
        strategy=BlockIntentFixture(invalidate_on_fill=False),
        symbols=["BTC"],
    )
    _assert_accounting_parity(oracle_result, block_result)
    assert compare_canonical_traces(
        oracle_result.metadata["canonical_trace_v1"],
        block_result.metadata["canonical_trace_v1"],
    )["passed"]


@pytest.mark.parametrize("trigger", ["reject", "margin"])
def test_r3_block_invalidates_future_rows_for_declared_reject_or_margin_change(trigger: str):
    frame = _frame()

    class InvalidationFixture(BlockIntentFixture):
        def next_block(self, context, start_bar, max_stop_bar, out):
            self.calls.append((context.bar_index, start_bar, max_stop_bar, int(context.wake_reason_mask)))
            if context.bar_index == 0:
                if trigger == "reject":
                    out.cancel(999, effective_bar=start_bar)
                else:
                    out.market(0, OrderSide.BUY, 1.0, effective_bar=start_bar)
                out.market(0, OrderSide.BUY, 1.0, effective_bar=start_bar + 3)
                return BlockPlanV1(
                    stop_bar=min(start_bar + 6, max_stop_bar),
                    invalidate_on_fill=False,
                    invalidate_on_reject=trigger == "reject",
                    invalidate_on_margin_change=trigger == "margin",
                )
            return BlockPlanV1(stop_bar=max_stop_bar, invalidate_on_fill=False)

    result = _endpoint(runtime="numeric_block_intent_v1").simulate(
        data=frame,
        strategy=InvalidationFixture(invalidate_on_fill=False),
        symbols=["BTC"],
    )
    report = result.metadata["command_report"]
    assert report["invalidated_before_execution"].sum() == 1
    wake_trace = result.metadata["reactive_numeric_observability"]["wake_trace"]
    assert any(
        int(mask) & int(WakeReasonV1.BLOCK_INVALIDATED)
        for mask in wake_trace["reason_mask"].tolist()
    )


def test_wake_protocol_conditions_are_typed_and_immutable():
    plan = WakePlanV1(
        next_bar=5,
        price_crosses=(PriceCrossConditionV1(0, 101.0, "up"),),
    )
    with pytest.raises((AttributeError, TypeError)):
        plan.next_bar = 6
    assert plan.as_native_payload()["price_crosses"] == ((0, 101.0, 1),)


def _candidate_runner(*, candidate_count: int):
    frame = _frame()
    backend = NativeEventBackend(
        NativeEventConfig(
            account=AccountConfig(initial_capital=20_000.0, leverage=3.0, maintenance_ratio=0.005),
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
    return RustReactiveCandidateBatchCoRuntime(
        candidate_count=candidate_count,
        idx=frame.index,
        symbols=["BTC"],
        market_arrays=market,
        opens_arr=np.ascontiguousarray(frame[["open"]].to_numpy(dtype=np.float64)),
        volumes_arr=np.ascontiguousarray(frame[["volume"]].to_numpy(dtype=np.float64)),
        constraints=build_quantity_constraints(["BTC"]),
        contract_sizes=np.array([1.0], dtype=np.float64),
        leverages=np.array([3.0], dtype=np.float64),
        fee_rates=np.array([0.0004], dtype=np.float64),
        initial_capital=20_000.0,
        maintenance_ratio=0.005,
        slippage=0.0,
        use_funding=True,
        event_contract="event_lifecycle_v3_next_open",
        requirements=_NUMERIC_REQUIREMENTS,
        retain_fills=True,
        retain_events=True,
    )


class CandidateBatchFixture:
    """One batch callback, independent candidate state and typed local error."""

    def __init__(self) -> None:
        self.calls: list[tuple[int, tuple[int, ...], tuple[int, ...]]] = []
        self.retained_context = None
        self.retained_writer = None

    def on_wake_batch(self, context_batch, out_batch) -> CandidateWakePlansV1:
        candidate_ids = tuple(int(value) for value in context_batch.candidate_ids.tolist())
        masks = tuple(int(value) for value in context_batch.wake_reason_masks.tolist())
        self.calls.append((context_batch.bar_index, candidate_ids, masks))
        if context_batch.bar_index == 0:
            self.retained_context = context_batch
        plans = {}
        for candidate_id in candidate_ids:
            if candidate_id == 1 and context_batch.bar_index == 0:
                out_batch.fail_candidate(candidate_id, CandidateErrorCodeV1.STRATEGY_REJECTED)
                continue
            writer = out_batch.writer(candidate_id)
            if candidate_id == 0 and context_batch.bar_index == 0:
                self.retained_writer = writer
            if context_batch.bar_index == 0:
                writer.market(0, OrderSide.BUY, float(candidate_id + 1))
                plans[candidate_id] = WakePlanV1(on_fill=True)
            else:
                plans[candidate_id] = WakePlanV1()
        return CandidateWakePlansV1(plans)


def test_r3b_candidate_batch_coalesces_callbacks_and_isolates_failures():
    runner = _candidate_runner(candidate_count=3)
    strategy = CandidateBatchFixture()
    payload = runner.run(strategy)

    assert np.asarray(payload["candidate_ids"]).tolist() == [0, 1, 2]
    assert np.asarray(payload["candidate_error_codes"]).tolist() == [0, 1, 0]
    assert payload["batch_callback_count"] == 2
    assert strategy.calls[0][0:2] == (0, (0, 1, 2))
    assert strategy.calls[1][0:2] == (1, (0, 2))
    outputs = list(payload["candidate_outputs"])
    assert len(outputs) == 3
    assert int(outputs[0]["fill_count"]) == 1
    assert int(outputs[1]["fill_count"]) == 0
    assert int(outputs[2]["fill_count"]) == 1
    assert int(outputs[0]["command_rows"]) == 1
    assert int(outputs[1]["command_rows"]) == 0
    assert int(outputs[2]["command_rows"]) == 1
    np.testing.assert_allclose(outputs[1]["positions"], 0.0, rtol=0.0, atol=0.0)
    with pytest.raises(RuntimeError, match="no longer valid"):
        _ = strategy.retained_context.candidate_ids
    with pytest.raises(RuntimeError, match="only writable during"):
        strategy.retained_writer.market(0, OrderSide.BUY, 1.0)


def test_r3b_enforces_bounded_capacity_and_reset_has_no_state_leakage():
    with pytest.raises(ValueError, match="1..=64"):
        _candidate_runner(candidate_count=65)

    runner = _candidate_runner(candidate_count=2)
    first = runner.run(CandidateBatchFixture())
    runner.reset()
    second = runner.run(CandidateBatchFixture())
    for left, right in zip(first["candidate_outputs"], second["candidate_outputs"]):
        np.testing.assert_allclose(left["equity"], right["equity"], rtol=0.0, atol=1e-12)
        np.testing.assert_allclose(left["positions"], right["positions"], rtol=0.0, atol=1e-12)
