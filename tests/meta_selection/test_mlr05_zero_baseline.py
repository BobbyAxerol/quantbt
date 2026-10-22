"""Independent fixed-zero skill and hierarchical weighting expectations."""

import pytest

from tools.meta_model_research.protocol import GROUPS
from tools.meta_model_research.zero_baseline import MODELS, matched_losses, reduce_cells


def test_independent_scalar_mse_and_perfect_or_zero_predictor():
    truth = {"a": 2.0, "b": -2.0}
    predictions = {c: {"a": 1.0, "b": -1.0} for c in MODELS}
    predictions["P0"] = {"a": 0.0, "b": 0.0}
    losses = matched_losses(truth, predictions)
    assert losses["ZERO"] == 4.0 and losses["P0"] == 4.0
    assert all(losses[c] == 1.0 for c in MODELS if c != "P0")


def test_origin_then_group_weights_not_row_pooling():
    cells = [
        dict(group=g, fold=13, n=2, mse={c: 4.0 for c in ("ZERO",) + MODELS})
        for g in GROUPS
    ]
    cells.append(
        dict(group=GROUPS[0], fold=14, n=100, mse={c: 16.0 for c in ("ZERO",) + MODELS})
    )
    summary = reduce_cells(cells)
    assert summary["groups"][GROUPS[0]]["mse"]["ZERO"] == 10.0
    assert summary["macro_mse"]["ZERO"] == 5.5
    assert summary["zero_reference_skill"]["P0"] == 0.0
    with pytest.raises(ValueError, match="duplicate"):
        reduce_cells(cells + cells[:1])


def test_zero_denominator_is_undefined_not_perfect_skill():
    cells = [
        dict(group=g, fold=13, n=1, mse={c: 0.0 for c in ("ZERO",) + MODELS})
        for g in GROUPS
    ]
    assert reduce_cells(cells)["zero_reference_skill"]["P0"] is None


def test_missing_prediction_is_not_silently_dropped():
    truth = {"a": 1.0, "b": 2.0}
    predictions = {c: dict(truth) for c in MODELS}
    predictions["P0"].pop("b")
    with pytest.raises(ValueError, match="mask mismatch"):
        matched_losses(truth, predictions)


def test_nonfinite_label_is_not_a_zero_observation():
    predictions = {c: {"a": 0.0} for c in MODELS}
    with pytest.raises(ValueError, match="finite"):
        matched_losses({"a": float("nan")}, predictions)


def test_missing_group_is_not_reweighted_without_authority():
    with pytest.raises(ValueError, match="missing group"):
        reduce_cells([])
