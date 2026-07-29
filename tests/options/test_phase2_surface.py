from __future__ import annotations

import pandas as pd
import pytest

from quantbt import TotalVarianceSurface


def _timestamp(value: str) -> int:
    return int(pd.Timestamp(value, tz="UTC").value)


def _surface_frame() -> pd.DataFrame:
    ts = _timestamp("2026-01-01 00:00:00")
    expiry_1 = _timestamp("2026-02-01 08:00:00")
    expiry_2 = _timestamp("2026-03-01 08:00:00")
    return pd.DataFrame(
        {
            "timestamp_ns": [ts, ts, ts, ts],
            "expiry_ns": [expiry_1, expiry_1, expiry_2, expiry_2],
            "strike": [90_000.0, 100_000.0, 90_000.0, 100_000.0],
            "mark_iv": [0.60, 0.62, 0.65, 0.67],
        }
    )


def test_phase2_total_variance_surface_interpolates_strike_then_expiry():
    frame = _surface_frame()
    ts = int(frame["timestamp_ns"].iloc[0])
    surface = TotalVarianceSurface.from_snapshot_frame(frame, timestamp_ns=ts)

    expiry_1, expiry_2 = sorted(frame["expiry_ns"].unique())
    strike_mid = 95_000.0
    expiry_mid = int((expiry_1 + expiry_2) // 2)

    v1 = surface.interpolate_total_variance(expiry_ns=int(expiry_1), strike=strike_mid)
    v2 = surface.interpolate_total_variance(expiry_ns=int(expiry_2), strike=strike_mid)
    vmid = surface.interpolate_total_variance(expiry_ns=expiry_mid, strike=strike_mid)

    assert v1 > 0.0
    assert v2 > v1
    assert v1 < vmid < v2
    assert surface.diagnostics().pass_basic
    assert surface.diagnostics().butterfly_convexity_checked is False


def test_phase2_total_variance_surface_rejects_future_timestamp_rows():
    frame = _surface_frame()
    ts = int(frame["timestamp_ns"].iloc[0])
    frame.loc[0, "timestamp_ns"] = ts + 1

    with pytest.raises(ValueError, match="future timestamp"):
        TotalVarianceSurface.from_snapshot_frame(frame, timestamp_ns=ts)


def test_phase2_total_variance_surface_flags_calendar_variance_decrease():
    ts = _timestamp("2026-01-01 00:00:00")
    expiry_1 = _timestamp("2026-02-01 08:00:00")
    expiry_2 = _timestamp("2026-03-01 08:00:00")
    surface = TotalVarianceSurface(
        timestamp_ns=ts,
        expiry_ns=[expiry_1, expiry_2],
        strike=[100_000.0, 100_000.0],
        total_variance=[0.20, 0.10],
    )

    diag = surface.diagnostics()
    assert diag.positive_total_variance
    assert diag.calendar_total_variance_non_decreasing is False
    assert diag.pass_basic is False


def test_phase2_total_variance_surface_rejects_expired_or_negative_variance():
    ts = _timestamp("2026-01-01 00:00:00")
    with pytest.raises(ValueError, match="after timestamp"):
        TotalVarianceSurface(timestamp_ns=ts, expiry_ns=[ts], strike=[100_000.0], total_variance=[0.1])
    with pytest.raises(ValueError, match="total_variance"):
        TotalVarianceSurface(
            timestamp_ns=ts,
            expiry_ns=[_timestamp("2026-02-01 08:00:00")],
            strike=[100_000.0],
            total_variance=[-0.1],
        )
