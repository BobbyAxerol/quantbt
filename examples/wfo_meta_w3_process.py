"""Synthetic W3 meta, reset-flat, original-pass witnesses; no private alpha.

Run from an installed local C02 pair, in a dedicated single-thread process:
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 python examples/wfo_meta_w3_process.py
"""

import argparse
import json

import numpy as np
import optuna
import pandas as pd

from quantbt import QuantBTEndpoint, OrderSide, StrategyContextRequirements
from quantbt.backends.reactive_wfo_support import ReactiveWfoRuntimeConfigV1
from quantbt.optimization.meta_selection.config import MetaHistoryContext
from quantbt.optimization.meta_selection.history import MetaHistory
from quantbt.strategies.reactive_wfo import STRICT_CAUSAL_CACHE_CONTRACT_V1
from quantbt.walkforward import WalkForwardConfig


class Strategy:
    quantbt_reactive_numeric_v1 = True
    quantbt_requirements = StrategyContextRequirements(
        market=("open", "close"), account=("equity",), positions=("qty",), context_mode="numeric")

    def __init__(self, params, task):
        self.params, self.task = params, task

    def reset(self, *, seed, task):
        self.task = task

    def on_bar_close(self, context, out):
        bar = int(context.bar_index)
        direction = self.params["direction"]
        if bar == self.task.start_bar:
            out.market(0, OrderSide.BUY if direction > 0 else OrderSide.SELL, 1.)
        elif bar == min(self.task.end_bar - 2, self.task.start_bar + 4):
            out.market(0, OrderSide.SELL if direction > 0 else OrderSide.BUY, 1., reduce_only=True)


class Prepared:
    causal_cache_contract = STRICT_CAUSAL_CACHE_CONTRACT_V1

    def build_strategy(self, *, params, task):
        return Strategy(params, task)

    def close(self):
        pass


class Factory:
    def prepare_reactive_wfo(self, *, data, folds, static_config):
        return Prepared()


def run(worker_mode="process"):
    optuna.logging.set_verbosity(optuna.logging.WARNING)
    index = pd.date_range("2024-01-01", periods=180, freq="1D", tz="UTC")
    close = 100. + .12 * np.arange(len(index)) + np.sin(np.arange(len(index)) / 8.)
    data = pd.DataFrame(dict(open=np.r_[close[0], close[:-1]], high=close + .8,
        low=close - .8, close=close, volume=1000., funding_rate=.0001), index=index)
    endpoint = QuantBTEndpoint.native_event_strategy(initial_capital=20_000., leverage=3.,
        fee_rate=.0004, use_funding=True, funding_rate=data.funding_rate,
        native_backend="rust", reactive_runtime="numeric_every_bar_v1",
        reactive_kernel_mode="single_pass", execution_contract="event_lifecycle_v3_next_open")
    config = WalkForwardConfig(split_mode="2024-03-01", split_frequency="monthly",
        window_mode="rolling", train_window="45D", min_train_bars=20, min_test_bars=8,
        target_mode="signal_notional", optimization_mode="mode_4_is_only_robust",
        optimization_schedule="per_fold_causal", candidate_selection_metric="is_only_robust",
        fold_account_policy="reset_flat", fold_boundary_position_policy="reset_flat",
        optuna_trials=8, random_seed=17, is_subperiods=2, top_is_fraction=1.,
        flat_eps=1., flat_min_samples=1, scoring_backend="endpoint", calendar_contract="exact_v2",
        strategy_lifecycle_policy="isolated_v1",
        meta_selection=dict(mode="active", label_observer=True, min_matured_origins=1))
    runtime = endpoint.prepare_reactive_walk_forward(data=data, strategy_factory=Factory(),
        walkforward_config=config, symbols=["BTCUSDT"],
        runtime_config=ReactiveWfoRuntimeConfigV1(worker_mode=worker_mode))
    try:
        result = runtime.backtest(param_ranges={"direction": [-1., 1.]},
            meta_history=MetaHistoryContext(MetaHistory(), "example", "BTC-linear", "1D", "synthetic"))
        return dict(folds=len(result.folds), params_by_fold=result.params_by_fold,
            continuous_equity_available=result.metadata["continuous_equity_available"],
            transport=result.metadata["meta_selection"]["witness_transport"])
    finally:
        runtime.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker-mode", choices=("inprocess", "process"), default="process")
    print(json.dumps(run(parser.parse_args().worker_mode), sort_keys=True))
