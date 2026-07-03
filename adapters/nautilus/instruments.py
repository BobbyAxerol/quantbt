"""
Data and instrument helpers for NautilusTrader adapter.
"""

from __future__ import annotations

import pandas as pd


_TIMEFRAME_MAP = {
    "1min": "1-MINUTE",
    "1m": "1-MINUTE",
    "5min": "5-MINUTE",
    "5m": "5-MINUTE",
    "15min": "15-MINUTE",
    "15m": "15-MINUTE",
    "30min": "30-MINUTE",
    "30m": "30-MINUTE",
    "1h": "1-HOUR",
    "2h": "2-HOUR",
    "4h": "4-HOUR",
    "6h": "6-HOUR",
    "12h": "12-HOUR",
    "1d": "1-DAY",
    "1w": "1-WEEK",
}


def timeframe_to_nautilus(timeframe: str) -> str:
    try:
        return _TIMEFRAME_MAP[timeframe.lower()]
    except KeyError as exc:
        raise ValueError(f"Unsupported timeframe {timeframe!r}") from exc


def ensure_utc_ohlcv(data: pd.DataFrame) -> pd.DataFrame:
    """
    Return Nautilus-compatible OHLCV data.

    Required output columns are lowercase: open, high, low, close, volume.
    Index is a UTC DatetimeIndex.
    """
    df = data.copy()
    rename = {
        "Date": "timestamp",
        "Datetime": "timestamp",
        "Open": "open",
        "High": "high",
        "Low": "low",
        "Close": "close",
        "Volume": "volume",
    }
    df = df.rename(columns=rename)
    if "timestamp" in df.columns:
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
        df = df.set_index("timestamp")
    if not isinstance(df.index, pd.DatetimeIndex):
        raise ValueError("data must have a DatetimeIndex or timestamp column")
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC")
    else:
        df.index = df.index.tz_convert("UTC")

    required = ["open", "high", "low", "close", "volume"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"missing OHLCV columns: {missing}")
    return df[required].sort_index()
