"""Account-attribution floor/mean selection, with no execution or market I/O.

This research profile reuses Mode 5's ddof=1 moments (explicit Python backend,
no JIT) and weighted mean reducer. Its scalar formula is exactly
``environment_floor_mean_v1`` with mean coefficient .25 and no activity penalty.
The full Mode 5 selector requires unrelated panel/access/gate witnesses; this
adapter does not fabricate them or relabel daily Sharpe as economic utility.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
import math
from typing import cast

from quantbt.mode5.statistics.moments import MomentEstimate, moments
from quantbt.mode5.statistics.tails import lower_tail

from .contracts import (
    AttributionSegment, DAILY_SHARPE_POLICY, DailyAccountReturn, FORMULA_VERSION,
    MEAN_COEFFICIENT, MIN_DAILY_OBSERVATIONS, PROFILE_ID, QuarterlyFold,
    attribution_segments, require_candidate_id, require_utc,
)


@dataclass(frozen=True)
class SegmentScore:
    """Support and nullable annual daily-account Sharpe for one fixed segment.

    Missing/UNAVAILABLE/late days never become zeros or change day weights.
    At least 60 finite available one-day observations are needed. Available
    INVALID/BANKRUPT rows block the segment even if 60 other days are valid.
    ``estimate`` retains the shared moment reducer's period Sharpe/variance.
    ``observation_dispositions`` retains available null-row day/status/reason;
    late rows disclose only an as-of-unavailable disposition, not future status.
    """

    segment: AttributionSegment
    observed_days: int
    valid_days: int
    missing_days: int
    unavailable_days: int
    invalid_days: int
    bankrupt_days: int
    zero_return_days: int
    sharpe_annual: float | None
    status: str
    reasons: tuple[str, ...]
    observation_dispositions: tuple[tuple[datetime, str, str], ...]
    estimate: MomentEstimate | None = None


@dataclass(frozen=True)
class CandidateScore:
    """All four rows; incomplete aggregates are null, not partial-panel scores.

    The weighted mean and objective are composites of segment Sharpes, not
    whole-account Sharpe or substitutes for the parent's canonical raw metrics.
    """

    candidate_id: str
    segments: tuple[SegmentScore, ...]
    floor_sharpe: float | None
    weighted_mean_sharpe: float | None
    score: float | None
    status: str
    reasons: tuple[str, ...]

    @property
    def eligible(self) -> bool:
        return self.status == "VALID"


@dataclass(frozen=True)
class QuarterlySelection:
    """A bounded research decision, not a model fit or executable policy.

    Candidates are retained in lexical ID order; ``ranking`` contains only
    supported IDs, descending score then ascending lexical ID on exact ties.
    There is no implicit legacy fallback or all-segments-positive gate.
    """

    fold: QuarterlyFold
    information_as_of: datetime
    candidates: tuple[CandidateScore, ...]
    ranking: tuple[str, ...]
    selected_candidate_id: str | None
    status: str
    reason: str | None
    profile_id: str = PROFILE_ID
    formula_version: str = FORMULA_VERSION
    mean_coefficient: float = MEAN_COEFFICIENT
    tie_policy: str = "score_desc_candidate_id_lexical_asc_exact_v1"


def _cutoff(fold: QuarterlyFold, information_as_of: datetime) -> datetime:
    if not isinstance(fold, QuarterlyFold):
        raise TypeError("a typed QuarterlyFold is required")
    cutoff = require_utc(information_as_of)
    if cutoff > fold.data_cutoff:
        raise ValueError("selection information frontier cannot extend into OOS")
    return cutoff


def _segment_score(segment: AttributionSegment, observations: tuple[DailyAccountReturn, ...],
                   cutoff: datetime) -> SegmentScore:
    available_rows, dispositions = [], []
    for row in observations:
        assert row.available_at is not None
        if row.available_at > cutoff:
            dispositions.append((row.day, "UNAVAILABLE", "not published at information frontier"))
        else:
            available_rows.append(row)
            if row.status != "VALID":
                assert row.reason is not None
                dispositions.append((row.day, row.status, row.reason))
    available = tuple(available_rows)
    valid = tuple(cast(float, row.value) for row in available if row.status == "VALID")
    invalid = tuple(row for row in available if row.status == "INVALID")
    bankrupt = tuple(row for row in available if row.status == "BANKRUPT")
    unavailable = len(observations) - len(available) + sum(row.status == "UNAVAILABLE" for row in available)
    estimate, sharpe = None, None
    if bankrupt or invalid:
        status = "BANKRUPT" if bankrupt else "INVALID"
        reasons = tuple(f"{row.day.date().isoformat()}: {row.status}: {row.reason}"
                        for row in available if row.status in ("BANKRUPT", "INVALID"))
    elif len(valid) < MIN_DAILY_OBSERVATIONS:
        status, reasons = "INSUFFICIENT", ("fewer than 60 valid available daily observations",)
    else:
        estimate = moments(valid, policy=DAILY_SHARPE_POLICY, backend="python")
        status = estimate.status
        reasons = () if estimate.reason is None else (estimate.reason,)
        if status == "VALID":
            assert estimate.sharpe_period is not None
            sharpe = estimate.sharpe_period * math.sqrt(DAILY_SHARPE_POLICY.annual_periods)
            if not math.isfinite(sharpe):
                status, reasons, sharpe = "INVALID", ("annual daily Sharpe overflow",), None
    return SegmentScore(
        segment, len(observations), len(valid), segment.calendar_days - len(observations),
        unavailable, len(invalid), len(bankrupt), sum(value == 0 for value in valid),
        sharpe, status, reasons, tuple(dispositions), estimate,
    )


def score_candidate(candidate_id: str, observations: Iterable[DailyAccountReturn] | None,
                    *, fold: QuarterlyFold, information_as_of: datetime) -> CandidateScore:
    """Reduce a single IS account's daily returns into the frozen profile.

    Warmup and OOS rows are ignored before deduplication/metric reduction.
    In-IS rows must have distinct UTC day labels; input order is immaterial.
    Late observations are counted as unavailable, regardless of their value or
    status. Missing/UNAVAILABLE days may leave a segment supported if >=60
    qualified days remain; calendar weights are never support-count weights.
    No failed observation is silently removed to improve a score. ``None``
    means no retained account returns, not a zero-return account.

    The caller supplies already qualified candidate/account records, with all
    feasibility/risk/engine gates applied by their existing owners. This pure
    reducer cannot certify those gates, equity continuity or indicator causality.
    """
    require_candidate_id(candidate_id)
    cutoff = _cutoff(fold, information_as_of)
    by_day: dict[datetime, DailyAccountReturn] = {}
    for row in (() if observations is None else observations):
        if not isinstance(row, DailyAccountReturn):
            raise TypeError("typed DailyAccountReturn observations required")
        if not fold.is_start <= row.day < fold.is_end:
            continue
        if row.day in by_day:
            raise ValueError("duplicate IS daily account observation")
        by_day[row.day] = row
    buckets: list[list[DailyAccountReturn]] = [[], [], [], []]
    for day, row in sorted(by_day.items()):
        index = min((day - fold.is_start).days // 91, 3)
        buckets[index].append(row)
    rows = tuple(_segment_score(segment, tuple(bucket), cutoff)
                 for segment, bucket in zip(attribution_segments(fold), buckets, strict=True))
    unsupported = tuple(row for row in rows if row.status != "VALID")
    if unsupported:
        reasons = tuple(f"{row.segment.segment_id}: {row.status}: {reason}"
                        for row in unsupported for reason in row.reasons)
        return CandidateScore(candidate_id, rows, None, None, None, "UNSUPPORTED", reasons)
    values = tuple(cast(float, row.sharpe_annual) for row in rows)
    mean = lower_tail(values, 1.0, weights=tuple(row.segment.calendar_days for row in rows),
                      unit="annual_daily_account_sharpe")
    floor = min(values)
    if mean.status != "VALID":
        assert mean.reason is not None
        return CandidateScore(candidate_id, rows, floor, None, None, "INVALID", (mean.reason,))
    assert mean.value is not None
    score = floor + MEAN_COEFFICIENT * mean.value
    if not math.isfinite(score):
        return CandidateScore(candidate_id, rows, floor, mean.value, None,
                              "INVALID", ("floor/mean objective overflow",))
    return CandidateScore(candidate_id, rows, floor, mean.value, score, "VALID", ())


def select_floor_mean(candidates: Mapping[str, Iterable[DailyAccountReturn] | None], *,
                      fold: QuarterlyFold, information_as_of: datetime) -> QuarterlySelection:
    """Select from ``{stable_candidate_id: one_IS_account_daily_returns}``.

    Uses the same account observations for every segment, without simulation,
    resets, optimizer feedback, raw-meta-metric replacement or mutable caches.
    Every supplied candidate stays in the result, including unsupported rows.
    No supported candidate (including an empty pool) yields explicit
    ``NO_SELECTION`` with a null winner. IDs, not mapping insertion order or
    a numerical tie tolerance, resolve exact score ties deterministically.
    ``information_as_of`` must be UTC and no later than the fold's IS end.
    """
    cutoff = _cutoff(fold, information_as_of)
    for candidate_id in candidates:
        require_candidate_id(candidate_id)
    rows = tuple(score_candidate(candidate_id, candidates[candidate_id], fold=fold,
                                 information_as_of=cutoff) for candidate_id in sorted(candidates))
    ranked = sorted((row for row in rows if row.eligible),
                    key=lambda row: (-cast(float, row.score), row.candidate_id))
    ranking = tuple(row.candidate_id for row in ranked)
    return QuarterlySelection(
        fold, cutoff, rows, ranking, ranking[0] if ranking else None,
        "SELECTED" if ranking else "NO_SELECTION",
        None if ranking else "NO_SUPPORTED_CANDIDATE" if rows else "EMPTY_POOL",
    )
