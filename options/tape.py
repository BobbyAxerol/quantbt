"""
Prepared ragged option tape.

The canonical option chain remains long-form. This module compiles validated
rows into CSR-style arrays so later selectors and execution code can scan the
listed contracts at each observable snapshot without building a dense
bar-by-contract matrix.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from .data import validate_option_chain_frame
from .schema import InstrumentRegistrySignature, OptionInstrumentRegistry


YEAR_NS = 365 * 24 * 60 * 60 * 1_000_000_000


@dataclass(frozen=True)
class OptionTapeSignature:
    row_count: int
    snapshot_count: int
    first_timestamp_ns: int
    last_timestamp_ns: int
    instrument_registry_signature: InstrumentRegistrySignature
    convention_signature: Tuple


@dataclass(frozen=True)
class PreparedOptionTape:
    timestamp_ns: np.ndarray
    row_ptr: np.ndarray
    instrument_code: np.ndarray
    instrument_id: Tuple[str, ...]
    expiry_ns: np.ndarray
    strike: np.ndarray
    option_kind_code: np.ndarray
    bid_price: np.ndarray
    bid_size: np.ndarray
    ask_price: np.ndarray
    ask_size: np.ndarray
    mark_price: np.ndarray
    index_price: np.ndarray
    forward_price: np.ndarray
    mark_iv: np.ndarray
    bid_iv: np.ndarray
    ask_iv: np.ndarray
    delta: np.ndarray
    gamma: np.ndarray
    vega: np.ndarray
    theta: np.ndarray
    open_interest: np.ndarray
    volume: np.ndarray
    source_latency_ns: np.ndarray
    registry: OptionInstrumentRegistry
    signature: OptionTapeSignature

    def __post_init__(self) -> None:
        if self.timestamp_ns.ndim != 1 or self.row_ptr.ndim != 1:
            raise ValueError("timestamp_ns and row_ptr must be 1-D")
        if len(self.row_ptr) != len(self.timestamp_ns) + 1:
            raise ValueError("row_ptr length must equal snapshot_count + 1")
        if len(self.instrument_code) != self.signature.row_count:
            raise ValueError("instrument_code length must match row_count")
        if self.row_ptr[0] != 0 or self.row_ptr[-1] != self.signature.row_count:
            raise ValueError("row_ptr bounds do not match row_count")
        if bool((np.diff(self.row_ptr) < 0).any()):
            raise ValueError("row_ptr must be non-decreasing")
        if bool((np.diff(self.timestamp_ns) <= 0).any()):
            raise ValueError("timestamp_ns must be strictly increasing")

    @property
    def snapshot_count(self) -> int:
        return len(self.timestamp_ns)

    @property
    def row_count(self) -> int:
        return len(self.instrument_code)

    def snapshot_index_at_or_before(self, decision_timestamp_ns: int, *, max_quote_age_ns: Optional[int] = None) -> int:
        decision_ts = int(decision_timestamp_ns)
        idx = int(np.searchsorted(self.timestamp_ns, decision_ts, side="right") - 1)
        if idx < 0:
            raise ValueError("no option snapshot is observable at or before decision_timestamp_ns")
        if max_quote_age_ns is not None and decision_ts - int(self.timestamp_ns[idx]) > int(max_quote_age_ns):
            raise ValueError("latest option snapshot is stale for decision_timestamp_ns")
        return idx

    def snapshot_slice(self, snapshot_index: int) -> slice:
        idx = int(snapshot_index)
        if idx < 0 or idx >= self.snapshot_count:
            raise IndexError("snapshot_index out of range")
        return slice(int(self.row_ptr[idx]), int(self.row_ptr[idx + 1]))

    def validate_compatible(
        self,
        *,
        registry_signature: Optional[InstrumentRegistrySignature] = None,
        convention_signature: Optional[Tuple] = None,
        timestamps_ns: Optional[Sequence[int]] = None,
    ) -> None:
        if registry_signature is not None and registry_signature != self.signature.instrument_registry_signature:
            raise ValueError("prepared option tape registry signature mismatch")
        if convention_signature is not None and tuple(convention_signature) != self.signature.convention_signature:
            raise ValueError("prepared option tape convention signature mismatch")
        if timestamps_ns is not None:
            expected = np.asarray(timestamps_ns, dtype=np.int64)
            if len(expected) != len(self.timestamp_ns) or bool((expected != self.timestamp_ns).any()):
                raise ValueError("prepared option tape timestamp mismatch")


def prepare_option_tape(
    chain: pd.DataFrame,
    registry: OptionInstrumentRegistry,
    *,
    max_spread_bps: Optional[float] = None,
    max_source_latency_ns: Optional[int] = None,
    convention_signature: Optional[Tuple] = None,
) -> PreparedOptionTape:
    """
    Validate long-form chain rows and compile a CSR-style option tape.

    `max_source_latency_ns` checks the per-row venue/source latency column when
    present. Decision-time quote age is checked later by selectors because it
    depends on the strategy timestamp.
    """
    canonical = validate_option_chain_frame(chain, max_spread_bps=max_spread_bps)
    registry_symbols = registry.by_symbol
    unknown = sorted(set(canonical["instrument_id"]).difference(registry_symbols))
    if unknown:
        raise ValueError(f"option chain contains instruments not in registry: {unknown}")
    if max_source_latency_ns is not None:
        if max_source_latency_ns < 0:
            raise ValueError("max_source_latency_ns must be >= 0")
        if "source_latency_ns" not in canonical:
            raise ValueError("source_latency_ns is required when max_source_latency_ns is set")
        if bool((canonical["source_latency_ns"].to_numpy(dtype=np.int64) > int(max_source_latency_ns)).any()):
            raise ValueError("option chain contains stale source latency rows")
    _validate_registry_static_fields(canonical, registry)
    timestamps, row_ptr = _build_row_ptr(canonical["timestamp_ns"].to_numpy(dtype=np.int64))
    ids = tuple(canonical["instrument_id"].astype(str).tolist())
    code_map = {symbol: code for code, symbol in enumerate(registry.symbols)}
    instrument_code = np.asarray([code_map[symbol] for symbol in ids], dtype=np.int32)
    kind_code = np.asarray([0 if kind == "call" else 1 for kind in canonical["option_kind"].astype(str)], dtype=np.int8)
    convention_sig = tuple(convention_signature) if convention_signature is not None else registry.signature.signature
    signature = OptionTapeSignature(
        row_count=len(canonical),
        snapshot_count=len(timestamps),
        first_timestamp_ns=int(timestamps[0]),
        last_timestamp_ns=int(timestamps[-1]),
        instrument_registry_signature=registry.signature,
        convention_signature=convention_sig,
    )
    return PreparedOptionTape(
        timestamp_ns=timestamps,
        row_ptr=row_ptr,
        instrument_code=instrument_code,
        instrument_id=ids,
        expiry_ns=canonical["expiry_ns"].to_numpy(dtype=np.int64),
        strike=canonical["strike"].to_numpy(dtype=np.float64),
        option_kind_code=kind_code,
        bid_price=canonical["bid_price"].to_numpy(dtype=np.float64),
        bid_size=canonical["bid_size"].to_numpy(dtype=np.float64),
        ask_price=canonical["ask_price"].to_numpy(dtype=np.float64),
        ask_size=canonical["ask_size"].to_numpy(dtype=np.float64),
        mark_price=canonical["mark_price"].to_numpy(dtype=np.float64),
        index_price=canonical["index_price"].to_numpy(dtype=np.float64),
        forward_price=canonical["forward_price"].to_numpy(dtype=np.float64),
        mark_iv=_float_column(canonical, "mark_iv", default=np.nan),
        bid_iv=_float_column(canonical, "bid_iv", default=np.nan),
        ask_iv=_float_column(canonical, "ask_iv", default=np.nan),
        delta=_float_column(canonical, "delta", default=np.nan),
        gamma=_float_column(canonical, "gamma", default=np.nan),
        vega=_float_column(canonical, "vega", default=np.nan),
        theta=_float_column(canonical, "theta", default=np.nan),
        open_interest=_float_column(canonical, "open_interest", default=0.0),
        volume=_float_column(canonical, "volume", default=0.0),
        source_latency_ns=_int_column(canonical, "source_latency_ns", default=0),
        registry=registry,
        signature=signature,
    )


def _build_row_ptr(timestamp_ns: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    timestamps, counts = np.unique(timestamp_ns, return_counts=True)
    row_ptr = np.empty(len(timestamps) + 1, dtype=np.int64)
    row_ptr[0] = 0
    row_ptr[1:] = np.cumsum(counts, dtype=np.int64)
    return timestamps.astype(np.int64), row_ptr


def _float_column(frame: pd.DataFrame, column: str, *, default: float) -> np.ndarray:
    if column not in frame:
        return np.full(len(frame), default, dtype=np.float64)
    return frame[column].to_numpy(dtype=np.float64)


def _int_column(frame: pd.DataFrame, column: str, *, default: int) -> np.ndarray:
    if column not in frame:
        return np.full(len(frame), default, dtype=np.int64)
    return frame[column].to_numpy(dtype=np.int64)


def _validate_registry_static_fields(chain: pd.DataFrame, registry: OptionInstrumentRegistry) -> None:
    for row in chain.itertuples(index=False):
        spec = registry.by_symbol[getattr(row, "instrument_id")]
        if int(getattr(row, "expiry_ns")) != int(spec.expiry_ns):
            raise ValueError("option chain expiry_ns does not match registry")
        if abs(float(getattr(row, "strike")) - float(spec.strike)) > 1e-12:
            raise ValueError("option chain strike does not match registry")
        if str(getattr(row, "option_kind")).lower() != spec.option_kind.value:
            raise ValueError("option chain option_kind does not match registry")
        if str(getattr(row, "venue")).lower() != spec.venue:
            raise ValueError("option chain venue does not match registry")
        if str(getattr(row, "underlying_id")).strip() != spec.underlying_id:
            raise ValueError("option chain underlying_id does not match registry")
        if str(getattr(row, "quote_currency")).upper() != spec.quote_currency:
            raise ValueError("option chain quote_currency does not match registry")
        if str(getattr(row, "settlement_currency")).upper() != spec.settlement_currency:
            raise ValueError("option chain settlement_currency does not match registry")
