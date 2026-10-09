import numpy as np
import pytest

from tools.mode5_geometry import paired_screen, saltelli_layout, validate_saltelli_outputs
from tools.mode5_geometry.design import SaltelliLayout


def structured_inputs(n, d, second=False):
    rng = np.random.default_rng(731)
    a, b = rng.random((n, d)), rng.random((n, d))
    result = []
    for left, right in zip(a, b):
        result.append(left)
        for j in range(d):
            cross = left.copy(); cross[j] = right[j]; result.append(cross)
        if second:
            for j in range(d):
                cross = right.copy(); cross[j] = left[j]; result.append(cross)
        result.append(right)
    return np.array(result)


def test_m5t_056_saltelli_budget_and_arbitrary_panel_rejection():
    layout = saltelli_layout(256, 10, stress_multiplier=3)
    assert layout.rows == 3072 and layout.execution_cells == 9216
    x = np.random.default_rng(1).random((3072, 10))
    with pytest.raises(ValueError, match="structured"):
        validate_saltelli_outputs(layout, x, x.sum(axis=1), method="plain_qmc", independent_axes=True)
    with pytest.raises(ValueError, match="cross"):
        validate_saltelli_outputs(layout, x, x.sum(axis=1), method="saltelli_pick_freeze_v1", independent_axes=True)


def test_malformed_restored_saltelli_layout_rejected():
    with pytest.raises(ValueError, match="layout"):
        SaltelliLayout(256, 10, False, 256, 1)


@pytest.mark.parametrize("second", [False, True])
def test_valid_structured_design_not_an_implicit_market_job(second):
    layout = saltelli_layout(8, 2, second_order=second)
    x = structured_inputs(8, 2, second)
    out = validate_saltelli_outputs(layout, x, x.sum(axis=1), method="saltelli_pick_freeze_v1", independent_axes=True)
    assert out["status"] == "STRUCTURED_DESIGN_VALID" and out["sensitivity_indices"] is None


def test_m5t_057_constant_output_is_undefined_not_zero_sensitivity():
    layout = saltelli_layout(8, 2)
    out = validate_saltelli_outputs(layout, structured_inputs(8, 2), np.ones(layout.rows),
        method="saltelli_pick_freeze_v1", independent_axes=True)
    assert out["status"] == "UNDEFINED_CONSTANT_OUTPUT" and out["sensitivity_indices"] is None


def test_invalid_and_coupled_rows_cannot_be_filtered_into_saltelli():
    layout = saltelli_layout(8, 2)
    x = structured_inputs(8, 2)
    for inputs, outputs, independent in ((x[:-1], np.ones(layout.rows-1), True),
        (x, np.r_[np.nan, np.ones(layout.rows-1)], True), (x, np.ones(layout.rows), False)):
        with pytest.raises(ValueError):
            validate_saltelli_outputs(layout, inputs, outputs, method="saltelli_pick_freeze_v1", independent_axes=independent)


def test_m5t_058_screen_keeps_risk_cost_activity_even_if_utility_flat():
    center = dict(utility=.5, tail=-1., cost=10., opportunities=20., holding=3.)
    out = paired_screen(center, [dict(probe_id="risk", status="COMPLETE", metrics=dict(
        utility=.5, tail=-5., cost=25., opportunities=30., holding=6.))],
        units=dict(utility="Sharpe", tail="money", cost="money", opportunities="count", holding="bars"))
    assert out["results"]["utility"]["status"] == "NO_OBSERVED_CHANGE"
    assert all(out["results"][m]["status"] == "OBSERVED_CHANGE" for m in ("tail", "cost", "opportunities", "holding"))
    assert not out["parameter_removal_authorized"] and out["results"]["tail"]["minimum_delta"] == -4.


def test_failed_and_absent_metric_cells_remain_visible():
    out = paired_screen(dict(utility=1., fees=None), [dict(probe_id="bad", status="FAILED",
        metrics=dict(utility=None, fees=None))], units=dict(utility="return", fees="money"))
    assert len(out["rows"]) == 1 and out["results"]["utility"]["status"] == "UNAVAILABLE"


def test_metric_unit_columns_must_align():
    with pytest.raises(ValueError):
        paired_screen(dict(utility=1.), [], units={})
