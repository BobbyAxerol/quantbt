from __future__ import annotations

import pandas as pd
import numpy as np
import pytest

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
    benchmark_walkforward_kernels,
    score_strategy_output,
    select_flat_minima_record,
    stationary_bootstrap_sharpes,
    synthetic_walkforward_sharpes,
    trade_frequency_penalty,
    validate_param_ranges,
    volatility_regime_labels,
    walkforward_support_matrix,
)
from quantbt.walkforward import _regime_bootstrap_indices


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


def test_train_test_split_single_fold_has_no_lookahead_and_stitches_holdout():
    idx = _idx()

    def strategy(data, params, train_index, test_index, fold):
        assert fold.fold_id == 0
        return pd.Series(float(params["side"]), index=test_index)

    engine = WalkForwardEngine(
        strategy=strategy,
        config=WalkForwardConfig(split_mode="2022-01-01", split_frequency="single"),
    )
    result = engine.run(data=_bars(idx), params={"side": 1.0})

    assert len(result.folds) == 1
    fold = result.folds[0]
    assert fold.train_index.max() < fold.test_index.min()
    assert result.oos_output.loc["2021-12-31"] == 0.0
    assert result.oos_output.loc["2022-01-01"] == 1.0
    assert result.oos_output.loc[idx[-1]] == 1.0
    assert result.metadata["split_frequency"] == "single"


def test_train_test_split_endpoint_runs_declared_fixed_params():
    idx = _idx()
    data = _bars(idx)
    data["close"] = 100.0 + pd.Series(range(len(idx)), index=idx) * 0.1

    def strategy(data, params, train_index, test_index, fold):
        return pd.Series(float(params["side"]), index=test_index)

    bt = QuantBTEndpoint.train_test_split(
        strategy_class=strategy,
        test_start="2022-01-01",
        target_mode="signal_notional",
        initial_capital=20_000.0,
        leverage=5.0,
        alloc_per_trade=1_000.0,
        fee_rate=0.0,
        use_funding=False,
    )
    result = bt.backtest(data=data, symbols=["BTC"], params={"side": 1.0})
    wf = result.metadata["walk_forward"]

    assert wf["split_frequency"] == "single"
    assert wf["n_folds"] == 1
    assert wf["params"] == {"side": 1.0}
    assert result.positions["Position_BTC"].loc["2022-01-01"] > 0.0


def test_train_test_split_metrics_default_to_test_scope():
    idx = _idx()
    data = _bars(idx)
    data["close"] = 100.0 + pd.Series(range(len(idx)), index=idx) * 0.1

    def strategy(data, params, train_index, test_index, fold):
        signal = pd.Series(1.0, index=test_index)
        signal.iloc[0] = 0.0
        return signal

    tts = QuantBTEndpoint.train_test_split(
        strategy_class=strategy,
        test_start="2022-01-01",
        target_mode="pct_equity",
        initial_capital=20_000.0,
        leverage=5.0,
        alloc_per_trade=0.5,
        fee=0.0,
        use_funding=False,
    )
    tts.backtest(data=data, params={})

    native = QuantBTEndpoint.pct_equity(
        initial_capital=20_000.0,
        leverage=5.0,
        alloc_per_trade=0.5,
        fee=0.0,
        use_funding=False,
    )
    native.backtest(
        data=data.loc["2022-01-01":],
        signal=strategy(data, {}, None, data.loc["2022-01-01":].index, None),
    )

    auto_report = tts.full_report()
    result_report = tts.result.full_report()
    full_report = tts.full_report(scope="full")
    native_report = native.full_report()

    assert auto_report["final_equity"] == pytest.approx(native_report["final_equity"])
    assert auto_report["total_return_pct"] == pytest.approx(native_report["total_return_pct"])
    assert auto_report["cagr_pct"] == pytest.approx(native_report["cagr_pct"])
    assert result_report["cagr_pct"] == pytest.approx(auto_report["cagr_pct"])
    assert full_report["final_equity"] == pytest.approx(native_report["final_equity"])
    assert full_report["cagr_pct"] < auto_report["cagr_pct"]


def test_endpoint_metrics_scope_survives_missing_module_global(monkeypatch):
    import quantbt.endpoint as endpoint_module

    idx = _idx()
    data = _bars(idx)
    data["close"] = 100.0 + pd.Series(range(len(idx)), index=idx) * 0.1

    def strategy(data, params, train_index, test_index, fold):
        signal = pd.Series(1.0, index=test_index)
        signal.iloc[0] = 0.0
        return signal

    bt = QuantBTEndpoint.train_test_split(
        strategy_class=strategy,
        test_start="2022-01-01",
        target_mode="pct_equity",
        initial_capital=20_000.0,
        leverage=5.0,
        alloc_per_trade=0.5,
        fee=0.0,
        use_funding=False,
    )
    bt.backtest(data=data, params={})

    monkeypatch.delattr(endpoint_module, "scoped_result", raising=False)

    report = bt.full_report()
    assert report["final_equity"] > 20_000.0


def test_walkforward_result_quick_plot_accepts_default_oos_scope(monkeypatch):
    idx = _idx()
    data = _bars(idx)
    data["close"] = 100.0 + pd.Series(range(len(idx)), index=idx) * 0.1

    def strategy(data, params, train_index, test_index, fold):
        signal = pd.Series(1.0, index=test_index)
        signal.iloc[0] = 0.0
        return signal

    bt = QuantBTEndpoint.train_test_split(
        strategy_class=strategy,
        test_start="2022-01-01",
        target_mode="pct_equity",
        initial_capital=20_000.0,
        leverage=5.0,
        alloc_per_trade=0.5,
        fee=0.0,
        use_funding=False,
    )
    result = bt.backtest(data=data, params={})

    import matplotlib.pyplot as plt

    monkeypatch.setattr(plt, "show", lambda: None)
    bt.quick_plot()
    result.quick_plot()


@pytest.mark.parametrize(
    "optimization_mode,optimization_config",
    [
        ("mode_1_decay", {"top_is_k": 2, "decay_lambda": 0.5, "decay_gamma": 0.5}),
        ("mode_2_sbb", {"top_is_k": 2, "sbb_samples": 16, "sbb_block_length": 10, "use_numba": True}),
        (
            "mode_3_flat_minima",
            {
                "top_is_k": 2,
                "flat_top_fraction": 1.0,
                "flat_eps": 1.0,
                "flat_min_samples": 1,
                "flat_selector": "medoid",
            },
        ),
    ],
)
def test_train_test_split_endpoint_tunes_params_with_walkforward_optuna_modes(
    optimization_mode,
    optimization_config,
):
    idx = _idx()
    data = _bars(idx)
    data["close"] = 100.0 + pd.Series(range(len(idx)), index=idx) * 0.1

    def strategy(data, params, train_index, test_index, fold):
        side = 1.0 if int(params["go_long"]) == 1 else -1.0
        return pd.Series(side, index=test_index)

    bt = QuantBTEndpoint.train_test_split(
        strategy_class=strategy,
        test_start="2022-01-01",
        target_mode="signal_notional",
        optimization_mode=optimization_mode,
        optimization_config=optimization_config,
        optuna_trials=8,
        random_seed=11,
        initial_capital=20_000.0,
        leverage=5.0,
        alloc_per_trade=1_000.0,
        fee_rate=0.0,
        use_funding=False,
    )
    result = bt.backtest(data=data, symbols=["BTC"], param_ranges={"go_long": (0, 1, 1)})
    wf = result.metadata["walk_forward"]

    assert wf["split_frequency"] == "single"
    assert wf["n_folds"] == 1
    assert wf["optimization_mode"] == optimization_mode
    assert wf["params"]["go_long"] == 1
    assert wf["best_trial"]["selection_metadata"]["oos_seen_by_optuna"] is False
    assert len(wf["trial_table"]) >= 1
    assert len(wf["candidate_table"]) >= 1


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


def test_walkforward_naive_data_index_is_aligned_to_fold_timezone_for_strategy():
    idx = pd.date_range("2021-07-01", "2022-09-30", freq="1D")
    data = _bars(idx)
    data["raw_signal"] = 1.0

    def strategy(data, params, train_index, test_index, fold):
        return data["raw_signal"].reindex(test_index).fillna(0.0)

    engine = WalkForwardEngine(
        strategy=strategy,
        config=WalkForwardConfig(split_mode=2022, split_frequency="quarterly"),
    )
    result = engine.run(data=data, params={})

    assert int((result.oos_output != 0.0).sum()) == sum(len(fold.test_index) for fold in result.folds)


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

    assert result.metadata["engine"] == "walk_forward_phase4"
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
    assert wf["best_trial"]["objective"] == wf["candidate_table"]["objective"].max()
    assert wf["best_trial"]["selection_metadata"]["oos_seen_by_optuna"] is False
    assert wf["candidate_table"]["selection_metadata"].notna().any()
    assert wf["config_hash"]
    assert wf["data_hash"]


def test_walkforward_phase_a_optuna_search_does_not_evaluate_oos_per_trial():
    idx = _idx()
    data = _bars(idx)
    data["close"] = 100.0 + pd.Series(range(len(idx)), index=idx) * 0.1
    calls = []

    def strategy(data, params, train_index, test_index, fold):
        calls.append({"fold_id": fold.fold_id, "is_train_index": train_index.equals(test_index)})
        side = 1.0 if int(params["go_long"]) == 1 else -1.0
        return pd.Series(side, index=test_index)

    engine = WalkForwardEngine(
        strategy=strategy,
        config=WalkForwardConfig(
            split_mode=2022,
            split_frequency="quarterly",
            optimization_mode="mode_1_decay",
            optuna_trials=8,
            top_is_k=1,
            random_seed=7,
        ),
    )
    folds = engine.build_folds(data.index)
    _, _, candidates = engine.optimize_params(data=data, folds=folds, param_ranges={"go_long": (0, 1, 1)})

    oos_calls = [call for call in calls if not call["is_train_index"]]
    assert len(candidates) == 1
    assert len(oos_calls) == len(folds)


def test_walkforward_score_strategy_output_is_transparent_return_proxy():
    idx = pd.date_range("2024-01-01", periods=4, freq="1D", tz="UTC")
    data = _bars(idx)
    data["close"] = [100.0, 110.0, 121.0, 133.1]
    signal = pd.Series([0.0, 1.0, 1.0, 1.0], index=idx)

    metrics = score_strategy_output(data, signal, idx)

    assert metrics["turnover"] == 1.0
    assert metrics["trade_count"] == 1.0
    assert metrics["mean_return"] > 0.0


def test_walkforward_trade_frequency_penalty_formula_is_normalized_linear():
    assert trade_frequency_penalty(actual_trades=10, required_trades=10, penalty_factor=2.0) == 0.0
    assert trade_frequency_penalty(actual_trades=5, required_trades=10, penalty_factor=2.0) == 1.0
    assert trade_frequency_penalty(actual_trades=0, required_trades=10, penalty_factor=2.0) == 2.0
    assert trade_frequency_penalty(actual_trades=0, required_trades=0, penalty_factor=2.0) == 0.0
    assert trade_frequency_penalty(actual_trades=0, required_trades=10, penalty_factor=None) == 0.0


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


def test_walkforward_phase_b_stationary_and_unit_stress_match_legacy_sbb_exactly():
    returns = np.array([0.0, 0.01, -0.004, 0.02, -0.003, 0.006] * 8, dtype=float)

    legacy = stationary_bootstrap_sharpes(
        returns,
        n_samples=32,
        block_length=5,
        seed=77,
        trading_days=365,
        use_numba=False,
    )
    stationary = synthetic_walkforward_sharpes(
        returns,
        n_samples=32,
        block_length=5,
        seed=77,
        trading_days=365,
        simulation="stationary",
        use_numba=True,
    )
    unit_stress = synthetic_walkforward_sharpes(
        returns,
        n_samples=32,
        block_length=5,
        seed=77,
        trading_days=365,
        simulation="stress",
        stress_vol_multiplier=1.0,
        use_numba=True,
    )

    np.testing.assert_allclose(stationary, legacy)
    np.testing.assert_allclose(unit_stress, legacy)


def test_walkforward_phase_b_supports_monthly_and_weekly_splits():
    idx = pd.date_range("2021-01-01", periods=220, freq="D", tz="UTC")
    data = _bars(idx)

    monthly = WalkForwardEngine(
        strategy=lambda data, params, train_index, test_index, fold: pd.Series(1.0, index=test_index),
        config=WalkForwardConfig(split_mode="2021-04-01", split_frequency="monthly", min_train_bars=10, min_test_bars=10),
    ).build_folds(data.index)
    weekly = WalkForwardEngine(
        strategy=lambda data, params, train_index, test_index, fold: pd.Series(1.0, index=test_index),
        config=WalkForwardConfig(split_mode="2021-04-01", split_frequency="weekly", min_train_bars=10, min_test_bars=5),
    ).build_folds(data.index)

    assert len(monthly) >= 3
    assert len(weekly) > len(monthly)
    assert all(fold.train_end < fold.test_start for fold in monthly + weekly)


def test_walkforward_phase_b_regime_and_stress_simulations_are_seeded():
    returns = np.array([0.001, -0.002, 0.003, -0.004, 0.008, -0.009, 0.002, -0.001] * 20, dtype=float)
    labels = volatility_regime_labels(returns, regime_count=3, lookback=5)

    assert set(labels.tolist()).issubset({0, 1, 2})
    assert labels.shape[0] == returns.shape[0]

    first = synthetic_walkforward_sharpes(
        returns,
        n_samples=24,
        block_length=4,
        seed=21,
        simulation="regime",
        regime_count=3,
        regime_lookback=5,
        regime_weights={"high": 0.7, "low": 0.3},
        use_numba=True,
    )
    second = synthetic_walkforward_sharpes(
        returns,
        n_samples=24,
        block_length=4,
        seed=21,
        simulation="regime",
        regime_count=3,
        regime_lookback=5,
        regime_weights={"high": 0.7, "low": 0.3},
        use_numba=False,
    )
    stressed = synthetic_walkforward_sharpes(
        returns,
        n_samples=24,
        block_length=4,
        seed=21,
        simulation="stress",
        stress_vol_multiplier=2.0,
        use_numba=True,
    )

    np.testing.assert_allclose(first, second)
    assert first.shape == (24,)
    assert stressed.shape == (24,)
    assert np.isfinite(first).all()
    assert np.isfinite(stressed).all()


def test_walkforward_phase_b_regime_labels_detect_trailing_high_volatility():
    low_vol = np.array([0.0005, -0.0004] * 30, dtype=float)
    high_vol = np.array([0.02, -0.018, 0.025, -0.021] * 15, dtype=float)
    labels = volatility_regime_labels(np.concatenate([low_vol, high_vol]), regime_count=3, lookback=10)

    assert float(np.median(labels[:30])) <= 1.0
    assert labels[-20:].min() >= 1
    assert labels[-20:].max() == 2
    assert float(np.mean(labels[-20:])) > float(np.mean(labels[:30]))


def test_walkforward_phase_b_regime_weights_select_requested_regime_blocks():
    labels = np.array([0] * 30 + [1] * 30 + [2] * 30, dtype=np.int64)

    high_indices = _regime_bootstrap_indices(
        labels,
        n_samples=6,
        block_length=8,
        seed=31,
        regime_weights={"high": 1.0},
        regime_count=3,
    )
    low_indices = _regime_bootstrap_indices(
        labels,
        n_samples=6,
        block_length=8,
        seed=31,
        regime_weights={"low": 1.0},
        regime_count=3,
    )

    assert np.all(labels[high_indices] == 2)
    assert np.all(labels[low_indices] == 0)


def test_walkforward_phase_b_regime_weights_tolerate_missing_regime_labels():
    returns = np.full(80, 0.001, dtype=float)

    out = synthetic_walkforward_sharpes(
        returns,
        n_samples=8,
        block_length=5,
        seed=7,
        simulation="regime",
        regime_count=3,
        regime_weights={"high": 1.0},
        use_numba=False,
    )

    assert out.shape == (8,)
    assert np.isfinite(out).all()


def test_walkforward_phase_b_garch_simulation_is_seeded_when_arch_is_available():
    pytest.importorskip("arch")
    rng = np.random.default_rng(123)
    returns = rng.standard_t(7, size=140).astype(float) * 0.01 + 0.0002

    first = synthetic_walkforward_sharpes(
        returns,
        n_samples=6,
        block_length=10,
        seed=99,
        simulation="garch",
        garch_p=1,
        garch_q=1,
        garch_dist="t",
        use_numba=True,
    )
    second = synthetic_walkforward_sharpes(
        returns,
        n_samples=6,
        block_length=10,
        seed=99,
        simulation="garch",
        garch_p=1,
        garch_q=1,
        garch_dist="t",
        use_numba=False,
    )

    np.testing.assert_allclose(first, second)
    assert np.isfinite(first).all()


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
    assert wf["best_trial"]["selection_metadata"]["oos_seen_by_optuna"] is False
    assert len(wf["candidate_table"]) >= 1


def test_walkforward_phase_b_mode_2_regime_endpoint_records_simulation_metadata():
    idx = _idx()
    data = _bars(idx)
    data["close"] = 100.0 + pd.Series(range(len(idx)), index=idx) * 0.1

    def strategy(data, params, train_index, test_index, fold):
        side = 1.0 if int(params["go_long"]) == 1 else -1.0
        return pd.Series(side, index=test_index)

    bt = QuantBTEndpoint.walk_forward(
        strategy_class=strategy,
        split_mode=2022,
        split_frequency="monthly",
        target_mode="signal_notional",
        optimization_mode="mode_2_sbb",
        optimization_config={
            "sbb_samples": 12,
            "sbb_block_length": 6,
            "sbb_simulation": "regime",
            "regime_count": 3,
            "regime_lookback": 5,
            "regime_weights": {"high": 0.6, "low": 0.4},
            "use_numba": True,
        },
        optuna_trials=4,
        random_seed=13,
        initial_capital=20_000.0,
        leverage=5.0,
        alloc_per_trade=1_000.0,
        fee_rate=0.0,
        use_funding=False,
    )
    result = bt.backtest(data=data, symbols=["BTC"], param_ranges={"go_long": (0, 1, 1)})
    wf = result.metadata["walk_forward"]
    best = wf["best_trial"]

    assert wf["split_frequency"] == "monthly"
    assert wf["sbb_simulation"] == "regime"
    assert best["selection_metadata"]["sbb_simulation"] == "regime"
    assert len(wf["candidate_table"]) >= 1
    assert wf["best_trial"]["selection_metadata"]["oos_seen_by_optuna"] is False


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
    assert selected.selection_metadata["cluster_method"] in {"sklearn.DBSCAN", "numpy_dbscan_fallback"}


def test_walkforward_phase3_flat_minima_centroid_snaps_to_valid_param_grid():
    records = [
        WalkForwardTrialRecord(0, {"x": 20}, 9.0, 0.0, 9.0, 0.0, 0.0, []),
        WalkForwardTrialRecord(1, {"x": 24}, 8.9, 0.0, 8.9, 0.0, 0.0, []),
        WalkForwardTrialRecord(2, {"x": 28}, 8.8, 0.0, 8.8, 0.0, 0.0, []),
        WalkForwardTrialRecord(3, {"x": 90}, 8.7, 0.0, 8.7, 0.0, 0.0, []),
    ]
    cfg = WalkForwardConfig(
        optimization_mode="mode_3_flat_minima",
        flat_selector="centroid",
        flat_top_fraction=1.0,
        flat_eps=0.1,
        flat_min_samples=2,
    )

    selected = select_flat_minima_record(records, {"x": (0, 100, 4)}, config=cfg)

    assert selected.trial_id == -1
    assert selected.params["x"] == 24
    assert selected.selection_metadata["selector"] == "centroid"
    assert selected.selection_metadata["requires_evaluation"] is True
    assert selected.selection_metadata["medoid_params"]["x"] == 24


def test_walkforward_phase4_rejects_non_timestamped_strategy_output():
    idx = _idx()

    def strategy(data, params, train_index, test_index, fold):
        return pd.Series([1.0] * len(test_index))

    engine = WalkForwardEngine(
        strategy=strategy,
        config=WalkForwardConfig(split_mode=2022, split_frequency="quarterly"),
    )

    with pytest.raises(TypeError, match="DatetimeIndex"):
        engine.run(data=_bars(idx), params={"window": 10})


def test_walkforward_phase4_rejects_partial_fold_strategy_output():
    idx = _idx()

    def strategy(data, params, train_index, test_index, fold):
        return pd.Series(1.0, index=test_index[:-1])

    engine = WalkForwardEngine(
        strategy=strategy,
        config=WalkForwardConfig(split_mode=2022, split_frequency="quarterly"),
    )

    with pytest.raises(ValueError, match="cover every expected fold timestamp"):
        engine.run(data=_bars(idx), params={"window": 10})


def test_walkforward_phase4_scoring_trading_days_controls_annualized_sharpe():
    idx = pd.date_range("2024-01-01", periods=6, freq="1D", tz="UTC")
    data = _bars(idx)
    data["close"] = [100.0, 101.0, 103.0, 102.0, 104.0, 107.0]
    signal = pd.Series([0.0, 1.0, 1.0, 1.0, 1.0, 1.0], index=idx)

    sharpe_252 = score_strategy_output(data, signal, idx, trading_days=252)["sharpe"]
    sharpe_365 = score_strategy_output(data, signal, idx, trading_days=365)["sharpe"]

    assert sharpe_365 > sharpe_252
    assert sharpe_365 / sharpe_252 == pytest.approx(np.sqrt(365 / 252))


def test_walkforward_phase4_endpoint_exposes_scoring_trading_days_metadata():
    idx = _idx()
    data = _bars(idx)
    data["close"] = 100.0 + pd.Series(range(len(idx)), index=idx) * 0.1

    def strategy(data, params, train_index, test_index, fold):
        return pd.Series(1.0, index=test_index)

    bt = QuantBTEndpoint.walk_forward(
        strategy_class=strategy,
        split_mode=2022,
        split_frequency="quarterly",
        target_mode="signal_notional",
        optimization_mode="mode_1_decay",
        optimization_config={"scoring_trading_days": 252},
        optuna_trials=4,
        random_seed=5,
        initial_capital=20_000.0,
        leverage=5.0,
        alloc_per_trade=1_000.0,
        fee_rate=0.0,
        use_funding=False,
    )
    result = bt.backtest(data=data, symbols=["BTC"], param_ranges={"side": [1.0]})

    assert result.metadata["walk_forward"]["scoring_trading_days"] == 252


def test_walkforward_optional_trade_frequency_penalty_adjusts_fold_sharpes():
    idx = _idx()
    data = _bars(idx)
    data["close"] = 100.0 + pd.Series(range(len(idx)), index=idx) * 0.1

    def strategy(data, params, train_index, test_index, fold):
        return pd.Series(1.0, index=test_index)

    engine = WalkForwardEngine(
        strategy=strategy,
        config=WalkForwardConfig(
            split_mode=2022,
            split_frequency="quarterly",
            min_trades_per_year=365.0,
            trade_penalty_factor=2.0,
        ),
    )
    result = engine.run(data=data, params={"side": 1.0})
    first_fold = result.best_trial["fold_metrics"][0]

    assert first_fold["oos_trade_count"] == 1.0
    assert first_fold["oos_required_trades"] > 0.0
    assert 0.0 < first_fold["oos_trade_penalty"] < 2.0
    assert first_fold["oos_sharpe"] == pytest.approx(
        first_fold["oos_sharpe_raw"] - first_fold["oos_trade_penalty"]
    )


def test_walkforward_trade_frequency_penalty_is_optional_endpoint_metadata():
    idx = _idx()

    def strategy(data, params, train_index, test_index, fold):
        return pd.Series(1.0, index=test_index)

    bt = QuantBTEndpoint.walk_forward(
        strategy_class=strategy,
        split_mode=2022,
        split_frequency="quarterly",
        target_mode="signal_notional",
        optimization_config={"min_trades_per_year": 24.0, "trade_penalty_factor": 1.5},
        initial_capital=20_000.0,
        leverage=5.0,
        alloc_per_trade=1_000.0,
        fee_rate=0.0,
        use_funding=False,
    )
    result = bt.backtest(data=_bars(idx), symbols=["BTC"], params={"side": 1.0})
    wf = result.metadata["walk_forward"]

    assert wf["min_trades_per_year"] == 24.0
    assert wf["trade_penalty_factor"] == 1.5


def test_walkforward_trade_frequency_penalty_applies_to_sbb_mode():
    idx = _idx()
    data = _bars(idx)
    data["close"] = 100.0 + pd.Series(range(len(idx)), index=idx) * 0.1

    def strategy(data, params, train_index, test_index, fold):
        return pd.Series(1.0, index=test_index)

    engine = WalkForwardEngine(
        strategy=strategy,
        config=WalkForwardConfig(
            split_mode=2022,
            split_frequency="quarterly",
            optimization_mode="mode_2_sbb",
            sbb_samples=16,
            min_trades_per_year=365.0,
            trade_penalty_factor=2.0,
        ),
    )
    folds = engine.build_folds(data.index)
    record = engine.evaluate_params_sbb(data=data, folds=folds, params={"side": 1.0})
    first_fold = record.fold_metrics[0]

    assert first_fold["is_trade_count"] == 1.0
    assert first_fold["is_trade_penalty"] > 0.0
    assert first_fold["synthetic_oos_sharpe"] == pytest.approx(
        first_fold["synthetic_oos_sharpe_raw"] - first_fold["is_trade_penalty"]
    )


def test_walkforward_phase4_param_range_validation_catches_invalid_math():
    with pytest.raises(ValueError, match="high must be >= low"):
        validate_param_ranges({"window": (30, 10, 1)})
    with pytest.raises(ValueError, match="step must be > 0"):
        validate_param_ranges({"window": (10, 30, 0)})
    with pytest.raises(ValueError, match="categorical choices"):
        validate_param_ranges({"mode": []})


def test_walkforward_phase4_support_matrix_covers_current_routes():
    matrix = walkforward_support_matrix()

    assert {
        "signal_notional",
        "notional",
        "unit",
        "pct_equity",
        "dca_ladder",
        "portfolio",
        "basket",
        "arbitrage",
    } <= set(matrix["target_mode"])
    assert set(matrix.columns) == {"target_mode", "expected_output", "final_engine", "status", "notes"}


def test_walkforward_phase4_benchmark_snapshot_is_finite_and_equivalent():
    snap = benchmark_walkforward_kernels(n_obs=128, n_samples=8, seed=21, use_numba=True)
    payload = snap.to_dict()

    assert payload["n_obs"] == 128
    assert payload["n_samples"] == 8
    assert payload["python_score_seconds"] >= 0.0
    assert payload["accelerated_score_seconds"] >= 0.0
    assert payload["python_bootstrap_seconds"] >= 0.0
    assert payload["accelerated_bootstrap_seconds"] >= 0.0
    assert payload["max_score_abs_diff"] < 1e-12
    assert payload["max_bootstrap_abs_diff"] < 1e-12


def test_walkforward_phase4_rolling_split_uses_bounded_train_window():
    idx = pd.date_range("2021-01-01", "2022-09-30", freq="1D", tz="UTC")

    def strategy(data, params, train_index, test_index, fold):
        return pd.Series(1.0, index=test_index)

    engine = WalkForwardEngine(
        strategy=strategy,
        config=WalkForwardConfig(
            split_mode=2022,
            split_frequency="quarterly",
            window_mode="rolling",
            train_window="180D",
            min_train_bars=120,
        ),
    )
    result = engine.run(data=_bars(idx), params={"window": 10})

    assert len(result.folds) == 3
    for fold in result.folds:
        assert fold.train_index.max() < fold.test_index.min()
        assert fold.train_index.min() >= fold.test_start - pd.Timedelta("180D")
        assert len(fold.train_index) <= 180
