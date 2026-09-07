"""PERF-09 reactive preparation, callback-binding, and parity closure."""

from __future__ import annotations

import importlib.util
from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from quantbt import (
    CandidateWakePlansV1,
    ExecutionConfig,
    NativeEventScoreRequirements,
    OrderSide,
    QuantBTEndpoint,
    StrategyContextRequirements,
    WakePlanV1,
)
from quantbt.backends import ReactiveWfoRuntimeConfigV1
from quantbt.strategies import STRICT_CAUSAL_CACHE_CONTRACT_V1, ReactiveWfoTaskV1
from quantbt.walkforward import WalkForwardConfig


pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("_quantbt_native") is None,
    reason="quantbt-native extension is not installed in this environment",
)


_REQUIREMENTS = StrategyContextRequirements(
    market=("open", "high", "low", "close"),
    account=("equity", "available_equity", "initial_margin", "maintenance_margin", "liquidated"),
    positions=("qty",),
    fills="new_only",
    events="new_only",
    active_orders="none",
    context_mode="numeric",
)


def _frame(*, bars: int = 210) -> pd.DataFrame:
    index = pd.date_range("2024-01-01", periods=bars, freq="1D", tz="UTC")
    phase = np.arange(bars, dtype=np.float64)
    close = 100.0 + phase * 0.08 + 1.2 * np.sin(phase / 7.0)
    return pd.DataFrame(
        {
            "open": np.r_[close[0], close[:-1]],
            "high": close + 0.75,
            "low": close - 0.75,
            "close": close,
            "volume": np.full(bars, 1_000.0),
            "funding_rate": np.where((phase.astype(np.int64) % 8) == 0, 0.0001, 0.0),
        },
        index=index,
    )


def _endpoint(frame: pd.DataFrame) -> QuantBTEndpoint:
    return QuantBTEndpoint.native_event_strategy(
        initial_capital=20_000.0,
        leverage=3.0,
        maintenance_ratio=0.005,
        fee_rate=0.0004,
        use_funding=True,
        funding_rate=frame["funding_rate"],
        report_level="audit",
        native_backend="rust",
        reactive_kernel_mode="single_pass",
        reactive_runtime="numeric_every_bar_v1",
        execution_contract="event_lifecycle_v3_next_open",
        execution=ExecutionConfig(slippage_bps=1.0),
    )


class _TaskStrategy:
    quantbt_reactive_numeric_v1 = True
    quantbt_requirements = _REQUIREMENTS

    def __init__(self, *, task, direction: float) -> None:
        self.task = task
        self.direction = float(direction)
        self.calls: list[int] = []

    def reset(self, *, seed: int, task) -> None:
        assert int(seed) == int(task.seed)
        self.task = task

    def on_bar_close(self, context, out) -> None:
        bar = int(context.bar_index)
        self.calls.append(bar)
        exit_bar = min(int(self.task.end_bar) - 2, int(self.task.start_bar) + 3)
        if bar == int(self.task.start_bar):
            out.market(0, OrderSide.BUY if self.direction > 0.0 else OrderSide.SELL, 1.0)
        elif bar == exit_bar:
            out.market(
                0,
                OrderSide.SELL if self.direction > 0.0 else OrderSide.BUY,
                1.0,
                reduce_only=True,
            )

    def quantbt_state_fingerprint(self):
        return (self.task.fold_id, self.task.start_bar, self.task.end_bar, tuple(self.calls))


class _PreparedFactory:
    causal_cache_contract = STRICT_CAUSAL_CACHE_CONTRACT_V1

    def build_strategy(self, *, params, task):
        return _TaskStrategy(task=task, direction=float(params["direction"]))

    def close(self) -> None:
        return None


class _Factory:
    def prepare_reactive_wfo(self, *, data, folds, static_config):
        assert len(data) and len(folds)
        assert static_config["schema"] == "quantbt-reactive-wfo-static-v1"
        return _PreparedFactory()


def _config(*, mode: str, schedule: str) -> WalkForwardConfig:
    candidate_metric = {
        "mode_1_decay": "robust_decay",
        "mode_3_flat_minima": "is_plateau_robust",
        "mode_4_is_only_robust": "is_only_robust",
        "mode_5_full_robust": "full_robust",
    }[mode]
    values: dict[str, object] = {
        "split_mode": "2024-03-01",
        "split_frequency": "monthly",
        "window_mode": "rolling",
        "train_window": "45D",
        "min_train_bars": 20,
        "min_test_bars": 8,
        "target_mode": "signal_notional",
        "optimization_mode": mode,
        "optimization_schedule": schedule,
        "fold_boundary_position_policy": "reset_flat",
        "fold_account_policy": "reset_flat",
        "optuna_trials": 2,
        "optuna_early_stopping": None,
        "random_seed": 31,
        "candidate_selection_metric": candidate_metric,
        "top_is_fraction": 1.0,
        "flat_eps": 1.0,
        "flat_min_samples": 1,
        "is_subperiods": 3 if mode == "mode_4_is_only_robust" else 1,
        "scoring_trading_days": 365,
        "min_trades_per_year": None,
        "trade_penalty_factor": None,
    }
    if schedule == "per_fold_causal" and mode == "mode_1_decay":
        values.update(
            {
                "inner_split_frequency": "single",
                "inner_window_mode": "rolling",
                "inner_train_window": "21D",
                "inner_min_folds": 1,
            }
        )
    return WalkForwardConfig(**values)


def _run(
    frame: pd.DataFrame,
    *,
    mode: str,
    schedule: str,
    prepared: bool,
):
    endpoint = _endpoint(frame)
    runtime = endpoint.prepare_reactive_walk_forward(
        data=frame,
        strategy_factory=_Factory(),
        walkforward_config=_config(mode=mode, schedule=schedule),
        symbols=["BTC"],
        runtime_config=ReactiveWfoRuntimeConfigV1(
            preparation_policy="prepared" if prepared else "compatibility",
        ),
    )
    return runtime.backtest(param_ranges={"direction": [-1.0, 1.0]})


def _assert_segmented_parity(left, right) -> None:
    assert left.params == right.params
    assert left.params_by_fold == right.params_by_fold
    assert left.best_trial == right.best_trial
    pd.testing.assert_frame_equal(left.trial_table, right.trial_table, check_exact=True)
    pd.testing.assert_frame_equal(left.candidate_table, right.candidate_table, check_exact=True)
    pd.testing.assert_frame_equal(left.fold_table, right.fold_table, check_exact=True)
    assert len(left.fold_results) == len(right.fold_results)
    for left_fold, right_fold in zip(left.fold_results, right.fold_results, strict=True):
        assert left_fold.task == right_fold.task
        assert left_fold.strategy_state_fingerprint == right_fold.strategy_state_fingerprint
        for field in ("equity", "fees", "funding"):
            np.testing.assert_allclose(
                getattr(left_fold.result, field).to_numpy(dtype=np.float64),
                getattr(right_fold.result, field).to_numpy(dtype=np.float64),
                rtol=0.0,
                atol=1.0e-10,
            )
        np.testing.assert_allclose(
            left_fold.result.positions.to_numpy(dtype=np.float64),
            right_fold.result.positions.to_numpy(dtype=np.float64),
            rtol=0.0,
            atol=1.0e-10,
        )


@pytest.mark.parametrize(
    ("mode", "schedule"),
    (
        ("mode_1_decay", "per_fold_causal"),
        ("mode_3_flat_minima", "global"),
        ("mode_4_is_only_robust", "per_fold_causal"),
        ("mode_5_full_robust", "global"),
    ),
)
def test_perf09_reactive_wfo_preparation_preserves_mode_and_schedule_results(mode: str, schedule: str):
    frame = _frame()
    baseline = _run(frame, mode=mode, schedule=schedule, prepared=False)
    optimized = _run(frame, mode=mode, schedule=schedule, prepared=True)

    _assert_segmented_parity(optimized, baseline)
    prepared_meta = optimized.metadata["wfo_preparation"]
    assert prepared_meta["enabled"] is True
    assert prepared_meta["policy"] == "prepared"
    assert optimized.metadata["runtime"]["preparation_policy"] == "prepared"
    assert prepared_meta["window_registry"]["window_lookup_hits"] > 0
    adapter_meta = optimized.metadata["prepared_strategy"]
    assert adapter_meta["prepared_task_window_hits"] > 0
    baseline_adapter = baseline.metadata["prepared_strategy"]
    baseline_meta = baseline.metadata["wfo_preparation"]
    assert baseline_meta["enabled"] is False
    assert baseline_meta["policy"] == "compatibility"
    assert baseline.metadata["runtime"]["preparation_policy"] == "compatibility"
    assert baseline_adapter["prepared_task_window_fallbacks"] > 0
    if mode == "mode_4_is_only_robust":
        assert prepared_meta["window_registry"]["shard_lookup_hits"] > 0
    if mode == "mode_1_decay" and schedule == "per_fold_causal":
        assert prepared_meta["inner_fold_lookup_hits"] > 0

    fold_table = optimized.fold_table.set_index("fold_id")
    for segment in optimized.fold_results:
        report = segment.result.full_report()
        row = fold_table.loc[int(segment.fold_id)]
        np.testing.assert_allclose(row["oos_final_equity"], report["final_equity"], rtol=0.0, atol=1.0e-10)
        np.testing.assert_allclose(row["oos_sharpe"], report["sharpe"], rtol=0.0, atol=1.0e-10)
        np.testing.assert_allclose(
            row["oos_max_drawdown_pct"], report["max_drawdown_pct"], rtol=0.0, atol=1.0e-10
        )
        assert int(row["oos_num_trades"]) == int(report["num_trades"])


def test_perf09_reactive_wfo_preparation_policy_is_validated():
    with pytest.raises(ValueError, match="preparation_policy"):
        ReactiveWfoRuntimeConfigV1(preparation_policy="unknown")


class _MutatingBatchStrategy:
    quantbt_reactive_candidate_batch_v1 = True
    quantbt_requirements = _REQUIREMENTS

    def __init__(self, *, pinned: bool) -> None:
        self.quantbt_reactive_callback_binding_v1 = "run_stable" if pinned else "dynamic"
        self.first_calls = 0
        self.replacement_calls = 0
        self.on_wake_batch = self._first

    def _plans(self, context_batch, *, next_bar: int | None) -> CandidateWakePlansV1:
        plans = {
            int(candidate): WakePlanV1(next_bar=next_bar)
            for candidate in context_batch.candidate_ids.tolist()
        }
        return CandidateWakePlansV1(plans)

    def _first(self, context_batch, _out_batch) -> CandidateWakePlansV1:
        self.first_calls += 1
        self.on_wake_batch = self._replacement
        return self._plans(context_batch, next_bar=1 if int(context_batch.bar_index) == 0 else None)

    def _replacement(self, context_batch, _out_batch) -> CandidateWakePlansV1:
        self.replacement_calls += 1
        return self._plans(context_batch, next_bar=None)


def test_perf09_r3b_callback_binding_is_dynamic_by_default_and_pinned_only_on_opt_in():
    frame = _frame(bars=20)
    prepared = _endpoint(frame).prepare_native_event_strategy(data=frame, symbols=["BTC"])

    dynamic = _MutatingBatchStrategy(pinned=False)
    dynamic_runner, _ = prepared.prepare_reactive_candidate_batch_score(
        dynamic,
        candidate_count=2,
        trading_days=365,
    )
    dynamic_payload = dynamic_runner.run_window(dynamic, start_bar=0, end_bar=4)

    pinned = _MutatingBatchStrategy(pinned=True)
    pinned_runner, _ = prepared.prepare_reactive_candidate_batch_score(
        pinned,
        candidate_count=2,
        trading_days=365,
    )
    pinned_payload = pinned_runner.run_window(pinned, start_bar=0, end_bar=4)

    assert dynamic.first_calls == 1
    assert dynamic.replacement_calls == 1
    assert pinned.first_calls == 2
    assert pinned.replacement_calls == 0
    dynamic_output = dynamic_payload["candidate_outputs"][0]
    pinned_output = pinned_payload["candidate_outputs"][0]
    assert dynamic_output["callback_binding_mode"] == "dynamic_compatibility_v1"
    assert dynamic_output["callback_dynamic_lookup_count"] == 2
    assert dynamic_output["callback_plan_compile_lookup_count"] == 0
    assert pinned_output["callback_binding_mode"] == "run_stable_pinned_v1"
    assert pinned_output["callback_dynamic_lookup_count"] == 0
    assert pinned_output["callback_plan_compile_lookup_count"] == 1


def test_perf09_prepared_market_binding_is_identity_scoped_and_score_parity_safe():
    frame = _frame(bars=24)
    prepared = _endpoint(frame).prepare_native_event_strategy(data=frame, symbols=["BTC"])
    task = ReactiveWfoTaskV1(
        run_id="perf09-binding",
        candidate_id="candidate",
        fold_id=0,
        stage="is",
        start_bar=0,
        end_bar=len(frame),
        history_start_bar=0,
        history_end_bar=len(frame) - 1,
        train_start=frame.index[0],
        train_end=frame.index[-1],
        test_start=frame.index[0],
        test_end=frame.index[-1],
        seed=17,
        market_signature=str(prepared.metadata["market_signature"]),
    )
    scalar_requirements = NativeEventScoreRequirements.scalar_score_contract()
    bound_score = prepared.score(
        _TaskStrategy(task=task, direction=1.0),
        score_requirements=scalar_requirements,
    )
    unbound = replace(prepared, reactive_market_binding=None)
    unbound_score = unbound.score(
        _TaskStrategy(task=task, direction=1.0),
        score_requirements=scalar_requirements,
    )

    assert bound_score.metrics == unbound_score.metrics
    assert bound_score.final_equity == unbound_score.final_equity
    assert bound_score.fill_count == unbound_score.fill_count

    binding = prepared.reactive_market_binding
    assert prepared.backend._trusted_reactive_market_cache_key(
        binding,
        idx=prepared.idx,
        symbol_list=prepared.symbols,
        market_arrays=prepared.market_arrays,
        opens_arr=prepared.opens_arr,
        volumes_arr=prepared.volumes_arr,
    ) == binding.cache_key

    foreign = _endpoint(frame).prepare_native_event_strategy(data=frame, symbols=["BTC"])
    assert foreign.backend._trusted_reactive_market_cache_key(
        binding,
        idx=foreign.idx,
        symbol_list=foreign.symbols,
        market_arrays=foreign.market_arrays,
        opens_arr=foreign.opens_arr,
        volumes_arr=foreign.volumes_arr,
    ) is None
