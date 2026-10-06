"""C01 scalar nested meta demo; no private alpha or economic claim.

Run: python -m examples.wfo_meta_nested --target pct_equity --mode shadow
"""

import argparse
from dataclasses import replace

import pandas as pd

from quantbt import QuantBTEndpoint
from quantbt.optimization.meta_selection.config import MetaHistoryContext
from quantbt.optimization.meta_selection.history import MetaHistory
from examples.wfo_meta_scalar import make_scalar_endpoint, market, PARAM_RANGES


def make_nested_endpoint(target="pct_equity", mode="shadow", *, prepared="off", policy="auto"):
    backend = "legacy" if target in {"pct_equity", "dca_ladder"} else "native_vectorized"
    original = make_scalar_endpoint(target, backend, mode, prepared=prepared, policy=policy)
    wf = replace(original.config.walkforward_config, optimization_mode="mode_1_decay",
        candidate_selection_metric="robust_decay", inner_split_frequency="monthly",
        inner_window_mode="expanding", inner_train_window="30D", inner_min_folds=2)
    return QuantBTEndpoint(replace(original.config, walkforward_config=wf))


def execute_nested(target="pct_equity", mode="shadow", *, data=None, history=None):
    endpoint = make_nested_endpoint(target, mode)
    context = MetaHistoryContext(history if history is not None else MetaHistory(),
        "nested-demo", "SYNTHETIC-linear", "1D", "nested-demo-v1",
        clock=lambda fold, stage, elapsed: fold.train_index[-1] + pd.Timedelta(
            seconds={"search": 10, "fit": 20, "seal": 30}[stage]))
    result = endpoint.backtest(data=market() if data is None else data, param_ranges=PARAM_RANGES,
        **({"meta_history": context} if mode != "off" else {}))
    return endpoint, result, context


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--target", choices=("signal_notional", "notional", "unit", "pct_equity", "dca_ladder"), default="pct_equity")
    p.add_argument("--mode", choices=("off", "shadow", "active"), default="shadow")
    a = p.parse_args()
    endpoint, result, _ = execute_nested(a.target, a.mode)
    endpoint.show_metrics()
    wf = result.metadata["walk_forward"]
    print(wf["params_by_fold"])
    print(wf.get("meta_selection", {}).get("records", ()))
