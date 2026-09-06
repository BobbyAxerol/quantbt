from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from quantbt.core.performance_contracts import (
    EXCLUSIVE_WORK_STAGES_V1,
    ExclusiveWorkProfilerV1,
    ObservationIdV1,
    compile_walkforward_computation_plan,
)
from quantbt import QuantBTEndpoint
from quantbt.walkforward import WalkForwardConfig, WalkForwardEngine


ROOT = Path(__file__).resolve().parents[1]
TRACEABILITY_TOOL = ROOT / "tools" / "generate_perf01_traceability.py"
OBSERVER_BENCHMARK = ROOT / "benchmarks" / "native_event" / "benchmark_perf01_observer.py"


def _bars(rows: int = 540) -> pd.DataFrame:
    index = pd.date_range("2020-01-01", periods=rows, freq="1D", tz="UTC")
    ordinal = np.arange(rows, dtype=np.float64)
    close = 100.0 + 0.03 * ordinal + np.sin(ordinal / 11.0)
    return pd.DataFrame(
        {
            "open": close,
            "high": close + 1.0,
            "low": close - 1.0,
            "close": close,
            "volume": 1_000.0 + ordinal,
        },
        index=index,
    )


def _strategy(data, params, train_index, test_index, fold):
    del data, train_index, fold
    return pd.Series(float(params["side"]), index=test_index)


def _deterministic_scorer(data, output, index, fold, params, context, trading_days):
    del data, output, index, fold, trading_days
    side = float(params["side"])
    is_oos = "out-of-sample" in str(context)
    sharpe = (1.10 if is_oos else 1.35) + 0.20 * side
    return {
        "sharpe": sharpe,
        "turnover": 400.0,
        "trade_count": 400.0,
        "mean_return": 0.001,
        "volatility": 0.01,
        "max_drawdown_pct": 3.0,
        "profit_factor": 1.2,
    }


def _run_mode1(*, perf_01_profile: bool):
    config = WalkForwardConfig(
        split_mode="2021-01-01",
        split_frequency="quarterly",
        window_mode="rolling",
        train_window="180D",
        optimization_mode="mode_1_decay",
        optimization_schedule="global",
        optuna_trials=4,
        random_seed=41,
        top_is_fraction=1.0,
        candidate_selection_metric="robust_decay",
        scoring_backend="endpoint",
        metadata={"perf_01_profile": perf_01_profile},
    )
    return WalkForwardEngine(strategy=_strategy, scorer=_deterministic_scorer, config=config).run(
        data=_bars(),
        param_ranges={"side": [0, 1]},
    )


def _load_traceability_tool():
    specification = importlib.util.spec_from_file_location("perf01_traceability", TRACEABILITY_TOOL)
    assert specification is not None and specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def _load_observer_benchmark():
    specification = importlib.util.spec_from_file_location("perf01_observer_benchmark", OBSERVER_BENCHMARK)
    assert specification is not None and specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def test_observation_ledger_deduplicates_per_reducer():
    config = WalkForwardConfig(optimization_mode="mode_1_decay")
    plan = compile_walkforward_computation_plan(config)
    observation = ObservationIdV1("account", "return_sample", ordinal=7)
    ledger = plan.observation_ledger()

    assert ledger.claim(observation, "standard_metrics") is True
    assert ledger.claim(observation, "standard_metrics") is False
    assert ledger.claim(observation, "trade_frequency") is True
    assert ledger.metadata()["reducer_observation_counts"] == {
        "standard_metrics": 1,
        "trade_frequency": 1,
        "selection_objective": 0,
        "decay_selector": 0,
    }


def test_opaque_custom_metric_requires_conservative_full_input():
    config = WalkForwardConfig(
        optimization_mode="mode_4_is_only_robust",
        metadata={"custom_metric_requirements": "undeclared callback inputs"},
    )
    plan = compile_walkforward_computation_plan(config)

    assert plan.opaque_custom_metric is True
    assert plan.native_score_eligible is False
    assert "full_execution_observation_stream" in plan.required_intermediate_paths
    with pytest.raises(ValueError, match="scalar-only native score route is not eligible"):
        plan.require_native_score_eligibility()


def test_profiled_wfo_preserves_trial_checkpoint_order_and_result():
    unprofiled = _run_mode1(perf_01_profile=False)
    profiled = _run_mode1(perf_01_profile=True)

    pd.testing.assert_series_equal(unprofiled.oos_output, profiled.oos_output)
    pd.testing.assert_frame_equal(unprofiled.fold_table, profiled.fold_table)
    pd.testing.assert_frame_equal(unprofiled.trial_table, profiled.trial_table)
    pd.testing.assert_frame_equal(unprofiled.candidate_table, profiled.candidate_table)
    assert unprofiled.best_trial == profiled.best_trial
    assert unprofiled.params == profiled.params

    plan = profiled.metadata["required_computation_plan"]
    assert plan["requires_intermediate_checkpoints"] is True
    assert "pruner_checkpoint_stream" in plan["output_sinks"]
    # Candidate rows intentionally preserve selector/source order rather than
    # sorting by ID; exact off/on ledger equality above is the checkpoint gate.
    assert len(profiled.trial_table) >= 2


def test_observer_on_off_keeps_walkforward_economics_identical():
    unprofiled = _run_mode1(perf_01_profile=False)
    profiled = _run_mode1(perf_01_profile=True)

    off = unprofiled.metadata["perf_01_profile"]
    on = profiled.metadata["perf_01_profile"]
    assert off["enabled"] is False
    assert on["enabled"] is True
    assert set(on["exclusive_stage_elapsed_ns"]) == set(EXCLUSIVE_WORK_STAGES_V1)
    assert on["exclusive_stage_calls"]["prepare_validate_ingest"] >= 1
    assert on["exclusive_stage_calls"]["advance_match_account_wake"] >= 1
    assert on["exclusive_stage_calls"]["projection_python_decision_command_write_ingest"] >= 1
    assert on["exclusive_stage_calls"]["metrics_analysis_audit_encode_flush_public_adapt"] == 1
    assert on["activity_counters"]["python_strategy_entries"] >= 1
    assert on["activity_counters"]["metric_observation_passes"] >= 1
    assert on["activity_counters"]["python_callback_entries"] is None

    pd.testing.assert_series_equal(unprofiled.oos_output, profiled.oos_output)
    assert unprofiled.params == profiled.params
    assert unprofiled.best_trial == profiled.best_trial


def test_public_endpoint_forwards_opt_in_perf01_profile():
    endpoint = QuantBTEndpoint.walk_forward(
        strategy_class=_strategy,
        split_mode="2021-01-01",
        split_frequency="quarterly",
        window_mode="rolling",
        train_window="180D",
        target_mode="signal_notional",
        optimization_mode="none",
        optimization_config={"perf_01_profile": True},
        initial_capital=20_000.0,
        alloc_per_trade=1_000.0,
        fee_rate=0.0,
        use_funding=False,
    )
    result = endpoint.backtest(data=_bars(), symbols=["BTC"], params={"side": 1.0})
    metadata = result.metadata["walk_forward"]

    assert metadata["required_computation_plan"]["optimization_mode"] == "none"
    assert metadata["perf_01_profile"]["enabled"] is True
    assert metadata["perf_01_profile"]["exclusive_stage_calls"]["prepare_validate_ingest"] >= 1


def test_exclusive_profiler_refuses_nested_double_counting():
    profiler = ExclusiveWorkProfilerV1(enabled=True, route_id="test")
    with profiler.stage("prepare_validate_ingest"):
        with pytest.raises(RuntimeError, match="does not allow nested stages"):
            profiler.begin("advance_match_account_wake")
    profiler.record_elapsed("advance_match_account_wake", 10, calls=1)

    snapshot = profiler.snapshot()
    assert snapshot["exclusive_stage_calls"]["prepare_validate_ingest"] == 1
    assert snapshot["exclusive_stage_calls"]["advance_match_account_wake"] == 1


def test_traceability_generator_has_complete_static_map_and_separate_runtime_identity(tmp_path):
    tool = _load_traceability_tool()
    manifest = tool.build_manifest()

    assert tool.validate_manifest(manifest) == []
    route_ids = {row["id"] for row in manifest["route_matrix"]}
    assert {f"walk_forward_mode_{mode}" for mode in range(1, 6)} <= route_ids
    assert {row["id"] for row in manifest["ap_dispositions"]} == {f"AP-{value:02d}" for value in range(1, 13)}
    assert {row["id"] for row in manifest["benchmark_classes"]} == {f"B-{value:02d}" for value in range(1, 15)}
    assert "git_commit" not in manifest["baseline_source"]

    runtime_identity = tool.capture_runtime_identity()
    assert runtime_identity["source_identity"]["git_commit"]
    assert runtime_identity["source_identity"]["canonical_source_sha256"]

    manifest_path = tmp_path / "traceability.json"
    doc_path = tmp_path / "traceability.md"
    identity_path = tmp_path / "runtime_identity.json"
    assert tool.main(
        [
            "--manifest",
            str(manifest_path),
            "--doc",
            str(doc_path),
            "--runtime-identity",
            str(identity_path),
        ]
    ) == 0
    assert tool.main(["--manifest", str(manifest_path), "--doc", str(doc_path), "--check"]) == 0
    assert tool.main(["--check"]) == 0


def test_public_observer_harness_preserves_economics_on_paired_runs():
    benchmark = _load_observer_benchmark()
    payload = benchmark.run_benchmark(bars=540, trials=2, warmup=0, repeats=2)

    assert payload["status"] == "development_baseline_not_promotion_evidence"
    assert payload["economic_parity"]["passed"] is True
    assert payload["observer_off"]["samples"] == 2
    assert payload["observer_on"]["samples"] == 2
    assert payload["candidate_identity"]["data_sha256"]
    assert payload["candidate_identity"]["intent_sha256"]
