import numpy as np
import pytest

from quantbt.optimization.meta_selection.numerics import NumericRuntime, reference_fit
from tests.meta_selection.test_mlr02_linear import corpus
from tests.meta_selection.test_qms03_history import snapshot
from tools.meta_model_research.family_controls import synthetic_correction
from tools.meta_model_research.forward_target import fit_forward, forward_labels
from tools.meta_model_research.learners import prepare_history


def test_forward_target_uses_original_weighted_rows_and_augmented_lstsq():
    schema, _, view, task, _ = corpus()
    runtime = NumericRuntime(native_policy="reference")
    p = prepare_history(schema, view, runtime)
    delta, q, w = forward_labels(view)
    assert np.array_equal(w, p.weights)
    np.testing.assert_allclose(delta - q, p.y, atol=1e-12)
    fitted = fit_forward(schema, view, task, runtime)
    a = np.vstack([p.X * np.sqrt(w[:, None]), np.sqrt(10) * np.eye(p.X.shape[1])])
    b = np.r_[q * np.sqrt(w), np.zeros(p.X.shape[1])]
    beta = np.linalg.lstsq(a, b, rcond=None)[0]
    np.testing.assert_allclose(
        fitted["fit"]["coefficients"], beta, atol=1e-10, rtol=1e-9
    )
    for row in fitted["predictions"]:
        assert row["qhat"] + row["yhat"] == pytest.approx(
            row["raw_is"] - task.anchor.observation.raw_sharpe
        )
    anchor = next(
        r
        for r in fitted["predictions"]
        if r["evaluation_id"] == task.anchor_candidate_evaluation_id
    )
    assert anchor["qhat"] == anchor["yhat"] == anchor["distance"] == 0


def test_regularized_target_change_is_not_algebraic_relabeling():
    schema, _, view, _, _ = corpus()
    p = prepare_history(schema, view, NumericRuntime(native_policy="reference"))
    delta, q, w = forward_labels(view)
    by = reference_fit(p.X, p.y, w, 10)[2]
    bq = reference_fit(p.X, q, w, 10)[2]
    bd = reference_fit(p.X, delta, w, 10)[2]
    np.testing.assert_allclose(bq, bd - by, atol=1e-12)
    assert np.max(np.abs(p.X @ bq - (delta - p.X @ by))) > 1e-3


def test_future_correction_does_not_change_fresh_fit_but_permitted_past_does():
    import pandas as pd

    schema, store, view, task, revisions = corpus()
    original = fit_forward(
        schema, view, task, NumericRuntime(native_policy="reference")
    )
    store.append(
        synthetic_correction(
            revisions[-1], schema, task.data_cutoff + pd.Timedelta(days=10)
        )
    )
    unchanged = snapshot(store, task, task.data_cutoff)
    assert unchanged.snapshot_id == view.snapshot_id
    fresh = fit_forward(
        schema, unchanged, task, NumericRuntime(native_policy="reference")
    )
    assert original == fresh
    store.append(
        synthetic_correction(
            revisions[0], schema, task.data_cutoff - pd.Timedelta(days=1)
        )
    )
    changed = snapshot(store, task, task.data_cutoff)
    new = fit_forward(schema, changed, task, NumericRuntime(native_policy="reference"))
    assert new["model_id"] != original["model_id"]
    assert (
        np.max(
            np.abs(
                np.asarray(new["fit"]["coefficients"]) - original["fit"]["coefficients"]
            )
        )
        > 1e-8
    )


def test_future_snapshot_or_family_rejected():
    import pandas as pd
    from types import SimpleNamespace

    schema, _, view, task, _ = corpus()
    late = SimpleNamespace(
        information_as_of=task.data_cutoff + pd.Timedelta(days=1),
        family_id=view.family_id,
    )
    with pytest.raises(ValueError, match="frontier"):
        fit_forward(
            schema,
            late,
            task,
            NumericRuntime(native_policy="reference"),
        )


def test_small_history_falls_back_without_fit():
    schema, _, view, task, _ = corpus(11)
    fitted = fit_forward(schema, view, task, NumericRuntime(native_policy="reference"))
    assert fitted["status"] == "META_SUPPORT_INSUFFICIENT" and fitted["charge"] == 0
