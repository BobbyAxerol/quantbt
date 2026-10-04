"""Q4-T01..08: independent math, immutable history, actual numeric policy."""

from dataclasses import replace
import json
import os
from pathlib import Path

import numpy as np
import pytest

from quantbt.optimization.meta_selection.artifacts import (
    dumps_model,
    loads_model,
    dumps_decision,
    loads_decision,
)
from quantbt.optimization.meta_selection.common import MetaRecordError, digest
from quantbt.optimization.meta_selection.descriptors import (
    DescriptorSchema,
    OriginBalancedStandardizer,
)
from quantbt.optimization.meta_selection.history import MetaHistory
from quantbt.optimization.meta_selection.model import (
    RidgeLearner,
    RidgeSettings,
    FitOutcome,
)
from quantbt.optimization.meta_selection.numerics import (
    NumericLimits,
    NumericRuntime,
    reference_fit,
    solution_diagnostics,
)
from quantbt.optimization.meta_selection.selection import (
    MetaSelector,
    select_indices,
    rank_decision,
)
from quantbt.optimization.meta_selection.records import OutcomeStatus
from tests.meta_selection.test_qms03_history import make_task, revision_for, stamp


def snapshot(revisions, *, cutoff="2023-12-31", extra=()):
    history = MetaHistory()
    for revision in revisions + tuple(extra):
        history.append(revision)
    task = revisions[0].task
    return history.snapshot(
        family_id=task.family.family_id,
        authorized_corpora=(task.corpus_id,),
        outcome_origins=(task.outcome_origin,),
        research_exposures=(task.research_exposure,),
        information_as_of=stamp(cutoff),
    )


def historical_fit(runtime=None):
    pairs = [make_task(n=6, year=y) for y in (2020, 2021, 2022)]
    schema = pairs[0][1]
    revisions = tuple(revision_for(t, s) for t, s in pairs)
    past = snapshot(revisions)
    fit = RidgeLearner(
        settings=RidgeSettings(min_matured_origins=3),
        runtime=runtime or NumericRuntime(native_policy="reference"),
    ).fit(
        schema,
        past,
        fit_completed_at=stamp("2023-12-31")
        + __import__("pandas").Timedelta(minutes=1),
    )
    current, _ = make_task(n=6, year=2023, schema=schema)
    return schema, revisions, past, fit, current


@pytest.fixture
def trained():
    return historical_fit()


@pytest.mark.parametrize("n,d", [(1, 1), (17, 3), (57, 8), (64, 40)])
def test_q4_t01_whitened_reference_and_augmented_lstsq(n, d):
    rng = np.random.default_rng(702)
    v, y, w = rng.normal(size=(n, d)), rng.normal(size=n), rng.uniform(0.1, 1, size=n)
    g, b, beta = reference_fit(v, y, w, 10.0)
    augmented = np.vstack([v * np.sqrt(w[:, None]), np.eye(d) * np.sqrt(10.0)])
    labels = np.concatenate([y * np.sqrt(w), np.zeros(d)])
    expected = np.linalg.lstsq(augmented, labels, rcond=None)[0]
    assert np.allclose(beta, expected, rtol=1e-9, atol=1e-10)
    assert np.allclose(
        g, (v * np.sqrt(w[:, None])).T @ (v * np.sqrt(w[:, None])) + 10 * np.eye(d)
    )
    assert np.allclose(b, v.T @ (w * y))
    assert (
        solution_diagnostics(g, b, beta, NumericLimits())["relative_residual"] < 1e-10
    )


def test_q4_t01_no_inverse_or_n_by_n_weight_allocation(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("dense diagonal/inverse forbidden")

    monkeypatch.setattr(np, "diag", forbidden)
    monkeypatch.setattr(np.linalg, "inv", forbidden)
    reference_fit(np.ones((1000, 3)), np.ones(1000), np.full(1000, 0.001), 10.0)


def test_q4_t02_anchor_zero_and_pool_permutation(trained):
    schema, _, _, fit, task = trained
    selector = MetaSelector(runtime=NumericRuntime(native_policy="reference"))
    first = selector.propose(task, fit, full_ranking=True)
    permuted = replace(
        task,
        candidates=tuple(reversed(task.candidates)),
        roles=tuple(reversed(task.roles)),
    )
    other = selector.propose(permuted, fit, full_ranking=True)
    assert first.proposed_evaluation_id == other.proposed_evaluation_id
    assert first.predictions == other.predictions
    assert first.tie_set == other.tie_set
    p = next(
        p
        for p in first.predictions
        if p["evaluation_id"] == task.anchor_candidate_evaluation_id
    )
    assert (p["yhat"], p["qhat"], p["distance"]) == (0.0, 0.0, 0.0)
    assert first.ranked_ids[0] == first.proposed_evaluation_id
    # No forward record or label argument exists on the inference boundary.
    assert first.numeric["current_forward_inputs"] is False


def test_q4_t02_origin_permutation_fit_and_scaler(trained):
    schema, _, past, fit, task = trained
    reordered = replace(past, revisions=tuple(reversed(past.revisions)))
    new = RidgeLearner(
        settings=fit.model.settings, runtime=NumericRuntime(native_policy="reference")
    ).fit(schema, reordered, fit_completed_at=fit.model.fit_completed_at)
    assert new.model.training_snapshot_id == fit.model.training_snapshot_id
    assert np.allclose(
        new.model.coefficients, fit.model.coefficients, rtol=1e-9, atol=1e-10
    )
    assert (
        MetaSelector().propose(task, new).proposed_evaluation_id
        == MetaSelector().propose(task, fit).proposed_evaluation_id
    )


def test_q4_t03_origin_weights_and_support_not_rows(trained):
    _, _, _, fit, _ = trained
    assert fit.origin_count == 3
    for tid, _, _ in fit.model.revision_references:
        rows = [r for r in fit.model.fit_row_references if r[0] == tid]
        assert len(rows) == 5
        assert sum(r[3] for r in rows) == pytest.approx(1.0)
        assert all(r[3] == 0.2 for r in rows)


def test_q4_t03_late_one_to_ten_revision_replaces_whole_origin():
    task, schema = make_task(n=11)
    failed = {
        c.evaluation_id: OutcomeStatus.OUTCOME_FAILED for c in task.candidates[2:]
    }
    old = revision_for(task, schema, status_by_id=failed)
    corrected = revision_for(
        task,
        schema,
        parent=old,
        available=old.revision_available_at + __import__("pandas").Timedelta(hours=1),
    )
    history = MetaHistory()
    history.append(old)
    a = snapshot((old,))
    history.append(corrected)
    b = snapshot((old,), extra=(corrected,))
    settings = RidgeSettings(min_matured_origins=1)
    first = RidgeLearner(settings=settings).fit(schema, a)
    second = RidgeLearner(settings=settings).fit(schema, b)
    assert first.origin_count == second.origin_count == 1
    assert len(first.model.fit_row_references) == 1
    assert len(second.model.fit_row_references) == 10
    assert {r[1] for r in second.model.fit_row_references} == {corrected.revision_id}
    assert sum(r[3] for r in second.model.fit_row_references) == pytest.approx(1.0)
    assert all(r[3] == 0.1 for r in second.model.fit_row_references)


def test_q4_t03_zero_label_dispositions_preserved_not_support():
    t, s = make_task(year=2020)
    z, _ = make_task(year=2021, schema=s)
    failed = revision_for(
        z, s, status_by_id={z.anchor.evaluation_id: OutcomeStatus.OUTCOME_FAILED}
    )
    past = snapshot((revision_for(t, s), failed))
    fit = RidgeLearner(settings=RidgeSettings(min_matured_origins=1)).fit(s, past)
    assert fit.origin_count == 1
    assert fit.model.training_snapshot_id == past.snapshot_id
    assert len(fit.model.revision_references) == 2


def policy_fixture():
    """Construct historical outcomes so the actual fitted policy matches guide 5.7."""
    schema = DescriptorSchema(
        {"recipe": ["anchor", "x", "y", "z"]}, include_activity=False
    )
    old, _ = make_task(n=4, year=2020)
    family = replace(
        old.family,
        parameter_schema_id=schema.space.identity,
        descriptor_schema_id=schema.schema_id,
    )

    def task_for(year):
        base, _ = make_task(n=4, year=year)
        candidates = tuple(
            replace(
                c,
                candidate_id=f"candidate-{name}",
                requested_params={"recipe": name},
                effective_params={"recipe": name},
                observation=replace(c.observation, raw_sharpe=raw),
                objective=raw,
            )
            for c, name, raw in zip(
                base.candidates, ["anchor", "x", "y", "z"], [1.8, 2.2, 1.5, 0.1]
            )
        )
        return replace(base, family=family, candidates=candidates)

    old = task_for(2020)
    revision = revision_for(old, schema)
    past = snapshot((revision,))
    scaler = OriginBalancedStandardizer.fit(schema, past)
    values, _ = scaler.transform(schema.encode(old.candidates))
    v = values[1:] - values[0]
    # Independent synthetic construction only: solve the three-row shrinkage
    # response to get observed Y whose Ridge predictions are the guide's values.
    g = v.T @ v / 3 + 10 * np.eye(v.shape[1])
    response = v @ np.linalg.solve(g, v.T / 3)
    labels = np.linalg.solve(response, np.array([0.7, -0.6, -1.4]))
    outcomes = []
    for i, o in enumerate(revision.outcomes):
        ci = next(
            j
            for j, c in enumerate(old.candidates)
            if c.evaluation_id == o.evaluation_id
        )
        raw = (
            1.8
            if ci == 0
            else old.candidates[ci].observation.raw_sharpe - labels[ci - 1]
        )
        outcomes.append(
            replace(o, observation=replace(o.observation, raw_sharpe=float(raw)))
        )
    revision = replace(revision, outcomes=tuple(outcomes))
    past = snapshot((revision,))
    fitted = RidgeLearner(
        settings=RidgeSettings(min_matured_origins=1),
        runtime=NumericRuntime(native_policy="reference"),
    ).fit(schema, past, fit_completed_at=stamp("2023-12-31"))
    return schema, past, fitted, task_for(2023)


def test_q4_t04_guide_fixture_actual_fitted_selector_not_gap_absolute():
    _, _, fit, task = policy_fixture()
    decision = MetaSelector(runtime=NumericRuntime(native_policy="reference")).propose(
        task, fit, full_ranking=True
    )
    values = {p["candidate_id"].split("-")[-1]: p for p in decision.predictions}
    assert decision.proposed_params["recipe"] == "y"
    assert decision.raw_best_evaluation_id == task.candidates[1].evaluation_id
    for name, y, q in [
        ("anchor", 0.0, 0.0),
        ("x", 0.7, -0.3),
        ("y", -0.6, 0.3),
        ("z", -1.4, -0.3),
    ]:
        assert values[name]["yhat"] == pytest.approx(y, abs=1e-10)
        assert values[name]["qhat"] == pytest.approx(q, abs=1e-10)
        assert values[name]["eligible"] == (name in {"anchor", "y"})


@pytest.mark.parametrize("delta", [0.0, 0.5e-10, 1e-10, 1.5e-10, 2e-10])
def test_q4_t04_total_order_ties_no_nontransitive_comparator(delta):
    y = np.array([0.0, -0.5, -0.5 + delta])
    winner, ties, _ = select_indices(
        y,
        np.zeros(3),
        [0.0, 2.0, 1.0],
        [("a",), ("b",), ("c",)],
        epsilon=0.1,
        tie_tolerance=1e-10,
    )
    assert winner == (2 if y[2] <= -0.5 + 1e-10 else 1)
    assert 0 not in ties


def test_q4_t05_lambda_origin_sum_and_raw_units(trained):
    schema, _, past, fit, _ = trained
    k = fit.origin_count
    assert fit.model.diagnostics["effective_mean_origin_lambda"] == 10 / k
    assert np.allclose(
        fit.model.raw_unit_coefficients,
        np.asarray(fit.model.coefficients) / np.asarray(fit.model.scaler["scale"]),
    )
    modified = RidgeLearner(
        settings=replace(fit.model.settings, lambda_reg=100.0),
        runtime=NumericRuntime(native_policy="reference"),
    ).fit(schema, past)
    assert np.linalg.norm(modified.model.coefficients) < np.linalg.norm(
        fit.model.coefficients
    )
    assert modified.model.model_id != fit.model.model_id


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), 0.0, -1.0])
def test_q4_t06_invalid_lambda_and_fit_inputs(bad):
    with pytest.raises(MetaRecordError):
        RidgeSettings(lambda_reg=bad)
    with pytest.raises(MetaRecordError):
        reference_fit(np.ones((2, 2)), np.ones(2), np.ones(2), bad)


@pytest.mark.parametrize("which", ["v", "y", "w"])
def test_q4_t06_nonfinite_rejected_not_fallback(which):
    values = dict(v=np.ones((2, 2)), y=np.ones(2), w=np.ones(2))
    values[which].flat[0] = np.nan
    with pytest.raises(MetaRecordError):
        reference_fit(values["v"], values["y"], values["w"], 10.0)


def test_q4_t06_empty_safe_pool_and_resource_and_condition():
    with pytest.raises(MetaRecordError, match="EMPTY_SAFE"):
        select_indices(
            [0.0, 1.0],
            [-1.0, -2.0],
            [0.0, 1.0],
            ["a", "b"],
            epsilon=0.1,
            tie_tolerance=0.0,
        )
    with pytest.raises(MetaRecordError, match="RESOURCE"):
        reference_fit(
            np.ones((100, 20)),
            np.ones(100),
            np.ones(100),
            10.0,
            NumericLimits(max_workspace_bytes=10),
        )
    with pytest.raises(MetaRecordError, match="ILL_CONDITIONED"):
        solution_diagnostics(
            np.array([[1.0, 0.0], [0.0, 1e-15]]),
            np.zeros(2),
            np.zeros(2),
            NumericLimits(),
        )


def test_q4_t06_cold_start_ood_and_invalid_anchor(trained):
    schema, _, past, fit, task = trained
    cold = RidgeLearner().fit(schema, past)
    assert cold.model is None and cold.origin_count == 3
    decision = MetaSelector().propose(task, cold, schema=schema, mode="shadow")
    assert (
        decision.status == "META_SUPPORT_INSUFFICIENT"
        and decision.fit_completed_at is None
    )
    assert decision.actual_evaluation_id == task.anchor_candidate_evaluation_id
    params = dict(task.candidates[-1].effective_params)
    params["hma_length"] = 100
    bad = replace(task.candidates[-1], effective_params=params, requested_params=params)
    # Numeric range OOD beyond historically constant support, not just bounds.
    old = schema.encode(task.candidates)
    assert old.valid.all()
    with pytest.raises(MetaRecordError, match="ANCHOR"):
        replace(task, anchor_candidate_evaluation_id="unknown")
    malformed = replace(task.candidates[-1], effective_params={**params, "unknown": 1})
    with pytest.raises(ValueError):
        MetaSelector().propose(
            replace(task, candidates=task.candidates[:-1] + (malformed,)), fit
        )
    assert bad.effective_params["hma_length"] == 100


def test_q4_t07_unmatured_revision_does_not_enter_fit(trained):
    schema, revisions, past, fit, task = trained
    future = revision_for(task, schema)
    changed = snapshot(revisions, extra=(future,))
    assert changed.snapshot_id == past.snapshot_id
    new = RidgeLearner(settings=fit.model.settings).fit(
        schema, changed, fit_completed_at=fit.model.fit_completed_at
    )
    assert np.array_equal(new.model.coefficients, fit.model.coefficients)
    assert not hasattr(task, "forward_labels")


def test_q4_t08_complete_model_and_decision_roundtrip(trained):
    _, _, _, fit, task = trained
    model = loads_model(
        dumps_model(fit.model),
        expected_model_id=fit.model.model_id,
        available_as_of=task.decision_sealed_at,
    )
    selector = MetaSelector(runtime=NumericRuntime(native_policy="reference"))
    a = selector.propose(task, fit, mode="shadow", full_ranking=True)
    b = selector.propose(
        task, FitOutcome(model, "FIT_VALID", 3), mode="shadow", full_ranking=True
    )
    assert (
        a.predictions == b.predictions
        and a.proposed_evaluation_id == b.proposed_evaluation_id
    )
    restored = loads_decision(
        dumps_decision(a),
        expected_decision_id=a.decision_id,
        available_as_of=a.ready_at,
    )
    assert restored.decision_id == a.decision_id
    assert restored.actual_evaluation_id == task.anchor_candidate_evaluation_id
    compact = selector.propose(task, fit, full_ranking=False)
    assert not compact.ranked_ids
    assert rank_decision(compact) == a.ranked_ids
    with pytest.raises(MetaRecordError, match="WINNER"):
        replace(a, proposed_evaluation_id="unknown")


@pytest.mark.parametrize(
    "field",
    [
        "scaler",
        "schema",
        "reference_gram",
        "revision_references",
        "coefficients",
        "settings",
    ],
)
def test_q4_t08_missing_complete_bundle_fails(trained, field):
    model = trained[3].model
    doc = json.loads(dumps_model(model))
    doc["payload"].pop(field)
    doc["content_digest"] = digest(doc["payload"])
    with pytest.raises(MetaRecordError):
        loads_model(
            json.dumps(doc),
            expected_model_id=model.model_id,
            available_as_of=stamp("2026-01-01"),
        )


def test_q4_t08_rehashed_tampering_and_future_model_rejected(trained):
    model = trained[3].model
    doc = json.loads(dumps_model(model))
    doc["payload"]["coefficients"][0] += 1.0
    doc["content_digest"] = digest(doc["payload"])
    with pytest.raises(MetaRecordError, match="REVIEW_ID"):
        loads_model(
            json.dumps(doc),
            expected_model_id=model.model_id,
            available_as_of=stamp("2026-01-01"),
        )
    with pytest.raises(MetaRecordError, match="NOT_YET"):
        loads_model(
            dumps_model(model),
            expected_model_id=model.model_id,
            available_as_of=model.information_as_of,
        )


def test_q4_t05_installed_baseline_auto_vs_require_and_candidate_blocks():
    try:
        import _quantbt_native as baseline
    except ImportError:
        baseline = None

    candidate = os.environ.get("QMS04_NATIVE_EXTENSION")
    if not candidate:
        if not hasattr(baseline, "qms_numeric_descriptor_v1"):
            assert NumericRuntime().native is None
            with pytest.raises(MetaRecordError):
                NumericRuntime(native_policy="require")
        return
    from tools.build_qms04_candidate import load_candidate

    native = load_candidate(Path(candidate))
    runtime = NumericRuntime(native_policy="require", native_module=native)
    rng = np.random.default_rng(707)
    for n, d in [(1, 1), (27, 4), (91, 12), (200, 32)]:
        v, y, w = (
            rng.normal(size=(n, d)),
            rng.normal(size=n),
            rng.uniform(0.01, 1, size=n),
        )
        actual = runtime.fit(v, y, w, 10.0)
        expected = reference_fit(v, y, w, 10.0)
        for a, e in zip(actual, expected):
            assert np.allclose(a, e, rtol=1e-9, atol=1e-10)
        dy, q = runtime.rank(v, actual[2], y)
        assert np.allclose(dy, v @ expected[2], rtol=1e-9, atol=1e-10)
        assert np.allclose(q, y - dy, rtol=1e-9, atol=1e-10)
    schema, _, _, fit, task = historical_fit(runtime)
    ref = historical_fit()[3]
    assert np.allclose(
        fit.model.coefficients, ref.model.coefficients, rtol=1e-9, atol=1e-10
    )
    a = MetaSelector(runtime=runtime).propose(task, fit, full_ranking=True)
    b = MetaSelector(runtime=NumericRuntime(native_policy="reference")).propose(
        task, ref, full_ranking=True
    )
    assert (
        a.proposed_evaluation_id == b.proposed_evaluation_id and a.tie_set == b.tie_set
    )
    assert runtime.metadata["selected_backend_by_block"]["gram_solve"] == "rust"
    if baseline is not None:
        assert baseline.version() == "0.4.2"  # No financial baseline replacement.


def test_q4_t06_constant_feature_support_uses_whole_pool_fallback():
    pairs = [make_task(n=4, year=y) for y in (2020, 2021, 2022)]
    schema = pairs[0][1]
    tasks = []
    for task, _ in pairs:
        candidates = tuple(
            replace(
                c,
                requested_params={**c.requested_params, "hma_length": 3},
                effective_params={**c.effective_params, "hma_length": 3},
            )
            for c in task.candidates
        )
        tasks.append(replace(task, candidates=candidates))
    past = snapshot(tuple(revision_for(t, schema) for t in tasks))
    fit = RidgeLearner(settings=RidgeSettings(min_matured_origins=3)).fit(
        schema, past, fit_completed_at=stamp("2023-12-31")
    )
    current, _ = make_task(n=4, year=2023, schema=schema)
    decision = MetaSelector().propose(current, fit)
    assert decision.status == "META_OOD_NATIVE_FALLBACK"
    assert decision.proposed_evaluation_id == current.anchor_candidate_evaluation_id
    assert decision.guard["unsupported_ids"]


def test_q4_t06_undefined_anchor_and_unverified_candidate_not_success(trained):
    _, _, _, fit, task = trained
    anchor = replace(
        task.anchor,
        observation=replace(
            task.anchor.observation,
            status=OutcomeStatus.NO_VARIANCE,
            raw_sharpe=None,
            sample_std=0.0,
        ),
    )
    invalid = replace(task, candidates=(anchor,) + task.candidates[1:])
    decision = MetaSelector().propose(invalid, fit)
    assert decision.status == "META_NOT_APPLICABLE_METRIC"
    assert not decision.predictions
    c = replace(
        task.candidates[1],
        observation=replace(
            task.candidates[1].observation,
            verification="unverified",
            status=OutcomeStatus.UNVERIFIED,
        ),
    )
    task = replace(task, candidates=(task.candidates[0], c) + task.candidates[2:])
    decision = MetaSelector().propose(task, fit)
    row = next(p for p in decision.predictions if p["evaluation_id"] == c.evaluation_id)
    assert not row["eligible"] and row["yhat"] is None


def test_q4_t07_family_and_future_model_are_typed_errors(trained):
    _, _, _, fit, task = trained
    with pytest.raises(MetaRecordError, match="INCOMPATIBLE"):
        MetaSelector().propose(
            replace(task, family=replace(task.family, window_policy_id="different")),
            fit,
        )
    with pytest.raises(MetaRecordError, match="CLOCK"):
        replace(
            fit.model,
            fit_completed_at=fit.model.information_as_of
            - __import__("pandas").Timedelta(seconds=1),
        )
    future = replace(fit.model, fit_completed_at=task.forward_end)
    with pytest.raises(MetaRecordError, match="UNAVAILABLE"):
        MetaSelector().propose(task, FitOutcome(future, "FIT_VALID", fit.origin_count))


def test_q4_t08_missing_scaler_category_and_weights_only_fail_with_reviewed_tamper(
    trained,
):
    model = trained[3].model
    for field in ("mean", "scale", "constant", "observed", "numeric_columns"):
        doc = json.loads(dumps_model(model))
        doc["payload"]["scaler"].pop(field)
        doc["content_digest"] = digest(doc["payload"])
        identity = digest({"schema": "qms-ridge-model-v1", "model": doc["payload"]})
        with pytest.raises(MetaRecordError):
            loads_model(
                json.dumps(doc),
                expected_model_id=identity,
                available_as_of=stamp("2026-01-01"),
            )
    doc = json.loads(dumps_model(model))
    doc["payload"]["schema"]["parameters"][1]["categories"] = []
    doc["content_digest"] = digest(doc["payload"])
    identity = digest({"schema": "qms-ridge-model-v1", "model": doc["payload"]})
    with pytest.raises(MetaRecordError):
        loads_model(
            json.dumps(doc),
            expected_model_id=identity,
            available_as_of=stamp("2026-01-01"),
        )


def test_q4_t05_native_boundary_and_chunk_contract():
    candidate = os.environ.get("QMS04_NATIVE_EXTENSION")
    if not candidate:
        # This tests missing-capability behavior, never claims native certification.
        with pytest.raises(MetaRecordError):
            NumericRuntime(native_policy="require", native_module=object())
        return
    from tools.build_qms04_candidate import load_candidate

    module = load_candidate(candidate)
    runtime = NumericRuntime(native_policy="require", native_module=module)
    schema, past, fit, task = policy_fixture()
    native_fit = RidgeLearner(
        settings=replace(fit.model.settings, epsilon=0.3), runtime=runtime
    ).fit(schema, past, fit_completed_at=fit.model.fit_completed_at)
    reference_fit_out = FitOutcome(
        replace(fit.model, settings=native_fit.model.settings), "FIT_VALID", 1
    )
    actual = MetaSelector(runtime=runtime).propose(task, native_fit, full_ranking=True)
    reference = MetaSelector(runtime=NumericRuntime(native_policy="reference")).propose(
        task, reference_fit_out, full_ranking=True
    )
    assert actual.numeric["reference_boundary_fallback"]
    assert actual.numeric["complete_reference_decision_verified"]
    assert actual.proposed_evaluation_id == reference.proposed_evaluation_id
    assert (
        actual.tie_set == reference.tie_set
        and actual.ranked_ids == reference.ranked_ids
    )
    assert [p["eligible"] for p in actual.predictions] == [
        p["eligible"] for p in reference.predictions
    ]
    rng = np.random.default_rng(718)
    v, y, w = (
        rng.normal(size=(71, 7)),
        rng.normal(size=71),
        rng.uniform(0.1, 1, size=71),
    )
    full = runtime.fit(v, y, w, 10.0)
    for chunk_size in (1, 3, 17, 71):
        grams, bs = [], []
        for start in range(0, len(v), chunk_size):
            g, b, _ = runtime.fit(
                v[start : start + chunk_size],
                y[start : start + chunk_size],
                w[start : start + chunk_size],
                10.0,
            )
            grams.append(g - 10 * np.eye(7))
            bs.append(b)
        assert np.allclose(
            np.sum(grams, axis=0) + 10 * np.eye(7), full[0], rtol=1e-9, atol=1e-10
        )
        assert np.allclose(np.sum(bs, axis=0), full[1], rtol=1e-9, atol=1e-10)
    with pytest.raises(ValueError):
        module.qms_fit_v1(np.ones((2, 2)), np.ones(1), np.ones(2), 10.0)
