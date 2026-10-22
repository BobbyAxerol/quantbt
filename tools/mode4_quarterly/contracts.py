"""Pure calendar/input contracts for the opt-in M5-11.6.1 research sidecar.

All intervals are half-open UTC intervals. Preload is permission to initialize
indicators, not scored account history or a guarantee of indicator readiness.
The parent owns execution, account qualification, readiness and decision seals;
these objects neither run accounts nor activate a public Mode 4 policy.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import math
from numbers import Real
from typing import Literal

from quantbt.mode5.diagnostics.identity import digest
from quantbt.mode5.statistics.contracts import StatisticsPolicy


DAY = timedelta(days=1)
DATA_START = datetime(2020, 1, 1, tzinfo=timezone.utc)
OOS_START = datetime(2022, 1, 1, tzinfo=timezone.utc)
OOS_END = datetime(2026, 10, 1, tzinfo=timezone.utc)
SEGMENT_DAYS = (91, 91, 91, 92)
PROFILE_ID = "mode4_is_environment_floor_mean_sharpe_v1"
FORMULA_VERSION = "environment_floor_mean_v1"
MIN_DAILY_OBSERVATIONS = 60
MEAN_COEFFICIENT = 0.25
DAILY_SHARPE_POLICY = StatisticsPolicy(
    annual_periods=365.0, variance_ddof=1, risk_free_per_period=0.0,
)
ObservationStatus = Literal["VALID", "UNAVAILABLE", "INVALID", "BANKRUPT"]


def require_utc(value: datetime, *, midnight: bool = False) -> datetime:
    """Reject naive/non-UTC clocks and optionally require a UTC day label."""
    if not isinstance(value, datetime) or value.utcoffset() != timedelta(0):
        raise ValueError("an aware UTC datetime is required")
    if midnight and (value.hour or value.minute or value.second or value.microsecond
                     or getattr(value, "nanosecond", 0)):
        raise ValueError("UTC midnight day boundary required")
    return value.astimezone(timezone.utc)


def require_candidate_id(candidate_id: str) -> None:
    """Candidate IDs are caller-owned stable identities, never positional IDs."""
    if not isinstance(candidate_id, str) or not candidate_id.strip():
        raise ValueError("nonempty stable string candidate ID required")


@dataclass(frozen=True)
class QuarterlyFold:
    """One registered quarter and its rolling365D IS and permitted preload.

    ``data_cutoff`` is the input frontier, not a claim about computation,
    seal, readiness or first effective action time. ``fold_id`` names only
    the quarter; ``identity`` also binds all calendar/preload boundaries.
    """

    fold_id: str
    preload_start: datetime
    is_start: datetime
    is_end: datetime
    oos_start: datetime
    oos_end: datetime

    def __post_init__(self) -> None:
        for name in ("preload_start", "is_start", "is_end", "oos_start", "oos_end"):
            object.__setattr__(self, name, require_utc(getattr(self, name), midnight=True))
        start = self.oos_start
        if not OOS_START <= start < OOS_END or start.day != 1 or start.month not in (1, 4, 7, 10):
            raise ValueError("a registered 2022Q1..2026Q3 quarter start is required")
        quarter = (start.month - 1) // 3 + 1
        end = datetime(start.year + (quarter == 4), 1 if quarter == 4 else start.month + 3,
                       1, tzinfo=timezone.utc)
        if self.fold_id != f"{start.year}Q{quarter}" or self.oos_end != end:
            raise ValueError("quarter ID and complete quarter end must match")
        if self.is_end != start or self.is_start != start - 365 * DAY:
            raise ValueError("IS must be exactly rolling365D ending at OOS start")
        if not DATA_START <= self.preload_start <= self.is_start:
            raise ValueError("preload must lie in the permitted prefix before scored IS")

    @property
    def data_cutoff(self) -> datetime:
        return self.is_end

    @property
    def identity(self) -> str:
        return digest(dict(
            schema="mode4.quarterly_calendar.v1", fold_id=self.fold_id,
            preload_start=self.preload_start.isoformat(), is_start=self.is_start.isoformat(),
            is_end=self.is_end.isoformat(), oos_start=self.oos_start.isoformat(),
            oos_end=self.oos_end.isoformat(),
        ))


def quarterly_calendar(*, preload_start: datetime = DATA_START,
                       data_end: datetime = OOS_END) -> tuple[QuarterlyFold, ...]:
    """Return exactly 19 complete quarters, 2022Q1 through 2026Q3 inclusive.

    ``data_end`` is exclusive and must cover the full registration. A later
    snapshot never adds partial October or another fold. The default preload
    retains the entire permitted prefix; a different approved preload is
    explicit and changes fold identity, not the scored IS start.
    """
    preload_start = require_utc(preload_start, midnight=True)
    data_end = require_utc(data_end)
    if data_end < OOS_END:
        raise ValueError("snapshot does not cover all 19 complete quarters")
    folds = []
    for offset in range(19):
        year, quarter_index = 2022 + offset // 4, offset % 4
        start = datetime(year, quarter_index * 3 + 1, 1, tzinfo=timezone.utc)
        end = datetime(year + (quarter_index == 3),
                       1 if quarter_index == 3 else quarter_index * 3 + 4, 1,
                       tzinfo=timezone.utc)
        folds.append(QuarterlyFold(
            f"{year}Q{quarter_index + 1}", preload_start, start - 365 * DAY,
            start, start, end,
        ))
    return tuple(folds)


@dataclass(frozen=True)
class AttributionSegment:
    """An immutable view of one IS account, never an independent simulation."""

    segment_id: str
    start: datetime
    end: datetime

    def __post_init__(self) -> None:
        require_candidate_id(self.segment_id)
        object.__setattr__(self, "start", require_utc(self.start, midnight=True))
        object.__setattr__(self, "end", require_utc(self.end, midnight=True))
        if self.end <= self.start:
            raise ValueError("positive segment duration required")

    @property
    def calendar_days(self) -> int:
        return (self.end - self.start).days

    @property
    def weight(self) -> float:
        return self.calendar_days / 365.0


def attribution_segments(fold: QuarterlyFold) -> tuple[AttributionSegment, ...]:
    """Partition one 365D IS into oldest-first 91/91/91/92-day views.

    A daily return belongs to the segment containing its day label. Its
    scope-entry valuation/cost remains in that return; no boundary mark,
    position reset, synthetic day or new account return is manufactured.
    """
    if not isinstance(fold, QuarterlyFold):
        raise TypeError("a typed QuarterlyFold is required")
    start, segments = fold.is_start, []
    for index, days in enumerate(SEGMENT_DAYS, start=1):
        end = start + days * DAY
        segments.append(AttributionSegment(f"{fold.fold_id}/is-{index}", start, end))
        start = end
    return tuple(segments)


@dataclass(frozen=True)
class DailyAccountReturn:
    """One producer-qualified net simple account return for ``[day, day+1D)``.

    ``day`` is a UTC-midnight label, not an equity mark or arbitrary bar time.
    The producer must retain the valuation before the first scored return,
    include fees/flat days, and supply actual one-day returns, not returns
    across missing days. No equity, cashflow or liquidation is inferred here.
    Omitted days are missing, never zero. Non-VALID rows require null + reason.
    ``available_at`` defaults to the next midnight (complete day); delayed
    publication is explicit. The cutoff admits equality under this completed-
    day convention; the parent owns any stricter publication event ordering.
    """

    day: datetime
    value: float | None
    status: ObservationStatus = "VALID"
    reason: str | None = None
    available_at: datetime | None = None

    def __post_init__(self) -> None:
        day = require_utc(self.day, midnight=True)
        available = day + DAY if self.available_at is None else require_utc(self.available_at)
        if available < day + DAY:
            raise ValueError("a complete daily return cannot be available before day end")
        if self.status not in ("VALID", "UNAVAILABLE", "INVALID", "BANKRUPT"):
            raise ValueError("unknown daily account-return status")
        if self.status == "VALID":
            if (isinstance(self.value, bool) or not isinstance(self.value, Real)
                    or not math.isfinite(self.value) or self.reason is not None):
                raise ValueError("VALID daily return requires a finite real value and no reason")
            object.__setattr__(self, "value", float(self.value))
        elif self.value is not None or not isinstance(self.reason, str) or not self.reason.strip():
            raise ValueError("non-VALID daily return requires null value and nonempty reason")
        object.__setattr__(self, "day", day)
        object.__setattr__(self, "available_at", available)
