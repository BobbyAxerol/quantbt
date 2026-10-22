"""Public synthetic controls, without private strategy or market imports."""

import numpy as np
import pandas as pd
import pytest

from quantbt.mode5.geometry.schema import EffectiveGeometry
from tools.mode5_research.winner_qualification import (
    attribute_original_account, environment_views, winner_neighborhood,
)


def market(days=420):
    n = days * 24
    t = np.arange(n)
    return pd.DataFrame(dict(close=100*np.exp(.00001*t + .03*np.sin(t/300)),
        volume=100 + 20*np.sin(t/71)), index=pd.date_range("2020-01-01", periods=n, freq="h", tz="UTC"))


def test_same_original_account_conserved_in_every_view():
    frame = market()
    views = environment_views(frame, descriptive_stop_ns=(frame.index[-1]+pd.Timedelta(hours=1)).value,
        historical_fit_stop_ns=pd.Timestamp("2021-01-01", tz="UTC").value)
    n = len(frame)
    eq = 20000 + np.cumsum(np.sin(np.arange(n)/30))
    arrays = dict(equity=eq, positions=np.ones((n, 1)), fees=np.full(n, .001))
    result = attribute_original_account(frame, arrays, views, initial_capital=20000.)
    assert result["financial_executions"] == result["optimizer_proposals"] == 0
    for families in result["views"].values():
        for row in families.values():
            attribution = row["attribution"]
            assert attribution["whole_days"] == 420
            assert attribution["grouped_pnl"] == pytest.approx(eq[-1]-20000, abs=1e-7)
            assert sum(r["days"] for r in attribution["rows"]) == 420
            assert sum(r["fees"] for r in attribution["rows"]) == pytest.approx(n*.001)
            assert all(r["annualized_sharpe"] is None for r in attribution["rows"])


def test_future_mutation_preserves_historical_fitted_partition():
    frame = market()
    stop = (frame.index[-1]+pd.Timedelta(hours=1)).value
    cutoff = pd.Timestamp("2021-01-01", tz="UTC").value
    original = environment_views(frame, descriptive_stop_ns=stop, historical_fit_stop_ns=cutoff)
    changed = frame.copy()
    changed.loc[changed.index >= "2021-01-15", "close"] *= 1.5
    mutated = environment_views(changed, descriptive_stop_ns=stop, historical_fit_stop_ns=cutoff)
    before = frame.index < "2021-01-15"
    for name in original["decision_vintage"]:
        left, right = original["decision_vintage"][name], mutated["decision_vintage"][name]
        assert left["fit_identity"] == right["fit_identity"]
        np.testing.assert_array_equal(left["labels"][before], right["labels"][before])


def test_mismatched_calendar_is_not_repaired():
    frame = market()
    with pytest.raises(ValueError):
        environment_views(frame, descriptive_stop_ns=frame.index[-1].value,
            historical_fit_stop_ns=pd.Timestamp("2021-01-01", tz="UTC").value)
    views = environment_views(frame, descriptive_stop_ns=(frame.index[-1]+pd.Timedelta(hours=1)).value,
        historical_fit_stop_ns=pd.Timestamp("2021-01-01", tz="UTC").value)
    with pytest.raises(ValueError):
        attribute_original_account(frame, dict(equity=np.ones(len(frame)-1),
            positions=np.zeros(len(frame))), views, initial_capital=20000.)


def test_held_design_keeps_all_axes_and_failure_dispositions():
    geometry = EffectiveGeometry.from_ranges(dict(length=(2, 20),
        scale=dict(kind="float", low=.1, high=1., step=.1), mode=["a", "b"]))
    design, neighborhood = winner_neighborhood(geometry, dict(length=2, scale=.5, mode="a"))
    assert not design["used_for_selection"]
    assert neighborhood.role == "local_validation"
    assert any(r["status"] != "READY" for r in design["rows"])
    assert any(r["direction"] == "category:mode" for r in design["rows"])
    assert len({r["point"]["candidate_id"] for r in design["rows"]
        if r["status"] == "READY"}) == neighborhood.coverage["unique_effective"]
    again, _ = winner_neighborhood(geometry, dict(length=2, scale=.5, mode="a"))
    assert design == again
