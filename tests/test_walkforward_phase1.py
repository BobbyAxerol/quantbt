from __future__ import annotations

import pandas as pd
import numpy as np

from quantbt import (
    ArbitrageLeg,
    BasisArbitrageSpec,
    ContractType,
    HedgePolicy,
    HedgePolicyKind,
    QuantBTEndpoint,
    SizingPolicy,
    SizingPolicyKind,
    WalkForwardConfig,
    WalkForwardEngine,
    WalkForwardTrialRecord,
    score_strategy_output,
    select_flat_minima_record,
    stationary_bootstrap_sharpes,
)


def _bars(index, close=100.0):
    return pd.DataFrame(
        {
            "open": float(close),
            "high": float(close) * 1.01,
            "low": float(close) * 0.99,
            "close": float(close),
            "volume": 1_000.0,
        },
        index=index,
    )


def _idx():
    return pd.date_range("2021-07-01", "2022-09-30", freq="1D", tz="UTC")


def test_walkforward_phase1_splitter_has_no_lookahead_and_stitches_oos_series():
    idx = _idx()

    def strategy(data, params, train_index, test_index, fold):
        return pd.Series(float(fold.fold_id + 1), index=test_index)

    engine = WalkForwardEngine(
        strategy=strategy,
        config=WalkForwardConfig(split_mode="walk_forward_2022", split_frequency="quarterly"),
    )
    result = engine.run(data=_bars(idx), params={"window": 10})

    assert len(result.folds) == 3
    for fold in result.folds:
        assert fold.train_index.max() < fold.test_index.min()
    assert result.oos_output.loc["2021-12-31"] == 0.0
    assert result.oos_output.loc["2022-01-01"] == 1.0
    assert result.oos_output.loc["2022-04-01"] == 2.0
    assert result.fold_table["train_bars"].min() > 0


def test_walkforward_endpoint_routes_stitched_signal_to_signal_notional():
    idx = _idx()

    def strategy(data, params, train_index, test_index, fold):
        return pd.Series(1.0, index=test_index)

    bt = QuantBTEndpoint.walk_forward(
        strategy_class=strategy,
        split_mode="walk_forward_2022",
        split_frequency="quarterly",
        target_mode="signal_notional",
        initial_capital=20_000.0,
        leverage=5.0,
        alloc_per_trade=1_000.0,
        fee_rate=0.0,
        use_funding=False,
    )
    result = bt.backtest(data=_bars(idx), symbols=["BTC"], params={"window": 10})

    assert result.metadata["walk_forward"]["n_folds"] == 3
    assert result.metadata["backend"] == "native_vectorized"
    assert result.positions["Position_BTC"].loc["2022-01-02"] > 0.0


def test_walkforward_endpoint_routes_pct_equity_to_legacy_backtester():
    idx = _idx()

    def strategy(data, params, train_index, test_index, fold):
        return pd.Series(0.5, index=test_index)

    bt = QuantBTEndpoint.walk_forward(
        strategy_class=strategy,
        split_mode=2022,
        split_frequency="quarterly",
        target_mode="pct_equity",
        initial_capital=20_000.0,
        leverage=5.0,
        alloc_per_trade=0.5,
        fee=0.0,
        use_funding=False,
    )
    result = bt.backtest(data=_bars(idx), params={"window": 10})

    assert result.metadata["walk_forward"]["target_mode"] == "pct_equity"
    assert result.metadata["hedge_type"] == "pct_equity"


def test_walkforward_endpoint_routes_dataframe_output_to_portfolio():
    idx = _idx()
    data = {"BTC": _bars(idx, 100.0), "ETH": _bars(idx, 10.0)}

    def strategy(data, params, train_index, test_index, fold):
        return pd.DataFrame({"BTC": 1.0, "ETH": -1.0}, index=test_index)

    bt = QuantBTEndpoint.walk_forward(
        strategy_class=strategy,
        split_mode=2022,
        split_frequency="quarterly",
        target_mode="portfolio",
        portfolio_mode="longshort",
        initial_capital=100_000.0,
        leverage=5.0,
        alloc_per_trade=1_000.0,
        fee=0.0,
        use_funding=False,
    )
    result = bt.backtest(data=data, params={"window": 10})

    assert result.metadata["backend"] == "legacy_portfolio"
    assert result.metadata["walk_forward"]["target_mode"] == "portfolio"
    assert "Position_BTC" in result.positions.columns
    assert "Position_ETH" in result.positions.columns


def test_walkforward_endpoint_routes_supported_arbitrage_signal():
    idx = _idx()
    data = {
        "PERP": _bars(idx, 100.0),
        "QUARTERLY": _bars(idx, 101.0),
    }
    spec = BasisArbitrageSpec(
        arb_id="WFO_BASIS",
        legs=(
            ArbitrageLeg("PERP", -1.0, role="perp", contract_type=ContractType.LINEAR),
            ArbitrageLeg("QUARTERLY", 1.0, role="quarterly", contract_type=ContractType.LINEAR),
        ),
        hedge_policy=HedgePolicy(HedgePolicyKind.BASE_QTY_EQUAL),
        sizing_policy=SizingPolicy(
            SizingPolicyKind.TARGET_NOTIONAL_TO_BASE_QTY,
            notional=1_000.0,
            reference_symbol="PERP",
        ),
    )

    def strategy(data, params, train_index, test_index, fold):
        return pd.Series(1.0, index=test_index)

    bt = QuantBTEndpoint.walk_forward(
        strategy_class=strategy,
        split_mode=2022,
        split_frequency="quarterly",
        target_mode="arbitrage",
        backend="native_vectorized",
        arbitrage_spec=spec,
        initial_capital=100_000.0,
        leverage=5.0,
        fee_rate=0.0,
        use_funding=False,
    )
    result = bt.backtest(data=data, params={"window": 10})

    assert result.metadata["engine"] == "units_v2_basis_arbitrage"
    assert result.metadata["walk_forward"]["target_mode"] == "arbitrage"
    assert "package_target_units" in result.metadata


def test_walkforward_phase2_fixed_params_expose_fold_metrics_and_best_trial():
    idx = _idx()
    data = _bars(idx)
    data["close"] = 100.0 + pd.Series(range(len(idx)), index=idx) * 0.1

    def strategy(data, params, train_index, test_index, fold):
        return pd.Series(float(params["side"]), index=test_index)

    engine = WalkForwardEngine(
        strategy=strategy,
        config=WalkForwardConfig(split_mode=2022, split_frequency="quarterly"),
    )
    result = engine.run(data=data, params={"side": 1.0})

    assert result.metadata["engine"] == "walk_forward_phase3"
    assert result.best_trial["params"] == {"side": 1.0}
    assert result.best_trial["fold_metrics"]
    assert set(["objective", "mean_is_sharpe", "mean_oos_sharpe", "mean_decay"]).issubset(result.trial_table.columns)


def test_walkforward_phase2_mode_1_decay_optimizes_with_optuna_and_records_ledger():
    idx = _idx()
    data = _bars(idx)
    data["close"] = 100.0 + pd.Series(range(len(idx)), index=idx) * 0.1

    def strategy(data, params, train_index, test_index, fold):
        side = 1.0 if int(params["go_long"]) == 1 else -1.0
        return pd.Series(side, index=test_index)

    bt = QuantBTEndpoint.walk_forward(
        strategy_class=strategy,
        split_mode=2022,
        split_frequency="quarterly",
        target_mode="signal_notional",
        optimization_mode="mode_1_decay",
        optimization_config={"decay_lambda": 0.5, "decay_gamma": 0.5},
        optuna_trials=12,
        random_seed=7,
        initial_capital=20_000.0,
        leverage=5.0,
        alloc_per_trade=1_000.0,
        fee_rate=0.0,
        use_funding=False,
    )
    result = bt.backtest(data=data, symbols=["BTC"], param_ranges={"go_long": (0, 1, 1)})
    wf = result.metadata["walk_forward"]

    assert wf["optimization_mode"] == "mode_1_decay"
    assert wf["params"]["go_long"] == 1
    assert wf["best_trial"]["objective"] == wf["trial_table"]["objective"].max()
    assert wf["config_hash"]
    assert wf["data_hash"]


def test_walkforward_score_strategy_output_is_transparent_return_proxy():
    idx = pd.date_range("2024-01-01", periods=4, freq="1D", tz="UTC")
    data = _bars(idx)
    data["close"] = [100.0, 110.0, 121.0, 133.1]
    signal = pd.Series([0.0, 1.0, 1.0, 1.0], index=idx)

    metrics = score_strategy_output(data, signal, idx)

    assert metrics["turnover"] == 1.0
    assert metrics["mean_return"] > 0.0


def test_walkforward_phase3_score_helpers_match_numba_and_python_paths():
    idx = pd.date_range("2024-01-01", periods=8, freq="1D", tz="UTC")
    data = _bars(idx)
    data["close"] = [100.0, 101.0, 100.5, 102.0, 103.0, 102.5, 104.0, 105.0]
    signal = pd.Series([0.0, 1.0, 1.0, -1.0, -1.0, 0.0, 1.0, 1.0], index=idx)

    py_metrics = score_strategy_output(data, signal, idx, use_numba=False)
    accelerated_metrics = score_strategy_output(data, signal, idx, use_numba=True)

    assert py_metrics == accelerated_metrics


def test_walkforward_phase3_stationary_bootstrap_is_seed_reproducible():
    returns = np.array([0.0, 0.01, -0.004, 0.02, -0.003, 0.006], dtype=float)

    first = stationary_bootstrap_sharpes(returns, n_samples=32, block_length=3, seed=11, use_numba=False)
    second = stationary_bootstrap_sharpes(returns, n_samples=32, block_length=3, seed=11, use_numba=True)
    different = stationary_bootstrap_sharpes(returns, n_samples=32, block_length=3, seed=12, use_numba=False)

    np.testing.assert_allclose(first, second)
    assert not np.allclose(first, different)


def test_walkforward_phase3_mode_2_sbb_optimizes_and_records_bootstrap_metrics():
    idx = _idx()
    data = _bars(idx)
    data["close"] = 100.0 + pd.Series(range(len(idx)), index=idx) * 0.1

    def strategy(data, params, train_index, test_index, fold):
        side = 1.0 if int(params["go_long"]) == 1 else -1.0
        return pd.Series(side, index=test_index)

    bt = QuantBTEndpoint.walk_forward(
        strategy_class=strategy,
        split_mode=2022,
        split_frequency="quarterly",
        target_mode="signal_notional",
        optimization_mode="mode_2_sbb",
        optimization_config={"sbb_samples": 32, "sbb_block_length": 10, "use_numba": True},
        optuna_trials=12,
        random_seed=13,
        initial_capital=20_000.0,
        leverage=5.0,
        alloc_per_trade=1_000.0,
        fee_rate=0.0,
        use_funding=False,
    )
    result = bt.backtest(data=data, symbols=["BTC"], param_ranges={"go_long": (0, 1, 1)})
    wf = result.metadata["walk_forward"]

    assert wf["optimization_mode"] == "mode_2_sbb"
    assert wf["params"]["go_long"] == 1
    assert wf["best_trial"]["selection_metadata"]["objective_mode"] == "mode_2_sbb"
    assert "synthetic_oos_sharpe" in wf["best_trial"]["fold_metrics"][0]


def test_walkforward_phase3_flat_minima_selector_prefers_dense_cluster_over_sharp_peak():
    records = [
        WalkForwardTrialRecord(0, {"x": 90}, 10.0, 0.0, 10.0, 0.0, 0.0, []),
        WalkForwardTrialRecord(1, {"x": 20}, 9.0, 0.0, 9.0, 0.0, 0.0, []),
        WalkForwardTrialRecord(2, {"x": 21}, 8.9, 0.0, 8.9, 0.0, 0.0, []),
        WalkForwardTrialRecord(3, {"x": 22}, 8.8, 0.0, 8.8, 0.0, 0.0, []),
        WalkForwardTrialRecord(4, {"x": 65}, 4.0, 0.0, 4.0, 0.0, 0.0, []),
    ]
    cfg = WalkForwardConfig(
        optimization_mode="mode_3_flat_minima",
        flat_top_fraction=1.0,
        flat_eps=0.03,
        flat_min_samples=2,
    )

    selected = select_flat_minima_record(records, {"x": (0, 100, 1)}, config=cfg)

    assert selected.params["x"] in {20, 21, 22}
    assert selected.selection_metadata["objective_mode"] == "mode_3_flat_minima"
    assert selected.selection_metadata["cluster_size"] == 3
