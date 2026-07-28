#!/usr/bin/env python3
"""Small domain-agnostic optimization examples."""

from __future__ import annotations

from pathlib import Path
import sys

import numpy as np
import pandas as pd

PACKAGE_DIR = Path(__file__).resolve().parents[1]
PROJECT_DIR = PACKAGE_DIR.parent
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from quantbt import (  # noqa: E402
    GenericEndpointEvaluator,
    ObjectiveResult,
    OptimizationConfig,
    OptunaOptimizer,
    PreparedSignalEvaluator,
    QuantBTEndpoint,
    SamplerConfig,
    SharpeObjective,
)


def main() -> None:
    df = _frame()
    endpoint = QuantBTEndpoint.signal_notional(
        backend="native_vectorized",
        initial_capital=20_000.0,
        leverage=5.0,
        alloc_per_trade=1_000.0,
        fee_rate=0.0,
        use_funding=False,
    )

    prepared = endpoint.prepare_service_context(data=df, symbols=["BTC"])
    prepared_evaluator = PreparedSignalEvaluator(
        prepared_context=prepared,
        strategy_func=lambda params: _signal(df, float(params["threshold"])),
        objective_builder=SharpeObjective(),
    )
    prepared_result = OptunaOptimizer(
        evaluator=prepared_evaluator,
        config=OptimizationConfig(study_name="example_prepared_signal", n_trials=6, show_progress_bar=False),
        sampler_config=SamplerConfig(name="random"),
    ).optimize(param_ranges={"threshold": (0.0, 1.0, 0.25)})

    generic_evaluator = GenericEndpointEvaluator(
        build_run_inputs=lambda params: {
            "data": df,
            "signal": _signal(df, float(params["threshold"])),
            "symbols": ["BTC"],
        },
        run_func=endpoint.backtest,
        objective_builder=lambda result, params: ObjectiveResult.scalar(
            result.full_report()["sharpe"],
            metrics={"sharpe": result.full_report()["sharpe"]},
        ),
    )
    generic_result = OptunaOptimizer(
        evaluator=generic_evaluator,
        config=OptimizationConfig(study_name="example_generic_endpoint", n_trials=6, show_progress_bar=False),
        sampler_config=SamplerConfig(name="random"),
    ).optimize(param_ranges={"threshold": (0.0, 1.0, 0.25)})

    print("prepared selected:", prepared_result.selected_params)
    print("generic selected:", generic_result.selected_params)


def _frame() -> pd.DataFrame:
    idx = pd.date_range("2024-01-01", periods=120, freq="1h", tz="UTC")
    x = np.linspace(0.0, 10.0, len(idx))
    close = 100.0 + np.sin(x) * 3.0 + np.arange(len(idx)) * 0.02
    return pd.DataFrame(
        {
            "open": close,
            "high": close * 1.01,
            "low": close * 0.99,
            "close": close,
            "volume": 1_000.0,
        },
        index=idx,
    )


def _signal(df: pd.DataFrame, threshold: float) -> pd.Series:
    returns = df["close"].pct_change().fillna(0.0)
    return pd.Series(np.where(returns > threshold / 100.0, 1.0, 0.0), index=df.index)


if __name__ == "__main__":
    main()

