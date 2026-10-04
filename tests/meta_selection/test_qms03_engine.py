"""Actual WFO/backtest integration, with no new financial metric calculator."""

from dataclasses import replace
import subprocess
import sys

import numpy as np
import pandas as pd
import pytest

from quantbt import QuantBTEndpoint
from quantbt.endpoint import _WalkForwardEndpointScorer
from quantbt.walkforward import WalkForwardEngine
from quantbt.optimization.meta_selection import MetaRecordError, OutcomeStatus
from quantbt.optimization.meta_selection.capture import ISPoolCapture
from quantbt.optimization.meta_selection.common import digest, wire
from quantbt.optimization.meta_selection.history import MetaHistory
from quantbt.optimization.meta_selection.observer import (
    PostDecisionObserver,
    ResultMetricAdapter,
    canonical_metric_contract,
    economics_identity,
    market_signature,
)
from quantbt.optimization.meta_selection.persistence import dumps_pending, loads_pending
from tools import qms01_baseline as baseline
from tools.qms03_history import financial_fixture, original_engine_run


def test_q3_t06_finite_zero_positive_variance_calendar_sample_matches_report():
    frame = baseline.market().iloc[[0, 5, 15]]
    endpoint = QuantBTEndpoint.signal_notional(
        initial_capital=20_000, alloc_per_trade=1000
    )
    result = endpoint.backtest(data=frame, signal=pd.Series(1.0, index=frame.index))
    # Reducer unit fixture, not additional engine-produced label evidence.
    result = replace(
        result, equity=pd.Series([20_000.0, 21_000.0, 19_950.0], index=frame.index)
    )
    report = result.full_report(trading_days=365, scope="full")
    observation = ResultMetricAdapter(canonical_metric_contract()).observe(
        result,
        expected_index=frame.index,
        economics_id=economics_identity(endpoint.config),
        input_signature="metric-reducer-unit",
        report=report,
    )
    assert observation.raw_sharpe == report["sharpe"] == 0.0
    assert observation.status == OutcomeStatus.VALID and observation.sample_count == 2
    assert observation.sample_std == pytest.approx(np.std([0.05, -0.05], ddof=1))


def test_q3_t07_quantity_constraints_part_of_actual_economics_evidence():
    frame = baseline.market().iloc[:20]
    first = QuantBTEndpoint.signal_notional(qty_step=0.001, fee_rate=0.0005)
    changed = QuantBTEndpoint.signal_notional(qty_step=1.0, fee_rate=0.0005)
    assert economics_identity(first.config) != economics_identity(changed.config)
    result = changed.backtest(data=frame, signal=pd.Series(1.0, index=frame.index))
    with pytest.raises(MetaRecordError, match="economics"):
        ResultMetricAdapter(canonical_metric_contract()).observe(
            result,
            expected_index=frame.index,
            economics_id=economics_identity(first.config),
            input_signature="x",
            execution_config=first.config,
        )


def test_q3_t08_omitted_public_route_does_not_import_meta_or_emit_new_work():
    source = """
import sys
from tools.qms01_baseline import endpoint, market
e = endpoint(retention="none")
r = e.backtest(data=market(), param_ranges={"window": (3, 31, 2)})
assert not any(n.startswith("quantbt.optimization.meta_selection") for n in sys.modules)
assert not any("meta" in k for k in r.metadata["walk_forward"])
"""
    subprocess.run(
        [sys.executable, "-c", source],
        cwd=baseline.ROOT,
        check=True,
        capture_output=True,
        text=True,
    )


@pytest.fixture(scope="module", params=[False, True], ids=["medoid", "centroid"])
def financial(request):
    evidence, revisions, result = financial_fixture(centroid=request.param)
    return evidence, revisions, result, request.param


def test_q3_t02_original_engine_labels_reconcile_and_centroid_has_own_is(financial):
    evidence, revisions, result, centroid = financial
    assert evidence["observer_failures"] == 0 and evidence["origin_count"] == 2
    assert evidence["observer_attempts"] == sum(len(r.panel.members) for r in revisions)
    for revision, row in zip(revisions, evidence["rows"], strict=True):
        assert revision.task.clock_mode == "historical_replay"
        assert revision.task.wall_generated_at > revision.task.forward_end
        assert row["auxiliary_is_evaluations"] == int(centroid)
        assert (revision.task.anchor.native_trial_id == -1) == centroid
        assert revision.task.anchor.observation.verification == "original_result"
        for label in revision.training_rows:
            candidate = next(
                c
                for c in revision.task.candidates
                if c.evaluation_id == label.candidate_evaluation_id
            )
            outcome = next(
                o
                for o in revision.outcomes
                if o.evaluation_id == label.candidate_evaluation_id
            )
            assert label.raw_is == candidate.observation.raw_sharpe
            assert label.raw_forward == outcome.observation.raw_sharpe
            assert label.q == pytest.approx(
                label.raw_forward - label.anchor_forward, abs=1e-12
            )
            assert label.y == pytest.approx(
                (label.raw_is - label.raw_forward)
                - (label.anchor_is - label.anchor_forward),
                abs=1e-12,
            )
            assert (
                label.anchor_evaluation_id
                == revision.task.anchor_candidate_evaluation_id
            )


def test_q3_t01_full_pool_retained_before_lossy_native_candidate_table(financial):
    evidence, revisions, result, centroid = financial
    full_count = sum(len(r.task.candidates) for r in revisions)
    assert full_count > len(result.candidate_table)
    for revision in revisions:
        assert len(revision.task.candidates) >= 5 + int(centroid)
        assert all(c.observation.sample_std > 0 for c in revision.task.candidates)
        assert not any(
            hasattr(c, "equity") or hasattr(c, "fills")
            for c in revision.task.candidates
        )


@pytest.mark.parametrize("centroid", [False, True])
def test_q3_t03_capture_does_not_change_native_selection_or_stitched_output(centroid):
    _, _, _, plain, _ = original_engine_run(capture=False, centroid=centroid)
    _, _, _, observed, capture = original_engine_run(capture=True, centroid=centroid)
    assert plain.params == observed.params and plain.best_trial == observed.best_trial
    assert plain.metadata["params_by_fold"] == observed.metadata["params_by_fold"]
    pd.testing.assert_series_equal(
        plain.oos_output, observed.oos_output, check_exact=True
    )
    pd.testing.assert_frame_equal(
        plain.trial_table, observed.trial_table, check_exact=True
    )
    pd.testing.assert_frame_equal(
        plain.candidate_table, observed.candidate_table, check_exact=True
    )
    assert all(
        p.selected_params_digest
        == digest(observed.metadata["params_by_fold"][p.fold_id])
        for p in capture.pools
    )


def test_q3_t03_actual_runner_future_suffix_mutation_preserves_first_pool_and_anchor():
    _, _, _, before, first = original_engine_run()
    _, _, _, after, changed = original_engine_run(mutate_future=True)
    assert wire(first.pools[0].candidates) == wire(changed.pools[0].candidates)
    assert first.pools[0].anchor_evaluation_id == changed.pools[0].anchor_evaluation_id
    assert before.metadata["params_by_fold"][0] == after.metadata["params_by_fold"][0]
    assert wire(first.pools[-1].candidates) != wire(changed.pools[-1].candidates)


def test_q3_t03_actual_panel_seals_before_engine_opens_forward_strategy_view(
    monkeypatch,
):
    original = WalkForwardEngine._call_strategy
    checked_folds = []

    def checked(engine, *, data, params, fold):
        if fold.test_index[0] > fold.train_index[-1]:
            observer = engine._is_pool_observer
            assert any(
                task.sampling_provenance["study_id"] == fold.fold_id
                and panel.sealed_at <= task.first_forward_action_at
                for task, panel in observer.sealed_tasks
            )
            checked_folds.append(fold.fold_id)
        return original(engine, data=data, params=params, fold=fold)

    monkeypatch.setattr(WalkForwardEngine, "_call_strategy", checked)
    _, _, _, result, capture = original_engine_run()
    assert checked_folds == [fold.fold_id for fold in result.folds]
    assert len(capture.sealed_tasks) == len(result.folds)


def test_q3_t03_actual_history_physical_order_and_future_labels_do_not_change_old_snapshot(
    financial,
):
    _, revisions, _, _ = financial
    earlier, later = revisions
    cutoff = earlier.revision_available_at + pd.Timedelta(seconds=1)
    snapshots = []
    for order in (revisions, list(reversed(revisions))):
        store = MetaHistory()
        for revision in order:
            store.append(revision)
        view = store.snapshot(
            family_id=earlier.task.family.family_id,
            authorized_corpora=(earlier.task.corpus_id,),
            outcome_origins=(earlier.task.outcome_origin,),
            research_exposures=(earlier.task.research_exposure,),
            information_as_of=cutoff,
        )
        assert view.revisions == (earlier,)
        snapshots.append(view.snapshot_id)
    assert snapshots[0] == snapshots[1]
    corrected = replace(
        later,
        outcomes=tuple(
            replace(o, observation=replace(o.observation, raw_sharpe=42))
            for o in later.outcomes
        ),
    )
    store = MetaHistory()
    store.append(earlier)
    store.append(corrected)
    view = store.snapshot(
        family_id=earlier.task.family.family_id,
        authorized_corpora=(earlier.task.corpus_id,),
        outcome_origins=(earlier.task.outcome_origin,),
        research_exposures=(earlier.task.research_exposure,),
        information_as_of=cutoff,
    )
    assert view.snapshot_id == snapshots[0]


def test_q3_t06_original_metric_zero_return_sample_has_no_variance_not_valid_zero():
    frame = baseline.market().iloc[:20]
    endpoint = QuantBTEndpoint.signal_notional(
        initial_capital=20_000,
        alloc_per_trade=1000,
        leverage=3,
        use_funding=False,
        fee_rate=0.0005,
    )
    result = endpoint.backtest(data=frame, signal=pd.Series(0.0, index=frame.index))
    adapter = ResultMetricAdapter(canonical_metric_contract())
    observation = adapter.observe(
        result,
        expected_index=frame.index,
        economics_id=economics_identity(endpoint.config),
        input_signature=market_signature(frame, frame.index),
    )
    assert observation.raw_sharpe == 0 and observation.sample_std == 0
    assert observation.status == OutcomeStatus.NO_VARIANCE
    with pytest.raises(MetaRecordError, match="original financial"):
        adapter.observe(
            object(), expected_index=frame.index, economics_id="x", input_signature="x"
        )


@pytest.mark.parametrize(
    "case,status",
    [
        ("short", OutcomeStatus.INCOMPLETE_WINDOW),
        ("liquidated", OutcomeStatus.CENSORED),
        ("few", OutcomeStatus.INSUFFICIENT_SAMPLE),
    ],
)
def test_q3_t06_actual_result_dispositions(case, status):
    frame = baseline.market().iloc[:20]
    endpoint = QuantBTEndpoint.signal_notional(
        initial_capital=20_000, alloc_per_trade=1000, use_funding=False
    )
    result = endpoint.backtest(data=frame, signal=pd.Series(1.0, index=frame.index))
    expected = frame.index
    if case == "short":
        result = replace(
            result,
            equity=result.equity.iloc[:-1],
            returns=result.returns.iloc[:-1],
            positions=result.positions.iloc[:-1],
            closes=result.closes.iloc[:-1],
        )
    elif case == "liquidated":
        result = replace(result, liquidated=True)
    else:
        result = replace(
            result,
            equity=result.equity.iloc[:1],
            returns=result.returns.iloc[:1],
            positions=result.positions.iloc[:1],
            closes=result.closes.iloc[:1],
        )
        expected = frame.index[:1]
    observation = ResultMetricAdapter(canonical_metric_contract()).observe(
        result,
        expected_index=expected,
        economics_id=economics_identity(endpoint.config),
        input_signature=market_signature(frame, expected),
    )
    assert observation.status == status


@pytest.mark.parametrize(
    "metadata",
    [
        {},
        {"use_scalar_trial_scoring": False},
        {"native_prepared_wfo": "off"},
        {"use_scalar_trial_scoring": False, "native_prepared_wfo": "require"},
    ],
)
def test_q3_t06_unsupported_scalar_support_rejected_before_search(metadata):
    endpoint = baseline.endpoint()
    config = replace(endpoint.config.walkforward_config, metadata=metadata)
    with pytest.raises(NotImplementedError, match="original-result"):
        _WalkForwardEndpointScorer(
            endpoint.config,
            "signal_notional",
            wf_config=config,
            meta_metric_support=True,
        )


@pytest.mark.parametrize(
    "mode,schedule",
    [
        ("mode_1_decay", "global"),
        ("mode_4_is_only_robust", "global"),
        ("mode_5_full_robust", "global"),
    ],
)
def test_q3_t06_capture_scope_rejected_before_search(mode, schedule):
    endpoint = baseline.endpoint(mode, schedule)
    capture = ISPoolCapture(resolved_at=lambda fold: fold.train_index[-1])
    with pytest.raises(MetaRecordError, match="Mode 4"):
        WalkForwardEngine(
            endpoint.config.strategy_class,
            endpoint.config.walkforward_config,
            scorer=lambda **kwargs: {},
            is_pool_observer=capture,
        )


def test_q3_t07_original_economics_mismatch_not_laundered_by_caller_contract():
    frame = baseline.market().iloc[:20]
    first = QuantBTEndpoint.signal_notional(
        initial_capital=20_000, alloc_per_trade=1000, fee_rate=0.0005
    )
    changed = QuantBTEndpoint.signal_notional(
        initial_capital=20_000, alloc_per_trade=1000, fee_rate=0.002
    )
    result = changed.backtest(data=frame, signal=pd.Series(1.0, index=frame.index))
    adapter = ResultMetricAdapter(canonical_metric_contract())
    with pytest.raises(MetaRecordError, match="economics"):
        adapter.observe(
            result,
            expected_index=frame.index,
            economics_id=economics_identity(first.config),
            input_signature="x",
        )
    with pytest.raises(MetaRecordError, match="metric contract"):
        ResultMetricAdapter(replace(canonical_metric_contract(), risk_free=0.01))


def test_q3_t07_same_legacy_and_one_way_cost_contract_and_funding_sample_signatures():
    frame = baseline.market().iloc[:20]
    first = QuantBTEndpoint.signal_notional(fee=0.001)
    same = QuantBTEndpoint.signal_notional(fee_rate=0.0005)
    assert economics_identity(first.config) == economics_identity(same.config)
    funded = replace(same.config, funding_rate=pd.Series(0.0001, index=frame.index))
    changed = replace(funded, funding_rate=funded.funding_rate * 2)
    assert economics_identity(funded) == economics_identity(changed)
    assert market_signature(frame, frame.index, config=funded) != market_signature(
        frame, frame.index, config=changed
    )
    changed_volume = frame.copy()
    changed_volume.iloc[0, changed_volume.columns.get_loc("volume")] += 1
    assert market_signature(frame, frame.index) != market_signature(
        changed_volume, frame.index
    )


def test_q3_t08_pending_portable_maturity_and_observer_failed_attempt_retained(
    financial,
):
    _, revisions, _, _ = financial
    revision = revisions[0]
    pending = replace(
        revision.outcomes[0],
        label_available_at=None,
        observation=replace(
            revision.outcomes[0].observation,
            status=OutcomeStatus.PENDING,
            raw_sharpe=None,
            sample_std=None,
            sample_count=0,
        ),
    )
    assert wire(loads_pending(dumps_pending(pending))) == wire(pending)
    adapter = ResultMetricAdapter(canonical_metric_contract())
    observer = PostDecisionObserver(adapter)

    def failed(candidate):
        raise RuntimeError("existing evaluator could not finish")

    outcomes = observer.observe(
        task=revision.task,
        panel=revision.panel,
        evaluate=failed,
        expected_index=pd.date_range(
            revision.task.forward_start, revision.task.forward_end, freq="D"
        ),
        label_available_at=revision.revision_available_at,
        reporting_lag_seconds=1,
    )
    sealed = replace(revision, outcomes=outcomes)
    assert observer.attempts == observer.failures == len(revision.panel.members)
    assert all(o.observation.status == OutcomeStatus.OUTCOME_FAILED for o in outcomes)
    assert not sealed.training_rows
    with pytest.raises(MetaRecordError):
        loads_pending(dumps_pending(pending).replace("PENDING", "VALID"))


def test_q3_t08_phase_scope_does_not_modify_execution_financial_or_sampler_sources():
    names = (
        baseline.git(
            "ls-tree",
            "-r",
            "--name-only",
            "3ce42bf",
            "src",
            "rust",
            "pyproject.toml",
            "uv.lock",
            "poetry.lock",
            baseline.GUIDE,
        )
        .decode()
        .splitlines()
    )
    allowed = {"src/quantbt/endpoint.py", "src/quantbt/walkforward.py"}
    for name in names:
        if name not in allowed:
            if name == "rust/native_event/src/lib.rs":
                # QMS-04 adds only registered numeric exports, not execution math.
                current = (baseline.ROOT / name).read_bytes()
                current = current.replace(b"mod qms_numeric;\n", b"").replace(
                    b"    qms_numeric::register(module)?;\n", b""
                )
                assert baseline.git("show", "3ce42bf:" + name) == current, name
                continue
            assert (
                baseline.git("show", "3ce42bf:" + name)
                == (baseline.ROOT / name).read_bytes()
            ), name
