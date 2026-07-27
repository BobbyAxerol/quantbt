from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from quantbt import (
    ArbitrageGenericEvaluator,
    ArbitrageTrialOutput,
    GenericEndpointEvaluator,
    GridDCAGenericEvaluator,
    GridDCATrialOutput,
    IntrabarIntentTape,
    ObjectiveResult,
    OptionPackageGenericEvaluator,
    OptionTrialOutput,
    PreparedIntrabarEvaluator,
    PreparedPortfolioEvaluator,
    PreparedSignalEvaluator,
    QuantBTEndpoint,
    ReportMetricObjective,
    SharpeObjective,
    max_drawdown_constraint,
    max_rejection_rate_constraint,
    min_trades_constraint,
)


def _single_frame(n: int = 8) -> pd.DataFrame:
    idx = pd.date_range("2024-01-01", periods=n, freq="1h", tz="UTC")
    close = np.linspace(100.0, 107.0, n)
    return pd.DataFrame(
        {
            "open": close,
            "high": close + 2.0,
            "low": close - 2.0,
            "close": close,
            "volume": np.full(n, 1000.0),
        },
        index=idx,
    )


def _portfolio_data():
    idx = pd.date_range("2024-01-01", periods=6, freq="1D", tz="UTC")
    btc = pd.DataFrame(
        {
            "open": [100, 100, 104, 106, 105, 107],
            "high": [101, 105, 107, 108, 108, 109],
            "low": [99, 99, 103, 104, 103, 106],
            "close": [100, 104, 106, 105, 107, 108],
            "volume": 1000.0,
        },
        index=idx,
    )
    eth = pd.DataFrame(
        {
            "open": [50, 50, 49, 51, 52, 51],
            "high": [51, 51, 52, 53, 53, 52],
            "low": [49, 48, 48, 50, 50, 50],
            "close": [50, 49, 51, 52, 51, 50],
            "volume": 1000.0,
        },
        index=idx,
    )
    return {"BTC": btc, "ETH": eth}


def test_generic_endpoint_evaluator_custom_objective_override():
    calls = []

    class Result:
        def __init__(self, value):
            self.value = value

        def full_report(self, trading_days=365, scope="auto"):
            return {"sharpe": self.value, "max_drawdown_pct": 1.0, "num_trades": 3}

    evaluator = GenericEndpointEvaluator(
        build_run_inputs=lambda params: {"value": float(params["x"]) * 2.0},
        run_func=lambda value: Result(value),
        objective_builder=lambda result, params: ObjectiveResult.scalar(result.value + 1.0, metrics={"custom": result.value}),
    )

    objective = evaluator.evaluate({"x": 4})
    calls.append(evaluator.last_run_inputs)

    assert objective.values == (9.0,)
    assert objective.metrics["custom"] == 8.0
    assert calls == [{"value": 8.0}]


def test_prepared_signal_evaluator_matches_normal_endpoint():
    df = _single_frame()
    signal = pd.Series([0, 1, 1, 0, -1, -1, 0, 0], index=df.index, dtype=float)
    endpoint = QuantBTEndpoint.signal_notional(
        backend="native_vectorized",
        initial_capital=10_000.0,
        leverage=5.0,
        alloc_per_trade=1_000.0,
        fee_rate=0.0,
        use_funding=False,
    )

    normal = endpoint.backtest(data=df, signal=signal, symbols=["BTC"])
    prepared = endpoint.prepare_service_context(data=df, symbols=["BTC"])
    evaluator = PreparedSignalEvaluator(
        prepared_context=prepared,
        strategy_func=lambda params: signal * float(params["scale"]),
        objective_builder=ReportMetricObjective(value_metrics=("sharpe",)),
    )
    objective = evaluator.evaluate({"scale": 1.0})

    np.testing.assert_allclose(evaluator.last_result.equity.to_numpy(), normal.equity.to_numpy(), rtol=0.0, atol=1e-9)
    assert prepared.metadata["runs"] == 1
    assert "sharpe" in objective.metrics


def test_prepared_intrabar_evaluator_from_frame_and_minimal_audit_accounting_match():
    df = _single_frame(5)
    endpoint = QuantBTEndpoint.intrabar_bracket(
        initial_capital=10_000.0,
        leverage=5.0,
        fee_rate=0.0,
        slippage_bps=0.0,
        use_funding=False,
        report_level="minimal",
        close_on_last_bar=True,
    )
    runner = endpoint.prepare_intrabar(data=df, symbols=["BTC"])
    alpha = pd.DataFrame(
        {
            "entry": [1.0, 0.0, 0.0, 0.0, 0.0],
            "stop_value": [0.03, np.nan, np.nan, np.nan, np.nan],
            "take_profit_value": [0.03, np.nan, np.nan, np.nan, np.nan],
        },
        index=df.index,
    )
    audit_intent = IntrabarIntentTape.from_frame(alpha)
    audit = runner.run(audit_intent, report_level="audit")

    evaluator = PreparedIntrabarEvaluator(
        runner=runner,
        strategy_func=lambda params: alpha,
        objective_builder=SharpeObjective(),
        report_level="minimal",
    )
    objective = evaluator.evaluate({})

    np.testing.assert_allclose(evaluator.last_result.equity.to_numpy(), audit.equity.to_numpy(), rtol=0.0, atol=1e-9)
    assert evaluator.last_result.metadata["report_level"] == "minimal"
    assert audit.metadata["report_level"] == "audit"
    assert objective.values == (objective.metrics["sharpe"],)


def test_prepared_intrabar_evaluator_requires_intent_contract():
    df = _single_frame(3)
    endpoint = QuantBTEndpoint.intrabar_bracket(initial_capital=10_000.0, use_funding=False)
    runner = endpoint.prepare_intrabar(data=df, symbols=["BTC"])
    evaluator = PreparedIntrabarEvaluator(runner=runner, strategy_func=lambda params: object(), objective_builder=SharpeObjective())

    with pytest.raises(TypeError, match="IntrabarIntentTape"):
        evaluator.evaluate({})


def test_prepared_portfolio_evaluator_matches_normal_endpoint():
    data = _portfolio_data()
    idx = next(iter(data.values())).index
    positions = pd.DataFrame(
        {
            "BTC": [0.0, 1.0, 1.0, 0.0, -1.0, -1.0],
            "ETH": [0.0, -1.0, -1.0, 0.0, 1.0, 1.0],
        },
        index=idx,
    )
    endpoint = QuantBTEndpoint.portfolio(
        portfolio_mode="longshort",
        backend="native_portfolio",
        initial_capital=100_000.0,
        leverage=5.0,
        alloc_per_trade={"BTC": 1_000.0, "ETH": 500.0},
        hedge_type="signal_notional",
        fee=0.0,
        use_funding=False,
    )

    normal = endpoint.backtest(data=data, positions=positions, symbols=["BTC", "ETH"])
    prepared = endpoint.prepare_service_context(data=data, symbols=["BTC", "ETH"])
    evaluator = PreparedPortfolioEvaluator(
        prepared_context=prepared,
        strategy_func=lambda params: positions,
        objective_builder=ReportMetricObjective(value_metrics=("sharpe", "max_drawdown_pct")),
    )
    objective = evaluator.evaluate({})

    np.testing.assert_allclose(evaluator.last_result.equity.to_numpy(), normal.equity.to_numpy(), rtol=0.0, atol=1e-9)
    assert objective.values[1] == objective.metrics["max_drawdown_pct"]


def test_common_objective_helpers_use_formal_constraints():
    df = _single_frame()
    signal = pd.Series([0, 1, 1, 0, 0, 0, 0, 0], index=df.index, dtype=float)
    endpoint = QuantBTEndpoint.signal_notional(
        backend="native_vectorized",
        initial_capital=10_000.0,
        leverage=5.0,
        alloc_per_trade=1_000.0,
        fee_rate=0.0,
        use_funding=False,
    )
    result = endpoint.backtest(data=df, signal=signal, symbols=["BTC"])
    result.metadata["rejected_count"] = 0
    result.metadata["fill_count"] = 1
    objective = ReportMetricObjective(
        value_metrics=("sharpe",),
        constraints=(min_trades_constraint(10), max_drawdown_constraint(99), max_rejection_rate_constraint(0.01)),
    )(result, {})

    assert objective.constraints[0] > 0.0
    assert objective.constraints[1] <= 0.0
    assert objective.constraints[2] <= 0.0


def test_arbitrage_grid_dca_and_option_generic_adapters():
    class Result:
        def __init__(self, value, metadata=None):
            self.metadata = dict(metadata or {})
            self.value = float(value)

        def full_report(self, trading_days=365, scope="auto"):
            return {"sharpe": self.value, "max_drawdown_pct": 0.0, "num_trades": 1, "profit_factor": 1.0}

    objective = SharpeObjective()

    arb = ArbitrageGenericEvaluator(
        build_run_inputs=lambda params: {"output": ArbitrageTrialOutput(signal=params["x"], hedge_ratios=1.0)},
        run_func=lambda output: Result(float(output.signal), {"kind": "arb"}),
        objective_builder=objective,
    )
    grid = GridDCAGenericEvaluator(
        build_run_inputs=lambda params: {"output": GridDCATrialOutput(levels=params["x"])},
        run_func=lambda output: Result(float(output.levels), {"kind": "grid"}),
        objective_builder=objective,
    )
    option = OptionPackageGenericEvaluator(
        build_run_inputs=lambda params: {"output": OptionTrialOutput(package=params["x"])},
        run_func=lambda output: Result(float(output.package), {"kind": "option"}),
        objective_builder=objective,
    )

    assert arb.evaluate({"x": 1.0}).values == (1.0,)
    assert grid.evaluate({"x": 2.0}).values == (2.0,)
    assert option.evaluate({"x": 3.0}).values == (3.0,)
