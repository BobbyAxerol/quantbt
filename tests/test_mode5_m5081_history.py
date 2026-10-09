"""M5-08.1 calendar/ownership/gate oracles, independent of private alphas."""

import numpy as np
import pandas as pd
import pytest

from tools.mode5_batteries.history import continuous_year_views, eligibility_breakdown


def test_leap_and_partial_year_views_keep_previous_actual_mark():
    times = pd.date_range("2023-01-01", "2025-03-01", freq="h", inclusive="left", tz="UTC")
    marks = np.linspace(20000., 25000., len(times))
    before = marks.copy()
    views = continuous_year_views(times.asi8, marks, initial_capital=20000.)
    assert [(v.year, v.days, v.complete_year) for v in views] == [
        (2023,365,True), (2024,366,True), (2025,59,False)]
    assert views[0].baseline_equity == 20000.
    assert views[1].baseline_equity == marks[365*24-1]
    assert views[1].baseline_equity != 20000.
    assert all(v.account_mode == "CONTINUOUS_ACCOUNT_VIEW" for v in views)
    np.testing.assert_array_equal(marks, before)
    marks[:] = 0
    assert views[1].equity[-1] > 0


@pytest.mark.parametrize("kind", ["gap", "duplicate", "partial", "minute", "nan", "shape"])
def test_bad_calendars_fail_closed(kind):
    times = pd.date_range("2023-01-01", periods=48, freq="h", tz="UTC").asi8.copy()
    marks = np.full(48,100.)
    if kind == "gap": times[24:] += 3_600_000_000_000
    if kind == "duplicate": times[24] = times[23]
    if kind == "partial": times,marks = times[:-1],marks[:-1]
    if kind == "minute": times += 60_000_000_000
    if kind == "nan": marks[0] = np.nan
    if kind == "shape": marks = marks[:-1]
    with pytest.raises(ValueError): continuous_year_views(times, marks, initial_capital=100.)


def test_future_mark_mutation_cannot_change_earlier_view():
    index = pd.date_range("2023-01-01", "2025-01-01", freq="h", inclusive="left", tz="UTC")
    marks = np.full(len(index),110.)
    original = continuous_year_views(index.asi8, marks, initial_capital=100.)
    marks[index.year == 2024] = 80.
    mutated = continuous_year_views(index.asi8, marks, initial_capital=100.)
    assert original[0] == mutated[0]
    assert original[1].equity != mutated[1].equity
    assert mutated[1].baseline_equity == 110.


def test_profitable_but_ineligible_is_not_false_no_edge():
    row = eligibility_breakdown(.06,.08,.01,daily_count=365)
    assert row["profitable"] and row["risk_pass"] and row["support_pass"]
    assert row["utility"] == pytest.approx(-.03)
    assert not row["quality_pass"] and row["reason"] == "QUALITY_FAIL"


@pytest.mark.parametrize("values,count,reason", [
    ((0.,0.,0.),365,"QUALITY_FAIL"), ((-.1,.2,.01),365,"QUALITY_FAIL"),
    ((None,.2,.01),365,"UNDEFINED"), ((.9,.6,.01),365,"RISK_FAIL"),
    ((.1,.01,.01),60,"SUPPORT_FAIL"), ((.1,.01,.01),365,"ELIGIBLE")])
def test_gate_units_null_and_support(values,count,reason):
    assert eligibility_breakdown(*values,daily_count=count)["reason"] == reason


def test_inventory_reset_is_not_inferred_from_calendar_slicing():
    times = pd.date_range("2023-12-31", periods=48, freq="h", tz="UTC").asi8
    marks = np.r_[np.full(24,110.),np.full(24,99.)]
    views = continuous_year_views(times,marks,initial_capital=100.)
    assert views[1].equity[-1]/views[1].baseline_equity-1 == pytest.approx(-.1)
    assert views[1].equity[-1]/100.-1 == pytest.approx(-.01)
