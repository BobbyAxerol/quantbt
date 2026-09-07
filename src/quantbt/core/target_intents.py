"""Typed static target-intent helpers for close-target execution.

The vectorized direct-target engine can only consume facts known before the
run. A scheduled DCA ladder is such a fact: it names absolute target units at
declared timestamps. A grid/safety-order program that waits for a fill or an
intrabar trigger is not a static target tape and must remain on a reactive
event route.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

import numpy as np
import pandas as pd


STATIC_TARGET_TAPE_SCHEMA_V1 = "quantbt-static-target-tape-v1"


@dataclass(frozen=True, slots=True)
class StaticDcaTargetStepV1:
    """One predeclared absolute target at an exact market timestamp.

    ``target_units`` is an absolute signed holding after the scheduled action,
    not a delta order. This makes scale-in, scale-out, reversal, and flatten
    semantics unambiguous to a direct target-delta executor.
    """

    timestamp: object
    target_units: float

    def __post_init__(self) -> None:
        value = float(self.target_units)
        if not np.isfinite(value):
            raise ValueError("static DCA target_units must be finite")
        object.__setattr__(self, "target_units", value)


@dataclass(frozen=True, slots=True)
class StaticTargetTapeV1:
    """Immutable provenance for a scheduled direct target tape."""

    target_units: pd.Series
    schedule: tuple[StaticDcaTargetStepV1, ...]
    initial_target_units: float
    schema: str = STATIC_TARGET_TAPE_SCHEMA_V1
    execution_class: str = "static_schedule_target_v1"
    fill_dependent: bool = False

    def metadata(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "execution_class": self.execution_class,
            "fill_dependent": bool(self.fill_dependent),
            "initial_target_units": float(self.initial_target_units),
            "scheduled_target_steps": int(len(self.schedule)),
            "schedule": [
                {
                    "timestamp": pd.Timestamp(step.timestamp).isoformat(),
                    "target_units": float(step.target_units),
                }
                for step in self.schedule
            ],
        }


def compile_static_dca_target_tape(
    datetime_index: pd.DatetimeIndex | Sequence[object],
    schedule: (
        Mapping[object, float]
        | pd.Series
        | Sequence[StaticDcaTargetStepV1]
        | Sequence[tuple[object, float]]
    ),
    *,
    initial_target_units: float = 0.0,
) -> StaticTargetTapeV1:
    """Compile a known-in-advance DCA schedule into an absolute target tape.

    The schedule is deliberately strict: each timestamp must occur exactly on
    the supplied market clock and may appear once only. It does not inspect
    OHLC, fills, or account state, so it cannot be mistaken for a dynamic grid
    or safety-order strategy.
    """

    index = pd.DatetimeIndex(datetime_index)
    if index.empty or not index.is_monotonic_increasing or not index.is_unique:
        raise ValueError("static target tape requires a non-empty unique monotonic DatetimeIndex")
    initial = float(initial_target_units)
    if not np.isfinite(initial):
        raise ValueError("initial_target_units must be finite")
    if index.tz is None:
        index = index.tz_localize("UTC")
    else:
        index = index.tz_convert("UTC")

    steps = _normalise_schedule(schedule, index.tz)
    timestamps = [pd.Timestamp(step.timestamp) for step in steps]
    if len(set(timestamps)) != len(timestamps):
        raise ValueError("static DCA schedule timestamps must be unique")
    missing = [timestamp for timestamp in timestamps if timestamp not in index]
    if missing:
        raise ValueError(
            "static DCA schedule timestamps must exist in the market index; "
            f"first missing timestamp: {missing[0]!s}"
        )

    # ``NaN`` is intentional here. A numeric initial fill would make every
    # unscheduled bar look like an explicit zero/initial target and prevent a
    # scheduled absolute target from carrying forward to its next step.
    targets = pd.Series(np.nan, index=index, dtype=np.float64, name="target_units")
    targets.iloc[0] = initial
    for step in steps:
        targets.loc[pd.Timestamp(step.timestamp)] = float(step.target_units)
    targets = targets.ffill().astype(np.float64)
    return StaticTargetTapeV1(
        target_units=targets,
        schedule=tuple(steps),
        initial_target_units=initial,
    )


def _normalise_schedule(
    schedule: (
        Mapping[object, float]
        | pd.Series
        | Sequence[StaticDcaTargetStepV1]
        | Sequence[tuple[object, float]]
    ),
    timezone,
) -> tuple[StaticDcaTargetStepV1, ...]:
    if isinstance(schedule, pd.Series):
        raw = list(schedule.items())
    elif isinstance(schedule, Mapping):
        raw = list(schedule.items())
    else:
        raw = list(schedule)
    if not raw:
        raise ValueError("static DCA schedule must contain at least one target step")

    normalized: list[StaticDcaTargetStepV1] = []
    for item in raw:
        if isinstance(item, StaticDcaTargetStepV1):
            timestamp, target = item.timestamp, item.target_units
        else:
            try:
                timestamp, target = item
            except (TypeError, ValueError) as exc:
                raise TypeError(
                    "static DCA schedule entries must be StaticDcaTargetStepV1 or (timestamp, target_units)"
                ) from exc
        resolved = pd.Timestamp(timestamp)
        if resolved.tz is None:
            resolved = resolved.tz_localize(timezone)
        else:
            resolved = resolved.tz_convert(timezone)
        normalized.append(StaticDcaTargetStepV1(resolved, float(target)))
    normalized.sort(key=lambda step: pd.Timestamp(step.timestamp))
    return tuple(normalized)


__all__ = [
    "STATIC_TARGET_TAPE_SCHEMA_V1",
    "StaticDcaTargetStepV1",
    "StaticTargetTapeV1",
    "compile_static_dca_target_tape",
]
