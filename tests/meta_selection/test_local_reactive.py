"""Actual native W3 windows, authoritative observations and causal metadata."""

from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from quantbt.optimization.meta_selection.common import MetaRecordError
from quantbt.optimization.meta_selection.config import MetaHistoryContext
from quantbt.optimization.meta_selection.history import MetaHistory
from quantbt.backends.reactive_wfo_support import ReactiveWfoRuntimeConfigV1
from tests.test_phase76_reactive_wfo import _bars, _endpoint, _config, _ReactiveFactory


def execute(mode=None, *, data=None, history=None, settings=None):
    data = _bars() if data is None else data
    cfg = replace(_config(mode="mode_4_is_only_robust"),
        optimization_schedule="per_fold_causal", optuna_trials=8, scoring_backend="endpoint",
        calendar_contract="exact_v2", strategy_lifecycle_policy="isolated_v1",
        meta_selection=dict(mode=mode, native_batch_policy="reference", min_matured_origins=1,
                            label_observer=True, **(settings or {})) if mode else None)
    runtime = _endpoint(data).prepare_reactive_walk_forward(data=data, strategy_factory=_ReactiveFactory(),
        walkforward_config=cfg, symbols=["BTC"])
    context = MetaHistoryContext(history or MetaHistory(), "w3-local-test", "BTC-linear", "1D", "w3-test")
    result = runtime.backtest(param_ranges={"direction": [-1., 1.]},
                              **({"meta_history": context} if mode else {}))
    return result, context, runtime


def test_w3_shadow_same_native_search_and_account_with_original_observations():
    old, _, _ = execute()
    new, history, runtime = execute("shadow")
    assert old.params_by_fold == new.params_by_fold
    np.testing.assert_array_equal(old.trial_table.objective, new.trial_table.objective)
    for a, b in zip(old.fold_results, new.fold_results):
        for field in ("equity", "returns", "positions", "fees", "funding"):
            np.testing.assert_array_equal(getattr(a.result, field), getattr(b.result, field))
    meta = new.metadata["meta_selection"]
    assert meta["account_authority"] == "existing_native_segmented_reset_flat"
    assert meta["observer_attempts"] > 0 and meta["observer_failures"] == 0
    assert len(meta["tasks"]) == len(new.folds)
    for task, record in zip(meta["tasks"], meta["records"]):
        assert len(task.candidates) >= 1
        assert task.decision_sealed_at < task.first_forward_action_at
        assert all(c.observation.verification == "original_result" for c in task.candidates)
        assert record["current_outer_oos_used_for_selection"] is False
        assert all(row["fresh_account"] and row["fresh_strategy"] for row in record["observer_lifecycle"])
    assert runtime._adapter is None and runtime._meta_boundary is None
    assert len(history.history.snapshot(family_id=meta["tasks"][0].family.family_id,
        authorized_corpora=history.authorized_corpora, outcome_origins=history.outcome_origins,
        research_exposures=history.research_exposures, information_as_of=new.folds[-1].test_end).revisions) > 0


def test_w3_active_metadata_actual_params_and_future_invariance():
    old, _, _ = execute("active")
    data = _bars()
    data.iloc[150:, data.columns.get_indexer(["open", "high", "low", "close"])] *= 1.3
    new, _, _ = execute("active", data=data)
    assert old.params_by_fold[0] == new.params_by_fold[0]
    meta = old.metadata["meta_selection"]
    for task, record in zip(meta["tasks"], meta["records"]):
        candidate = next(c for c in task.candidates if c.evaluation_id == record["selected_evaluation_id"])
        assert dict(candidate.effective_params) == old.params_by_fold[record["fold_id"]]
    assert old.metadata["continuous_equity_available"] is False


@pytest.mark.parametrize("change", ["mode", "schedule", "account", "process", "batch"])
def test_w3_unsupported_preflight(change):
    data = _bars()
    cfg = replace(_config(mode="mode_4_is_only_robust"), optimization_schedule="per_fold_causal",
        scoring_backend="endpoint", calendar_contract="exact_v2", strategy_lifecycle_policy="isolated_v1",
        optuna_trials=8, meta_selection=dict(mode="active", native_batch_policy="reference"))
    runtime = ReactiveWfoRuntimeConfigV1()
    if change == "mode":
        cfg = replace(cfg, optimization_mode="mode_5_full_robust", optimization_schedule="global",
                      candidate_selection_metric="full_robust")
    elif change == "schedule":
        cfg = replace(cfg, optimization_schedule="global")
    elif change == "account":
        cfg = replace(cfg, fold_account_policy="carry_position", fold_boundary_position_policy="carry")
    elif change == "process":
        runtime = replace(runtime, worker_mode="process")
    else:
        runtime = replace(runtime, optimizer_schedule="throughput_batch_v1")
    with pytest.raises((ValueError, NotImplementedError), match="META_"):
        _endpoint(data).prepare_reactive_walk_forward(data=data, strategy_factory=_ReactiveFactory(),
            walkforward_config=cfg, runtime_config=runtime, symbols=["BTC"])


def test_w3_missing_history_does_not_execute_strategy():
    data = _bars()
    cfg = replace(_config(mode="mode_4_is_only_robust"), optimization_schedule="per_fold_causal",
        scoring_backend="endpoint", calendar_contract="exact_v2", strategy_lifecycle_policy="isolated_v1",
        optuna_trials=8, meta_selection=dict(mode="active", native_batch_policy="reference"))
    runtime = _endpoint(data).prepare_reactive_walk_forward(data=data, strategy_factory=_ReactiveFactory(),
                                                          walkforward_config=cfg, symbols=["BTC"])
    with pytest.raises(MetaRecordError, match="HISTORY_INCOMPATIBLE"):
        runtime.backtest(param_ranges={"direction": [-1., 1.]})
    assert runtime._score_calls == 0
    assert runtime._meta_boundary is None and runtime._meta_runtime is None
    runtime.close()


@pytest.mark.parametrize("error", ["cancel", "failure"])
def test_w3_error_releases_original_witness_and_prepared_strategy(error, monkeypatch):
    from quantbt.optimization.meta_selection.reactive import ReactiveMetricBoundary
    from quantbt.core.runtime_governance import RuntimeCanceledError

    owners = []
    original = ReactiveMetricBoundary.execute

    def execute_then_fail(self, marker, **kwargs):
        owners.append(self)
        original(self, marker, **kwargs)
        if error == "cancel":
            self.runtime.cancel("test")
            raise RuntimeCanceledError("test canceled at candidate boundary")
        raise RuntimeError("intentional witness lane failure")

    monkeypatch.setattr(ReactiveMetricBoundary, "execute", execute_then_fail)
    with pytest.raises(RuntimeError, match="test|intentional"):
        execute("active")
    assert owners
    owner = owners[0]
    assert owner.runtime._adapter is None and owner.runtime._meta_boundary is None
    assert owner._meta_witness.closed and owner._meta_witness.metadata["retained_bytes"] == 0


def test_w3_no_variance_not_fabricated_valid(monkeypatch):
    from tests.test_phase76_reactive_wfo import _TaskStrategy

    monkeypatch.setattr(_TaskStrategy, "on_bar_close", lambda self, context, out: None)
    result, _, _ = execute("shadow")
    for task in result.metadata["meta_selection"]["tasks"]:
        assert all(c.observation.status.value == "NO_VARIANCE" for c in task.candidates)
        assert all(c.observation.raw_sharpe == 0. for c in task.candidates)


def test_original_scalar_score_and_witness_share_full_tape_native_pass():
    from tests.test_phase76_reactive_wfo import _TaskStrategy
    from types import SimpleNamespace

    data = _bars()
    endpoint = _endpoint(data)
    runner = endpoint.prepare_native_event_strategy(data=data, symbols=["BTC"])
    task = SimpleNamespace(fold_id=0, start_bar=0, end_bar=len(data))
    try:
        ordinary = runner.run_window(strategy=_TaskStrategy(task=task, direction=1.), start_bar=0, end_bar=len(data),
                                     report_level="minimal")
        witnessed = runner.run_window(strategy=_TaskStrategy(task=task, direction=1.), start_bar=0, end_bar=len(data),
            report_level="minimal", _metric_witness_trading_days=365)
        assert "same_pass_score" not in ordinary.metadata["reactive_numeric_observability"]
        payload = witnessed.metadata["reactive_numeric_observability"]["same_pass_score"]
        assert payload["score_metrics_present"] is True
        assert "score_sharpe" in payload
        for field in ("equity", "returns", "positions", "fees", "funding"):
            np.testing.assert_array_equal(getattr(ordinary, field), getattr(witnessed, field))
    finally:
        runner.backend.clear_prepared_caches()


def test_w3_supported_meta_actually_switches_the_applied_native_candidate():
    from quantbt.optimization.meta_selection.history import SealedTaskRevision
    from quantbt.optimization.meta_selection.panel import freeze_panel
    from quantbt.optimization.meta_selection.descriptors import DescriptorSchema
    from quantbt.optimization.meta_selection.records import CandidateForwardRecord

    cold, _, _ = execute("shadow")
    template = cold.metadata["meta_selection"]["tasks"][0]
    shift = pd.Timedelta(days=730)
    ids = {c.evaluation_id: "reviewed-" + c.evaluation_id for c in template.candidates}
    candidates = tuple(replace(c, evaluation_id=ids[c.evaluation_id], candidate_id="reviewed-" + c.candidate_id,
        resolved_at=c.resolved_at - shift, observation=replace(c.observation,
        window_start=c.observation.window_start - shift, window_end=c.observation.window_end - shift,
        input_frontier=c.observation.input_frontier - shift, verification="reviewed_import"))
        for c in template.candidates)
    fields = ("origin", "is_start", "is_end", "forward_start", "forward_end", "data_cutoff",
              "search_completed_at", "anchor_selected_at", "decision_sealed_at", "first_forward_action_at")
    task = replace(template, candidates=candidates, run_id="reviewed-w3-policy-fixture",
                   anchor_candidate_evaluation_id=ids[template.anchor_candidate_evaluation_id],
                   roles=tuple(replace(role, evaluation_id=ids[role.evaluation_id]) for role in template.roles),
                   **{key: getattr(template, key) - shift for key in fields})
    panel = freeze_panel(task, DescriptorSchema({"direction": [-1., 1.]}), sealed_at=task.decision_sealed_at)
    available = task.forward_end + pd.Timedelta(hours=1)
    outcomes = tuple(CandidateForwardRecord(task.task_id, c.evaluation_id,
        replace(c.observation, raw_sharpe=2., window_start=task.forward_start,
            window_end=task.forward_end, input_frontier=task.forward_end, verification="reviewed_import"),
        available, 3600) for c in candidates)
    history = MetaHistory()
    history.append(SealedTaskRevision(task, panel, outcomes, available, verification="reviewed_import"))
    result, _, _ = execute("active", history=history, settings=dict(lambda_reg=1e-5))
    record = result.metadata["meta_selection"]["records"][0]
    assert record["selected_evaluation_id"] != record["native_selected_evaluation_id"]
    current = result.metadata["meta_selection"]["tasks"][0]
    selected = next(c for c in current.candidates if c.evaluation_id == record["selected_evaluation_id"])
    assert dict(selected.effective_params) == result.params_by_fold[0] == result.fold_results[0].params
