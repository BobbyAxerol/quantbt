"""Phase 74 public WFO prepared-native routing and parity contracts.

The tests deliberately exercise the normal ``QuantBTEndpoint`` facade.  A
prepared batch may accelerate fresh candidate/fold scoring, but it may not
change Optuna sampling, any selector, the causality schedule, or the one final
stitched account reconstruction.
"""

from __future__ import annotations

import importlib.util

import numpy as np
import pandas as pd
import pytest

from quantbt import QuantBTEndpoint
from quantbt.backends.native_wfo_public import NativePreparedPublicWfoUnsupported
from quantbt.strategies.wfo_prepared import PreparedWfoStrategyUnsupported


pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("_quantbt_native") is None,
    reason="quantbt-native extension is not installed in this environment",
)


def _bars(*, periods: int = 720, frequency: str = "1D") -> pd.DataFrame:
    index = pd.date_range("2020-01-01", periods=periods, freq=frequency, tz="UTC")
    phase = np.arange(len(index), dtype=np.float64)
    close = 100.0 + 0.04 * phase + np.sin(phase / 7.0) + 0.35 * np.cos(phase / 19.0)
    return pd.DataFrame(
        {
            "open": close - 0.12,
            "high": close + 0.75,
            "low": close - 0.75,
            "close": close,
            "volume": 1_000.0 + phase,
            "funding_rate": np.where((phase.astype(int) % 5) == 0, 0.00015, -0.00005),
        },
        index=index,
    )


def _transition_strategy(data, params, train_index, test_index, fold):
    """Create multiple reversals without inspecting data after ``test_index``."""

    del data, train_index, fold
    direction = float(params["direction"])
    bars = np.arange(len(test_index), dtype=np.int64)
    base = np.where((bars // 11) % 2 == 0, 1.0, -1.0)
    return pd.Series(direction * base, index=test_index, dtype=float)


def _absolute_transition_signal(index: pd.DatetimeIndex, direction: float) -> np.ndarray:
    """A full-tape formulation whose W0/W1/W2 projections are identical."""

    epoch = pd.Timestamp("2020-01-01", tz="UTC")
    bars = ((pd.DatetimeIndex(index).asi8 - epoch.value) // pd.Timedelta("1D").value).astype(np.int64)
    base = np.where((bars // 11) % 2 == 0, 1.0, -1.0)
    return np.asarray(float(direction) * base, dtype=np.float64)


class _PreparedW1Intent:
    causal_cache_contract = "causal_parameter_independent_v1"

    def __init__(self, index: pd.DatetimeIndex) -> None:
        self.index = pd.DatetimeIndex(index)

    def generate(self, *, params, fold_id):
        del fold_id
        return {"signal": _absolute_transition_signal(self.index, float(params["direction"]))}


class _PreparedW2Intent(_PreparedW1Intent):
    def generate_batch(self, *, params_matrix, fold_id):
        del fold_id
        rows = [_absolute_transition_signal(self.index, float(params["direction"])) for params in params_matrix]
        return {"signal": np.ascontiguousarray(np.vstack(rows), dtype=np.float64)}


class _PreparedPublicStrategy:
    causal_cache_contract = "causal_parameter_independent_v1"

    def __init__(self, adapter: str) -> None:
        self.adapter = adapter

    def __call__(self, *, data, params, train_index, test_index, fold):
        del data, train_index, fold
        return pd.Series(
            _absolute_transition_signal(test_index, float(params["direction"])),
            index=test_index,
            dtype=float,
        )

    def prepare_wfo(self, *, data, folds, static_config):
        assert static_config["schema"] == "quantbt-prepared-wfo-strategy-v1"
        assert len(data) == len(static_config["datetime_index"])
        assert len(folds) > 0
        if self.adapter == "w1":
            return _PreparedW1Intent(data.index)
        return _PreparedW2Intent(data.index)


class _UndeclaredPreparedStrategy(_PreparedPublicStrategy):
    causal_cache_contract = "undeclared"

    def prepare_wfo(self, *, data, folds, static_config):
        prepared = super().prepare_wfo(data=data, folds=folds, static_config=static_config)
        prepared.causal_cache_contract = "undeclared"
        return prepared


class _W0OnlyStrategyClass:
    def __call__(self, *, data, params, train_index, test_index, fold):
        del data, train_index, fold
        return pd.Series(
            _absolute_transition_signal(test_index, float(params["direction"])),
            index=test_index,
            dtype=float,
        )


def _mode_config(mode: str, *, native_policy: str) -> dict[str, object]:
    common: dict[str, object] = {
        "top_is_fraction": 1.0,
        "flat_eps": 1.0,
        "flat_min_samples": 1,
        "scoring_backend": "endpoint",
        "native_prepared_wfo": native_policy,
        "native_prepared_wfo_workers": 1,
        "scoring_trading_days": 365,
        "min_trades_per_year": None,
        "trade_penalty_factor": None,
    }
    if mode == "mode_1_decay":
        return {**common, "candidate_selection_metric": "robust_decay"}
    if mode == "mode_3_flat_minima":
        return {**common, "candidate_selection_metric": "is_plateau_robust"}
    if mode == "mode_4_is_only_robust":
        return {
            **common,
            "candidate_selection_metric": "is_only_robust",
            "is_subperiods": 2,
        }
    if mode == "mode_5_full_robust":
        return {
            **common,
            "candidate_selection_metric": "full_robust",
            "is_subperiods": 1,
        }
    raise AssertionError(f"unexpected endpoint-native mode {mode!r}")


def _run_public(
    data: pd.DataFrame,
    *,
    mode: str,
    native_policy: str,
    schedule: str = "global",
    target_mode: str = "signal_notional",
    use_funding: bool = False,
):
    config = _mode_config(mode, native_policy=native_policy)
    if schedule == "per_fold_decay":
        config["candidate_selection_metric"] = "robust_decay"
    elif schedule == "per_fold_causal" and mode == "mode_1_decay":
        config.update(
            {
                "candidate_selection_metric": "robust_decay",
                "inner_split_frequency": "monthly",
                "inner_window_mode": "rolling",
                "inner_train_window": "60D",
                "inner_min_folds": 2,
            }
        )

    endpoint = QuantBTEndpoint.walk_forward(
        strategy_class=_transition_strategy,
        split_mode="2020-07-01",
        split_frequency="quarterly",
        window_mode="rolling",
        train_window="180D",
        target_mode=target_mode,
        optimization_mode=mode,
        optimization_schedule=schedule,
        optimization_config=config,
        optuna_trials=2,
        random_seed=71,
        initial_capital=20_000.0,
        leverage=3.0,
        maintenance_ratio=0.005,
        alloc_per_trade=1_000.0,
        fee_rate=0.0002,
        slippage=0.0001,
        use_funding=use_funding,
        funding_rate=data["funding_rate"] if use_funding else 0.0,
        target_runtime="rust",
    )
    result = endpoint.backtest(
        data=data,
        symbols=["BTC"],
        param_ranges={"direction": [-1.0, 1.0]},
    )
    return endpoint, result


def _run_prepared_strategy(
    data: pd.DataFrame,
    *,
    adapter: str,
    schedule: str = "global",
    strategy=None,
):
    config = _mode_config("mode_4_is_only_robust", native_policy="require")
    config.update(
        {
            "prepared_wfo_strategy": "require",
            "prepared_wfo_strategy_adapter": adapter,
        }
    )
    endpoint = QuantBTEndpoint.walk_forward(
        strategy_class=strategy or _PreparedPublicStrategy(adapter),
        split_mode="2020-07-01",
        split_frequency="quarterly",
        window_mode="rolling",
        train_window="180D",
        target_mode="signal_notional",
        optimization_mode="mode_4_is_only_robust",
        optimization_schedule=schedule,
        optimization_config=config,
        optuna_trials=2,
        random_seed=71,
        initial_capital=20_000.0,
        leverage=3.0,
        maintenance_ratio=0.005,
        alloc_per_trade=1_000.0,
        fee_rate=0.0002,
        slippage=0.0001,
        use_funding=True,
        funding_rate=data["funding_rate"],
        target_runtime="rust",
    )
    result = endpoint.backtest(
        data=data,
        symbols=["BTC"],
        param_ranges={"direction": [-1.0, 1.0]},
    )
    return endpoint, result


def _assert_public_parity(native, reference) -> None:
    pd.testing.assert_series_equal(native.equity, reference.equity, check_exact=False, atol=1e-10)
    pd.testing.assert_series_equal(native.returns, reference.returns, check_exact=False, atol=1e-12)
    pd.testing.assert_frame_equal(native.positions, reference.positions, check_exact=False, atol=1e-12)
    for native_cost, reference_cost in (
        (native.fees, reference.fees),
        (native.funding, reference.funding),
    ):
        if isinstance(native_cost, pd.Series):
            assert isinstance(reference_cost, pd.Series)
            pd.testing.assert_series_equal(
                native_cost,
                reference_cost,
                check_exact=False,
                atol=1e-12,
            )
        else:
            assert isinstance(reference_cost, pd.DataFrame)
            pd.testing.assert_frame_equal(
                native_cost,
                reference_cost,
                check_exact=False,
                atol=1e-12,
            )

    native_wf = native.metadata["walk_forward"]
    reference_wf = reference.metadata["walk_forward"]
    assert native_wf["params"] == reference_wf["params"]
    assert native_wf["params_by_fold"] == reference_wf["params_by_fold"]
    assert native_wf["best_trial"]["params"] == reference_wf["best_trial"]["params"]
    for field in ("objective", "mean_is_sharpe", "mean_oos_sharpe", "mean_decay", "std_decay"):
        assert native_wf["best_trial"][field] == pytest.approx(
            reference_wf["best_trial"][field], abs=1e-10
        )

    columns = [
        column
        for column in ("trial_id", "objective", "mean_is_sharpe", "mean_oos_sharpe", "mean_decay", "std_decay")
        if column in native_wf["trial_table"].columns
    ]
    np.testing.assert_allclose(
        native_wf["trial_table"][columns].select_dtypes(include=[np.number]).to_numpy(dtype=float),
        reference_wf["trial_table"][columns].select_dtypes(include=[np.number]).to_numpy(dtype=float),
        rtol=0.0,
        atol=1e-10,
    )
    pd.testing.assert_series_equal(
        native.metadata["walk_forward_result"].oos_output,
        reference.metadata["walk_forward_result"].oos_output,
        check_exact=False,
        atol=1e-12,
    )


@pytest.mark.parametrize(
    "mode",
    [
        "mode_1_decay",
        "mode_3_flat_minima",
        "mode_4_is_only_robust",
        "mode_5_full_robust",
    ],
)
def test_phase74_native_prepared_public_modes_preserve_selection_and_final_account(mode: str):
    data = _bars()
    _native_endpoint, native = _run_public(data, mode=mode, native_policy="require")
    _reference_endpoint, reference = _run_public(data, mode=mode, native_policy="off")

    _assert_public_parity(native, reference)
    prepared = native.metadata["walk_forward"]["prepared_scoring_cache"]["native_prepared_wfo"]
    assert prepared["requested_policy"] == "require"
    assert prepared["resolved_policy"] == "native_prepared"
    assert prepared["native_batches"] > 0
    assert prepared["native_rows"] > 0
    assert prepared["native_scored_bars"] > 0
    assert prepared["fresh_account_policy"] == "fresh_account_per_evaluation"
    assert prepared["final_account_policy"] == "endpoint_stitched_continuous_account"
    assert native.metadata["walk_forward"]["prepared_scoring_cache"]["released_after_run"] is True


@pytest.mark.parametrize(
    ("mode", "schedule"),
    [
        ("mode_1_decay", "per_fold_decay"),
        ("mode_1_decay", "per_fold_causal"),
        ("mode_4_is_only_robust", "per_fold_causal"),
    ],
)
def test_phase74_native_prepared_preserves_supported_per_fold_schedules(mode: str, schedule: str):
    data = _bars()
    _native_endpoint, native = _run_public(data, mode=mode, native_policy="require", schedule=schedule)
    _reference_endpoint, reference = _run_public(data, mode=mode, native_policy="off", schedule=schedule)

    _assert_public_parity(native, reference)
    native_wf = native.metadata["walk_forward"]
    assert native_wf["optimization_schedule"] == schedule
    assert native_wf["prepared_scoring_cache"]["native_prepared_wfo"]["native_batches"] > 0
    if schedule == "per_fold_causal":
        assert native_wf["oos_used_for_selection"] is False
    else:
        assert native_wf["oos_used_for_selection"] is True


def test_phase74_mode2_keeps_proxy_path_explicit_and_require_fails_closed():
    data = _bars()
    endpoint = QuantBTEndpoint.walk_forward(
        strategy_class=_transition_strategy,
        split_mode="2020-07-01",
        split_frequency="quarterly",
        window_mode="rolling",
        train_window="180D",
        target_mode="signal_notional",
        optimization_mode="mode_2_sbb",
        optimization_config={
            "candidate_selection_metric": "robust_decay",
            "scoring_backend": "proxy",
            "sbb_samples": 8,
            "sbb_block_length": 3,
            "native_prepared_wfo": "auto",
        },
        optuna_trials=2,
        random_seed=71,
        initial_capital=20_000.0,
        alloc_per_trade=1_000.0,
        fee_rate=0.0002,
        use_funding=False,
        target_runtime="rust",
    )
    result = endpoint.backtest(data=data, symbols=["BTC"], param_ranges={"direction": [-1.0, 1.0]})
    resolution = result.metadata["walk_forward"]["native_prepared_wfo"]
    assert resolution["requested_policy"] == "auto"
    assert resolution["resolved_policy"] == "proxy_preserved"
    assert resolution["native_batches"] == 0
    assert "path-resampling" in resolution["reason"]

    with pytest.raises(NotImplementedError, match="mode_2_sbb deliberately retains"):
        QuantBTEndpoint.walk_forward(
            strategy_class=_transition_strategy,
            target_mode="signal_notional",
            optimization_mode="mode_2_sbb",
            optimization_config={"scoring_backend": "proxy", "native_prepared_wfo": "require"},
            target_runtime="rust",
        )


def test_phase74_train_test_split_funding_cost_and_transition_parity():
    data = _bars(periods=720, frequency="12h")

    def run(policy: str):
        endpoint = QuantBTEndpoint.train_test_split(
            strategy_class=_transition_strategy,
            test_start="2020-06-01",
            target_mode="signal_notional",
            optimization_mode="mode_4_is_only_robust",
            optimization_config={
                **_mode_config("mode_4_is_only_robust", native_policy=policy),
                "is_subperiods": 2,
            },
            optuna_trials=2,
            random_seed=71,
            initial_capital=20_000.0,
            leverage=3.0,
            alloc_per_trade=1_000.0,
            fee_rate=0.0002,
            slippage=0.0001,
            use_funding=True,
            funding_rate=data["funding_rate"],
            target_runtime="rust",
        )
        return endpoint.backtest(
            data=data,
            symbols=["BTC"],
            param_ranges={"direction": [-1.0, 1.0]},
        )

    native = run("require")
    reference = run("off")
    _assert_public_parity(native, reference)
    assert float(native.fees.to_numpy(dtype=float).sum()) > 0.0
    assert float(np.abs(native.funding.to_numpy(dtype=float)).sum()) > 0.0


@pytest.mark.parametrize("target_mode", ["notional", "unit"])
def test_phase74_native_prepared_supports_explicit_single_symbol_target_routes(target_mode: str):
    data = _bars()
    _native_endpoint, native = _run_public(
        data,
        mode="mode_4_is_only_robust",
        native_policy="require",
        target_mode=target_mode,
    )
    _reference_endpoint, reference = _run_public(
        data,
        mode="mode_4_is_only_robust",
        native_policy="off",
        target_mode=target_mode,
    )

    _assert_public_parity(native, reference)
    prepared = native.metadata["walk_forward"]["native_prepared_wfo"]
    assert prepared["resolved_policy"] == "native_prepared"
    assert prepared["native_rows"] > 0
    assert prepared["native_scored_bars"] > 0


def test_phase74_prepared_causal_prefix_ignores_appended_future_market_and_funding():
    short_data = _bars(periods=540)
    extended_data = _bars(periods=720)
    future = extended_data.index > short_data.index[-1]
    extended_data.loc[future, "close"] += 50_000.0
    extended_data.loc[future, "open"] += 50_000.0
    extended_data.loc[future, "high"] += 50_000.0
    extended_data.loc[future, "low"] += 50_000.0
    extended_data.loc[future, "funding_rate"] = 0.99

    _short_endpoint, short = _run_public(
        short_data,
        mode="mode_4_is_only_robust",
        native_policy="require",
        schedule="per_fold_causal",
    )
    _extended_endpoint, extended = _run_public(
        extended_data,
        mode="mode_4_is_only_robust",
        native_policy="require",
        schedule="per_fold_causal",
    )

    short_wf = short.metadata["walk_forward"]
    extended_wf = extended.metadata["walk_forward"]
    assert short_wf["params_by_fold"] == {
        fold_id: params
        for fold_id, params in extended_wf["params_by_fold"].items()
        if fold_id < len(short_wf["params_by_fold"])
    }
    short_output = short.metadata["walk_forward_result"].oos_output
    extended_output = extended.metadata["walk_forward_result"].oos_output
    pd.testing.assert_series_equal(
        short_output,
        extended_output.reindex(short_output.index),
        check_exact=False,
        atol=1e-12,
    )
    pd.testing.assert_series_equal(
        short.equity,
        extended.equity.reindex(short.equity.index),
        check_exact=False,
        atol=1e-10,
    )


def test_phase74_auto_fallback_preserves_legacy_pct_equity_until_explicit_native_opt_in():
    data = _bars()
    endpoint = QuantBTEndpoint.walk_forward(
        strategy_class=_transition_strategy,
        split_mode="2020-07-01",
        split_frequency="single",
        target_mode="pct_equity",
        optimization_mode="mode_4_is_only_robust",
        optimization_config={
            "candidate_selection_metric": "is_only_robust",
            "top_is_fraction": 1.0,
            "flat_eps": 1.0,
            "flat_min_samples": 1,
            "is_subperiods": 2,
            "scoring_backend": "endpoint",
            "native_prepared_wfo": "auto",
        },
        optuna_trials=2,
        random_seed=71,
        initial_capital=20_000.0,
        leverage=3.0,
        alloc_per_trade=0.5,
        fee_rate=0.0002,
        use_funding=False,
        target_runtime="rust",
    )
    result = endpoint.backtest(data=data, symbols=["BTC"], param_ranges={"direction": [-1.0, 1.0]})
    prepared = result.metadata["walk_forward"]["prepared_scoring_cache"]["native_prepared_wfo"]
    assert prepared["requested_policy"] == "auto"
    assert prepared["resolved_policy"] == "fallback"
    assert "target_mode" in str(prepared["reason"])
    assert prepared["native_batches"] == 0

    _endpoint, native = _run_public(
        data,
        mode="mode_4_is_only_robust",
        native_policy="require",
        target_mode="pct_equity",
    )
    native_prepared = native.metadata["walk_forward"]["prepared_scoring_cache"]["native_prepared_wfo"]
    assert native_prepared["resolved_policy"] == "native_prepared"
    assert native_prepared["score_adapter"] == "scalar_columns_v1"


@pytest.mark.parametrize("adapter", ["w1", "w2"])
def test_phase74_public_w1_w2_strategy_adapters_preserve_w0_selection_and_stitched_account(adapter: str):
    data = _bars()
    _prepared_endpoint, prepared = _run_prepared_strategy(data, adapter=adapter)

    config = _mode_config("mode_4_is_only_robust", native_policy="require")
    reference_endpoint = QuantBTEndpoint.walk_forward(
        strategy_class=_PreparedPublicStrategy(adapter),
        split_mode="2020-07-01",
        split_frequency="quarterly",
        window_mode="rolling",
        train_window="180D",
        target_mode="signal_notional",
        optimization_mode="mode_4_is_only_robust",
        optimization_config=config,
        optuna_trials=2,
        random_seed=71,
        initial_capital=20_000.0,
        leverage=3.0,
        maintenance_ratio=0.005,
        alloc_per_trade=1_000.0,
        fee_rate=0.0002,
        slippage=0.0001,
        use_funding=True,
        funding_rate=data["funding_rate"],
        target_runtime="rust",
    )
    reference = reference_endpoint.backtest(
        data=data,
        symbols=["BTC"],
        param_ranges={"direction": [-1.0, 1.0]},
    )

    _assert_public_parity(prepared, reference)
    provenance = prepared.metadata["walk_forward"]["prepared_wfo_strategy"]
    assert provenance["resolved_adapter"] == adapter
    assert provenance["cache_contract"] == "causal_parameter_independent_v1"
    assert provenance["prepare_calls"] == 1
    assert provenance["generate_calls"] > 0
    assert provenance["closed"] is True
    assert provenance[f"{adapter}_generate{'_batch' if adapter == 'w2' else ''}_calls"] > 0


def test_phase74_public_w2_strategy_adapter_keeps_causal_per_fold_selection_isolated():
    data = _bars()
    _prepared_endpoint, prepared = _run_prepared_strategy(
        data,
        adapter="w2",
        schedule="per_fold_causal",
    )
    provenance = prepared.metadata["walk_forward"]["prepared_wfo_strategy"]
    assert provenance["resolved_adapter"] == "w2"
    assert prepared.metadata["walk_forward"]["oos_used_for_selection"] is False
    assert prepared.metadata["walk_forward"]["signal_causality_scope"] == (
        "prepared_strategy_declared_parameter_independent_cache_v1"
    )


def test_phase74_public_prepared_w2_causal_prefix_is_invariant_to_future_market_mutation():
    short_data = _bars(periods=540)
    extended_data = _bars(periods=720)
    future = extended_data.index > short_data.index[-1]
    extended_data.loc[future, ["open", "high", "low", "close"]] += 50_000.0
    extended_data.loc[future, "funding_rate"] = 0.99

    _short_endpoint, short = _run_prepared_strategy(
        short_data,
        adapter="w2",
        schedule="per_fold_causal",
    )
    _extended_endpoint, extended = _run_prepared_strategy(
        extended_data,
        adapter="w2",
        schedule="per_fold_causal",
    )

    short_wf = short.metadata["walk_forward"]
    extended_wf = extended.metadata["walk_forward"]
    assert short_wf["params_by_fold"] == {
        fold_id: params
        for fold_id, params in extended_wf["params_by_fold"].items()
        if fold_id < len(short_wf["params_by_fold"])
    }
    short_output = short.metadata["walk_forward_result"].oos_output
    extended_output = extended.metadata["walk_forward_result"].oos_output
    pd.testing.assert_series_equal(
        short_output,
        extended_output.reindex(short_output.index),
        check_exact=False,
        atol=1e-12,
    )
    pd.testing.assert_series_equal(
        short.equity,
        extended.equity.reindex(short.equity.index),
        check_exact=False,
        atol=1e-10,
    )


def test_phase74_prepared_strategy_auto_falls_back_only_before_generation_and_strict_schedule_requires_contract():
    data = _bars()
    endpoint = QuantBTEndpoint.walk_forward(
        strategy_class=_transition_strategy,
        split_mode="2020-07-01",
        split_frequency="single",
        target_mode="signal_notional",
        optimization_mode="mode_4_is_only_robust",
        optimization_config={
            **_mode_config("mode_4_is_only_robust", native_policy="require"),
            "prepared_wfo_strategy": "auto",
        },
        optuna_trials=2,
        random_seed=71,
        initial_capital=20_000.0,
        alloc_per_trade=1_000.0,
        fee_rate=0.0002,
        target_runtime="rust",
    )
    result = endpoint.backtest(data=data, symbols=["BTC"], param_ranges={"direction": [-1.0, 1.0]})
    fallback = result.metadata["walk_forward"]["prepared_wfo_strategy"]
    assert fallback["resolved_adapter"] == "w0"
    assert "does not expose prepare_wfo" in str(fallback["reason"])

    class_endpoint = QuantBTEndpoint.walk_forward(
        strategy_class=_W0OnlyStrategyClass,
        split_mode="2020-07-01",
        split_frequency="single",
        target_mode="signal_notional",
        optimization_mode="mode_4_is_only_robust",
        optimization_config={
            **_mode_config("mode_4_is_only_robust", native_policy="require"),
            "prepared_wfo_strategy": "auto",
        },
        optuna_trials=2,
        random_seed=71,
        initial_capital=20_000.0,
        alloc_per_trade=1_000.0,
        fee_rate=0.0002,
        target_runtime="rust",
    )
    class_result = class_endpoint.backtest(
        data=data,
        symbols=["BTC"],
        param_ranges={"direction": [-1.0, 1.0]},
    )
    assert class_result.metadata["walk_forward"]["prepared_wfo_strategy"]["resolved_adapter"] == "w0"

    with pytest.raises(PreparedWfoStrategyUnsupported, match="causal_cache_contract"):
        _run_prepared_strategy(
            data,
            adapter="w1",
            schedule="per_fold_causal",
            strategy=_UndeclaredPreparedStrategy("w1"),
        )
