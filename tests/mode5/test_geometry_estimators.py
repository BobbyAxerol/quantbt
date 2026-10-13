"""Independent analytic product-measure oracles for the additive estimator API."""

from itertools import product
import json

import numpy as np
import pytest

from tools.mode5_geometry import (
    IndependentInputs,
    estimate_saltelli,
    saltelli_completion,
    saltelli_inputs,
    saltelli_layout,
)
from tools.mode5_geometry import validate_saltelli_outputs


def oracle_inputs(a, b, second=False):
    rows = []
    for left, right in zip(a, b):
        rows.append(list(left))
        for j in range(len(left)):
            rows.append([right[k] if k == j else left[k] for k in range(len(left))])
        if second:
            for j in range(len(left)):
                rows.append([left[k] if k == j else right[k] for k in range(len(left))])
        rows.append(list(right))
    return np.array(rows, dtype=float)


def exact_design(d=3, second=True):
    joint = np.array(list(product((-1.0, 1.0), repeat=2 * d)))
    layout = saltelli_layout(len(joint), d, second_order=second)
    return layout, oracle_inputs(joint[:, :d], joint[:, d:], second)


def declaration(d, **kwargs):
    return IndependentInputs(
        tuple(f"x{i}" for i in range(d)),
        ("Rademacher(-1,+1)",) * d,
        "analytic-independent-v1",
        kwargs.pop("kind", "numeric_product"),
        True,
        **kwargs,
    )


def analyze(layout, x, y, **kwargs):
    options = dict(
        method="saltelli_pick_freeze_v1",
        representation=declaration(layout.dimensions),
        bootstrap_seed=0,
        bootstrap_resamples=64,
    )
    options.update(kwargs)
    return estimate_saltelli(layout, x, y, **options)


@pytest.mark.parametrize("second", [False, True])
def test_additive_known_variance_shares_and_legacy_admission_unchanged(second):
    layout, x = exact_design(second=second)
    y = x[:, 0] + 2 * x[:, 1] - 3 * x[:, 2]
    result = analyze(layout, x, y)
    indices = result["sensitivity_indices"]
    np.testing.assert_allclose(indices["S1"], [1 / 14, 4 / 14, 9 / 14], atol=1e-14)
    np.testing.assert_allclose(indices["ST"], indices["S1"], atol=1e-14)
    np.testing.assert_allclose(indices["ST_minus_S1"], 0.0, atol=1e-14)
    np.testing.assert_allclose([r["value"] for r in indices["S2"]], 0.0, atol=1e-14)
    assert len(indices["S2"]) == (3 if second else 0)
    assert result["bootstrap"]["resample_unit"] == "A_B_all_cross_block_row"
    assert result["bootstrap"]["status"] == "AVAILABLE"
    assert not result["parameter_removal_authorized"]
    legacy = validate_saltelli_outputs(
        layout, x, y, method="saltelli_pick_freeze_v1", independent_axes=True
    )
    assert legacy["sensitivity_indices"] is None and legacy["output_variance"] == 14.0
    json.dumps(result, allow_nan=False)


def test_interacting_known_shares_and_inactive_independent_axis():
    layout, x = exact_design()
    result = analyze(layout, x, x[:, 0] + 2 * x[:, 1] + 3 * x[:, 0] * x[:, 1])
    indices = result["sensitivity_indices"]
    np.testing.assert_allclose(indices["S1"], [1 / 14, 4 / 14, 0.0], atol=1e-14)
    np.testing.assert_allclose(indices["ST"], [10 / 14, 13 / 14, 0.0], atol=1e-14)
    np.testing.assert_allclose(
        indices["ST_minus_S1"], [9 / 14, 9 / 14, 0.0], atol=1e-14
    )
    np.testing.assert_allclose(
        [r["value"] for r in indices["S2"]], [9 / 14, 0.0, 0.0], atol=1e-14
    )
    assert indices["S2"][0]["axes"] == ["x0", "x1"]


def test_continuous_independent_oracle_and_prefix_diagnostics():
    rng = np.random.default_rng(127)
    n, d = 8192, 3
    a, b = rng.uniform(-1.0, 1.0, size=(2, n, d))
    layout = saltelli_layout(n, d)
    x = oracle_inputs(a, b)
    rep = IndependentInputs(
        ("a", "b", "c"), ("uniform(-1,1)",) * d, "uniform-v1", "numeric_product", True
    )
    result = analyze(
        layout,
        x,
        x @ np.array([1.0, 2.0, -3.0]),
        representation=rep,
        convergence_sizes=(256, 1024, n),
        bootstrap_resamples=32,
    )
    np.testing.assert_allclose(
        result["sensitivity_indices"]["S1"], [1 / 14, 4 / 14, 9 / 14], atol=0.025
    )
    np.testing.assert_allclose(
        result["sensitivity_indices"]["ST"], [1 / 14, 4 / 14, 9 / 14], atol=0.025
    )
    prefixes = result["convergence"]["prefixes"]
    assert [r["prefix_size"] for r in prefixes] == [256, 1024, n]
    assert prefixes[-1]["estimates"] == result["sensitivity_indices"]
    assert prefixes[-1]["max_abs_change_from_previous"] < 0.06
    assert result["convergence"]["status"] == "PREFIX_DIAGNOSTICS_ONLY"


def manual_indices(block, d):
    base = np.r_[block[:, 0], block[:, -1]]
    centered = block - base.mean()
    variance = np.var(base)
    a, b, ab = centered[:, 0], centered[:, -1], centered[:, 1 : 1 + d]
    s1 = np.mean(b[:, None] * (ab - a[:, None]), axis=0) / variance
    st = np.mean((ab - a[:, None]) ** 2, axis=0) / (2 * variance)
    return np.r_[s1, st, st - s1]


def test_seed_zero_joint_block_bootstrap_matches_independent_calculation_and_is_pure():
    layout, x = exact_design(second=False)
    y = 17 + x[:, 0] + 2 * x[:, 1] + 3 * x[:, 0] * x[:, 1]
    before_x, before_y = x.copy(), y.copy()
    global_before = np.random.get_state()
    result = analyze(layout, x, y)
    global_after = np.random.get_state()
    np.testing.assert_array_equal(global_before[1], global_after[1])
    assert global_before[2:] == global_after[2:]
    assert result == analyze(layout, x, y)
    np.testing.assert_array_equal(x, before_x)
    np.testing.assert_array_equal(y, before_y)
    rng = np.random.default_rng(0)
    block = y.reshape(layout.base_n, layout.dimensions + 2)
    values = np.array(
        [
            manual_indices(block[rng.integers(len(block), size=len(block))], 3)
            for _ in range(64)
        ]
    )
    expected = np.quantile(values, [0.025, 0.975], axis=0).T
    actual = np.concatenate(
        [result["confidence_intervals"][k] for k in ("S1", "ST", "ST_minus_S1")]
    )
    np.testing.assert_allclose(actual, expected, atol=1e-14)


def test_negative_finite_sample_estimate_and_intervals_are_not_clipped():
    layout, x = exact_design()
    result = analyze(layout, x, x[:, 0] * x[:, 1])
    assert result["sensitivity_indices"]["S1"] == [0.0, 0.0, 0.0]
    assert result["confidence_intervals"]["S1"][0][0] < 0
    small = saltelli_layout(2, 1)
    inputs = oracle_inputs(np.array([[1.0], [-1.0]]), np.array([[0.5], [-0.5]]))
    negative = analyze(small, inputs, inputs[:, 0])
    assert negative["sensitivity_indices"]["S1"][0] < 0


@pytest.mark.parametrize("value", [0.1, 0.3, 0.7, 1e308])
def test_constant_output_is_undefined_not_zero_importance(value):
    layout, x = exact_design()
    result = analyze(layout, x, np.full(layout.rows, value))
    assert result["status"] == "UNDEFINED_CONSTANT_OUTPUT"
    assert (
        result["sensitivity_indices"] is None and result["confidence_intervals"] is None
    )
    assert result["numerics"]["scaled_base_variance"] == 0.0
    assert result["bootstrap"]["status"] == "NOT_RUN_UNDEFINED_OUTPUT"


def test_zero_base_variance_and_degenerate_bootstrap_are_explicit():
    layout, x = exact_design()
    y = np.zeros(layout.rows)
    y[1] = 1.0
    result = analyze(layout, x, y)
    assert result["status"] == "UNDEFINED_ZERO_BASE_VARIANCE"
    assert result["sensitivity_indices"] is None
    small = saltelli_layout(2, 1)
    x = oracle_inputs(np.zeros((2, 1)), np.array([[1.0], [0.0]]))
    result = analyze(small, x, x[:, 0])
    assert result["sensitivity_indices"] is not None
    assert result["confidence_intervals"] is None
    assert result["bootstrap"]["status"] == "UNAVAILABLE_DEGENERATE_RESAMPLES"
    assert result["bootstrap"]["invalid_resamples"] > 0
    assert (
        result["bootstrap"]["valid_resamples"]
        + result["bootstrap"]["invalid_resamples"]
        == 64
    )


@pytest.mark.parametrize(
    "scale,offset", [(2.0**-1000, 0.0), (2.0**600, 0.0), (2.0**600, 2.0**650)]
)
def test_stable_numerics_small_variance_large_scale_and_large_offset(scale, offset):
    layout, x = exact_design()
    y = x[:, 0] + 2 * x[:, 1] + 3 * x[:, 0] * x[:, 1]
    expected = analyze(layout, x, y)
    actual = analyze(layout, x, offset + scale * y)
    for key in ("S1", "ST", "ST_minus_S1"):
        np.testing.assert_allclose(
            actual["sensitivity_indices"][key],
            expected["sensitivity_indices"][key],
            atol=1e-14,
        )
        np.testing.assert_allclose(
            actual["confidence_intervals"][key],
            expected["confidence_intervals"][key],
            atol=1e-14,
        )
    assert actual["numerics"]["scaled_base_variance"] > 0


def test_opposite_finite_extremes_do_not_overflow_internal_variance():
    layout, x = exact_design()
    result = analyze(layout, x, 1e308 * x[:, 0])
    np.testing.assert_allclose(
        result["sensitivity_indices"]["S1"], [1.0, 0.0, 0.0], atol=1e-14
    )
    json.dumps(result, allow_nan=False)


@pytest.mark.parametrize("second", [False, True])
def test_assembly_matches_independent_oracle(second):
    joint = np.array(list(product((-1.0, 1.0), repeat=4)))
    a, b = joint[:, :2], joint[:, 2:]
    layout = saltelli_layout(len(a), 2, second_order=second, stress_multiplier=3)
    np.testing.assert_array_equal(
        saltelli_inputs(layout, a, b), oracle_inputs(a, b, second)
    )
    result = analyze(layout, saltelli_inputs(layout, a, b), np.ones(layout.rows))
    assert result["execution_cells"] == layout.rows * 3


@pytest.mark.parametrize(
    "kind,kwargs",
    [
        ("fixed_branch", {"branch_id": "mode-a"}),
        (
            "independent_latent",
            {"mapping_id": "positive-spans-v1", "branch_id": "mode-b"},
        ),
    ],
)
def test_branch_and_latent_attribution_is_retained_without_global_pooling(kind, kwargs):
    layout, x = exact_design()
    result = analyze(
        layout, x, x.sum(axis=1), representation=declaration(3, kind=kind, **kwargs)
    )
    assert result["representation"]["kind"] == kind
    for key, value in kwargs.items():
        assert result["representation"][key] == value
    assert "global_ranking" not in result


@pytest.mark.parametrize("method", ["tpe", "neutral_coverage", "plain_qmc"])
def test_ordinary_panels_cannot_emit_global_indices(method):
    layout, x = exact_design()
    with pytest.raises(ValueError, match="structured"):
        analyze(layout, x, x.sum(axis=1), method=method)
    arbitrary = np.random.default_rng(7).random(x.shape)
    with pytest.raises(ValueError, match="cross"):
        analyze(layout, arbitrary, arbitrary.sum(axis=1))


@pytest.mark.parametrize("identical_all_axes", [False, True])
def test_degenerate_base_inputs_cannot_masquerade_as_zero_importance(
    identical_all_axes,
):
    rng = np.random.default_rng(43)
    a, b = rng.random((2, 16, 2))
    b[:, 0] = a[:, 0]
    if identical_all_axes:
        b = a.copy()
    layout = saltelli_layout(len(a), 2)
    x = oracle_inputs(a, b)
    with pytest.raises(ValueError, match="pick-freeze variation"):
        analyze(layout, x, x.sum(axis=1))


@pytest.mark.parametrize(
    "bad",
    [
        "missing_input",
        "missing_output",
        "nan",
        "inf",
        "cross",
        "reverse",
        "complex",
        "masked",
    ],
)
def test_invalid_or_incomplete_design_is_not_filtered(bad):
    layout, x = exact_design()
    y = x.sum(axis=1)
    if bad == "missing_input":
        x = x[:-1]
    elif bad == "missing_output":
        y = y[:-1]
    elif bad == "nan":
        y[1] = np.nan
    elif bad == "inf":
        x[0, 0] = np.inf
    elif bad == "cross":
        x[1, 1] += 0.1
    elif bad == "reverse":
        x[4, 2] += 0.1
    elif bad == "complex":
        y = y.astype(complex) + 1j
    elif bad == "masked":
        y = np.ma.array(y, mask=np.arange(len(y)) == 1)
    with pytest.raises(ValueError):
        analyze(layout, x, y)


@pytest.mark.parametrize(
    "options",
    [
        dict(bootstrap_seed=None),
        dict(bootstrap_seed=True),
        dict(bootstrap_resamples=1),
        dict(confidence_level=float("nan")),
        dict(confidence_level=True),
        dict(convergence_sizes=(8, 4, 64)),
        dict(convergence_sizes=(8, 32)),
        dict(representation=None),
        dict(representation=declaration(2)),
    ],
)
def test_estimator_requires_registered_uncertainty_and_representation(options):
    layout, x = exact_design()
    with pytest.raises(ValueError):
        analyze(layout, x, x.sum(axis=1), **options)


@pytest.mark.parametrize(
    "kind,independent,kwargs",
    [
        ("numeric_product", False, {}),
        ("dependent", True, {}),
        ("fixed_branch", True, {}),
        ("independent_latent", True, {}),
        ("numeric_product", True, {"branch_id": "a"}),
    ],
)
def test_dependent_or_undeclared_branch_representation_is_rejected(
    kind, independent, kwargs
):
    with pytest.raises(ValueError):
        IndependentInputs(
            ("x",), ("uniform(0,1)",), "product-v1", kind, independent, **kwargs
        )


def test_incomplete_censored_output_ledger_cannot_become_global_indices():
    layout = saltelli_layout(2, 1, stress_multiplier=3)
    records = [
        dict(row_id=0, status="COMPLETE", output=1.0),
        dict(row_id=1, status="CENSORED", output=0.5),
        dict(row_id=2, status="FAILED", output=None),
        dict(row_id=3, status="COMPLETE", output=np.nan),
    ]
    result = saltelli_completion(layout, records)
    assert result["status"] == "INCOMPLETE_OR_CENSORED_DESIGN"
    assert result["complete_rows"] == 1 and result["observed_rows"] == 4
    assert result["expected_rows"] == 6 and result["planned_execution_cells"] == 18
    assert [r["row_id"] for r in result["missing_rows"]] == [1, 2, 3, 4, 5]
    assert (
        result["rows"][1]["status"] == "CENSORED" and result["rows"][1]["output"] == 0.5
    )
    assert result["rows"][3]["reason"] == "INVALID_OR_MISSING_OUTPUT"
    assert result["sensitivity_indices"] is None
    json.dumps(result, allow_nan=False)


def test_complete_output_ledger_still_requires_estimator_input_admission():
    layout = saltelli_layout(2, 1)
    records = [
        dict(row_id=i, status="COMPLETE", output=float(i)) for i in range(layout.rows)
    ]
    result = saltelli_completion(layout, records)
    assert result["status"] == "COMPLETE_OUTPUT_LEDGER"
    assert result["missing_rows"] == [] and result["sensitivity_indices"] is None
    x = np.arange(layout.rows, dtype=float)[:, None]
    with pytest.raises(ValueError, match="cross"):
        analyze(layout, x, [r["output"] for r in result["rows"]])


@pytest.mark.parametrize(
    "record",
    [
        dict(row_id=9, status="COMPLETE", output=1.0),
        dict(row_id=True, status="COMPLETE", output=1.0),
        dict(row_id=0, status="UNKNOWN", output=None),
        dict(row_id=0, status="FAILED"),
    ],
)
def test_malformed_completion_records_are_rejected(record):
    with pytest.raises(ValueError):
        saltelli_completion(saltelli_layout(2, 1), [record])


def test_duplicate_completion_slot_is_not_extra_independent_work():
    row = dict(row_id=0, status="COMPLETE", output=1.0)
    with pytest.raises(ValueError):
        saltelli_completion(saltelli_layout(2, 1), [row, row])
