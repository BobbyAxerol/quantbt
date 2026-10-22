"""Exact market/preload and account calendars for an opt-in continuous binding.

This descriptor owns calendar policy only. The sealed contract and existing
engine own financial execution, strategy isolation, and account initialization.
No preload may be dropped, scored, or replaced with an external history closure.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd

from .continuous import ContinuousAccountContract, _index
from .diagnostics.identity import digest

if TYPE_CHECKING:
    from ..walkforward import WalkForwardFold


SCOPE_VERSION = "quantbt.mode5.continuous_account_scope.v1"


def _calendar(index: pd.DatetimeIndex) -> bytes:
    times = _index(index)
    if not len(times):
        raise ValueError("nonempty exact calendar required")
    return times.astype("<i8", copy=False).tobytes()


@dataclass(frozen=True, slots=True)
class ContinuousAccountScope:
    """Immutable full allowed prefix and its exact scored-account suffix.

    Use ``full_index`` for market alignment, prepared context, and strategy data
    access. Use ``scored_index`` for folds, execution and account observations.
    Witness intervals and account intervals are half-open nanosecond ranges.
    Naive calendars mean UTC, matching the continuous contract; other timezones
    must be normalized by the existing ingestion layer before this boundary.
    """

    contract: ContinuousAccountContract
    _full_calendar: bytes = field(repr=False)
    version: str = SCOPE_VERSION

    def __post_init__(self) -> None:
        if self.version != SCOPE_VERSION:
            raise ValueError("explicit continuous account scope version required")
        if not isinstance(self.contract, ContinuousAccountContract):
            raise TypeError("sealed ContinuousAccountContract required")
        if (type(self._full_calendar) is not bytes or not self._full_calendar
                or len(self._full_calendar) % 8):
            raise TypeError("immutable exact nanosecond calendar required")
        c = self.contract
        c.access.require(c.witness)
        if (c.access.purpose == "independent_validation"
                or c.witness.start_ns > c.start_ns or c.witness.end_ns < c.stop_ns):
            raise PermissionError("complete permitted development prefix required")
        if c.execution.data["initial_state"].get("position_policy") != "flat":
            raise NotImplementedError("continuous scope requires explicit flat account entry; no state replay")
        times = np.frombuffer(self._full_calendar, dtype="<i8")
        step = c.metrics.data["bar_interval_ns"]
        if int(times[0]) != c.witness.start_ns:
            raise PermissionError("full prefix must start at sealed witness.start_ns; preload is not optional")
        if int(times[-1]) != c.stop_ns - step:
            raise PermissionError("full prefix must end at the last scored bar; no missing end or future suffix")
        if ((c.start_ns - c.witness.start_ns) % step
                or len(times) != (c.stop_ns - c.witness.start_ns) // step
                or np.any(times == np.iinfo(np.int64).min)
                or np.any(np.diff(times) != step)):
            raise ValueError("exact complete market/preload and scored clock required; no gaps or relabeling")

    @classmethod
    def from_contract(
        cls, contract: ContinuousAccountContract, full_index: pd.DatetimeIndex,
    ) -> ContinuousAccountScope:
        """Derive policy from a sealed contract, not caller-selected score bounds."""
        if not isinstance(contract, ContinuousAccountContract):
            raise TypeError("sealed ContinuousAccountContract required")
        return cls(contract, _calendar(full_index))

    def _index_view(self, span: slice) -> pd.DatetimeIndex:
        # Bytes retain no caller-owned mutable ndarray, including after pickle.
        times = np.frombuffer(self._full_calendar, dtype="<i8")[span]
        return pd.DatetimeIndex(times.copy(), tz="UTC")

    @property
    def full_index(self) -> pd.DatetimeIndex:
        return self._index_view(slice(None))

    @property
    def scored_slice(self) -> slice:
        c = self.contract
        start = (c.start_ns - c.witness.start_ns) // c.metrics.data["bar_interval_ns"]
        return slice(start, len(self._full_calendar) // 8)

    @property
    def scored_index(self) -> pd.DatetimeIndex:
        return self._index_view(self.scored_slice)

    @property
    def preload_index(self) -> pd.DatetimeIndex:
        return self._index_view(slice(0, self.scored_slice.start))

    def require_full_index(self, index: pd.DatetimeIndex) -> None:
        """Pre-execution guard: exact full prefix, without hidden future data."""
        self.contract.access.require(self.contract.witness)
        if _calendar(index) != self._full_calendar:
            raise PermissionError("market calendar differs from sealed full prefix")

    def require_scored_index(self, index: pd.DatetimeIndex) -> None:
        """Post-execution guard: no preload, missing marks, or future accounting."""
        self.contract.access.require(self.contract.witness)
        if _calendar(index) != self._full_calendar[self.scored_slice.start * 8:]:
            raise ValueError("account calendar differs from exact sealed scored window")

    def prefix_slice(self, end_ns: int) -> slice:
        """Positions on the full market through an exact permitted bar, inclusive."""
        if type(end_ns) is not int:
            raise TypeError("exact integer nanosecond prefix cutoff required")
        c = self.contract
        c.access.require(c.witness)
        step = c.metrics.data["bar_interval_ns"]
        if not c.witness.start_ns <= end_ns < c.stop_ns:
            raise PermissionError("prefix cutoff outside permitted market/account window")
        distance = end_ns - c.witness.start_ns
        if distance % step:
            raise ValueError("prefix cutoff must be an exact observed bar; no snapping")
        return slice(0, distance // step + 1)

    def folds(self) -> tuple[WalkForwardFold, ...]:
        """Adapt to the existing single-account fold, never annual reset folds.

        Initial flat state is supplied by the sealed execution contract. Carry
        describes continuity *inside* this one account, not inherited candidate
        state. Preload remains strategy data; no warmup hook is silently added.
        """
        from ..walkforward import WalkForwardFold

        index = self.scored_index
        return (WalkForwardFold(
            fold_id=0, train_start=index[0], train_end=index[-1],
            test_start=index[0], test_end=index[-1], train_index=index,
            test_index=index, cutoff_timestamp=index[-1], account_policy="carry_position",
        ),)

    @property
    def identity(self) -> str:
        return digest(dict(version=self.version, contract=self.contract.identity,
                           full_calendar=sha256(self._full_calendar).hexdigest()))

    def metadata(self) -> dict[str, object]:
        c = self.contract
        lo, hi = self.scored_slice.start, self.scored_slice.stop
        return dict(schema=self.version, identity=self.identity,
            contract_identity=c.identity, access_identity=c.access.identity,
            witness_identity=c.witness.identity, full_start_ns=c.witness.start_ns,
            full_stop_ns=c.stop_ns, scored_start_ns=c.start_ns, scored_stop_ns=c.stop_ns,
            bar_interval_ns=c.metrics.data["bar_interval_ns"], full_bars=hi,
            preload_bars=lo, scored_bars=hi-lo, scored_positions=(lo, hi),
            account_policy=c.account_policy, initial_state=c.execution.data["initial_state"],
            candidate_initialization="fresh_sealed_initial_state_per_evaluation",
            preload_account_execution=False, annual_account_resets=0,
            validation_claim="none_full_sample_calibration", execution_qualification=False)
