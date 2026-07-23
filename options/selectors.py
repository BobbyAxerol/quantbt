"""
No-lookahead option selectors.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Union

import numpy as np

from .schema import OptionKind
from .tape import PreparedOptionTape, YEAR_NS


@dataclass(frozen=True)
class OptionSelectionFilters:
    option_kind: Optional[Union[OptionKind, str]] = None
    min_bid_size: float = 0.0
    min_ask_size: float = 0.0
    max_spread_bps: Optional[float] = None
    min_open_interest: float = 0.0
    min_volume: float = 0.0
    min_dte_days: Optional[float] = None
    max_dte_days: Optional[float] = None
    min_moneyness: Optional[float] = None
    max_moneyness: Optional[float] = None
    require_mark_iv: bool = False
    require_delta: bool = False


@dataclass(frozen=True)
class OptionSelection:
    row_index: int
    snapshot_index: int
    snapshot_timestamp_ns: int
    decision_timestamp_ns: int
    instrument_id: str
    instrument_code: int
    option_kind: OptionKind
    expiry_ns: int
    strike: float
    dte_years: float
    moneyness: float
    bid_price: float
    ask_price: float
    mark_price: float
    mid_price: float
    mark_iv: float
    delta: float
    score: float


def select_atm_option(
    tape: PreparedOptionTape,
    decision_timestamp_ns: int,
    *,
    filters: Optional[OptionSelectionFilters] = None,
    max_quote_age_ns: Optional[int] = None,
) -> OptionSelection:
    """Select the listed option closest to ATM at the observable snapshot."""
    return _select_min_score(
        tape,
        decision_timestamp_ns,
        filters=filters,
        max_quote_age_ns=max_quote_age_ns,
        score_fn=lambda rows: np.abs(tape.strike[rows] / tape.forward_price[rows] - 1.0),
    )


def select_target_delta_option(
    tape: PreparedOptionTape,
    decision_timestamp_ns: int,
    *,
    target_delta: float,
    filters: Optional[OptionSelectionFilters] = None,
    max_quote_age_ns: Optional[int] = None,
) -> OptionSelection:
    """Select the option with observable delta closest to `target_delta`."""
    base_filters = _merge_require_delta(filters)
    target = float(target_delta)
    if not np.isfinite(target):
        raise ValueError("target_delta must be finite")
    return _select_min_score(
        tape,
        decision_timestamp_ns,
        filters=base_filters,
        max_quote_age_ns=max_quote_age_ns,
        score_fn=lambda rows: np.abs(tape.delta[rows] - target),
    )


def select_target_dte_option(
    tape: PreparedOptionTape,
    decision_timestamp_ns: int,
    *,
    target_dte_days: float,
    filters: Optional[OptionSelectionFilters] = None,
    max_quote_age_ns: Optional[int] = None,
) -> OptionSelection:
    """Select the option with expiry closest to target DTE at the snapshot."""
    target_years = _positive_days(target_dte_days, "target_dte_days") / 365.0
    return _select_min_score(
        tape,
        decision_timestamp_ns,
        filters=filters,
        max_quote_age_ns=max_quote_age_ns,
        score_fn=lambda rows: np.abs(_dte_years(tape, rows, decision_timestamp_ns) - target_years),
    )


def select_target_moneyness_option(
    tape: PreparedOptionTape,
    decision_timestamp_ns: int,
    *,
    target_moneyness: float,
    filters: Optional[OptionSelectionFilters] = None,
    max_quote_age_ns: Optional[int] = None,
) -> OptionSelection:
    """Select the option with strike/forward closest to target moneyness."""
    target = float(target_moneyness)
    if not np.isfinite(target) or target <= 0.0:
        raise ValueError("target_moneyness must be finite and > 0")
    return _select_min_score(
        tape,
        decision_timestamp_ns,
        filters=filters,
        max_quote_age_ns=max_quote_age_ns,
        score_fn=lambda rows: np.abs(tape.strike[rows] / tape.forward_price[rows] - target),
    )


def available_option_rows(
    tape: PreparedOptionTape,
    decision_timestamp_ns: int,
    *,
    filters: Optional[OptionSelectionFilters] = None,
    max_quote_age_ns: Optional[int] = None,
) -> np.ndarray:
    """Return global row indexes listed and tradable at the observable snapshot."""
    snapshot_idx = tape.snapshot_index_at_or_before(decision_timestamp_ns, max_quote_age_ns=max_quote_age_ns)
    rows = np.arange(tape.row_ptr[snapshot_idx], tape.row_ptr[snapshot_idx + 1], dtype=np.int64)
    mask = _filter_mask(tape, rows, int(decision_timestamp_ns), filters or OptionSelectionFilters())
    return rows[mask]


def _select_min_score(
    tape: PreparedOptionTape,
    decision_timestamp_ns: int,
    *,
    filters: Optional[OptionSelectionFilters],
    max_quote_age_ns: Optional[int],
    score_fn,
) -> OptionSelection:
    snapshot_idx = tape.snapshot_index_at_or_before(decision_timestamp_ns, max_quote_age_ns=max_quote_age_ns)
    rows = np.arange(tape.row_ptr[snapshot_idx], tape.row_ptr[snapshot_idx + 1], dtype=np.int64)
    filtered = _filter_mask(tape, rows, int(decision_timestamp_ns), filters or OptionSelectionFilters())
    candidates = rows[filtered]
    if len(candidates) == 0:
        raise ValueError("no option candidates pass filters at observable snapshot")
    scores = np.asarray(score_fn(candidates), dtype=np.float64)
    valid_scores = np.isfinite(scores)
    if not bool(valid_scores.any()):
        raise ValueError("no option candidates have finite selector score")
    candidates = candidates[valid_scores]
    scores = scores[valid_scores]
    local_idx = int(np.argmin(scores))
    return _build_selection(tape, int(candidates[local_idx]), snapshot_idx, int(decision_timestamp_ns), float(scores[local_idx]))


def _filter_mask(
    tape: PreparedOptionTape,
    rows: np.ndarray,
    decision_timestamp_ns: int,
    filters: OptionSelectionFilters,
) -> np.ndarray:
    if len(rows) == 0:
        return np.zeros(0, dtype=bool)
    mask = np.ones(len(rows), dtype=bool)
    if filters.option_kind is not None:
        kind = _coerce_kind(filters.option_kind)
        mask &= tape.option_kind_code[rows] == (0 if kind is OptionKind.CALL else 1)
    mask &= tape.expiry_ns[rows] > int(decision_timestamp_ns)
    mask &= tape.bid_size[rows] >= float(filters.min_bid_size)
    mask &= tape.ask_size[rows] >= float(filters.min_ask_size)
    mask &= tape.open_interest[rows] >= float(filters.min_open_interest)
    mask &= tape.volume[rows] >= float(filters.min_volume)
    if filters.max_spread_bps is not None:
        mid = 0.5 * (tape.bid_price[rows] + tape.ask_price[rows])
        spread_bps = np.divide(
            tape.ask_price[rows] - tape.bid_price[rows],
            mid,
            out=np.full(len(rows), np.inf, dtype=np.float64),
            where=mid > 0.0,
        ) * 10_000.0
        mask &= spread_bps <= float(filters.max_spread_bps)
    dte_days = _dte_years(tape, rows, decision_timestamp_ns) * 365.0
    if filters.min_dte_days is not None:
        mask &= dte_days >= float(filters.min_dte_days)
    if filters.max_dte_days is not None:
        mask &= dte_days <= float(filters.max_dte_days)
    moneyness = tape.strike[rows] / tape.forward_price[rows]
    if filters.min_moneyness is not None:
        mask &= moneyness >= float(filters.min_moneyness)
    if filters.max_moneyness is not None:
        mask &= moneyness <= float(filters.max_moneyness)
    if filters.require_mark_iv:
        mask &= np.isfinite(tape.mark_iv[rows])
    if filters.require_delta:
        mask &= np.isfinite(tape.delta[rows])
    return mask


def _build_selection(
    tape: PreparedOptionTape,
    row_index: int,
    snapshot_index: int,
    decision_timestamp_ns: int,
    score: float,
) -> OptionSelection:
    mid = 0.5 * (float(tape.bid_price[row_index]) + float(tape.ask_price[row_index]))
    kind = OptionKind.CALL if int(tape.option_kind_code[row_index]) == 0 else OptionKind.PUT
    return OptionSelection(
        row_index=row_index,
        snapshot_index=snapshot_index,
        snapshot_timestamp_ns=int(tape.timestamp_ns[snapshot_index]),
        decision_timestamp_ns=int(decision_timestamp_ns),
        instrument_id=tape.instrument_id[row_index],
        instrument_code=int(tape.instrument_code[row_index]),
        option_kind=kind,
        expiry_ns=int(tape.expiry_ns[row_index]),
        strike=float(tape.strike[row_index]),
        dte_years=float((int(tape.expiry_ns[row_index]) - int(decision_timestamp_ns)) / YEAR_NS),
        moneyness=float(tape.strike[row_index] / tape.forward_price[row_index]),
        bid_price=float(tape.bid_price[row_index]),
        ask_price=float(tape.ask_price[row_index]),
        mark_price=float(tape.mark_price[row_index]),
        mid_price=mid,
        mark_iv=float(tape.mark_iv[row_index]),
        delta=float(tape.delta[row_index]),
        score=float(score),
    )


def _dte_years(tape: PreparedOptionTape, rows: np.ndarray, decision_timestamp_ns: int) -> np.ndarray:
    return (tape.expiry_ns[rows].astype(np.float64) - float(decision_timestamp_ns)) / float(YEAR_NS)


def _merge_require_delta(filters: Optional[OptionSelectionFilters]) -> OptionSelectionFilters:
    if filters is None:
        return OptionSelectionFilters(require_delta=True)
    return OptionSelectionFilters(
        option_kind=filters.option_kind,
        min_bid_size=filters.min_bid_size,
        min_ask_size=filters.min_ask_size,
        max_spread_bps=filters.max_spread_bps,
        min_open_interest=filters.min_open_interest,
        min_volume=filters.min_volume,
        min_dte_days=filters.min_dte_days,
        max_dte_days=filters.max_dte_days,
        min_moneyness=filters.min_moneyness,
        max_moneyness=filters.max_moneyness,
        require_mark_iv=filters.require_mark_iv,
        require_delta=True,
    )


def _coerce_kind(option_kind: Union[OptionKind, str]) -> OptionKind:
    if isinstance(option_kind, OptionKind):
        return option_kind
    try:
        return OptionKind(str(option_kind).lower())
    except ValueError as exc:
        raise ValueError("option_kind must be call or put") from exc


def _positive_days(value: float, name: str) -> float:
    out = float(value)
    if not np.isfinite(out) or out <= 0.0:
        raise ValueError(f"{name} must be finite and > 0")
    return out
