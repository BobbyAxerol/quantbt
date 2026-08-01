"""
quantbt.core.preprocessor
--------------------------
Data alignment and numpy array assembly for the simulation kernels.
Keeps BacktestEngine clean; all pandas wrangling lives here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional, Union

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class MarketDataSignature:
    length: int
    first_timestamp_ns: Optional[int]
    last_timestamp_ns: Optional[int]
    symbols: tuple
    shape: tuple


@dataclass(frozen=True)
class PreparedMarketArrays:
    idx: pd.DatetimeIndex
    symbols: tuple
    closes: np.ndarray
    highs: np.ndarray
    lows: np.ndarray
    funding: np.ndarray
    is_funding_bar: np.ndarray
    signature: MarketDataSignature


def validate_datetime(dt_input) -> pd.DatetimeIndex:
    """Return a sorted, unique, UTC DatetimeIndex from any sensible input."""
    if isinstance(dt_input, pd.DatetimeIndex):
        idx = dt_input
    else:
        idx = pd.to_datetime(pd.Series(dt_input), errors="coerce", utc=True)
    idx = pd.DatetimeIndex(idx).drop_duplicates().sort_values()
    if idx.tz is None:
        idx = idx.tz_localize("UTC")
    else:
        idx = idx.tz_convert("UTC")
    return idx


def align_series(
    data: Union[pd.Series, Dict[str, pd.Series]],
    symbols: list,
    idx: pd.DatetimeIndex,
    fill_val: float = np.nan,
    fallback: Optional[Dict[str, pd.Series]] = None,
) -> Dict[str, pd.Series]:
    """
    Reindex each symbol's series to idx using forward-fill.
    If data is a bare Series (single-symbol case), map it to symbols[0].
    """
    is_single = (len(symbols) == 1 and symbols[0] == "DEFAULT")
    out: Dict[str, pd.Series] = {}

    for sym in symbols:
        if isinstance(data, dict):
            s = data.get(sym)
        elif is_single:
            s = data
        else:
            s = None

        if s is None:
            if fallback is not None:
                out[sym] = fallback[sym]
            else:
                out[sym] = pd.Series(fill_val, index=idx)
            continue

        if not isinstance(s, pd.Series):
            s = pd.Series(s, index=idx)
        else:
            # ensure UTC
            if isinstance(s.index, pd.DatetimeIndex):
                if s.index.tz is None:
                    s.index = s.index.tz_localize("UTC")
                else:
                    s.index = s.index.tz_convert("UTC")
            s = s[~s.index.duplicated(keep="first")]
            s = s.reindex(idx, method="ffill")

        out[sym] = s

    return out


def prepare_funding(
    fr_input: Union[float, int, pd.Series, Dict],
    symbols: list,
    idx: pd.DatetimeIndex,
) -> Dict[str, pd.Series]:
    """Build per-symbol funding-rate series aligned to idx."""
    out: Dict[str, pd.Series] = {}
    for sym in symbols:
        if isinstance(fr_input, dict):
            if sym not in fr_input:
                raise KeyError(
                    f"funding_rate dict is missing symbol {sym!r}; pass 0.0 explicitly "
                    "or set use_funding=False to avoid synthetic funding defaults"
                )
            val = fr_input[sym]
        elif isinstance(fr_input, pd.Series):
            val = fr_input
        else:
            val = fr_input

        if isinstance(val, (float, int)):
            out[sym] = pd.Series(float(val), index=idx)
        else:
            if isinstance(val.index, pd.DatetimeIndex):
                if val.index.tz is None:
                    val.index = val.index.tz_localize("UTC")
                else:
                    val.index = val.index.tz_convert("UTC")
            out[sym] = val.reindex(idx, method="ffill").fillna(0.0)

    return out


def make_funding_mask(idx: pd.DatetimeIndex) -> np.ndarray:
    """
    Boolean mask: True on the FIRST bar that enters each funding window.
    Windows are [00:00, 08:00, 16:00) UTC.  Works for any bar frequency.

    Compared to np.isin(hour, [0,8,16]) this fires exactly once per window
    instead of once per bar within the hour.
    """
    hours = idx.hour.to_numpy()
    mask  = np.zeros(len(idx), dtype=np.bool_)
    funding_hours = {0, 8, 16}
    for i in range(1, len(idx)):
        if hours[i] in funding_hours and hours[i] != hours[i - 1]:
            mask[i] = True
    return mask


def build_arrays(
    symbols:       list,
    idx:           pd.DatetimeIndex,
    closes_dict:   Dict[str, pd.Series],
    highs_dict:    Dict[str, pd.Series],
    lows_dict:     Dict[str, pd.Series],
    signals_dict:  Dict[str, pd.Series],
    funding_dict:  Dict[str, pd.Series],
) -> tuple:
    """
    Pack all per-symbol Series into contiguous float64 numpy arrays
    ready for the numba kernels.

    Returns
    -------
    closes, highs, lows, signals, funding  each shape (n_bars, n_syms)
    is_funding_bar                          shape (n_bars,) bool
    """
    market = build_market_arrays(
        symbols=symbols,
        idx=idx,
        closes_dict=closes_dict,
        highs_dict=highs_dict,
        lows_dict=lows_dict,
        funding_dict=funding_dict,
    )
    signals = build_signal_matrix(symbols=symbols, idx=idx, signals_dict=signals_dict)
    return market.closes, market.highs, market.lows, signals, market.funding, market.is_funding_bar


def build_market_arrays(
    symbols:       list,
    idx:           pd.DatetimeIndex,
    closes_dict:   Dict[str, pd.Series],
    highs_dict:    Dict[str, pd.Series],
    lows_dict:     Dict[str, pd.Series],
    funding_dict:  Dict[str, pd.Series],
) -> PreparedMarketArrays:
    """
    Pack immutable market arrays without allocating a dummy signal matrix.

    This is the safe prepared-data object used by event-driven runs and future
    optimizer caches. It stores arrays plus an explicit signature; it does not
    cache results or infer validity from mutable pandas object identity.
    """
    n = len(idx)
    s = len(symbols)
    closes = np.zeros((n, s), dtype=np.float64)
    highs = np.zeros((n, s), dtype=np.float64)
    lows = np.zeros((n, s), dtype=np.float64)
    funding = np.zeros((n, s), dtype=np.float64)

    for k, sym in enumerate(symbols):
        c_ser = closes_dict[sym].fillna(0)
        c     = c_ser.values
        closes[:, k]  = c
        # fillna with close series (same index), then extract values
        highs[:, k]   = highs_dict[sym].fillna(c_ser).values
        lows[:, k]    = lows_dict[sym].fillna(c_ser).values
        funding[:, k] = funding_dict[sym].fillna(0).values

    is_funding_bar = make_funding_mask(idx)
    closes = np.ascontiguousarray(closes, dtype=np.float64)
    highs = np.ascontiguousarray(highs, dtype=np.float64)
    lows = np.ascontiguousarray(lows, dtype=np.float64)
    funding = np.ascontiguousarray(funding, dtype=np.float64)
    is_funding_bar = np.ascontiguousarray(is_funding_bar, dtype=np.bool_)
    for arr in (closes, highs, lows, funding, is_funding_bar):
        arr.setflags(write=False)
    return PreparedMarketArrays(
        idx=idx,
        symbols=tuple(symbols),
        closes=closes,
        highs=highs,
        lows=lows,
        funding=funding,
        is_funding_bar=is_funding_bar,
        signature=market_data_signature(idx, symbols),
    )


def build_signal_matrix(
    symbols: list,
    idx: pd.DatetimeIndex,
    signals_dict: Dict[str, pd.Series],
) -> np.ndarray:
    n = len(idx)
    s = len(symbols)
    signals = np.zeros((n, s), dtype=np.float64)
    for k, sym in enumerate(symbols):
        signals[:, k] = signals_dict[sym].fillna(0).values
    return np.ascontiguousarray(signals, dtype=np.float64)


def market_data_signature(idx: pd.DatetimeIndex, symbols: list) -> MarketDataSignature:
    if len(idx) == 0:
        first = None
        last = None
    else:
        values = idx.view("int64")
        first = int(values[0])
        last = int(values[-1])
    return MarketDataSignature(
        length=int(len(idx)),
        first_timestamp_ns=first,
        last_timestamp_ns=last,
        symbols=tuple(symbols),
        shape=(int(len(idx)), int(len(symbols))),
    )
