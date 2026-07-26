"""
Strict market tape preparation for execution-certified engines.

This module intentionally does not reuse the compatibility preprocessor. The
existing preprocessor is permissive for legacy notebooks; Phase 31 engines need
explicit validation and a certificate before kernels run.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from typing import Dict, Optional, Sequence, Union

import numpy as np
import pandas as pd


SeriesMap = Dict[str, pd.Series]
FrameMap = Dict[str, pd.DataFrame]


@dataclass(frozen=True)
class MarketValidationCertificate:
    signature: str
    row_count: int
    symbol_count: int
    timezone: str
    first_timestamp_ns: int
    last_timestamp_ns: int
    finite_ok: bool
    ohlc_ok: bool
    monotonic_ok: bool
    unique_ok: bool
    alignment_ok: bool
    validator_version: str = "market_tape_v1"


@dataclass(frozen=True)
class PreparedMarketTape:
    timestamps_ns: np.ndarray
    symbols: tuple[str, ...]
    opens: np.ndarray
    highs: np.ndarray
    lows: np.ndarray
    closes: np.ndarray
    volumes: np.ndarray
    funding_rates: np.ndarray
    funding_event_mask: np.ndarray
    signature: str
    validation_certificate: MarketValidationCertificate

    @property
    def n_bars(self) -> int:
        return int(self.opens.shape[0])

    @property
    def n_symbols(self) -> int:
        return int(self.opens.shape[1])


def prepare_market_tape(
    *,
    data: Optional[Union[pd.DataFrame, FrameMap]] = None,
    opens: Optional[Union[pd.Series, SeriesMap]] = None,
    highs: Optional[Union[pd.Series, SeriesMap]] = None,
    lows: Optional[Union[pd.Series, SeriesMap]] = None,
    closes: Optional[Union[pd.Series, SeriesMap]] = None,
    volumes: Optional[Union[pd.Series, SeriesMap]] = None,
    datetime_index: Optional[pd.DatetimeIndex] = None,
    symbols: Optional[Sequence[str]] = None,
    funding_rate: Union[float, pd.Series, Dict[str, Union[float, pd.Series]]] = 0.0,
    use_funding: bool = True,
    validation_mode: str = "strict",
) -> PreparedMarketTape:
    """
    Build a strict, immutable OHLCV/funding tape.

    `validation_mode="strict"` rejects unsorted, duplicate, missing, NaN, and
    invalid OHLC data. It does not forward-fill or fallback high/low to close.
    """
    mode = str(validation_mode).lower().strip()
    if mode not in {"strict", "trusted_prepared", "debug"}:
        raise ValueError("validation_mode must be strict, trusted_prepared, or debug")
    if isinstance(data, PreparedMarketTape):
        return data

    frames, symbol_list = _frames_from_inputs(
        data=data,
        opens=opens,
        highs=highs,
        lows=lows,
        closes=closes,
        volumes=volumes,
        datetime_index=datetime_index,
        symbols=symbols,
    )
    if not symbol_list:
        raise ValueError("at least one symbol is required")
    idx = frames[symbol_list[0]].index
    _validate_index(idx, name=symbol_list[0])
    for symbol in symbol_list[1:]:
        if not frames[symbol].index.equals(idx):
            raise ValueError(f"symbol {symbol!r} index is not aligned to {symbol_list[0]!r}")

    n = len(idx)
    m = len(symbol_list)
    opens_m = np.empty((n, m), dtype=np.float64)
    highs_m = np.empty((n, m), dtype=np.float64)
    lows_m = np.empty((n, m), dtype=np.float64)
    closes_m = np.empty((n, m), dtype=np.float64)
    volumes_m = np.empty((n, m), dtype=np.float64)
    for j, symbol in enumerate(symbol_list):
        frame = frames[symbol]
        _validate_ohlcv_frame(frame, symbol)
        opens_m[:, j] = frame["open"].to_numpy(dtype=np.float64)
        highs_m[:, j] = frame["high"].to_numpy(dtype=np.float64)
        lows_m[:, j] = frame["low"].to_numpy(dtype=np.float64)
        closes_m[:, j] = frame["close"].to_numpy(dtype=np.float64)
        volumes_m[:, j] = frame["volume"].to_numpy(dtype=np.float64)

    ohlcv = np.stack((opens_m, highs_m, lows_m, closes_m, volumes_m), axis=2)
    finite_ok = bool(np.isfinite(ohlcv).all())
    if not finite_ok:
        raise ValueError("OHLCV contains NaN or infinite values")
    ohlc_ok = bool(
        (
            (lows_m <= opens_m)
            & (lows_m <= closes_m)
            & (highs_m >= opens_m)
            & (highs_m >= closes_m)
            & (highs_m >= lows_m)
            & (opens_m > 0.0)
            & (highs_m > 0.0)
            & (lows_m > 0.0)
            & (closes_m > 0.0)
            & (volumes_m >= 0.0)
        ).all()
    )
    if not ohlc_ok:
        raise ValueError("invalid OHLCV invariant")

    timestamps_ns = idx.view("int64").astype(np.int64, copy=True)
    funding_m, funding_mask = _prepare_funding_matrix(
        funding_rate=funding_rate,
        use_funding=use_funding,
        symbols=symbol_list,
        idx=idx,
    )
    signature = _signature(timestamps_ns, symbol_list, opens_m, highs_m, lows_m, closes_m)
    cert = MarketValidationCertificate(
        signature=signature,
        row_count=int(n),
        symbol_count=int(m),
        timezone=str(idx.tz),
        first_timestamp_ns=int(timestamps_ns[0]),
        last_timestamp_ns=int(timestamps_ns[-1]),
        finite_ok=finite_ok,
        ohlc_ok=ohlc_ok,
        monotonic_ok=True,
        unique_ok=True,
        alignment_ok=True,
    )
    arrays = (timestamps_ns, opens_m, highs_m, lows_m, closes_m, volumes_m, funding_m, funding_mask)
    for arr in arrays:
        arr.setflags(write=False)
    return PreparedMarketTape(
        timestamps_ns=np.ascontiguousarray(timestamps_ns),
        symbols=tuple(symbol_list),
        opens=np.ascontiguousarray(opens_m),
        highs=np.ascontiguousarray(highs_m),
        lows=np.ascontiguousarray(lows_m),
        closes=np.ascontiguousarray(closes_m),
        volumes=np.ascontiguousarray(volumes_m),
        funding_rates=np.ascontiguousarray(funding_m),
        funding_event_mask=np.ascontiguousarray(funding_mask),
        signature=signature,
        validation_certificate=cert,
    )


def _frames_from_inputs(
    *,
    data,
    opens,
    highs,
    lows,
    closes,
    volumes,
    datetime_index,
    symbols,
) -> tuple[FrameMap, list[str]]:
    if data is not None:
        if isinstance(data, pd.DataFrame):
            symbol_list = list(symbols or ["DEFAULT"])
            if len(symbol_list) != 1:
                raise ValueError("single DataFrame market tape requires one symbol")
            return {symbol_list[0]: _standard_frame(data, datetime_index)}, symbol_list
        symbol_list = list(symbols or data.keys())
        return {symbol: _standard_frame(data[symbol], datetime_index=None) for symbol in symbol_list}, symbol_list

    if closes is None:
        raise ValueError("closes or data is required")
    if isinstance(closes, pd.Series):
        symbol_list = list(symbols or ["DEFAULT"])
        if len(symbol_list) != 1:
            raise ValueError("single Series market tape requires one symbol")
        symbol = symbol_list[0]
        idx = _strict_index(datetime_index if datetime_index is not None else closes.index, name=symbol)
        frame = pd.DataFrame(
            {
                "open": _series_for_symbol(opens, symbol, idx, required=True),
                "high": _series_for_symbol(highs, symbol, idx, required=True),
                "low": _series_for_symbol(lows, symbol, idx, required=True),
                "close": _align_exact(closes, idx, "close"),
                "volume": _series_for_symbol(volumes, symbol, idx, required=False),
            },
            index=idx,
        )
        return {symbol: frame}, symbol_list

    symbol_list = list(symbols or closes.keys())
    idx = _strict_index(datetime_index if datetime_index is not None else closes[symbol_list[0]].index, name=symbol_list[0])
    frames = {}
    for symbol in symbol_list:
        frames[symbol] = pd.DataFrame(
            {
                "open": _series_for_symbol(opens, symbol, idx, required=True),
                "high": _series_for_symbol(highs, symbol, idx, required=True),
                "low": _series_for_symbol(lows, symbol, idx, required=True),
                "close": _align_exact(closes[symbol], idx, "close"),
                "volume": _series_for_symbol(volumes, symbol, idx, required=False),
            },
            index=idx,
        )
    return frames, symbol_list


def _standard_frame(data: pd.DataFrame, datetime_index=None) -> pd.DataFrame:
    frame = data.copy().rename(
        columns={
            "Datetime": "timestamp",
            "Date": "timestamp",
            "Timestamp": "timestamp",
            "Open": "open",
            "High": "high",
            "Low": "low",
            "Close": "close",
            "Volume": "volume",
        }
    )
    if datetime_index is not None:
        frame.index = _strict_index(datetime_index, name="datetime_index")
    elif "timestamp" in frame.columns:
        frame = frame.set_index(pd.to_datetime(frame["timestamp"], errors="raise", utc=True))
    else:
        frame.index = _strict_index(frame.index, name="data")
    required = {"open", "high", "low", "close"}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"market data is missing required columns {missing}")
    if "volume" not in frame.columns:
        frame["volume"] = 0.0
    frame = frame[["open", "high", "low", "close", "volume"]].copy()
    frame.index = _strict_index(frame.index, name="data")
    return frame


def _strict_index(value, *, name: str) -> pd.DatetimeIndex:
    idx = pd.DatetimeIndex(pd.to_datetime(value, errors="raise", utc=True))
    _validate_index(idx, name=name)
    return idx


def _validate_index(idx: pd.DatetimeIndex, *, name: str) -> None:
    if len(idx) == 0:
        raise ValueError(f"{name} index is empty")
    values = idx.view("int64")
    if not bool(np.all(values[1:] > values[:-1])):
        if bool(pd.Index(values).duplicated().any()):
            raise ValueError(f"{name} index contains duplicate timestamps")
        raise ValueError(f"{name} index must be strictly increasing")
    if idx.tz is None:
        raise ValueError(f"{name} index must be timezone-aware")


def _validate_ohlcv_frame(frame: pd.DataFrame, symbol: str) -> None:
    if len(frame) == 0:
        raise ValueError(f"{symbol} market data is empty")
    missing = [col for col in ("open", "high", "low", "close", "volume") if col not in frame]
    if missing:
        raise ValueError(f"{symbol} market data is missing columns {missing}")


def _series_for_symbol(data, symbol: str, idx: pd.DatetimeIndex, *, required: bool) -> pd.Series:
    if data is None:
        if required:
            raise ValueError(f"{symbol} requires explicit open/high/low/close for strict market tape")
        return pd.Series(0.0, index=idx, name="volume")
    if isinstance(data, pd.Series):
        series = data
    else:
        if symbol not in data:
            if required:
                raise KeyError(f"{symbol!r} missing from strict market tape input")
            return pd.Series(0.0, index=idx, name="volume")
        series = data[symbol]
    return _align_exact(series, idx, symbol)


def _align_exact(series: pd.Series, idx: pd.DatetimeIndex, name: str) -> pd.Series:
    s = series.copy()
    s.index = _strict_index(s.index, name=name)
    if not s.index.equals(idx):
        raise ValueError(f"{name} series index is not exactly aligned")
    return pd.to_numeric(s, errors="raise").astype(float)


def _prepare_funding_matrix(
    *,
    funding_rate,
    use_funding: bool,
    symbols: list[str],
    idx: pd.DatetimeIndex,
) -> tuple[np.ndarray, np.ndarray]:
    n = len(idx)
    m = len(symbols)
    funding = np.zeros((n, m), dtype=np.float64)
    mask = np.zeros(n, dtype=np.bool_)
    if not use_funding:
        return funding, mask
    if isinstance(funding_rate, dict):
        for j, symbol in enumerate(symbols):
            if symbol not in funding_rate:
                raise KeyError(f"funding_rate dict is missing symbol {symbol!r}")
            value = funding_rate[symbol]
            if isinstance(value, pd.Series):
                funding[:, j] = _align_exact(value, idx, f"funding:{symbol}").to_numpy(dtype=np.float64)
            else:
                funding[:, j] = float(value)
    elif isinstance(funding_rate, pd.Series):
        series = _align_exact(funding_rate, idx, "funding")
        funding[:, :] = series.to_numpy(dtype=np.float64)[:, None]
    else:
        funding[:, :] = float(funding_rate)
    mask[1:] = funding[1:].any(axis=1)
    return funding, mask


def _signature(timestamps_ns: np.ndarray, symbols: list[str], *arrays: np.ndarray) -> str:
    h = hashlib.sha256()
    h.update(np.ascontiguousarray(timestamps_ns).view(np.uint8))
    h.update("|".join(symbols).encode("utf-8"))
    for arr in arrays:
        h.update(np.ascontiguousarray(arr).view(np.uint8))
    return h.hexdigest()
