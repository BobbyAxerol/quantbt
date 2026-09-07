"""PERF-05 WFO reuse, identity, retention, and pruning-safety contracts."""

from __future__ import annotations

import importlib.util
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from quantbt import QuantBTEndpoint
from quantbt.core.wfo_evaluation import WfoExecutionReuseRuntimeV1
from quantbt.walkforward import WalkForwardConfig, WalkForwardEngine, WalkForwardFold


def _bars(*, periods: int = 420) -> pd.DataFrame:
    index = pd.date_range("2020-01-01", periods=periods, freq="1D", tz="UTC")
    phase = np.arange(periods, dtype=np.float64)
    close = 100.0 + phase * 0.05 + np.sin(phase / 6.0)
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
    signal = np.where((bars // 5) % 2 == 0, direction, -direction)
    return pd.Series(np.asarray(signal, dtype=np.float64), index=test_index)


class _PureTerminalScorer:
    """Deterministic scorer which models the prepared-native terminal boundary."""

    def __init__(self) -> None:
        self.calls: list[int] = []

    def bind_walkforward_context(self, context) -> None:
        self.context = context

    def wfo_execution_reuse_contract(self):
        return {
            "schema": "tests-perf05-terminal-contract-v1",
            "contract": "run_local_terminal_metrics_v1",
            "pure_terminal_metrics": True,
            "fresh_account_per_evaluation": True,
            "deterministic_given_contract": True,
            "cross_run_reuse": False,
            "engine_semantic_build": "tests-perf05-v1",
            "numeric_contract": "tests-terminal-score-v1",
            "market_identity": "fixed-market-v1",
            "template_identity": "fixed-template-v1",
            "score_context_affects_terminal_metrics": False,
        }

    def score_batch(self, tasks):
        self.calls.append(len(tasks))
        rows = []
        for task in tasks:
            values = task["output"].to_numpy(dtype=np.float64, copy=False)
            changes = float(np.count_nonzero(np.diff(np.sign(values))))
            rows.append(
                {
                    "sharpe": float(0.75 + np.mean(values) * 0.1 + changes / max(len(values), 1)),
                    "turnover": changes,
                    "trade_count": changes,
                    "mean_return": float(np.mean(values) * 0.001),
                    "volatility": 0.0,
                    "max_drawdown_pct": 1.0,
                    "profit_factor": float("inf"),
                }
            )
        return rows


def _config(mode: str, *, reuse: str = "auto") -> WalkForwardConfig:
    common = dict(
        split_mode="2020-07-01",
        split_frequency="quarterly",
        window_mode="rolling",
        train_window="120D",
        min_train_bars=30,
        min_test_bars=20,
        target_mode="signal_notional",
        optimization_mode=mode,
        optimization_schedule="global",
        optuna_trials=4,
        optuna_early_stopping=None,
        random_seed=17,
        top_is_fraction=1.0,
        flat_eps=1.0,
        flat_min_samples=1,
        candidate_selection_metric={
            "mode_1_decay": "robust_decay",
            "mode_3_flat_minima": "is_plateau_robust",
            "mode_4_is_only_robust": "is_only_robust",
            "mode_5_full_robust": "full_robust",
        }.get(mode, "robust_decay"),
        scoring_backend="endpoint",
        scoring_trading_days=365,
        min_trades_per_year=None,
        trade_penalty_factor=None,
        is_subperiods=2,
        metadata={
            "wfo_execution_reuse": reuse,
            "wfo_execution_reuse_trace_limit": 128,
            "use_prepared_wfo_context": True,
        },
    )
    return WalkForwardConfig(**common)


def _run(mode: str, *, reuse: str):
    scorer = _PureTerminalScorer()
    result = WalkForwardEngine(strategy=_strategy, config=_config(mode, reuse=reuse), scorer=scorer).run(
        _bars(),
        param_ranges={"direction": [-1.0, 1.0]},
    )
    return result, scorer


def _run_schedule(mode: str, schedule: str, *, reuse: str):
    source = _config(mode, reuse=reuse)
    config = WalkForwardConfig(
        **{
            **source.__dict__,
            "optimization_schedule": schedule,
            "inner_split_frequency": "monthly" if schedule == "per_fold_causal" else None,
            "inner_window_mode": "rolling" if schedule == "per_fold_causal" else None,
            "inner_train_window": "60D" if schedule == "per_fold_causal" else None,
            "inner_min_folds": 1 if schedule == "per_fold_causal" else 2,
        }
    )
    scorer = _PureTerminalScorer()
    result = WalkForwardEngine(strategy=_strategy, config=config, scorer=scorer).run(
        _bars(periods=720),
        param_ranges={"direction": [-1.0, 1.0]},
    )
    return result, scorer


@pytest.mark.parametrize(
    "mode",
    ("mode_1_decay", "mode_3_flat_minima", "mode_4_is_only_robust", "mode_5_full_robust"),
)
def test_perf05_exact_native_score_reuse_preserves_all_supported_endpoint_mode_outputs(mode: str):
    baseline, baseline_scorer = _run(mode, reuse="off")
    reused, reused_scorer = _run(mode, reuse="auto")

    pd.testing.assert_series_equal(reused.oos_output, baseline.oos_output, check_exact=True)
    pd.testing.assert_frame_equal(reused.trial_table, baseline.trial_table, check_exact=True)
    pd.testing.assert_frame_equal(reused.candidate_table, baseline.candidate_table, check_exact=True)
    assert reused.params == baseline.params
    assert reused.best_trial == baseline.best_trial

    runtime = reused.metadata["wfo_evaluation_runtime"]
    assert runtime["mode_evaluation_matrix"][mode]["retention"]
    assert runtime["cache_payload"] == "completed_terminal_metric_mapping_only"
    assert runtime["cache_entries"] == 0
    assert runtime["cache_entries_released"] is True
    if mode == "mode_5_full_robust":
        assert runtime["resolved_policy"] == "disabled"
        assert runtime["reason"] == "mode_5_has_no_post_study_exact_score_reuse"
        assert runtime["cache_hits"] == 0
        assert runtime["cache_stores"] == 0
        assert runtime["adaptive_read_bypasses"] == 0
    else:
        assert runtime["adaptive_read_bypasses"] > 0
        assert runtime["cache_stores"] > 0
        assert runtime["cache_hits"] > 0
        assert runtime["terminal_score_bars_reused"] > 0
        assert sum(reused_scorer.calls) < sum(baseline_scorer.calls)


def test_perf05_mode2_keeps_proxy_path_and_streaming_retention_declaration():
    data = _bars()
    config = WalkForwardConfig(
        split_mode="2020-07-01",
        split_frequency="quarterly",
        window_mode="rolling",
        train_window="120D",
        min_train_bars=30,
        min_test_bars=20,
        target_mode="signal_notional",
        optimization_mode="mode_2_sbb",
        optuna_trials=3,
        random_seed=17,
        top_is_fraction=1.0,
        scoring_backend="proxy",
        sbb_samples=8,
        sbb_block_length=3,
        min_trades_per_year=None,
        trade_penalty_factor=None,
        metadata={"wfo_execution_reuse": "auto", "use_prepared_wfo_context": True},
    )
    result = WalkForwardEngine(strategy=_strategy, config=config).run(
        data,
        param_ranges={"direction": [-1.0, 1.0]},
    )
    runtime = result.metadata["wfo_evaluation_runtime"]
    assert runtime["resolved_policy"] == "disabled"
    assert runtime["reason"] == "scorer_has_no_pure_terminal_reuse_contract"
    assert runtime["mode_evaluation_matrix"]["mode_2_sbb"]["score_reuse"] == "proxy_path_authority_no_native_score_reuse"
    assert runtime["streaming_reducer_contract"]["replicate_by_bar_by_candidate_tensor"] == (
        "never_constructed_by_wfo_reducer"
    )


def test_perf05_mode1_per_fold_decay_keeps_study_local_reuse_and_exact_result_parity():
    baseline, _ = _run_schedule("mode_1_decay", "per_fold_decay", reuse="off")
    reused, _ = _run_schedule("mode_1_decay", "per_fold_decay", reuse="require")

    pd.testing.assert_series_equal(reused.oos_output, baseline.oos_output, check_exact=True)
    pd.testing.assert_frame_equal(reused.trial_table, baseline.trial_table, check_exact=True)
    pd.testing.assert_frame_equal(reused.candidate_table, baseline.candidate_table, check_exact=True)
    assert reused.metadata["params_by_fold"] == baseline.metadata["params_by_fold"]
    runtime = reused.metadata["wfo_evaluation_runtime"]
    assert runtime["cache_hits"] > 0
    assert runtime["terminal_score_bars_reused"] > 0
    studies = {int(row["study_id"]) for row in runtime["attempt_ledger"]}
    assert len(studies) > 1


def test_perf05_mode4_per_fold_causal_disables_cache_without_a_post_study_exact_replay():
    baseline, _ = _run_schedule("mode_4_is_only_robust", "per_fold_causal", reuse="off")
    reused, _ = _run_schedule("mode_4_is_only_robust", "per_fold_causal", reuse="auto")

    pd.testing.assert_series_equal(reused.oos_output, baseline.oos_output, check_exact=True)
    assert reused.metadata["params_by_fold"] == baseline.metadata["params_by_fold"]
    runtime = reused.metadata["wfo_evaluation_runtime"]
    assert runtime["resolved_policy"] == "disabled"
    assert runtime["reason"] == "mode_4_per_fold_causal_has_no_post_study_exact_score_reuse"
    assert runtime["cache_stores"] == 0


def _runtime_context(*, data_signature: str = "data-a", config_signature: str = "config-a"):
    return SimpleNamespace(signature=f"context:{data_signature}:{config_signature}", data_signature=data_signature, config_signature=config_signature)


def _runtime_task():
    index = pd.date_range("2024-01-01", periods=4, freq="1D", tz="UTC")
    fold = WalkForwardFold(
        fold_id=0,
        train_start=index[0],
        train_end=index[1],
        test_start=index[2],
        test_end=index[3],
        train_index=index[:2],
        test_index=index[2:],
    )
    output = pd.Series(np.asarray([1.0, -1.0], dtype=np.float64), index=index[:2])
    return (output, index[:2], fold, {"direction": 1.0}, "in-sample scoring")


def test_perf05_cache_keeps_duplicate_trial_attempts_distinct_and_never_reads_during_adaptive_sampling():
    config = _config("mode_1_decay", reuse="require")
    scorer = _PureTerminalScorer()
    first = WfoExecutionReuseRuntimeV1(
        config=config,
        prepared_context=_runtime_context(),
        strategy_fingerprint="strategy-a",
        scorer=scorer,
    )
    task = _runtime_task()
    adaptive_a = first.lookup((task,), scope={"trial_id": 3, "stage": "is_search", "adaptive_optimizer": True})
    first.commit(adaptive_a, metrics_by_position={0: {"sharpe": 1.0, "turnover": 2.0, "trade_count": 2.0}})
    adaptive_b = first.lookup((task,), scope={"trial_id": 3, "stage": "is_search", "adaptive_optimizer": True})
    assert adaptive_b.cached_metrics == (None,)
    first.commit(adaptive_b, metrics_by_position={0: {"sharpe": 1.0, "turnover": 2.0, "trade_count": 2.0}})
    post_selection = first.lookup(
        (task,),
        scope={"trial_id": 3, "stage": "oos_candidate_selection", "adaptive_optimizer": False},
    )
    assert post_selection.cached_metrics[0] == {"sharpe": 1.0, "turnover": 2.0, "trade_count": 2.0}
    assert post_selection.attempt_rows[0]["execution_id"] == adaptive_a.attempt_rows[0]["execution_id"]
    assert post_selection.attempt_rows[0]["execution_attempt_id"] != adaptive_a.attempt_rows[0]["execution_attempt_id"]

    duplicate_trial = first.lookup(
        (task,),
        scope={"trial_id": 4, "stage": "is_search", "adaptive_optimizer": False},
    )
    assert duplicate_trial.cached_metrics == (None,)
    assert duplicate_trial.attempt_rows[0]["execution_id"] != adaptive_a.attempt_rows[0]["execution_id"]
    first.commit(duplicate_trial, metrics_by_position={0: {"sharpe": 1.0, "turnover": 2.0, "trade_count": 2.0}})
    metadata = first.close()
    assert metadata["adaptive_read_bypasses"] == 2
    assert metadata["cache_hits"] == 1
    assert metadata["attempt_rows_retained"] == 4


def test_perf05_semantic_context_and_seed_changes_do_not_share_execution_keys():
    task = _runtime_task()
    scorer = _PureTerminalScorer()
    left = WfoExecutionReuseRuntimeV1(
        config=_config("mode_1_decay", reuse="require"),
        prepared_context=_runtime_context(data_signature="prices-and-funding-a"),
        strategy_fingerprint="strategy-a",
        scorer=scorer,
    )
    changed_config = _config("mode_1_decay", reuse="require")
    object.__setattr__(changed_config, "random_seed", 99)
    right = WfoExecutionReuseRuntimeV1(
        config=changed_config,
        prepared_context=_runtime_context(data_signature="prices-and-funding-b"),
        strategy_fingerprint="strategy-a",
        scorer=scorer,
    )
    left_lookup = left.lookup((task,), scope={"trial_id": 2, "adaptive_optimizer": True})
    right_lookup = right.lookup((task,), scope={"trial_id": 2, "adaptive_optimizer": True})
    assert left_lookup.keys[0] != right_lookup.keys[0]
    assert left_lookup.attempt_rows[0]["run_id"] != right_lookup.attempt_rows[0]["run_id"]


def test_perf05_study_seed_and_study_identity_prevent_cross_study_reuse():
    runtime = WfoExecutionReuseRuntimeV1(
        config=_config("mode_1_decay", reuse="require"),
        prepared_context=_runtime_context(),
        strategy_fingerprint="strategy-a",
        scorer=_PureTerminalScorer(),
    )
    task = _runtime_task()
    first = runtime.lookup(
        (task,),
        scope={"trial_id": 0, "study_id": 1, "rng_seed": 101, "adaptive_optimizer": True},
    )
    second = runtime.lookup(
        (task,),
        scope={"trial_id": 0, "study_id": 2, "rng_seed": 202, "adaptive_optimizer": True},
    )
    assert first.keys[0] != second.keys[0]
    assert first.attempt_rows[0]["study_id"] == 1
    assert second.attempt_rows[0]["rng_seed"] == 202


def test_perf05_rejects_an_underspecified_terminal_scorer_contract():
    """Reuse is fail-closed when terminal-score determinism is not declared."""

    class _UnderspecifiedScorer(_PureTerminalScorer):
        def wfo_execution_reuse_contract(self):
            contract = super().wfo_execution_reuse_contract()
            contract.pop("deterministic_given_contract")
            return contract

    with pytest.raises(ValueError, match="scorer_has_no_pure_terminal_reuse_contract"):
        WfoExecutionReuseRuntimeV1(
            config=_config("mode_1_decay", reuse="require"),
            prepared_context=_runtime_context(),
            strategy_fingerprint="strategy-a",
            scorer=_UnderspecifiedScorer(),
        )


@pytest.mark.skipif(
    importlib.util.find_spec("_quantbt_native") is None,
    reason="quantbt-native extension is not installed in this environment",
)
def test_perf05_public_native_prepared_score_reuse_is_real_and_preserves_public_result():
    """Exercise the real public scorer rather than only the deterministic oracle.

    Candidate analysis deliberately re-reads exact complete trial/fold metrics;
    adaptive Optuna calls remain store-only.  This test makes that boundary
    visible on the actual prepared Rust endpoint route.
    """

    data = _bars(periods=720)

    def public_strategy(data, params, train_index, test_index, fold):
        del data, train_index, fold
        bars = np.arange(len(test_index), dtype=np.int64)
        direction = float(params["direction"])
        return pd.Series(
            direction * np.where((bars // 9) % 2 == 0, 1.0, -1.0),
            index=test_index,
            dtype=float,
        )

    def run(policy: str):
        endpoint = QuantBTEndpoint.walk_forward(
            strategy_class=public_strategy,
            split_mode="2020-07-01",
            split_frequency="quarterly",
            window_mode="rolling",
            train_window="180D",
            target_mode="signal_notional",
            optimization_mode="mode_1_decay",
            optimization_config={
                "candidate_selection_metric": "robust_decay",
                "top_is_fraction": 1.0,
                "scoring_backend": "endpoint",
                "native_prepared_wfo": "require",
                "native_prepared_wfo_workers": 1,
                "wfo_execution_reuse": policy,
                "scoring_trading_days": 365,
                "min_trades_per_year": None,
                "trade_penalty_factor": None,
            },
            optuna_trials=2,
            random_seed=13,
            initial_capital=20_000.0,
            leverage=3.0,
            maintenance_ratio=0.005,
            alloc_per_trade=1_000.0,
            fee_rate=0.0002,
            slippage=0.0001,
            target_runtime="rust",
        )
        return endpoint.backtest(
            data=data,
            symbols=["BTC"],
            param_ranges={"direction": [-1.0, 1.0]},
        )

    baseline = run("off")
    reused = run("require")
    pd.testing.assert_series_equal(reused.equity, baseline.equity, check_exact=False, atol=1e-10)
    pd.testing.assert_frame_equal(reused.positions, baseline.positions, check_exact=False, atol=1e-12)
    baseline_wf = baseline.metadata["walk_forward"]
    reused_wf = reused.metadata["walk_forward"]
    pd.testing.assert_frame_equal(reused_wf["trial_table"], baseline_wf["trial_table"], check_exact=True)
    assert reused_wf["params"] == baseline_wf["params"]
    assert reused_wf["best_trial"] == baseline_wf["best_trial"]

    runtime = reused_wf["wfo_evaluation_runtime"]
    assert runtime["resolved_policy"] == "enabled_then_released"
    assert runtime["cache_hits"] > 0
    assert runtime["cache_stores"] > 0
    assert runtime["adaptive_read_bypasses"] > 0
    assert runtime["semantic_contract"]["engine_semantic_build"] == "native_prepared_public_wfo_v1"
