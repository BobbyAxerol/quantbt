"""Synthetic-only MLR-02 contracts; no corpus admission or financial execution."""

from dataclasses import replace
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from quantbt.optimization.meta_selection.common import MetaRecordError, digest
from quantbt.optimization.meta_selection.history import MetaHistory
from quantbt.optimization.meta_selection.model import RidgeLearner, RidgeSettings
from quantbt.optimization.meta_selection.numerics import NumericLimits, NumericRuntime
from quantbt.optimization.meta_selection.panel import freeze_panel
from quantbt.optimization.meta_selection.records import OutcomeStatus
from quantbt.optimization.meta_selection.selection import select_indices
from tests.meta_selection.test_qms03_history import make_task, revision_for, snapshot, stamp
from tools.meta_model_research.linear import (
    ALPHA_GRID, BUNDLE_VERSION, LinearResearch, Policy, ResearchArtifact,
    dumps_artifact, evaluate_revision, loads_artifact,
)


def supported_task(schema, n=7):
    task, _ = make_task(n=n, year=2020, schema=schema)
    candidates = []
    for c in task.candidates:
        params = dict(c.effective_params)
        if params["filter"]:
            params["threshold"] = 0.2
        candidates.append(replace(c, requested_params=params, effective_params=params))
    return replace(task, candidates=tuple(candidates))


def corpus(k=12):
    revisions = []
    schema = None
    for i in range(k):
        task, schema = make_task(n=2 if i % 2 == 0 else 3, year=2000 + i, schema=schema)
        raw = (0.0, 2.0) if i % 2 == 0 else (2.0, 4.0, 6.0)
        task = replace(task, candidates=tuple(
            replace(c, observation=replace(c.observation, raw_sharpe=x))
            for c, x in zip(task.candidates, raw)))
        revisions.append(revision_for(task, schema))
    task = supported_task(schema)
    store = MetaHistory()
    for revision in revisions:
        store.append(revision)
    view = snapshot(store, task, task.data_cutoff)
    return schema, store, view, task, tuple(revisions)


@pytest.fixture
def data():
    return corpus()


def fit(engine, policy, data):
    schema, _, view, task, _ = data
    return engine.fit(policy, schema, view, fit_completed_at=task.decision_sealed_at)


def artifact(data, policy=Policy(), **kwargs):
    engine = LinearResearch(**kwargs)
    fitted = fit(engine, policy, data)
    return engine, engine.propose(data[3], fitted, schema=data[0], full_ranking=True)


def oracle(schema, view, penalty):
    """Independent scaler/target/weights and augmented least squares, not G solve."""
    blocks, raw_weights, masks, labels = [], [], [], []
    for revision in view.revisions:
        task = revision.task
        outcomes = {o.evaluation_id: o.observation for o in revision.outcomes}
        valid = [c for c in task.candidates if outcomes[c.evaluation_id].status == OutcomeStatus.VALID]
        batch = schema.encode(valid)
        blocks.append((task, valid, np.array(batch.values)))
        masks.append(batch.active)
        raw_weights.extend([1 / len(valid)] * len(valid))
        anchor = task.anchor
        base = anchor.observation.raw_sharpe - outcomes[anchor.evaluation_id].raw_sharpe
        labels.append([(c.observation.raw_sharpe - outcomes[c.evaluation_id].raw_sharpe) - base
                       for c in valid if c.evaluation_id != anchor.evaluation_id])
    raw, active, weight = np.concatenate([b[2] for b in blocks]), np.concatenate(masks), np.array(raw_weights)
    means, scales = np.zeros(raw.shape[1]), np.ones(raw.shape[1])
    transformed = raw.copy()
    for j in schema.numeric_columns:
        mask = active[:, j]
        if mask.any():
            x, w = raw[mask, j], weight[mask]
            means[j] = math.fsum(float(a * b) for a, b in zip(x, w)) / math.fsum(w)
            variance = math.fsum(float(b * (a - means[j]) ** 2) for a, b in zip(x, w)) / math.fsum(w)
            if np.any(np.abs(x - means[j]) > 1e-12):
                scales[j] = math.sqrt(variance)
                transformed[mask, j] = (x - means[j]) / scales[j]
            else:
                transformed[mask, j] = 0
        transformed[~mask, j] = 0
    contrasts, y, w, start = [], [], [], 0
    for (task, valid, _), target in zip(blocks, labels):
        x = transformed[start:start + len(valid)]
        ai = next(i for i, c in enumerate(valid) if c.evaluation_id == task.anchor.evaluation_id)
        contrasts.extend(x[i] - x[ai] for i in range(len(valid)) if i != ai)
        y.extend(target)
        w.extend([1 / len(target)] * len(target))
        start += len(valid)
    v, y, w = np.array(contrasts), np.array(y), np.array(w)
    a = np.vstack((v * np.sqrt(w[:, None]), np.eye(v.shape[1]) * math.sqrt(penalty)))
    rhs = np.concatenate((y * np.sqrt(w), np.zeros(v.shape[1])))
    return means, scales, np.linalg.lstsq(a, rhs, rcond=None)[0]


@pytest.mark.parametrize("policy", [Policy(), Policy("P1"), *(Policy("P2", a) for a in ALPHA_GRID)])
def test_weight_scaler_and_augmented_oracle_for_every_policy(data, policy):
    engine = LinearResearch()
    fitted = fit(engine, policy, data)
    model = fitted.outcome.model
    means, scales, beta = oracle(data[0], data[2], policy.lambda_for(12))
    np.testing.assert_allclose(model.scaler["mean"], means, rtol=1e-12, atol=1e-12)
    np.testing.assert_allclose(model.scaler["scale"], scales, rtol=1e-12, atol=1e-12)
    np.testing.assert_allclose(model.coefficients, beta, rtol=1e-9, atol=1e-10)
    j = data[0].feature_names.index("raw_is_sharpe")
    assert model.scaler["mean"][j] == pytest.approx(5 / 2)
    assert model.scaler["scale"][j] ** 2 == pytest.approx(49 / 12)
    for tid, _, _ in model.revision_references:
        refs = [r for r in model.fit_row_references if r[0] == tid]
        assert len(refs) in {1, 2}
        assert sum(r[3] for r in refs) == 1
    assert engine.metadata["regression_fit_count"] == 1
    assert model.settings.min_matured_origins == 12


def test_p1_k12_identity_and_other_k_units(data):
    engine = LinearResearch()
    p0, p1 = fit(engine, Policy(), data), fit(engine, Policy("P1"), data)
    assert p0.fit_id != p1.fit_id and p0.policy.policy_id != p1.policy.policy_id
    assert p0.outcome.model.settings == p1.outcome.model.settings == RidgeSettings()
    np.testing.assert_array_equal(p0.outcome.model.coefficients, p1.outcome.model.coefficients)
    assert engine.fit_count == 2
    assert engine.regression_fit_count == 1  # Exact underlying V1 numeric cache hit.
    more = corpus(14)
    other = fit(LinearResearch(), Policy("P1"), more)
    assert other.outcome.model.settings.lambda_reg == 14 * (10 / 12)
    assert other.outcome.model.diagnostics["effective_mean_origin_lambda"] == pytest.approx(10 / 12)
    assert Policy().lambda_for(14) == 10
    assert Policy("P2", 3).lambda_for(14) == 42


@pytest.mark.parametrize("kwargs", [dict(name="P3"), dict(name="P0", alpha=1),
    dict(name="P1", alpha=1), dict(name="P2"), dict(name="P2", alpha=0.2),
    dict(name="P2", alpha=True), dict(name="P2", alpha=float("nan")), dict(version="unknown")])
def test_policy_versions_and_grid_are_closed(kwargs):
    with pytest.raises(MetaRecordError):
        Policy(**kwargs)


def test_full_valid_pool_anchor_guard_distance_and_permutation(data):
    schema, _, _, old, _ = data
    task = supported_task(schema, n=24)
    invalid = replace(task.candidates[-1], observation=replace(task.candidates[-1].observation,
        status=OutcomeStatus.NO_VARIANCE, raw_sharpe=None, sample_std=None, sample_count=0))
    task = replace(task, candidates=task.candidates[:-1] + (invalid,))
    engine = LinearResearch()
    fitted = fit(engine, Policy(), data)
    result = engine.propose(task, fitted, schema=schema, full_ranking=True)
    decision = result.decision
    assert len(decision.predictions) == len(task.candidates) == 24
    served = [p for p in decision.predictions if p["yhat"] is not None]
    assert len(served) == 23 and len(served) > 16
    anchor = next(p for p in served if p["evaluation_id"] == task.anchor.evaluation_id)
    assert (anchor["yhat"], anchor["qhat"], anchor["distance"]) == (0.0, 0.0, 0.0)
    for p in served:
        assert p["qhat"] == pytest.approx(p["raw_is"] - anchor["raw_is"] - p["yhat"])
        assert p["eligible"] == (p["qhat"] >= -0.1)
    safe = [p for p in served if p["eligible"]]
    minimum = min(p["yhat"] for p in safe)
    ties = [p for p in safe if p["yhat"] <= minimum + 1e-10]
    winner = min(ties, key=lambda p: (p["distance"], p["candidate_id"], p["evaluation_id"]))
    assert decision.proposed_evaluation_id == decision.ranked_ids[0] == winner["evaluation_id"]
    reversed_task = replace(task, candidates=tuple(reversed(task.candidates)), roles=tuple(reversed(task.roles)))
    other = engine.propose(reversed_task, fitted, schema=schema, full_ranking=True)
    assert decision.predictions == other.decision.predictions
    assert decision.tie_set == other.decision.tie_set
    assert decision.actual_evaluation_id is None
    assert old.task_id != task.task_id


def test_exact_floor_and_minimum_based_ties_not_chaining():
    y = [0, -1, -1 + 0.75e-10, -1 + 1.5e-10, -2]
    q = [0, -0.1, 0, 0, np.nextafter(-0.1, -np.inf)]
    winner, ties, safe = select_indices(y, q, [0, 3, 2, 1, 0],
        [("anchor",), ("b",), ("c",), ("d",), ("e",)], epsilon=0.1, tie_tolerance=1e-10)
    assert winner == 2 and ties == (1, 2)
    assert safe.tolist() == [True, True, True, True, False]


def test_independent_scalar_sum_mean_and_origin_replication_identity():
    runtime = NumericRuntime(native_policy="reference", work_cache=False)
    v = np.tile([[1.0], [1.0], [3.0]], (6, 1))
    y, w = np.tile([2.0, 0.0, 4.0], 6), np.tile([1.0, 0.5, 0.5], 6)
    assert w.sum() == 12
    _, _, summed = runtime.fit(v, y, w, 10)
    _, _, mean = runtime.fit(v, y, w / 12, 10 / 12)
    assert summed[0] == pytest.approx(24 / 23)
    np.testing.assert_allclose(summed, mean, atol=1e-12)
    _, _, doubled = runtime.fit(np.tile(v, (2, 1)), np.tile(y, 2), np.tile(w, 2), 20)
    np.testing.assert_allclose(summed, doubled, atol=1e-12)


def test_whole_pool_ood_and_undefined_anchor_preserve_native(data):
    schema, _, _, task, _ = data
    engine = LinearResearch()
    fitted = fit(engine, Policy("P2", 10), data)
    unsupported, _ = make_task(n=7, year=2020, schema=schema)
    result = engine.propose(unsupported, fitted, schema=schema)
    assert result.decision.status == "META_OOD_NATIVE_FALLBACK"
    assert result.decision.proposed_evaluation_id == unsupported.anchor.evaluation_id
    assert result.decision.guard["unsupported_ids"]
    anchor = replace(task.anchor, observation=replace(task.anchor.observation,
        status=OutcomeStatus.NO_VARIANCE, raw_sharpe=None, sample_std=None, sample_count=0))
    task = replace(task, candidates=(anchor,) + task.candidates[1:])
    result = engine.propose(task, fitted, schema=schema)
    assert result.decision.status == "META_NOT_APPLICABLE_METRIC"
    assert result.decision.proposed_evaluation_id == task.anchor.evaluation_id


def test_future_and_equal_time_correction_cannot_invalidate_earlier_cache(data):
    schema, history, view, task, revisions = data
    engine = LinearResearch()
    first = fit(engine, Policy(), data)
    old = revisions[0]
    corrected = revision_for(old.task, schema, parent=old,
                             available=task.data_cutoff + pd.Timedelta(days=1))
    corrected = replace(corrected, outcomes=tuple(replace(o, observation=replace(
        o.observation, raw_sharpe=o.observation.raw_sharpe + o.evaluation_id.endswith("-1")))
        for o in corrected.outcomes))
    history.append(corrected)
    same = snapshot(history, task, task.data_cutoff)
    assert same.snapshot_id == view.snapshot_id
    assert engine.fit(Policy(), schema, same, fit_completed_at=task.decision_sealed_at) is first
    equal = snapshot(history, task, corrected.revision_available_at)
    assert equal.revisions == view.revisions
    later = snapshot(history, task, corrected.revision_available_at + pd.Timedelta(seconds=1))
    new = engine.fit(Policy(), schema, later, fit_completed_at=later.information_as_of)
    assert new.snapshot_id != first.snapshot_id and new.origin_count == first.origin_count
    assert not np.allclose(new.outcome.model.coefficients, first.outcome.model.coefficients)
    assert first.outcome.model.revision_references != new.outcome.model.revision_references
    assert engine.fit_count == 2 and engine.cache_hits == 1


def test_correction_reweights_entire_origin_and_rebuilds_scaler(data):
    schema, history, _, task, revisions = data
    old = revisions[1]
    bad_id = old.training_rows[-1].candidate_evaluation_id
    revised = revision_for(old.task, schema, parent=old,
        status_by_id={bad_id: OutcomeStatus.OUTCOME_FAILED},
        available=old.revision_available_at + pd.Timedelta(days=1))
    engine = LinearResearch()
    original = fit(engine, Policy("P1"), data)
    history.append(revised)
    view = snapshot(history, task, task.data_cutoff)
    changed = engine.fit(Policy("P1"), schema, view, fit_completed_at=task.decision_sealed_at)
    refs = [r for r in changed.outcome.model.fit_row_references if r[0] == old.task.task_id]
    assert len(refs) == 1 and refs[0][3] == 1
    assert changed.origin_count == original.origin_count == 12
    means, scales, beta = oracle(schema, view, 10)
    np.testing.assert_allclose(changed.outcome.model.coefficients, beta, atol=1e-10)
    np.testing.assert_allclose(changed.outcome.model.scaler["mean"], means, atol=1e-12)
    np.testing.assert_allclose(changed.outcome.model.scaler["scale"], scales, atol=1e-12)


@pytest.mark.parametrize("k", [0, 11])
def test_min12_cold_start_does_not_spend_fit_budget(data, k):
    schema, _, view, task, _ = data
    view = replace(view, revisions=view.revisions[:k])
    engine = LinearResearch(max_fits=0)
    for policy in (Policy(), Policy("P1"), Policy("P2", 0.1)):
        fitted = engine.fit(policy, schema, view)
        result = engine.propose(task, fitted, schema=schema)
        assert result.decision.proposed_evaluation_id == task.anchor.evaluation_id
        assert result.decision.status == "META_SUPPORT_INSUFFICIENT"
        assert result.fit.outcome.model is None
    assert engine.fit_count == engine.regression_fit_count == 0


def test_cache_capacity_settings_cutoff_clocks_and_hard_budget(data):
    engine = LinearResearch(max_fits=3, max_cache_entries=1)
    p0 = fit(engine, Policy(), data)
    assert fit(engine, Policy(), data) is p0
    assert engine.fit_count == 1
    fit(engine, Policy("P2", 0.1), data)
    assert engine.metadata["cache_entries"] == 1
    fit(engine, Policy(), data)
    assert engine.fit_count == 3
    engine.clear_cache()
    assert engine.cache_bytes == engine.runtime.work_cache.retained_bytes == 0
    with pytest.raises(MetaRecordError, match="BUDGET"):
        fit(engine, Policy(), data)
    bypass = LinearResearch(max_cache_bytes=1)
    fit(bypass, Policy(), data)
    assert bypass.cache_bytes == 0
    schema, _, view, task, _ = data
    fit(bypass, Policy(), data)
    newer = replace(view, information_as_of=view.information_as_of + pd.Timedelta(seconds=1))
    bypass.fit(Policy(), schema, newer, fit_completed_at=task.decision_sealed_at)
    assert bypass.fit_count == 3 and bypass.regression_fit_count == 2
    with pytest.raises(MetaRecordError, match="COMPLETION"):
        LinearResearch().fit(Policy(), schema, view)


def test_failed_fit_is_charged_and_no_silent_dimension_reduction(data):
    runtime = NumericRuntime(native_policy="reference", limits=NumericLimits(max_workspace_bytes=1))
    engine = LinearResearch(runtime=runtime, max_fits=1)
    with pytest.raises(MetaRecordError, match="RESOURCE_LIMIT"):
        fit(engine, Policy(), data)
    assert engine.fit_count == 1 and engine.failed_regression_fit_charge == 1
    assert engine.regression_fit_count == 0
    with pytest.raises(MetaRecordError, match="BUDGET"):
        fit(engine, Policy(), data)


def test_require_native_delegate_and_actual_regression_fit_bill(data):
    import importlib.util

    root = Path(__file__).resolve().parents[2]
    prefix = root / ".maturin/mode5-m5111/goal-native-gate01/native/_quantbt_native"
    paths = list(prefix.glob("_quantbt_native*.so"))
    if len(paths) != 1:
        pytest.skip("owner-specified existing native prefix is unavailable; no build permitted")
    spec = importlib.util.spec_from_file_location("_mlr02_numeric_test._quantbt_native", paths[0])
    native = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(native)
    runtime = NumericRuntime(native_policy="require", native_module=native)
    engine = LinearResearch(runtime=runtime, max_fits=4)
    first = fit(engine, Policy(), data)
    assert engine.fit_count == 1 and engine.regression_fit_count == 2
    assert engine.metadata["external_runtime_qualification_fits"] == 2
    second = fit(engine, Policy("P1"), data)
    assert engine.fit_count == 2 and engine.regression_fit_count == 3
    assert fit(engine, Policy("P1"), data) is second
    proposed = engine.propose(data[3], first, schema=data[0], full_ranking=True)
    assert proposed.decision.numeric["complete_reference_decision_verified"]
    reference_engine, reference = artifact(data)
    assert proposed.decision.proposed_evaluation_id == reference.decision.proposed_evaluation_id
    assert proposed.decision.tie_set == reference.decision.tie_set
    for a, b in zip(proposed.decision.predictions, reference.decision.predictions):
        assert a["evaluation_id"] == b["evaluation_id"] and a["eligible"] == b["eligible"]
        assert a["yhat"] == pytest.approx(b["yhat"], abs=1e-10)
    with pytest.raises(MetaRecordError, match="BUDGET"):
        fit(engine, Policy("P2", 0.1), data)
    restored = loads_artifact(dumps_artifact(proposed), expected_artifact_id=proposed.artifact_id,
        available_as_of=data[3].decision_sealed_at, task=data[3], schema=data[0])
    assert restored.artifact_id == proposed.artifact_id
    assert reference_engine.regression_fit_count == 1


@pytest.mark.parametrize("kwargs", [dict(max_fits=-1), dict(max_fits=4001),
    dict(max_fits=True), dict(max_cache_entries=65), dict(max_cache_bytes=8_000_001)])
def test_resource_settings_are_bounded(kwargs):
    with pytest.raises(MetaRecordError, match="BUDGET"):
        LinearResearch(**kwargs)


@pytest.mark.parametrize("policy", [Policy(), Policy("P1"), Policy("P2", 0.3)])
def test_artifact_restore_uses_trusted_ids_and_full_served_pool(data, policy):
    engine, result = artifact(data, policy)
    text = dumps_artifact(result)
    restored = loads_artifact(text, expected_artifact_id=result.artifact_id,
        available_as_of=data[3].decision_sealed_at, task=data[3], schema=data[0])
    assert restored.artifact_id == result.artifact_id
    assert restored.fit.fit_id == result.fit.fit_id
    assert restored.decision == result.decision
    assert engine.fit_count == 1
    with pytest.raises(MetaRecordError):
        loads_artifact(text, expected_artifact_id="unknown", available_as_of=data[3].decision_sealed_at,
                       task=data[3], schema=data[0])
    with pytest.raises(MetaRecordError, match="AVAILABLE"):
        loads_artifact(text, expected_artifact_id=result.artifact_id,
            available_as_of=data[3].data_cutoff, task=data[3], schema=data[0])


def test_restore_rejects_rehashed_wrong_policy_and_incomplete_pool(data):
    _, result = artifact(corpus(14))
    more = corpus(14)
    document = json.loads(dumps_artifact(result))
    document["payload"]["policy"] = dict(name="P1", alpha=10 / 12, version=Policy().version)
    document["artifact_id"] = digest(dict(schema=BUNDLE_VERSION, payload=document["payload"]))
    with pytest.raises(MetaRecordError, match="FIT_CONTEXT"):
        loads_artifact(json.dumps(document), expected_artifact_id=document["artifact_id"],
            available_as_of=more[3].decision_sealed_at, task=more[3], schema=more[0])
    _, result = artifact(data)
    decision = result.decision
    protected = {decision.anchor_evaluation_id, decision.proposed_evaluation_id, decision.raw_best_evaluation_id}
    drop = next(p["evaluation_id"] for p in decision.predictions if p["evaluation_id"] not in protected)
    partial = replace(decision, predictions=tuple(p for p in decision.predictions if p["evaluation_id"] != drop),
                      tie_set=tuple(i for i in decision.tie_set if i != drop),
                      ranked_ids=tuple(i for i in decision.ranked_ids if i != drop))
    invalid = ResearchArtifact(result.fit, partial, result.task_digest)
    with pytest.raises(MetaRecordError, match="MISMATCH"):
        loads_artifact(dumps_artifact(invalid), expected_artifact_id=invalid.artifact_id,
            available_as_of=data[3].decision_sealed_at, task=data[3], schema=data[0])


def test_evaluation_uses_served_predictions_known_panel_and_independent_error_oracle(data, monkeypatch):
    engine, result = artifact(data)
    revision = revision_for(data[3], data[0])
    def forbidden(*args, **kwargs):
        raise AssertionError("evaluation must not fit or predict again")
    monkeypatch.setattr(engine.runtime, "rank", forbidden)
    monkeypatch.setattr(RidgeLearner, "fit", forbidden)
    at = revision.revision_available_at + pd.Timedelta(seconds=1)
    measured = evaluate_revision(result, revision, available_as_of=at)
    pred = {p["evaluation_id"]: p for p in result.decision.predictions}
    anchor = revision.task.anchor
    outcomes = {o.evaluation_id: o.observation.raw_sharpe for o in revision.outcomes}
    base = anchor.observation.raw_sharpe - outcomes[anchor.evaluation_id]
    residual = [pred[c.evaluation_id]["yhat"] - (c.observation.raw_sharpe - outcomes[c.evaluation_id] - base)
                for c in revision.task.candidates if c.evaluation_id != anchor.evaluation_id]
    mse = math.fsum(e * e for e in residual) / len(residual)
    mae = math.fsum(abs(e) for e in residual) / len(residual)
    assert measured.metrics["y_mse"] == pytest.approx(mse)
    assert measured.metrics["y_mae"] == pytest.approx(mae)
    assert measured.metrics["y_rmse"] == math.sqrt(measured.metrics["y_mse"])
    for suffix in ("mae", "mse", "rmse"):
        assert measured.metrics[f"y_{suffix}"] == measured.metrics[f"q_{suffix}"]
    assert all(r["q_error"] == -r["y_error"] for r in measured.errors)
    assert measured.task_id == revision.task.task_id and measured.origin == revision.task.origin
    assert measured.known_rows == measured.scored_rows == len(residual)
    assert "not_full_pool_oracle" in measured.estimand
    for name in ("y", "q"):
        actual = np.array([r.y if name == "y" else r.q for r in revision.training_rows])
        scores = np.array([pred[r.candidate_evaluation_id][f"{name}hat"] for r in revision.training_rows])
        x = scores - scores.mean()
        slope = float(np.dot(x, actual - actual.mean()) / np.dot(x, x))
        assert measured.metrics[f"{name}_calibration_slope"] == pytest.approx(slope)
        # No ties here: ranks independently counted, not production midrank helper.
        a = np.array([sum(v < y for v in actual) for y in actual])
        b = np.array([sum(v < y for v in scores) for y in scores])
        expected_rank = np.corrcoef(a, b)[0, 1]
        assert measured.metrics[f"{name}_spearman"] == pytest.approx(expected_rank)


def test_evaluation_availability_nulls_and_base_membership(data):
    _, result = artifact(data)
    revision = revision_for(data[3], data[0])
    with pytest.raises(MetaRecordError, match="unavailable"):
        evaluate_revision(result, revision, available_as_of=revision.revision_available_at)
    at = revision.revision_available_at + pd.Timedelta(seconds=1)
    failed = revision_for(data[3], data[0], status_by_id={data[3].anchor.evaluation_id: OutcomeStatus.NO_VARIANCE})
    null = evaluate_revision(result, failed, available_as_of=at)
    assert null.scored_rows == 0 and null.metrics["y_mse"] is None
    assert null.label_statuses["NO_VARIANCE"] == 1
    cold_view = replace(data[2], revisions=())
    engine = LinearResearch(max_fits=0)
    fitted = engine.fit(Policy(), data[0], cold_view)
    cold = engine.propose(data[3], fitted, schema=data[0])
    null = evaluate_revision(cold, revision, available_as_of=at)
    assert null.status == "NO_SERVED_PREDICTIONS" and null.metrics["q_rmse"] is None
    base = evaluate_revision(result, revision, available_as_of=at, panel="base")
    assert base.panel_members == revision.panel.base_members and base.panel == "base"


def test_base_vs_union_evaluation_is_conditional_not_an_eligibility_filter(data):
    schema, _, _, _, _ = data
    task = supported_task(schema, n=24)
    engine = LinearResearch()
    fitted = fit(engine, Policy(), data)
    result = engine.propose(task, fitted, schema=schema, full_ranking=True)
    revision = revision_for(task, schema)
    extra = next(c for c in task.candidates if c.evaluation_id not in revision.panel.members)
    panel = freeze_panel(task, schema, required_winners=(extra.evaluation_id,),
                         sealed_at=task.decision_sealed_at)
    template = revision.outcomes[0]
    observation = replace(template.observation, raw_sharpe=-1,
                          output_ref="synthetic-extra-winner-forward")
    outcome = replace(template, evaluation_id=extra.evaluation_id, observation=observation)
    revision = replace(revision, panel=panel, outcomes=revision.outcomes + (outcome,))
    at = revision.revision_available_at + pd.Timedelta(seconds=1)
    base = evaluate_revision(result, revision, available_as_of=at, panel="base")
    union = evaluate_revision(result, revision, available_as_of=at, panel="union")
    assert base.known_rows == base.scored_rows == 15
    assert union.known_rows == union.scored_rows == 16
    assert len(result.decision.predictions) == 24
    assert extra.evaluation_id in {r["evaluation_id"] for r in union.errors}
    assert extra.evaluation_id not in {r["evaluation_id"] for r in base.errors}


def test_constant_truth_rank_null_is_not_zero_or_silently_dropped(data):
    _, result = artifact(data)
    revision = revision_for(data[3], data[0])
    candidates = {c.evaluation_id: c for c in revision.task.candidates}
    revision = replace(revision, outcomes=tuple(replace(o, observation=replace(
        o.observation, raw_sharpe=candidates[o.evaluation_id].observation.raw_sharpe))
        for o in revision.outcomes))
    measured = evaluate_revision(result, revision,
        available_as_of=revision.revision_available_at + pd.Timedelta(seconds=1))
    assert measured.scored_rows == 6
    assert measured.metrics["y_spearman"] is None and measured.metrics["y_pair_accuracy"] is None
    assert measured.null_reasons["y_spearman"]


def test_cold_restore_and_strict_payload_failures(data):
    engine = LinearResearch(max_fits=0)
    fitted = engine.fit(Policy("P1"), data[0], replace(data[2], revisions=()))
    result = engine.propose(data[3], fitted, schema=data[0])
    kwargs = dict(expected_artifact_id=result.artifact_id,
                  available_as_of=data[3].decision_sealed_at, task=data[3], schema=data[0])
    assert loads_artifact(dumps_artifact(result), **kwargs).fit.outcome.model is None
    for text in ('{"schema":1,"schema":2}', '{"bad":NaN}', '[]'):
        with pytest.raises(MetaRecordError):
            loads_artifact(text, **kwargs)
    with pytest.raises(MetaRecordError, match="SIZE"):
        loads_artifact(dumps_artifact(result), max_bytes=1, **kwargs)


def test_frozen_sources_and_settings_still_match():
    from hashlib import sha256
    root = Path(__file__).resolve().parents[2]
    manifest = json.loads((root / "benchmarks/optimization/meta_selection/model_research_v1/ridge_v1_freeze.json").read_text())
    assert all(sha256((root / p).read_bytes()).hexdigest() == h for p, h in manifest["source_sha256"].items())
