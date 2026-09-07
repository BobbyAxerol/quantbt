"""Standard-library-only calendar mapping oracle for V1.1 differential tests."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Optional, Sequence


@dataclass(frozen=True)
class OracleCalendarMap:
    canonical_to_local: tuple[Optional[int], ...]
    local_to_canonical: tuple[Optional[int], ...]
    observed: tuple[bool, ...]
    stale: tuple[bool, ...]
    tradable: tuple[bool, ...]


def build_calendar_plan(
    calendars: Mapping[str, Sequence[int]],
    *,
    policy: str,
    missing_policy: str = "no_observation",
    primary_symbol: Optional[str] = None,
) -> tuple[tuple[int, ...], dict[str, OracleCalendarMap]]:
    """Return the minimal independent counterpart of ``CalendarPlanV2``."""
    symbols = tuple(sorted(calendars))
    if not symbols:
        raise ValueError("calendar mapping is empty")
    source = {symbol: _strict(calendars[symbol], symbol) for symbol in symbols}
    mode = str(policy).lower().strip()
    if mode == "exact":
        canonical = source[symbols[0]]
        for symbol in symbols[1:]:
            if source[symbol] != canonical:
                row = _first_difference(canonical, source[symbol])
                raise ValueError(f"exact mismatch at row {row}")
    elif mode == "intersection":
        common = set(source[symbols[0]])
        for symbol in symbols[1:]:
            common &= set(source[symbol])
        canonical = tuple(sorted(common))
        if not canonical:
            raise ValueError("empty intersection")
    elif mode == "union":
        canonical = tuple(sorted({stamp for values in source.values() for stamp in values}))
    elif mode == "primary_clock":
        if primary_symbol not in source:
            raise ValueError("primary symbol missing")
        canonical = source[str(primary_symbol)]
    else:
        raise ValueError("unknown calendar policy")
    maps: dict[str, OracleCalendarMap] = {}
    for symbol in symbols:
        local = source[symbol]
        local_positions = {timestamp: index for index, timestamp in enumerate(local)}
        canonical_to_local = tuple(local_positions.get(timestamp) for timestamp in canonical)
        canonical_positions = {timestamp: index for index, timestamp in enumerate(canonical)}
        local_to_canonical = tuple(canonical_positions.get(timestamp) for timestamp in local)
        observed = tuple(value is not None for value in canonical_to_local)
        stale = _stale(observed, missing_policy)
        maps[symbol] = OracleCalendarMap(
            canonical_to_local=canonical_to_local,
            local_to_canonical=local_to_canonical,
            observed=observed,
            stale=stale,
            tradable=observed,
        )
    return canonical, maps


def _strict(values: Sequence[int], symbol: str) -> tuple[int, ...]:
    result = tuple(int(value) for value in values)
    if not result or any(left >= right for left, right in zip(result, result[1:])):
        raise ValueError(f"invalid source calendar for {symbol}")
    return result


def _first_difference(left: Sequence[int], right: Sequence[int]) -> int:
    for index, (lhs, rhs) in enumerate(zip(left, right)):
        if lhs != rhs:
            return index
    return min(len(left), len(right))


def _stale(observed: Sequence[bool], missing_policy: str) -> tuple[bool, ...]:
    if str(missing_policy).lower().strip() not in {
        "mark_to_last_no_execution",
        "forward_fill_quote_no_volume",
    }:
        return tuple(False for _ in observed)
    seen = False
    values = []
    for present in observed:
        values.append((not present) and seen)
        seen = seen or present
    return tuple(values)
