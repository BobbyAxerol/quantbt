"""C05 opt-ins on existing WFO; synthetic contract example, not edge."""

from examples.wfo_meta_scalar import market
from quantbt import QuantBTEndpoint
from quantbt.optimization import SamplerConfig

PARAM_RANGES = {
    "use_filter": {"kind": "boolean"},
    "window": {"kind": "integer", "low": 3, "high": 31, "step": 2},
    "filter_window": {"kind": "integer", "low": 3, "high": 15, "step": 2,
                      "active_if": {"use_filter": True}},
}


def strategy(data, params, train_index, test_index, fold):
    history = data.loc[:test_index[-1]]
    signal = (history.close > history.close.rolling(params["window"]).mean()).astype(float)
    if params["use_filter"]:
        signal *= (history.close.diff(params["filter_window"]) > 0).astype(float)
    return signal.reindex(test_index).fillna(0.)


def execute():
    endpoint = QuantBTEndpoint.walk_forward(strategy_class=strategy,
        target_mode="pct_equity", optimization_mode="mode_4_is_only_robust",
        optimization_schedule="per_fold_causal", split_mode="2021-01-01",
        split_frequency="quarterly", window_mode="rolling", train_window="180D",
        optuna_trials=16, random_seed=731, initial_capital=20000., leverage=3.,
        alloc_per_trade=.5, fee_rate=.0005, use_funding=False,
        optimization_config=dict(scoring_backend="endpoint", is_subperiods=1,
            top_is_fraction=.5, flat_eps=1., flat_min_samples=1,
            sampler_config=SamplerConfig(name="sobol", sobol_policy="conditional_numeric_latent_v1"),
            flat_selector="feasible_support_projection_v1", native_prepared_wfo="off"))
    result = endpoint.backtest(data=market(520), param_ranges=PARAM_RANGES)
    return endpoint, result


if __name__ == "__main__":
    import optuna
    optuna.logging.set_verbosity(optuna.logging.WARNING)
    endpoint, result = execute()
    endpoint.show_metrics()
    wf = result.metadata["walk_forward"]
    print(wf["params_by_fold"])
    print(wf["sampler_studies"][0]["latent_stream"]["dimensions"])
