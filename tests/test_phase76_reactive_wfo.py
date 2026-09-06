"""Phase 76 reactive WFO correctness and lifecycle certification.

The fixture deliberately uses a Python callback strategy rather than a target
series.  It verifies that W3 keeps the original prepared-market clock while
each candidate/fold starts from a fresh account, so dynamic lifecycle state is
never fabricated as a stitched signal.
"""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import subprocess
import sys
from threading import Thread
import time

import numpy as np
import pandas as pd
import pytest

from quantbt import (
    CandidateWakePlansV1,
    ExecutionConfig,
    OrderSide,
    QuantBTEndpoint,
    StrategyContextRequirements,
    WakePlanV1,
)
from quantbt.backends.native_event import NativeEventScoreRequirements
from quantbt.backends.reactive_wfo import (
    _ReactiveSelectionEngine,
    ReactivePreparedWfoRuntimeV1,
    ReactiveWalkForwardUnsupported,
    ReactiveWfoRuntimeConfigV1,
)
from quantbt.backends.reactive_wfo_workers import (
    ForkReactiveWfoWorkerV1,
    fork_reactive_wfo_worker_safe,
    fork_reactive_wfo_worker_supported,
)
from quantbt.core.runtime_governance import (
    ParallelismPlanV1,
    RuntimeBudgetError,
    RuntimeBudgetV1,
    RuntimeCanceledError,
    RuntimeCancellationV1,
)
from quantbt.strategies.reactive_wfo import (
    STRICT_CAUSAL_CACHE_CONTRACT_V1,
    prepare_reactive_wfo_strategy,
)
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
    active_orders="snapshot",
    context_mode="numeric",
)


def _bars(*, periods: int = 180) -> pd.DataFrame:
    index = pd.date_range("2024-01-01", periods=periods, freq="1D", tz="UTC")
    phase = np.arange(periods, dtype=np.float64)
    close = 100.0 + 0.12 * phase + 1.4 * np.sin(phase / 8.0)
    return pd.DataFrame(
        {
            "open": np.r_[close[0], close[:-1]],
            "high": close + 0.8,
            "low": close - 0.8,
            "close": close,
            "volume": np.full(periods, 1_000.0),
            "funding_rate": np.where((phase.astype(np.int64) % 7) == 0, 0.0001, 0.0),
        },
        index=index,
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
        if bar == int(self.task.start_bar):
            side = OrderSide.BUY if self.direction > 0.0 else OrderSide.SELL
            out.market(0, side, 1.0)
        elif bar == min(int(self.task.end_bar) - 2, int(self.task.start_bar) + 4):
            side = OrderSide.SELL if self.direction > 0.0 else OrderSide.BUY
            out.market(0, side, 1.0, reduce_only=True)

    def quantbt_state_fingerprint(self):
        return (self.task.fold_id, self.task.start_bar, self.task.end_bar, tuple(self.calls))


class _PreparedFactory:
    causal_cache_contract = STRICT_CAUSAL_CACHE_CONTRACT_V1

    def __init__(self, index: pd.DatetimeIndex) -> None:
        self.index = pd.DatetimeIndex(index)
        self.closed = False

    def build_strategy(self, *, params, task):
        assert not self.closed
        return _TaskStrategy(task=task, direction=float(params["direction"]))

    def close(self) -> None:
        self.closed = True


class _CandidateBatchStrategy:
    """R3B equivalent of ``_TaskStrategy`` with sparse scheduled wakes."""

    quantbt_reactive_candidate_batch_v1 = True
    quantbt_requirements = _REQUIREMENTS

    def __init__(self, *, params_matrix, tasks) -> None:
        self.params_matrix = tuple(params_matrix)
        self.tasks = tuple(tasks)
        self.callback_rows: list[tuple[int, tuple[int, ...]]] = []

    def on_wake_batch(self, context_batch, out_batch) -> CandidateWakePlansV1:
        candidate_ids = tuple(int(value) for value in context_batch.candidate_ids.tolist())
        self.callback_rows.append((int(context_batch.bar_index), candidate_ids))
        plans = {}
        for candidate_id in candidate_ids:
            task = self.tasks[candidate_id]
            direction = float(self.params_matrix[candidate_id]["direction"])
            bar = int(context_batch.bar_index)
            writer = out_batch.writer(candidate_id)
            exit_bar = min(int(task.end_bar) - 2, int(task.start_bar) + 4)
            if bar == int(task.start_bar):
                writer.market(0, OrderSide.BUY if direction > 0.0 else OrderSide.SELL, 1.0)
                plans[candidate_id] = WakePlanV1(next_bar=exit_bar)
            elif bar == exit_bar:
                writer.market(
                    0,
                    OrderSide.SELL if direction > 0.0 else OrderSide.BUY,
                    1.0,
                    reduce_only=True,
                )
                plans[candidate_id] = WakePlanV1()
            else:  # Defensive only: native scheduling should not wake here.
                plans[candidate_id] = WakePlanV1()
        return CandidateWakePlansV1(plans)


class _CandidateBatchPreparedFactory(_PreparedFactory):
    def build_candidate_batch(self, *, params_matrix, tasks):
        assert not self.closed
        return _CandidateBatchStrategy(params_matrix=params_matrix, tasks=tasks)


class _ReactiveFactory:
    def prepare_reactive_wfo(self, *, data, folds, static_config):
        assert static_config["schema"] == "quantbt-reactive-wfo-static-v1"
        assert len(data) > 0 and len(folds) > 0
        return _PreparedFactory(data.index)


class _CandidateBatchReactiveFactory:
    def prepare_reactive_wfo(self, *, data, folds, static_config):
        assert static_config["schema"] == "quantbt-reactive-wfo-static-v1"
        return _CandidateBatchPreparedFactory(data.index)


class _CandidateBatchLocalErrorStrategy(_CandidateBatchStrategy):
    """Make one candidate omit its wake plan without poisoning its peer."""

    def on_wake_batch(self, context_batch, out_batch) -> CandidateWakePlansV1:
        response = super().on_wake_batch(context_batch, out_batch)
        plans = dict(response.plans)
        for candidate_id in tuple(plans):
            if float(self.params_matrix[candidate_id]["direction"]) < 0.0:
                plans.pop(candidate_id)
        return CandidateWakePlansV1(plans)


class _CandidateBatchLocalErrorPreparedFactory(_CandidateBatchPreparedFactory):
    def build_candidate_batch(self, *, params_matrix, tasks):
        assert not self.closed
        return _CandidateBatchLocalErrorStrategy(params_matrix=params_matrix, tasks=tasks)


class _CandidateBatchLocalErrorReactiveFactory:
    def prepare_reactive_wfo(self, *, data, folds, static_config):
        assert static_config["schema"] == "quantbt-reactive-wfo-static-v1"
        return _CandidateBatchLocalErrorPreparedFactory(data.index)


def _endpoint(data: pd.DataFrame) -> QuantBTEndpoint:
    return QuantBTEndpoint.native_event_strategy(
        initial_capital=20_000.0,
        leverage=3.0,
        maintenance_ratio=0.005,
        fee_rate=0.0004,
        use_funding=True,
        funding_rate=data["funding_rate"],
        report_level="audit",
        native_backend="rust",
        reactive_kernel_mode="single_pass",
        reactive_runtime="numeric_every_bar_v1",
        execution_contract="event_lifecycle_v3_next_open",
        execution=ExecutionConfig(slippage_bps=1.0),
    )


def _config(*, mode: str) -> WalkForwardConfig:
    candidate_metric = {
        "mode_1_decay": "robust_decay",
        "mode_3_flat_minima": "is_plateau_robust",
        "mode_4_is_only_robust": "is_only_robust",
        "mode_5_full_robust": "full_robust",
    }.get(mode, "robust_decay")
    return WalkForwardConfig(
        split_mode="2024-03-01",
        split_frequency="monthly",
        window_mode="rolling",
        train_window="45D",
        min_train_bars=20,
        min_test_bars=8,
        target_mode="signal_notional",
        optimization_mode=mode,
        optimization_schedule="global",
        fold_boundary_position_policy="reset_flat",
        fold_account_policy="reset_flat",
        optuna_trials=0,
        random_seed=17,
        candidate_selection_metric=candidate_metric,
        is_subperiods=2,
        top_is_fraction=1.0,
        flat_eps=1.0,
        flat_min_samples=1,
        scoring_trading_days=365,
        min_trades_per_year=None,
        trade_penalty_factor=None,
    )


@pytest.mark.parametrize("mode", ("mode_1_decay", "mode_4_is_only_robust"))
def test_phase76_reactive_wfo_keeps_absolute_clock_and_reset_flat_score_audit_parity(mode: str):
    data = _bars()
    endpoint = _endpoint(data)
    runtime = endpoint.prepare_reactive_walk_forward(
        data=data,
        strategy_factory=_ReactiveFactory(),
        walkforward_config=_config(mode=mode),
        symbols=["BTC"],
    )
    assert isinstance(runtime, ReactivePreparedWfoRuntimeV1)
    result = runtime.backtest(params={"direction": 1.0})

    assert result.oos_output is None
    assert result.metadata["continuous_equity_available"] is False
    scalar_sessions = result.metadata["runtime"]["scalar_sessions"]
    assert scalar_sessions["session_runs"] == result.metadata["runtime"]["score_calls"]
    assert scalar_sessions["python_callback_calls"] == result.metadata["runtime"]["score_bars"]
    assert scalar_sessions["gil_acquisitions"] == scalar_sessions["session_runs"]
    assert len(result.fold_results) == len(result.folds) > 1
    for fold_result, fold in zip(result.fold_results, result.folds, strict=True):
        assert fold_result.result.equity.index.equals(fold.test_index)
        assert fold_result.task.start_bar > 0
        assert fold_result.task.end_bar - fold_result.task.start_bar == len(fold.test_index)
        assert fold_result.result.metadata["prepared_market_window"]["start_bar"] == fold_result.task.start_bar
        assert fold_result.result.metadata["prepared_market_window"]["bar_coordinate"] == "absolute_prepared_market"
        score = runtime._prepared_runner.score(
            _TaskStrategy(task=fold_result.task, direction=1.0),
            trading_days=365,
            score_requirements=NativeEventScoreRequirements.scalar_score_contract(),
            start_bar=fold_result.task.start_bar,
            end_bar=fold_result.task.end_bar,
        )
        np.testing.assert_allclose(score.final_equity, fold_result.result.equity.iloc[-1], rtol=0.0, atol=1e-10)
        np.testing.assert_allclose(
            score.metrics["total_fee"],
            fold_result.result.fees.sum(),
            rtol=0.0,
            atol=1e-10,
        )
    if mode == "mode_4_is_only_robust":
        assert result.best_trial["selection_metadata"]["oos_seen_by_optuna"] is False
        assert result.best_trial["selection_metadata"]["reactive_task_windows"] == "absolute_prepared_market_fresh_account"
    runtime.close()


def test_phase76_reactive_wfo_rejects_sbb_and_non_reset_account_policy_before_execution():
    data = _bars()
    endpoint = _endpoint(data)
    with pytest.raises(ReactiveWalkForwardUnsupported, match="mode_2_sbb"):
        endpoint.prepare_reactive_walk_forward(
            data=data,
            strategy_factory=_ReactiveFactory(),
            walkforward_config=_config(mode="mode_2_sbb"),
            symbols=["BTC"],
        )
    with pytest.raises(ReactiveWalkForwardUnsupported, match="reset_flat"):
        endpoint.prepare_reactive_walk_forward(
            data=data,
            strategy_factory=_ReactiveFactory(),
            walkforward_config=WalkForwardConfig(
                **{
                    **_config(mode="mode_1_decay").__dict__,
                    "fold_boundary_position_policy": "carry_position",
                    "fold_account_policy": "carry_position",
                }
            ),
            symbols=["BTC"],
        )


@pytest.mark.parametrize(
    ("mode", "schedule"),
    (
        ("mode_1_decay", "per_fold_decay"),
        ("mode_4_is_only_robust", "per_fold_causal"),
    ),
)
def test_phase76_sequential_reuses_certified_per_fold_selection_schedules(mode: str, schedule: str):
    """W3 may change the scorer, never the established schedule semantics."""

    data = _bars()
    config = WalkForwardConfig(
        **{
            **_config(mode=mode).__dict__,
            "optimization_schedule": schedule,
            "optuna_trials": 2,
            "optuna_early_stopping": None,
        }
    )
    runtime = _endpoint(data).prepare_reactive_walk_forward(
        data=data,
        strategy_factory=_ReactiveFactory(),
        walkforward_config=config,
        symbols=["BTC"],
    )
    try:
        result = runtime.backtest(param_ranges={"direction": [-1.0, 1.0]})
    finally:
        runtime.close()

    fold_ids = {int(fold.fold_id) for fold in result.folds}
    assert set(result.params_by_fold) == fold_ids
    selection = result.metadata["fold_selection_table"]
    assert set(selection["fold_id"].astype(int)) == fold_ids
    assert set(selection["outer_oos_used_for_selection"].astype(bool)) == {schedule == "per_fold_decay"}
    if mode == "mode_4_is_only_robust":
        assert result.best_trial["selection_metadata"]["outer_oos_used_for_selection"] is False


@pytest.mark.skipif(
    not fork_reactive_wfo_worker_safe(),
    reason="Phase 76 direct process-worker check requires a single-thread POSIX parent",
)
def test_phase76_process_worker_matches_inprocess_and_tears_down_without_market_ipc():
    data = _bars()
    config = _config(mode="mode_1_decay")
    baseline = _endpoint(data).prepare_reactive_walk_forward(
        data=data,
        strategy_factory=_ReactiveFactory(),
        walkforward_config=config,
        symbols=["BTC"],
    )
    observed = _endpoint(data).prepare_reactive_walk_forward(
        data=data,
        strategy_factory=_ReactiveFactory(),
        walkforward_config=config,
        runtime_config=ReactiveWfoRuntimeConfigV1(worker_mode="process"),
        symbols=["BTC"],
    )
    reference_result = baseline.backtest(params={"direction": -1.0})
    process_result = observed.backtest(params={"direction": -1.0})

    assert reference_result.params == process_result.params
    assert len(reference_result.fold_results) == len(process_result.fold_results)
    for reference, actual in zip(reference_result.fold_results, process_result.fold_results, strict=True):
        pd.testing.assert_series_equal(
            reference.result.equity,
            actual.result.equity,
            check_exact=False,
            atol=1e-10,
        )
        pd.testing.assert_series_equal(
            reference.result.fees,
            actual.result.fees,
            check_exact=False,
            atol=1e-12,
        )
        assert reference.strategy_state_fingerprint == actual.strategy_state_fingerprint
    worker = process_result.metadata["runtime"]["worker"]
    assert worker["worker_transport"] == "fork_copy_on_write_v1"
    assert worker["worker_pool_creations"] == 1
    assert worker["worker_market_ipc_bytes_per_task"] == 0
    assert worker["worker_scalar_sessions"]["session_creations"] == 1
    assert worker["worker_scalar_sessions"]["session_runs"] > 1
    assert worker["worker_scalar_sessions"]["python_callback_calls"] == process_result.metadata["runtime"]["score_bars"]
    assert worker["worker_scalar_sessions"]["gil_acquisitions"] == worker["worker_scalar_sessions"]["session_runs"]
    assert worker["closed"] is True
    assert process_result.metadata["runtime"]["worker_mode_resolved"] == "process"
    baseline.close()
    observed.close()


@pytest.mark.parametrize(
    "mode",
    (
        "mode_1_decay",
        "mode_3_flat_minima",
        "mode_4_is_only_robust",
        "mode_5_full_robust",
    ),
)
def test_phase76_fixed_candidate_batch_matches_scalar_selection_rows(mode: str):
    """R3B changes callback coalescing, never WFO metric/selector mathematics."""

    data = _bars()
    config = _config(mode=mode)
    candidate_matrix = [{"direction": -1.0}, {"direction": 1.0}]
    batched = _endpoint(data).prepare_reactive_walk_forward(
        data=data,
        strategy_factory=_CandidateBatchReactiveFactory(),
        walkforward_config=config,
        runtime_config=ReactiveWfoRuntimeConfigV1(
            optimizer_schedule="throughput_batch_v1",
            candidate_batch_size=2,
        ),
        symbols=["BTC"],
    )
    try:
        observed = batched.backtest(
            candidate_matrix=candidate_matrix,
            param_ranges={"direction": [-1.0, 1.0]},
        )
        metadata = observed.metadata["candidate_batch"]
        assert observed.metadata["sampling_contract"] == "fixed_candidate_matrix_r3b_v1"
        assert metadata["sequential_equivalent"] is False
        assert metadata["market_copies_per_candidate"] == 0
        assert metadata["market_ipc_bytes_per_candidate"] == 0
        assert metadata["candidate_matrix_size"] == 2
        assert metadata["batch_size"] == 2
        assert metadata["batches"] > 0
        assert metadata["callbacks"] > 0
        assert metadata["runner_creations"] == 1
        assert observed.metadata["runtime"]["score_calls"] > 0

        for candidate in candidate_matrix:
            scalar = _endpoint(data).prepare_reactive_walk_forward(
                data=data,
                strategy_factory=_ReactiveFactory(),
                walkforward_config=config,
                symbols=["BTC"],
            )
            try:
                reference = scalar.backtest(params=candidate)
            finally:
                scalar.close()
            is_rows = observed.trial_table[
                observed.trial_table["params"].apply(lambda value: value == candidate)
            ]
            assert len(is_rows) >= 1
            is_row = is_rows.iloc[0]
            assert is_row["selection_metadata"]["stage"] == "is_search"
            assert is_row["mean_oos_sharpe"] == 0.0

            if mode in {"mode_1_decay", "mode_3_flat_minima"}:
                # R3B first ranks candidates on the same pure-IS metric as
                # ordinary Optuna. OOS is only evaluated for top IS rows.
                matching = observed.candidate_table[
                    observed.candidate_table["params"].apply(lambda value: value == candidate)
                ]
                assert len(matching) == 1
                row = matching.iloc[0]
            else:
                # Modes 4/5 are IS-only selection protocols, so the native
                # IS row itself is the complete scalar reference.
                row = is_row
            assert row["params"] == candidate
            np.testing.assert_allclose(row["objective"], reference.best_trial["objective"], rtol=0.0, atol=1e-10)
            np.testing.assert_allclose(
                row["mean_is_sharpe"], reference.best_trial["mean_is_sharpe"], rtol=0.0, atol=1e-10
            )
            np.testing.assert_allclose(
                row["mean_oos_sharpe"], reference.best_trial["mean_oos_sharpe"], rtol=0.0, atol=1e-10
            )
        if mode == "mode_4_is_only_robust":
            assert observed.best_trial["selection_metadata"]["oos_used_for_selection"] is False
    finally:
        batched.close()


def test_phase76_reactive_batch_schedule_is_explicit_and_bounded():
    with pytest.raises(ValueError, match="max_inflight_tasks must be 1"):
        ReactiveWfoRuntimeConfigV1(
            optimizer_schedule="throughput_batch_v1",
            candidate_batch_size=2,
            max_inflight_tasks=2,
        )
    data = _bars()
    runtime = _endpoint(data).prepare_reactive_walk_forward(
        data=data,
        strategy_factory=_CandidateBatchReactiveFactory(),
        walkforward_config=_config(mode="mode_1_decay"),
        runtime_config=ReactiveWfoRuntimeConfigV1(
            optimizer_schedule="throughput_batch_v1",
            candidate_batch_size=2,
        ),
        symbols=["BTC"],
    )
    try:
        with pytest.raises(ValueError, match="requires walkforward_config.optuna_trials > 0"):
            runtime.backtest(param_ranges={"direction": [-1.0, 1.0]})
        with pytest.raises(ValueError, match="requires param_ranges"):
            runtime.backtest(params={"direction": 1.0})
    finally:
        runtime.close()


def _adaptive_config(*, mode: str = "mode_1_decay", trials: int = 6) -> WalkForwardConfig:
    return WalkForwardConfig(
        **{
            **_config(mode=mode).__dict__,
            "optuna_trials": int(trials),
            "optuna_early_stopping": None,
        }
    )


def test_phase76_adaptive_r3b_is_deterministic_and_quality_gated():
    data = _bars()
    ranges = {"direction": [-2.0, -1.0, 1.0, 2.0]}

    def run(runtime_config):
        runtime = _endpoint(data).prepare_reactive_walk_forward(
            data=data,
            strategy_factory=_CandidateBatchReactiveFactory(),
            walkforward_config=_adaptive_config(trials=6),
            runtime_config=runtime_config,
            symbols=["BTC"],
        )
        try:
            return runtime.backtest(param_ranges=ranges)
        finally:
            runtime.close()

    first = run(
        ReactiveWfoRuntimeConfigV1(
            optimizer_schedule="throughput_batch_v1",
            candidate_batch_size=2,
        )
    )
    second = run(
        ReactiveWfoRuntimeConfigV1(
            optimizer_schedule="throughput_batch_v1",
            candidate_batch_size=2,
        )
    )
    assert first.metadata["sampling_contract"] == "adaptive_optuna_batch_r3b_v1"
    assert first.metadata["candidate_batch"]["sequential_equivalent"] is False
    assert first.metadata["candidate_batch"]["batch_size"] == 2
    assert first.metadata["candidate_batch"]["asked_trials"] == 6
    pd.testing.assert_frame_equal(first.trial_table, second.trial_table, check_exact=True)
    pd.testing.assert_frame_equal(first.candidate_table, second.candidate_table, check_exact=True)
    assert first.best_trial == second.best_trial

    verified = run(
        ReactiveWfoRuntimeConfigV1(
            optimizer_schedule="throughput_batch_v1",
            candidate_batch_size=2,
            reference_best_objective=float(first.best_trial["objective"]),
            max_quality_regret=0.0,
        )
    )
    assert verified.metadata["candidate_batch"]["quality_reference_status"] == "evaluated_against_explicit_reference"
    assert verified.metadata["candidate_batch"]["quality_regret_vs_reference"] == 0.0

    with pytest.raises(ReactiveWalkForwardUnsupported, match="quality regret gate"):
        run(
            ReactiveWfoRuntimeConfigV1(
                optimizer_schedule="throughput_batch_v1",
                candidate_batch_size=2,
                reference_best_objective=float(first.best_trial["objective"]) + 1.0,
                max_quality_regret=0.0,
            )
        )


def test_phase76_batch_candidate_local_error_is_pruned_without_poisoning_peer():
    data = _bars()
    runtime = _endpoint(data).prepare_reactive_walk_forward(
        data=data,
        strategy_factory=_CandidateBatchLocalErrorReactiveFactory(),
        walkforward_config=_config(mode="mode_1_decay"),
        runtime_config=ReactiveWfoRuntimeConfigV1(
            optimizer_schedule="throughput_batch_v1",
            candidate_batch_size=2,
        ),
        symbols=["BTC"],
    )
    try:
        result = runtime.backtest(
            candidate_matrix=[{"direction": -1.0}, {"direction": 1.0}],
            param_ranges={"direction": [-1.0, 1.0]},
        )
    finally:
        runtime.close()
    failed = result.trial_table[result.trial_table["pruned"]]
    assert len(failed) == 1
    failure = failed.iloc[0]["selection_metadata"]
    assert failure["stage"] == "candidate_local_error"
    assert failure["candidate_error_count"] > 0
    assert failure["candidate_errors"][0]["error_code"] == 2
    assert result.params == {"direction": 1.0}
    assert result.metadata["candidate_batch"]["candidate_failures"] > 0
    assert len(result.fold_results) == len(result.folds)


def test_phase76_batch_rejects_process_transport_and_bad_quality_contract():
    with pytest.raises(ValueError, match="provided together"):
        ReactiveWfoRuntimeConfigV1(reference_best_objective=1.0)
    data = _bars()
    runtime = _endpoint(data).prepare_reactive_walk_forward(
        data=data,
        strategy_factory=_CandidateBatchReactiveFactory(),
        walkforward_config=_adaptive_config(trials=2),
        runtime_config=ReactiveWfoRuntimeConfigV1(
            worker_mode="process",
            optimizer_schedule="throughput_batch_v1",
            candidate_batch_size=2,
        ),
        symbols=["BTC"],
    )
    try:
        with pytest.raises(ReactiveWalkForwardUnsupported, match="worker_mode='process'"):
            runtime.backtest(param_ranges={"direction": [-1.0, 1.0]})
    finally:
        runtime.close()


def test_phase76_budget_rejects_before_reactive_strategy_preparation():
    data = _bars()
    runtime = _endpoint(data).prepare_reactive_walk_forward(
        data=data,
        strategy_factory=_ReactiveFactory(),
        walkforward_config=_config(mode="mode_1_decay"),
        runtime_config=ReactiveWfoRuntimeConfigV1(runtime_budget=RuntimeBudgetV1(max_bars=1)),
        symbols=["BTC"],
    )
    try:
        with pytest.raises(RuntimeBudgetError) as error:
            runtime.backtest(params={"direction": 1.0})
        assert error.value.code == "MAX_BARS"
    finally:
        runtime.close()


def _worker_fixture(*, slow: bool = False):
    """Build the narrow worker primitive without executing a full WFO study."""

    data = _bars()
    endpoint = _endpoint(data)
    runtime = endpoint.prepare_reactive_walk_forward(
        data=data,
        strategy_factory=_ReactiveFactory(),
        walkforward_config=_config(mode="mode_1_decay"),
        symbols=["BTC"],
    )
    engine = _ReactiveSelectionEngine(runtime=runtime, config=runtime.config)
    folds = engine.build_folds(runtime._prepared_runner.idx)
    runtime._adapter = prepare_reactive_wfo_strategy(
        strategy_factory=runtime.strategy_factory,
        data=runtime.data,
        datetime_index=runtime._prepared_runner.idx,
        folds=folds,
        random_seed=runtime.config.random_seed,
        static_config={"schema": "quantbt-reactive-wfo-static-v1"},
    )
    task = runtime.make_task(
        params={"direction": 1.0},
        fold=folds[0],
        evaluation_index=folds[0].test_index,
        stage="worker_lifecycle_test",
    )
    marker = engine._call_strategy_for_indices(
        data=runtime.data,
        params={"direction": 1.0},
        train_index=folds[0].train_index,
        test_index=folds[0].test_index,
        fold=folds[0],
        context="worker_lifecycle_test",
    )
    # The marker above is built through the same WFO task factory; preserve
    # the explicit task assertion so a future context string cannot hide a
    # window-coordinate regression.
    assert marker.task.start_bar == task.start_bar
    worker = ForkReactiveWfoWorkerV1(
        adapter=runtime._adapter,
        prepared_runner=runtime._prepared_runner,
        trading_days=365,
        parallelism_plan=ParallelismPlanV1.resolve(python_processes=1, rust_workers=1),
        max_inflight_tasks=1,
    )
    return runtime, worker, marker


@pytest.mark.skipif(
    not fork_reactive_wfo_worker_safe(),
    reason="Phase 76 direct process-worker check requires a single-thread POSIX parent",
)
def test_phase76_worker_death_recovers_with_new_generation_and_no_market_ipc():
    runtime, worker, marker = _worker_fixture()
    try:
        first = worker.score(marker, canceled=lambda: False)
        assert np.isfinite(first["sharpe"])
        first_pid = worker.metadata()["worker_pid"]
        assert first_pid is not None
        assert worker._process is not None  # Intentional white-box lifecycle gate.
        worker._process.terminate()
        worker._process.join(timeout=1.0)
        second = worker.score(marker, canceled=lambda: False)
        np.testing.assert_allclose(second["sharpe"], first["sharpe"], rtol=0.0, atol=1e-10)
        metadata = worker.metadata()
        assert metadata["worker_pool_creations"] == 2
        assert metadata["worker_generation"] >= 2
        assert metadata["worker_market_ipc_bytes_per_task"] == 0
        assert metadata["worker_memory"]["rss_bytes"] > 0
        worker.close()
        assert worker.metadata()["closed"] is True
        deadline = time.monotonic() + 1.0
        while Path(f"/proc/{first_pid}").exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert not Path(f"/proc/{first_pid}").exists()
    finally:
        worker.close()
        runtime.close()


class _SlowTaskStrategy(_TaskStrategy):
    def on_bar_close(self, context, out) -> None:
        time.sleep(0.25)
        super().on_bar_close(context, out)


class _SlowPreparedFactory(_PreparedFactory):
    def build_strategy(self, *, params, task):
        return _SlowTaskStrategy(task=task, direction=float(params["direction"]))


class _SlowReactiveFactory:
    def prepare_reactive_wfo(self, *, data, folds, static_config):
        return _SlowPreparedFactory(data.index)


@pytest.mark.skipif(
    not fork_reactive_wfo_worker_safe(),
    reason="Phase 76 direct process-worker check requires a single-thread POSIX parent",
)
def test_phase76_worker_cancel_discards_active_child_without_leak():
    data = _bars()
    endpoint = _endpoint(data)
    runtime = endpoint.prepare_reactive_walk_forward(
        data=data,
        strategy_factory=_SlowReactiveFactory(),
        walkforward_config=_config(mode="mode_1_decay"),
        symbols=["BTC"],
    )
    engine = _ReactiveSelectionEngine(runtime=runtime, config=runtime.config)
    folds = engine.build_folds(runtime._prepared_runner.idx)
    runtime._adapter = prepare_reactive_wfo_strategy(
        strategy_factory=runtime.strategy_factory,
        data=runtime.data,
        datetime_index=runtime._prepared_runner.idx,
        folds=folds,
        random_seed=runtime.config.random_seed,
        static_config={"schema": "quantbt-reactive-wfo-static-v1"},
    )
    marker = engine._call_strategy_for_indices(
        data=runtime.data,
        params={"direction": 1.0},
        train_index=folds[0].train_index,
        test_index=folds[0].test_index,
        fold=folds[0],
        context="worker_cancel_test",
    )
    worker = ForkReactiveWfoWorkerV1(
        adapter=runtime._adapter,
        prepared_runner=runtime._prepared_runner,
        trading_days=365,
        parallelism_plan=ParallelismPlanV1.resolve(python_processes=1, rust_workers=1),
        max_inflight_tasks=1,
    )
    cancel = RuntimeCancellationV1()
    outcome: list[BaseException] = []

    # Fork before the test creates the helper thread.  The persistent worker
    # then services the in-flight task safely while cancellation is signalled
    # from another Python thread.
    worker._start()

    def _run() -> None:
        try:
            worker.score(marker, canceled=lambda: cancel.canceled)
        except BaseException as exc:  # Assert the typed cancellation outside the thread.
            outcome.append(exc)

    thread = Thread(target=_run, daemon=True)
    thread.start()
    time.sleep(0.08)
    cancel.cancel("phase76_test")
    thread.join(timeout=3.0)
    try:
        assert not thread.is_alive()
        assert len(outcome) == 1
        assert isinstance(outcome[0], RuntimeCanceledError)
        assert worker.metadata()["worker_pid"] is None
    finally:
        worker.close()
        runtime.close()


def test_phase76_fork_route_fails_closed_when_kernel_reports_extra_threads(monkeypatch):
    import quantbt.backends.reactive_wfo_workers as workers

    monkeypatch.setattr(workers, "_parent_os_thread_count", lambda: 2)
    assert workers.fork_reactive_wfo_worker_supported() is True
    assert workers.fork_reactive_wfo_worker_safe() is False


@pytest.mark.skipif(
    not fork_reactive_wfo_worker_supported(),
    reason="Phase 76 subprocess worker check requires POSIX fork copy-on-write",
)
def test_phase76_process_worker_certifies_in_clean_single_thread_subprocess():
    """Exercise COW lifecycle in a process that constrains BLAS before import."""

    source = Path(__file__).resolve()
    code = (
        "import runpy; "
        f"namespace = runpy.run_path({str(source)!r}); "
        "namespace['_phase76_clean_worker_smoke'](); "
        "print('phase76-clean-worker-ok')"
    )
    environment = dict(os.environ)
    environment.update(
        {
            "OPENBLAS_NUM_THREADS": "1",
            "OMP_NUM_THREADS": "1",
            "MKL_NUM_THREADS": "1",
            "NUMEXPR_NUM_THREADS": "1",
            "NUMBA_NUM_THREADS": "1",
            "PYTHONPATH": str(Path.cwd() / "src"),
        }
    )
    completed = subprocess.run(
        [sys.executable, "-c", code],
        cwd=Path.cwd(),
        env=environment,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + "\n" + completed.stderr
    assert "phase76-clean-worker-ok" in completed.stdout


def _phase76_clean_worker_smoke() -> None:
    """Subprocess entry point: keep the parent unthreaded until it forks."""

    assert fork_reactive_wfo_worker_safe()
    runtime, worker, marker = _worker_fixture()
    try:
        first = worker.score(marker, canceled=lambda: False)
        second = worker.score(marker, canceled=lambda: False)
        np.testing.assert_allclose(first["sharpe"], second["sharpe"], rtol=0.0, atol=1e-10)
        metadata = worker.metadata()
        assert metadata["worker_pool_creations"] == 1
        assert metadata["worker_scalar_sessions"]["session_creations"] == 1
        assert metadata["worker_scalar_sessions"]["session_runs"] == 2
        assert metadata["worker_market_ipc_bytes_per_task"] == 0
    finally:
        worker.close()
        runtime.close()
