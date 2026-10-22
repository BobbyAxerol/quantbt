"""Bounded original package account, synthetic software evidence only.

Run: python -m examples.wfo_meta_package --kind basis --mode shadow
"""

import argparse
from dataclasses import replace

import numpy as np
import pandas as pd

from quantbt import (QuantBTEndpoint, ArbitrageLeg, BasisArbitrageSpec,
    StatArbPairSpec, HedgePolicy, HedgePolicyKind, SizingPolicy, SizingPolicyKind)
from quantbt.core.schema import BasketSpec, BasketLegSpec
from quantbt.optimization.meta_selection.config import MetaHistoryContext
from quantbt.optimization.meta_selection.history import MetaHistory
from examples.wfo_meta_portfolio import SYMBOLS, PARAM_RANGES, market, make_endpoint as portfolio_endpoint


def package_spec(kind):
    if kind == "basket":
        return BasketSpec("qms-demo", (BasketLegSpec(SYMBOLS[0], 1.), BasketLegSpec(SYMBOLS[1], -1.)), 2000.)
    cls = {"basis": BasisArbitrageSpec, "stat_pair": StatArbPairSpec}[kind]
    return cls(arb_id="qms-demo", legs=tuple(ArbitrageLeg(s, r, asset_class="crypto",
        funding_enabled=True) for s, r in zip(SYMBOLS, (1., -1.))),
        hedge_policy=HedgePolicy(HedgePolicyKind.BASE_QTY_EQUAL),
        sizing_policy=SizingPolicy(SizingPolicyKind.TARGET_GROSS_NOTIONAL, notional=2000.))


def strategy(data, params, train_index, test_index, fold):
    spread = data[SYMBOLS[0]].close / data[SYMBOLS[1]].close
    return np.sign(spread - spread.rolling(int(params["window"])).mean()).reindex(test_index).fillna(0.)


def make_endpoint(mode="shadow", *, kind="basket", cache=True, witness=True, support=12,
                  policy="auto", **kwargs):
    cfg = portfolio_endpoint(mode, cache=cache, witness=witness, support=support, policy=policy).config
    route = "basket" if kind == "basket" else "arbitrage"
    spec = package_spec(kind)
    wf = replace(cfg.walkforward_config, target_mode=route)
    return QuantBTEndpoint(replace(cfg, walkforward_config=wf, walkforward_target_mode=route,
        backend="native_event", strategy_class=strategy,
        basket=spec if route == "basket" else None,
        arbitrage_spec=spec if route == "arbitrage" else None, **kwargs))


def execute(mode="shadow", *, data=None, kind="basket", context=None, native_module=None, **kwargs):
    endpoint = make_endpoint(mode, kind=kind, **kwargs)
    context = context or MetaHistoryContext(MetaHistory(), "public-package-demo", "SYNTHETIC-two-linear",
        "1D", "e05-demo", native_module=native_module,
        clock=lambda fold, stage, elapsed: fold.train_index[-1] + pd.Timedelta(
            seconds={"search": 10, "fit": 20, "seal": 30}[stage]))
    result = endpoint.backtest(data=market() if data is None else data, param_ranges=PARAM_RANGES,
        **({"meta_history": context} if mode != "off" else {}))
    return endpoint, result, context


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kind", choices=("basket", "basis", "stat_pair"), default="basket")
    parser.add_argument("--mode", choices=("off", "shadow", "active"), default="shadow")
    endpoint, result, _ = execute(**vars(parser.parse_args()))
    endpoint.show_metrics()
    print(result.metadata["walk_forward"].get("meta_selection", {}).get("domain_adapter"))
