"""Signed and nonlinear elementary-effect oracles, without financial execution."""

from itertools import permutations, product
import json

import numpy as np
import pytest

from tools.mode5_geometry import (
    IndependentInputs,
    trajectory_inputs,
    trajectory_layout,
    trajectory_screen,
)


def independent_paths():
    rows = []
    for signs in product((-1, 1), repeat=2):
        for order in permutations(range(2)):
            point = np.array([1.0 if s < 0 else 0.0 for s in signs])
            rows.append(point.copy())
            for axis in order:
                point[axis] += signs[axis] * 2 / 3
                rows.append(point.copy())
    return np.array(rows)


def screen(layout, x, y, **kwargs):
    options = dict(
        method="morris_trajectory_v1",
        representation=IndependentInputs(
            tuple(f"x{i}" for i in range(layout.dimensions)),
            ("uniform(0,1)",) * layout.dimensions,
            "unit-cube-v1",
            "numeric_product",
            True,
        ),
        output_unit="money",
        bootstrap_seed=0,
        bootstrap_resamples=64,
    )
    options.update(kwargs)
    return trajectory_screen(layout, x, y, **options)


def test_reversed_steps_recover_signed_linear_effects_for_every_axis():
    layout = trajectory_layout(8, 2, seed=19)
    x = independent_paths()
    before = x.copy()
    result = screen(layout, x, 7 + 3 * x[:, 0] - 4 * x[:, 1])
    np.testing.assert_allclose(result["effects"]["mu"], [3.0, -4.0], atol=1e-14)
    np.testing.assert_allclose(result["effects"]["mu_star"], [3.0, 4.0], atol=1e-14)
    np.testing.assert_allclose(result["effects"]["sigma"], 0.0, atol=1e-14)
    np.testing.assert_allclose(
        result["elementary_effects"], [[3.0, -4.0]] * 8, atol=1e-14
    )
    assert result["effect_sign"] == ["POSITIVE", "NEGATIVE"]
    assert (
        result["sensitivity_indices"] is None
        and not result["parameter_removal_authorized"]
    )
    assert result["effect_unit"] == "money per normalized input span"
    assert result["bootstrap"]["resample_unit"] == "complete_trajectory"
    np.testing.assert_array_equal(x, before)
    json.dumps(result, allow_nan=False)


def test_interaction_has_mixed_sign_magnitude_and_context_variation():
    layout = trajectory_layout(8, 2, seed=19)
    x = independent_paths()
    result = screen(layout, x, (2 * x[:, 0] - 1) * (2 * x[:, 1] - 1))
    np.testing.assert_allclose(result["effects"]["mu"], 0.0, atol=1e-14)
    np.testing.assert_allclose(result["effects"]["mu_star"], [4 / 3, 4 / 3], atol=1e-14)
    assert result["effect_sign"] == ["MIXED", "MIXED"]
    assert all(v > 1 for v in result["effects"]["sigma"])
    assert "nonlinearity and interaction" in result["interpretation"]


def test_nonlinearity_can_also_raise_sigma_and_is_not_labeled_proven_interaction():
    layout = trajectory_layout(8, 2, seed=19)
    x = independent_paths()
    result = screen(layout, x, x[:, 0] ** 2)
    np.testing.assert_allclose(result["effects"]["mu"], [1.0, 0.0], atol=1e-14)
    assert result["effects"]["sigma"][0] > 0.3
    assert result["effects"]["sigma"][1] == 0
    assert result["effect_sign"] == ["POSITIVE", "ZERO"]


@pytest.mark.parametrize("value", [0.3, 1e308])
def test_constant_screen_is_observed_zero_not_structural_inactivity(value):
    layout = trajectory_layout(8, 2, seed=19)
    x = independent_paths()
    result = screen(layout, x, np.full(layout.rows, value))
    assert result["status"] == "NO_OBSERVED_EFFECT_ON_DESIGN"
    assert result["effects"] == dict(
        mu=[0.0, 0.0], mu_star=[0.0, 0.0], sigma=[0.0, 0.0]
    )
    assert not result["parameter_removal_authorized"]


@pytest.mark.parametrize("levels", [4, 6, 8])
def test_seeded_grid_design_and_real_unique_input_bill(levels):
    layout = trajectory_layout(32, 3, seed=771, levels=levels, stress_multiplier=3)
    x = trajectory_inputs(layout)
    np.testing.assert_array_equal(x, trajectory_inputs(layout))
    assert x.shape == (128, 3) and np.all((x >= 0) & (x <= 1))
    result = screen(layout, x, x @ np.array([1.0, -2.0, 3.0]))
    np.testing.assert_allclose(result["effects"]["mu"], [1.0, -2.0, 3.0], atol=1e-14)
    assert result["input_rows"] == 128 and result["execution_cells"] == 384
    unique = len({tuple(row) for row in x})
    assert result["unique_execution_cells"] == 3 * unique
    assert result["duplicate_input_rows"] == 128 - unique
    assert result["convergence"]["prefixes"][-1]["estimates"] == result["effects"]


def test_seeded_joint_trajectory_resampling_matches_manual_oracle():
    layout = trajectory_layout(8, 2, seed=19)
    x = independent_paths()
    y = (2 * x[:, 0] - 1) * (2 * x[:, 1] - 1)
    result = screen(layout, x, y)
    block_x, block_y = x.reshape(8, 3, 2), y.reshape(8, 3)
    effects = np.empty((8, 2))
    for i in range(8):
        for step in range(2):
            difference = block_x[i, step + 1] - block_x[i, step]
            axis = int(np.flatnonzero(difference)[0])
            effects[i, axis] = (block_y[i, step + 1] - block_y[i, step]) / difference[
                axis
            ]
    rng = np.random.default_rng(0)
    summaries = []
    for _ in range(64):
        sample = effects[rng.integers(8, size=8)]
        summaries.append(
            np.r_[
                sample.mean(axis=0),
                np.abs(sample).mean(axis=0),
                sample.std(axis=0, ddof=1),
            ]
        )
    expected = np.quantile(summaries, [0.025, 0.975], axis=0).T
    actual = np.concatenate(
        [result["confidence_intervals"][k] for k in ("mu", "mu_star", "sigma")]
    )
    np.testing.assert_allclose(actual, expected, atol=1e-14)
    assert result == screen(layout, x, y)


@pytest.mark.parametrize("scale,offset", [(2.0**-1000, 0.0), (2.0**600, 2.0**650)])
def test_screen_stable_numerics_preserve_units_and_sign(scale, offset):
    layout = trajectory_layout(8, 2, seed=19)
    x = independent_paths()
    # Values are integer multiples before scaling, so the offset is exact.
    y = 3 * x[:, 0] - 6 * x[:, 1]
    result = screen(layout, x, offset + scale * y)
    np.testing.assert_allclose(
        np.array(result["effects"]["mu"]) / scale, [3.0, -6.0], atol=1e-14
    )
    assert result["effect_sign"] == ["POSITIVE", "NEGATIVE"]


@pytest.mark.parametrize(
    "bad",
    [
        "missing_input",
        "missing_output",
        "nan",
        "multi_axis",
        "repeat_axis",
        "off_grid",
        "wrong_delta",
    ],
)
def test_invalid_trajectories_are_rejected_without_row_filtering(bad):
    layout = trajectory_layout(8, 2, seed=19)
    x = independent_paths()
    y = x.sum(axis=1)
    if bad == "missing_input":
        x = x[:-1]
    elif bad == "missing_output":
        y = y[:-1]
    elif bad == "nan":
        y[1] = np.nan
    elif bad == "multi_axis":
        x[1] = [1 / 3, 1 / 3]
    elif bad == "repeat_axis":
        x[2] = x[0]
    elif bad == "off_grid":
        x[0, 0] = 0.2
    elif bad == "wrong_delta":
        x[1, 0] = 2 / 3
    with pytest.raises(ValueError):
        screen(layout, x, y)


@pytest.mark.parametrize(
    "kwargs",
    [
        dict(method="plain_qmc"),
        dict(representation=None),
        dict(output_unit=""),
        dict(bootstrap_seed=None),
        dict(bootstrap_resamples=1),
    ],
)
def test_screen_requires_explicit_design_and_uncertainty(kwargs):
    layout = trajectory_layout(8, 2, seed=19)
    x = independent_paths()
    with pytest.raises(ValueError):
        screen(layout, x, x.sum(axis=1), **kwargs)


@pytest.mark.parametrize(
    "kwargs",
    [
        dict(seed=True),
        dict(seed=-1),
        dict(levels=3),
        dict(levels=5),
        dict(stress_multiplier=0),
    ],
)
def test_invalid_restored_trajectory_layout_is_rejected(kwargs):
    options = dict(seed=1)
    options.update(kwargs)
    with pytest.raises(ValueError):
        trajectory_layout(4, 2, **options)
