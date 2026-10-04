"""Q3-T01..08: isolated record/time algebra; financial proof is separate."""

from dataclasses import replace
import json

import numpy as np
import pandas as pd
import pytest

from quantbt.optimization.meta_selection import (
    CandidateForwardRecord,
    CandidateISRecord,
    CandidateRoleRef,
    CompatibilityFamily,
    MetaRecordError,
    MetaTask,
    MetricObservation,
    OutcomeStatus,
)
from quantbt.optimization.meta_selection.common import digest, wire
from quantbt.optimization.meta_selection.descriptors import (
    DescriptorSchema,
    OriginBalancedStandardizer,
)
from quantbt.optimization.meta_selection.history import MetaHistory, SealedTaskRevision
from quantbt.optimization.meta_selection.panel import freeze_panel
from quantbt.optimization.meta_selection.persistence import (
    dumps_revision,
    loads_revision,
    retention_chunk,
    restore_chunk,
)


RANGES = {
    "hma_length": (2, 100, 1),
    "smooth": ["ema", "sma", "wma"],
    "filter": [True, False],
    "threshold": {
        "kind": "float",
        "low": 0.1,
        "high": 10.0,
        "log": True,
        "active_if": {"filter": [True]},
    },
    "degree": 2,
}


def stamp(value):
    return pd.Timestamp(value, tz="UTC")


def make_task(
    n=4, *, year=2020, corpus="approved", run="research", seed=71, schema=None
):
    schema = schema or DescriptorSchema(RANGES)
    family = CompatibilityFamily(
        "hma-strategy-v1",
        schema.space.identity,
        schema.schema_id,
        "ETHUSDT-linear-binance",
        "1h",
        "rolling-365D-forward-90D",
        "metric-v1",
        "economics-v1",
        "fresh-account-endpoint",
        "mode4-causal-medoid-v1",
        "tpe_legacy-v1",
        "independent-reset-v1",
    )
    is_start, is_end = stamp(f"{year}-01-01"), stamp(f"{year}-12-31")
    forward_start, forward_end = stamp(f"{year + 1}-01-01"), stamp(f"{year + 1}-03-31")
    resolved = is_end + pd.Timedelta(hours=1)
    candidates = []
    for i in range(n):
        params = {
            "hma_length": 3 + i,
            "smooth": ("ema", "sma", "wma")[i % 3],
            "filter": bool(i % 2),
            "degree": 2,
        }
        if params["filter"]:
            params["threshold"] = 0.1 + i * 0.1
        observation = MetricObservation(
            OutcomeStatus.VALID,
            i / 10,
            10 + i,
            364,
            0.1,
            family.metric_contract_id,
            family.economics_id,
            is_start,
            is_end,
            is_end,
            20_000.0,
            20_000.0,
            f"is-output-{year}-{i}",
            f"is-market-{year}",
            "original_result",
        )
        candidates.append(
            CandidateISRecord(
                f"evaluation-{year}-{i}",
                f"candidate-{i}",
                i,
                params,
                params,
                i / 20,
                observation,
                resolved,
                {},
            )
        )
    task = MetaTask(
        family,
        corpus,
        run,
        is_end,
        is_start,
        is_end,
        forward_start,
        forward_end,
        is_end,
        seed,
        tuple(candidates),
        candidates[0].evaluation_id,
        (CandidateRoleRef("native_anchor", "mode4", candidates[0].evaluation_id),),
        resolved,
        resolved,
        resolved + pd.Timedelta(minutes=1),
        forward_start,
        stamp("2026-10-04"),
        "historical_replay",
        "synthetic_counterfactual",
        "research_only",
        {},
    )
    return task, schema


def revision_for(task, schema, *, status_by_id=None, parent=None, available=None):
    panel = freeze_panel(task, schema, sealed_at=task.decision_sealed_at)
    available = available or task.forward_end + pd.Timedelta(hours=1)
    statuses = status_by_id or {}
    outcomes = []
    for candidate in task.candidates:
        if candidate.evaluation_id not in panel.members:
            continue
        status = statuses.get(candidate.evaluation_id, OutcomeStatus.VALID)
        m = replace(
            candidate.observation,
            window_start=task.forward_start,
            window_end=task.forward_end,
            input_frontier=task.forward_end,
            raw_sharpe=0.2 - candidate.native_trial_id / 20,
            output_ref=f"forward-output-{task.origin.year}-{candidate.native_trial_id}",
            status=status,
        )
        if status != OutcomeStatus.VALID:
            m = replace(m, raw_sharpe=None, sample_std=None, sample_count=0)
        outcomes.append(
            CandidateForwardRecord(
                task.task_id, candidate.evaluation_id, m, available, 3600
            )
        )
    return SealedTaskRevision(
        task,
        panel,
        tuple(outcomes),
        available,
        parent.revision_id if parent else None,
        "reviewed late correction" if parent else None,
    )


def snapshot(history, task, cutoff, **kwargs):
    return history.snapshot(
        family_id=task.family.family_id,
        authorized_corpora=(task.corpus_id,),
        outcome_origins=(task.outcome_origin,),
        research_exposures=(task.research_exposure,),
        information_as_of=cutoff,
        **kwargs,
    )


def witnesses(revision):
    observations = [c.observation for c in revision.task.candidates] + [
        o.observation for o in revision.outcomes
    ]
    return {o.output_ref: digest(o) for o in observations}


def test_q3_t01_explicit_anchor_roles_order_and_identical_parameter_evaluations():
    task, schema = make_task()
    duplicate = replace(
        task.candidates[0],
        evaluation_id="same-params-new-stochastic-evaluation",
        native_trial_id=40,
    )
    changed = replace(
        task,
        candidates=(duplicate,) + tuple(reversed(task.candidates)),
        roles=(CandidateRoleRef("STATIC", "static-v1", duplicate.evaluation_id),)
        + task.roles,
    )
    assert changed.anchor == task.anchor
    assert changed.task_id != task.task_id
    panel = freeze_panel(changed, schema, sealed_at=changed.decision_sealed_at)
    assert panel.base_members[0] == task.anchor_candidate_evaluation_id
    assert duplicate.evaluation_id in panel.members
    assert all(not hasattr(c, "is_anchor") for c in task.candidates)
    reordered = replace(task, candidates=tuple(reversed(task.candidates)))
    assert reordered.task_id == task.task_id
    assert freeze_panel(
        reordered, schema, sealed_at=task.decision_sealed_at
    ) == freeze_panel(task, schema, sealed_at=task.decision_sealed_at)


@pytest.mark.parametrize(
    "change",
    ["missing", "duplicate_candidate", "missing_role", "double_role", "unknown_role"],
)
def test_q3_t01_invalid_anchor_rejected(change):
    task, _ = make_task()
    with pytest.raises(MetaRecordError):
        if change == "missing":
            replace(task, anchor_candidate_evaluation_id="missing")
        elif change == "duplicate_candidate":
            replace(task, candidates=task.candidates + (task.anchor,))
        elif change == "missing_role":
            replace(task, roles=())
        elif change == "double_role":
            replace(task, roles=task.roles * 2)
        else:
            replace(
                task, roles=task.roles + (CandidateRoleRef("STATIC", "s", "unknown"),)
            )


def test_q3_t01_panel_quotas_required_union_and_outcome_blind_membership():
    task, schema = make_task(40)
    base = freeze_panel(task, schema, sealed_at=task.decision_sealed_at)
    roles = [role for role, _ in base.quota_roles]
    assert (
        roles.count("anchor") == 1
        and roles.count("top")
        == roles.count("diversity")
        == roles.count("control")
        == 5
    )
    extras = tuple(
        c.evaluation_id for c in task.candidates if c.evaluation_id not in base.members
    )[:3]
    union = freeze_panel(
        task, schema, sealed_at=task.decision_sealed_at, required_winners=extras
    )
    assert union.base_members == base.base_members
    assert len(union.members) == 19 and set(union.extra_union_members) == set(extras)
    with pytest.raises(MetaRecordError):
        freeze_panel(
            task,
            schema,
            sealed_at=task.first_forward_action_at + pd.Timedelta(seconds=1),
        )


def test_q3_t01_same_physical_evaluation_can_have_two_roles_without_double_weight():
    task, schema = make_task()
    shared = replace(
        task,
        roles=task.roles
        + (
            CandidateRoleRef(
                "STATIC",
                "approved-exact-evaluation-reuse",
                task.anchor_candidate_evaluation_id,
            ),
        ),
    )
    before, after = revision_for(task, schema), revision_for(shared, schema)
    assert task.task_id == shared.task_id
    assert len(after.training_rows) == len(before.training_rows)
    assert [r.origin_weight for r in after.training_rows] == [
        r.origin_weight for r in before.training_rows
    ]


def test_q3_t02_raw_label_algebra_and_penalized_objective_not_substituted():
    task, schema = make_task()
    revision = revision_for(task, schema)
    for row in revision.training_rows:
        assert row.decay == pytest.approx(row.raw_is - row.raw_forward)
        assert row.y == pytest.approx(row.decay - (row.anchor_is - row.anchor_forward))
        assert row.q == pytest.approx(row.raw_forward - row.anchor_forward)
        candidate = next(
            c for c in task.candidates if c.evaluation_id == row.candidate_evaluation_id
        )
        assert row.raw_is != candidate.objective
    assert sum(row.origin_weight for row in revision.training_rows) == pytest.approx(1)


@pytest.mark.parametrize(
    "field,value",
    [
        ("economics_id", "different-cost"),
        ("metric_contract_id", "different-rf"),
        ("initial_capital", 10_000),
        ("window_start", stamp("2021-01-02")),
    ],
)
def test_q3_t02_cross_origin_contracts_rejected(field, value):
    task, schema = make_task()
    revision = revision_for(task, schema)
    changed = replace(
        revision.outcomes[0],
        observation=replace(revision.outcomes[0].observation, **{field: value}),
    )
    with pytest.raises(MetaRecordError):
        replace(revision, outcomes=(changed,) + revision.outcomes[1:])


def test_q3_t03_frozen_snapshot_excludes_arrivals_during_compute_and_equality():
    task, schema = make_task()
    revision = revision_for(task, schema)
    history = MetaHistory()
    cutoff = revision.revision_available_at
    frozen = snapshot(history, task, cutoff)
    history.append(revision)
    assert not frozen.revisions and not snapshot(history, task, cutoff).revisions
    visible = snapshot(history, task, cutoff + pd.Timedelta(seconds=1))
    assert visible.origin_count == 1 and visible.snapshot_id != frozen.snapshot_id
    ordered = replace(
        revision,
        publication_order=3,
        outcomes=tuple(replace(o, publication_order=2) for o in revision.outcomes),
    )
    store = MetaHistory()
    store.append(ordered)
    assert not snapshot(store, task, cutoff, snapshot_order=3).revisions
    assert snapshot(store, task, cutoff, snapshot_order=4).origin_count == 1


def test_q3_t03_revision_frontier_and_computation_after_cutoff():
    task, schema = make_task()
    assert task.search_completed_at > task.data_cutoff
    first = revision_for(task, schema)
    second = revision_for(
        task,
        schema,
        parent=first,
        available=first.revision_available_at + pd.Timedelta(days=20),
    )
    history = MetaHistory()
    history.append(first)
    frozen = snapshot(history, task, first.revision_available_at + pd.Timedelta(days=1))
    history.append(second)
    assert (
        snapshot(history, task, frozen.information_as_of).snapshot_id
        == frozen.snapshot_id
    )
    assert frozen.revisions == (first,)
    assert snapshot(
        history, task, second.revision_available_at + pd.Timedelta(seconds=1)
    ).revisions == (second,)


def test_q3_t03_reporting_lag_is_not_actual_availability_or_revision_publication():
    task, schema = make_task()
    revision = revision_for(
        task, schema, available=task.forward_end + pd.Timedelta(days=10)
    )
    history = MetaHistory()
    history.append(revision)
    assert not snapshot(
        history, task, task.forward_end + pd.Timedelta(days=1)
    ).revisions
    with pytest.raises(MetaRecordError, match="lag"):
        replace(revision.outcomes[0], label_available_at=task.forward_end)
    with pytest.raises(MetaRecordError, match="availability"):
        replace(revision, revision_available_at=task.forward_end + pd.Timedelta(days=1))


@pytest.mark.parametrize(
    "field",
    [
        "search_completed_at",
        "decision_sealed_at",
        "first_forward_action_at",
        "data_cutoff",
    ],
)
def test_q3_t03_invalid_clocks_fail_closed(field):
    task, _ = make_task()
    value = task.is_start if field != "data_cutoff" else task.forward_end
    with pytest.raises(MetaRecordError):
        replace(task, **{field: value})


def test_q3_t04_category_geometry_permutation_and_activity_masks():
    task, schema = make_task()
    geometry = schema.parameter_geometry(task.candidates)
    permuted = DescriptorSchema({**RANGES, "smooth": ["wma", "ema", "sma"]})
    alternate = permuted.parameter_geometry(task.candidates)

    def distance(x):
        return ((x[:, None] - x[None, :]) ** 2).sum(axis=2)

    np.testing.assert_allclose(distance(geometry), distance(alternate))
    assert schema.schema_id != permuted.schema_id
    batch = schema.encode(task.candidates)
    inactive = schema.feature_names.index("threshold:numeric")
    flag = schema.feature_names.index("threshold:active")
    assert (
        not batch.active[0, inactive]
        and batch.values[0, inactive] == batch.values[0, flag] == 0
    )
    assert batch.active[1, inactive] and batch.values[1, flag] == 1
    assert not any("degree" in name for name in schema.feature_names)
    assert batch.values.dtype == np.float64 and batch.values.flags.c_contiguous
    with pytest.raises(ValueError):
        batch.values.flags.writeable = True
    with pytest.raises(ValueError):
        schema.encode(
            (
                replace(
                    task.anchor,
                    effective_params={
                        **task.anchor.effective_params,
                        "smooth": "unknown",
                    },
                ),
            )
        )


def test_q3_t04_origin_balanced_scaling_constant_support_and_no_shape_padding():
    task, schema = make_task(3)
    next_task, _ = make_task(10, year=2021, schema=schema)
    store = MetaHistory()
    revisions = (revision_for(task, schema), revision_for(next_task, schema))
    for revision in revisions:
        store.append(revision)
    view = snapshot(store, task, stamp("2024-01-01"))
    scaler = OriginBalancedStandardizer.fit(schema, view)
    sharpe_col = schema.feature_names.index("raw_is_sharpe")
    assert scaler.mean[sharpe_col] == pytest.approx((0.1 + 0.45) / 2)
    batch = schema.encode(task.candidates)
    transformed, unsupported = scaler.transform(batch)
    assert np.isfinite(transformed).all() and not unsupported.any()
    with pytest.raises(MetaRecordError):
        scaler.transform(replace(batch, schema_id="other"))
    with pytest.raises(MetaRecordError):
        replace(batch, values=batch.values[:, :-1])
    with pytest.raises(MetaRecordError):
        OriginBalancedStandardizer.fit(schema, ())
    constant_task = replace(
        task,
        candidates=tuple(
            replace(c, observation=replace(c.observation, raw_sharpe=0.0))
            for c in task.candidates
        ),
    )
    constant_store = MetaHistory()
    constant_store.append(revision_for(constant_task, schema))
    constant = OriginBalancedStandardizer.fit(
        schema, snapshot(constant_store, constant_task, stamp("2024-01-01"))
    )
    assert constant.constant[sharpe_col] and constant.scale[sharpe_col] == 1
    _, unsupported = constant.transform(batch)
    assert unsupported.tolist() == [False, True, True]


def test_q3_t04_scaler_reads_only_permitted_historical_is_not_forward_label_magnitudes():
    task, schema = make_task()
    first = revision_for(task, schema)
    other = replace(
        first,
        outcomes=tuple(
            replace(o, observation=replace(o.observation, raw_sharpe=1000))
            for o in first.outcomes
        ),
    )
    scalers = []
    for revision in (first, other):
        history = MetaHistory()
        history.append(revision)
        scalers.append(
            OriginBalancedStandardizer.fit(
                schema, snapshot(history, task, stamp("2025-01-01"))
            )
        )
    np.testing.assert_array_equal(scalers[0].mean, scalers[1].mean)
    np.testing.assert_array_equal(scalers[0].scale, scalers[1].scale)
    assert scalers[0].training_snapshot_id != scalers[1].training_snapshot_id


def test_q3_t04_conditional_feature_without_historical_support_is_explicitly_unsupported():
    task, schema = make_task()
    task = replace(
        task,
        candidates=tuple(
            replace(c, effective_params={**c.effective_params, "filter": False})
            for c in task.candidates
        ),
    )
    store = MetaHistory()
    store.append(revision_for(task, schema))
    scaler = OriginBalancedStandardizer.fit(
        schema, snapshot(store, task, stamp("2025-01-01"))
    )
    current, _ = make_task()
    _, unsupported = scaler.transform(schema.encode(current.candidates))
    assert unsupported.tolist() == [False, True, False, True]


def test_q3_t05_hma_keys_numeric_log_and_identity_not_alpha_specific():
    task, schema = make_task()
    geometry = schema.parameter_geometry(task.candidates)
    assert np.linalg.norm(geometry[1] - geometry[0]) > 0
    assert all(
        not any(key in name for key in ("rsi", "atr", "ASC"))
        for name in schema.feature_names
    )
    encoded = schema.encode(task.candidates)
    col = schema.feature_names.index("threshold:numeric")
    assert encoded.values[1, col] == pytest.approx(np.log(0.2 / 0.1) / np.log(10 / 0.1))
    with pytest.raises(NotImplementedError, match="CAPABILITY_MISSING"):
        DescriptorSchema(RANGES, native_policy="require")
    assert (
        schema.backend["selected"] == "numpy_reference"
        and schema.backend["ffi_calls"] == 0
    )


@pytest.mark.parametrize(
    "status",
    [
        OutcomeStatus.OUTCOME_FAILED,
        OutcomeStatus.INCOMPLETE_WINDOW,
        OutcomeStatus.CENSORED,
        OutcomeStatus.NO_VARIANCE,
        OutcomeStatus.INSUFFICIENT_SAMPLE,
        OutcomeStatus.UNVERIFIED,
    ],
)
def test_q3_t06_nontraining_dispositions_never_become_zero_labels(status):
    task, schema = make_task()
    revision = revision_for(
        task, schema, status_by_id={task.candidates[1].evaluation_id: status}
    )
    assert len(revision.training_rows) == 2
    assert all(
        row.candidate_evaluation_id != task.candidates[1].evaluation_id
        for row in revision.training_rows
    )
    anchor_invalid = revision_for(
        task, schema, status_by_id={task.anchor_candidate_evaluation_id: status}
    )
    assert not anchor_invalid.training_rows


def test_q3_t06_valid_zero_vs_placeholder_variance():
    task, schema = make_task()
    assert (
        task.anchor.observation.raw_sharpe == 0
        and schema.encode(task.candidates).valid[0]
    )
    with pytest.raises(MetaRecordError):
        replace(task.anchor.observation, sample_std=0)
    with pytest.raises(MetaRecordError):
        replace(task.anchor.observation, verification="unverified")
    invalid = replace(
        task.anchor,
        observation=replace(
            task.anchor.observation, status=OutcomeStatus.NO_VARIANCE, sample_std=0
        ),
    )
    batch = schema.encode((invalid,))
    assert not batch.valid[0] and np.isnan(batch.values[0, -1])


def test_q3_t07_task_family_snapshot_and_authorized_corpus_are_distinct():
    task, schema = make_task()
    later, _ = make_task(year=2021, seed=999, schema=schema)
    private, _ = make_task(
        year=2022, corpus="unapproved", run="another-run", schema=schema
    )
    assert task.family.family_id == later.family.family_id == private.family.family_id
    assert len({task.task_id, later.task_id, private.task_id}) == 3
    store = MetaHistory()
    for item in (task, later, private):
        store.append(revision_for(item, schema))
    view = snapshot(store, task, stamp("2025-01-01"))
    assert view.origin_count == 2 and all(
        r.task.corpus_id == "approved" for r in view.revisions
    )
    for field in task.family.__dataclass_fields__:
        other = replace(
            task.family, **{field: getattr(task.family, field) + "-different"}
        )
        assert not store.snapshot(
            family_id=other.family_id,
            authorized_corpora=("approved",),
            outcome_origins=(task.outcome_origin,),
            research_exposures=(task.research_exposure,),
            information_as_of=stamp("2025-01-01"),
        ).revisions
    with pytest.raises(MetaRecordError):
        replace(view, authorized_corpora=("unapproved",))
    with pytest.raises(MetaRecordError):
        replace(view, revisions=(view.revisions[0], view.revisions[0]))


def test_q3_t08_safe_roundtrip_witness_policy_and_existing_retention():
    task, schema = make_task()
    revision = revision_for(task, schema)
    text = dumps_revision(revision)
    restored = loads_revision(
        text,
        verified_output_witnesses=witnesses(revision),
        reviewed_revision_ids=(revision.revision_id,),
    )
    assert restored.revision_id == revision.revision_id and wire(restored) == wire(
        revision
    )
    imported = loads_revision(text)
    assert imported.verification == "unverified" and not imported.training_rows
    store = MetaHistory()
    store.append(imported)
    assert not snapshot(store, task, stamp("2025-01-01")).revisions
    chunk = retention_chunk(revision, chunk_id="qms03-history-1")
    assert (
        restore_chunk(
            chunk,
            expected_logical_digest=chunk.logical_digest,
            verified_output_witnesses=witnesses(revision),
            reviewed_revision_ids=(revision.revision_id,),
        )[0].revision_id
        == revision.revision_id
    )
    with pytest.raises(MetaRecordError):
        restore_chunk(chunk, expected_logical_digest="tampered")


def test_q3_t08_rehashed_raw_metric_is_not_verified_by_reusing_an_output_reference():
    task, schema = make_task()
    revision = revision_for(task, schema)
    document = json.loads(dumps_revision(revision))
    document["payload"]["outcomes"][0]["observation"]["raw_sharpe"] += 1
    document["content_digest"] = digest(document["payload"])
    with pytest.raises(MetaRecordError, match="witness mismatch"):
        loads_revision(
            json.dumps(document), verified_output_witnesses=witnesses(revision)
        )
    unverified = loads_revision(json.dumps(document))
    assert not unverified.training_rows
    with pytest.raises(MetaRecordError, match="observation digests"):
        loads_revision(
            dumps_revision(revision), verified_output_witnesses=set(witnesses(revision))
        )


@pytest.mark.parametrize(
    "corruption",
    [
        "schema",
        "hash",
        "payload",
        "missing",
        "extra",
        "NaN",
        "duplicate",
        "oversize",
        "pickle",
    ],
)
def test_q3_t08_checkpoint_corruption_raises(corruption):
    task, schema = make_task()
    text = dumps_revision(revision_for(task, schema))
    document = json.loads(text)
    if corruption in {"schema", "hash", "payload"}:
        if corruption == "schema":
            document["schema"] = "unknown"
        elif corruption == "hash":
            document["content_digest"] = "wrong"
        else:
            document["payload"]["task"]["resolved_fold_seed"] += 1
        text = json.dumps(document)
    elif corruption in {"missing", "extra"}:
        if corruption == "missing":
            del document["payload"]["task"]["corpus_id"]
        else:
            document["payload"]["task"]["evil"] = True
        document["content_digest"] = digest(document["payload"])
        text = json.dumps(document)
    elif corruption == "NaN":
        text = '{"payload": NaN}'
    elif corruption == "duplicate":
        text = '{"schema":"a","schema":"b"}'
    elif corruption == "pickle":
        text = "gASVpickle-content"
    with pytest.raises(MetaRecordError):
        loads_revision(text, max_bytes=1 if corruption == "oversize" else 16_000_000)


def test_q3_t08_pending_maturity_revisions_reweight_entire_origin_and_freeze_old_view():
    task, schema = make_task(11)
    failed = {
        c.evaluation_id: OutcomeStatus.OUTCOME_FAILED for c in task.candidates[2:]
    }
    first = revision_for(task, schema, status_by_id=failed)
    store = MetaHistory(max_revisions=10)
    pending = replace(
        first.outcomes[1],
        label_available_at=None,
        observation=replace(
            first.outcomes[1].observation,
            status=OutcomeStatus.PENDING,
            raw_sharpe=None,
            sample_std=None,
            sample_count=0,
        ),
    )
    store.retain_pending(pending)
    with pytest.raises(MetaRecordError, match="PENDING"):
        replace(first, outcomes=(first.outcomes[0], pending) + first.outcomes[2:])
    assert len(store.pending) == 1
    store.append(first)
    assert not store.pending
    earlier = snapshot(
        store, task, first.revision_available_at + pd.Timedelta(seconds=1)
    )
    assert (
        len(earlier.training_rows) == 1 and earlier.training_rows[0].origin_weight == 1
    )
    second = revision_for(
        task,
        schema,
        parent=first,
        available=first.revision_available_at + pd.Timedelta(days=3),
    )
    store.append(second)
    assert store.append(second) == second.revision_id
    latest = snapshot(
        store, task, second.revision_available_at + pd.Timedelta(seconds=1)
    )
    assert latest.origin_count == 1 and len(latest.training_rows) == 10
    assert all(row.origin_weight == 0.1 for row in latest.training_rows)
    assert earlier.training_rows[0].origin_weight == 1 and earlier.revisions == (first,)
    assert latest.snapshot_id != earlier.snapshot_id
    with pytest.raises(MetaRecordError):
        store.append(
            replace(
                first,
                revision_available_at=second.revision_available_at
                + pd.Timedelta(days=1),
            )
        )


def test_q3_t08_bounded_history_no_eviction_or_origin_support_inflation():
    task, schema = make_task()
    store = MetaHistory(max_revisions=1)
    first = revision_for(task, schema)
    store.append(first)
    with pytest.raises(MetaRecordError, match="capacity"):
        store.append(
            revision_for(
                task,
                schema,
                parent=first,
                available=first.revision_available_at + pd.Timedelta(days=1),
            )
        )
    assert snapshot(store, task, stamp("2025-01-01")).revisions == (first,)
    duplicated_run = replace(task, run_id="another-study-same-origin")
    unlimited = MetaHistory()
    unlimited.append(first)
    unlimited.append(revision_for(duplicated_run, schema))
    with pytest.raises(MetaRecordError, match="origin"):
        snapshot(unlimited, task, stamp("2025-01-01"))


def test_q3_t08_pending_does_not_invent_availability_and_retires_at_capacity():
    task, schema = make_task()
    revision = revision_for(task, schema)
    pending = replace(
        revision.outcomes[0],
        label_available_at=None,
        observation=replace(
            revision.outcomes[0].observation,
            status=OutcomeStatus.PENDING,
            raw_sharpe=None,
        ),
    )
    assert pending.nominal_maturity_at == task.forward_end + pd.Timedelta(hours=1)
    with pytest.raises(MetaRecordError, match="actual label availability"):
        replace(pending, label_available_at=pending.nominal_maturity_at)
    store = MetaHistory(max_revisions=1)
    store.retain_pending(pending)
    store.append(revision)
    assert not store.pending
    assert snapshot(store, task, stamp("2025-01-01")).origin_count == 1
