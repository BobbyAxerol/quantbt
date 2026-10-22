"""Synthetic record algebra and actual QMS fits; no financial executions."""

from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from quantbt.optimization.meta_selection.common import MetaRecordError, digest
from quantbt.optimization.meta_selection.config import MetaHistoryContext, MetaSelectionConfig
from quantbt.optimization.meta_selection.descriptors import DescriptorSchema
from quantbt.optimization.meta_selection.history import MetaHistory, SealedTaskRevision
from quantbt.optimization.meta_selection.model import RidgeLearner
from quantbt.optimization.meta_selection.panel import freeze_panel
from quantbt.optimization.meta_selection.records import (
    CandidateForwardRecord, CandidateISRecord, CandidateRoleRef, CompatibilityFamily,
    MetaTask, MetricObservation, OutcomeStatus,
)

from tools.mode4_quarterly.contracts import quarterly_calendar
from tools.mode4_quarterly.policy import ResearchPolicies, rebase_task


CALENDAR = quarterly_calendar()
HOUR = pd.Timedelta(hours=1)
SECOND = pd.Timedelta(seconds=1)


def task_for(index=0, *, n=40, schema=None):
    schema = schema or DescriptorSchema({"coordinate": (0.0, 1.0)}, native_policy="reference")
    fold = CALENDAR[index]
    start, cutoff = pd.Timestamp(fold.is_start), pd.Timestamp(fold.is_end) - HOUR
    forward_start, forward_end = pd.Timestamp(fold.oos_start), pd.Timestamp(fold.oos_end) - HOUR
    family = CompatibilityFamily(
        "public-synthetic-variant-v1", schema.space.identity, schema.schema_id,
        "synthetic-instrument", "1h", "caller-rolling365D-quarterly-v1",
        "qualified-raw-metric-v1", "synthetic-economics-v1", "qualified-scorer-v1",
        "frozen-native-selector-v1", "frozen-sampler-v1", "reset-flat-diagnostics-v1",
    )
    candidates = []
    for i in range(n):
        params = {"coordinate": i / (n - 1)}
        observation = MetricObservation(
            OutcomeStatus.VALID, 1.0 + i * .01 + index * .03, 10 + i + index,
            364, .1, family.metric_contract_id, family.economics_id,
            start, cutoff, cutoff, 20_000.0, 20_000.0,
            f"synthetic-is-{index}-{i}", f"synthetic-is-input-{index}", "original_result",
        )
        candidates.append(CandidateISRecord(
            f"evaluation-{index:02d}-{i:03d}", f"candidate-{i:03d}", i, params, params,
            100.0 - i, observation, cutoff + 2 * SECOND, {"public_marker": i},
        ))
    anchor = candidates[0].evaluation_id
    return MetaTask(
        family, "permitted-quarterly", "synthetic-run", cutoff, start, cutoff,
        forward_start, forward_end, cutoff, 731 + index, tuple(candidates), anchor,
        (CandidateRoleRef("native_anchor", family.anchor_policy_id, anchor),
         CandidateRoleRef("static_control", "public-control", candidates[1].evaluation_id)),
        cutoff + 2 * SECOND, cutoff + 3 * SECOND, cutoff + 20 * SECOND,
        forward_start, pd.Timestamp("2026-10-16", tz="UTC"), "historical_replay",
        "historical_counterfactual", "research_only", {"captured_pool": f"pool-{index}"},
    ), schema


def policies_for(task, schema, *, history=None, mode="active", observer=True, **kwargs):
    context = MetaHistoryContext(
        history if history is not None else MetaHistory(max_revisions=200),
        task.corpus_id, task.family.instrument_id, task.family.timeframe, task.run_id,
    )
    return ResearchPolicies(
        base_family=task.family, context=context, schema=schema,
        config=MetaSelectionConfig(mode=mode, native_batch_policy="reference",
                                   label_observer=observer, full_ranking=True, **kwargs),
    )


def process(policies, task, *, alternate=True, **kwargs):
    return policies.process_task(
        task, alternate_anchor_evaluation_id=(task.candidates[-5].evaluation_id if alternate else None),
        information_as_of=task.data_cutoff, fit_completed_at=task.data_cutoff + 10 * SECOND,
        **kwargs,
    )


def forward_records(bound, *, available=None, publication_order=None):
    task = bound.base_task
    available = available if available is not None else task.forward_end + SECOND
    by_id = {c.evaluation_id: c for c in task.candidates}
    records = []
    for eid in bound.query_panel.members:
        candidate = by_id[eid]
        # Declared synthetic observations, not simulated account returns or fake
        # financial proof. Nonzero decay varies with candidate and origin.
        decay = 1.5 - .9 * candidate.effective_params["coordinate"] + .02 * task.resolved_fold_seed
        observation = replace(
            candidate.observation, raw_sharpe=candidate.observation.raw_sharpe - decay,
            sample_count=85, window_start=task.forward_start, window_end=task.forward_end,
            input_frontier=task.forward_end, output_ref=f"synthetic-forward-{eid}",
            input_signature=f"synthetic-forward-input-{task.resolved_fold_seed}",
        )
        records.append(CandidateForwardRecord(
            task.task_id, eid, observation, available, 1.0, publication_order,
        ))
    return tuple(records)


def publish(policies, bound):
    return policies.publish_forward(bound, forward_records(bound),
                                    revision_available_at=bound.base_task.forward_end + SECOND)


def history_from(revisions):
    history = MetaHistory(max_revisions=200)
    for revision in revisions:
        history.append(revision)
    return history


@pytest.fixture(scope="module")
def mature():
    task, schema = task_for()
    policies = policies_for(task, schema)
    revisions, decisions = [], []
    for i in range(13):
        current, _ = task_for(i, schema=schema)
        bound = process(policies, current)
        decisions.append(bound)
        revisions.extend(publish(policies, bound))
    return policies, schema, tuple(revisions), tuple(decisions)


def test_anchor_binding_keeps_original_records_and_separate_stable_families():
    task, schema = task_for()
    policies = policies_for(task, schema)
    bound = process(policies, task)
    assert bound.alternate is not None
    assert bound.native.task.family != bound.alternate.task.family
    for result in bound.families:
        assert result.task.candidates is task.candidates
        assert result.task.sampling_provenance == task.sampling_provenance
        assert result.task.resolved_fold_seed == task.resolved_fold_seed
        assert result.task.task_id != task.task_id
        assert result.task.roles[0] == task.roles[1]
        assert result.task.roles[-1] == CandidateRoleRef(
            "native_anchor", result.task.family.anchor_policy_id, result.native.evaluation_id,
        )
        assert result.fit.model is None
        assert result.decision.status == "META_SUPPORT_INSUFFICIENT"
        assert result.selected is result.native
    later, _ = task_for(1, schema=schema)
    again = process(policies, later)
    assert [r.task.family for r in again.families] == [r.task.family for r in bound.families]
    same = policies.process_task(
        task, alternate_anchor_evaluation_id=task.anchor_candidate_evaluation_id,
        information_as_of=task.data_cutoff, fit_completed_at=task.decision_sealed_at,
    )
    assert same.native.task.family != same.alternate.task.family
    assert same.native.task.task_id != same.alternate.task.task_id


def test_each_panel_is_original_anchor_first16_and_physical_union_is_exact():
    task, schema = task_for()
    bound = process(policies_for(task, schema), task)
    compared = {r.native.evaluation_id for r in bound.families}
    for result in bound.families:
        expected = freeze_panel(result.task, schema, required_winners=compared,
                                sealed_at=task.decision_sealed_at)
        assert result.panel == expected
        assert result.panel.base_members[0] == result.native.evaluation_id
        assert len(result.panel.base_members) == 16
        assert [role for role, _ in result.panel.quota_roles] == (
            ["anchor"] + ["top"] * 5 + ["diversity"] * 5 + ["control"] * 5
        )
        assert compared <= set(result.panel.required_members)
        assert result.panel.sealed_at <= task.first_forward_action_at
    assert bound.native.panel.base_members != bound.alternate.panel.base_members
    union = {eid for r in bound.families for eid in r.panel.members}
    assert set(bound.query_panel.members) == union
    assert len(bound.query_panel.members) == len(union) <= 36
    assert bound.query_panel.task_id == task.task_id


def test_raw_observations_are_shared_but_y_q_and_weights_are_own_anchor():
    task, schema = task_for()
    policies = policies_for(task, schema)
    bound = process(policies, task)
    records = forward_records(bound)
    revisions = policies.publish_forward(bound, records, revision_available_at=task.forward_end + SECOND)
    raw = {o.evaluation_id: o for o in records}
    for result, revision in zip(bound.families, revisions, strict=True):
        assert revision.panel == result.panel
        assert set(o.evaluation_id for o in revision.outcomes) == set(result.panel.members)
        anchor = result.native
        anchor_decay = anchor.observation.raw_sharpe - raw[anchor.evaluation_id].observation.raw_sharpe
        for outcome in revision.outcomes:
            assert outcome.task_id == result.task.task_id
            assert outcome.observation is raw[outcome.evaluation_id].observation
            assert outcome.label_available_at == raw[outcome.evaluation_id].label_available_at
        assert sum(row.origin_weight for row in revision.training_rows) == pytest.approx(1)
        for row in revision.training_rows:
            assert row.y == pytest.approx(row.raw_is - row.raw_forward - anchor_decay)
            assert row.q == pytest.approx(row.raw_forward - raw[anchor.evaluation_id].observation.raw_sharpe)
            assert row.anchor_evaluation_id == anchor.evaluation_id
            assert row.origin_weight == 1 / len(revision.training_rows)
    left, right = ({row.candidate_evaluation_id: row for row in r.training_rows} for r in revisions)
    shared = min(left.keys() & right.keys())
    assert left[shared].y != pytest.approx(right[shared].y)
    assert left[shared].revision_id != right[shared].revision_id


def test_nineteen_quarters_have_first_real_fit_2025q2_and_only_six_learned(mature):
    _, schema, revisions, early = mature
    first, _ = task_for(schema=schema)
    policies = policies_for(first, schema, history=history_from(revisions))
    decisions = list(early)
    for index in range(13, 19):
        task, _ = task_for(index, schema=schema)
        bound = process(policies, task)
        decisions.append(bound)
        publish(policies, bound)
    for slot in range(2):
        counts = [bound.families[slot].fit.origin_count for bound in decisions]
        assert counts == [max(0, index - 1) for index in range(19)]
        learned = [i for i, bound in enumerate(decisions)
                   if bound.families[slot].decision.status == "META_MODEL_PROPOSAL"]
        assert learned == list(range(13, 19))
        assert CALENDAR[learned[0]].fold_id == "2025Q2"
        assert all(bound.families[slot].fit.model is None for bound in decisions[:13])


def test_actual_ridge_matches_independent_augmented_solve_and_full_pool_rank(mature):
    policies, schema, _, _ = mature
    task, _ = task_for(13, schema=schema)
    bound = process(policies, task)
    for result in bound.families:
        model = result.fit.model
        assert model is not None and model.origin_count == 12
        assert model.settings.lambda_reg == 10 and model.settings.min_matured_origins == 12
        assert model.settings.epsilon == .10
        assert model.scaler["training_snapshot_id"] == result.snapshot.snapshot_id
        # Independently rebuild origin-balanced scaler moments from raw IS rows.
        blocks, contrasts, labels, weights = [], [], [], []
        for revision in result.snapshot.revisions:
            ids = {row.candidate_evaluation_id for row in revision.training_rows}
            ids.add(revision.task.anchor_candidate_evaluation_id)
            block = schema.encode(c for c in revision.task.candidates if c.evaluation_id in ids)
            blocks.append(block.values)
        values = np.concatenate(blocks)
        scaler_weights = np.concatenate([np.full(len(block), 1 / len(block)) for block in blocks])
        mean = np.average(values, axis=0, weights=scaler_weights)
        scale = np.sqrt(np.average((values - mean) ** 2, axis=0, weights=scaler_weights))
        np.testing.assert_allclose(model.scaler["mean"], mean, atol=1e-12)
        np.testing.assert_allclose(model.scaler["scale"], scale, atol=1e-12)
        for revision in result.snapshot.revisions:
            by_id = {c.evaluation_id: c for c in revision.task.candidates}
            observed = {o.evaluation_id: o.observation.raw_sharpe for o in revision.outcomes}
            anchor = revision.task.anchor
            anchor_x = schema.encode((anchor,)).values[0]
            for row in revision.training_rows:
                candidate = by_id[row.candidate_evaluation_id]
                contrasts.append((schema.encode((candidate,)).values[0] - anchor_x) / scale)
                labels.append((candidate.observation.raw_sharpe - observed[candidate.evaluation_id])
                              - (anchor.observation.raw_sharpe - observed[anchor.evaluation_id]))
                weights.append(1 / len(revision.training_rows))
        v, y, w = np.asarray(contrasts), np.asarray(labels), np.asarray(weights)
        augmented = np.vstack((v * np.sqrt(w[:, None]), np.sqrt(10) * np.eye(v.shape[1])))
        expected = np.linalg.lstsq(augmented, np.r_[y * np.sqrt(w), np.zeros(v.shape[1])], rcond=None)[0]
        np.testing.assert_allclose(model.coefficients, expected, atol=1e-10)
        assert np.linalg.norm(expected) > 0
        predictions = {p["evaluation_id"]: p for p in result.decision.predictions}
        assert set(predictions) == {c.evaluation_id for c in task.candidates}
        assert len(predictions) == len(result.decision.ranked_ids) == 40
        anchor_x = schema.encode((result.native,)).values[0]
        for candidate in task.candidates:
            prediction = predictions[candidate.evaluation_id]
            expected_y = ((schema.encode((candidate,)).values[0] - anchor_x) / scale) @ expected
            assert prediction["yhat"] == pytest.approx(expected_y, abs=1e-10)
            assert prediction["qhat"] == pytest.approx(
                candidate.observation.raw_sharpe - result.native.observation.raw_sharpe - expected_y,
                abs=1e-10,
            )
            assert prediction["eligible"] == (prediction["qhat"] >= -.10)
        anchor_prediction = predictions[result.native.evaluation_id]
        assert (anchor_prediction["yhat"], anchor_prediction["qhat"], anchor_prediction["distance"]) == (0, 0, 0)
        assert result.selected.evaluation_id == result.decision.ranked_ids[0]
        assert result.selected is not result.native
        assert result.selected.effective_params == result.decision.proposed_params
    assert bound.native.fit.model.model_id != bound.alternate.fit.model.model_id
    assert bound.native.fit.model.family_id != bound.alternate.fit.model.family_id


def test_off_does_not_read_or_fit_and_shadow_never_applies_proposal(mature, monkeypatch):
    _, schema, revisions, _ = mature
    task, _ = task_for(13, schema=schema)
    active = process(policies_for(task, schema, history=history_from(revisions)), task)
    shadow = process(policies_for(task, schema, history=history_from(revisions), mode="shadow"), task)
    for live, passive in zip(active.families, shadow.families, strict=True):
        assert passive.decision.status == "META_MODEL_PROPOSAL"
        assert passive.decision.predictions == live.decision.predictions
        assert passive.decision.proposed_evaluation_id == live.decision.proposed_evaluation_id
        assert passive.selected is passive.native
        assert passive.decision.actual_evaluation_id == passive.native.evaluation_id
    off = policies_for(task, schema, mode="off", observer=False)

    def forbidden(*args, **kwargs):
        raise AssertionError("OFF must not touch history/numerics/learner")

    monkeypatch.setattr(MetaHistory, "snapshot", forbidden)
    monkeypatch.setattr(MetaHistoryContext, "numeric_runtime", forbidden)
    monkeypatch.setattr(RidgeLearner, "fit", forbidden)
    for result in process(off, task).families:
        assert result.snapshot is result.fit is result.decision is None
        assert result.selected is result.native
    with pytest.raises(MetaRecordError, match="not explicitly enabled"):
        off.publish_forward(active, (), revision_available_at=task.forward_end + SECOND)


def revise(revision, available, *, amount=100.0, order=None):
    outcomes = tuple(replace(
        o, observation=replace(o.observation, raw_sharpe=o.observation.raw_sharpe + amount * i,
                                output_ref=f"corrected-{o.observation.output_ref}"),
        label_available_at=available, publication_order=order,
    ) for i, o in enumerate(revision.outcomes))
    return SealedTaskRevision(
        revision.task, revision.panel, outcomes, available, revision.revision_id,
        "synthetic late source correction", order,
    )


def reidentify(revision, **changes):
    task = replace(revision.task, run_id=f"unrelated-{digest(changes)}", **changes)
    return SealedTaskRevision(
        task, replace(revision.panel, task_id=task.task_id),
        tuple(replace(o, task_id=task.task_id) for o in revision.outcomes),
        revision.revision_available_at, publication_order=revision.publication_order,
    )


def test_future_late_and_unauthorized_records_cannot_change_earlier_fit_or_scaler(mature):
    _, schema, revisions, _ = mature
    task, _ = task_for(13, schema=schema)
    baseline = process(policies_for(task, schema, history=history_from(revisions)), task)
    dirty = history_from(revisions)
    for revision in revisions[:2]:
        dirty.append(revise(revision, task.data_cutoff + SECOND))
        dirty.append(reidentify(revision, corpus_id="not-permitted"))
        dirty.append(reidentify(revision, outcome_origin="not-permitted-cohort"))
        dirty.append(reidentify(revision, research_exposure="not-permitted-exposure"))
    future, _ = task_for(18, schema=schema)
    future = replace(future, candidates=tuple(replace(
        c, observation=replace(c.observation, raw_sharpe=10_000 + i),
        effective_params={"coordinate": 1 - c.effective_params["coordinate"]},
    ) for i, c in enumerate(future.candidates)))
    future_policies = policies_for(future, schema, history=dirty, mode="off")
    publish(future_policies, process(future_policies, future))
    altered = process(policies_for(task, schema, history=dirty), task)
    for before, after in zip(baseline.families, altered.families, strict=True):
        assert before.snapshot.snapshot_id == after.snapshot.snapshot_id
        assert before.fit.model.scaler == after.fit.model.scaler
        assert before.fit.model.coefficients == after.fit.model.coefficients
        assert before.decision.predictions == after.decision.predictions
        assert before.panel.panel_id == after.panel.panel_id
        assert before.selected == after.selected
    later, _ = task_for(14, schema=schema)
    corrected = process(policies_for(later, schema, history=dirty), later)
    clean = process(policies_for(later, schema, history=history_from(revisions)), later)
    for a, b in zip(corrected.families, clean.families, strict=True):
        assert a.fit.origin_count == b.fit.origin_count == 13
        assert a.fit.model.coefficients != b.fit.model.coefficients


def test_equal_time_requires_publication_before_snapshot_order(mature):
    _, schema, revisions, _ = mature
    task, _ = task_for(13, schema=schema)
    history = history_from(revisions)
    for revision in revisions[:2]:
        history.append(revise(revision, task.data_cutoff, order=5))
    policies = policies_for(task, schema, history=history)
    absent_order = process(policies, task)
    same_order = process(policies, task, snapshot_order=5)
    ordered = process(policies, task, snapshot_order=6)
    for a, b, c in zip(absent_order.families, same_order.families, ordered.families, strict=True):
        assert a.snapshot.revisions == b.snapshot.revisions
        assert a.fit.model.coefficients == b.fit.model.coefficients
        assert a.fit.model.coefficients != c.fit.model.coefficients
        assert a.fit.origin_count == c.fit.origin_count == 12


def test_native_monthly_other_sampler_and_unpermitted_histories_cannot_support_floor(mature):
    _, schema, revisions, early = mature
    task, _ = task_for(13, schema=schema)
    history = MetaHistory()
    for revision in revisions[::2]:
        history.append(revision)
        history.append(reidentify(revision, family=task.family))
        history.append(reidentify(revision, family=replace(revision.task.family, sampler_policy_id="other")))
    policies = policies_for(task, schema, history=history)
    bound = process(policies, task)
    assert bound.native.fit.origin_count == 12 and bound.native.fit.model is not None
    assert bound.alternate.fit.origin_count == 0 and bound.alternate.fit.model is None
    assert bound.alternate.selected is bound.alternate.native
    assert early[0].native.task.family != task.family
    # Actually monthly windows cannot be imported even by relabelling a family.
    old = revisions[1]
    monthly_task = replace(old.task, forward_end=old.task.forward_start + pd.Timedelta(days=28))
    monthly = SealedTaskRevision(
        monthly_task, replace(old.panel, task_id=monthly_task.task_id),
        tuple(replace(o, task_id=monthly_task.task_id,
                      observation=replace(o.observation, window_end=monthly_task.forward_end,
                                          input_frontier=monthly_task.forward_end)) for o in old.outcomes),
        old.revision_available_at,
    )
    history.append(monthly)
    with pytest.raises(MetaRecordError, match="19-quarter"):
        process(policies, task)


@pytest.mark.parametrize("problem", ["missing", "duplicate", "extra", "wrong-task", "wrong-lag", "pending"])
def test_publication_rejects_incomplete_or_unbound_union_before_any_append(problem):
    task, schema = task_for()
    policies = policies_for(task, schema)
    bound = process(policies, task)
    records = list(forward_records(bound))
    if problem == "missing":
        records.pop()
    elif problem == "duplicate":
        records.append(records[0])
    elif problem == "extra":
        records.append(replace(records[0], evaluation_id="uncaptured"))
    elif problem == "wrong-task":
        records[0] = replace(records[0], task_id="another-task")
    elif problem == "wrong-lag":
        records[0] = replace(records[0], reporting_lag_seconds=0)
    else:
        records[0] = replace(records[0], observation=replace(records[0].observation,
                             status=OutcomeStatus.PENDING), label_available_at=None)
    with pytest.raises(MetaRecordError):
        policies.publish_forward(bound, records, revision_available_at=task.forward_end + SECOND)
    later, _ = task_for(2, schema=schema)
    assert all(not r.snapshot.revisions for r in process(policies, later).families)


def test_late_last_required_label_delays_origin_and_invalid_anchor_never_makes_zero_rows(mature):
    _, schema, revisions, _ = mature
    task, _ = task_for(13, schema=schema)
    # Delay one complete origin in each family beyond the first possible fit.
    kept = revisions[:22] + revisions[24:]
    history = history_from(kept)
    for revision in revisions[22:24]:
        delayed = replace(revision, outcomes=tuple(replace(o, label_available_at=task.data_cutoff + SECOND)
                                                  for o in revision.outcomes),
                          revision_available_at=task.data_cutoff + SECOND)
        history.append(delayed)
    for result in process(policies_for(task, schema, history=history), task).families:
        assert result.fit.origin_count == 11 and result.fit.model is None
    fresh, _ = task_for(schema=schema)
    policies = policies_for(fresh, schema)
    bound = process(policies, fresh)
    records = tuple(replace(o, observation=replace(o.observation,
                    status=OutcomeStatus.OUTCOME_FAILED, raw_sharpe=None, sample_count=0, sample_std=None))
                    if o.evaluation_id == fresh.anchor_candidate_evaluation_id else o
                    for o in forward_records(bound))
    native, alternate = policies.publish_forward(bound, records,
                                                 revision_available_at=fresh.forward_end + SECOND)
    assert native.training_rows == ()
    assert alternate.training_rows
    assert all(row.candidate_evaluation_id != fresh.anchor_candidate_evaluation_id
               for row in alternate.training_rows)
    assert sum(row.origin_weight for row in alternate.training_rows) == pytest.approx(1)


def test_pool_permutations_and_exact_lexical_ties_use_existing_selector(mature):
    policies, schema, _, _ = mature
    task, _ = task_for(13, schema=schema)
    best = task.candidates[-1]
    duplicate = replace(best, evaluation_id="lexical-tie-evaluation", candidate_id="aaa-lexical-tie")
    task = replace(task, candidates=task.candidates + (duplicate,))
    bound = process(policies, task, alternate=False)
    shuffled = process(policies, replace(task, candidates=tuple(reversed(task.candidates)),
                                         roles=tuple(reversed(task.roles))), alternate=False)
    assert bound.native.selected.evaluation_id == duplicate.evaluation_id
    assert bound.native.decision.predictions == shuffled.native.decision.predictions
    assert bound.native.decision.tie_set == shuffled.native.decision.tie_set
    assert bound.query_panel.panel_id == shuffled.query_panel.panel_id
    assert bound.alternate is None and len(bound.query_panel.members) <= 18


def test_compact_ranking_still_scores_the_whole_current_eligible_pool(mature):
    _, schema, revisions, _ = mature
    task, _ = task_for(13, schema=schema)
    policies = policies_for(task, schema, history=history_from(revisions))
    compact = ResearchPolicies(
        base_family=task.family, context=policies.context, schema=schema,
        config=replace(policies.config, full_ranking=False),
    )
    detailed, minimal = process(policies, task), process(compact, task)
    for full, small in zip(detailed.families, minimal.families, strict=True):
        assert len(small.decision.predictions) == len(task.candidates) > 16
        assert small.decision.ranked_ids == ()
        assert full.decision.predictions == small.decision.predictions
        assert full.selected == small.selected
    assert any(not p["eligible"] for p in minimal.alternate.decision.predictions)


def test_undefined_current_anchor_retains_native_without_fabricating_predictions(mature):
    _, schema, revisions, _ = mature
    task, _ = task_for(13, schema=schema)
    original = task.anchor
    bad_anchor = replace(original, observation=replace(
        original.observation, status=OutcomeStatus.NO_VARIANCE, raw_sharpe=None, sample_std=0,
    ))
    task = replace(task, candidates=(bad_anchor,) + task.candidates[1:])
    result = process(policies_for(task, schema, history=history_from(revisions)), task,
                     alternate=False).native
    assert result.fit.model is not None
    assert result.decision.status == "META_NOT_APPLICABLE_METRIC"
    assert result.decision.predictions == ()
    assert result.selected is bad_anchor


def test_full_pool_constant_feature_ood_retains_native_fallback():
    task, schema = task_for(n=6)
    policies = policies_for(task, schema)
    for index in range(13):
        task, _ = task_for(index, n=6, schema=schema)
        task = replace(task, candidates=tuple(replace(c, observation=replace(c.observation, activity_count=10))
                                              for c in task.candidates))
        publish(policies, process(policies, task, alternate=False))
    current, _ = task_for(13, n=6, schema=schema)
    result = process(policies, current, alternate=False).native
    assert result.fit.model is not None and result.fit.origin_count == 12
    assert result.decision.status == "META_OOD_NATIVE_FALLBACK"
    assert result.selected is result.native


@pytest.mark.parametrize("change", [dict(min_matured_origins=11), dict(lambda_reg=1),
                                   dict(q_hat_floor=-.2), dict(reporting_lag_seconds=0)])
def test_registered_math_and_lag_cannot_be_weakened(change):
    task, schema = task_for()
    with pytest.raises(MetaRecordError, match="research fixes"):
        policies_for(task, schema, **change)


def test_clock_calendar_schema_and_physical_rebase_errors_are_not_fallbacks():
    task, schema = task_for()
    policies = policies_for(task, schema)
    with pytest.raises(MetaRecordError, match="captured IS pool"):
        policies.process_task(task, information_as_of=task.data_cutoff,
                              alternate_anchor_evaluation_id="not-captured")
    with pytest.raises(MetaRecordError, match="frontier"):
        policies.process_task(task, information_as_of=task.data_cutoff + SECOND)
    with pytest.raises(MetaRecordError, match="fit completion"):
        policies.process_task(task, information_as_of=task.data_cutoff,
                              fit_completed_at=task.decision_sealed_at + SECOND)
    with pytest.raises(MetaRecordError, match="fit completion"):
        policies.process_task(task, information_as_of=task.data_cutoff)
    with pytest.raises(MetaRecordError, match="physical compatibility"):
        rebase_task(task, family=replace(policies.native.family, economics_id="other"),
                    anchor_evaluation_id=task.anchor_candidate_evaluation_id)
    wrong = replace(task, forward_end=task.forward_end - pd.Timedelta(days=1))
    with pytest.raises(MetaRecordError, match="19-quarter"):
        process(policies, wrong)
    with pytest.raises(MetaRecordError, match="descriptor schema"):
        policies_for(task, DescriptorSchema({"other": (0.0, 1.0)}))
    assert digest(task) == digest(process(policies, task).base_task)
