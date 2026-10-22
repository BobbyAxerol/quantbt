"""E03 scalar opt-ins; synthetic strategies demonstrate contracts, not edge.

Run: python -m examples.wfo_meta_scalar --target unit --mode shadow
Structural ladder uses the actual legacy high/low engine, not dynamic orders.
"""

import argparse
from dataclasses import replace

import numpy as np
import pandas as pd

from quantbt import QuantBTEndpoint
from quantbt.optimization.meta_selection.config import MetaHistoryContext
from quantbt.optimization.meta_selection.history import MetaHistory
from quantbt.optimization.meta_selection.domains.scalar_contract import canonical_scalar_route


PARAM_RANGES = {"window": (3, 31, 2)}


def market(bars=850):
    index = pd.date_range("2020-01-01", periods=bars, freq="1D", tz="UTC")
    t = np.arange(bars, dtype=float)
    close = 100 + .025*t + 3*np.sin(t/13) + np.cos(t/5)
    return pd.DataFrame(dict(open=close, high=close+1, low=close-1,
                             close=close, volume=1000+t), index=index)


def strategy(data, params, train_index, test_index, fold):
    history = data.loc[:test_index[-1]]
    signal = (history.close > history.close.rolling(int(params["window"])).mean()).astype(float)
    return signal.reindex(test_index).fillna(0.0)


def make_endpoint(mode, *, observer, min_origins, policy):
    return QuantBTEndpoint.walk_forward(strategy_class=strategy,
        split_mode="2021-01-01", split_frequency="quarterly", window_mode="rolling",
        train_window="180D", optimization_mode="mode_4_is_only_robust",
        optimization_schedule="per_fold_causal", optuna_trials=6, random_seed=731,
        initial_capital=20000., alloc_per_trade=1000., leverage=3., fee_rate=.0005,
        use_funding=False, target_runtime="numba", optimization_config=dict(
            scoring_backend="endpoint", use_scalar_trial_scoring=False, wfo_execution_reuse="off",
            top_is_fraction=.5, flat_eps=1., flat_min_samples=1, is_subperiods=3,
            min_trades_per_year=100, trade_penalty_factor=.5,
            meta_selection=dict(mode=mode, label_observer=observer,
                                min_matured_origins=min_origins, native_batch_policy=policy)))


def ladder_strategy(data, params, train_index, test_index, fold):
    history = data.loc[:test_index[-1]]
    average = history.close.rolling(int(params["window"])).mean()
    # A simple causal mean-reversion ladder with a flat band. Signed caps
    # enable base/safety orders; the financial engine decides actual fills.
    distance = history.close / average - 1.0
    signal = np.sign(-distance).where(distance.abs() > 0.01, 0.0) * 3.0
    return signal.reindex(test_index).fillna(0.0).astype(float)


def make_scalar_endpoint(target="unit", backend="auto", mode="shadow", *,
                         prepared="off", policy="auto", support=12, observer=True, runtime="numba"):
    original = make_endpoint(mode, observer=observer, min_origins=support, policy=policy)
    canonical = canonical_scalar_route(target)
    sizing = "%_equity" if canonical == "pct_equity" else canonical
    config = original.config
    wf = replace(config.walkforward_config, target_mode=target,
                 metadata={**config.walkforward_config.metadata, "native_prepared_wfo": prepared})
    return QuantBTEndpoint(replace(config, walkforward_config=wf,
        walkforward_target_mode=target, sizing=sizing, backend=backend,
        target_runtime=runtime,
        fee=0.001, fee_rate=0.0005,
        alloc_per_trade=0.5 if canonical == "pct_equity" else 1000.0,
        strategy_class=ladder_strategy if canonical == "dca_ladder" else strategy,
        dca_kwargs=dict(dca_base_notional=1000.0, dca_safety_notional=1000.0,
                        dca_step_pct=.02, dca_max_safety_orders=2,
                        dca_take_profit_pct=.04) if canonical == "dca_ladder" else {}))


def execute_scalar(target="unit", backend="auto", mode="shadow", *, data=None,
                   prepared="off", policy="auto", support=12, observer=True, native_module=None, runtime="numba"):
    endpoint = make_scalar_endpoint(target, backend, mode, prepared=prepared,
                                    policy=policy, support=support, observer=observer, runtime=runtime)
    context = MetaHistoryContext(MetaHistory(), "public-scalar-demo", "SYNTHETIC-linear",
        "1D", "e03-demo", native_module=native_module, clock=lambda fold, stage, elapsed: fold.train_index[-1]
        + pd.Timedelta(seconds={"search": 10, "fit": 20, "seal": 30}[stage]))
    result = endpoint.backtest(data=market() if data is None else data, param_ranges=PARAM_RANGES,
                              **({"meta_history": context} if mode != "off" else {}))
    return endpoint, result, context


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", choices=("signal_notional", "notional", "unit", "pct_equity", "dca_ladder"), default="unit")
    parser.add_argument("--backend", choices=("auto", "native_vectorized", "native_event", "legacy"), default="auto")
    parser.add_argument("--mode", choices=("off", "shadow", "active"), default="shadow")
    args = parser.parse_args()
    endpoint, result, _ = execute_scalar(args.target, args.backend, args.mode)
    endpoint.show_metrics()
    print(result.metadata["walk_forward"].get("meta_selection", {}).get("domain_adapter"))
