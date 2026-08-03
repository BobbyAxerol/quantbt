from __future__ import annotations

import math

import numpy as np
import pandas as pd

from quantbt import NativeCommandBatch, OrderCommand, OrderSide, OrderType, QuantBTEndpoint, TimeInForce
from quantbt.backends.native_event import NativeEventScoreRequirements
from quantbt.optimization.evaluators.native_event import PreparedNativeEventStrategyEvaluator
from quantbt.optimization.result import ObjectiveResult


def _bars(n: int = 72) -> pd.DataFrame:
    idx = pd.date_range("2024-01-01", periods=n, freq="1h", tz="UTC")
    close = pd.Series(100.0 + np.sin(np.arange(n) / 4.0) * 2.0 + np.arange(n) * 0.08, index=idx)
    return pd.DataFrame(
        {
            "open": close.shift(1).fillna(close.iloc[0]),
            "high": close + 1.5,
            "low": close - 1.5,
            "close": close,
            "volume": 1_000.0,
        },
        index=idx,
    )


class EnterExitStrategy:
    def __init__(self, entry_bar: int = 2, exit_bar: int = 40):
        self.entry_bar = int(entry_bar)
        self.exit_bar = int(exit_bar)

    def on_bar_close(self, context):
        if context.bar_index == self.entry_bar:
            return [
                OrderCommand(
                    timestamp=context.timestamp,
                    symbol="BTC",
                    side=OrderSide.BUY,
                    order_type=OrderType.MARKET,
                    qty=1.0,
                    tif=TimeInForce.IOC,
                    order_id="entry",
                )
            ]
        if context.bar_index == self.exit_bar:
            return [
                OrderCommand(
                    timestamp=context.timestamp,
                    symbol="BTC",
                    side=OrderSide.SELL,
                    order_type=OrderType.MARKET,
                    qty=1.0,
                    tif=TimeInForce.IOC,
                    reduce_only=True,
                    order_id="exit",
                )
            ]
        return ()


class NoContextObjectsStrategy(EnterExitStrategy):
    native_context_requirements = {
        "fills": False,
        "events": False,
        "active_orders": False,
        "positions": False,
        "margin": False,
    }

    def __init__(self):
        super().__init__(entry_bar=2, exit_bar=40)
        self.context_shapes = []

    def on_bar_close(self, context):
        self.context_shapes.append(
            (
                len(context.fills_this_bar),
                len(context.order_events_this_bar),
                len(context.active_orders),
                len(context.positions),
                context.initial_margin,
                context.maintenance_margin,
            )
        )
        return super().on_bar_close(context)


class BatchStrategy(EnterExitStrategy):
    def on_bar_close(self, context):
        return NativeCommandBatch.from_commands(super().on_bar_close(context))


def _prepared():
    endpoint = QuantBTEndpoint.native_event_strategy(
        initial_capital=10_000,
        leverage=10,
        use_funding=False,
        fee_rate=0.0002,
        report_level="audit",
    )
    return endpoint, endpoint.prepare_native_event_strategy(data=_bars(), symbols=["BTC"])


def test_scalar_score_matches_public_audit_metrics_without_accounting_paths():
    endpoint, prepared = _prepared()
    strategy = EnterExitStrategy()
    scalar = prepared.score(
        strategy,
        score_requirements=NativeEventScoreRequirements.scalar_score_contract(),
    )
    audit = prepared.run(EnterExitStrategy(), report_level="audit")
    report = audit.full_report()

    assert scalar.metadata["score_scalar"] is True
    assert scalar.metadata["score_pandas_materialized"] is False
    assert all(value is False for value in scalar.metadata["score_retained_paths"].values())
    assert not hasattr(scalar, "accounting")
    for key, expected in report.items():
        actual = scalar.metrics[key]
        if isinstance(expected, (float, int)) and not isinstance(expected, bool):
            if math.isinf(float(expected)):
                assert math.isinf(float(actual)) and (float(expected) > 0) == (float(actual) > 0)
            else:
                np.testing.assert_allclose(actual, expected, rtol=0.0, atol=1e-12)
        else:
            assert actual == expected
    assert scalar.final_equity == audit.equity.iloc[-1]
    assert endpoint.result is audit


def test_context_declaration_avoids_current_bar_event_objects_and_snapshots():
    _, prepared = _prepared()
    strategy = NoContextObjectsStrategy()
    scalar = prepared.score(
        strategy,
        score_requirements=NativeEventScoreRequirements.from_strategy(
            strategy,
            base=NativeEventScoreRequirements.scalar_score_contract(),
        ),
    )

    assert scalar.metrics["num_trades"] == 3
    assert all(shape == (0, 0, 0, 0, 0.0, 0.0) for shape in strategy.context_shapes)
    assert scalar.metadata["score_requirements"]["need_context_fills"] is False
    assert scalar.metadata["score_requirements"]["need_context_events"] is False


def test_prepared_evaluator_uses_scalar_score_and_keeps_strategy_compatibility():
    _, prepared = _prepared()

    evaluator = PreparedNativeEventStrategyEvaluator(
        runner=prepared,
        strategy_factory=lambda params: EnterExitStrategy(
            entry_bar=int(params["entry_bar"]),
            exit_bar=int(params["exit_bar"]),
        ),
        objective_builder=lambda result, params: ObjectiveResult(
            values=(float(result.metrics["sharpe"]),),
            metrics=result.metrics,
            metadata={"params": dict(params)},
        ),
    )
    objective = evaluator.evaluate({"entry_bar": 2, "exit_bar": 40})

    assert isinstance(objective, ObjectiveResult)
    assert evaluator.last_result is None
    assert prepared.metadata["scores"] == 1


def test_native_command_batch_preserves_legacy_callback_execution():
    _, prepared = _prepared()
    scalar = prepared.score(
        BatchStrategy(),
        score_requirements=NativeEventScoreRequirements.scalar_score_contract(),
    )
    assert scalar.fill_count == 2
    assert scalar.metrics["num_trades"] == 3


def test_scalar_fee_and_funding_counters_reconcile_to_audit_paths():
    endpoint = QuantBTEndpoint.native_event_strategy(
        initial_capital=10_000,
        leverage=10,
        use_funding=True,
        funding_rate=0.0001,
        fee_rate=0.0002,
        report_level="audit",
    )
    prepared = endpoint.prepare_native_event_strategy(data=_bars(96), symbols=["BTC"])
    scalar = prepared.score(
        EnterExitStrategy(entry_bar=2, exit_bar=80),
        score_requirements=NativeEventScoreRequirements.scalar_score_contract(),
    )
    audit = prepared.run(EnterExitStrategy(entry_bar=2, exit_bar=80), report_level="audit")

    np.testing.assert_allclose(
        scalar.metrics["total_fee"],
        float(audit.fees.sum()),
        rtol=0.0,
        atol=1e-12,
    )
    np.testing.assert_allclose(
        scalar.metrics["total_funding"],
        float(audit.funding.sum()),
        rtol=0.0,
        atol=1e-12,
    )
    np.testing.assert_allclose(
        scalar.metrics["final_equity"],
        float(audit.equity.iloc[-1]),
        rtol=0.0,
        atol=1e-12,
    )
