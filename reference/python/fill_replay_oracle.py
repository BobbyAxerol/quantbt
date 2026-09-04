"""Pure-Python bounded fill-replay oracle built on linear_accounting_oracle."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Mapping, Sequence

from .linear_accounting_oracle import (
    FillTransition,
    FundingTransition,
    LinearAccountSpec,
    LinearAccountState,
    MarginSnapshot,
    apply_fill,
    apply_funding,
    initial_state,
    mark_to_market,
)


@dataclass(frozen=True, slots=True)
class ReplayFill:
    bar_index: int
    sequence: int
    signed_qty: float
    price: float
    fee: float


@dataclass(frozen=True, slots=True)
class ReplayFunding:
    bar_index: int
    sequence: int
    rate: float


@dataclass(frozen=True, slots=True)
class ReplaySnapshot:
    bar_index: int
    state: LinearAccountState
    margin: MarginSnapshot


@dataclass(frozen=True, slots=True)
class FillReplayOracleResult:
    state: LinearAccountState
    fills: tuple[FillTransition, ...]
    funding: tuple[FundingTransition, ...]
    snapshots: tuple[ReplaySnapshot, ...]


def run_fill_replay(
    *,
    marks: Sequence[float],
    fills: Sequence[ReplayFill],
    spec: LinearAccountSpec,
    funding: Sequence[ReplayFunding] = (),
    funding_phase: str = "after_fills_at_close",
) -> FillReplayOracleResult:
    """Run an explicit fill tape with deterministic `(bar, sequence)` order.

    The default close-boundary phase applies accepted fills first and funding at
    that bar's mark. ``before_fills_at_close`` is exposed only for hand tests
    of timing semantics; production timing selection belongs to the execution
    contract, not this accounting oracle.
    """

    if funding_phase not in {"after_fills_at_close", "before_fills_at_close"}:
        raise ValueError("unsupported funding_phase")
    if not marks:
        raise ValueError("marks cannot be empty")
    normalized_marks = tuple(float(value) for value in marks)
    if any(not math.isfinite(value) or value <= 0.0 for value in normalized_marks):
        raise ValueError("marks must be finite and > 0")
    fills_by_bar = _group_fills(fills, len(normalized_marks))
    funding_by_bar = _group_funding(funding, len(normalized_marks))
    state = initial_state(spec)
    fill_transitions: list[FillTransition] = []
    funding_transitions: list[FundingTransition] = []
    snapshots: list[ReplaySnapshot] = []

    for bar_index, mark in enumerate(normalized_marks):
        if funding_phase == "before_fills_at_close":
            state, transitions = _apply_funding_rows(state, funding_by_bar.get(bar_index, ()), mark, spec)
            funding_transitions.extend(transitions)
        for fill in fills_by_bar.get(bar_index, ()):
            transition = apply_fill(
                state,
                signed_qty=fill.signed_qty,
                price=fill.price,
                fee=fill.fee,
                spec=spec,
            )
            state = transition.after
            fill_transitions.append(transition)
        if funding_phase == "after_fills_at_close":
            state, transitions = _apply_funding_rows(state, funding_by_bar.get(bar_index, ()), mark, spec)
            funding_transitions.extend(transitions)
        snapshots.append(ReplaySnapshot(bar_index, state, mark_to_market(state, mark_price=mark, spec=spec)))

    return FillReplayOracleResult(state, tuple(fill_transitions), tuple(funding_transitions), tuple(snapshots))


def _group_fills(rows: Sequence[ReplayFill], n_bars: int) -> Mapping[int, tuple[ReplayFill, ...]]:
    grouped: dict[int, list[ReplayFill]] = {}
    seen: set[tuple[int, int]] = set()
    for row in rows:
        _validate_bar_and_sequence(row.bar_index, row.sequence, n_bars, seen)
        grouped.setdefault(int(row.bar_index), []).append(row)
    return {bar: tuple(sorted(items, key=lambda item: item.sequence)) for bar, items in grouped.items()}


def _group_funding(rows: Sequence[ReplayFunding], n_bars: int) -> Mapping[int, tuple[ReplayFunding, ...]]:
    grouped: dict[int, list[ReplayFunding]] = {}
    seen: set[tuple[int, int]] = set()
    for row in rows:
        _validate_bar_and_sequence(row.bar_index, row.sequence, n_bars, seen)
        if not math.isfinite(float(row.rate)):
            raise ValueError("funding rate must be finite")
        grouped.setdefault(int(row.bar_index), []).append(row)
    return {bar: tuple(sorted(items, key=lambda item: item.sequence)) for bar, items in grouped.items()}


def _apply_funding_rows(
    state: LinearAccountState,
    rows: Sequence[ReplayFunding],
    mark: float,
    spec: LinearAccountSpec,
) -> tuple[LinearAccountState, tuple[FundingTransition, ...]]:
    transitions: list[FundingTransition] = []
    for row in rows:
        transition = apply_funding(state, rate=row.rate, mark_price=mark, spec=spec)
        state = transition.after
        transitions.append(transition)
    return state, tuple(transitions)


def _validate_bar_and_sequence(bar_index: int, sequence: int, n_bars: int, seen: set[tuple[int, int]]) -> None:
    if not 0 <= int(bar_index) < n_bars:
        raise ValueError("replay row bar_index is outside marks")
    if int(sequence) < 0:
        raise ValueError("replay row sequence must be >= 0")
    key = (int(bar_index), int(sequence))
    if key in seen:
        raise ValueError("replay rows cannot share a bar/sequence")
    seen.add(key)


__all__ = [
    "FillReplayOracleResult",
    "ReplayFill",
    "ReplayFunding",
    "ReplaySnapshot",
    "run_fill_replay",
]
