"""Analytic rank-association oracles conditional on an outcome-blind roster."""

from copy import deepcopy
import json

import numpy as np
import pytest

from tools.mode5_geometry import finite_panel_screen


def candidate(i, *, branch="a", x=None, utility=None, risk=None, status="COMPLETE"):
    return dict(
        candidate_id=f"{branch}-{i}",
        branch_id=branch,
        status=status,
        parameters=dict(x=float(i) if x is None else x),
        metrics=dict(
            utility=float(i) if utility is None else utility,
            risk=-float(i) if risk is None else risk,
        ),
    )


def screen(rows, **kwargs):
    options = dict(
        panel_id="outcome-blind-discovery-v1",
        axis_names=("x",),
        active_axes_by_branch={"a": ("x",)},
        units=dict(utility="return", risk="money"),
        outcome_blind=True,
        bootstrap_seed=0,
        bootstrap_resamples=64,
    )
    options.update(kwargs)
    return finite_panel_screen(rows, **options)


def oracle_midrank(values):
    return np.array(
        [
            sum(other < value for other in values)
            + (sum(other == value for other in values) + 1) / 2
            for value in values
        ]
    )


def oracle_rho(x, y):
    x, y = oracle_midrank(x), oracle_midrank(y)
    x, y = x - x.mean(), y - y.mean()
    return np.sum(x * y) / np.sqrt(np.sum(x * x) * np.sum(y * y))


def test_multiple_metrics_have_meaningful_direction_even_when_utility_is_constant():
    rows = [candidate(i, utility=0.5, risk=2 * i) for i in range(24)]
    result = screen(rows)
    effects = result["branches"]["a"]["associations"]["x"]
    assert effects["utility"]["status"] == "CONSTANT_METRIC_ON_PANEL"
    assert effects["utility"]["rho"] is None
    assert effects["risk"]["rho"] == pytest.approx(1.0)
    assert result["inference"] == "CONDITIONAL_FINITE_PANEL"
    assert (
        result["sensitivity_indices"] is None
        and not result["parameter_removal_authorized"]
    )
    assert "market-CI" in result["interpretation"]
    assert result["missing_support"] == [
        dict(
            branch_id="a", axis="x", metric="utility", reason="CONSTANT_METRIC_ON_PANEL"
        )
    ]
    json.dumps(result, allow_nan=False)


def test_opposite_branches_and_conditional_axes_are_not_pooled_into_global_ranking():
    rows = []
    for i in range(24):
        a = candidate(i, utility=3 * i, risk=-i)
        a["parameters"]["z"] = float(23 - i)
        rows.append(a)
        rows.append(candidate(i, branch="b", utility=-3 * i, risk=i))
    result = screen(
        rows,
        axis_names=("x", "z"),
        active_axes_by_branch={"a": ("x", "z"), "b": ("x",)},
    )
    a, b = (
        result["branches"]["a"]["associations"],
        result["branches"]["b"]["associations"],
    )
    assert a["x"]["utility"]["rho"] == pytest.approx(1.0)
    assert b["x"]["utility"]["rho"] == pytest.approx(-1.0)
    assert a["z"]["utility"]["rho"] == pytest.approx(-1.0)
    assert b["z"]["utility"]["status"] == "INACTIVE_ON_BRANCH"
    assert b["z"]["utility"]["rho"] is None
    assert "global_ranking" not in result


def test_cast_ties_use_independent_midrank_oracle():
    x = [1.0, 1.0, 2.0, 3.0, 3.0, 4.0]
    y = [6.0, 5.0, 4.0, 3.0, 2.0, 1.0]
    rows = [candidate(i, x=value, utility=y[i]) for i, value in enumerate(x)]
    result = screen(rows)["branches"]["a"]["associations"]["x"]["utility"]
    assert result["rho"] == pytest.approx(oracle_rho(x, y))
    assert result["support"]["unique_axis_values"] == 4


def test_candidate_resampling_recomputes_tied_ranks_and_matches_seeded_oracle():
    rows = [candidate(i, x=i // 2, utility=(i * 7) % 23) for i in range(24)]
    original = deepcopy(rows)
    before = np.random.get_state()
    result = screen(rows)
    after = np.random.get_state()
    np.testing.assert_array_equal(before[1], after[1])
    assert before[2:] == after[2:]
    assert rows == original and result == screen(rows)
    rng = np.random.default_rng(0)
    values = []
    for _ in range(64):
        sample = [rows[i] for i in rng.integers(len(rows), size=len(rows))]
        values.append(
            oracle_rho(
                [r["parameters"]["x"] for r in sample],
                [r["metrics"]["utility"] for r in sample],
            )
        )
    interval = result["branches"]["a"]["associations"]["x"]["utility"][
        "confidence_interval"
    ]
    np.testing.assert_allclose(
        interval, np.quantile(values, [0.025, 0.975]), atol=1e-14
    )
    assert result["bootstrap"]["resample_unit"] == "candidate_within_branch"
    assert result["bootstrap"]["paired_columns"]


def test_missing_failed_and_no_trade_rows_survive_per_metric_support():
    rows = [candidate(i) for i in range(24)]
    rows[0]["metrics"]["utility"] = None
    rows[1]["parameters"]["x"] = None
    rows[2]["status"] = "FAILED"
    rows[3]["status"] = "NO_TRADE"
    result = screen(rows)
    associations = result["branches"]["a"]["associations"]["x"]
    assert associations["utility"]["support"]["paired_candidates"] == 21
    assert associations["risk"]["support"]["paired_candidates"] == 22
    assert associations["utility"]["support"]["excluded_status_rows"] == 1
    assert associations["utility"]["support"]["missing_axis_rows"] == 1
    assert associations["utility"]["support"]["missing_metric_rows"] == 1
    assert len(result["candidate_rows"]) == 24
    assert result["candidate_rows"][2]["status"] == "FAILED"
    assert result["branches"]["a"]["status_counts"]["NO_TRADE"] == 1


def test_correlated_axes_remain_associations_not_causal_variance_decomposition():
    rows = [candidate(i) for i in range(24)]
    for row in rows:
        row["parameters"]["z"] = row["parameters"]["x"]
    result = screen(
        rows, axis_names=("x", "z"), active_axes_by_branch={"a": ("x", "z")}
    )
    associations = result["branches"]["a"]["associations"]
    assert associations["x"]["utility"]["rho"] == associations["z"]["utility"]["rho"]
    assert "confounding" in result["interpretation"]
    assert result["sensitivity_indices"] is None


def test_nonmonotone_effect_can_have_zero_rank_association_without_inactivity_claim():
    rows = [
        candidate(i, x=float(i - 12), utility=float((i - 12) ** 2)) for i in range(25)
    ]
    result = screen(rows)["branches"]["a"]["associations"]["x"]["utility"]
    assert result["rho"] == pytest.approx(0.0, abs=1e-15)
    assert result["support"]["unique_metric_values"] > 1
    assert result["status"] in {
        "OBSERVED_RANK_ASSOCIATION",
        "NO_RANK_ASSOCIATION_ON_PANEL",
    }


def test_interacting_finite_panel_is_not_a_global_sensitivity_oracle():
    rows = []
    for i, (x, z) in enumerate((x, z) for x in range(-3, 4) for z in range(-3, 4)):
        row = candidate(i, x=float(x), utility=float(x * z), risk=float(x + z))
        row["parameters"]["z"] = float(z)
        rows.append(row)
    result = screen(
        rows, axis_names=("x", "z"), active_axes_by_branch={"a": ("x", "z")}
    )
    for axis in ("x", "z"):
        effect = result["branches"]["a"]["associations"][axis]["utility"]
        assert effect["rho"] == pytest.approx(0.0, abs=1e-15)
        assert effect["support"]["unique_metric_values"] > 1
    assert result["sensitivity_indices"] is None


@pytest.mark.parametrize("scale,offset", [(2.0**-1000, 0.0), (2.0**600, 2.0**650)])
def test_finite_panel_ranks_do_not_overflow_or_underflow_raw_moments(scale, offset):
    rows = [
        candidate(i, x=offset + scale * i, utility=offset - scale * i)
        for i in range(24)
    ]
    result = screen(rows)["branches"]["a"]["associations"]["x"]["utility"]
    assert result["rho"] == pytest.approx(-1.0)


def test_empty_branch_and_unvaried_axis_produce_missing_support_not_zero_importance():
    rows = [candidate(i, x=3.0) for i in range(24)]
    result = screen(rows, active_axes_by_branch={"a": ("x",), "missing": ("x",)})
    a = result["branches"]["a"]["associations"]["x"]["utility"]
    missing = result["branches"]["missing"]["associations"]["x"]["utility"]
    assert a["status"] == "NO_AXIS_VARIATION_ON_PANEL" and a["rho"] is None
    assert (
        missing["status"] == "INSUFFICIENT_PAIRED_CANDIDATES" and missing["rho"] is None
    )
    assert missing["support"]["branch_candidates"] == 0
    assert len(result["missing_support"]) == 4


def test_degenerate_candidate_resamples_are_counted_and_cannot_create_zero_width_ci():
    result = screen([candidate(i) for i in range(3)])
    stats = result["branches"]["a"]["associations"]["x"]["utility"]
    assert stats["rho"] == pytest.approx(1.0)
    assert stats["confidence_interval"] is None
    assert stats["bootstrap"]["status"] == "UNAVAILABLE_DEGENERATE_RESAMPLES"
    assert stats["bootstrap"]["invalid_resamples"] > 0


@pytest.mark.parametrize(
    "bad",
    [
        "duplicate_id",
        "unknown_branch",
        "unknown_status",
        "missing_axis",
        "missing_metric",
        "nan",
        "inf",
        "category_code",
    ],
)
def test_malformed_finite_panel_is_rejected_not_silently_reduced(bad):
    rows = [candidate(i) for i in range(24)]
    if bad == "duplicate_id":
        rows[1]["candidate_id"] = rows[0]["candidate_id"]
    elif bad == "unknown_branch":
        rows[0]["branch_id"] = "unknown"
    elif bad == "unknown_status":
        rows[0]["status"] = "bad"
    elif bad == "missing_axis":
        rows[0]["parameters"] = {}
    elif bad == "missing_metric":
        rows[0]["metrics"] = dict(utility=1.0)
    elif bad == "nan":
        rows[0]["metrics"]["utility"] = np.nan
    elif bad == "inf":
        rows[0]["parameters"]["x"] = np.inf
    elif bad == "category_code":
        rows[0]["parameters"]["x"] = "category-a"
    with pytest.raises(ValueError):
        screen(rows)


@pytest.mark.parametrize(
    "kwargs",
    [
        dict(outcome_blind=False),
        dict(outcome_blind=None),
        dict(panel_id=""),
        dict(bootstrap_seed=None),
        dict(bootstrap_resamples=1),
        dict(units={}),
        dict(active_axes_by_branch={"a": ()}),
        dict(active_axes_by_branch={"a": ("unknown",)}),
        dict(axis_names=("x", "x")),
    ],
)
def test_requires_outcome_blind_registration_all_active_axis_declaration_and_uncertainty(
    kwargs,
):
    with pytest.raises(ValueError):
        screen([candidate(i) for i in range(24)], **kwargs)
