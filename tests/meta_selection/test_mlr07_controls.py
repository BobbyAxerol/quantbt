from copy import deepcopy

import pandas as pd
import pytest

from tools.meta_model_research.forward_controls import (
    structural_choice,
    structural_losses,
    retention_gate,
)


def history():
    return [
        dict(
            month=str(m),
            available_at=m.to_timestamp().tz_localize("UTC").isoformat(),
            status="VALID",
            Q=1.0,
        )
        for m in pd.period_range("2022-01", "2022-12", freq="M")
    ]


def test_independent_weighted_oracle_and_forward_error_identity():
    rows = [
        dict(origin="a", weight=0.25, delta_is=2.0, y=1.0, predictions={"R": 0.5}),
        dict(origin="a", weight=0.75, delta_is=-1.0, y=2.0, predictions={"R": 1.0}),
        dict(origin="b", weight=1.0, delta_is=1.0, y=0.0, predictions={"R": 0.0}),
    ]
    out = structural_losses(rows)["models"]
    assert out["R"]["mse"] == pytest.approx((0.25 * 0.25 + 0.75 * 1) / 2)
    assert out["Y_IS"]["mse"] == pytest.approx((0.25 * 1 + 0.75 * 9 + 1) / 2)
    assert out["Y_ZERO"]["mse"] == pytest.approx((0.25 * 1 + 0.75 * 4) / 2)
    assert out["R"]["Y_MSE_equals_Q_MSE"]
    bad = deepcopy(rows)
    bad[1]["predictions"]["X"] = 2
    with pytest.raises(ValueError, match="mask"):
        structural_losses(bad)


def test_structural_min_y_picks_low_is_max_q_keeps_anchor():
    rows = [
        dict(
            evaluation_id="a",
            candidate_id="a",
            raw_is=2.0,
            yhat=0.0,
            qhat=0.0,
            distance=0.0,
        ),
        dict(
            evaluation_id="b",
            candidate_id="b",
            raw_is=-2.0,
            yhat=-1.0,
            qhat=-3.0,
            distance=1.0,
        ),
    ]
    assert structural_choice(rows, "a", "min_y")["winner"] == "b"
    assert structural_choice(rows, "a", "max_q")["winner"] == "a"
    assert structural_choice([], "a", "min_y")["status"] == "NOT_SCORED"


def test_retention_past_only_and_no_calendar_compression():
    rows = history()
    args = dict(current_month="2023-02", cutoff="2023-01-31T23:00:00Z")
    old = retention_gate(rows, **args)
    assert old["accepted"] and old["count"] == 12 and old["window_end"] == "2022-12"
    poison = dict(month="2023-02", available_at="invalid", status=object(), Q=object())
    delayed = dict(
        month="2023-01",
        available_at="2023-02-01T00:00:01Z",
        status=object(),
        Q=object(),
    )
    assert retention_gate(rows + [poison, delayed], **args) == old
    assert not retention_gate(rows[1:], **args)["accepted"]
    missing = deepcopy(rows)
    missing[3]["status"] = "NO_VARIANCE"
    missing[3]["Q"] = None
    assert not retention_gate(missing, **args)["accepted"]
    zero = [dict(r, Q=0.0) for r in rows]
    assert retention_gate(zero, **args)["reason"] == "NONPOSITIVE_PAST_MEAN"
    with pytest.raises(ValueError, match="duplicate"):
        retention_gate(rows + [rows[0]], **args)


@pytest.mark.parametrize(
    "field,value",
    [
        ("weight", 0.0),
        ("weight", -1.0),
        ("y", float("nan")),
        ("delta_is", float("inf")),
    ],
)
def test_invalid_loss_inputs_fail_closed(field, value):
    row = dict(origin="a", weight=1.0, delta_is=1.0, y=1.0, predictions={"R": 0.0})
    row[field] = value
    with pytest.raises(ValueError):
        structural_losses([row])
