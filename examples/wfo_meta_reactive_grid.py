"""Public synthetic fill-feedback grid for reset-flat W3 software checks."""

from quantbt import OrderSide, StrategyContextRequirements
from quantbt.strategies.reactive_wfo import STRICT_CAUSAL_CACHE_CONTRACT_V1


class FillFeedbackGrid:
    quantbt_reactive_numeric_v1 = True
    quantbt_requirements = StrategyContextRequirements(
        market=("open", "high", "low", "close"), positions=("qty",),
        account=("equity", "available_equity", "initial_margin", "maintenance_margin", "liquidated"),
        fills="new_only", events="new_only", active_orders="snapshot", context_mode="numeric")

    def __init__(self, *, task, window):
        self.task, self.window = task, int(window)
        self.fill_feedback_count = 0

    def reset(self, *, seed, task):
        self.task = task
        self.fill_feedback_count = 0

    def on_bar_close(self, context, out):
        elapsed = int(context.bar_index) - int(self.task.start_bar)
        for row in range(context.new_fill_count):
            self.fill_feedback_count += 1
            if context.fill_side(row) > 0:
                out.limit(0, OrderSide.SELL, context.fill_qty(row),
                          context.fill_price(row) * 1.003, reduce_only=True)
        if elapsed % (2 * self.window) == 0:
            out.cancel_all(symbol_id=0)
            qty = context.position_qty(0)
            if qty > 0:
                out.market(0, OrderSide.SELL, qty, reduce_only=True)
            else:
                out.limit(0, OrderSide.BUY, .5, context.close(0) * .998)

    def quantbt_state_fingerprint(self):
        return self.window, self.fill_feedback_count


class PreparedGrid:
    causal_cache_contract = STRICT_CAUSAL_CACHE_CONTRACT_V1

    def build_strategy(self, *, params, task):
        return FillFeedbackGrid(task=task, window=params["window"])

    def close(self):
        pass


class GridFactory:
    def prepare_reactive_wfo(self, *, data, folds, static_config):
        return PreparedGrid()


def run(mode="shadow", worker="inprocess"):
    """Run public synthetic history; no private data or continuous-account claim."""
    from dataclasses import replace
    import pandas as pd
    from examples.wfo_meta_execution import market
    from examples.wfo_reactive_samplers import configuration, execute
    from quantbt.optimization.meta_selection.config import MetaHistoryContext
    from quantbt.optimization.meta_selection.history import MetaHistory

    data = market("event_driven", end="2023-05-31").assign(funding_rate=.0001)
    config = replace(configuration(schedule="per_fold_causal", trials=8),
        split_mode="2021-04-01", train_window="90D", random_seed=731,
        meta_selection=dict(mode=mode, label_observer=True, min_matured_origins=12,
                            lambda_reg=10., reporting_lag_seconds=86400.))
    context = MetaHistoryContext(MetaHistory(), "public-grid-example", "SYNTHETIC-linear",
        "1D", "synthetic", clock=lambda fold, stage, elapsed: fold.train_index[-1]
        + pd.Timedelta(seconds={"search": 10, "fit": 20, "seal": 30}[stage]))
    result = execute(worker=worker, config=config, data=data, factory=GridFactory(),
        ranges={"window": (3, 9, 2)}, meta_history=context if mode != "off" else None)
    meta = result.metadata.get("meta_selection", {})
    return dict(folds=len(result.folds), params_by_fold=result.params_by_fold,
        continuous_equity_available=result.metadata["continuous_equity_available"],
        fit_count=sum(r["final_selection_reason"] == "META_MODEL_PROPOSAL" for r in meta.get("records", ())),
        observed_revisions=len(meta.get("observed_revisions", ())),
        transport=meta.get("witness_transport"), economic_promotion=False)


if __name__ == "__main__":
    import argparse
    import json
    import optuna

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("off", "shadow", "active"), default="shadow")
    parser.add_argument("--worker", choices=("inprocess", "process"), default="inprocess")
    args = parser.parse_args()
    optuna.logging.set_verbosity(optuna.logging.WARNING)
    print(json.dumps(run(args.mode, args.worker), sort_keys=True))
