"""Session-aware intrabar execution primitives.

These objects are intentionally data-only. Calendar, timezone, and entry-window
logic are normalized before the execution kernel so the hot path never needs to
parse datetimes.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import Enum
from typing import Optional, Sequence

import numpy as np
import pandas as pd


class EntryPositionPolicy(str, Enum):
    CURRENT_BEHAVIOR = "current_behavior"
    FLAT_ONLY = "flat_only"
    REVERSE = "reverse"


class SessionCounterBasis(str, Enum):
    FILLED_ENTRY = "filled_entry"
    ACCEPTED_ENTRY = "accepted_entry"


class ProtectiveExitReentryPolicy(str, Enum):
    ALLOW = "allow"
    SUPPRESS_SIGNAL_BAR = "suppress_signal_bar"


@dataclass(frozen=True)
class SessionExecutionPolicy:
    entry_position_policy: EntryPositionPolicy = EntryPositionPolicy.CURRENT_BEHAVIOR
    max_long_entries_per_session: Optional[int] = None
    max_short_entries_per_session: Optional[int] = None
    counter_basis: SessionCounterBasis = SessionCounterBasis.FILLED_ENTRY
    cancel_pending_on_session_change: bool = True
    suppress_entry_on_force_flat_bar: bool = True
    protective_exit_reentry_policy: ProtectiveExitReentryPolicy = ProtectiveExitReentryPolicy.ALLOW

    def __post_init__(self) -> None:
        object.__setattr__(self, "entry_position_policy", EntryPositionPolicy(self.entry_position_policy))
        object.__setattr__(self, "counter_basis", SessionCounterBasis(self.counter_basis))
        object.__setattr__(self, "protective_exit_reentry_policy", ProtectiveExitReentryPolicy(self.protective_exit_reentry_policy))
        for name in ("max_long_entries_per_session", "max_short_entries_per_session"):
            value = getattr(self, name)
            if value is not None and int(value) < 0:
                raise ValueError(f"{name} must be >= 0 when provided")
            if value is not None:
                object.__setattr__(self, name, int(value))

    def to_metadata(self) -> dict:
        return {
            "entry_position_policy": self.entry_position_policy.value,
            "max_long_entries_per_session": self.max_long_entries_per_session,
            "max_short_entries_per_session": self.max_short_entries_per_session,
            "counter_basis": self.counter_basis.value,
            "cancel_pending_on_session_change": bool(self.cancel_pending_on_session_change),
            "suppress_entry_on_force_flat_bar": bool(self.suppress_entry_on_force_flat_bar),
            "protective_exit_reentry_policy": self.protective_exit_reentry_policy.value,
        }

    @classmethod
    def from_metadata(cls, metadata: Optional[dict]) -> Optional["SessionExecutionPolicy"]:
        if metadata is None:
            return None
        if isinstance(metadata, SessionExecutionPolicy):
            return metadata
        return cls(**dict(metadata))


@dataclass(frozen=True)
class IntrabarSessionTape:
    session_id: np.ndarray
    entry_allowed_at_open: np.ndarray
    force_flat_at_open: np.ndarray
    signature: str = ""

    def __post_init__(self) -> None:
        session_id = np.ascontiguousarray(self.session_id, dtype=np.int64)
        entry_allowed = np.ascontiguousarray(self.entry_allowed_at_open, dtype=np.bool_)
        force_flat = np.ascontiguousarray(self.force_flat_at_open, dtype=np.bool_)
        n = len(session_id)
        if len(entry_allowed) != n or len(force_flat) != n:
            raise ValueError("session tape arrays must have the same length")
        session_id.setflags(write=False)
        entry_allowed.setflags(write=False)
        force_flat.setflags(write=False)
        object.__setattr__(self, "session_id", session_id)
        object.__setattr__(self, "entry_allowed_at_open", entry_allowed)
        object.__setattr__(self, "force_flat_at_open", force_flat)
        signature = self.signature or self._build_signature(session_id, entry_allowed, force_flat)
        object.__setattr__(self, "signature", signature)

    @classmethod
    def from_index(
        cls,
        index: Sequence,
        *,
        timezone: str = "UTC",
        session_key: str = "local_date",
        entry_windows: Sequence[tuple[str, str]] = (),
        force_flat_time: Optional[str] = None,
    ) -> "IntrabarSessionTape":
        idx = pd.DatetimeIndex(pd.to_datetime(index))
        if idx.tz is None:
            if not timezone:
                raise ValueError("timezone is required for naive session indexes")
            idx = idx.tz_localize(timezone)
        local = idx.tz_convert(timezone)
        if session_key != "local_date":
            raise NotImplementedError("IntrabarSessionTape.from_index currently supports session_key='local_date'")
        dates = pd.Index(local.date)
        _, session_id = np.unique(dates.astype(str), return_inverse=True)
        minutes = local.hour.to_numpy(dtype=np.int64) * 60 + local.minute.to_numpy(dtype=np.int64)
        if entry_windows:
            entry_allowed = np.zeros(len(local), dtype=np.bool_)
            for start, end in entry_windows:
                start_min = _parse_hhmm(start)
                end_min = _parse_hhmm(end)
                entry_allowed |= (minutes >= start_min) & (minutes <= end_min)
        else:
            entry_allowed = np.ones(len(local), dtype=np.bool_)
        force_flat = np.zeros(len(local), dtype=np.bool_)
        if force_flat_time is not None:
            force_flat[:] = minutes == _parse_hhmm(force_flat_time)
        return cls(
            session_id=np.ascontiguousarray(session_id, dtype=np.int64),
            entry_allowed_at_open=entry_allowed,
            force_flat_at_open=force_flat,
        )

    @staticmethod
    def _build_signature(session_id: np.ndarray, entry_allowed: np.ndarray, force_flat: np.ndarray) -> str:
        h = hashlib.blake2b(digest_size=16)
        for arr in (session_id, entry_allowed, force_flat):
            h.update(np.ascontiguousarray(arr).view(np.uint8))
        payload = {
            "session_id": str(session_id.dtype),
            "entry_allowed": str(entry_allowed.dtype),
            "force_flat": str(force_flat.dtype),
            "rows": int(len(session_id)),
            "hash": h.hexdigest(),
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


def _parse_hhmm(value: str) -> int:
    hour, minute = str(value).split(":", 1)
    return int(hour) * 60 + int(minute)

