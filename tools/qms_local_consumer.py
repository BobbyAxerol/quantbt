"""Isolated installed W3 proof; no source imports, data download or publication."""

from dataclasses import replace
from hashlib import sha256
import importlib.metadata as metadata
import json
from pathlib import Path
import sys


def consume(*, core_version=None, native_version=None):
    import numpy as np
    import optuna
    import pandas as pd
    import quantbt
    from quantbt import QuantBTEndpoint, ExecutionConfig, OrderSide, StrategyContextRequirements
    from quantbt.optimization.meta_selection.config import MetaHistoryContext
    from quantbt.optimization.meta_selection.common import wire
    from quantbt.optimization.meta_selection.history import MetaHistory
    from quantbt.strategies.reactive_wfo import STRICT_CAUSAL_CACHE_CONTRACT_V1
    from quantbt.walkforward import WalkForwardConfig

    assert "site-packages" in Path(quantbt.__file__).resolve().parts
    import _quantbt_native as native

    actual_core = metadata.version("quantbt-engine")
    actual_native = metadata.version("quantbt-native")
    assert actual_core == quantbt.__version__
    assert actual_native == native.version()
    if core_version is not None:
        assert actual_core == core_version, "installed core version mismatch"
    if native_version is not None:
        assert actual_native == native_version, "installed native version mismatch"
    assert "site-packages" in Path(native.__file__).resolve().parts
    assert native.qms_numeric_descriptor_v1()["abi"] == "qms-numeric-v1"
    assert hasattr(native, "QMS_PREPARED_METRIC_SUPPORT_V1")
    optuna.logging.set_verbosity(optuna.logging.WARNING)
    index = pd.date_range("2024-01-01", periods=180, freq="1D", tz="UTC")
    t = np.arange(len(index))
    close = 100 + .12 * t + 1.4 * np.sin(t / 8)
    data = pd.DataFrame(dict(open=np.r_[close[0], close[:-1]], high=close + .8,
        low=close - .8, close=close, volume=1000., funding_rate=.0001), index=index)

    class Strategy:
        quantbt_reactive_numeric_v1 = True
        quantbt_requirements = StrategyContextRequirements(
            market=("open", "high", "low", "close"), account=("equity",),
            positions=("qty",), context_mode="numeric")

        def __init__(self, task, direction):
            self.task, self.direction = task, direction

        def reset(self, *, seed, task):
            self.task = task

        def on_bar_close(self, context, out):
            bar = int(context.bar_index)
            if bar == self.task.start_bar:
                out.market(0, OrderSide.BUY if self.direction > 0 else OrderSide.SELL, 1.)
            elif bar == min(self.task.end_bar - 2, self.task.start_bar + 4):
                out.market(0, OrderSide.SELL if self.direction > 0 else OrderSide.BUY,
                           1., reduce_only=True)

    class Prepared:
        causal_cache_contract = STRICT_CAUSAL_CACHE_CONTRACT_V1

        def build_strategy(self, *, params, task):
            return Strategy(task, params["direction"])

        def close(self):
            pass

    class Factory:
        def prepare_reactive_wfo(self, *, data, folds, static_config):
            return Prepared()

    config = WalkForwardConfig(split_mode="2024-03-01", split_frequency="monthly",
        window_mode="rolling", train_window="45D", min_train_bars=20, min_test_bars=8,
        target_mode="signal_notional", optimization_mode="mode_4_is_only_robust",
        optimization_schedule="per_fold_causal", fold_account_policy="reset_flat",
        fold_boundary_position_policy="reset_flat", optuna_trials=8, random_seed=17,
        candidate_selection_metric="is_only_robust", is_subperiods=2, top_is_fraction=1.,
        flat_eps=1., flat_min_samples=1, scoring_backend="endpoint",
        calendar_contract="exact_v2", strategy_lifecycle_policy="isolated_v1")

    def execute(mode):
        endpoint = QuantBTEndpoint.native_event_strategy(initial_capital=20000., leverage=3.,
            fee_rate=.0004, use_funding=True, funding_rate=data.funding_rate,
            native_backend="rust", reactive_kernel_mode="single_pass",
            reactive_runtime="numeric_every_bar_v1", report_level="minimal",
            execution_contract="event_lifecycle_v3_next_open", execution=ExecutionConfig(slippage_bps=1.))
        cfg = replace(config, meta_selection=None if mode is None else dict(mode=mode,
            native_batch_policy="require", min_matured_origins=1, label_observer=True))
        runtime = endpoint.prepare_reactive_walk_forward(data=data, strategy_factory=Factory(),
            walkforward_config=cfg, symbols=["BTC"])
        try:
            kwargs = {} if mode is None else {"meta_history": MetaHistoryContext(
                MetaHistory(), "installed-W3", "BTC-linear", "1D", "local-closure")}
            result = runtime.backtest(param_ranges={"direction": [-1., 1.]}, **kwargs)
            assert runtime._adapter is None and runtime._meta_boundary is None
            return result
        finally:
            runtime.close()

    off, shadow, active = execute(None), execute("shadow"), execute("active")
    np.testing.assert_array_equal(off.trial_table.objective, shadow.trial_table.objective)
    assert off.params_by_fold == shadow.params_by_fold
    for a, b in zip(off.fold_results, shadow.fold_results, strict=True):
        for field in ("equity", "returns", "positions", "fees", "funding"):
            np.testing.assert_array_equal(getattr(a.result, field), getattr(b.result, field))
    meta = active.metadata["meta_selection"]
    assert meta["observer_attempts"] > 0 and meta["observer_failures"] == 0
    assert not active.metadata["continuous_equity_available"]
    assert any(r["numeric_backend"]["selected_backend_by_block"].get("gram_solve") == "rust"
               for r in meta["records"])
    for record in meta["records"]:
        assert record["selected_params"] == active.params_by_fold[record["fold_id"]]
        assert record["current_outer_oos_used_for_selection"] is False
    return wire(dict(installed_origin=str(Path(quantbt.__file__).resolve()),
        core_version=actual_core, native_version=actual_native, python=sys.version,
        native_extension_sha256=sha256(Path(native.__file__).read_bytes()).hexdigest(),
        off_shadow_exact=True, observer_failures=0, folds=len(active.folds),
        same_pass=True, selected_lineage=True, closed=True,
        account_authority=meta["account_authority"],
        witness_reuse=meta["witness_reuse"], native_blocks=meta["records"][-1]["numeric_backend"]))


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--core-version")
    parser.add_argument("--native-version")
    args = parser.parse_args()
    print(json.dumps(consume(core_version=args.core_version,
                             native_version=args.native_version), sort_keys=True))
