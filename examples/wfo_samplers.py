"""Sampler-only public WFO on synthetic OHLC; no claim of trading edge.

Run: python examples/wfo_samplers.py --sampler sobol
Requires quantbt-engine[optimization]. Meta-selection is not enabled.
"""

import argparse
import json

import numpy as np
import pandas as pd

from quantbt import QuantBTEndpoint
from quantbt.optimization import NormalizedSearchSpace, SamplerConfig
from quantbt.core.wfo_contracts import strategy_fingerprint


def strategy(data, params, train_index, test_index, fold):
    frame = data.loc[: test_index[-1]]
    close = frame["close"]
    average = close.rolling(params["window"], min_periods=1).mean()
    deviation = close / average - 1.0
    return (
        deviation.where(deviation.abs() >= params["threshold"], 0)
        .apply(np.sign)
        .reindex(test_index)
        .fillna(0)
    )


def run(sampler="tpe_legacy", *, warm_start=False):
    index = pd.date_range("2020-01-01", "2021-06-30", freq="D", tz="UTC")
    t = np.arange(len(index))
    close = 100 + 0.02 * t + 3 * np.sin(t / 13)
    data = pd.DataFrame(
        dict(open=close, high=close + 1, low=close - 1, close=close, volume=1000),
        index=index,
    )
    ranges = {
        "window": (3, 31, 2),
        "threshold": {"kind": "float", "low": 0.0001, "high": 0.01, "log": True},
    }
    config = dict(
        sampler_config=SamplerConfig(name=sampler),
        scoring_backend="endpoint",
        is_subperiods=3,
        top_is_fraction=0.5,
        flat_min_samples=1,
        flat_eps=1,
        research_retention="none",
        wfo_execution_reuse="off",
        profile_walkforward=True,
    )
    if warm_start:
        config["sampler_warm_start"] = [
            {
                "params": {"window": 11, "threshold": 0.001},
                "available_at": "2020-01-01T00:00:00Z",
                "space_identity": NormalizedSearchSpace(ranges).identity,
                "strategy_identity": strategy_fingerprint(strategy),
            }
        ]
    endpoint = QuantBTEndpoint.walk_forward(
        strategy_class=strategy,
        split_mode="2021-01-01",
        split_frequency="quarterly",
        window_mode="rolling",
        train_window="180D",
        optimization_mode="mode_4_is_only_robust",
        optimization_schedule="per_fold_causal",
        optimization_config=config,
        optuna_trials=12,
        random_seed=731,
        target_mode="signal_notional",
        initial_capital=20_000,
        alloc_per_trade=1000,
        leverage=3,
        fee_rate=0.0005,
        use_funding=False,
    )
    result = endpoint.backtest(data=data, param_ranges=ranges)
    return endpoint, result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--sampler",
        choices=("tpe_legacy", "tpe_multivariate_group", "cmaes", "sobol"),
        default="tpe_legacy",
    )
    parser.add_argument("--warm-start", action="store_true")
    args = parser.parse_args()
    endpoint, result = run(args.sampler, warm_start=args.warm_start)
    print(
        json.dumps(
            result.metadata["walk_forward"]["sampler_studies"], default=str, indent=2
        )
    )
    endpoint.show_metrics()
