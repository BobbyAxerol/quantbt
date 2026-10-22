"""Optional sampler-space helper on a public synthetic pct-equity alpha.

Requires quantbt-engine[optimization]. No meta activation or economic promise.
"""

from __future__ import annotations

import argparse
import json

import numpy as np
import pandas as pd

from quantbt import QuantBTEndpoint
from quantbt.optimization import prepare_sampler_space


RANGES = {
    "fast_window": list(range(4, 33, 4)),
    "slow_window": list(range(40, 101, 10)),
    "threshold": (0.001, 0.02),
    "offset": (-0.02, 0.02),
}
ACCOUNT = dict(initial_capital=20_000.0, leverage=1.0, alloc_per_trade=0.5,
               fee_rate=0.0005, slippage=0.0001, use_funding=False,
               use_pyramiding=False, target_runtime="numba")


def market():
    index = pd.date_range("2020-01-01", "2022-12-31", freq="D", tz="UTC")
    rng = np.random.default_rng(1049)
    t = np.arange(len(index))
    returns = 0.0015 * np.sin(t / 90) + 0.003 * np.sin(t / 11) + rng.normal(0, 0.007, len(t))
    close = 100 * np.exp(np.cumsum(returns))
    open_ = np.r_[close[0], close[:-1]]
    return pd.DataFrame(dict(open=open_, high=np.maximum(open_, close) * 1.003,
                             low=np.minimum(open_, close) * 0.997,
                             close=close, volume=1000.0), index=index)


def strategy(data, params, train_index, test_index, fold):
    close = data.loc[:test_index[-1], "close"]
    fast = close.rolling(params["fast_window"], min_periods=params["fast_window"]).mean()
    slow = close.rolling(params["slow_window"], min_periods=params["slow_window"]).mean()
    deviation = fast / slow - 1.0 - params["offset"]
    signal = np.sign(deviation).where(deviation.abs() >= params["threshold"], 0.0)
    return signal.reindex(test_index).fillna(0.0).astype(float)


def endpoint(strategy_class=strategy, *, config=None, seed=731, trials=128, account=None):
    optimization = dict(scoring_backend="endpoint", is_subperiods=1,
                        candidate_selection_metric="is_only_robust", top_is_fraction=0.10,
                        flat_min_samples=3, flat_eps=0.15, flat_selector="medoid",
                        min_trades_per_year=10, trade_penalty_factor=0.5,
                        scoring_trading_days=365, research_retention="none",
                        native_prepared_wfo="off", use_scalar_trial_scoring=False,
                        wfo_execution_reuse="off", meta_selection={"mode": "off"},
                        profile_walkforward=True)
    optimization.update(config or {})
    return QuantBTEndpoint.walk_forward(
        strategy_class=strategy_class, split_mode="2022-01-01", split_frequency="quarterly",
        window_mode="rolling", train_window="365D", target_mode="pct_equity",
        optimization_mode="mode_4_is_only_robust", optimization_schedule="per_fold_causal",
        optuna_trials=trials, optuna_early_stopping=None, random_seed=seed,
        optimization_config=optimization, **(ACCOUNT if account is None else account),
    )


def run(sampler="cmaes", *, trials=128):
    plan = prepare_sampler_space(RANGES, preferred_sampler=sampler,
                                 numeric_parameters=("fast_window", "slow_window"))
    bt = endpoint(config=plan.optimization_config(), trials=trials)
    result = bt.backtest(data=market(), param_ranges=plan.param_ranges)
    return plan, bt, result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sampler", choices=("cmaes", "tpe_legacy", "sobol"), default="cmaes")
    parser.add_argument("--trials", type=int, default=128)
    args = parser.parse_args()
    plan, bt, result = run(args.sampler, trials=args.trials)
    print(json.dumps(plan.assessment.metadata(), indent=2))
    bt.show_metrics()
