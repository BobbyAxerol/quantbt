"""Phase 77.2 `%_equity` transition contract and prepared-WFO parity.

The reference remains the long-lived Numba ``_engine_pct_equity`` route.
These tests intentionally compare public endpoint behavior rather than just a
Rust kernel: legacy result positions expose processed signal weights while the
native audit retains accepted units separately.
"""

from __future__ import annotations

import importlib.util

import numpy as np
import pandas as pd
import pytest

from quantbt import QuantBTEndpoint
from quantbt.core.schema import ExecutionConfig
from quantbt.backends.native_prepared_evaluation import (
    NativePreparedEvaluationRuntimeV1,
    NativePreparedWorkloadV1,
)
from quantbt.preparation.native_execution import CachePolicy, NativeExecutionPreparationCache


pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("_quantbt_native") is None,
    reason="quantbt-native extension is not installed in this environment",
)


def _market(*, periods: int = 400) -> pd.DataFrame:
    index = pd.date_range("2020-01-01", periods=periods, freq="1D", tz="UTC")
    phase = np.arange(periods, dtype=np.float64)
    close = 100.0 + np.cumsum(0.13 + np.sin(phase / 8.0))
    return pd.DataFrame(
        {
            "open": close - 0.15,
            "high": close + 2.25,
            "low": close - 2.25,
            "close": close,
            "volume": 1_000.0 + phase,
        },
        index=index,
    )


def _signal(index: pd.DatetimeIndex) -> pd.Series:
    phase = np.arange(len(index), dtype=np.int64)
    values = np.select(
        [phase % 17 < 4, phase % 17 < 8, phase % 17 < 12],
        [1.0, -1.0, 0.5],
        default=0.0,
    )
    return pd.Series(values, index=index, dtype=float)


def _pct_kwargs(*, funding_rate=0.0, alloc_per_trade=0.5, leverage=3.0) -> dict[str, object]:
    return {
        "initial_capital": 20_000.0,
        "leverage": leverage,
        "maintenance_ratio": 0.005,
        "contract_size": 1.0,
        "use_funding": True,
        "funding_rate": funding_rate,
        # Legacy round-trip compatibility field: canonical one-way is .0002.
        "fee": 0.0004,
        "slippage": 0.0001,
        "alloc_per_trade": alloc_per_trade,
        "use_pyramiding": True,
        "qty_step": 0.001,
    }


def _assert_endpoint_parity(reference, native) -> None:
    np.testing.assert_allclose(reference.equity.to_numpy(), native.equity.to_numpy(), rtol=0.0, atol=1e-10)
    np.testing.assert_allclose(reference.returns.to_numpy(), native.returns.to_numpy(), rtol=0.0, atol=1e-12)
    np.testing.assert_allclose(reference.positions.to_numpy(), native.positions.to_numpy(), rtol=0.0, atol=0.0)
    assert reference.liquidated is native.liquidated
    assert reference.liquidation_bar == native.liquidation_bar
    assert reference.full_report() == native.full_report()


def test_pct_equity_rust_transition_matches_legacy_with_funding_and_lots() -> None:
    data = _market(periods=96)
    signal = _signal(data.index)
    funding = pd.Series(
        np.where((np.arange(len(data)) % 8) == 0, 0.00015, -0.00005), index=data.index
    )
    kwargs = _pct_kwargs(funding_rate=funding)

    reference = QuantBTEndpoint.pct_equity(**kwargs).backtest(data=data, signal=signal, symbols=["BTC"])
    native = QuantBTEndpoint.pct_equity(**kwargs, target_runtime="rust").backtest(
        data=data,
        signal=signal,
        symbols=["BTC"],
    )

    _assert_endpoint_parity(reference, native)
    transition = native.metadata["pct_equity_transition"]
    assert transition["contract"] == "pct_equity_transition_v1"
    assert transition["drift_rebalance"] is False
    assert transition["public_position_surface"] == "processed_signal_weights"
    accepted = transition["accepted_positions"]
    assert accepted.shape == native.positions.shape
    assert list(native.positions.columns) == ["Position_DEFAULT"]
    assert transition["requested_symbol_ignored_for_legacy_compatibility"] == "BTC"
    assert native.metadata["canonical_one_way_fee_rate"] == pytest.approx(0.0002)


def test_pct_equity_rust_transition_preserves_non_pyramiding_sign_processing() -> None:
    data = _market(periods=48)
    signal = pd.Series(
        np.resize(np.asarray([2.5, 2.5, 0.25, -3.0, -3.0, 0.0], dtype=float), len(data)),
        index=data.index,
    )
    kwargs = _pct_kwargs()
    kwargs["use_pyramiding"] = False
    reference = QuantBTEndpoint.pct_equity(**kwargs).backtest(data=data, signal=signal)
    native = QuantBTEndpoint.pct_equity(**kwargs, target_runtime="rust").backtest(data=data, signal=signal)

    _assert_endpoint_parity(reference, native)
    expected = np.sign(signal.to_numpy(dtype=np.float64))
    np.testing.assert_array_equal(native.positions.iloc[:, 0].to_numpy(dtype=np.float64), expected)


def test_pct_equity_rust_transition_matches_legacy_liquidation_path() -> None:
    index = pd.date_range("2024-04-01", periods=6, freq="1h", tz="UTC")
    data = pd.DataFrame(
        {
            "open": [100.0] * 6,
            "high": [100.0, 101.0, 101.0, 101.0, 101.0, 101.0],
            "low": [100.0, 99.0, 1.0, 1.0, 1.0, 1.0],
            "close": [100.0] * 6,
            "volume": [1_000.0] * 6,
        },
        index=index,
    )
    signal = pd.Series([1.0, 2.0, 2.0, 2.0, 0.0, 0.0], index=index)
    kwargs = _pct_kwargs(alloc_per_trade=1.0)
    reference = QuantBTEndpoint.pct_equity(**kwargs).backtest(data=data, signal=signal)
    native = QuantBTEndpoint.pct_equity(**kwargs, target_runtime="rust").backtest(data=data, signal=signal)

    _assert_endpoint_parity(reference, native)
    assert reference.liquidated is native.liquidated is True
    assert reference.liquidation_bar == native.liquidation_bar == 2


def test_pct_equity_rejection_does_not_retry_without_a_new_signal_transition() -> None:
    data = _market(periods=16)
    signal = pd.Series([0.0, 1.0, 1.0, 1.0, 1.0, 0.0] + [0.0] * 10, index=data.index)
    kwargs = _pct_kwargs(alloc_per_trade=500.0, leverage=1.0)

    native = QuantBTEndpoint.pct_equity(**kwargs, target_runtime="rust").backtest(data=data, signal=signal)
    accepted = native.metadata["pct_equity_transition"]["accepted_positions"].iloc[:, 0]

    # The raw public signal remains visible while the rejected unit target
    # stays flat. Bars 2-4 must not create repeated rejected admissions.
    assert native.positions.iloc[1:5, 0].eq(1.0).all()
    assert accepted.iloc[1:5].eq(0.0).all()
    diagnostics = native.diagnostics
    assert int(diagnostics["rejected_orders"].sum()) == 1
    assert int(diagnostics["rejected_orders"].iloc[2:5].sum()) == 0


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"fee_rate": 0.0005}, "fee_rate to equal legacy fee / 2"),
        ({"execution": ExecutionConfig(slippage_bps=3.0)}, "slippage_bps to equal legacy slippage"),
    ],
)
def test_pct_equity_rust_refuses_conflicting_legacy_and_v2_cost_inputs(kwargs, message) -> None:
    data = _market(periods=16)
    with pytest.raises(ValueError, match=message):
        QuantBTEndpoint.pct_equity(**_pct_kwargs(), target_runtime="rust", **kwargs).backtest(
            data=data,
            signal=_signal(data.index),
        )


def _wfo_strategy(data, params, train_index, test_index, fold):
    del data, train_index, fold
    direction = float(params["direction"])
    phase = np.arange(len(test_index), dtype=np.int64)
    return pd.Series(np.where((phase // 11) % 2 == 0, direction, -direction), index=test_index)


def _wfo_result(*, native_policy: str, target_runtime: str, mode: str):
    data = _market()
    config: dict[str, object] = {
        "scoring_backend": "endpoint",
        "top_is_fraction": 1.0,
        "flat_eps": 1.0,
        "flat_min_samples": 1,
        "scoring_trading_days": 365,
        "native_prepared_wfo": native_policy,
    }
    if mode == "mode_1_decay":
        config["candidate_selection_metric"] = "robust_decay"
    elif mode == "mode_3_flat_minima":
        config["candidate_selection_metric"] = "is_plateau_robust"
    elif mode == "mode_4_is_only_robust":
        config.update({"candidate_selection_metric": "is_only_robust", "is_subperiods": 2})
    elif mode == "mode_5_full_robust":
        config.update({"candidate_selection_metric": "full_robust", "is_subperiods": 1})
    else:  # pragma: no cover - test helper misuse
        raise AssertionError(mode)
    endpoint = QuantBTEndpoint.walk_forward(
        strategy_class=_wfo_strategy,
        split_mode="2020-07-01",
        split_frequency="quarterly",
        window_mode="rolling",
        train_window="90D",
        target_mode="pct_equity",
        optimization_mode=mode,
        optimization_config=config,
        optuna_trials=2,
        random_seed=71,
        target_runtime=target_runtime,
        **_pct_kwargs(),
    )
    return endpoint.backtest(data=data, param_ranges={"direction": [-1.0, 1.0]})


@pytest.mark.parametrize(
    "mode",
    [
        "mode_1_decay",
        "mode_3_flat_minima",
        "mode_4_is_only_robust",
        "mode_5_full_robust",
    ],
)
def test_prepared_pct_equity_wfo_matches_legacy_selection_and_stitched_account(mode: str) -> None:
    reference = _wfo_result(native_policy="off", target_runtime="numba", mode=mode)
    native = _wfo_result(native_policy="require", target_runtime="rust", mode=mode)

    _assert_endpoint_parity(reference, native)
    ref_wf = reference.metadata["walk_forward"]
    native_wf = native.metadata["walk_forward"]
    assert ref_wf["best_trial"]["params"] == native_wf["best_trial"]["params"]
    np.testing.assert_allclose(
        ref_wf["trial_table"]["objective"].to_numpy(dtype=float),
        native_wf["trial_table"]["objective"].to_numpy(dtype=float),
        rtol=0.0,
        atol=1e-10,
        equal_nan=True,
    )
    prepared = native_wf["native_prepared_wfo"]
    assert prepared["resolved_policy"] == "native_prepared"
    assert prepared["fallback_rows"] == 0
    assert native.metadata["walk_forward_native_final_execution"]["resolved"] == "rust_pct_equity_transition_v1"


def test_pct_equity_auto_preserves_legacy_wfo_route() -> None:
    result = _wfo_result(native_policy="auto", target_runtime="rust", mode="mode_1_decay")
    prepared = result.metadata["walk_forward"]["native_prepared_wfo"]
    assert prepared["resolved_policy"] == "fallback"
    assert "opt-in" in str(prepared["reason"])
    assert "walk_forward_native_final_execution" not in result.metadata


def _prepared_scalar_fixture():
    """One small typed request pair for cold/score boundary parity."""

    bars = 12
    index = pd.date_range("2024-01-01", periods=bars, freq="1h", tz="UTC")
    close = np.ascontiguousarray(
        (100.0 + np.arange(bars, dtype=np.float64)).reshape(-1, 1), dtype=np.float64
    )
    cache = NativeExecutionPreparationCache(CachePolicy(max_bytes=2_000_000, max_entries=8))
    market = cache.prepare_market(
        timestamps_ns=np.ascontiguousarray(index.asi8, dtype=np.int64),
        opens=close,
        highs=np.ascontiguousarray(close + 1.0),
        lows=np.ascontiguousarray(close - 1.0),
        closes=close,
        volumes=np.ones_like(close),
        funding=np.zeros_like(close),
        funding_mask=np.zeros(bars, dtype=np.bool_),
        symbols=["BTC"],
    )
    template = cache.prepare_template(
        market,
        contract_sizes=np.ones(1, dtype=np.float64),
        leverages=np.full(1, 3.0, dtype=np.float64),
        fee_rates=np.full(1, 0.0002, dtype=np.float64),
        initial_capital=20_000.0,
        maintenance_ratio=0.005,
        slippage_rate=0.0001,
        use_funding=False,
    )
    first = np.zeros((bars, 1), dtype=np.float64)
    first[1:6] = 1.0
    second = np.zeros((bars, 1), dtype=np.float64)
    second[2:9] = -0.5
    return cache, (
        cache.direct_target_request(template, targets=first, target_kind="units", output_profile=0),
        cache.direct_target_request(template, targets=second, target_kind="units", output_profile=0),
    )


def test_prepared_score_columns_match_cold_rows_without_python_row_materialization() -> None:
    cache, requests = _prepared_scalar_fixture()
    runtime = NativePreparedEvaluationRuntimeV1(cache, workers=2)
    try:
        bindings = tuple(
            runtime.bind_request(
                request,
                workload=NativePreparedWorkloadV1.TARGET_UNITS,
                candidate_id=11 + scenario_id,
                fold_id=scenario_id,
                scenario_id=scenario_id,
            )
            for scenario_id, request in enumerate(requests)
        )
        cold = runtime.evaluate(bindings)
        score = runtime.evaluate_score_columns(bindings)
        by_scenario = score.index_by_scenario()
        assert score.metadata["adapter"] == "scalar_columns_v1"
        assert score.metadata["python_row_objects"] == 0
        assert score.metadata["python_dict_materialized"] is False
        assert score.errors == cold.errors == ()
        for row in cold.rows:
            index = by_scenario[row.scenario_id]
            assert int(score.candidate_id[index]) == row.candidate_id
            assert int(score.fold_id[index]) == row.fold_id
            assert int(score.status[index]) == 0
            assert float(score.total_return[index]) == pytest.approx(row.total_return, abs=1e-12)
            assert float(score.sharpe[index]) == pytest.approx(row.sharpe, abs=1e-12)
            assert float(score.max_drawdown[index]) == pytest.approx(row.max_drawdown, abs=1e-12)
            assert float(score.profit_factor[index]) == pytest.approx(row.profit_factor, abs=1e-12)
            assert int(score.report_trade_count[index]) == row.report_trade_count
    finally:
        runtime.close()


def test_prepared_pct_equity_wfo_worker_count_has_no_effect_on_scores_or_account() -> None:
    def run(workers: int):
        data = _market()
        endpoint = QuantBTEndpoint.walk_forward(
            strategy_class=_wfo_strategy,
            split_mode="2020-07-01",
            split_frequency="quarterly",
            window_mode="rolling",
            train_window="90D",
            target_mode="pct_equity",
            optimization_mode="mode_1_decay",
            optimization_config={
                "candidate_selection_metric": "robust_decay",
                "top_is_fraction": 1.0,
                "scoring_trading_days": 365,
                "native_prepared_wfo": "require",
                "native_prepared_wfo_workers": workers,
            },
            optuna_trials=2,
            random_seed=71,
            target_runtime="rust",
            **_pct_kwargs(),
        )
        return endpoint.backtest(data=data, param_ranges={"direction": [-1.0, 1.0]})

    serial = run(1)
    parallel = run(2)
    _assert_endpoint_parity(serial, parallel)
    serial_wf = serial.metadata["walk_forward"]
    parallel_wf = parallel.metadata["walk_forward"]
    assert serial_wf["best_trial"]["params"] == parallel_wf["best_trial"]["params"]
    np.testing.assert_allclose(
        serial_wf["trial_table"]["objective"].to_numpy(dtype=float),
        parallel_wf["trial_table"]["objective"].to_numpy(dtype=float),
        rtol=0.0,
        atol=1e-12,
    )
    assert serial_wf["native_prepared_wfo"]["score_adapter"] == "scalar_columns_v1"
    assert parallel_wf["native_prepared_wfo"]["score_python_row_objects"] == 0
