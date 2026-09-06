"""Canonical multi-symbol market calendars for the V1.1 certified routes.

The legacy preprocessor intentionally remains permissive for historical
notebooks.  This module is the separate, fail-closed preparation boundary for
routes that claim calendar certification: it never aligns a tape by row count
and it never manufactures an OHLC observation with ``fillna``.
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field
from enum import Enum
from hashlib import sha256
import json
from typing import Mapping, Optional, Sequence

import numpy as np
import pandas as pd


MARKET_CALENDAR_V2_SCHEMA = "market-calendar-v2"


class CalendarPolicyV2(str, Enum):
    """How source symbol calendars become the simulation clock."""

    EXACT = "exact"
    INTERSECTION = "intersection"
    UNION = "union"
    PRIMARY_CLOCK = "primary_clock"


class MissingObservationPolicyV1(str, Enum):
    """Explicit treatment of a missing source observation.

    Raw OHLCV arrays always retain ``NaN`` for a missing bar.  The policy only
    controls the separate mark/stale/tradable projections, so no execution
    path can mistake an inherited mark for a venue observation.
    """

    NO_OBSERVATION = "no_observation"
    MARK_TO_LAST_NO_EXECUTION = "mark_to_last_no_execution"
    FORWARD_FILL_QUOTE_NO_VOLUME = "forward_fill_quote_no_volume"
    REJECT_INTENT = "reject_intent"


def _readonly(values, dtype) -> np.ndarray:
    array = np.ascontiguousarray(values, dtype=dtype)
    array.setflags(write=False)
    return array


def _utc_index(index, *, symbol: str) -> pd.DatetimeIndex:
    if not isinstance(index, pd.DatetimeIndex):
        index = pd.DatetimeIndex(pd.to_datetime(index, utc=True, errors="raise"))
    elif index.tz is None:
        index = index.tz_localize("UTC")
    else:
        index = index.tz_convert("UTC")
    if len(index) == 0:
        raise ValueError(f"market calendar for {symbol!r} is empty")
    if index.has_duplicates:
        duplicate = index[index.duplicated()][0]
        raise ValueError(f"market calendar for {symbol!r} has duplicate timestamp {duplicate.isoformat()}")
    if not index.is_monotonic_increasing:
        raise ValueError(f"market calendar for {symbol!r} must be strictly increasing")
    return index


def _first_exact_divergence(reference: pd.DatetimeIndex, candidate: pd.DatetimeIndex) -> tuple[int, object, object]:
    shared = min(len(reference), len(candidate))
    for row in range(shared):
        if reference[row] != candidate[row]:
            return row, reference[row], candidate[row]
    if len(reference) != len(candidate):
        row = shared
        return (
            row,
            reference[row] if row < len(reference) else "<end>",
            candidate[row] if row < len(candidate) else "<end>",
        )
    return -1, None, None


def _as_policy(value: CalendarPolicyV2 | str) -> CalendarPolicyV2:
    try:
        return value if isinstance(value, CalendarPolicyV2) else CalendarPolicyV2(str(value).lower().strip())
    except ValueError as exc:
        allowed = ", ".join(item.value for item in CalendarPolicyV2)
        raise ValueError(f"calendar_policy must be one of: {allowed}") from exc


def _as_missing_policy(value: MissingObservationPolicyV1 | str) -> MissingObservationPolicyV1:
    try:
        return value if isinstance(value, MissingObservationPolicyV1) else MissingObservationPolicyV1(str(value).lower().strip())
    except ValueError as exc:
        allowed = ", ".join(item.value for item in MissingObservationPolicyV1)
        raise ValueError(f"missing_policy must be one of: {allowed}") from exc


@dataclass(frozen=True, slots=True)
class SymbolCalendarMapV2:
    """Bidirectional mapping from one source symbol to the canonical clock."""

    symbol: str
    canonical_to_local: np.ndarray
    local_to_canonical: np.ndarray
    observed: np.ndarray
    stale: np.ndarray
    tradable: np.ndarray
    dropped_source_rows: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(self, "canonical_to_local", _readonly(self.canonical_to_local, np.int64))
        object.__setattr__(self, "local_to_canonical", _readonly(self.local_to_canonical, np.int64))
        for name in ("observed", "stale", "tradable"):
            object.__setattr__(self, name, _readonly(getattr(self, name), np.bool_))
        n = len(self.canonical_to_local)
        if any(len(getattr(self, name)) != n for name in ("observed", "stale", "tradable")):
            raise ValueError("calendar flags must match canonical_to_local length")
        if np.any(self.canonical_to_local < -1) or np.any(self.local_to_canonical < -1):
            raise ValueError("calendar mappings contain invalid offsets")
        if np.any(self.observed != (self.canonical_to_local >= 0)):
            raise ValueError("observed flags must match canonical_to_local mappings")
        if np.any(self.tradable & ~self.observed):
            raise ValueError("a missing observation cannot be tradable")

    @property
    def n_canonical(self) -> int:
        return int(len(self.canonical_to_local))


@dataclass(frozen=True, slots=True)
class CalendarPlanV2:
    """Immutable canonical market clock and one mapping per normalized symbol."""

    timestamps_ns: np.ndarray
    symbols: tuple[str, ...]
    policy: CalendarPolicyV2
    missing_policy: MissingObservationPolicyV1
    symbol_maps: tuple[SymbolCalendarMapV2, ...]
    primary_symbol: Optional[str]
    fingerprint: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "timestamps_ns", _readonly(self.timestamps_ns, np.int64))
        if len(self.timestamps_ns) == 0:
            raise ValueError("canonical calendar must contain at least one timestamp")
        if np.any(np.diff(self.timestamps_ns) <= 0):
            raise ValueError("canonical timestamps must be strictly increasing")
        if tuple(item.symbol for item in self.symbol_maps) != self.symbols:
            raise ValueError("calendar map symbols must match canonical symbols")
        if any(mapping.n_canonical != len(self.timestamps_ns) for mapping in self.symbol_maps):
            raise ValueError("calendar map lengths must match canonical clock")
        if self.policy is CalendarPolicyV2.PRIMARY_CLOCK and self.primary_symbol not in self.symbols:
            raise ValueError("primary_clock policy requires primary_symbol in symbols")

    @property
    def datetime_index(self) -> pd.DatetimeIndex:
        return pd.to_datetime(self.timestamps_ns, utc=True)

    @property
    def n_bars(self) -> int:
        return int(len(self.timestamps_ns))

    @property
    def n_symbols(self) -> int:
        return int(len(self.symbols))

    def map_for(self, symbol: str) -> SymbolCalendarMapV2:
        try:
            return self.symbol_maps[self.symbols.index(str(symbol))]
        except ValueError as exc:
            raise KeyError(f"calendar does not contain symbol {symbol!r}") from exc

    def metadata(self) -> dict[str, object]:
        return {
            "schema": MARKET_CALENDAR_V2_SCHEMA,
            "policy": self.policy.value,
            "missing_policy": self.missing_policy.value,
            "primary_symbol": self.primary_symbol,
            "symbols": list(self.symbols),
            "bars": self.n_bars,
            "fingerprint": self.fingerprint,
            "dropped_source_rows": {mapping.symbol: int(mapping.dropped_source_rows) for mapping in self.symbol_maps},
        }


@dataclass(frozen=True, slots=True)
class MarketExecutionViewV2:
    """A finite, all-observed projection safe for current legacy/Rust kernels."""

    timestamps_ns: np.ndarray
    symbols: tuple[str, ...]
    opens: np.ndarray
    highs: np.ndarray
    lows: np.ndarray
    closes: np.ndarray
    volumes: np.ndarray
    funding_rates: np.ndarray
    funding_event_mask: np.ndarray
    observed: np.ndarray
    stale: np.ndarray
    tradable: np.ndarray
    market_fingerprint: str


@dataclass(slots=True)
class PreparedMarketHandleV2:
    """An immutable prepared market allocation with explicit lifetime control."""

    calendar: CalendarPlanV2
    opens: np.ndarray
    highs: np.ndarray
    lows: np.ndarray
    closes: np.ndarray
    volumes: np.ndarray
    funding_rates: np.ndarray
    funding_event_mask: np.ndarray
    shared_funding_event_mask: np.ndarray
    observed: np.ndarray
    stale: np.ndarray
    tradable: np.ndarray
    mark_closes: np.ndarray
    fingerprint: str
    source_rows: Mapping[str, int]
    allocation_id: int
    _closed: bool = field(default=False, init=False, repr=False)

    def __post_init__(self) -> None:
        shape = (self.calendar.n_bars, self.calendar.n_symbols)
        for name in ("opens", "highs", "lows", "closes", "volumes", "funding_rates", "mark_closes"):
            values = _readonly(getattr(self, name), np.float64)
            if values.shape != shape:
                raise ValueError(f"{name} shape must be {shape}")
            object.__setattr__(self, name, values)
        for name in ("funding_event_mask", "observed", "stale", "tradable"):
            values = _readonly(getattr(self, name), np.bool_)
            if values.shape != shape:
                raise ValueError(f"{name} shape must be {shape}")
            object.__setattr__(self, name, values)
        shared_mask = _readonly(self.shared_funding_event_mask, np.bool_)
        if shared_mask.shape != (shape[0],):
            raise ValueError("shared_funding_event_mask must have one value per canonical bar")
        object.__setattr__(self, "shared_funding_event_mask", shared_mask)
        if not np.array_equal(self.observed, np.column_stack([item.observed for item in self.calendar.symbol_maps])):
            raise ValueError("prepared observed flags drift from calendar plan")

    @property
    def closed(self) -> bool:
        return bool(self._closed)

    @property
    def nbytes(self) -> int:
        return int(sum(
            getattr(self, name).nbytes
            for name in (
                "opens", "highs", "lows", "closes", "volumes", "funding_rates", "funding_event_mask",
                "shared_funding_event_mask",
                "observed", "stale", "tradable", "mark_closes",
            )
        ) + self.calendar.timestamps_ns.nbytes)

    @property
    def symbols(self) -> tuple[str, ...]:
        return self.calendar.symbols

    @property
    def datetime_index(self) -> pd.DatetimeIndex:
        self.require_open()
        return self.calendar.datetime_index

    def require_open(self) -> None:
        if self._closed:
            raise RuntimeError("PreparedMarketHandleV2 is closed; prepare a new market handle")

    def close(self) -> None:
        """Release this caller's handle. Existing raw references are never reused."""
        self._closed = True

    release = close

    def __enter__(self) -> "PreparedMarketHandleV2":
        self.require_open()
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()

    def execution_view(self) -> MarketExecutionViewV2:
        """Return the zero-copy finite projection supported by current kernels.

        Union/primary-clock data with a missing bar deliberately fail here.
        Passing fabricated prices to a current OHLC kernel would be a domain
        lie; a later missing-data-aware execution phase can lower that contract
        without changing this prepared market representation.
        """
        self.require_open()
        if not bool(np.all(self.observed)):
            raise NotImplementedError(
                "current native execution lowering requires every symbol observation; "
                "use exact/intersection or a future missing-data-aware execution route"
            )
        if not bool(np.isfinite(np.stack((self.opens, self.highs, self.lows, self.closes, self.volumes, self.funding_rates))).all()):
            raise ValueError("all-observed prepared market contains non-finite execution data")
        # V1 execution kernels have one funding schedule per bar.  Per-symbol
        # funding is retained in the handle; nonuniform event timing must not
        # be silently collapsed until the request ABI owns the matrix mask.
        first_mask = self.shared_funding_event_mask
        if not bool(np.all(self.funding_event_mask == first_mask[:, None])):
            raise NotImplementedError(
                "current native execution lowering requires one shared funding event clock; "
                "per-symbol event masks remain preserved on PreparedMarketHandleV2"
            )
        return MarketExecutionViewV2(
            timestamps_ns=self.calendar.timestamps_ns,
            symbols=self.symbols,
            opens=self.opens,
            highs=self.highs,
            lows=self.lows,
            closes=self.closes,
            volumes=self.volumes,
            funding_rates=self.funding_rates,
            funding_event_mask=first_mask,
            observed=self.observed,
            stale=self.stale,
            tradable=self.tradable,
            market_fingerprint=self.fingerprint,
        )

    def metadata(self) -> dict[str, object]:
        self.require_open()
        return {
            **self.calendar.metadata(),
            "prepared_market_handle_v2": True,
            "allocation_id": int(self.allocation_id),
            "nbytes": self.nbytes,
            "source_rows": dict(self.source_rows),
            "all_observed": bool(np.all(self.observed)),
        }


class PreparedMarketCacheV2:
    """Bounded content-addressed handle cache with explicit caller release."""

    def __init__(self, *, max_entries: int = 8, max_bytes: int = 512 * 1024 * 1024) -> None:
        if int(max_entries) <= 0 or int(max_bytes) <= 0:
            raise ValueError("max_entries and max_bytes must be positive")
        self.max_entries = int(max_entries)
        self.max_bytes = int(max_bytes)
        self._entries: OrderedDict[str, PreparedMarketHandleV2] = OrderedDict()
        self._bytes = 0
        self._hits = 0
        self._misses = 0

    def get(self, fingerprint: str) -> Optional[PreparedMarketHandleV2]:
        handle = self._entries.get(str(fingerprint))
        if handle is None or handle.closed:
            self._misses += 1
            return None
        self._entries.move_to_end(str(fingerprint))
        self._hits += 1
        return handle

    def put(self, handle: PreparedMarketHandleV2) -> PreparedMarketHandleV2:
        handle.require_open()
        key = handle.fingerprint
        existing = self._entries.pop(key, None)
        if existing is not None:
            self._bytes -= existing.nbytes
        self._entries[key] = handle
        self._bytes += handle.nbytes
        self._evict()
        return handle

    def release(self, handle_or_fingerprint: PreparedMarketHandleV2 | str) -> None:
        key = handle_or_fingerprint.fingerprint if isinstance(handle_or_fingerprint, PreparedMarketHandleV2) else str(handle_or_fingerprint)
        handle = self._entries.pop(key, None)
        if handle is not None:
            self._bytes -= handle.nbytes
            handle.close()

    def clear(self) -> None:
        for handle in self._entries.values():
            handle.close()
        self._entries.clear()
        self._bytes = 0

    def _evict(self) -> None:
        while self._entries and (len(self._entries) > self.max_entries or self._bytes > self.max_bytes):
            _, handle = self._entries.popitem(last=False)
            self._bytes -= handle.nbytes
            handle.close()

    @property
    def stats(self) -> dict[str, int]:
        return {
            "entries": len(self._entries),
            "bytes": int(self._bytes),
            "hits": int(self._hits),
            "misses": int(self._misses),
        }


_ALLOCATION_SEQUENCE = 0


def prepare_calendar_plan_v2(
    source_indexes: Mapping[str, pd.DatetimeIndex | pd.Series | pd.DataFrame] | pd.DatetimeIndex,
    *,
    calendar_policy: CalendarPolicyV2 | str = CalendarPolicyV2.EXACT,
    missing_policy: MissingObservationPolicyV1 | str = MissingObservationPolicyV1.NO_OBSERVATION,
    primary_symbol: Optional[str] = None,
) -> CalendarPlanV2:
    """Build an immutable calendar plan without requiring OHLCV columns.

    WFO strategy frames commonly contain research features rather than a full
    executable market schema.  They still need the same canonical-clock proof
    as executable market data, so this helper reuses CalendarPlanV2's mapping
    rules without materializing price arrays.  The fingerprint covers every
    source timestamp and map; callers must separately include result-affecting
    values in their data signature.
    """

    policy = _as_policy(calendar_policy)
    missing = _as_missing_policy(missing_policy)
    if isinstance(source_indexes, pd.DatetimeIndex):
        raw = {"DEFAULT": source_indexes}
    elif isinstance(source_indexes, Mapping):
        raw = dict(source_indexes)
    else:
        raise TypeError("source_indexes must be a DatetimeIndex or mapping of indexed objects")
    if not raw:
        raise ValueError("CalendarPlanV2 requires at least one source calendar")
    indexes: dict[str, pd.DatetimeIndex] = {}
    for key, value in raw.items():
        symbol = str(key)
        index = value.index if isinstance(value, (pd.Series, pd.DataFrame)) else value
        indexes[symbol] = _utc_index(pd.DatetimeIndex(index), symbol=symbol)
    symbols = tuple(sorted(indexes))
    primary = str(primary_symbol) if primary_symbol is not None else symbols[0]
    if policy is CalendarPolicyV2.PRIMARY_CLOCK and primary not in indexes:
        raise ValueError("primary_symbol must be present in source_indexes")
    canonical = _canonical_index(indexes, policy=policy, primary_symbol=primary)
    maps = _build_maps(
        indexes,
        canonical,
        policy=policy,
        missing_policy=missing,
        primary_symbol=primary,
    )
    digest = sha256()
    digest.update(MARKET_CALENDAR_V2_SCHEMA.encode())
    digest.update(b"|calendar-only-v1|")
    digest.update(policy.value.encode())
    digest.update(missing.value.encode())
    digest.update((primary if policy is CalendarPolicyV2.PRIMARY_CLOCK else "").encode())
    digest.update(json.dumps(list(symbols), separators=(",", ":")).encode())
    digest.update(np.ascontiguousarray(canonical.view("int64"), dtype=np.int64).tobytes())
    for mapping in maps:
        digest.update(mapping.symbol.encode())
        digest.update(mapping.canonical_to_local.tobytes())
        digest.update(mapping.local_to_canonical.tobytes())
        digest.update(mapping.observed.tobytes())
        digest.update(mapping.stale.tobytes())
        digest.update(mapping.tradable.tobytes())
    return CalendarPlanV2(
        timestamps_ns=canonical.view("int64"),
        symbols=symbols,
        policy=policy,
        missing_policy=missing,
        symbol_maps=maps,
        primary_symbol=primary if policy is CalendarPolicyV2.PRIMARY_CLOCK else None,
        fingerprint=digest.hexdigest(),
    )


def prepare_market_handle_v2(
    data: pd.DataFrame | Mapping[str, pd.DataFrame] | PreparedMarketHandleV2,
    *,
    symbols: Optional[Sequence[str]] = None,
    calendar_policy: CalendarPolicyV2 | str = CalendarPolicyV2.EXACT,
    missing_policy: MissingObservationPolicyV1 | str = MissingObservationPolicyV1.NO_OBSERVATION,
    primary_symbol: Optional[str] = None,
    cutoff_timestamp=None,
    cache: Optional[PreparedMarketCacheV2] = None,
) -> PreparedMarketHandleV2:
    """Prepare a canonical immutable V2 market handle.

    ``data`` is a single OHLCV frame for one symbol or a ``{symbol: frame}``
    mapping.  Symbol mappings are normalized lexicographically so dictionary
    insertion order cannot change a certified result.  Passing a handle simply
    validates that it remains open and compatible with the requested policy.
    """
    policy = _as_policy(calendar_policy)
    missing = _as_missing_policy(missing_policy)
    if isinstance(data, PreparedMarketHandleV2):
        data.require_open()
        if data.calendar.policy is not policy or data.calendar.missing_policy is not missing:
            raise ValueError("prepared market handle calendar policy does not match request")
        if symbols is not None and tuple(sorted(map(str, symbols))) != data.symbols:
            raise ValueError("prepared market handle symbols do not match request")
        return data

    frames = _normalize_frames(data, symbols=symbols, cutoff_timestamp=cutoff_timestamp)
    symbol_values = tuple(sorted(frames))
    source_indexes = {symbol: _utc_index(frame.index, symbol=symbol) for symbol, frame in frames.items()}
    primary = str(primary_symbol) if primary_symbol is not None else symbol_values[0]
    if policy is CalendarPolicyV2.PRIMARY_CLOCK and primary not in source_indexes:
        raise ValueError("primary_symbol must be present in the supplied market data")
    canonical = _canonical_index(source_indexes, policy=policy, primary_symbol=primary)
    maps = _build_maps(source_indexes, canonical, policy=policy, missing_policy=missing, primary_symbol=primary)
    arrays = _materialize_market_arrays(frames, symbol_values, canonical, maps, missing)
    fingerprint = _market_fingerprint(
        canonical=canonical,
        symbols=symbol_values,
        policy=policy,
        missing=missing,
        primary=primary if policy is CalendarPolicyV2.PRIMARY_CLOCK else None,
        mappings=maps,
        arrays=arrays,
    )
    if cache is not None:
        cached = cache.get(fingerprint)
        if cached is not None:
            return cached
    plan = CalendarPlanV2(
        timestamps_ns=canonical.view("int64"),
        symbols=symbol_values,
        policy=policy,
        missing_policy=missing,
        symbol_maps=maps,
        primary_symbol=primary if policy is CalendarPolicyV2.PRIMARY_CLOCK else None,
        fingerprint=fingerprint,
    )
    global _ALLOCATION_SEQUENCE
    _ALLOCATION_SEQUENCE += 1
    handle = PreparedMarketHandleV2(
        calendar=plan,
        **arrays,
        fingerprint=fingerprint,
        source_rows={symbol: int(len(frame)) for symbol, frame in frames.items()},
        allocation_id=_ALLOCATION_SEQUENCE,
    )
    return cache.put(handle) if cache is not None else handle


def _normalize_frames(data, *, symbols, cutoff_timestamp) -> dict[str, pd.DataFrame]:
    if isinstance(data, pd.DataFrame):
        requested = tuple(map(str, symbols or ("DEFAULT",)))
        if len(requested) != 1:
            raise ValueError("a single DataFrame requires exactly one symbol")
        values = {requested[0]: data}
    elif isinstance(data, Mapping):
        values = {str(symbol): frame for symbol, frame in data.items()}
        if not values:
            raise ValueError("market data mapping is empty")
        if symbols is not None and set(map(str, symbols)) != set(values):
            raise ValueError("symbols must match the supplied market-data mapping exactly")
    else:
        raise TypeError("data must be an OHLCV DataFrame or {symbol: DataFrame} mapping")
    cutoff = None if cutoff_timestamp is None else pd.Timestamp(cutoff_timestamp)
    if cutoff is not None:
        cutoff = cutoff.tz_localize("UTC") if cutoff.tzinfo is None else cutoff.tz_convert("UTC")
    out: dict[str, pd.DataFrame] = {}
    for symbol, frame in values.items():
        if not isinstance(frame, pd.DataFrame):
            raise TypeError(f"market data for {symbol!r} must be a DataFrame")
        index = _utc_index(frame.index, symbol=symbol)
        item = frame.copy(deep=False)
        item.index = index
        if cutoff is not None:
            item = item.loc[item.index <= cutoff]
        if len(item) == 0:
            raise ValueError(f"market data for {symbol!r} has no rows at or before cutoff")
        _validate_frame(item, symbol)
        out[symbol] = item
    return out


def _validate_frame(frame: pd.DataFrame, symbol: str) -> None:
    lookup = {str(column).lower(): column for column in frame.columns}
    required = ("open", "high", "low", "close")
    missing = [name for name in required if name not in lookup]
    if missing:
        raise ValueError(f"market data for {symbol!r} is missing required OHLC columns: {missing}")
    ohlc = np.column_stack([pd.to_numeric(frame[lookup[name]], errors="raise").to_numpy(dtype=np.float64) for name in required])
    if not bool(np.isfinite(ohlc).all()):
        raise ValueError(f"market data for {symbol!r} has non-finite observed OHLC")
    opens, highs, lows, closes = ohlc.T
    if not bool(((lows <= opens) & (lows <= closes) & (highs >= opens) & (highs >= closes) & (highs >= lows) & (opens > 0.0) & (highs > 0.0) & (lows > 0.0) & (closes > 0.0)).all()):
        raise ValueError(f"market data for {symbol!r} violates low <= open/close <= high")
    if "volume" in lookup:
        volume = pd.to_numeric(frame[lookup["volume"]], errors="raise").to_numpy(dtype=np.float64)
        if not bool(np.isfinite(volume).all()) or bool((volume < 0.0).any()):
            raise ValueError(f"market data for {symbol!r} has invalid volume")
    for funding_name in ("funding_rate", "funding"):
        if funding_name in lookup:
            funding = pd.to_numeric(frame[lookup[funding_name]], errors="raise").to_numpy(dtype=np.float64)
            if not bool(np.isfinite(funding).all()):
                raise ValueError(f"market data for {symbol!r} has non-finite funding values")
            break


def _canonical_index(source_indexes, *, policy, primary_symbol) -> pd.DatetimeIndex:
    symbols = tuple(sorted(source_indexes))
    reference = source_indexes[symbols[0]]
    if policy is CalendarPolicyV2.EXACT:
        for symbol in symbols[1:]:
            row, expected, actual = _first_exact_divergence(reference, source_indexes[symbol])
            if row >= 0:
                raise ValueError(
                    "CalendarPlanV2 Exact mismatch: "
                    f"symbol {symbol!r} diverges from {symbols[0]!r} at row {row}: "
                    f"{expected} != {actual}"
                )
        return reference
    if policy is CalendarPolicyV2.INTERSECTION:
        values = reference
        for symbol in symbols[1:]:
            values = values.intersection(source_indexes[symbol], sort=False)
        values = values.sort_values()
        if len(values) == 0:
            raise ValueError("CalendarPlanV2 Intersection produced no common timestamps")
        return values
    if policy is CalendarPolicyV2.UNION:
        values = reference
        for symbol in symbols[1:]:
            values = values.union(source_indexes[symbol], sort=False)
        return values.sort_values()
    return source_indexes[primary_symbol]


def _build_maps(source_indexes, canonical, *, policy, missing_policy, primary_symbol) -> tuple[SymbolCalendarMapV2, ...]:
    maps = []
    for symbol in sorted(source_indexes):
        local = source_indexes[symbol]
        canonical_to_local = local.get_indexer(canonical).astype(np.int64, copy=False)
        local_to_canonical = canonical.get_indexer(local).astype(np.int64, copy=False)
        observed = canonical_to_local >= 0
        stale = np.zeros(len(canonical), dtype=np.bool_)
        if missing_policy in {
            MissingObservationPolicyV1.MARK_TO_LAST_NO_EXECUTION,
            MissingObservationPolicyV1.FORWARD_FILL_QUOTE_NO_VOLUME,
        }:
            seen = False
            for row, present in enumerate(observed):
                stale[row] = bool((not present) and seen)
                seen = bool(seen or present)
        # A source observation is tradable.  A stale quote never becomes an
        # executable bar under any V2 missing-data policy.
        tradable = observed.copy()
        maps.append(
            SymbolCalendarMapV2(
                symbol=symbol,
                canonical_to_local=canonical_to_local,
                local_to_canonical=local_to_canonical,
                observed=observed,
                stale=stale,
                tradable=tradable,
                dropped_source_rows=int(len(local) - int(observed.sum())),
            )
        )
    return tuple(maps)


def _materialize_market_arrays(frames, symbols, canonical, maps, missing_policy) -> dict[str, np.ndarray]:
    shape = (len(canonical), len(symbols))
    floats = {name: np.full(shape, np.nan, dtype=np.float64) for name in ("opens", "highs", "lows", "closes", "volumes", "funding_rates")}
    masks = {name: np.zeros(shape, dtype=np.bool_) for name in ("funding_event_mask", "observed", "stale", "tradable")}
    marks = np.full(shape, np.nan, dtype=np.float64)
    for column, (symbol, mapping) in enumerate(zip(symbols, maps)):
        frame = frames[symbol]
        lookup = {str(name).lower(): name for name in frame.columns}
        target_rows = np.flatnonzero(mapping.observed)
        local_rows = mapping.canonical_to_local[target_rows]
        for field, source_name in (("opens", "open"), ("highs", "high"), ("lows", "low"), ("closes", "close")):
            source = pd.to_numeric(frame[lookup[source_name]], errors="raise").to_numpy(dtype=np.float64)
            floats[field][target_rows, column] = source[local_rows]
        volume_source = np.zeros(len(frame), dtype=np.float64) if "volume" not in lookup else pd.to_numeric(frame[lookup["volume"]], errors="raise").to_numpy(dtype=np.float64)
        floats["volumes"][target_rows, column] = volume_source[local_rows]
        funding_name = "funding_rate" if "funding_rate" in lookup else "funding" if "funding" in lookup else None
        funding_source = np.zeros(len(frame), dtype=np.float64) if funding_name is None else pd.to_numeric(frame[lookup[funding_name]], errors="raise").to_numpy(dtype=np.float64)
        floats["funding_rates"][target_rows, column] = funding_source[local_rows]
        event_name = "funding_event_mask" if "funding_event_mask" in lookup else "funding_event" if "funding_event" in lookup else None
        event_source = np.zeros(len(frame), dtype=np.bool_) if event_name is None else frame[lookup[event_name]].astype(bool).to_numpy(dtype=np.bool_)
        masks["funding_event_mask"][target_rows, column] = event_source[local_rows]
        for name in ("observed", "stale", "tradable"):
            masks[name][:, column] = getattr(mapping, name)
        marks[target_rows, column] = floats["closes"][target_rows, column]
        if missing_policy in {
            MissingObservationPolicyV1.MARK_TO_LAST_NO_EXECUTION,
            MissingObservationPolicyV1.FORWARD_FILL_QUOTE_NO_VOLUME,
        }:
            last = np.nan
            for row in range(len(canonical)):
                if mapping.observed[row]:
                    last = marks[row, column]
                elif mapping.stale[row]:
                    marks[row, column] = last
    # Construct the legacy one-clock lowering view once at preparation.  It is
    # intentionally independent from the 2-D event matrix and only usable
    # after ``execution_view`` confirms all symbols share it.
    shared_mask = np.ascontiguousarray(masks["funding_event_mask"][:, 0], dtype=np.bool_)
    return {**floats, **masks, "shared_funding_event_mask": shared_mask, "mark_closes": marks}


def _market_fingerprint(*, canonical, symbols, policy, missing, primary, mappings, arrays) -> str:
    digest = sha256()
    digest.update(MARKET_CALENDAR_V2_SCHEMA.encode())
    digest.update(policy.value.encode())
    digest.update(missing.value.encode())
    digest.update((primary or "").encode())
    digest.update(json.dumps(list(symbols), separators=(",", ":")).encode())
    digest.update(np.ascontiguousarray(canonical.view("int64"), dtype=np.int64).tobytes())
    for mapping in mappings:
        digest.update(mapping.symbol.encode())
        digest.update(mapping.canonical_to_local.tobytes())
        digest.update(mapping.local_to_canonical.tobytes())
        digest.update(mapping.observed.tobytes())
        digest.update(mapping.stale.tobytes())
        digest.update(mapping.tradable.tobytes())
    for name in (
        "opens", "highs", "lows", "closes", "volumes", "funding_rates", "funding_event_mask",
        "shared_funding_event_mask", "mark_closes",
    ):
        digest.update(np.ascontiguousarray(arrays[name]).tobytes())
    return digest.hexdigest()


__all__ = [
    "CalendarPlanV2",
    "CalendarPolicyV2",
    "MARKET_CALENDAR_V2_SCHEMA",
    "MarketExecutionViewV2",
    "MissingObservationPolicyV1",
    "PreparedMarketCacheV2",
    "PreparedMarketHandleV2",
    "SymbolCalendarMapV2",
    "prepare_calendar_plan_v2",
    "prepare_market_handle_v2",
]
