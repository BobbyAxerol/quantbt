"""Independent arithmetic and fail-closed gates for the research admission."""

import pytest

from tools.mode4_quarterly.admission import ControlTiming, forecast, proposal_budget


def control(alpha, role, seconds):
    return ControlTiming(alpha, role, seconds, 400., execution_identity="fixture-v1")


def test_attempt_budget_is_not_policy_count():
    assert proposal_budget() == dict(primary=19456, reference=2432, total=21888)


def test_known_slow_work_can_reject_before_more_finance():
    result = forecast([control("A-HMA", "is", 5.)])
    assert result["partial_search_wall_seconds"] == 6080.
    assert result["status"] == "REJECT_PARTIAL_SEARCH_FORECAST_EXCEEDS_CAP"
    assert not result["launch_allowed"]
    assert not result["optimizer_started"]


def test_fast_kernel_or_incomplete_roles_cannot_admit():
    result = forecast([control("A-HMA", "is", .001)])
    assert result["status"] == "NOT_ADMITTED_MISSING_WHOLE_WORK_MEASUREMENTS"
    assert not result["launch_allowed"]


def test_measured_maximum_is_used_not_best_control():
    result = forecast([control("A-HMA", "is", 1.), control("A-HMA", "is", 5.)])
    assert result["costs"]["A-HMA"]["search_worker_seconds"] == 24320.


def test_full_fixed_work_arithmetic():
    rows = [control(alpha, role, .01) for alpha in
            ("A-SC", "A-HMA", "A-HASH", "A-VWAP", "A-RSI")
            for role in ("is", "forward", "final")]
    result = forecast(rows, setup_seconds=10.)
    search = 21888 * .01
    observers = 19 * (8 * 36 + 18) * .01
    final = 34 * .01
    assert result["estimated_whole_work_wall_seconds"] == pytest.approx(
        10 + (search + observers + final) * 1.25 / 4)
    assert result["timing_admitted"]
    assert not result["launch_allowed"]


@pytest.mark.parametrize("kwargs", [dict(workers=5), dict(workers=0),
    dict(observer_candidates=20), dict(queue_cap_seconds=0), dict(overhead_fraction=-1)])
def test_invalid_budgets_fail(kwargs):
    with pytest.raises(ValueError):
        forecast([control("A-HMA", "is", 1.)], **kwargs)


def test_preparation_cannot_be_excluded():
    with pytest.raises(ValueError):
        ControlTiming("A-HMA", "is", .001, 400., False, "kernel-only")


@pytest.mark.parametrize("kwargs", [dict(elapsed_seconds=True), dict(peak_rss_mib=True),
    dict(elapsed_seconds=float("nan")), dict(peak_rss_mib=float("inf")),
    dict(includes_preparation=1), dict(execution_identity=1), dict(execution_identity=" ")])
def test_boolean_or_malformed_observations_are_not_measurements(kwargs):
    values=dict(alpha="A-HMA", role="is", elapsed_seconds=1., peak_rss_mib=400.,
                execution_identity="fixture-v1")
    with pytest.raises(ValueError):
        ControlTiming(**(values | kwargs))
