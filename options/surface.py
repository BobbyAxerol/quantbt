"""
Minimal option surface diagnostics.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, Tuple

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class SurfaceDiagnostics:
    positive_total_variance: bool
    no_future_timestamps: bool
    expiries_after_snapshot: bool
    calendar_total_variance_non_decreasing: bool
    butterfly_convexity_checked: bool
    notes: Tuple[str, ...]

    @property
    def pass_basic(self) -> bool:
        return (
            self.positive_total_variance
            and self.no_future_timestamps
            and self.expiries_after_snapshot
            and self.calendar_total_variance_non_decreasing
        )


@dataclass(frozen=True)
class TotalVarianceSurface:
    timestamp_ns: int
    expiry_ns: np.ndarray
    strike: np.ndarray
    total_variance: np.ndarray

    def __post_init__(self) -> None:
        timestamp = int(self.timestamp_ns)
        expiry = np.asarray(self.expiry_ns, dtype=np.int64)
        strike = np.asarray(self.strike, dtype=np.float64)
        variance = np.asarray(self.total_variance, dtype=np.float64)
        if timestamp <= 0:
            raise ValueError("timestamp_ns must be > 0")
        if expiry.ndim != 1 or strike.ndim != 1 or variance.ndim != 1:
            raise ValueError("surface arrays must be 1-D")
        if len(expiry) == 0 or len(expiry) != len(strike) or len(expiry) != len(variance):
            raise ValueError("surface arrays must be non-empty and equal length")
        if bool((expiry <= timestamp).any()):
            raise ValueError("surface expiry_ns must be after timestamp_ns")
        if bool((strike <= 0.0).any()):
            raise ValueError("surface strikes must be > 0")
        if bool((~np.isfinite(variance)).any()) or bool((variance < 0.0).any()):
            raise ValueError("total_variance must be finite and >= 0")
        order = np.lexsort((strike, expiry))
        object.__setattr__(self, "timestamp_ns", timestamp)
        object.__setattr__(self, "expiry_ns", expiry[order])
        object.__setattr__(self, "strike", strike[order])
        object.__setattr__(self, "total_variance", variance[order])

    @classmethod
    def from_snapshot_frame(
        cls,
        frame: pd.DataFrame,
        *,
        timestamp_ns: int,
        volatility_column: str = "mark_iv",
    ) -> "TotalVarianceSurface":
        required = {"timestamp_ns", "expiry_ns", "strike", volatility_column}
        missing = sorted(required.difference(frame.columns))
        if missing:
            raise ValueError(f"surface frame missing required columns: {missing}")
        timestamp = int(timestamp_ns)
        future_rows = frame.loc[pd.to_numeric(frame["timestamp_ns"], errors="raise").astype("int64") > timestamp]
        if len(future_rows) > 0:
            raise ValueError("surface calibration cannot include future timestamp rows")
        snapshot = frame.loc[pd.to_numeric(frame["timestamp_ns"], errors="raise").astype("int64") == timestamp].copy()
        if snapshot.empty:
            raise ValueError("surface snapshot has no rows for timestamp_ns")
        expiry = pd.to_numeric(snapshot["expiry_ns"], errors="raise").astype("int64").to_numpy()
        strike = pd.to_numeric(snapshot["strike"], errors="raise").astype("float64").to_numpy()
        vol = pd.to_numeric(snapshot[volatility_column], errors="raise").astype("float64").to_numpy()
        tau_years = (expiry.astype(np.float64) - float(timestamp)) / (365.0 * 24.0 * 60.0 * 60.0 * 1_000_000_000.0)
        total_variance = vol * vol * tau_years
        return cls(timestamp_ns=timestamp, expiry_ns=expiry, strike=strike, total_variance=total_variance)

    @property
    def expiries(self) -> np.ndarray:
        return np.unique(self.expiry_ns)

    def interpolate_total_variance(self, *, expiry_ns: int, strike: float) -> float:
        """Interpolate total variance by strike first, then expiry."""
        target_expiry = int(expiry_ns)
        target_strike = float(strike)
        if target_expiry <= self.timestamp_ns:
            raise ValueError("target expiry must be after surface timestamp")
        if target_strike <= 0.0:
            raise ValueError("target strike must be > 0")
        expiries = self.expiries
        per_expiry = np.array([self._interpolate_strike(expiry, target_strike) for expiry in expiries], dtype=np.float64)
        if len(expiries) == 1:
            return float(per_expiry[0])
        return float(np.interp(float(target_expiry), expiries.astype(np.float64), per_expiry))

    def diagnostics(self) -> SurfaceDiagnostics:
        notes = ["butterfly convexity is placeholder-only in Phase 2"]
        by_strike = _group_by_strike(self.expiry_ns, self.strike, self.total_variance)
        calendar_ok = True
        for rows in by_strike.values():
            rows_sorted = sorted(rows, key=lambda item: item[0])
            variances = np.array([item[1] for item in rows_sorted], dtype=np.float64)
            if len(variances) > 1 and bool((np.diff(variances) < -1e-12).any()):
                calendar_ok = False
                break
        return SurfaceDiagnostics(
            positive_total_variance=bool((self.total_variance >= 0.0).all()),
            no_future_timestamps=True,
            expiries_after_snapshot=bool((self.expiry_ns > self.timestamp_ns).all()),
            calendar_total_variance_non_decreasing=calendar_ok,
            butterfly_convexity_checked=False,
            notes=tuple(notes),
        )

    def _interpolate_strike(self, expiry_ns: int, strike: float) -> float:
        mask = self.expiry_ns == int(expiry_ns)
        strikes = self.strike[mask]
        variances = self.total_variance[mask]
        if len(strikes) == 0:
            raise ValueError("expiry not found")
        if len(strikes) == 1:
            return float(variances[0])
        order = np.argsort(strikes)
        return float(np.interp(strike, strikes[order], variances[order]))


def _group_by_strike(expiry_ns: Iterable[int], strike: Iterable[float], total_variance: Iterable[float]) -> Dict[float, list[tuple[int, float]]]:
    grouped: Dict[float, list[tuple[int, float]]] = {}
    for expiry, strike_value, variance in zip(expiry_ns, strike, total_variance):
        grouped.setdefault(float(strike_value), []).append((int(expiry), float(variance)))
    return grouped
