"""Lossless current-bar prefix certificate, not an approximate account cache."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True, eq=False)
class CommittedFeedbackPrefix:
    stop: int
    # Tuple links contain only prior tuple links, exact native row bytes and
    # immutable ID/name pairs. No mutable array/account/market is authorized.
    payload: tuple
