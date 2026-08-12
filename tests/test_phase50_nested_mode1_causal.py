from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from quantbt import QuantBTEndpoint
from quantbt.walkforward import WalkForwardConfig, WalkForwardEngine


def _bars(end: str = "2021-06-30") -> pd.DataFrame:
    index = pd.date_range("2020-01-01", end, freq="1D", tz="UTC")
    phase = np.arange(len(index), dtype=np.float64)
    close = 100.0 + 0.03 * phase + np.sin(phase / 11.0)
    return pd.DataFrame(
        {
            "open": close,
            "high": close + 1.0,
            "low": close - 1.0,
            "close": close,
            "volume": 1_000.0 + phase,
        },
        index=index,
    )


def _strategy(call_log=None):
    def build(data, params, train_index, test_index, fold):
        if call_log is not None:
            call_log.append(
                {
                    "fold_id": int(fold.fold_id),
                    "visible_end": data.index[-1],
                    "train_end": train_index[-1],
                    "requested_end": test_index[-1],
                    "is_call": bool(test_index.equals(train_index)),
                }
            )
        return pd.Series(float(params["side"]), index=test_index)

    return build


def _mode1_scorer(data, output, index, fold, params, context, trading_days):
    del output, fold, trading_days
    assert data.index[-1] <= index[-1]
    side = int(params["side"])
    if context == "out-of-sample scoring":
        sharpe = 2.0 if side == 1 else -1.0
    elif context == "post-selection outer OOS realization":
        sharpe = 1.25 if side == 1 else -1.25
    else:
        sharpe = 1.0
    return {
        "sharpe": sharpe,
        "turnover": 100.0,
        "trade_count": 100.0,
        "mean_return": 0.0,
        "volatility": 0.0,
        "max_drawdown_pct": 0.0,
        "profit_factor": 1.0,
    }


def _nested_config(**overrides) -> WalkForwardConfig:
    values = {
        "split_mode": "2021-01-01",
        "split_frequency": "quarterly",
        "window_mode": "rolling",
        "train_window": "180D",
        "optimization_mode": "mode_1_decay",
        "optimization_schedule": "per_fold_causal",
        "candidate_selection_metric": "robust_decay",
        "inner_split_frequency": "monthly",
        "inner_window_mode": "rolling",
        "inner_train_window": "60D",
        "inner_min_folds": 2,
        "optuna_trials": 4,
        "random_seed": 71,
        "top_is_fraction": 1.0,
        "scoring_backend": "endpoint",
    }
    values.update(overrides)
    return WalkForwardConfig(**values)


def test_nested_mode1_causal_selects_only_on_inner_is_and_realizes_outer_oos_after_freeze():
    calls = []
    engine = WalkForwardEngine(
        strategy=_strategy(calls),
        scorer=_mode1_scorer,
        config=_nested_config(),
    )

    result = engine.run(data=_bars(), param_ranges={"side": [0, 1]})
    metadata = result.metadata
    selection = metadata["fold_selection_table"]
    inner = metadata["inner_fold_table"]

    assert metadata["validation_claim"] == "strict_nested_fold_local_retraining"
    assert metadata["chronological_validation_claim"] == "strict_outer_oos_after_frozen_selection"
    assert metadata["oos_used_for_selection"] is False
    assert metadata["inner_validation"]["selection_scope"] == "outer_is_only"
    assert result.params == {"side": 1}
    assert not selection["outer_oos_used_for_selection"].any()
    assert selection["inner_fold_count"].ge(2).all()
    assert (inner["inner_test_end"] <= inner["outer_train_end"]).all()
    assert (inner["outer_test_start"] > inner["inner_test_end"]).all()

    outer_realizations = [call for call in calls if not call["is_call"] and call["requested_end"] > call["train_end"]]
    assert len(outer_realizations) >= len(result.folds)
    assert all(call["visible_end"] <= call["requested_end"] for call in calls)


def test_nested_mode1_causal_completed_prefix_is_invariant_to_appended_future_data():
    config = _nested_config(optuna_trials=3)
    short = WalkForwardEngine(strategy=_strategy(), scorer=_mode1_scorer, config=config).run(
        data=_bars("2021-06-30"),
        param_ranges={"side": [0, 1]},
    )
    extended = WalkForwardEngine(strategy=_strategy(), scorer=_mode1_scorer, config=config).run(
        data=_bars("2021-09-30"),
        param_ranges={"side": [0, 1]},
    )

    assert {
        fold_id: params
        for fold_id, params in extended.metadata["params_by_fold"].items()
        if fold_id < len(short.folds)
    } == short.metadata["params_by_fold"]
    pd.testing.assert_series_equal(
        short.oos_output.loc[short.folds[0].test_start : short.folds[-1].test_end],
        extended.oos_output.loc[short.folds[0].test_start : short.folds[-1].test_end],
    )


def test_nested_mode1_causal_requires_enough_inner_history_without_fallback():
    config = _nested_config(inner_train_window="360D")
    with pytest.raises(ValueError, match="no room for an inner OOS window"):
        WalkForwardEngine(strategy=_strategy(), scorer=_mode1_scorer, config=config).run(
            data=_bars(),
            param_ranges={"side": [0, 1]},
        )


def test_nested_mode1_causal_prepared_and_reference_account_results_match():
    data = _bars()

    def run(*, prepared: bool):
        endpoint = QuantBTEndpoint.walk_forward(
            strategy_class=_strategy(),
            split_mode="2021-01-01",
            split_frequency="quarterly",
            window_mode="rolling",
            train_window="180D",
            target_mode="signal_notional",
            optimization_mode="mode_1_decay",
            optimization_schedule="per_fold_causal",
            optimization_config={
                "candidate_selection_metric": "robust_decay",
                "inner_split_frequency": "monthly",
                "inner_window_mode": "rolling",
                "inner_train_window": "60D",
                "inner_min_folds": 2,
                "top_is_fraction": 1.0,
                "scoring_backend": "proxy",
                "use_prepared_wfo_context": prepared,
                "use_scalar_trial_scoring": prepared,
                "compact_trial_ledger": prepared,
            },
            optuna_trials=2,
            random_seed=79,
            initial_capital=20_000.0,
            leverage=2.0,
            alloc_per_trade=1_000.0,
            fee_rate=0.0002,
            slippage=0.0001,
            use_funding=False,
        )
        return endpoint.backtest(data=data, symbols=["BTC"], param_ranges={"side": [1]})

    prepared = run(prepared=True)
    reference = run(prepared=False)
    pd.testing.assert_series_equal(prepared.equity, reference.equity)
    pd.testing.assert_frame_equal(prepared.positions, reference.positions)
    assert prepared.metadata["walk_forward"]["params_by_fold"] == reference.metadata["walk_forward"]["params_by_fold"]
    assert prepared.metadata["walk_forward"]["inner_fold_table"].equals(reference.metadata["walk_forward"]["inner_fold_table"])


def test_global_schedule_exposes_non_causal_chronological_claim_without_changing_legacy_claim():
    def global_scorer(data, output, index, fold, params, context, trading_days):
        del data, output, index, fold, params, context, trading_days
        return {
            "sharpe": 1.0,
            "turnover": 0.0,
            "trade_count": 0.0,
            "mean_return": 0.0,
            "volatility": 0.0,
            "max_drawdown_pct": 0.0,
            "profit_factor": 1.0,
        }

    result = WalkForwardEngine(
        strategy=_strategy(),
        scorer=global_scorer,
        config=WalkForwardConfig(
            split_mode="2021-01-01",
            split_frequency="single",
            optimization_mode="mode_4_is_only_robust",
            candidate_selection_metric="is_only_robust",
            scoring_backend="endpoint",
        ),
    ).run(data=_bars(), params={"side": 1})

    assert result.metadata["validation_claim"] == "walk_forward_oos"
    assert result.metadata["causality_claim"] == "retrospective_global_calibration"
    assert result.metadata["chronological_validation_claim"] == "not_causal_multi_fold_global_calibration"
