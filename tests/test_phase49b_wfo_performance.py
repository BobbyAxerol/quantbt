from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from quantbt import (
    AccountConfig,
    ExecutionConfig,
    NativePortfolioBackend,
    NativePortfolioConfig,
    NativeVectorizedBackend,
    NativeVectorizedConfig,
    PreparedWalkForwardContext,
    QuantBTEndpoint,
)
from quantbt.walkforward import WalkForwardConfig, WalkForwardEngine


def _bars(rows: int = 540) -> pd.DataFrame:
    idx = pd.date_range("2020-01-01", periods=rows, freq="1D", tz="UTC")
    phase = np.arange(rows, dtype=np.float64)
    close = 100.0 + phase * 0.02 + 1.5 * np.sin(phase / 17.0)
    return pd.DataFrame(
        {
            "open": close,
            "high": close * 1.002,
            "low": close * 0.998,
            "close": close,
            "volume": 1_000.0 + phase,
            "funding_rate": np.where((phase.astype(int) % 8) == 0, 0.0001, 0.0),
        },
        index=idx,
    )


def _assert_report_equal(left: dict, right: dict) -> None:
    assert left.keys() == right.keys()
    for key in left:
        if isinstance(left[key], bool):
            assert left[key] is right[key]
        elif math.isinf(float(left[key])) or math.isinf(float(right[key])):
            assert float(left[key]) == float(right[key])
        else:
            np.testing.assert_allclose(float(left[key]), float(right[key]), rtol=0.0, atol=1e-12)


def test_native_vectorized_scalar_score_is_exact_public_report_without_pandas_paths():
    frame = _bars(180)
    idx = frame.index
    signal = pd.Series(np.sign(np.sin(np.arange(len(idx)) / 9.0)), index=idx)
    closes = {"BTC": frame["close"]}
    highs = {"BTC": frame["high"]}
    lows = {"BTC": frame["low"]}
    positions = {"BTC": signal}
    backend = NativeVectorizedBackend(
        NativeVectorizedConfig(
            account=AccountConfig(initial_capital=20_000.0, leverage=4.0),
            execution=ExecutionConfig(slippage_bps=1.0),
            fee_rate=0.0002,
            use_funding=False,
        )
    )
    market = backend.prepare_market_arrays(idx, closes, highs, lows, symbols=["BTC"])
    kwargs = dict(
        datetime_index=idx,
        positions=positions,
        closes=closes,
        highs=highs,
        lows=lows,
        symbols=["BTC"],
        alloc_per_trade=5_000.0,
        hedge_type="signal_notional",
        market_arrays=market,
    )

    public = backend.run_signals(**kwargs)
    scalar = backend.score_signals(trading_days=365, **kwargs)

    _assert_report_equal(scalar.full_report(), public.full_report(scope="full"))
    assert scalar.final_equity == public.equity.iloc[-1]
    np.testing.assert_allclose(scalar.final_positions, public.positions.iloc[-1].to_numpy(), rtol=0.0, atol=0.0)
    assert scalar.metadata["score_pandas_materialized"] is False


def test_native_portfolio_scalar_score_is_exact_public_report_without_audit_reports():
    btc = _bars(180)
    eth = _bars(180).copy()
    eth[["open", "high", "low", "close"]] *= 0.55
    idx = btc.index
    closes = {"BTC": btc["close"], "ETH": eth["close"]}
    highs = {"BTC": btc["high"], "ETH": eth["high"]}
    lows = {"BTC": btc["low"], "ETH": eth["low"]}
    positions = {
        "BTC": pd.Series(np.sign(np.sin(np.arange(len(idx)) / 11.0)), index=idx),
        "ETH": pd.Series(-np.sign(np.sin(np.arange(len(idx)) / 11.0)), index=idx),
    }
    backend = NativePortfolioBackend(
        NativePortfolioConfig(
            account=AccountConfig(initial_capital=100_000.0, leverage=5.0),
            execution=ExecutionConfig(slippage_bps=1.0),
            fee_rate=0.0002,
            use_funding=False,
            report_level="minimal",
        )
    )
    market = backend.prepare_market_arrays(idx, closes, highs, lows, symbols=["BTC", "ETH"])
    kwargs = dict(
        positions=positions,
        closes=closes,
        highs=highs,
        lows=lows,
        datetime_index=idx,
        symbols=["BTC", "ETH"],
        mode="market_neutral",
        hedge_type="notional",
        alloc_per_trade={"BTC": 5_000.0, "ETH": 5_000.0},
        market_arrays=market,
        report_level="minimal",
    )

    public = backend.run_signals(**kwargs)
    scalar = backend.score_signals(trading_days=365, **kwargs)

    _assert_report_equal(scalar.full_report(), public.full_report(scope="full"))
    assert scalar.final_equity == public.equity.iloc[-1]
    np.testing.assert_allclose(scalar.final_positions, public.positions.iloc[-1].to_numpy(), rtol=0.0, atol=0.0)
    assert scalar.metadata["score_pandas_materialized"] is False


def test_prepared_walkforward_context_has_content_signature_and_isolated_strategy_slice():
    frame = _bars(400)
    config = WalkForwardConfig(
        split_mode="2021-01-01",
        split_frequency="single",
        optimization_mode="mode_4_is_only_robust",
        optimization_schedule="per_fold_causal",
        optuna_trials=1,
        top_is_fraction=1.0,
        flat_eps=1.0,
        flat_min_samples=1,
        is_subperiods=2,
        candidate_selection_metric="is_only_robust",
    )
    engine = WalkForwardEngine(
        strategy=lambda data, params, train_index, test_index, fold: pd.Series(1.0, index=test_index),
        config=config,
    )
    folds = engine.build_folds(frame.index)
    context = PreparedWalkForwardContext.prepare(
        data=frame,
        datetime_index=frame.index,
        folds=folds,
        config=config,
    )

    context.validate_source(frame)
    isolated = context.data_through(folds[0].train_end, strategy_copy=True)
    isolated.iloc[0, isolated.columns.get_loc("close")] = -1.0
    assert context.data.iloc[0]["close"] != -1.0

    mutated = frame.copy()
    mutated.iloc[0, mutated.columns.get_loc("volume")] += 1.0
    try:
        context.validate_source(mutated)
    except ValueError as exc:
        assert "signature changed" in str(exc)
    else:  # pragma: no cover - mutation must be detected
        raise AssertionError("volume mutation reused a stale prepared WFO context")


def _run_portfolio_wfo(*, optimized: bool):
    btc = _bars(720)
    eth = _bars(720).copy()
    eth[["open", "high", "low", "close"]] *= 0.55
    data = {"BTC": btc, "ETH": eth}

    def strategy(data, params, train_index, test_index, fold):
        scale = float(params["scale"])
        return pd.DataFrame({"BTC": scale, "ETH": -scale}, index=test_index)

    endpoint = QuantBTEndpoint.train_test_split(
        strategy_class=strategy,
        test_start="2021-06-01",
        target_mode="portfolio",
        portfolio_mode="longshort",
        optimization_mode="mode_1_decay",
        optimization_config={
            "scoring_backend": "endpoint",
            "top_is_fraction": 0.5,
            "use_prepared_scoring_cache": True,
            "use_prepared_wfo_context": optimized,
            "use_scalar_trial_scoring": optimized,
            "compact_trial_ledger": optimized,
        },
        optuna_trials=12,
        random_seed=123,
        initial_capital=100_000.0,
        leverage=5.0,
        alloc_per_trade=5_000.0,
        fee_rate=0.0002,
        use_funding=False,
    )
    return endpoint.backtest(data=data, param_ranges={"scale": (0.5, 1.5, 0.1)})


def test_prepared_scalar_wfo_matches_reference_params_objectives_order_and_account():
    optimized = _run_portfolio_wfo(optimized=True)
    reference = _run_portfolio_wfo(optimized=False)
    optimized_wf = optimized.metadata["walk_forward"]
    reference_wf = reference.metadata["walk_forward"]

    pd.testing.assert_series_equal(optimized.equity, reference.equity)
    pd.testing.assert_frame_equal(optimized.positions, reference.positions)
    pd.testing.assert_frame_equal(optimized_wf["trial_table"], reference_wf["trial_table"])
    pd.testing.assert_frame_equal(optimized_wf["candidate_table"], reference_wf["candidate_table"])
    assert optimized_wf["params"] == reference_wf["params"]
    assert optimized_wf["best_trial"] == reference_wf["best_trial"]
    assert optimized_wf["prepared_scoring_cache"]["scalar_runs"] > 0
    assert optimized_wf["prepared_scoring_cache"]["released_after_run"] is True
    assert optimized_wf["prepared_wfo_context"]["enabled"] is True
    assert reference_wf["prepared_wfo_context"]["enabled"] is False


def test_prepared_context_is_run_local_and_timezone_alignment_is_stable():
    naive = _bars(400)
    naive.index = naive.index.tz_localize(None)

    def strategy(data, params, train_index, test_index, fold):
        return pd.Series(float(params["side"]), index=test_index)

    endpoint = QuantBTEndpoint.walk_forward(
        strategy_class=strategy,
        split_mode="2021-01-01",
        split_frequency="single",
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
        random_seed=7,
        initial_capital=20_000.0,
        alloc_per_trade=1_000.0,
        fee_rate=0.0,
        use_funding=False,
    )
    first = endpoint.backtest(data=naive, symbols=["BTC"], param_ranges={"side": [1]})
    changed = naive.copy()
    changed["volume"] += 10.0
    second = endpoint.backtest(data=changed, symbols=["BTC"], param_ranges={"side": [1]})

    first_meta = first.metadata["walk_forward"]["prepared_wfo_context"]
    second_meta = second.metadata["walk_forward"]["prepared_wfo_context"]
    assert first_meta["data_signature"] != second_meta["data_signature"]
    assert first.equity.index.tz is not None
    assert second.equity.index.tz is not None


@pytest.mark.parametrize("target_mode", ["signal_notional", "pct_equity"])
def test_per_fold_prepared_and_reference_final_account_parity(target_mode: str):
    data = _bars(540)

    def strategy(data, params, train_index, test_index, fold):
        del data, train_index, fold
        return pd.Series(float(params["side"]), index=test_index)

    def run(optimized: bool):
        endpoint = QuantBTEndpoint.walk_forward(
            strategy_class=strategy,
            split_mode="2021-01-01",
            split_frequency="quarterly",
            window_mode="rolling",
            train_window="180D",
            target_mode=target_mode,
            optimization_mode="mode_4_is_only_robust",
            optimization_schedule="per_fold_causal",
            optimization_config={
                "candidate_selection_metric": "is_only_robust",
                "top_is_fraction": 1.0,
                "flat_eps": 1.0,
                "flat_min_samples": 1,
                "is_subperiods": 2,
                "scoring_backend": "endpoint",
                "use_prepared_scoring_cache": True,
                "use_prepared_wfo_context": optimized,
                "use_scalar_trial_scoring": optimized,
                "compact_trial_ledger": optimized,
            },
            optuna_trials=1,
            random_seed=19,
            initial_capital=20_000.0,
            leverage=3.0,
            alloc_per_trade=0.5 if target_mode == "pct_equity" else 2_000.0,
            fee_rate=0.0002,
            slippage=0.0001,
            use_funding=False,
        )
        return endpoint.backtest(data=data, symbols=["BTC"], param_ranges={"side": [1]})

    optimized = run(True)
    reference = run(False)
    pd.testing.assert_series_equal(optimized.equity, reference.equity)
    pd.testing.assert_frame_equal(optimized.positions, reference.positions)
    assert optimized.metadata["walk_forward"]["best_trial"] == reference.metadata["walk_forward"]["best_trial"]
    assert optimized.metadata["walk_forward"]["params_by_fold"] == reference.metadata["walk_forward"]["params_by_fold"]
