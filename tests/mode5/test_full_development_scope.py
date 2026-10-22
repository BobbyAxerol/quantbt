from copy import deepcopy

import numpy as np
import pytest

from quantbt.mode5.diagnostics.full_development import (
    DAY_NS, HOUR_NS, DevelopmentCalendar, WorkQuestion, work_manifest,
)


def tape(days=12, extra=3):
    return np.arange(0, (days * 24 + extra) * HOUR_NS, HOUR_NS, dtype=np.int64)


def test_partial_latest_day_and_readiness_are_reported_without_whole_year_exclusion():
    scope = DevelopmentCalendar.from_times(tape(), requested_start_ns=0, readiness_bars=30)
    assert scope.scored_start_ns == 2 * DAY_NS
    assert scope.scored_stop_ns == 12 * DAY_NS
    assert scope.scored_bars == 240
    assert scope.partial_days == ((12 * DAY_NS, 3),)
    assert scope.to_metadata()["status"] == "READINESS_PREFIX_GAP"
    assert scope.to_metadata()["unsupported_prefix_hours"] == 48


def test_existing_prehistory_meets_requested_day_and_copy_keeps_identity():
    scope = DevelopmentCalendar.from_times(tape(), requested_start_ns=5 * DAY_NS,
        readiness_bars=72)
    assert scope.scored_start_ns == 5 * DAY_NS
    assert scope.to_metadata()["has_pre_requested_history"]
    assert scope.to_metadata()["requested_start_met"]
    assert deepcopy(scope).identity == scope.identity


def test_missing_internal_hour_is_not_silently_filled():
    scope = DevelopmentCalendar.from_times(np.delete(tape(), 100),
        requested_start_ns=0, readiness_bars=0)
    assert scope.missing_hours == (100 * HOUR_NS,)
    assert scope.to_metadata()["status"] == "MISSING_SCORED_HOURS"
    with pytest.raises(ValueError, match="missing scored"):
        scope.require_complete()


@pytest.mark.parametrize("bad", [np.array([0, 0]), np.array([1, HOUR_NS]),
    np.array([HOUR_NS, 0]), np.array([0.0, float(HOUR_NS)])])
def test_bad_clock_rejects(bad):
    with pytest.raises(ValueError):
        DevelopmentCalendar.from_times(bad, requested_start_ns=0, readiness_bars=0)


def test_partial_year_and_leap_day_keep_real_calendar_counts():
    days = 366 + 70
    scope = DevelopmentCalendar.from_times(tape(days, 7), requested_start_ns=0,
        readiness_bars=0)
    assert scope.to_metadata()["scored_days"] == days


def test_scope_change_and_new_source_cannot_masquerade_as_reuse():
    with pytest.raises(ValueError, match="matching identity"):
        WorkQuestion("x", "old account begins a year later", "old", "new",
            "EXACT_REUSE", "path", 0, "start changed")
    with pytest.raises(ValueError, match="zero financial"):
        WorkQuestion("x", "rerender", "same", "same", "REANALYZE_ONLY",
            "report", 1, "use retained metrics")
    q = WorkQuestion("x", "full account", "old", "new",
        "INCOMPATIBLE_ECONOMICS_OR_ALPHA", "path", 1, "initial account changed")
    m = work_manifest([q])
    assert m["new_financial_calls"] == 1
    assert m["disposition_counts"][q.disposition] == 1
    assert m == work_manifest([deepcopy(q)])
