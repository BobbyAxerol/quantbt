"""Approved nested cohort on the frozen PRE02 public software fixtures."""

from dataclasses import replace

from quantbt import QuantBTEndpoint
from quantbt.optimization.meta_selection.config import MetaHistoryContext
from quantbt.optimization.meta_selection.history import MetaHistory
from tests.meta_selection import pre_e06_02_support as original

ROUTES = original.ROUTES[:5]
CUTOFFS = original.CUTOFFS
RANGES = original.RANGES


def endpoint(route, data, mode, *, start="2020-04-01", prepared=False,
             numeric="reference", witness=True):
    old = original.endpoint(route, data, mode, start=start, prepared=prepared,
                            numeric=numeric, witness=witness)
    wf = replace(old.config.walkforward_config, optimization_mode="mode_1_decay",
        candidate_selection_metric="robust_decay", inner_split_frequency="monthly",
        inner_window_mode="expanding", inner_train_window="30D", inner_min_folds=2)
    return QuantBTEndpoint(replace(old.config, walkforward_config=wf))


def run(route, mode="shadow", *, data=None, history=None, start="2020-04-01",
        prepared=False, numeric="reference", witness=True, clock=original.replay_clock):
    data = original.tape(route) if data is None else data
    bt = endpoint(route, data, mode, start=start, prepared=prepared, numeric=numeric, witness=witness)
    ctx = MetaHistoryContext(history if history is not None else MetaHistory(),
        "pre-e06-public-synthetic", "pre-e06-"+route, "1D", "pre-e06-software-v1", clock=clock)
    result = bt.backtest(data=data, param_ranges=RANGES,
                        **({} if mode == "off" else {"meta_history": ctx}))
    return original.Run(route, bt, result, ctx, data)
