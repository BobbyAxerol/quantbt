from __future__ import annotations

import numpy as np
import pandas as pd

from quantbt import QuantBTEndpoint
from quantbt.core.orders import OrderCommand
from quantbt.core.schema import OrderSide, OrderType, TimeInForce
from quantbt.optimization import ObjectiveResult, PreparedNativeEventStrategyEvaluator


def _bars(n: int = 16) -> pd.DataFrame:
    idx = pd.date_range("2024-01-01", periods=n, freq="1h", tz="UTC")
    close = pd.Series(100.0 + np.sin(np.arange(n) / 2.0) * 2.0, index=idx)
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


class TwoTradeStrategy:
    def __init__(self, entry_bar: int = 0, exit_bar: int = 5, qty: float = 1.0):
        self.entry_bar = int(entry_bar)
        self.exit_bar = int(exit_bar)
        self.qty = float(qty)

    def on_bar_close(self, context):
        if context.bar_index == self.entry_bar:
            return [
                OrderCommand(
                    timestamp=context.timestamp,
                    symbol=context.symbols[0],
                    side=OrderSide.BUY,
                    order_type=OrderType.MARKET,
                    qty=self.qty,
                    tif=TimeInForce.IOC,
                    order_id=f"entry-{self.entry_bar}",
                )
            ]
        if context.bar_index == self.exit_bar:
            return [
                OrderCommand(
                    timestamp=context.timestamp,
                    symbol=context.symbols[0],
                    side=OrderSide.SELL,
                    order_type=OrderType.MARKET,
                    qty=self.qty,
                    tif=TimeInForce.IOC,
                    reduce_only=True,
                    order_id=f"exit-{self.exit_bar}",
                )
            ]
        return []


def test_prepared_native_event_score_matches_public_audit_metrics_exactly():
    df = _bars()
    endpoint = QuantBTEndpoint.native_event_strategy(
        initial_capital=10_000,
        leverage=10,
        use_funding=False,
        fee_rate=0.0002,
        report_level="audit",
    )
    prepared = endpoint.prepare_native_event_strategy(data=df, symbols=["BTC"])

    score = prepared.score(TwoTradeStrategy(entry_bar=0, exit_bar=5), trading_days=365)
    assert endpoint.result is None
    audit = prepared.run(TwoTradeStrategy(entry_bar=0, exit_bar=5), report_level="audit")

    np.testing.assert_array_equal(score.equity, audit.equity.to_numpy(dtype=np.float64))
    np.testing.assert_array_equal(score.returns, audit.returns.to_numpy(dtype=np.float64))
    np.testing.assert_array_equal(score.positions, audit.positions[["Position_BTC"]].to_numpy(dtype=np.float64))
    np.testing.assert_array_equal(score.fees, audit.fees.to_numpy(dtype=np.float64))
    np.testing.assert_array_equal(score.funding, audit.funding.to_numpy(dtype=np.float64))
    np.testing.assert_array_equal(score.initial_margin, audit.margin["initial_margin"].to_numpy(dtype=np.float64))
    np.testing.assert_array_equal(score.maintenance_margin, audit.margin["maintenance_margin"].to_numpy(dtype=np.float64))

    full_metrics = audit.full_report(trading_days=365, scope="full")
    for key in (
        "sharpe",
        "max_drawdown_pct",
        "profit_factor",
        "num_trades",
        "final_equity",
        "total_return_pct",
        "liquidated",
    ):
        assert score.metrics[key] == full_metrics[key]

    assert score.metadata["report_level"] == "score"
    assert score.fill_count == audit.metadata["lifecycle_counters"]["fill_count"]
    assert score.rejection_count == audit.metadata["lifecycle_counters"]["rejected_count"]
    assert prepared.metadata["scores"] == 1
    assert prepared.metadata["runs"] == 1


def test_prepared_native_event_score_reuses_market_arrays_and_keeps_endpoint_result_light():
    df = _bars(24)
    endpoint = QuantBTEndpoint.native_event_strategy(initial_capital=10_000, leverage=10, use_funding=False)
    prepared = endpoint.prepare_native_event_strategy(data=df, symbols=["BTC"])
    signature = prepared.market_arrays.signature

    first = prepared.score(TwoTradeStrategy(entry_bar=0, exit_bar=4))
    second = prepared.score(TwoTradeStrategy(entry_bar=2, exit_bar=8))

    assert prepared.market_arrays.signature == signature
    assert prepared.metadata["scores"] == 2
    assert endpoint.result is None
    assert not hasattr(first, "fills")
    assert not hasattr(second, "orders")
    assert first.metadata["prepared_native_event_strategy"]["market_signature"] == signature
    assert second.metadata["prepared_native_event_strategy"]["market_signature"] == signature


def test_prepared_native_event_strategy_evaluator_uses_score_result_contract():
    df = _bars()
    endpoint = QuantBTEndpoint.native_event_strategy(initial_capital=10_000, leverage=10, use_funding=False)
    prepared = endpoint.prepare_native_event_strategy(data=df, symbols=["BTC"])

    def strategy_factory(params):
        return TwoTradeStrategy(entry_bar=int(params["entry_bar"]), exit_bar=int(params["exit_bar"]))

    def objective_builder(result, params):
        report = result.full_report()
        return ObjectiveResult(values=(float(report["sharpe"]),), metrics=report, metadata={"params": dict(params)})

    evaluator = PreparedNativeEventStrategyEvaluator(
        runner=prepared,
        strategy_factory=strategy_factory,
        objective_builder=objective_builder,
    )
    objective = evaluator.evaluate({"entry_bar": 0, "exit_bar": 5})

    assert isinstance(objective, ObjectiveResult)
    assert evaluator.last_result.metadata["engine"] == "event_v2_reactive_score"
    assert prepared.metadata["scores"] == 1
