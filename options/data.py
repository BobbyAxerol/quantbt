"""
Canonical option chain data validation.

The canonical chain is long-form. Phase 1 validates structure only; Phase 3
will compile this data into a ragged/CSR option tape.
"""

from __future__ import annotations

from typing import Iterable, Optional, Sequence

import numpy as np
import pandas as pd


CANONICAL_OPTION_CHAIN_COLUMNS = (
    "timestamp_ns",
    "instrument_id",
    "venue",
    "underlying_id",
    "expiry_ns",
    "strike",
    "option_kind",
    "bid_price",
    "bid_size",
    "ask_price",
    "ask_size",
    "mark_price",
    "last_price",
    "index_price",
    "forward_price",
    "mark_iv",
    "bid_iv",
    "ask_iv",
    "delta",
    "gamma",
    "vega",
    "theta",
    "open_interest",
    "volume",
    "quote_currency",
    "settlement_currency",
    "sequence_id",
    "source_latency_ns",
)

REQUIRED_OPTION_CHAIN_COLUMNS = (
    "timestamp_ns",
    "instrument_id",
    "venue",
    "underlying_id",
    "expiry_ns",
    "strike",
    "option_kind",
    "bid_price",
    "bid_size",
    "ask_price",
    "ask_size",
    "mark_price",
    "index_price",
    "forward_price",
    "quote_currency",
    "settlement_currency",
)


def validate_option_chain_frame(
    frame: pd.DataFrame,
    *,
    required_columns: Sequence[str] = REQUIRED_OPTION_CHAIN_COLUMNS,
    max_spread_bps: Optional[float] = None,
    reject_crossed: bool = True,
) -> pd.DataFrame:
    """
    Validate and return a sorted canonical long-form option chain copy.

    This function intentionally avoids filling missing market values. Missing
    fields must remain visible to later tape compilation and no-lookahead tests.
    """
    if not isinstance(frame, pd.DataFrame):
        raise TypeError("option chain must be a pandas DataFrame")
    missing = [column for column in required_columns if column not in frame.columns]
    if missing:
        raise ValueError(f"option chain missing required columns: {missing}")
    out = frame.copy()
    _coerce_int64(out, ("timestamp_ns", "expiry_ns", "sequence_id", "source_latency_ns"), required=set(required_columns))
    _coerce_float(
        out,
        (
            "strike",
            "bid_price",
            "bid_size",
            "ask_price",
            "ask_size",
            "mark_price",
            "last_price",
            "index_price",
            "forward_price",
            "mark_iv",
            "bid_iv",
            "ask_iv",
            "delta",
            "gamma",
            "vega",
            "theta",
            "open_interest",
            "volume",
        ),
    )
    _normalize_strings(out, ("instrument_id", "underlying_id", "quote_currency", "settlement_currency"))
    out["venue"] = out["venue"].astype(str).str.strip().str.lower()
    out["option_kind"] = out["option_kind"].astype(str).str.strip().str.lower()
    _validate_positive(out, ("timestamp_ns", "expiry_ns", "strike", "index_price", "forward_price"))
    _validate_non_negative(out, ("bid_price", "bid_size", "ask_price", "ask_size", "mark_price"))
    if reject_crossed and bool((out["bid_price"] > out["ask_price"]).any()):
        raise ValueError("option chain contains crossed quotes: bid_price > ask_price")
    if bool((out["bid_price"] <= 0.0).any()):
        raise ValueError("option chain requires bid_price > 0 in Phase 1 canonical validation")
    if bool((out["ask_price"] <= 0.0).any()):
        raise ValueError("option chain requires ask_price > 0 in Phase 1 canonical validation")
    if max_spread_bps is not None:
        if max_spread_bps < 0.0:
            raise ValueError("max_spread_bps must be >= 0")
        mid = 0.5 * (out["bid_price"].to_numpy() + out["ask_price"].to_numpy())
        spread_bps = np.divide(
            out["ask_price"].to_numpy() - out["bid_price"].to_numpy(),
            mid,
            out=np.full(len(out), np.inf, dtype=np.float64),
            where=mid > 0.0,
        ) * 10_000.0
        if bool((spread_bps > float(max_spread_bps)).any()):
            raise ValueError("option chain contains quotes wider than max_spread_bps")
    if bool((out["expiry_ns"] <= out["timestamp_ns"]).any()):
        raise ValueError("option chain contains expired quotes")
    if not set(out["option_kind"].unique()).issubset({"call", "put"}):
        raise ValueError("option_kind must be call or put")
    out = out.sort_values(["timestamp_ns", "sequence_id", "instrument_id"] if "sequence_id" in out else ["timestamp_ns", "instrument_id"])
    out = out.reset_index(drop=True)
    if bool(out.duplicated(subset=[column for column in ("timestamp_ns", "instrument_id", "sequence_id") if column in out]).any()):
        raise ValueError("option chain contains duplicate timestamp/instrument/sequence rows")
    return out


def _coerce_int64(frame: pd.DataFrame, columns: Iterable[str], *, required: set[str]) -> None:
    for column in columns:
        if column not in frame:
            if column in required:
                raise ValueError(f"missing required integer column {column!r}")
            continue
        frame[column] = pd.to_numeric(frame[column], errors="raise").astype("int64")


def _coerce_float(frame: pd.DataFrame, columns: Iterable[str]) -> None:
    for column in columns:
        if column in frame:
            frame[column] = pd.to_numeric(frame[column], errors="raise").astype("float64")


def _normalize_strings(frame: pd.DataFrame, columns: Iterable[str]) -> None:
    for column in columns:
        if column in frame:
            frame[column] = frame[column].astype(str).str.strip()
    for column in ("quote_currency", "settlement_currency"):
        if column in frame:
            frame[column] = frame[column].str.upper()


def _validate_positive(frame: pd.DataFrame, columns: Iterable[str]) -> None:
    for column in columns:
        if column in frame and bool((frame[column] <= 0).any()):
            raise ValueError(f"{column} must be > 0")


def _validate_non_negative(frame: pd.DataFrame, columns: Iterable[str]) -> None:
    for column in columns:
        if column in frame and bool((frame[column] < 0).any()):
            raise ValueError(f"{column} must be >= 0")
