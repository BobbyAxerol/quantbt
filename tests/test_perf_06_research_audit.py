"""PERF-06 columnar research-audit, retention, and compatibility contracts."""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from quantbt import QuantBTEndpoint
from quantbt.core.orders import Fill
from quantbt.core.research_audit import (
    ColumnarResearchTableV1,
    ResearchAuditArtifactV1,
    ResearchAuditBudgetError,
    ResearchAuditError,
    ResearchAuditSchemaError,
    ResearchAuditWriteError,
    ResearchAuditWriterV1,
    ResearchRetentionPlanV1,
    build_walkforward_research_audit,
)
from quantbt.core.schema import OrderSide
from quantbt.walkforward import WalkForwardConfig, WalkForwardEngine, WalkForwardTrialRecord


def _bars(*, periods: int = 420) -> pd.DataFrame:
    index = pd.date_range("2020-01-01", periods=periods, freq="1D", tz="UTC")
    phase = np.arange(periods, dtype=np.float64)
    close = 100.0 + 0.04 * phase + np.sin(phase / 7.0)
    return pd.DataFrame(
        {
            "open": close - 0.1,
            "high": close + 0.5,
            "low": close - 0.5,
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
    return pd.Series(signal, index=test_index, dtype=float)


class _TerminalScorer:
    """Small deterministic endpoint scorer with real fold metric components."""

    def score_batch(self, tasks):
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


def _config(
    *,
    research_retention: str = "none",
    financial_retention: str = "score",
    chunk_rows: int = 2,
) -> WalkForwardConfig:
    return WalkForwardConfig(
        split_mode="2020-07-01",
        split_frequency="quarterly",
        window_mode="rolling",
        train_window="120D",
        min_train_bars=30,
        min_test_bars=20,
        target_mode="signal_notional",
        optimization_mode="mode_1_decay",
        optimization_schedule="global",
        optuna_trials=4,
        optuna_early_stopping=None,
        random_seed=17,
        top_is_fraction=1.0,
        flat_eps=1.0,
        flat_min_samples=1,
        candidate_selection_metric="robust_decay",
        scoring_backend="endpoint",
        scoring_trading_days=365,
        min_trades_per_year=None,
        trade_penalty_factor=None,
        metadata={
            "compact_trial_ledger": True,
            "research_retention": research_retention,
            "financial_retention": financial_retention,
            "research_audit_chunk_rows": chunk_rows,
        },
    )


def _run_engine(**kwargs):
    return WalkForwardEngine(strategy=_strategy, config=_config(**kwargs), scorer=_TerminalScorer()).run(
        _bars(),
        param_ranges={"direction": [-1.0, 1.0]},
    )


def _record(trial_id: int, params: dict[str, object], *, pruned: bool = False) -> WalkForwardTrialRecord:
    return WalkForwardTrialRecord(
        trial_id=trial_id,
        params=dict(params),
        objective=1.25 - trial_id * 0.1,
        mean_is_sharpe=1.5,
        mean_oos_sharpe=0.9,
        mean_decay=0.6,
        std_decay=0.1,
        fold_metrics=[
            {
                "fold_id": 0,
                "train_start": pd.Timestamp("2020-01-01", tz="UTC"),
                "train_end": pd.Timestamp("2020-03-01", tz="UTC"),
                "test_start": pd.Timestamp("2020-03-02", tz="UTC"),
                "test_end": pd.Timestamp("2020-04-01", tz="UTC"),
                "is_sharpe": 1.5,
                "oos_sharpe": 0.9,
                "is_trade_count": 12.0,
                "oos_trade_count": 6.0,
            }
        ],
        pruned=pruned,
        selection_metadata={"stage": "is_search", "study_id": 7},
    )


def _artifact(
    *,
    plan: ResearchRetentionPlanV1,
    param_ranges: dict[str, object] | None = None,
    trial_records: list[WalkForwardTrialRecord] | None = None,
    candidate_records: list[WalkForwardTrialRecord] | None = None,
) -> ResearchAuditArtifactV1:
    trials = trial_records or [_record(0, {"mode": "fast", "window": 12})]
    candidates = candidate_records if candidate_records is not None else [trials[0]]
    fold = SimpleNamespace(
        fold_id=0,
        train_start=pd.Timestamp("2020-01-01", tz="UTC"),
        train_end=pd.Timestamp("2020-03-01", tz="UTC"),
        test_start=pd.Timestamp("2020-03-02", tz="UTC"),
        test_end=pd.Timestamp("2020-04-01", tz="UTC"),
        account_policy="carry_position",
    )
    config = SimpleNamespace(metadata=plan.metadata())
    return build_walkforward_research_audit(
        config=config,
        result_metadata={
            "engine": "tests-perf06",
            "data_hash": "data-v1",
            "config_hash": "config-v1",
            "strategy_fingerprint": "strategy-v1",
            "random_seed": 17,
            "optimization_mode": "mode_1_decay",
            "optimization_schedule": "global",
            "target_mode": "signal_notional",
            "fold_account_policy": "carry_position",
        },
        param_ranges=param_ranges or {"mode": ["fast", "slow"], "window": (8, 24, 2)},
        trial_records=trials,
        candidate_records=candidates,
        selected_record=candidates[0],
        folds=[fold],
        params_by_fold={0: dict(candidates[0].params)},
        result_kind="tests",
    )


def test_perf06_default_retention_preserves_legacy_public_wfo_without_a_sidecar():
    result = _run_engine()

    assert result.metadata["research_audit"] is None
    summary = result.metadata["research_audit_summary"]
    assert summary["enabled"] is False
    assert summary["retention"]["research_retention"] == "none"
    assert not result.trial_table.empty
    assert "columnar_research_audit" not in result.metadata["required_computation_plan"]["output_sinks"]


def test_perf06_computation_plan_declares_the_sidecar_for_either_opt_in_axis():
    full = _run_engine(research_retention="full_trial_ledger")
    assert "columnar_research_audit" in full.metadata["required_computation_plan"]["output_sinks"]

    compact = _run_engine(financial_retention="compact")
    sinks = compact.metadata["required_computation_plan"]["output_sinks"]
    assert "columnar_research_audit" in sinks
    assert "selected_financial_compact" in sinks


def test_perf06_full_trial_ledger_keeps_full_fold_metrics_while_public_table_stays_compact():
    result = _run_engine(research_retention="full_trial_ledger")
    audit = result.metadata["research_audit"]
    assert audit is not None
    assert audit.metadata()["writer"]["memory_result_complete"] is True

    public = result.trial_table.reset_index(drop=True)
    exports = audit.legacy_exports()
    legacy = exports["trial_table"].reset_index(drop=True)
    assert len(legacy) == len(public)
    assert legacy["trial_id"].tolist() == public["trial_id"].tolist()
    assert legacy["params"].tolist() == public["params"].tolist()
    np.testing.assert_allclose(legacy["objective"], public["objective"], equal_nan=True)

    full = exports["trial_table_full"]
    assert "fold_metrics" in full
    assert any(bool(value) for value in full["fold_metrics"])
    evaluations = audit.to_pandas("evaluations")
    assert not evaluations.empty
    assert set(evaluations["status"]) <= {"complete", "pruned"}
    assert audit.search_space_manifest["space_completeness"] == "declared"
    assert audit.run_manifest["instrument_manifest_id"] == audit.instrument_manifest["instrument_manifest_id"]
    assert audit.instrument_manifest["target_mode"] == "signal_notional"
    with pytest.raises(TypeError):
        audit.run_manifest["engine"] = "mutated"  # type: ignore[index]
    with pytest.raises(TypeError):
        audit.instrument_manifest["target_mode"] = "mutated"  # type: ignore[index]


def test_perf06_per_fold_full_ledger_keeps_distinct_study_and_fold_identities_before_compaction():
    source = _config(research_retention="full_trial_ledger")
    config = WalkForwardConfig(
        **{
            **source.__dict__,
            "optimization_schedule": "per_fold_decay",
            "optuna_trials": 2,
        }
    )
    result = WalkForwardEngine(strategy=_strategy, config=config, scorer=_TerminalScorer()).run(
        _bars(periods=520),
        param_ranges={"direction": [-1.0, 1.0]},
    )
    audit = result.metadata["research_audit"]
    trials = audit.to_pandas("trials")
    assert not trials.empty
    metadata = list(trials["selection_metadata"])
    scheduled_folds = {int(item["schedule_fold_id"]) for item in metadata}
    assert scheduled_folds == {int(fold.fold_id) for fold in result.folds}
    assert {int(item["study_id"]) for item in metadata} == scheduled_folds
    assert any(bool(row) for row in audit.legacy_exports()["trial_table_full"]["fold_metrics"])


def test_perf06_selected_only_and_none_keep_truthful_scope_without_inventing_trials():
    selected_only = _artifact(
        plan=ResearchRetentionPlanV1(research_retention="selected_only", chunk_rows=1),
        trial_records=[_record(0, {"mode": "fast", "window": 12}), _record(1, {"mode": "slow", "window": 18})],
        candidate_records=[_record(1, {"mode": "slow", "window": 18})],
    )
    assert len(selected_only.to_pandas("trials")) == 1
    assert len(selected_only.to_pandas("analysis")) == 1
    assert selected_only.to_pandas("trials").iloc[0]["trial_id"] == 1

    none = _artifact(plan=ResearchRetentionPlanV1(research_retention="none"))
    assert none.to_pandas("trials").empty
    assert none.to_pandas("analysis").empty
    assert none.metadata()["space_completeness"] == "declared"


def test_perf06_dynamic_conditional_space_is_observed_only_and_keeps_category_order():
    trials = [
        _record(0, {"branch": "atr", "atr_length": 14}),
        _record(1, {"branch": "volume", "volume_length": 28}),
    ]
    audit = _artifact(
        plan=ResearchRetentionPlanV1(research_retention="full_trial_ledger"),
        param_ranges={"branch": ["atr", "volume"]},
        trial_records=trials,
        candidate_records=[trials[0]],
    )
    manifest = audit.search_space_manifest
    assert manifest["space_completeness"] == "observed_only"
    assert tuple(manifest["declared_parameters"]["branch"]["category_order"]) == ("atr", "volume")
    assert set(manifest["observed_parameter_names"]) == {"branch", "atr_length", "volume_length"}


def test_perf06_columnar_codec_is_immutable_exact_and_never_uses_repr_identity():
    timestamp = pd.Timestamp("2024-01-01 12:34:56.123456789", tz="UTC")
    value = np.nextafter(1.0, 2.0)
    records = [
        {
            "category": "beta",
            "timestamp": timestamp,
            "float": value,
            "payload": {"b": 2, "a": (1, range(2, 8, 2))},
        },
        {
            "category": "alpha",
            "timestamp": timestamp,
            "float": np.nan,
            "payload": {"a": (1, range(2, 8, 2)), "b": 2},
        },
    ]
    table = ColumnarResearchTableV1.from_records(table_name="records", chunk_id="records:0", records=records)
    assert table.dictionary_columns["category"][1] == ("beta", "alpha")
    assert table.primitive_columns["float"].flags.writeable is False
    with pytest.raises(ValueError):
        table.primitive_columns["float"][0] = 0.0

    restored = table.to_records()
    assert restored[0]["timestamp"] == timestamp
    assert restored[0]["float"] == value
    assert np.isnan(restored[1]["float"])
    assert restored[0]["payload"] == restored[1]["payload"]

    reordered = ColumnarResearchTableV1.from_records(
        table_name="records",
        chunk_id="records:1",
        records=[{"payload": {"a": 1, "b": 2}}],
    )
    canonical = ColumnarResearchTableV1.from_records(
        table_name="records",
        chunk_id="records:2",
        records=[{"payload": {"b": 2, "a": 1}}],
    )
    assert reordered.logical_digest == canonical.logical_digest

    class _Unsupported:
        pass

    with pytest.raises(ResearchAuditSchemaError, match="unsupported research-audit value type"):
        ColumnarResearchTableV1.from_records(
            table_name="bad", chunk_id="bad:0", records=[{"value": _Unsupported()}]
        )


def test_perf06_writer_is_bounded_idempotent_and_reports_fault_or_cancel_prefixes():
    plan = ResearchRetentionPlanV1(research_retention="full_trial_ledger", chunk_rows=1, max_retained_chunks=1)
    first = ColumnarResearchTableV1.from_records(
        table_name="trials", chunk_id="trials:00000000", records=[{"trial_id": 0}]
    )
    writer = ResearchAuditWriterV1(plan=plan)
    writer.append_chunk(first)
    writer.append_chunk(first)
    assert writer.metadata()["idempotent_chunk_retries"] == 1
    with pytest.raises(ResearchAuditBudgetError, match="max_retained_chunks"):
        writer.append_chunk(
            ColumnarResearchTableV1.from_records(
                table_name="trials", chunk_id="trials:00000001", records=[{"trial_id": 1}]
            )
        )
    assert writer.metadata()["writer_state"] == "failed"

    conflict = ResearchAuditWriterV1(plan=ResearchRetentionPlanV1(research_retention="full_trial_ledger"))
    conflict.append_chunk(first)
    with pytest.raises(ResearchAuditWriteError, match="conflicting duplicate"):
        conflict.append_chunk(
            ColumnarResearchTableV1.from_records(
                table_name="trials", chunk_id="trials:00000000", records=[{"trial_id": 99}]
            )
        )
    assert conflict.metadata()["failure"].startswith("conflicting_duplicate_chunk")

    failed_export = ResearchAuditWriterV1(
        plan=ResearchRetentionPlanV1(research_retention="full_trial_ledger"),
        export_hook=lambda *_args: (_ for _ in ()).throw(OSError("simulated disk full")),
    )
    with pytest.raises(ResearchAuditWriteError, match="export failed"):
        failed_export.append_chunk(first)
    assert failed_export.metadata()["failure"] == "export_hook_failed:OSError"
    assert failed_export.metadata()["crash_durable"] == "not_provided"

    canceled = ResearchAuditWriterV1(plan=ResearchRetentionPlanV1(research_retention="full_trial_ledger"))
    canceled.append_chunk(first)
    canceled.cancel(missing_range={"from_trial_id": 1, "to_trial_id": 4}, reason="requested")
    assert canceled.metadata()["writer_state"] == "canceled"
    assert canceled.metadata()["table_rows"] == {"trials": 1}
    assert canceled.metadata()["missing_range"] == {"from_trial_id": 1, "to_trial_id": 4}
    with pytest.raises(ResearchAuditWriteError, match="state='canceled'"):
        canceled.append_chunk(
            ColumnarResearchTableV1.from_records(
                table_name="trials", chunk_id="trials:00000001", records=[{"trial_id": 1}]
            )
        )


def test_perf06_financial_axes_retain_original_path_and_audit_records_or_fail_closed():
    index = pd.date_range("2024-01-01", periods=3, freq="1h", tz="UTC")
    result = SimpleNamespace(
        equity=pd.Series([100.0, 101.5, 103.0], index=index, name="equity"),
        returns=pd.Series([0.0, 0.015, 0.014778], index=index, name="returns"),
        fees=pd.Series([0.0, 0.1, 0.0], index=index, name="fees"),
        funding=pd.Series([0.0, -0.01, 0.0], index=index, name="funding"),
        fills=(
            Fill(timestamp=index[1], symbol="BTC", side=OrderSide.BUY, qty=1.0, price=100.0, fee=0.1),
        ),
        orders=(),
        trades=(),
        diagnostics=pd.DataFrame({"event": ["fill"]}, index=index[:1]),
        margin=pd.DataFrame({"initial_margin": [0.0, 10.0, 10.0]}, index=index),
        positions=pd.DataFrame({"BTC": [0.0, 1.0, 1.0]}, index=index),
        metadata={},
    )
    audit = _artifact(plan=ResearchRetentionPlanV1(research_retention="none", financial_retention="audit"))
    audit.finalize_financial(result)
    summary = audit.metadata()["financial"]
    assert summary["financial_completion"] == "audit_complete_selected_final_execution"
    assert summary["original_fill_count"] == 1
    assert len(audit.to_pandas("financial_path")) == len(index)
    assert audit.to_pandas("financial_path").iloc[1]["timestamp"] == index[1]
    assert len(audit.to_pandas("financial_fills")) == 1

    incomplete = SimpleNamespace(
        equity=pd.Series([100.0, 99.0], index=index[:2]),
        returns=pd.Series([0.0, -0.01], index=index[:2]),
        fees=pd.Series([0.0, 0.1], index=index[:2]),
        funding=pd.Series([0.0, 0.0], index=index[:2]),
        fills=(),
        positions=pd.DataFrame({"BTC": [0.0, 1.0]}, index=index[:2]),
        metadata={},
    )
    incomplete_audit = _artifact(
        plan=ResearchRetentionPlanV1(research_retention="none", financial_retention="audit")
    )
    with pytest.raises(ResearchAuditError, match="empty generic fills field"):
        incomplete_audit.finalize_financial(incomplete)
    assert len(audit.to_pandas("financial_positions")) == len(index)

    missing_original = _artifact(plan=ResearchRetentionPlanV1(research_retention="none", financial_retention="audit"))
    with pytest.raises(ResearchAuditError, match="requires original selected-final fill/audit output"):
        missing_original.finalize_financial(
            SimpleNamespace(equity=result.equity, returns=result.returns, metadata={})
        )


def test_perf06_endpoint_fails_closed_when_target_execution_has_no_original_fill_ledger():
    data = _bars(periods=400)

    endpoint = QuantBTEndpoint.walk_forward(
        strategy_class=_strategy,
        split_mode="2020-07-01",
        split_frequency="quarterly",
        window_mode="rolling",
        train_window="120D",
        target_mode="signal_notional",
        optimization_mode="mode_1_decay",
        optimization_config={
            "candidate_selection_metric": "robust_decay",
            "top_is_fraction": 1.0,
            "scoring_backend": "endpoint",
            "min_trades_per_year": None,
            "trade_penalty_factor": None,
            "research_retention": "selected_only",
            "financial_retention": "audit",
        },
        optuna_trials=2,
        random_seed=17,
        initial_capital=20_000.0,
        alloc_per_trade=1_000.0,
        fee_rate=0.0002,
    )
    with pytest.raises(ResearchAuditError, match="requires original selected-final fill/audit output"):
        endpoint.backtest(data=data, param_ranges={"direction": [-1.0, 1.0]})


def test_perf06_endpoint_exposes_opt_in_compact_financial_audit_without_changing_public_result():
    data = _bars()
    endpoint = QuantBTEndpoint.walk_forward(
        strategy_class=_strategy,
        split_mode="2020-07-01",
        split_frequency="quarterly",
        window_mode="rolling",
        train_window="120D",
        target_mode="signal_notional",
        optimization_mode="mode_1_decay",
        optimization_config={
            "top_is_fraction": 1.0,
            "candidate_selection_metric": "robust_decay",
            "scoring_backend": "endpoint",
            "min_trades_per_year": None,
            "trade_penalty_factor": None,
            "research_retention": "full_trial_ledger",
            "financial_retention": "compact",
            "research_audit_chunk_rows": 2,
        },
        optuna_trials=2,
        random_seed=19,
        initial_capital=20_000.0,
        leverage=2.0,
        alloc_per_trade=1_000.0,
        fee_rate=0.0002,
        slippage=0.0,
    )
    result = endpoint.backtest(data=data, param_ranges={"direction": [-1.0, 1.0]})
    audit = endpoint.research_audit
    assert audit is result.metadata["walk_forward"]["research_audit"]
    assert audit.metadata()["financial"]["financial_completion"] == "compact_complete_selected_final_path"
    assert len(audit.to_pandas("financial_path")) == len(result.equity)
    exports = audit.legacy_exports()
    assert len(exports["trial_table"]) == len(result.metadata["walk_forward"]["trial_table"])
