"""Immutable positional preparation for one walk-forward invocation.

The WFO engine repeatedly evaluates the same train/test windows while Optuna
changes only strategy parameters.  This module owns the parameter-independent
calendar views used by those evaluations.  It intentionally does not own
market data, strategy state, scoring, or account state.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

import numpy as np
import pandas as pd

from .preprocessor import validate_datetime


@dataclass(frozen=True, slots=True)
class PreparedWfoWindowV1:
    """One exact contiguous window on the canonical WFO clock.

    ``index`` is retained by identity, rather than reconstructed from a hash,
    so an engine can prove that a score task uses the run-local prepared view
    without recalculating a pandas indexer on every trial.
    """

    index: pd.DatetimeIndex
    start: int
    stop: int

    def __post_init__(self) -> None:
        if not isinstance(self.index, pd.DatetimeIndex) or len(self.index) == 0:
            raise ValueError("prepared WFO window requires a non-empty DatetimeIndex")
        if not 0 <= int(self.start) < int(self.stop):
            raise ValueError("prepared WFO window requires 0 <= start < stop")
        if int(self.stop) - int(self.start) != len(self.index):
            raise ValueError("prepared WFO window bounds must match its index length")

    @property
    def bars(self) -> int:
        return int(self.stop) - int(self.start)


def split_datetime_index_into_subperiods_v1(
    index: pd.DatetimeIndex,
    n_parts: int,
) -> tuple[pd.DatetimeIndex, ...]:
    """Reproduce ``numpy.array_split`` chronology without timestamp boxing.

    The old implementation converted every shard through ``np.array_split``
    and ``DatetimeIndex`` again for every trial.  The quotient/remainder rule
    below is exactly the array-split allocation rule.  Constructing from
    ``asi8`` deliberately retains the historic ``freq=None`` shard surface,
    including for a regular parent index.
    """

    idx = validate_datetime(index)
    if len(idx) == 0:
        return ()
    count = max(1, min(int(n_parts), len(idx)))
    base, remainder = divmod(len(idx), count)
    start = 0
    shards: list[pd.DatetimeIndex] = []
    for ordinal in range(count):
        stop = start + base + int(ordinal < remainder)
        if stop > start:
            shards.append(
                pd.DatetimeIndex(
                    idx.asi8[start:stop],
                    tz=idx.tz,
                    name=idx.name,
                )
            )
        start = stop
    return tuple(shards)


class PreparedWfoWindowRegistryV1:
    """Run-local registry of validated score windows and temporal shards.

    The registry is deliberately identity-keyed.  A caller only receives a
    fast path when it passes the exact canonical ``DatetimeIndex`` prepared by
    the current WFO run.  Equivalent but independently created indexes retain
    the historical path, which prevents accidental cross-run/cache reuse.
    """

    def __init__(self, full_index: pd.DatetimeIndex) -> None:
        self._full_index = validate_datetime(full_index)
        self._windows: dict[int, PreparedWfoWindowV1] = {}
        self._shards: dict[tuple[int, int], tuple[pd.DatetimeIndex, ...]] = {}
        self._trade_requirements: dict[tuple[int, float], float] = {}
        self._window_hits = 0
        self._window_misses = 0
        self._shard_hits = 0
        self._shard_misses = 0
        self._trade_requirement_hits = 0
        self._trade_requirement_misses = 0

    def register(self, index: pd.DatetimeIndex) -> PreparedWfoWindowV1 | None:
        """Register a contiguous canonical view once and return its window."""

        if not isinstance(index, pd.DatetimeIndex) or len(index) == 0:
            return None
        cached = self._windows.get(id(index))
        if cached is not None and cached.index is index:
            return cached
        locations = self._full_index.get_indexer(index)
        if (
            np.any(locations < 0)
            or len(locations) == 0
            or (len(locations) > 1 and not np.all(np.diff(locations) == 1))
        ):
            return None
        window = PreparedWfoWindowV1(
            index=index,
            start=int(locations[0]),
            stop=int(locations[-1]) + 1,
        )
        self._windows[id(index)] = window
        return window

    def register_shards(self, index: pd.DatetimeIndex, n_parts: int) -> tuple[pd.DatetimeIndex, ...]:
        """Precompute exact temporal shards for an already-owned IS window."""

        self.register(index)
        key = (id(index), int(n_parts))
        cached = self._shards.get(key)
        if cached is not None:
            return cached
        shards = split_datetime_index_into_subperiods_v1(index, int(n_parts))
        for shard in shards:
            registered = self.register(shard)
            if registered is None:  # defensive: a parent canonical slice must remain canonical
                raise RuntimeError("prepared WFO shard was not contiguous on the canonical clock")
        self._shards[key] = shards
        return shards

    def window_for(self, index: pd.DatetimeIndex) -> PreparedWfoWindowV1 | None:
        """Return an exact registered window or record a safe fallback."""

        window = self._windows.get(id(index))
        if window is not None and window.index is index:
            self._window_hits += 1
            return window
        self._window_misses += 1
        return None

    def shards_for(self, index: pd.DatetimeIndex, n_parts: int) -> tuple[pd.DatetimeIndex, ...] | None:
        """Return a precomputed shard tuple only for the exact source index."""

        shards = self._shards.get((id(index), int(n_parts)))
        if shards is not None:
            self._shard_hits += 1
            return shards
        self._shard_misses += 1
        return None

    def required_trades_for(
        self,
        index: pd.DatetimeIndex,
        min_trades_per_year: float | None,
    ) -> float | None:
        """Return the historic annualized requirement for an exact view.

        The calculation is intentionally retained here rather than cached by
        an index hash.  It is available only for a registered immutable view,
        so an unrelated caller cannot make a stale calendar appear eligible.
        """

        if min_trades_per_year is None or float(min_trades_per_year) <= 0.0:
            return 0.0
        window = self._windows.get(id(index))
        if window is None or window.index is not index:
            self._trade_requirement_misses += 1
            return None
        key = (id(index), float(min_trades_per_year))
        cached = self._trade_requirements.get(key)
        if cached is not None:
            self._trade_requirement_hits += 1
            return float(cached)
        if len(index) <= 1:
            duration_days = 1.0 / 365.0
        else:
            duration_days = max((index[-1] - index[0]).total_seconds() / 86_400.0, 1.0 / 365.0)
        result = float(min_trades_per_year) * (duration_days / 365.0)
        self._trade_requirements[key] = result
        self._trade_requirement_misses += 1
        return result

    def metadata(self) -> Mapping[str, int | str]:
        return {
            "schema": "quantbt-prepared-wfo-window-registry-v1",
            "canonical_windows": int(len(self._windows)),
            "prepared_shard_sets": int(len(self._shards)),
            "prepared_shards": int(sum(len(value) for value in self._shards.values())),
            "prepared_trade_requirements": int(len(self._trade_requirements)),
            "window_lookup_hits": int(self._window_hits),
            "window_lookup_misses": int(self._window_misses),
            "shard_lookup_hits": int(self._shard_hits),
            "shard_lookup_misses": int(self._shard_misses),
            "trade_requirement_hits": int(self._trade_requirement_hits),
            "trade_requirement_misses": int(self._trade_requirement_misses),
        }


__all__ = [
    "PreparedWfoWindowRegistryV1",
    "PreparedWfoWindowV1",
    "split_datetime_index_into_subperiods_v1",
]
