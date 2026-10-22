"""Active default-maturity checks through real public financial owners."""

from dataclasses import replace
import json
import random

import numpy as np
import optuna
import pandas as pd
import pytest

from quantbt.optimization.meta_selection.records import OutcomeStatus
from tests.meta_selection.pre_e06_02_support import (
    CUTOFFS, ROUTES, account_equal, clone_history, current, decision_equal,
    independent, rebuild_final, policy_equal, replay_clock, run, tape,
)

optuna.logging.set_verbosity(optuna.logging.WARNING)


@pytest.fixture(scope="module", params=ROUTES)
def history_run(request):
    return run(request.param)


@pytest.fixture(scope="module")
def matured(history_run):
    out = {}
    for cutoff in CUTOFFS:
        out[cutoff] = run(history_run.route, "active", data=current(history_run.data, cutoff),
            start=str((cutoff+pd.Timedelta(days=1)).date()),
            history=clone_history(history_run.context.history))
    return out


def test_pre02_matured_actual_fit_rank_and_applied_params(history_run, matured, record_property):
    rows = []
    for cutoff, value in matured.items():
        m = value.meta
        snapshot, task, record = m["snapshots"][0], m["tasks"][0], m["records"][0]
        assert task.data_cutoff == cutoff
        assert snapshot.origin_count >= 12, (value.route, cutoff, snapshot.origin_count)
        assert len({r.task.origin for r in snapshot.revisions if r.training_rows}) == snapshot.origin_count
        assert record["final_selection_reason"] == "META_MODEL_PROPOSAL", (value.route, record)
        assert m["models"] and record["proposal"].predictions
        assert record["past_matured_forward_used_for_selection"]
        assert not record["current_outer_oos_used_for_selection"]
        assert task.decision_sealed_at < task.first_forward_action_at
        assert record["fit_completed_at"] is not None
        candidate = next(c for c in task.candidates if c.evaluation_id == record["selected_evaluation_id"])
        result = value.result
        params = result.params_by_fold if value.route == "reactive_reset" else result.metadata["walk_forward"]["params_by_fold"]
        assert params[0] == dict(candidate.effective_params) == record["selected_params"]
        rows.append(dict(route=value.route, cutoff=str(cutoff), matured_origins=snapshot.origin_count,
                         training_rows=len(snapshot.training_rows), predictions=len(record["proposal"].predictions),
                         selected_params=record["selected_params"], model_status=record["final_selection_reason"],
                         changed_from_anchor=record["selected_evaluation_id"] != record["native_selected_evaluation_id"]))
    record_property("pre02_matured", json.dumps(rows, sort_keys=True))


@pytest.mark.parametrize("cutoff", CUTOFFS)
def test_pre02_m01_future_ohlcv_funding_real_active_runner(history_run, matured, cutoff):
    value = matured[cutoff]
    data = current(history_run.data, cutoff)
    for f in data.values() if isinstance(data, dict) else (data,):
        mask = f.index > cutoff
        f.loc[mask, ["open", "high", "low", "close", "volume"]] *= 1.3
        if history_run.route != "delivery_arbitrage" or f.funding_rate.ne(0).any():
            f.loc[mask, "funding_rate"] *= 7
    altered = run(value.route, "active", data=data, start=str((cutoff+pd.Timedelta(days=1)).date()),
                  history=clone_history(history_run.context.history))
    decision_equal(value, altered)
    # The real forward observer saw the mutation; profit need not change under
    # price-scale-invariant sizing, flat signals or rejected orders.
    def forward_signatures(v):
        task = v.meta["tasks"][0]
        revision = next(r for r in v.context.history._revisions.values() if r.task.task_id == task.task_id)
        return {o.evaluation_id: o.observation.input_signature for o in revision.outcomes}
    assert forward_signatures(value) != forward_signatures(altered)


@pytest.mark.parametrize("cutoff", CUTOFFS)
def test_pre02_original_raw_is_forward_and_final_account(history_run, matured, cutoff):
    value = matured[cutoff]
    task = value.meta["tasks"][0]
    revision = next(r for r in value.context.history._revisions.values() if r.task.task_id == task.task_id)
    for outcome in revision.outcomes:
        candidate = next(c for c in task.candidates if c.evaluation_id == outcome.evaluation_id)
        for forward, observation in ((False, candidate.observation), (True, outcome.observation)):
            original = independent(value, task, candidate, forward=forward)
            report = original.full_report(scope="full", trading_days=365)
            assert observation.raw_sharpe == pytest.approx(report["sharpe"], rel=1e-12, abs=1e-12)
            assert observation.activity_count == report["num_trades"]
            assert observation.verification == "original_result"
            from quantbt.metrics.performance import _array_returns_for_stats
            sample = _array_returns_for_stats(original.equity.index,
                original.equity.to_numpy(dtype=float), original.returns.to_numpy(dtype=float))
            assert observation.sample_count == len(sample)
            assert observation.sample_std == pytest.approx(float(np.std(sample, ddof=1)), rel=1e-12, abs=1e-12)
            status = OutcomeStatus.CENSORED if original.liquidated else (
                OutcomeStatus.NO_VARIANCE if np.std(sample, ddof=1) <= 0 else OutcomeStatus.VALID)
            assert observation.status == status
        assert outcome.label_available_at >= task.forward_end+pd.Timedelta(days=1)
    actual = value.result.fold_results[0].result if value.route == "reactive_reset" else value.result
    original = rebuild_final(value)
    original = original[0] if value.route == "reactive_reset" else original
    account_equal(actual, original)


def test_pre02_full_multifold_continuous_original_account(history_run):
    original = rebuild_final(history_run)
    if history_run.route == "reactive_reset":
        for fold, rebuilt in zip(history_run.result.fold_results, original, strict=True):
            account_equal(fold.result, rebuilt)
    else:
        account_equal(history_run.result, original)


def test_pre02_off_shadow_exact_search_rng_and_original_account(history_run):
    cutoff = CUTOFFS[0]
    data = current(history_run.data, cutoff)
    start = str((cutoff+pd.Timedelta(days=1)).date())
    random.seed(81)
    np.random.seed(82)
    a = run(history_run.route, "off", data=data, start=start)
    state = random.getstate(), np.random.get_state()
    b = run(history_run.route, "shadow", data=data, start=start,
            history=clone_history(history_run.context.history))
    assert random.getstate() == state[0]
    assert np.array_equal(np.random.get_state()[1], state[1][1])
    if history_run.route == "reactive_reset":
        assert a.result.params_by_fold == b.result.params_by_fold
        pd.testing.assert_frame_equal(a.result.trial_table, b.result.trial_table)
        account_equal(a.result.fold_results[0].result, b.result.fold_results[0].result)
    else:
        x, y = (v.result.metadata["walk_forward"] for v in (a, b))
        assert x["params_by_fold"] == y["params_by_fold"]
        pd.testing.assert_frame_equal(x["trial_table"], y["trial_table"])
        account_equal(a.result, b.result)
    assert b.meta["records"][0]["final_selection_reason"] == "META_MODEL_PROPOSAL"


def test_pre02_m04_physical_history_order_same_active_decision(history_run, matured):
    cutoff = CUTOFFS[0]
    b = run(history_run.route, "active", data=current(history_run.data, cutoff),
            start=str((cutoff+pd.Timedelta(days=1)).date()),
            history=clone_history(history_run.context.history, reverse=True))
    decision_equal(matured[cutoff], b)


def altered_labels(revision, amount):
    return tuple(replace(o, observation=replace(o.observation,
        raw_sharpe=o.observation.raw_sharpe+amount))
        if o.observation.status == OutcomeStatus.VALID else o for o in revision.outcomes)


def test_pre02_m02_future_labels_and_candidate_archive_excluded(history_run, matured):
    from quantbt.optimization.meta_selection.descriptors import DescriptorSchema
    from quantbt.optimization.meta_selection.panel import freeze_panel
    from tests.meta_selection.pre_e06_02_support import RANGES
    cutoff = CUTOFFS[0]
    items = []
    changed = 0
    for revision in history_run.context.history._revisions.values():
        if revision.revision_available_at > cutoff:
            task = revision.task
            anchor = next((c for c in task.candidates if c.evaluation_id != task.anchor_candidate_evaluation_id), task.anchor)
            task = replace(task, candidates=tuple(reversed(task.candidates)),
                anchor_candidate_evaluation_id=anchor.evaluation_id,
                roles=tuple(replace(r, evaluation_id=anchor.evaluation_id) if r.role == "native_anchor" else r
                            for r in task.roles))
            panel = freeze_panel(task, DescriptorSchema(RANGES), sealed_at=task.decision_sealed_at)
            labels = {o.evaluation_id: replace(o, task_id=task.task_id)
                      for o in altered_labels(revision, 1000.)}
            revision = replace(revision, task=task, panel=panel,
                               outcomes=tuple(labels[eid] for eid in panel.members))
            changed += 1
        items.append(revision)
    assert changed > 0
    b = run(history_run.route, "active", data=current(history_run.data, cutoff),
        start=str((cutoff+pd.Timedelta(days=1)).date()),
        history=clone_history(history_run.context.history, revisions=items))
    decision_equal(matured[cutoff], b)
    account_equal(matured[cutoff].result.fold_results[0].result if history_run.route == "reactive_reset" else matured[cutoff].result,
                  b.result.fold_results[0].result if history_run.route == "reactive_reset" else b.result)


def test_pre02_m02_fitted_future_artifact_fail_closed(history_run, matured):
    from quantbt.optimization.meta_selection.artifacts import dumps_model, loads_model
    from quantbt.optimization.meta_selection.common import MetaRecordError
    model = next(iter(matured[CUTOFFS[-1]].meta["models"].values()))
    with pytest.raises(MetaRecordError, match="NOT_YET_AVAILABLE"):
        loads_model(dumps_model(model), expected_model_id=model.model_id, available_as_of=CUTOFFS[0])
    assert loads_model(dumps_model(model), expected_model_id=model.model_id,
                       available_as_of=model.fit_completed_at) == model


def test_pre02_m03_labels_published_during_search_do_not_enter_frozen_fit(history_run, matured):
    cutoff = CUTOFFS[0]
    h = clone_history(history_run.context.history)
    parent = next(r for r in h._revisions.values() if r.training_rows and r.revision_available_at < cutoff)
    correction = replace(parent, outcomes=altered_labels(parent, 4.),
        revision_available_at=cutoff+pd.Timedelta(seconds=5),
        parent_revision_id=parent.revision_id, correction_reason="synthetic late reconciliation")
    added = []

    def clock(fold, stage, elapsed):
        if stage == "search" and not added:
            h.append(correction)
            added.append(correction.revision_id)
        return replay_clock(fold, stage, elapsed)

    b = run(history_run.route, "active", data=current(history_run.data, cutoff),
            start=str((cutoff+pd.Timedelta(days=1)).date()), history=h, clock=clock)
    assert added and correction.revision_id not in b.meta["records"][0]["training_revision_ids"]
    decision_equal(matured[cutoff], b)
    future = h.snapshot(family_id=parent.task.family.family_id, authorized_corpora=b.context.authorized_corpora,
        outcome_origins=b.context.outcome_origins, research_exposures=b.context.research_exposures,
        information_as_of=cutoff+pd.Timedelta(seconds=6))
    assert correction.revision_id in {r.revision_id for r in future.revisions}
    assert parent.revision_id not in {r.revision_id for r in future.revisions}
    # A correction replaces, rather than doubles, one origin's contribution.
    assert future.origin_count == b.meta["snapshots"][0].origin_count


def test_pre02_m03_permitted_correction_changes_real_fit_positive_control(history_run, matured):
    cutoff = CUTOFFS[0]
    h = clone_history(history_run.context.history)
    parent = next(r for r in h._revisions.values() if len(r.training_rows) > 1 and r.revision_available_at < cutoff)
    anchor = parent.task.anchor_candidate_evaluation_id
    outcomes = tuple(replace(o, observation=replace(o.observation,
        raw_sharpe=o.observation.raw_sharpe+5.*(i+1)))
        if o.evaluation_id != anchor and o.observation.status == OutcomeStatus.VALID else o
        for i, o in enumerate(parent.outcomes))
    correction = replace(parent, outcomes=outcomes, revision_available_at=cutoff-pd.Timedelta(days=1),
                         parent_revision_id=parent.revision_id, correction_reason="synthetic permitted correction")
    h.append(correction)
    b = run(history_run.route, "active", data=current(history_run.data, cutoff),
            start=str((cutoff+pd.Timedelta(days=1)).date()), history=h)
    assert correction.revision_id in b.meta["records"][0]["training_revision_ids"]
    assert b.meta["snapshots"][0].origin_count == matured[cutoff].meta["snapshots"][0].origin_count
    a_model, b_model = (next(iter(v.meta["models"].values())) for v in (matured[cutoff], b))
    assert a_model.coefficients != b_model.coefficients
    assert sum(r.origin_weight for r in correction.training_rows) == pytest.approx(1.)


def test_pre02_m04_current_pool_order_total_tie_rule(history_run, matured, monkeypatch):
    from quantbt.optimization.meta_selection.runtime import PublicISPoolCapture
    original = PublicISPoolCapture.capture

    def reordered(self, **kwargs):
        original(self, **kwargs)
        self.pools[-1] = replace(self.pools[-1], candidates=tuple(reversed(self.pools[-1].candidates)))

    monkeypatch.setattr(PublicISPoolCapture, "capture", reordered)
    cutoff = CUTOFFS[0]
    b = run(history_run.route, "active", data=current(history_run.data, cutoff),
            start=str((cutoff+pd.Timedelta(days=1)).date()), history=clone_history(history_run.context.history))
    a = matured[cutoff]
    for field in ("selected_params", "selected_evaluation_id", "panel_members", "training_snapshot_id"):
        assert a.meta["records"][0][field] == b.meta["records"][0][field]
    assert a.meta["records"][0]["proposal"].predictions == b.meta["records"][0]["proposal"].predictions


def test_pre02_m05_equal_availability_without_proven_publication_is_excluded(history_run, matured):
    cutoff = CUTOFFS[0]
    h = clone_history(history_run.context.history)
    parent = next(r for r in h._revisions.values() if r.training_rows and r.revision_available_at < cutoff)
    correction = replace(parent, outcomes=altered_labels(parent, 1000.), revision_available_at=cutoff,
                         parent_revision_id=parent.revision_id, correction_reason="equal-clock publication")
    h.append(correction)
    b = run(history_run.route, "active", data=current(history_run.data, cutoff),
            start=str((cutoff+pd.Timedelta(days=1)).date()), history=h)
    decision_equal(matured[cutoff], b)


def test_pre02_m07_in_window_market_funding_invalidates_witness(history_run, matured):
    cutoff = CUTOFFS[0]
    data = current(history_run.data, cutoff)
    for f in data.values() if isinstance(data, dict) else (data,):
        f.loc[cutoff, ["open", "high", "low", "close"]] *= 1.01
        f.loc[cutoff, "volume"] *= 1.5
        if f.funding_rate.ne(0).any():
            f.loc[cutoff, "funding_rate"] = .0009
    b = run(history_run.route, "active", data=data, start=str((cutoff+pd.Timedelta(days=1)).date()),
            history=clone_history(history_run.context.history))
    a = matured[cutoff]
    assert {c.observation.input_signature for c in a.meta["tasks"][0].candidates} != {
        c.observation.input_signature for c in b.meta["tasks"][0].candidates}


@pytest.mark.parametrize("cutoff", CUTOFFS)
def test_pre02_matured_rust_reference_fit_rank_account(history_run, matured, cutoff):
    b = run(history_run.route, "active", data=current(history_run.data, cutoff),
        start=str((cutoff+pd.Timedelta(days=1)).date()), numeric="require",
        history=clone_history(history_run.context.history))
    policy_equal(matured[cutoff], b)
    assert b.meta["records"][0]["numeric_backend"]["ffi_calls"] > 0


@pytest.mark.parametrize("cutoff", CUTOFFS)
def test_pre02_matured_cached_uncached_witness_exact(history_run, matured, cutoff):
    b = run(history_run.route, "active", data=current(history_run.data, cutoff),
        start=str((cutoff+pd.Timedelta(days=1)).date()), witness=False,
        history=clone_history(history_run.context.history))
    decision_equal(matured[cutoff], b)
    original = matured[cutoff]
    account_equal(original.result.fold_results[0].result if original.route == "reactive_reset" else original.result,
                  b.result.fold_results[0].result if b.route == "reactive_reset" else b.result)


@pytest.mark.parametrize("cutoff", CUTOFFS)
def test_pre02_matured_scalar_prepared_reference(history_run, matured, cutoff):
    if history_run.route not in {"signal_notional", "notional", "unit", "pct_equity"}:
        pytest.skip("This route has its own original account, not the same-close scalar scorer")
    b = run(history_run.route, "active", data=current(history_run.data, cutoff),
        start=str((cutoff+pd.Timedelta(days=1)).date()), prepared=True,
        history=clone_history(history_run.context.history))
    policy_equal(matured[cutoff], b, prepared=True)
    assert b.result.metadata["walk_forward"]["prepared_scoring_cache"]["native_prepared_wfo"]["native_batches"] > 0
