"""Runnable synthetic W3 recipe/scheduler example; not an economic study."""

import json

import numpy as np
import pandas as pd

from quantbt import (CandidateWakePlansV1, ExecutionConfig, OrderSide, QuantBTEndpoint,
                     StrategyContextRequirements, WakePlanV1)
from quantbt.backends.reactive_wfo_support import ReactiveWfoRuntimeConfigV1
from quantbt.optimization import SamplerConfig
from quantbt.strategies.reactive_wfo import STRICT_CAUSAL_CACHE_CONTRACT_V1
from quantbt.walkforward import WalkForwardConfig

RECIPES = ("tpe_legacy", "tpe_multivariate_group", "cmaes", "sobol")
RANGES = {"qty": {"kind": "float", "low": .5, "high": 2.},
          "hold": {"kind": "integer", "low": 2, "high": 8}, "direction": 1.}
REQUIREMENTS = StrategyContextRequirements(market=("open", "high", "low", "close"),
    account=("equity",), positions=("qty",), context_mode="numeric")


def market():
    index = pd.date_range("2024-01-01", periods=180, freq="1D", tz="UTC")
    t = np.arange(len(index))
    close = 100 + .08 * t + 2.4 * np.sin(t / 7.)
    return pd.DataFrame(dict(open=np.r_[close[0], close[:-1]], high=close + .8,
        low=close - .8, close=close, volume=1000., funding_rate=.0001), index=index)


def commands(params, task, bar, writer):
    side = OrderSide.BUY if params["direction"] > 0 else OrderSide.SELL
    hold = params["hold"] + int(params.get("extra", 0))
    exit_bar = min(task.end_bar - 2, task.start_bar + hold)
    if bar == task.start_bar:
        writer.market(0, side, params["qty"])
    elif bar == exit_bar:
        writer.market(0, OrderSide.SELL if side == OrderSide.BUY else OrderSide.BUY,
                      params["qty"], reduce_only=True)
    return exit_bar


class Strategy:
    quantbt_reactive_numeric_v1 = True
    quantbt_requirements = REQUIREMENTS

    def __init__(self, params, task):
        self.params, self.task = dict(params), task

    def reset(self, *, seed, task):
        self.task = task

    def on_bar_close(self, context, out):
        commands(self.params, self.task, int(context.bar_index), out)


class CandidateBatchStrategy:
    quantbt_reactive_candidate_batch_v1 = True
    quantbt_requirements = REQUIREMENTS

    def __init__(self, params_matrix, tasks):
        self.params, self.tasks = params_matrix, tasks

    def on_wake_batch(self, context_batch, out_batch):
        bar = int(context_batch.bar_index)
        plans = {}
        for raw in context_batch.candidate_ids:
            i = int(raw)
            exit_bar = commands(self.params[i], self.tasks[i], bar, out_batch.writer(i))
            plans[i] = WakePlanV1(next_bar=exit_bar) if bar == self.tasks[i].start_bar else WakePlanV1()
        return CandidateWakePlansV1(plans)


class Prepared:
    causal_cache_contract = STRICT_CAUSAL_CACHE_CONTRACT_V1

    def build_strategy(self, *, params, task):
        return Strategy(params, task)

    def build_candidate_batch(self, *, params_matrix, tasks):
        return CandidateBatchStrategy(params_matrix, tasks)

    def close(self):
        pass


class Factory:
    def prepare_reactive_wfo(self, *, data, folds, static_config):
        return Prepared()


def configuration(recipe="tpe_legacy", *, schedule="global", trials=16):
    return WalkForwardConfig(split_mode="2024-03-01", split_frequency="monthly",
        window_mode="rolling", train_window="45D", min_train_bars=20, min_test_bars=8,
        target_mode="signal_notional", optimization_mode="mode_4_is_only_robust",
        optimization_schedule=schedule, fold_account_policy="reset_flat",
        fold_boundary_position_policy="reset_flat", optuna_trials=trials, random_seed=731,
        candidate_selection_metric="is_only_robust", is_subperiods=1, top_is_fraction=1.,
        flat_eps=1., flat_min_samples=1, scoring_backend="endpoint",
        calendar_contract="exact_v2", strategy_lifecycle_policy="isolated_v1",
        sampler_config=SamplerConfig(name=recipe))


def execute(recipe="tpe_legacy", *, scheduler="certified_sequential_v1", worker="inprocess",
            config=None, ranges=None, candidate_matrix=None, data=None, factory=None, batch_size=None,
            meta_history=None):
    data = market() if data is None else data
    config = configuration(recipe) if config is None else config
    batch_size = (4 if scheduler == "throughput_batch_v1" else 1) if batch_size is None else batch_size
    endpoint = QuantBTEndpoint.native_event_strategy(initial_capital=20000., leverage=3.,
        fee_rate=.0004, use_funding=True, funding_rate=data.funding_rate,
        native_backend="rust", reactive_kernel_mode="single_pass",
        reactive_runtime="numeric_every_bar_v1", report_level="minimal",
        execution_contract="event_lifecycle_v3_next_open", execution=ExecutionConfig(slippage_bps=1.))
    runtime = endpoint.prepare_reactive_walk_forward(data=data, strategy_factory=factory or Factory(),
        walkforward_config=config, symbols=["BTC"], runtime_config=ReactiveWfoRuntimeConfigV1(
            optimizer_schedule=scheduler, worker_mode=worker, candidate_batch_size=batch_size))
    try:
        kwargs = {} if meta_history is None else {"meta_history": meta_history}
        return runtime.backtest(param_ranges=RANGES if ranges is None else ranges,
                                candidate_matrix=candidate_matrix, **kwargs)
    finally:
        runtime.close()


if __name__ == "__main__":
    import argparse
    import optuna

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sampler", choices=RECIPES, default="tpe_legacy")
    parser.add_argument("--scheduler", choices=("certified_sequential_v1", "throughput_batch_v1"),
                        default="certified_sequential_v1")
    parser.add_argument("--trials", type=int, default=16)
    args = parser.parse_args()
    optuna.logging.set_verbosity(optuna.logging.WARNING)
    result = execute(args.sampler, scheduler=args.scheduler,
                     config=configuration(args.sampler, trials=args.trials))
    print(json.dumps(dict(sampling_contract=result.metadata["sampling_contract"],
        continuous_equity_available=result.metadata["continuous_equity_available"],
        studies=[dict(recipe=s["recipe"], attempts=s["attempts"], states=s["states"],
                      relative_proposals=s["relative_proposal_trials"],
                      ask_tell_digest=s["ask_tell_digest"]) for s in result.metadata["sampler_studies"]])))
