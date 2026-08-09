import numpy as np
import pandas as pd
import pytest

from quantbt import QuantBTEndpoint
from quantbt.walkforward import WalkForwardConfig, WalkForwardEngine


def _bars(end="2021-06-30", *, start="2020-01-01"):
    idx = pd.date_range(start, end, freq="1D", tz="UTC")
    phase = np.arange(len(idx), dtype=float)
    close = 100.0 + 0.025 * phase + 1.5 * np.sin(phase / 13.0)
    return pd.DataFrame(
        {
            "open": close,
            "high": close + 1.0,
            "low": close - 1.0,
            "close": close,
            "volume": 1_000.0,
        },
        index=idx,
    )


def _constant_strategy(call_log=None):
    def strategy(data, params, train_index, test_index, fold):
        if call_log is not None:
            call_log.append(
                {
                    "fold_id": int(fold.fold_id),
                    "is_call": bool(test_index.equals(train_index)),
                    "visible_end": data.index[-1],
                    "requested_end": test_index[-1],
                    "side": int(params["side"]),
                }
            )
        return pd.Series(float(params["side"]), index=test_index)

    return strategy


def _data_end(data):
    if isinstance(data, dict):
        return max(value.index[-1] for value in data.values() if hasattr(value, "index"))
    return data.index[-1]


def _regime_scorer(data, output, index, fold, params, context, trading_days):
    assert _data_end(data) <= index[-1]
    del output, trading_days
    side = int(params["side"])
    if "out-of-sample" in context:
        preferred = 0 if int(fold.fold_id) % 2 == 0 else 1
        sharpe = 2.0 if side == preferred else -1.0
    else:
        sharpe = 1.0
    return {
        "sharpe": sharpe,
        "turnover": 200.0,
        "trade_count": 200.0,
        "mean_return": 0.0,
        "volatility": 0.0,
        "max_drawdown_pct": 0.0,
        "profit_factor": 1.0,
    }


def _neutral_scorer(data, output, index, fold, params, context, trading_days):
    assert _data_end(data) <= index[-1]
    del output, fold, params, context, trading_days
    return {
        "sharpe": 1.0,
        "turnover": 200.0,
        "trade_count": 200.0,
        "mean_return": 0.0,
        "volatility": 0.0,
        "max_drawdown_pct": 0.0,
        "profit_factor": 1.0,
    }


def test_per_fold_decay_uses_independent_studies_and_existing_mode1_selector():
    data = _bars()
    calls = []
    engine = WalkForwardEngine(
        strategy=_constant_strategy(calls),
        scorer=_regime_scorer,
        config=WalkForwardConfig(
            split_mode="2021-01-01",
            split_frequency="quarterly",
            window_mode="rolling",
            train_window="180D",
            optimization_mode="mode_1_decay",
            optimization_schedule="per_fold_decay",
            optuna_trials=8,
            random_seed=17,
            top_is_fraction=1.0,
            candidate_selection_metric="robust_decay",
            scoring_backend="endpoint",
        ),
    )

    result = engine.run(data=data, param_ranges={"side": [0, 1]})

    assert result.metadata["optimization_schedule"] == "per_fold_decay"
    assert result.metadata["causality_claim"] == "fold_local_decay_calibration"
    assert result.metadata["validation_claim"] == "selection_adjusted_oos"
    assert result.metadata["oos_used_for_selection"] is True
    assert result.metadata["n_studies"] == 2
    assert result.metadata["optuna_trials_scope"] == "per_fold"
    assert result.metadata["params_by_fold"] == {0: {"side": 0}, 1: {"side": 1}}
    assert result.params == {"side": 1}
    assert result.metadata["params_semantics"] == "last_completed_fold_selected_params"

    selection = result.metadata["fold_selection_table"]
    assert selection["study_id"].tolist() == [0, 1]
    assert selection["fold_seed"].nunique() == 2
    assert selection["outer_oos_used_for_selection"].all()
    assert selection["candidate_count"].min() == 2
    assert selection["candidate_decay"].tolist() == [-1.0, -1.0]
    assert result.metadata["n_optuna_trial_rows"] == int(selection["study_trial_rows"].sum())
    assert result.metadata["optuna_trials_configured_per_study"] == 8

    assert set(result.trial_table["schedule_fold_id"].dropna().astype(int)) == {0, 1}
    assert set(result.candidate_table["schedule_fold_id"].dropna().astype(int)) == {0, 1}
    assert result.candidate_table["mean_oos_sharpe"].abs().max() > 0.0
    assert all(call["visible_end"] <= call["requested_end"] for call in calls)


def test_per_fold_causal_mode4_selects_on_is_then_realizes_outer_oos_once():
    data = _bars()
    calls = []
    engine = WalkForwardEngine(
        strategy=_constant_strategy(calls),
        scorer=_neutral_scorer,
        config=WalkForwardConfig(
            split_mode="2021-01-01",
            split_frequency="quarterly",
            window_mode="rolling",
            train_window="180D",
            optimization_mode="mode_4_is_only_robust",
            optimization_schedule="per_fold_causal",
            optuna_trials=1,
            random_seed=23,
            top_is_fraction=1.0,
            flat_eps=1.0,
            flat_min_samples=1,
            is_subperiods=2,
            candidate_selection_metric="is_only_robust",
            scoring_backend="endpoint",
        ),
    )

    result = engine.run(data=data, param_ranges={"side": [1]})

    assert result.metadata["validation_claim"] == "strict_fold_local_retraining"
    assert result.metadata["causality_claim"] == "strict_fold_local_retraining"
    assert result.metadata["oos_used_for_selection"] is False
    assert not result.metadata["fold_selection_table"]["outer_oos_used_for_selection"].any()
    assert (result.candidate_table["mean_oos_sharpe"] == 0.0).all()
    assert result.best_trial["selection_metadata"]["oos_used_for_selection"] is False

    oos_calls = [call for call in calls if not call["is_call"]]
    assert len(oos_calls) == len(result.folds)
    assert all(call["visible_end"] == call["requested_end"] for call in calls)


def test_phase49a_schedule_validation_is_explicit_and_never_falls_back():
    with pytest.raises(NotImplementedError, match="nested inner-validation"):
        WalkForwardConfig(
            optimization_mode="mode_1_decay",
            optimization_schedule="per_fold_causal",
            optuna_trials=10,
        )
    with pytest.raises(NotImplementedError, match="requires optimization_mode='mode_1_decay'"):
        WalkForwardConfig(
            optimization_mode="mode_4_is_only_robust",
            optimization_schedule="per_fold_decay",
            optuna_trials=10,
        )
    with pytest.raises(NotImplementedError, match="currently requires"):
        WalkForwardConfig(
            optimization_mode="mode_5_full_robust",
            optimization_schedule="per_fold_causal",
            optuna_trials=10,
        )
    with pytest.raises(ValueError, match="require optuna_trials > 0"):
        WalkForwardConfig(
            optimization_mode="mode_4_is_only_robust",
            optimization_schedule="per_fold_causal",
            optuna_trials=0,
        )
    with pytest.raises(NotImplementedError, match="supports 'carry' only"):
        WalkForwardConfig(fold_boundary_position_policy="flatten")


def test_explicit_global_schedule_preserves_existing_walkforward_behavior():
    data = _bars()
    strategy = _constant_strategy()
    kwargs = dict(
        split_mode="2021-01-01",
        split_frequency="quarterly",
        window_mode="rolling",
        train_window="180D",
    )
    implicit = WalkForwardEngine(strategy=strategy, config=WalkForwardConfig(**kwargs)).run(
        data=data,
        params={"side": 1},
    )
    explicit = WalkForwardEngine(
        strategy=strategy,
        config=WalkForwardConfig(optimization_schedule="global", **kwargs),
    ).run(data=data, params={"side": 1})

    pd.testing.assert_series_equal(implicit.oos_output, explicit.oos_output)
    pd.testing.assert_frame_equal(implicit.trial_table, explicit.trial_table)
    assert implicit.best_trial == explicit.best_trial
    assert implicit.metadata["config_hash"] == explicit.metadata["config_hash"]


def test_per_fold_causal_completed_prefix_is_invariant_to_appended_future_bars():
    strategy = _constant_strategy()
    config = WalkForwardConfig(
        split_mode="2021-01-01",
        split_frequency="quarterly",
        window_mode="rolling",
        train_window="180D",
        optimization_mode="mode_4_is_only_robust",
        optimization_schedule="per_fold_causal",
        optuna_trials=2,
        random_seed=31,
        top_is_fraction=1.0,
        flat_eps=1.0,
        flat_min_samples=1,
        is_subperiods=2,
        candidate_selection_metric="is_only_robust",
        scoring_backend="endpoint",
    )
    short = WalkForwardEngine(strategy=strategy, scorer=_neutral_scorer, config=config).run(
        data=_bars("2021-06-30"),
        param_ranges={"side": [0, 1]},
    )
    extended = WalkForwardEngine(strategy=strategy, scorer=_neutral_scorer, config=config).run(
        data=_bars("2021-09-30"),
        param_ranges={"side": [0, 1]},
    )

    assert {
        fold_id: params for fold_id, params in extended.metadata["params_by_fold"].items() if fold_id < 2
    } == short.metadata["params_by_fold"]
    pd.testing.assert_series_equal(
        short.oos_output.loc[short.folds[0].test_start : short.folds[-1].test_end],
        extended.oos_output.loc[short.folds[0].test_start : short.folds[-1].test_end],
    )


def test_per_fold_decay_completed_prefix_is_invariant_to_later_folds():
    config = WalkForwardConfig(
        split_mode="2021-01-01",
        split_frequency="quarterly",
        window_mode="rolling",
        train_window="180D",
        optimization_mode="mode_1_decay",
        optimization_schedule="per_fold_decay",
        optuna_trials=8,
        random_seed=37,
        top_is_fraction=1.0,
        candidate_selection_metric="robust_decay",
        scoring_backend="endpoint",
    )
    short = WalkForwardEngine(
        strategy=_constant_strategy(), scorer=_regime_scorer, config=config
    ).run(data=_bars("2021-06-30"), param_ranges={"side": [0, 1]})
    extended = WalkForwardEngine(
        strategy=_constant_strategy(), scorer=_regime_scorer, config=config
    ).run(data=_bars("2021-09-30"), param_ranges={"side": [0, 1]})

    assert {
        fold_id: params for fold_id, params in extended.metadata["params_by_fold"].items() if fold_id < 2
    } == short.metadata["params_by_fold"]
    pd.testing.assert_series_equal(
        short.oos_output.loc[short.folds[0].test_start : short.folds[-1].test_end],
        extended.oos_output.loc[short.folds[0].test_start : short.folds[-1].test_end],
    )


def test_per_fold_schedule_supports_timestamp_safe_multi_symbol_outputs():
    data = {"BTC": _bars(), "ETH": _bars()}
    visible_ends = []

    def strategy(data, params, train_index, test_index, fold):
        visible_ends.append((data["BTC"].index[-1], test_index[-1]))
        side = float(params["side"])
        return pd.DataFrame({"BTC": side, "ETH": -side}, index=test_index)

    engine = WalkForwardEngine(
        strategy=strategy,
        scorer=_neutral_scorer,
        config=WalkForwardConfig(
            split_mode="2021-01-01",
            split_frequency="quarterly",
            window_mode="rolling",
            train_window="180D",
            target_mode="portfolio",
            optimization_mode="mode_4_is_only_robust",
            optimization_schedule="per_fold_causal",
            optuna_trials=1,
            top_is_fraction=1.0,
            flat_eps=1.0,
            flat_min_samples=1,
            is_subperiods=2,
            candidate_selection_metric="is_only_robust",
            scoring_backend="endpoint",
        ),
    )
    result = engine.run(data=data, param_ranges={"side": [1]})

    assert isinstance(result.oos_output, pd.DataFrame)
    assert list(result.oos_output.columns) == ["BTC", "ETH"]
    assert all(visible_end == requested_end for visible_end, requested_end in visible_ends)
    assert (result.metadata["fold_boundary_table"]["changed_targets"] == 0).all()


def test_train_test_split_forwards_per_fold_schedule_to_single_holdout():
    endpoint = QuantBTEndpoint.train_test_split(
        strategy_class=_constant_strategy(),
        test_start="2021-01-01",
        target_mode="signal_notional",
        optimization_mode="mode_4_is_only_robust",
        optimization_schedule="per_fold_causal",
        optimization_config={
            "candidate_selection_metric": "is_only_robust",
            "top_is_fraction": 1.0,
            "flat_eps": 1.0,
            "flat_min_samples": 1,
            "is_subperiods": 2,
            "scoring_backend": "proxy",
        },
        optuna_trials=1,
        initial_capital=20_000.0,
        alloc_per_trade=1_000.0,
        fee_rate=0.0,
        use_funding=False,
    )
    result = endpoint.backtest(data=_bars(), symbols=["BTC"], param_ranges={"side": [1]})

    wf = result.metadata["walk_forward"]
    assert wf["optimization_schedule"] == "per_fold_causal"
    assert wf["n_studies"] == 1
    assert wf["split_frequency"] == "single"


def test_walkforward_endpoint_forwards_mode1_per_fold_decay_audit_contract():
    endpoint = QuantBTEndpoint.walk_forward(
        strategy_class=_constant_strategy(),
        split_mode="2021-01-01",
        split_frequency="quarterly",
        window_mode="rolling",
        train_window="180D",
        target_mode="signal_notional",
        optimization_mode="mode_1_decay",
        optimization_schedule="per_fold_decay",
        optimization_config={
            "candidate_selection_metric": "robust_decay",
            "top_is_fraction": 1.0,
            "scoring_backend": "proxy",
        },
        optuna_trials=4,
        random_seed=43,
        initial_capital=20_000.0,
        alloc_per_trade=1_000.0,
        fee_rate=0.0,
        use_funding=False,
    )
    result = endpoint.backtest(data=_bars(), symbols=["BTC"], param_ranges={"side": [-1, 1]})

    wf = result.metadata["walk_forward"]
    assert wf["optimization_schedule"] == "per_fold_decay"
    assert wf["n_studies"] == wf["n_folds"] == 2
    assert wf["oos_used_for_selection"] is True
    assert set(wf["params_by_fold"]) == {0, 1}
    assert wf["fold_selection_table"]["outer_oos_used_for_selection"].all()


def test_endpoint_runs_stitched_targets_once_without_boundary_reopen_cost():
    data = _bars()

    endpoint = QuantBTEndpoint.walk_forward(
        strategy_class=_constant_strategy(),
        split_mode="2021-01-01",
        split_frequency="quarterly",
        window_mode="rolling",
        train_window="180D",
        target_mode="signal_notional",
        optimization_mode="mode_4_is_only_robust",
        optimization_schedule="per_fold_causal",
        optimization_config={
            "candidate_selection_metric": "is_only_robust",
            "top_is_fraction": 1.0,
            "flat_eps": 1.0,
            "flat_min_samples": 1,
            "is_subperiods": 2,
            "scoring_backend": "proxy",
        },
        optuna_trials=1,
        random_seed=41,
        initial_capital=20_000.0,
        leverage=1.0,
        alloc_per_trade=1_000.0,
        fee_rate=0.0005,
        slippage=0.0001,
        use_funding=False,
    )
    result = endpoint.backtest(data=data, symbols=["BTC"], param_ranges={"side": [1]})
    wf_result = result.metadata["walk_forward_result"]

    direct = QuantBTEndpoint.signal_notional(
        initial_capital=20_000.0,
        leverage=1.0,
        alloc_per_trade=1_000.0,
        fee_rate=0.0005,
        slippage=0.0001,
        use_funding=False,
    ).backtest(data=data, signal=wf_result.oos_output, symbols=["BTC"])

    pd.testing.assert_series_equal(result.equity, direct.equity)
    pd.testing.assert_frame_equal(result.positions, direct.positions)
    boundaries = result.metadata["walk_forward"]["fold_boundary_table"]
    assert (boundaries["gap_bars"] == 0).all()
    assert (boundaries["gap_policy"] == "contiguous").all()
    assert (boundaries["gap_fill_value"] == 0.0).all()
    assert (boundaries["changed_targets"] == 0).all()
    assert result.metadata["walk_forward"]["account_execution"] == "single_stitched_run"
