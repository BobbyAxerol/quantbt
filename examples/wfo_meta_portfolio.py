"""Original shared-account WFO; synthetic engineering evidence, not alpha edge.

Run: python -m examples.wfo_meta_portfolio --mode shadow
"""

import argparse

import numpy as np
import pandas as pd

from quantbt import QuantBTEndpoint
from quantbt.optimization.meta_selection.config import MetaHistoryContext
from quantbt.optimization.meta_selection.history import MetaHistory


SYMBOLS = ("SYNTH-A", "SYNTH-B")
PARAM_RANGES = {"window": (3, 31, 2)}


def market(bars=730):
    index = pd.date_range("2020-01-01", periods=bars, freq="1D", tz="UTC")
    t = np.arange(bars, dtype=float)
    out = {}
    for j, symbol in enumerate(SYMBOLS):
        close = (100 + .025*t + (3+j)*np.sin(t/(13+j)) + np.cos(t/(5+j)))*(j+1)
        out[symbol] = pd.DataFrame(dict(open=close, high=close+1, low=close-1,
            close=close, volume=1000+t), index=index)
    return out


def strategy(data, params, train_index, test_index, fold):
    return pd.DataFrame({s: np.sign(frame.close - frame.close.rolling(int(params["window"])).mean())
        .reindex(test_index).fillna(0.) for s, frame in data.items()}, index=test_index)


def make_endpoint(mode="shadow", *, sizing="target_units", portfolio_mode="longshort",
                  cache=True, witness=True, support=12, observer=True, policy="auto", **kwargs):
    return QuantBTEndpoint.walk_forward(strategy_class=strategy, symbols=list(SYMBOLS),
        target_mode="portfolio", backend="native_portfolio", sizing=sizing,
        portfolio_mode=portfolio_mode, split_mode="2021-01-01", split_frequency="quarterly",
        window_mode="rolling", train_window="180D", optimization_mode="mode_4_is_only_robust",
        optimization_schedule="per_fold_causal", optuna_trials=6, random_seed=731,
        initial_capital=20000., alloc_per_trade=1000., leverage=3., fee_rate=.0005,
        use_funding=False, optimization_config=dict(scoring_backend="endpoint",
            use_scalar_trial_scoring=False, use_prepared_scoring_cache=cache,
            metadata=dict(use_prepared_meta_witness=witness),
            native_prepared_wfo="off", wfo_execution_reuse="off",
            top_is_fraction=.5, flat_eps=1., flat_min_samples=1, is_subperiods=3,
            meta_selection=dict(mode=mode, label_observer=observer,
                min_matured_origins=support, native_batch_policy=policy)), **kwargs)


def execute(mode="shadow", *, data=None, history=None, native_module=None, **kwargs):
    endpoint = make_endpoint(mode, **kwargs)
    context = MetaHistoryContext(history or MetaHistory(), "public-portfolio-demo", "SYNTHETIC-two-linear",
        "1D", "e04-demo", native_module=native_module,
        clock=lambda fold, stage, elapsed: fold.train_index[-1] + pd.Timedelta(
            seconds={"search": 10, "fit": 20, "seal": 30}[stage]))
    result = endpoint.backtest(data=market() if data is None else data, param_ranges=PARAM_RANGES,
        **({"meta_history": context} if mode != "off" else {}))
    return endpoint, result, context


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("off", "shadow", "active"), default="shadow")
    args = parser.parse_args()
    endpoint, result, _ = execute(args.mode)
    endpoint.show_metrics()
    print(result.metadata["walk_forward"].get("meta_selection", {}).get("domain_adapter"))
