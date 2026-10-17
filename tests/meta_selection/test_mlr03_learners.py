"""Independent synthetic checks of the common research context and original Q head."""

from dataclasses import replace
import json

import numpy as np
import pytest

from quantbt.optimization.meta_selection.common import MetaRecordError
from quantbt.optimization.meta_selection.numerics import NumericRuntime
from quantbt.optimization.meta_selection.selection import select_indices
from tests.meta_selection.test_mlr02_linear import corpus, oracle
from tools.meta_model_research.families import FamilySpec
from tools.meta_model_research.learners import (
    FamilyResearch,
    dumps_family_artifact,
    loads_family_artifact,
)
from tools.meta_model_research.linear import evaluate_revision
from tests.meta_selection.test_qms03_history import revision_for


def setup(k=12, code="B1", **kwargs):
    data = corpus(k)
    engine = FamilyResearch(**kwargs)
    fitted = engine.fit(
        FamilySpec(code), data[0], data[2], fit_completed_at=data[3].decision_sealed_at
    )
    artifact = engine.propose(data[3], fitted, schema=data[0], full_ranking=True)
    return data, engine, artifact


def test_history_basis_and_bayesian_mean_match_independent_augmented_oracle():
    data, engine, artifact = setup()
    means, scales, beta = oracle(data[0], data[2], 12.0)
    np.testing.assert_allclose(
        artifact.fit.scaler["mean"], means, atol=1e-12, rtol=1e-12
    )
    np.testing.assert_allclose(
        artifact.fit.scaler["scale"], scales, atol=1e-12, rtol=1e-12
    )
    expected = engine.prepared.X @ beta
    np.testing.assert_allclose(
        artifact.fit.model.predict(engine.prepared.X), expected, atol=1e-10, rtol=1e-9
    )
    assert engine.prepared.weights.sum() == pytest.approx(12.0)
    for values in (engine.prepared.X, engine.prepared.y, engine.prepared.weights):
        with pytest.raises(ValueError):
            values.setflags(write=True)


@pytest.mark.parametrize("code", ["B1", "H135", "H200"])
def test_full_pool_head_and_portable_roundtrip(code):
    data, engine, artifact = setup(code=code)
    decision = artifact.decision
    assert decision.status == "META_MODEL_PROPOSAL"
    anchor = next(
        p
        for p in decision.predictions
        if p["evaluation_id"] == decision.anchor_evaluation_id
    )
    assert (anchor["yhat"], anchor["qhat"], anchor["distance"]) == (0.0, 0.0, 0.0)
    selected = [p for p in decision.predictions if p["yhat"] is not None]
    wi, ti, safe = select_indices(
        [p["yhat"] for p in selected],
        [p["qhat"] for p in selected],
        [p["distance"] for p in selected],
        [(p["candidate_id"], p["evaluation_id"]) for p in selected],
        epsilon=0.1,
        tie_tolerance=decision.guard["tie_tolerance"],
    )
    assert selected[wi]["evaluation_id"] == decision.proposed_evaluation_id
    assert set(decision.tie_set) == {selected[i]["evaluation_id"] for i in ti}
    text = dumps_family_artifact(artifact)
    other = loads_family_artifact(
        text, expected_artifact_id=artifact.artifact_id, task=data[3], schema=data[0]
    )
    assert other == artifact
    revision = revision_for(data[3], data[0])
    metrics = evaluate_revision(
        artifact,
        revision,
        available_as_of=revision.revision_available_at
        + __import__("pandas").Timedelta(nanoseconds=1),
    )
    assert metrics.metrics["y_mse"] == metrics.metrics["q_mse"]
    assert engine.fits == 1
    assert (
        engine.fit(
            FamilySpec(code),
            data[0],
            data[2],
            fit_completed_at=data[3].decision_sealed_at,
        )
        is artifact.fit
    )
    assert engine.cache_hits == 1


def test_support_budget_clock_and_unknown_artifact_fail_closed():
    data, engine, artifact = setup(11)
    assert artifact.fit.model is None and engine.fits == 0
    assert artifact.decision.status == "META_SUPPORT_INSUFFICIENT"
    data = corpus()
    with pytest.raises(MetaRecordError, match="BUDGET"):
        FamilyResearch(max_fits=0).fit(
            FamilySpec("B1"),
            data[0],
            data[2],
            fit_completed_at=data[3].decision_sealed_at,
        )
    with pytest.raises(MetaRecordError, match="CLOCK"):
        FamilyResearch().fit(
            FamilySpec("B1"), data[0], data[2], fit_completed_at="1999-01-01"
        )
    data, engine, artifact = setup()
    payload = json.loads(dumps_family_artifact(artifact))
    payload["version"] = "not-registered"
    with pytest.raises(MetaRecordError, match="VERSION"):
        loads_family_artifact(
            json.dumps(payload),
            expected_artifact_id=artifact.artifact_id,
            task=data[3],
            schema=data[0],
        )
    with pytest.raises(MetaRecordError, match="CONTEXT"):
        engine.propose(
            data[3],
            replace(
                artifact.fit,
                fit_completed_at=data[3].decision_sealed_at
                + __import__("pandas").Timedelta(seconds=1),
            ),
            schema=data[0],
        )


def test_own_past_correction_changes_context_but_reordering_does_not():
    data, engine, artifact = setup()
    snapshot = replace(data[2], revisions=tuple(reversed(data[2].revisions)))
    other = engine.fit(
        FamilySpec("B1"), data[0], snapshot, fit_completed_at=data[3].decision_sealed_at
    )
    assert other.fit_id == artifact.fit.fit_id
    first = snapshot.revisions[0]
    outcomes = tuple(
        replace(
            o,
            observation=replace(
                o.observation,
                raw_sharpe=o.observation.raw_sharpe
                + (
                    1.0
                    if o.evaluation_id != first.task.anchor_candidate_evaluation_id
                    else 0.0
                ),
            ),
        )
        for o in first.outcomes
    )
    changed = replace(first, outcomes=outcomes)
    corrected = replace(snapshot, revisions=(changed, *snapshot.revisions[1:]))
    fitted = engine.fit(
        FamilySpec("B1"),
        data[0],
        corrected,
        fit_completed_at=data[3].decision_sealed_at,
    )
    assert fitted.fit_id != artifact.fit.fit_id and fitted.K == artifact.fit.K
    assert engine.fits == 2


def test_context_origin_count_cannot_disagree_with_fitted_normalization():
    data, engine, artifact = setup()
    with pytest.raises(MetaRecordError, match="NORMALIZATION"):
        replace(artifact.fit, K=13)
    payload = json.loads(dumps_family_artifact(artifact))
    payload["fit"]["K"] = 13
    payload["fit"]["training"]["K"] = 13
    with pytest.raises(MetaRecordError, match="NORMALIZATION"):
        loads_family_artifact(
            json.dumps(payload),
            expected_artifact_id=artifact.artifact_id,
            task=data[3],
            schema=data[0],
        )


def test_native_basis_prediction_restore_and_real_fit_bill():
    if __import__("importlib.util").util.find_spec("_quantbt_native") is None:
        pytest.skip(
            "source native qualification needs the retained QMS numeric extension"
        )
    data, engine, artifact = setup(
        runtime=NumericRuntime(native_policy="require"), max_fits=4
    )
    assert artifact.fit.model.metadata["fit_count"] == 2
    assert (
        engine.regression_fit_charge == 4
    )  # two runtime qualification solves + two fit/parity solves.
    text = dumps_family_artifact(artifact)
    other = loads_family_artifact(
        text, expected_artifact_id=artifact.artifact_id, task=data[3], schema=data[0]
    )
    assert other.artifact_id == artifact.artifact_id
    assert (
        engine.fit(
            FamilySpec("B1"),
            data[0],
            data[2],
            fit_completed_at=data[3].decision_sealed_at,
        )
        is artifact.fit
    )
    assert engine.regression_fit_charge == 4
    with pytest.raises(MetaRecordError, match="BUDGET"):
        engine.fit(
            FamilySpec("H135"),
            data[0],
            data[2],
            fit_completed_at=data[3].decision_sealed_at,
        )
