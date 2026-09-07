"""PERF-08 calendar, shard, and prepared-score transport contracts."""

from __future__ import annotations

import importlib.util

import numpy as np
import pandas as pd
import pytest

from quantbt import QuantBTEndpoint
from quantbt.core.wfo_preparation import (
    PreparedWfoWindowRegistryV1,
    split_datetime_index_into_subperiods_v1,
)
from quantbt.core.preprocessor import slice_prepared_market_arrays
from quantbt.backends.native_vectorized import NativeVectorizedBackend, NativeVectorizedConfig
from quantbt.core.schema import AccountConfig, ExecutionConfig
from quantbt.endpoint import _series_to_raw_matrix_prepared
from quantbt.walkforward import WalkForwardConfig, WalkForwardEngine, _split_index_into_subperiods


def _bars(*, periods: int = 720, freq: str = "1D") -> pd.DataFrame:
    index = pd.date_range("2020-01-01", periods=periods, freq=freq, tz="UTC")
    phase = np.arange(periods, dtype=np.float64)
    close = 100.0 + phase * 0.03 + np.sin(phase / 7.0) + np.cos(phase / 19.0)
    return pd.DataFrame(
        {
            "open": close - 0.1,
            "high": close + 0.7,
            "low": close - 0.7,
            "close": close,
            "volume": 1_000.0 + phase,
        },
        index=index,
    )


def _strategy(data, params, train_index, test_index, fold):
    del data, train_index, fold
    bars = np.arange(len(test_index), dtype=np.int64)
    direction = float(params["direction"])
    period = int(params["period"])
    return pd.Series(np.where((bars // period) % 2 == 0, direction, -direction), index=test_index)


class _EndpointScorer:
    """Deterministic stand-in for an endpoint scorer with batch support."""

    def score_batch(self, tasks):
        rows = []
        for task in tasks:
            values = task["output"].reindex(task["index"]).fillna(0.0).to_numpy(dtype=np.float64)
            changes = float(np.count_nonzero(np.diff(np.sign(values))))
            rows.append(
                {
                    "sharpe": float(0.75 + values.mean() * 0.05 + changes / max(1, len(values))),
                    "turnover": changes,
                    "trade_count": changes,
                    "mean_return": float(values.mean() * 0.001),
                    "volatility": 0.0,
                    "max_drawdown_pct": 1.0,
                    "profit_factor": float("inf"),
                }
            )
        return rows


class _LegacyEndpointScorer:
    """Keyword-only legacy scorer used to guard the old public payload."""

    def __call__(self, *, data, output, index, fold, params, context, trading_days):
        del data, fold, params, context, trading_days
        values = output.reindex(index).fillna(0.0).to_numpy(dtype=np.float64)
        changes = float(np.count_nonzero(np.diff(np.sign(values))))
        return {
            "sharpe": float(0.5 + values.mean() * 0.01 + changes / max(1, len(values))),
            "turnover": changes,
            "trade_count": changes,
            "mean_return": float(values.mean() * 0.001),
            "volatility": 0.0,
            "max_drawdown_pct": 1.0,
            "profit_factor": float("inf"),
        }


def _config(mode: str, *, schedule: str, prepared: bool) -> WalkForwardConfig:
    selection = {
        "mode_1_decay": "robust_decay",
        "mode_2_sbb": "robust_decay",
        "mode_3_flat_minima": "is_plateau_robust",
        "mode_4_is_only_robust": "is_only_robust",
        "mode_5_full_robust": "full_robust",
    }[mode]
    values: dict[str, object] = {
        "split_mode": "2020-07-01",
        "split_frequency": "quarterly",
        "window_mode": "rolling",
        "train_window": "120D",
        "min_train_bars": 30,
        "min_test_bars": 20,
        "target_mode": "signal_notional",
        "optimization_mode": mode,
        "optimization_schedule": schedule,
        "optuna_trials": 4,
        "optuna_early_stopping": None,
        "random_seed": 71,
        "top_is_fraction": 1.0,
        "flat_eps": 1.0,
        "flat_min_samples": 1,
        "candidate_selection_metric": selection,
        "scoring_backend": "proxy" if mode == "mode_2_sbb" else "endpoint",
        "scoring_trading_days": 365,
        "min_trades_per_year": 35.0,
        "trade_penalty_factor": 0.5,
        "is_subperiods": 3,
        "sbb_samples": 8,
        "sbb_block_length": 3,
        "metadata": {
            "use_prepared_wfo_context": prepared,
            "wfo_execution_reuse": "off",
        },
    }
    if schedule == "per_fold_causal" and mode == "mode_1_decay":
        values.update(
            {
                "inner_split_frequency": "monthly",
                "inner_window_mode": "rolling",
                "inner_train_window": "60D",
                "inner_min_folds": 1,
            }
        )
    return WalkForwardConfig(**values)


def _run(mode: str, *, schedule: str, prepared: bool):
    config = _config(mode, schedule=schedule, prepared=prepared)
    scorer = None if mode == "mode_2_sbb" else _EndpointScorer()
    return WalkForwardEngine(strategy=_strategy, config=config, scorer=scorer).run(
        _bars(),
        param_ranges={"direction": [-1.0, 1.0], "period": [3, 5]},
    )


@pytest.mark.parametrize(
    ("mode", "schedule"),
    (
        ("mode_1_decay", "global"),
        ("mode_1_decay", "per_fold_causal"),
        ("mode_2_sbb", "global"),
        ("mode_3_flat_minima", "global"),
        ("mode_4_is_only_robust", "global"),
        ("mode_4_is_only_robust", "per_fold_causal"),
        ("mode_5_full_robust", "global"),
    ),
)
def test_perf08_prepared_context_preserves_mode_selection_and_oos_output(mode: str, schedule: str):
    baseline = _run(mode, schedule=schedule, prepared=False)
    optimized = _run(mode, schedule=schedule, prepared=True)

    pd.testing.assert_series_equal(optimized.oos_output, baseline.oos_output, check_exact=True)
    pd.testing.assert_frame_equal(optimized.trial_table, baseline.trial_table, check_exact=True)
    pd.testing.assert_frame_equal(optimized.candidate_table, baseline.candidate_table, check_exact=True)
    assert optimized.params == baseline.params
    assert optimized.best_trial == baseline.best_trial

    prepared = optimized.metadata["prepared_wfo_context"]
    assert prepared["enabled"] is True
    assert prepared["window_preparation"]["canonical_windows"] > 0
    if mode in {"mode_4_is_only_robust", "mode_5_full_robust"}:
        assert prepared["window_preparation"]["prepared_shard_sets"] > 0
        assert prepared["window_preparation"]["shard_lookup_hits"] > 0
    if schedule == "per_fold_causal" and mode == "mode_1_decay":
        assert prepared["prepared_inner_fold_groups"] > 0


@pytest.mark.parametrize("parts", (1, 2, 3, 7, 99))
def test_perf08_positional_split_is_exact_numpy_array_split_parity(parts: int):
    regular = pd.date_range("2024-03-09", periods=11, freq="1h", tz="America/New_York", name="clock")
    irregular = pd.DatetimeIndex(
        pd.to_datetime(
            ["2024-03-09 23:00Z", "2024-03-10 01:00Z", "2024-03-10 07:00Z", "2024-03-11 00:00Z"], utc=True),
        name="clock",
    )
    for index in (regular, irregular):
        normalized = pd.DatetimeIndex(index).tz_convert("UTC")
        count = max(1, min(int(parts), len(normalized)))
        expected = [pd.DatetimeIndex(chunk) for chunk in np.array_split(normalized, count) if len(chunk)]
        observed = split_datetime_index_into_subperiods_v1(normalized, parts)
        fallback = _split_index_into_subperiods(normalized, parts)
        assert len(observed) == len(expected)
        for actual, reference, legacy in zip(observed, expected, fallback, strict=True):
            pd.testing.assert_index_equal(actual, reference, exact=True)
            pd.testing.assert_index_equal(legacy, reference, exact=True)


def test_perf08_registry_is_identity_scoped_and_keeps_exact_trade_requirements():
    index = pd.date_range("2024-01-01", periods=12, freq="1h", tz="UTC")
    registry = PreparedWfoWindowRegistryV1(index)
    registered = registry.register(index[2:10])
    assert registered is not None
    assert (registered.start, registered.stop, registered.bars) == (2, 10, 8)
    shards = registry.register_shards(index[2:10], 3)
    assert [len(item) for item in shards] == [3, 3, 2]
    assert registry.window_for(index[2:10]) is None  # a fresh but equal view is deliberately not cached
    assert registry.shards_for(index[2:10], 3) is None

    owned = registered.index
    requirement = registry.required_trades_for(owned, 365.0)
    assert requirement == pytest.approx((owned[-1] - owned[0]).total_seconds() / 86_400.0)
    assert registry.required_trades_for(owned, 365.0) == requirement
    metadata = registry.metadata()
    assert metadata["trade_requirement_hits"] == 1
    assert metadata["trade_requirement_misses"] == 1


def test_perf08_prepared_market_view_is_exact_readonly_and_rejects_wrong_clock():
    index = pd.date_range("2024-01-01", periods=12, freq="1h", tz="UTC")
    values = pd.Series(np.arange(len(index), dtype=np.float64) + 100.0, index=index)
    backend = NativeVectorizedBackend(
        NativeVectorizedConfig(
            account=AccountConfig(initial_capital=1_000.0, leverage=2.0),
            execution=ExecutionConfig(),
        )
    )
    parent = backend.prepare_market_arrays(
        datetime_index=index,
        closes={"BTC": values},
        highs={"BTC": values + 1.0},
        lows={"BTC": values - 1.0},
        symbols=["BTC"],
    )
    child_index = index[3:9]
    view = slice_prepared_market_arrays(parent, start=3, stop=9, idx=child_index)
    np.testing.assert_array_equal(view.closes[:, 0], parent.closes[3:9, 0])
    assert not view.closes.flags.writeable
    assert np.shares_memory(view.closes, parent.closes)
    with pytest.raises(ValueError, match="index does not match"):
        slice_prepared_market_arrays(parent, start=3, stop=9, idx=index[2:8])


def test_perf08_exact_signal_matrix_is_readonly_consumer_view_without_mutation():
    index = pd.date_range("2024-01-01", periods=8, freq="1h", tz="UTC")
    values = np.linspace(-1.0, 1.0, len(index), dtype=np.float64)
    signal = pd.Series(values, index=index)
    matrix, no_copy = _series_to_raw_matrix_prepared(signal, index)
    assert no_copy is True
    assert np.shares_memory(matrix, values)
    before = values.copy()
    # Consumers must treat this exact prepared view as read-only.  The test
    # proves the helper itself does not alter strategy-owned signal storage.
    np.testing.assert_array_equal(matrix[:, 0], before)
    np.testing.assert_array_equal(values, before)


def test_perf08_native_vectorized_validated_market_guard_rejects_recreated_clock():
    index = pd.date_range("2024-01-01", periods=8, freq="1h", tz="UTC")
    values = pd.Series(np.arange(len(index), dtype=np.float64) + 100.0, index=index)
    backend = NativeVectorizedBackend(
        NativeVectorizedConfig(
            account=AccountConfig(initial_capital=1_000.0, leverage=2.0),
            execution=ExecutionConfig(),
        )
    )
    market = backend.prepare_market_arrays(
        datetime_index=index,
        closes={"BTC": values},
        highs={"BTC": values + 1.0},
        lows={"BTC": values - 1.0},
        symbols=["BTC"],
    )
    clone = pd.DatetimeIndex(index.asi8, tz="UTC")
    with pytest.raises(ValueError, match="exact prepared market clock"):
        backend.run_signals(
            datetime_index=clone,
            positions={"BTC": values},
            closes={"BTC": values},
            symbols=["BTC"],
            market_arrays=market,
            raw_signal_matrix=np.zeros((len(index), 1), dtype=np.float64),
            _validated_prepared_market=True,
        )
    raw = np.linspace(-1.0, 1.0, len(index), dtype=np.float64).reshape(-1, 1)
    before = raw.copy()
    backend.score_signals(
        datetime_index=market.idx,
        positions={"BTC": values},
        closes={"BTC": values},
        symbols=["BTC"],
        market_arrays=market,
        raw_signal_matrix=raw,
        _validated_prepared_market=True,
    )
    np.testing.assert_array_equal(raw, before)


def test_perf08_legacy_endpoint_scorer_keeps_historic_keyword_surface():
    config = _config("mode_1_decay", schedule="global", prepared=True)
    result = WalkForwardEngine(strategy=_strategy, config=config, scorer=_LegacyEndpointScorer()).run(
        _bars(),
        param_ranges={"direction": [-1.0, 1.0], "period": [3, 5]},
    )
    assert not result.trial_table.empty


def test_perf08_generic_endpoint_scorer_uses_one_full_market_tape_and_window_views():
    data = _bars(periods=720)
    endpoint = QuantBTEndpoint.walk_forward(
        strategy_class=_strategy,
        split_mode="2020-07-01",
        split_frequency="quarterly",
        window_mode="rolling",
        train_window="120D",
        target_mode="signal_notional",
        optimization_mode="mode_4_is_only_robust",
        optimization_schedule="per_fold_causal",
        optimization_config={
            "candidate_selection_metric": "is_only_robust",
            "top_is_fraction": 1.0,
            "flat_eps": 1.0,
            "flat_min_samples": 1,
            "is_subperiods": 3,
            "scoring_backend": "endpoint",
            "native_prepared_wfo": "off",
            "use_prepared_wfo_context": True,
        },
        optuna_trials=3,
        random_seed=71,
        initial_capital=20_000.0,
        leverage=3.0,
        alloc_per_trade=1_000.0,
        fee_rate=0.0002,
        use_funding=False,
        target_runtime="rust",
    )
    result = endpoint.backtest(
        data=data,
        symbols=["BTC"],
        param_ranges={"direction": [-1.0, 1.0], "period": [3, 5]},
    )
    stats = result.metadata["walk_forward"]["prepared_scoring_cache"]
    # Metadata is captured before release so it records the run-local owner;
    # the public lifecycle flag proves that owner was cleared afterwards.
    assert stats["prepared_full_market_entries"] == 1
    assert stats["released_after_run"] is True
    assert stats["full_market_cache_misses"] == 1
    assert stats["prepared_window_view_misses"] > 0
    assert stats["prepared_window_view_hits"] > 0
    assert stats["signal_no_copy_hits"] > 0


@pytest.mark.skipif(
    importlib.util.find_spec("_quantbt_native") is None,
    reason="prepared native scorer requires the optional quantbt-native extension",
)
def test_perf08_native_prepared_score_uses_context_owned_windows_without_account_change():
    data = _bars(periods=720)

    def run(policy: str):
        endpoint = QuantBTEndpoint.walk_forward(
            strategy_class=_strategy,
            split_mode="2020-07-01",
            split_frequency="quarterly",
            window_mode="rolling",
            train_window="120D",
            target_mode="signal_notional",
            optimization_mode="mode_4_is_only_robust",
            optimization_schedule="per_fold_causal",
            optimization_config={
                "candidate_selection_metric": "is_only_robust",
                "top_is_fraction": 1.0,
                "flat_eps": 1.0,
                "flat_min_samples": 1,
                "is_subperiods": 3,
                "scoring_backend": "endpoint",
                "native_prepared_wfo": policy,
            },
            optuna_trials=3,
            random_seed=71,
            initial_capital=20_000.0,
            leverage=3.0,
            alloc_per_trade=1_000.0,
            fee_rate=0.0002,
            use_funding=False,
            target_runtime="rust",
        )
        return endpoint.backtest(
            data=data,
            symbols=["BTC"],
            param_ranges={"direction": [-1.0, 1.0], "period": [3, 5]},
        )

    native = run("require")
    reference = run("off")
    pd.testing.assert_series_equal(native.equity, reference.equity, check_exact=False, atol=1.0e-10)
    pd.testing.assert_series_equal(native.returns, reference.returns, check_exact=False, atol=1.0e-12)
    pd.testing.assert_frame_equal(native.positions, reference.positions, check_exact=False, atol=1.0e-12)
    native_wf = native.metadata["walk_forward"]
    reference_wf = reference.metadata["walk_forward"]
    assert native_wf["params_by_fold"] == reference_wf["params_by_fold"]
    score_stats = native_wf["prepared_scoring_cache"]["native_prepared_wfo"]
    assert score_stats["prepared_window_hits"] > 0
    assert score_stats["prepared_window_fallbacks"] == 0
