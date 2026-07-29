from __future__ import annotations

import inspect

import numpy as np
import pandas as pd

import quantbt
from quantbt import EndpointConfig, OrderCommand, PreparedNativeEventStrategyRunner, QuantBTEndpoint
from quantbt.core.schema import OrderSide, OrderType, TimeInForce
from quantbt.optimization import ObjectiveResult, PreparedNativeEventStrategyEvaluator, ReportMetricObjective


class _GateStrategy:
    def on_bar_close(self, context):
        symbol = context.symbols[0]
        if context.bar_index == 0:
            return [
                OrderCommand(
                    timestamp=context.timestamp,
                    symbol=symbol,
                    side=OrderSide.BUY,
                    order_type=OrderType.MARKET,
                    qty=1.0,
                    tif=TimeInForce.IOC,
                    order_id="entry",
                )
            ]
        if context.bar_index == 4 and context.positions[symbol] > 0.0:
            return [
                OrderCommand(
                    timestamp=context.timestamp,
                    symbol=symbol,
                    side=OrderSide.SELL,
                    order_type=OrderType.MARKET,
                    qty=abs(context.positions[symbol]),
                    tif=TimeInForce.IOC,
                    reduce_only=True,
                    order_id="exit",
                )
            ]
        return []


def _bars() -> pd.DataFrame:
    idx = pd.date_range("2024-01-01", periods=12, freq="1h", tz="UTC")
    close = pd.Series(100.0 + np.sin(np.arange(len(idx)) / 2.0), index=idx)
    return pd.DataFrame(
        {
            "open": close,
            "high": close + 2.0,
            "low": close - 2.0,
            "close": close,
            "volume": 1_000.0,
        },
        index=idx,
    )


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> None:
    fields = EndpointConfig.__dataclass_fields__
    _assert(
        all(name in fields for name in ("reactive_kernel_mode", "audit_sink", "audit_sink_path")),
        "EndpointConfig missing Phase 34 fields",
    )
    print("EndpointConfig fields: PASSED")

    _assert(hasattr(QuantBTEndpoint, "prepare_native_event_strategy"), "prepare_native_event_strategy missing")
    _assert(hasattr(quantbt, "PreparedNativeEventStrategyRunner"), "PreparedNativeEventStrategyRunner missing")
    _assert(quantbt.PreparedNativeEventStrategyRunner is PreparedNativeEventStrategyRunner, "Prepared runner export mismatch")
    print("Prepared endpoint API: PASSED")

    endpoint = QuantBTEndpoint.native_event_strategy(initial_capital=10_000, leverage=10, use_funding=False)
    prepared = endpoint.prepare_native_event_strategy(data=_bars(), symbols=["BTC"])
    _assert(isinstance(prepared, PreparedNativeEventStrategyRunner), "prepared runner type mismatch")
    score = prepared.score(_GateStrategy())
    _assert(score.metadata["reactive_kernel_mode"] == "single_pass", "prepared score did not use single_pass")
    print("prepared.score(): PASSED")

    signature = inspect.signature(score.full_report)
    _assert("scope" in signature.parameters, "NativeEventScoreResult.full_report missing scope")
    score.full_report(scope="auto")
    print("Score/full_report signature: PASSED")

    def strategy_factory(_params):
        return _GateStrategy()

    def objective_builder(result, params):
        objective = ReportMetricObjective(value_metrics=("sharpe",), scope="auto")
        return objective(result, params)

    evaluator = PreparedNativeEventStrategyEvaluator(
        runner=prepared,
        strategy_factory=strategy_factory,
        objective_builder=objective_builder,
    )
    objective = evaluator.evaluate({})
    _assert(isinstance(objective, ObjectiveResult), "Prepared evaluator did not return ObjectiveResult")
    print("Prepared evaluator import: PASSED")

    objective = ReportMetricObjective(value_metrics=("sharpe",), scope="auto")(score, {})
    _assert(isinstance(objective, ObjectiveResult), "ReportMetricObjective(score) failed")
    print("ReportMetricObjective(score): PASSED")
    print("PHASE 34 MERGE GATE: PASSED")


if __name__ == "__main__":
    main()
