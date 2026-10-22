"""Explicit full-development calendars and cold missing-work dispositions."""

from dataclasses import asdict, dataclass

import numpy as np

from .identity import digest

HOUR_NS = 3_600_000_000_000
DAY_NS = 24 * HOUR_NS
DISPOSITIONS = frozenset({"EXACT_REUSE", "REANALYZE_ONLY",
    "REPLAY_REQUIRED_FOR_REQUESTED_METRIC", "INCOMPATIBLE_ECONOMICS_OR_ALPHA"})


@dataclass(frozen=True)
class DevelopmentCalendar:
    requested_start_ns: int
    provider_start_ns: int
    provider_last_ns: int
    scored_start_ns: int
    scored_stop_ns: int
    readiness_bars: int
    missing_hours: tuple[int, ...]
    partial_days: tuple[tuple[int, int], ...]
    clock: str = "UTC_BAR_OPEN_HOURLY"

    @classmethod
    def from_times(cls, times_ns, *, requested_start_ns, readiness_bars):
        raw = np.asarray(times_ns)
        if (raw.ndim != 1 or not len(raw) or raw.dtype.kind not in "iu"
                or np.any(raw > np.iinfo(np.int64).max)
                or type(requested_start_ns) is not int or requested_start_ns % DAY_NS
                or type(readiness_bars) is not int or readiness_bars < 0):
            raise ValueError("integer hourly calendar, UTC day start and explicit readiness required")
        times = raw.astype(np.int64)
        if (np.any(times < 0) or np.any(times % HOUR_NS)
                or np.any(np.diff(times) <= 0)):
            raise ValueError("unique increasing aligned hourly timestamps required")
        first, last = int(times[0]), int(times[-1])
        days, counts = np.unique(times // DAY_NS, return_counts=True)
        partial = tuple((int(day * DAY_NS), int(count))
            for day, count in zip(days, counts, strict=True) if count != 24)
        complete = days[counts == 24]
        if not len(complete) or readiness_bars >= len(times):
            raise ValueError("no complete calendar with requested readiness")
        stop = int((complete[-1] + 1) * DAY_NS)
        ready = int(times[readiness_bars])
        start = max(requested_start_ns, first, ready)
        start = ((start + DAY_NS - 1) // DAY_NS) * DAY_NS
        if start >= stop:
            raise ValueError("no complete scored day after common readiness")
        actual = times[(times >= start) & (times < stop)]
        expected = np.arange(start, stop, HOUR_NS, dtype=np.int64)
        missing = tuple(int(t) for t in np.setdiff1d(expected, actual))
        return cls(requested_start_ns, first, last, start, stop, readiness_bars,
            missing, partial)

    @property
    def identity(self):
        return digest(asdict(self))

    @property
    def scored_bars(self):
        return (self.scored_stop_ns - self.scored_start_ns) // HOUR_NS

    def to_metadata(self):
        complete = not self.missing_hours
        prefix = max(0, self.scored_start_ns - self.requested_start_ns)
        return asdict(self) | dict(identity=self.identity, scored_bars=self.scored_bars,
            scored_days=self.scored_bars // 24, unsupported_prefix_hours=prefix // HOUR_NS,
            has_pre_requested_history=self.provider_start_ns < self.requested_start_ns,
            complete_scored_calendar=complete,
            requested_start_met=prefix == 0,
            status=("MISSING_SCORED_HOURS" if not complete else
                "READINESS_PREFIX_GAP" if prefix else "COMPLETE_REQUESTED_SCOPE"))

    def require_complete(self):
        if self.missing_hours:
            raise ValueError("missing scored hours; filling or splicing is not authorized")


@dataclass(frozen=True)
class WorkQuestion:
    question_id: str
    question: str
    source_identity: str | None
    requested_identity: str
    disposition: str
    missing_output: str
    new_financial_calls: int
    reason: str

    def __post_init__(self):
        if (not all(isinstance(v, str) and v.strip() for v in
                (self.question_id, self.question, self.requested_identity,
                 self.missing_output, self.reason)) or self.disposition not in DISPOSITIONS
                or type(self.new_financial_calls) is not int or self.new_financial_calls < 0):
            raise ValueError("explicit question, identities, disposition and work bill required")
        if self.disposition in {"EXACT_REUSE", "REANALYZE_ONLY"}:
            if self.source_identity != self.requested_identity or self.new_financial_calls:
                raise ValueError("reuse needs matching identity and zero financial calls")


def work_manifest(questions):
    rows = tuple(questions)
    if (not rows or any(not isinstance(row, WorkQuestion) for row in rows)
            or len({row.question_id for row in rows}) != len(rows)):
        raise ValueError("unique typed work questions required")
    data = [asdict(row) for row in rows]
    return dict(schema="mode5.full_development_work.v1", questions=data,
        new_financial_calls=sum(row.new_financial_calls for row in rows),
        disposition_counts={key: sum(row.disposition == key for row in rows)
            for key in sorted(DISPOSITIONS)}, identity=digest(data))
