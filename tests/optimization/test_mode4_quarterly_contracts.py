"""Synthetic M4Q-01/02/03/05 contract oracles; no finance or optimizer work."""

from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timedelta, timezone
import math

import pytest

from tools.mode4_quarterly.contracts import (
    DATA_START, DAILY_SHARPE_POLICY, DailyAccountReturn, OOS_END,
    attribution_segments, quarterly_calendar,
)
from tools.mode4_quarterly.selection import score_candidate, select_floor_mean


DAY = timedelta(days=1)


def utc(year, month, day):
    return datetime(year, month, day, tzinfo=timezone.utc)


@pytest.fixture
def fold():
    return quarterly_calendar()[0]


def account(start, means=(-0.01, 0.01, 0.03, -0.02)):
    """Hand-designed symmetric samples, independent of the segment builder."""
    rows, offset = [], 0
    for n, mean in zip((91, 91, 91, 92), means, strict=True):
        values = [mean - 0.02, mean + 0.02] * (n // 2)
        if n % 2:
            values.append(mean)
        for value in values:
            rows.append(DailyAccountReturn(start + offset * DAY, value))
            offset += 1
    return tuple(rows)


def hand_sharpe(values):
    """Two-pass sample-variance oracle, not the shared tested reducer."""
    n = len(values)
    mean = math.fsum(values) / n
    variance = math.fsum((value - mean) ** 2 for value in values) / (n - 1)
    return mean / math.sqrt(variance) * math.sqrt(365)


def test_exact_registered_calendar_and_rolling365d():
    folds = quarterly_calendar()
    assert tuple(row.fold_id for row in folds) == (
        "2022Q1", "2022Q2", "2022Q3", "2022Q4",
        "2023Q1", "2023Q2", "2023Q3", "2023Q4",
        "2024Q1", "2024Q2", "2024Q3", "2024Q4",
        "2025Q1", "2025Q2", "2025Q3", "2025Q4",
        "2026Q1", "2026Q2", "2026Q3",
    )
    assert folds[0].oos_start == utc(2022, 1, 1)
    assert folds[-1].oos_end == utc(2026, 10, 1)
    assert sum((row.oos_end - row.oos_start).days for row in folds) == 1734
    assert all(left.oos_end == right.oos_start for left, right in zip(folds, folds[1:]))
    assert all(row.is_end == row.oos_start == row.data_cutoff for row in folds)
    assert all(row.is_end - row.is_start == 365 * DAY for row in folds)
    assert all(row.preload_start == utc(2020, 1, 1) for row in folds)
    assert folds[0].is_start == utc(2021, 1, 1)
    assert folds[9].is_start == utc(2023, 4, 2)  # A duration, not one calendar year.
    assert (folds[8].oos_end - folds[8].oos_start).days == 91
    assert len({row.identity for row in folds}) == 19
    assert quarterly_calendar(data_end=utc(2026, 10, 16)) == folds
    assert quarterly_calendar() == folds


@pytest.mark.parametrize("nanoseconds", [1, 59, 999])
def test_submicrosecond_day_labels_cannot_inflate_support(fold, nanoseconds):
    import pandas as pd

    for segment in attribution_segments(fold):
        stamp = pd.Timestamp(segment.start) + pd.Timedelta(nanoseconds=nanoseconds)
        with pytest.raises(ValueError, match="midnight"):
            DailyAccountReturn(stamp, .01)


def test_exact_pandas_midnight_is_still_a_valid_day(fold):
    import pandas as pd

    row = DailyAccountReturn(pd.Timestamp(fold.is_start), .01)
    assert row.day == fold.is_start


def test_preload_permission_is_separate_from_scored_warmup(fold):
    later = quarterly_calendar(preload_start=utc(2020, 6, 1))[0]
    assert later.fold_id == fold.fold_id
    assert later.is_start == fold.is_start
    assert later.identity != fold.identity
    for start in (utc(2019, 12, 31), utc(2021, 1, 2)):
        with pytest.raises(ValueError, match="preload"):
            quarterly_calendar(preload_start=start)


def test_future_snapshot_cannot_manufacture_a_complete_last_quarter():
    with pytest.raises(ValueError, match="19 complete quarters"):
        quarterly_calendar(data_end=OOS_END - timedelta(microseconds=1))


@pytest.mark.parametrize("change", [
    {"fold_id": "2022Q2"}, {"oos_end": utc(2022, 3, 31)},
    {"is_start": utc(2020, 12, 31)}, {"is_end": utc(2022, 1, 2)},
    {"oos_start": utc(2022, 2, 1)}, {"oos_start": utc(2026, 10, 1)},
])
def test_malformed_fold_cannot_bypass_calendar_validation(fold, change):
    with pytest.raises(ValueError):
        replace(fold, **change)


def test_four_segments_cover_account_once_with_fixed_day_weights(fold):
    segments = attribution_segments(fold)
    assert tuple(row.segment_id for row in segments) == tuple(f"2022Q1/is-{i}" for i in range(1, 5))
    assert tuple(row.start for row in segments) == (
        utc(2021, 1, 1), utc(2021, 4, 2), utc(2021, 7, 2), utc(2021, 10, 1),
    )
    assert tuple(row.end for row in segments) == (
        utc(2021, 4, 2), utc(2021, 7, 2), utc(2021, 10, 1), utc(2022, 1, 1),
    )
    assert tuple(row.calendar_days for row in segments) == (91, 91, 91, 92)
    assert tuple(row.weight for row in segments) == (91 / 365, 91 / 365, 91 / 365, 92 / 365)
    memberships = [row.start + j * DAY for row in segments for j in range(row.calendar_days)]
    assert memberships == [fold.is_start + j * DAY for j in range(365)]
    leap_segments = attribution_segments(quarterly_calendar()[9])
    assert sum(row.start <= utc(2024, 2, 29) < row.end for row in leap_segments) == 1


def test_hand_calculated_sharpe_and_floor_mean_profile(fold):
    rows = account(fold.is_start)
    result = select_floor_mean({"synthetic": rows}, fold=fold, information_as_of=fold.data_cutoff)
    candidate = result.candidates[0]
    # In each 91-point sample there are 45 symmetric pairs and the mean.
    # Their sample variance is .02**2. The 92-point variance is .02**2*92/91.
    expected = tuple(mean / 0.02 * math.sqrt(365) for mean in (-0.01, 0.01, 0.03))
    expected += (-0.02 / 0.02 * math.sqrt(365 * 91 / 92),)
    mean = math.fsum(n * value for n, value in zip((91, 91, 91, 92), expected)) / 365
    assert tuple(row.sharpe_annual for row in candidate.segments) == pytest.approx(expected, abs=1e-12)
    assert candidate.floor_sharpe == pytest.approx(min(expected), abs=1e-12)
    assert candidate.weighted_mean_sharpe == pytest.approx(mean, abs=1e-12)
    assert candidate.score == pytest.approx(min(expected) + 0.25 * mean, abs=1e-12)
    assert candidate.score < 0  # Negative floors are not a rejection or a fake zero.
    assert candidate.eligible and result.selected_candidate_id == "synthetic"
    assert result.profile_id == "mode4_is_environment_floor_mean_sharpe_v1"
    assert result.formula_version == "environment_floor_mean_v1"
    assert result.mean_coefficient == 0.25
    assert DAILY_SHARPE_POLICY.annual_periods == 365
    assert DAILY_SHARPE_POLICY.variance_ddof == 1
    assert DAILY_SHARPE_POLICY.risk_free_per_period == 0
    for row, n in zip(candidate.segments, (91, 91, 91, 92), strict=True):
        assert row.valid_days == row.observed_days == row.estimate.n == n
        assert row.missing_days == row.unavailable_days == 0
        assert row.estimate.variance_ddof == 1


def test_first_fee_return_and_boundary_returns_are_retained(fold):
    rows = list(account(fold.is_start))
    rows[0] = replace(rows[0], value=-0.20)
    rows[91] = replace(rows[91], value=-0.15)
    score = score_candidate("first-cost", rows, fold=fold, information_as_of=fold.data_cutoff)
    for segment, start, end in zip(score.segments, (0, 91, 182, 273), (91, 182, 273, 365), strict=True):
        sample = [row.value for row in rows[start:end]]
        assert segment.sharpe_annual == pytest.approx(hand_sharpe(sample), abs=1e-12)
        assert segment.estimate.mean == pytest.approx(math.fsum(sample) / len(sample), abs=1e-15)


@pytest.mark.parametrize("fold_index", range(19))
def test_same_hand_account_attributes_identically_on_every_registered_fold(fold_index):
    fold = quarterly_calendar()[fold_index]
    rows = account(fold.is_start)
    score = score_candidate("calendar-control", rows, fold=fold, information_as_of=fold.data_cutoff)
    expected = tuple(hand_sharpe([row.value for row in rows[start:end]])
                     for start, end in ((0, 91), (91, 182), (182, 273), (273, 365)))
    assert score.eligible
    assert tuple(row.sharpe_annual for row in score.segments) == pytest.approx(expected, abs=1e-12)
    assert sum(row.observed_days for row in score.segments) == 365
    assert sum(row.missing_days for row in score.segments) == 0


def test_warmup_and_future_suffix_changes_do_not_change_selection(fold):
    rows = account(fold.is_start)
    before = select_floor_mean({"x": rows}, fold=fold, information_as_of=fold.data_cutoff)
    outside = (
        DailyAccountReturn(fold.is_start - DAY, None, "BANKRUPT", "outside scored IS"),
        DailyAccountReturn(fold.is_start - DAY, 1e50),
        DailyAccountReturn(fold.is_end, None, "INVALID", "current forward is closed"),
        DailyAccountReturn(fold.is_end, -1e50),
        DailyAccountReturn(utc(2026, 10, 1), 1e50),
    )
    after = select_floor_mean({"x": (*outside, *reversed(rows))}, fold=fold, information_as_of=fold.data_cutoff)
    assert after == before


@pytest.mark.parametrize("removed, supported", [(31, True), (32, False), (91, False)])
def test_min60_daily_support_and_missing_days_are_not_filled(fold, removed, supported):
    rows = account(fold.is_start)[removed:]
    score = score_candidate("sparse", rows, fold=fold, information_as_of=fold.data_cutoff)
    segment = score.segments[0]
    assert segment.valid_days == segment.observed_days == 91 - removed
    assert segment.missing_days == removed
    assert segment.segment.weight == 91 / 365
    assert score.eligible is supported
    assert all(row.status == "VALID" for row in score.segments[1:])
    if supported:
        expected = math.fsum(row.segment.calendar_days * row.sharpe_annual for row in score.segments) / 365
        assert score.weighted_mean_sharpe == pytest.approx(expected, abs=1e-12)
    else:
        assert segment.status == "INSUFFICIENT" and segment.sharpe_annual is None
        assert score.floor_sharpe is score.weighted_mean_sharpe is score.score is None


@pytest.mark.parametrize("segment_index, start, end", [(0, 0, 91), (1, 91, 182), (2, 182, 273), (3, 273, 365)])
@pytest.mark.parametrize("retained", [59, 60])
def test_each_segment_independently_requires60_daily_observations(fold, segment_index, start, end, retained):
    rows = account(fold.is_start)
    kept = rows[:start] + rows[end - retained:]
    score = score_candidate("support-boundary", kept, fold=fold, information_as_of=fold.data_cutoff)
    segment = score.segments[segment_index]
    assert segment.valid_days == retained
    assert segment.missing_days == end - start - retained
    assert score.eligible is (retained == 60)
    assert all(row.status == "VALID" for i, row in enumerate(score.segments) if i != segment_index)
    if retained == 60:
        assert segment.sharpe_annual == pytest.approx(
            hand_sharpe([row.value for row in rows[end - retained:end]]), abs=1e-12,
        )
    else:
        assert segment.sharpe_annual is score.score is None


def test_explicit_unavailable_keeps_support_and_null_witness(fold):
    rows = list(account(fold.is_start))
    rows[0] = replace(rows[0], value=None, status="UNAVAILABLE", reason="producer mark missing")
    result = score_candidate("missing", rows, fold=fold, information_as_of=fold.data_cutoff)
    segment = result.segments[0]
    assert result.eligible
    assert segment.observed_days == 91 and segment.valid_days == 90
    assert segment.missing_days == 0 and segment.unavailable_days == 1
    assert segment.observation_dispositions == ((fold.is_start, "UNAVAILABLE", "producer mark missing"),)
    assert segment.estimate.n == 90
    assert segment.sharpe_annual == pytest.approx(hand_sharpe([row.value for row in rows[1:91]]), abs=1e-12)


@pytest.mark.parametrize("value", [0.0, 0.01, -0.01])
def test_zero_variance_has_null_sharpe_not_favorable_zero(fold, value):
    rows = tuple(DailyAccountReturn(fold.is_start + i * DAY, value) for i in range(365))
    result = select_floor_mean({"flat": rows}, fold=fold, information_as_of=fold.data_cutoff)
    assert result.status == "NO_SELECTION" and result.selected_candidate_id is None
    assert result.reason == "NO_SUPPORTED_CANDIDATE"
    assert result.ranking == () and result.candidates[0].score is None
    for segment in result.candidates[0].segments:
        assert segment.valid_days == segment.segment.calendar_days
        assert segment.status == "UNDEFINED" and segment.sharpe_annual is None
        assert segment.reasons == ("zero return variance",)
        assert segment.estimate.status == "UNDEFINED"


def test_valid_zero_mean_sharpe_and_flat_days_are_retained(fold):
    rows = list(account(fold.is_start))
    values = [0.0] * 45 + [-0.02, 0.02] * 23
    rows[:91] = [DailyAccountReturn(fold.is_start + i * DAY, value) for i, value in enumerate(values)]
    score = score_candidate("with-flat-days", rows, fold=fold, information_as_of=fold.data_cutoff)
    segment = score.segments[0]
    assert score.eligible and segment.status == "VALID"
    assert segment.valid_days == segment.estimate.n == 91 and segment.zero_return_days == 45
    assert segment.sharpe_annual == pytest.approx(0, abs=1e-12)
    assert segment.estimate.variance == pytest.approx(46 * 0.02**2 / 90, abs=1e-15)


@pytest.mark.parametrize("status", ["INVALID", "BANKRUPT"])
def test_failed_or_bankrupt_day_is_not_dropped_even_with_enough_other_days(fold, status):
    rows = list(account(fold.is_start))
    rows[0] = replace(rows[0], value=None, status=status, reason="synthetic producer failure")
    result = select_floor_mean({"failed": rows}, fold=fold, information_as_of=fold.data_cutoff)
    segment = result.candidates[0].segments[0]
    assert segment.valid_days == 90 and segment.status == status
    assert segment.invalid_days + segment.bankrupt_days == 1
    assert segment.sharpe_annual is None and result.candidates[0].score is None
    assert "synthetic producer failure" in segment.reasons[0]
    assert result.status == "NO_SELECTION" and len(result.candidates[0].segments) == 4


def test_late_observation_value_and_status_are_closed_at_cutoff(fold):
    rows = list(account(fold.is_start))
    rows[0] = replace(rows[0], available_at=fold.is_end + DAY, value=1e50)
    before = score_candidate("late", rows, fold=fold, information_as_of=fold.data_cutoff)
    rows[0] = replace(rows[0], value=None, status="BANKRUPT", reason="not yet published")
    after = score_candidate("late", rows, fold=fold, information_as_of=fold.data_cutoff)
    assert after == before
    assert before.segments[0].unavailable_days == 1
    assert before.segments[0].valid_days == 90
    assert before.segments[0].bankrupt_days == 0
    assert before.segments[0].observation_dispositions == (
        (fold.is_start, "UNAVAILABLE", "not published at information frontier"),
    )


def test_completed_last_day_cutoff_equality_is_explicit(fold):
    rows = account(fold.is_start)
    assert rows[-1].available_at == fold.data_cutoff
    equal = score_candidate("x", rows, fold=fold, information_as_of=fold.data_cutoff)
    earlier = score_candidate("x", rows, fold=fold, information_as_of=fold.data_cutoff - timedelta(microseconds=1))
    assert equal.segments[-1].valid_days == 92
    assert earlier.segments[-1].valid_days == 91 and earlier.segments[-1].unavailable_days == 1
    with pytest.raises(ValueError, match="OOS"):
        select_floor_mean({"x": rows}, fold=fold, information_as_of=fold.data_cutoff + timedelta(microseconds=1))


def test_ids_exact_ties_order_and_unsupported_candidates(fold):
    rows = account(fold.is_start)
    first = select_floor_mean({"z": rows, "missing": None, "a": rows}, fold=fold, information_as_of=fold.data_cutoff)
    second = select_floor_mean({"a": reversed(rows), "missing": (), "z": iter(rows)},
                              fold=fold, information_as_of=fold.data_cutoff)
    assert first == second
    assert tuple(row.candidate_id for row in first.candidates) == ("a", "missing", "z")
    assert first.ranking == ("a", "z") and first.selected_candidate_id == "a"
    assert first.candidates[1].score is None
    assert all(row.missing_days == row.segment.calendar_days for row in first.candidates[1].segments)
    better = tuple(replace(row, value=row.value + 1e-10) for row in rows)
    distinct = select_floor_mean({"a": rows, "z": better}, fold=fold, information_as_of=fold.data_cutoff)
    assert distinct.selected_candidate_id == "z"  # No implicit approximate tie bucket.


@pytest.mark.parametrize("pool, reason", [({}, "EMPTY_POOL"), ({"missing": None}, "NO_SUPPORTED_CANDIDATE")])
def test_no_supported_candidate_is_explicit_no_selection(fold, pool, reason):
    result = select_floor_mean(pool, fold=fold, information_as_of=fold.data_cutoff)
    assert result.status == "NO_SELECTION" and result.reason == reason
    assert result.selected_candidate_id is None and result.ranking == ()


def test_duplicate_in_scope_days_are_rejected_not_last_writer_wins(fold):
    rows = account(fold.is_start)
    with pytest.raises(ValueError, match="duplicate"):
        score_candidate("duplicate", (*rows, rows[0]), fold=fold, information_as_of=fold.data_cutoff)


@pytest.mark.parametrize("value", [None, float("nan"), float("inf"), -float("inf"), True, "0.1"])
def test_valid_observations_cannot_hide_nonfinite_or_null_values(value):
    with pytest.raises(ValueError, match="finite real"):
        DailyAccountReturn(utc(2021, 1, 1), value)


@pytest.mark.parametrize("change", [
    {"status": "INVALID", "value": 0.0, "reason": "bad"},
    {"status": "UNAVAILABLE", "value": None},
    {"status": "BANKRUPT", "value": None, "reason": " "},
    {"status": "guessed"}, {"reason": "VALID cannot carry a failure reason"},
    {"available_at": utc(2021, 1, 1)},
])
def test_explicit_status_and_availability_contracts(change):
    with pytest.raises(ValueError):
        replace(DailyAccountReturn(utc(2021, 1, 1), 0.1), **change)


@pytest.mark.parametrize("bad", [
    datetime(2021, 1, 1), datetime(2021, 1, 1, tzinfo=timezone(timedelta(hours=1))),
    "2021-01-01",
])
def test_utc_datetime_is_required(fold, bad):
    with pytest.raises(ValueError, match="UTC"):
        DailyAccountReturn(bad, 0.1)
    with pytest.raises(ValueError, match="UTC"):
        select_floor_mean({}, fold=fold, information_as_of=bad)


def test_day_labels_not_intraday_marks_and_records_are_immutable(fold):
    with pytest.raises(ValueError, match="midnight"):
        DailyAccountReturn(utc(2021, 1, 1) + timedelta(hours=1), 0.1)
    result = select_floor_mean({"x": account(fold.is_start)}, fold=fold, information_as_of=fold.data_cutoff)
    for obj, field, value in (
        (fold, "is_start", DATA_START), (result, "selected_candidate_id", "changed"),
        (result.candidates[0], "score", 42), (result.candidates[0].segments[0], "valid_days", 1),
    ):
        with pytest.raises(FrozenInstanceError):
            setattr(obj, field, value)


@pytest.mark.parametrize("bad_id", ["", " ", None, 1])
def test_ids_cannot_depend_on_pool_position(fold, bad_id):
    with pytest.raises(ValueError, match="candidate ID"):
        select_floor_mean({bad_id: None}, fold=fold, information_as_of=fold.data_cutoff)


def test_observation_adapter_requires_typed_rows(fold):
    with pytest.raises(TypeError, match="DailyAccountReturn"):
        score_candidate("x", [{"day": fold.is_start, "value": 0.1}],
                        fold=fold, information_as_of=fold.data_cutoff)
