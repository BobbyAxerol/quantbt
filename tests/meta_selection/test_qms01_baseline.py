"""Q1-T01..Q1-T08: inspect the released public path, not a proposed meta API."""

from copy import deepcopy
from dataclasses import replace
import json

import numpy as np
import pandas as pd
import pytest

from quantbt.core.types import BacktestResult
from quantbt.backends.native_wfo_public import NativePreparedPublicWfoScorerV1, NativePreparedPublicWfoUnsupported
from quantbt.metrics.performance import _returns_for_stats, sharpe
from quantbt.walkforward import WalkForwardConfig, select_is_only_robust_record
from tools import qms01_baseline as baseline


@pytest.fixture(scope="module")
def source():
    # QMS-01 is an immutable snapshot; later approved phases have new source.
    return json.loads(baseline.MANIFEST.read_text())["source"]


@pytest.fixture(scope="module")
def traced():
    return baseline.trace_run()


@pytest.fixture(scope="module")
def manifest():
    if baseline.MANIFEST.exists():
        return json.loads(baseline.MANIFEST.read_text())
    return baseline.build_manifest()


@pytest.mark.parametrize("mutation", ["tag", "import", "core", "native", "descriptor", "abi", "source", "guide"])
def test_q1_t01_source_mismatch_is_detected(source, mutation):
    baseline.validate_identity(source, historical=True)
    bad = deepcopy(source)
    if mutation == "tag":
        bad["release_sha"] = "0" * 40
    elif mutation == "import":
        bad["installed"]["core_origin"] = str(baseline.ROOT / "quantbt/__init__.py")
    elif mutation in {"core", "native"}:
        bad["installed"]["versions"]["quantbt-engine" if mutation == "core" else "quantbt-native"] = "0.0.0"
    elif mutation == "descriptor":
        bad["installed"]["product_descriptor"]["native_package_version"] = "0.0.0"
    elif mutation == "abi":
        bad["installed"]["core_abi"] = "9.0"
    elif mutation == "source":
        bad["runtime_diff_from_release"] = ["src/quantbt/walkforward.py"]
    else:
        bad["protected_sources"][baseline.GUIDE] = "0" * 64
    with pytest.raises(ValueError):
        baseline.validate_identity(bad, historical=True)


def test_q1_t02_actual_public_current_oos_mutation_cannot_change_first_selection(traced):
    observed, result, _engine = traced
    future = baseline.market()
    mask = future.index >= pd.Timestamp("2021-01-01", tz="UTC")
    factor = np.linspace(1.0, 3.0, mask.sum())
    future.loc[mask, ["open", "high", "low", "close"]] *= factor[:, None]
    changed, changed_result, _engine = baseline.trace_run(future)
    assert observed["pools"][0] == changed["pools"][0]
    assert observed["studies"][0]["selected"] == changed["studies"][0]["selected"]
    assert not np.array_equal(result.equity.to_numpy(), changed_result.equity.to_numpy())
    assert all(pd.Timestamp(row["visible_data_end"]) <= pd.Timestamp(row["requested_end"])
               for row in observed["scorer_windows"])
    events = observed["events"]
    for study in observed["studies"]:
        fid = study["study_id"]
        boundary = next(i for i, event in enumerate(events)
                        if event["event"] == "optimize_return_before_params_by_fold" and event["study_id"] == fid)
        outer = [i for i, event in enumerate(events) if event["event"] == "score"
                 and event["fold_id"] == fid and event["context"] == "post-selection outer OOS realization"]
        assert len(outer) == 1 and outer[0] > boundary
        assert pd.Timestamp(study["cutoff"]) < pd.Timestamp(study["wall_search_started_at"])
        assert pd.Timestamp(study["cutoff"]) < pd.Timestamp(study["fold_execution_cutoff"])
        assert pd.Timestamp(study["wall_search_started_at"]) <= pd.Timestamp(study["wall_search_completed_at"])
        # Replay generation timestamps are evidence, never past live effects.
        assert "decision_sealed_at" not in study and "effective_at" not in study
    assert observed["summary"]["oos_used_for_selection"] is False


@pytest.mark.parametrize("selector", ["medoid", "centroid", "fallback"])
def test_q1_t03_native_anchor_is_not_raw_best(selector):
    records, selected, config = baseline.anchor_fixture("centroid" if selector == "centroid" else "medoid")
    if selector == "fallback":
        config = replace(config, flat_min_samples=5)
        records[0].selection_metadata["temporal_score"] = -1.0
        records[2].selection_metadata["temporal_score"] = 20.0
        selected = select_is_only_robust_record(records, {"x": (0, 10, 1)}, config)
        assert selected.selection_metadata["selector"] == "fallback_best_is_temporal"
    assert selected.params == {"x": 3}
    assert selected.trial_id != 0
    assert max(records, key=lambda row: row.fold_metrics[0]["is_sharpe_raw"]).trial_id == 0
    if selector == "centroid":
        assert selected.trial_id == -1 and selected.selection_metadata["requires_evaluation"]
        assert not selected.fold_metrics


def test_q1_t03_centroid_authoritative_same_is_replay_is_available():
    observed, _result, _engine = baseline.trace_run(centroid=True)
    anchor = observed["studies"][0]["selected"]
    assert anchor["trial_id"] == -1 and anchor["selection_metadata"]["requires_evaluation"]
    assert not anchor["fold_metrics"]
    exact = observed["studies"][0]["diagnostic_anchor_replay"]
    assert len(exact["fold_metrics"]) == 1
    assert np.isfinite(exact["fold_metrics"][0]["is_sharpe_raw"])
    assert exact["fold_metrics"][0]["oos_evaluated"] is False
    assert exact["mean_is_sharpe"] != anchor["mean_is_sharpe"]
    # Legacy is preserved; future opt-in meta must use this exact IS evaluator,
    # not assign the cluster-average proxy to a new candidate.
    assert observed["pools"][0]["native_anchor"]["params"] == anchor["params"]


def test_q1_t03_actual_public_anchor_is_not_raw_best(traced):
    observed, _result, _engine = traced
    pool = observed["pools"][0]
    assert pool["native_anchor"]["trial_id"] == 4
    assert pool["raw_best_trial_id"] == pool["objective_best_trial_id"] == 2


def test_q1_t04_pool_and_compaction_are_traced_before_loss(traced):
    observed, _result, engine = traced
    for pool, study in zip(observed["pools"], observed["studies"], strict=True):
        eligible = [row for row in pool["all_trials"] if not row["pruned"] and np.isfinite(row["objective"])]
        assert pool["eligible_ids"] == [row["trial_id"] for row in eligible]
        assert len(pool["all_trials"]) == baseline.BUDGET["trials_per_study"]
        assert len(set(pool["eligible_ids"])) > len(set(pool["filtered_candidate_ids"]))
        assert all(row["fold_metrics"] for row in eligible)
        assert all(not row["fold_metrics"] for row in study["compact_trials"])
        for row in eligible:
            metrics = row["fold_metrics"][0]
            assert metrics["is_sharpe"] == metrics["is_sharpe_raw"] - metrics["is_trade_penalty"]
    assert len(engine._research_full_trial_records) == 12
    assert engine._research_full_trial_records[0].fold_metrics


def test_q1_t04_instrumentation_and_retention_do_not_change_public_outputs(traced):
    observed, result, _engine = traced
    bt = baseline.endpoint(retention="none")
    plain = bt.backtest(data=baseline.market(), symbols=["BTC"], param_ranges={"window": (3, 31, 2)})
    pd.testing.assert_series_equal(result.equity, plain.equity, check_exact=True)
    pd.testing.assert_frame_equal(result.positions, plain.positions, check_exact=True)
    assert plain.metadata["walk_forward"]["params_by_fold"] == result.metadata["walk_forward"]["params_by_fold"]
    pd.testing.assert_frame_equal(plain.metadata["walk_forward"]["trial_table"], result.metadata["walk_forward"]["trial_table"], check_exact=True)


def test_q1_t05_installed_prepared_rust_matches_public_oracle(traced, source):
    observed, result, _engine = traced
    native, native_result, _engine = baseline.trace_run(native="require")
    assert native["summary"]["params_by_fold"] == observed["summary"]["params_by_fold"]
    pd.testing.assert_series_equal(native_result.equity, result.equity, rtol=1e-11, atol=1e-9)
    pd.testing.assert_frame_equal(native_result.positions, result.positions, rtol=1e-11, atol=1e-9)
    for ref, actual in zip(observed["score_tasks"], native["score_tasks"], strict=True):
        assert ref["context"] == actual["context"] and ref["params"] == actual["params"]
        assert actual["metrics"]["sharpe"] == pytest.approx(ref["metrics"]["sharpe"], abs=1e-9)
        assert actual["metrics"]["trade_count"] == ref["metrics"]["trade_count"]
        assert ref["metrics"]["volatility"] == actual["metrics"]["volatility"] == 0.0
    stats = native["summary"]["native_prepared_wfo"]
    assert stats["execution_clock"] == "close_target_v2_same_close"
    assert stats["resolved_policy"] == "native_prepared" and stats["fallback_rows"] == 0
    assert stats["native_rows"] == len(native["score_tasks"])
    assert stats["native_scored_bars"] == sum(row["bars"] for row in native["score_tasks"])
    assert "NativePreparedEvaluationRuntimeCore" in source["installed"]["native_exports"]


def test_q1_t05_zero_undefined_absent_and_placeholder_are_distinct():
    def result(returns):
        index = pd.date_range("2020-01-01", periods=len(returns) + 1, freq="D", tz="UTC")
        equity = pd.Series(np.r_[100.0, 100.0 * np.cumprod(1.0 + np.asarray(returns))], index=index)
        return BacktestResult(equity, equity.pct_change().fillna(0), pd.DataFrame(index=index),
                              pd.DataFrame(index=index), [], 100.0, 1.0)

    zero_mean = result([-0.125, 0.125])
    flat = result([0.0, 0.0])
    empty = pd.Series([], dtype=float)
    assert sharpe(zero_mean) == pytest.approx(0.0, abs=1e-12)
    assert _returns_for_stats(zero_mean).std(ddof=1) > 0
    assert sharpe(flat) == 0.0 and _returns_for_stats(flat).std(ddof=1) == 0.0
    assert len(empty) == 0 and np.isnan(empty.std(ddof=1))
    # Equal public Sharpe scalars do not imply equal sample/variance validity.
    assert zero_mean.daily_returns.size == flat.daily_returns.size == 2


def test_q1_t05_native_guards_are_fail_closed_or_observable():
    from types import SimpleNamespace

    context = SimpleNamespace(data=baseline.market(), datetime_index=baseline.market().index)
    bt = baseline.endpoint(native="require")
    scorer = NativePreparedPublicWfoScorerV1(config=bt.config, target_mode="portfolio", wf_config=bt.config.walkforward_config)
    with pytest.raises(NativePreparedPublicWfoUnsupported, match="target_mode"):
        scorer.bind_walkforward_context(context)
    cfg = replace(bt.config.walkforward_config,
                  metadata={**bt.config.walkforward_config.metadata, "native_prepared_wfo": "auto"})
    fallback = NativePreparedPublicWfoScorerV1(config=bt.config, target_mode="portfolio", wf_config=cfg)
    fallback.bind_walkforward_context(context)
    assert fallback.metadata()["resolved_policy"] == "fallback"
    assert fallback.metadata()["reason"]
    bad_days = replace(bt.config.walkforward_config, scoring_trading_days=252)
    scorer = NativePreparedPublicWfoScorerV1(config=bt.config, target_mode="signal_notional", wf_config=bad_days)
    with pytest.raises(NativePreparedPublicWfoUnsupported, match="365"):
        scorer.bind_walkforward_context(context)
    with pytest.raises(NativePreparedPublicWfoUnsupported, match="contiguous"):
        NativePreparedPublicWfoScorerV1._window_bounds(context.datetime_index, context.datetime_index[[0, 2]])
    with pytest.raises(NotImplementedError, match="proxy"):
        baseline.endpoint("mode_2_sbb", "global", native="require")


def test_q1_t06_all_supported_mode_schedule_baselines(manifest):
    assert [(lane["mode"], lane["schedule"]) for lane in manifest["lanes"]] == list(baseline.ROUTES)
    for lane in manifest["lanes"]:
        assert lane["summary"]["n_folds"] == (1 if lane["mode"] == "mode_5_full_robust" else 2)
        assert len(lane["equity"]["values"]) == baseline.BUDGET["bars"]
        assert lane["account_contract"]["initial_capital"] == 20000.0
        assert lane["canonical_one_way_fee_rate"] == 0.0005
        assert len(lane["pools"]) == (2 if lane["schedule"] != "global" else 1)
        assert sum(len(pool["all_trials"]) for pool in lane["pools"]) == len(lane["pools"]) * 6


@pytest.mark.parametrize("mode,schedule", [
    (f"mode_{number}_{suffix}", schedule)
    for number, suffix in ((1, "decay"), (2, "sbb"), (3, "flat_minima"), (4, "is_only_robust"), (5, "full_robust"))
    for schedule in ("per_fold_decay", "per_fold_causal")
    if (f"mode_{number}_{suffix}", schedule) not in baseline.ROUTES
])
def test_q1_t06_unsupported_schedule_behavior_is_preserved(mode, schedule):
    with pytest.raises(NotImplementedError):
        WalkForwardConfig(optimization_mode=mode, optimization_schedule=schedule, optuna_trials=6)


def test_q1_t06_nested_mode1_without_inner_config_still_fails():
    with pytest.raises(ValueError, match="inner_split_frequency"):
        WalkForwardConfig(optimization_mode="mode_1_decay", optimization_schedule="per_fold_causal", optuna_trials=6)


def test_q1_t07_financial_sources_and_entry_state_preserved(source, manifest):
    captured = {name: baseline.digest(baseline.git("show", source["phase_entry_sha"] + ":" + name))
                for name in source["protected_sources"]}
    assert captured == source["protected_sources"] == manifest["source"]["protected_sources"]
    assert source["entry_unrelated_dirty"] == manifest["source"]["entry_unrelated_dirty"] == []
    changed = baseline.git("diff", "--name-only", baseline.RELEASE, source["phase_entry_sha"], "--", "src", "rust", "pyproject.toml", "uv.lock")
    assert changed == b""
    bad = deepcopy(source)
    path = "src/quantbt/walkforward.py"
    bad["protected_sources"][path] = "0" * 64
    with pytest.raises(ValueError, match="protected source changed"):
        baseline.validate_identity(bad, historical=True)


@pytest.mark.parametrize("tamper", ["budget", "pool", "routes", "payload", "resource"])
def test_q1_t08_manifest_verifier_rejects_false_evidence(manifest, tamper):
    baseline.verify_manifest(manifest, historical=True)
    bad = deepcopy(manifest)
    if tamper == "budget":
        bad["budget"]["economic_matured_origins"] = 2
    elif tamper == "pool":
        bad["lanes"][0]["pools"][0]["eligible_ids"] = []
    elif tamper == "routes":
        bad["lanes"].pop()
    elif tamper == "payload":
        bad["lanes"][0]["equity"]["values"] = []
    else:
        bad["timing"] = []
    with pytest.raises(ValueError):
        baseline.verify_manifest(bad, historical=True)


def test_q1_t08_real_baseline_budgets_no_fabricated_empirical_or_live_claim(manifest):
    measured = [row for row in manifest["timing"] if not row["warmup"]]
    assert len(measured) == baseline.BUDGET["timing_repeats"]
    assert len({row["equity_sha256"] for row in measured}) == 1
    assert all(row["wall_seconds"] > 0 and row["cpu_seconds"] > 0 and row["after"]["pss_mib"] > 0 for row in measured)
    assert manifest["maturity"]["matured_sealed_meta_origins"] == 0
    assert manifest["maturity"]["economic_status"] == "NOT_RUN_BUDGET"
    assert manifest["strategy"]["real_market"] is False
    assert manifest["status"]["owner_review"] == "PENDING"
    assert manifest["status"]["can_start_next_phase"] is False


@pytest.mark.parametrize("invalid", ["missing_group", "failure", "skipped"])
def test_q1_t08_receipt_requires_all_executed_groups(tmp_path, invalid):
    import xml.etree.ElementTree as ET

    root = ET.Element("testsuite")
    for number in range(1, 9):
        if invalid == "missing_group" and number == 8:
            continue
        item = ET.SubElement(root, "testcase", name=f"test_q1_t{number:02d}_receipt_fixture")
        if number == 8 and invalid in {"failure", "skipped"}:
            ET.SubElement(item, invalid)
    path = tmp_path / "invalid.xml"
    ET.ElementTree(root).write(path)
    with pytest.raises(ValueError):
        baseline.junit_checks(path)
