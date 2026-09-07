"""Typed Python boundary for the Rust V1.1 FillReplay accounting authority.

The V1 replay kernel remains an explicit legacy comparator.  This module does
not generate fills or model matching; it validates an already ordered fill and
funding tape, performs one PyO3 call, and adapts cold-path results into normal
QuantBT pandas artifacts.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import importlib
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from ..verification.canonical_trace_v2 import CanonicalEventKindV2, CanonicalTraceRowV2, CanonicalTraceV2
from .market_tape import PreparedMarketTape
from .schema import AccountConfig, MarginMode, OmsMode


_FUNDING_PHASE_CODES = {
    "before_fills_at_close": 0,
    "after_fills_at_close": 1,
}
_OUTPUT_PROFILE_CODES = {"score": 0, "compact": 1, "audit": 2}


class FillReplayV2Error(ValueError):
    """Raised when an explicit FillReplay V2 contract is invalid."""


class FillReplayV2NativeUnavailable(RuntimeError):
    """Raised when the caller explicitly requests the missing Rust authority."""


@dataclass(frozen=True, slots=True)
class FillReplayTapeV2:
    """One ordered set of explicit signed fills for the Rust accounting route."""

    bar_index: np.ndarray
    sequence: np.ndarray
    event_id: np.ndarray
    symbol: np.ndarray
    signed_qty: np.ndarray
    price: np.ndarray
    fee: np.ndarray

    @classmethod
    def empty(cls) -> "FillReplayTapeV2":
        """Return a typed zero-fill tape for a valid no-trade replay."""

        return cls(
            bar_index=np.empty(0, dtype=np.int64),
            sequence=np.empty(0, dtype=np.int64),
            event_id=np.empty(0, dtype=np.uint64),
            symbol=np.empty(0, dtype=np.int64),
            signed_qty=np.empty(0, dtype=np.float64),
            price=np.empty(0, dtype=np.float64),
            fee=np.empty(0, dtype=np.float64),
        )

    @classmethod
    def from_frame(
        cls,
        frame: pd.DataFrame,
        *,
        symbols: Sequence[str],
        contract_sizes: Sequence[float],
        fee_rate: float = 0.0,
    ) -> "FillReplayTapeV2":
        """Normalize a human-readable explicit-fill table without reordering it.

        Required columns are ``bar_index`` and ``price`` plus either
        ``signed_qty`` or the legacy pair ``side``/``qty``.  `event_id` and
        `sequence` default to monotonically increasing IDs only when omitted.
        Existing order is intentionally preserved so out-of-order rows fail in
        the Rust authority rather than being silently corrected at the facade.
        """

        if not isinstance(frame, pd.DataFrame):
            raise TypeError("FillReplayTapeV2.from_frame requires a pandas DataFrame")
        if frame.empty:
            return cls.empty()
        required = {"bar_index", "price"}
        missing = sorted(required - set(frame.columns))
        if missing:
            raise FillReplayV2Error(f"fill replay V2 frame is missing columns {missing}")
        if "signed_qty" not in frame and not {"side", "qty"}.issubset(frame.columns):
            raise FillReplayV2Error("fill replay V2 requires signed_qty or side plus qty")
        count = len(frame)
        symbol_codes = _symbol_codes(frame.get("symbol"), symbols, label="fill", count=count)
        bar_index = _int_array(frame["bar_index"], name="fill bar_index", nonnegative=True)
        sequence = _uint_array(frame.get("sequence", pd.Series(np.arange(count), index=frame.index)), name="fill sequence")
        event_id = _uint_array(frame.get("event_id", pd.Series(np.arange(1, count + 1), index=frame.index)), name="fill event_id")
        price = _float_array(frame["price"], name="fill price", positive=True)
        if "signed_qty" in frame:
            signed_qty = _float_array(frame["signed_qty"], name="fill signed_qty", nonzero=True)
        else:
            qty = _float_array(frame["qty"], name="fill qty", positive=True)
            signed_qty = qty * _side_signs(frame["side"])
        if "fee" in frame:
            fee = _float_array(frame["fee"], name="fill fee", nonnegative=True)
        else:
            sizes = np.asarray(contract_sizes, dtype=np.float64)
            fee = np.abs(signed_qty) * price * sizes[symbol_codes] * float(fee_rate)
        return cls(
            bar_index=np.ascontiguousarray(bar_index, dtype=np.int64),
            sequence=np.ascontiguousarray(sequence, dtype=np.int64),
            event_id=np.ascontiguousarray(event_id, dtype=np.uint64),
            symbol=np.ascontiguousarray(symbol_codes, dtype=np.int64),
            signed_qty=np.ascontiguousarray(signed_qty, dtype=np.float64),
            price=np.ascontiguousarray(price, dtype=np.float64),
            fee=np.ascontiguousarray(fee, dtype=np.float64),
        )

    @classmethod
    def from_legacy(
        cls,
        tape: Any,
        *,
        symbols: Sequence[str],
    ) -> "FillReplayTapeV2":
        """Adapt the old single-symbol tape only for V1/V2 comparison fixtures."""

        attributes = ("bar_index", "sequence", "side", "qty", "price", "fee")
        if not all(hasattr(tape, name) for name in attributes):
            raise TypeError("legacy FillReplayTape adapter received an unsupported object")
        if len(symbols) != 1:
            raise FillReplayV2Error("legacy FillReplayTape can only adapt to one V2 symbol")
        qty = _float_array(getattr(tape, "qty"), name="legacy fill qty", positive=True)
        side = _float_array(getattr(tape, "side"), name="legacy fill side", nonzero=True)
        count = len(qty)
        return cls(
            bar_index=np.ascontiguousarray(_int_array(getattr(tape, "bar_index"), name="legacy fill bar_index", nonnegative=True), dtype=np.int64),
            sequence=np.ascontiguousarray(_uint_array(getattr(tape, "sequence"), name="legacy fill sequence"), dtype=np.int64),
            event_id=np.arange(1, count + 1, dtype=np.uint64),
            symbol=np.zeros(count, dtype=np.int64),
            signed_qty=np.ascontiguousarray(np.sign(side) * qty, dtype=np.float64),
            price=np.ascontiguousarray(_float_array(getattr(tape, "price"), name="legacy fill price", positive=True), dtype=np.float64),
            fee=np.ascontiguousarray(_float_array(getattr(tape, "fee"), name="legacy fill fee", nonnegative=True), dtype=np.float64),
        )

    def to_frame(self, symbols: Sequence[str]) -> pd.DataFrame:
        """Return the normalized, immutable-input representation for audits."""

        return pd.DataFrame(
            {
                "bar_index": self.bar_index,
                "sequence": self.sequence,
                "event_id": self.event_id,
                "symbol": [symbols[int(value)] for value in self.symbol],
                "signed_qty": self.signed_qty,
                "price": self.price,
                "fee": self.fee,
            }
        )


@dataclass(frozen=True, slots=True)
class FundingReplayTapeV2:
    """Explicit close-boundary funding events, separate from fill rows."""

    bar_index: np.ndarray
    sequence: np.ndarray
    event_id: np.ndarray
    symbol: np.ndarray
    rate: np.ndarray

    @classmethod
    def from_frame(cls, frame: pd.DataFrame, *, symbols: Sequence[str]) -> "FundingReplayTapeV2":
        if not isinstance(frame, pd.DataFrame):
            raise TypeError("FundingReplayTapeV2.from_frame requires a pandas DataFrame")
        if frame.empty:
            return cls.empty()
        missing = sorted({"bar_index", "rate"} - set(frame.columns))
        if missing:
            raise FillReplayV2Error(f"funding replay V2 frame is missing columns {missing}")
        count = len(frame)
        return cls(
            bar_index=np.ascontiguousarray(_int_array(frame["bar_index"], name="funding bar_index", nonnegative=True), dtype=np.int64),
            sequence=np.ascontiguousarray(_uint_array(frame.get("sequence", pd.Series(np.arange(count), index=frame.index)), name="funding sequence"), dtype=np.int64),
            event_id=np.ascontiguousarray(_uint_array(frame.get("event_id", pd.Series(np.arange(1, count + 1), index=frame.index)), name="funding event_id"), dtype=np.uint64),
            symbol=np.ascontiguousarray(
                _symbol_codes(frame.get("symbol"), symbols, label="funding", count=count),
                dtype=np.int64,
            ),
            rate=np.ascontiguousarray(_float_array(frame["rate"], name="funding rate"), dtype=np.float64),
        )

    @classmethod
    def empty(cls) -> "FundingReplayTapeV2":
        return cls(
            bar_index=np.empty(0, dtype=np.int64),
            sequence=np.empty(0, dtype=np.int64),
            event_id=np.empty(0, dtype=np.uint64),
            symbol=np.empty(0, dtype=np.int64),
            rate=np.empty(0, dtype=np.float64),
        )

    def to_frame(self, symbols: Sequence[str]) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "bar_index": self.bar_index,
                "sequence": self.sequence,
                "event_id": self.event_id,
                "symbol": [symbols[int(value)] for value in self.symbol],
                "rate": self.rate,
            }
        )


@dataclass(frozen=True, slots=True)
class NativeFillReplayV2Result:
    """Cold-path result of one Rust-owned FillReplay V2 accounting run."""

    profile: str
    score: Mapping[str, Any]
    equity: pd.Series | None = None
    cash: pd.Series | None = None
    positions: pd.DataFrame | None = None
    average_entries: pd.DataFrame | None = None
    fees: pd.Series | None = None
    funding: pd.Series | None = None
    margin: pd.DataFrame | None = None
    diagnostics: pd.DataFrame | None = None
    canonical_trace: CanonicalTraceV2 | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


def run_fill_replay_v2_native(
    *,
    tape: PreparedMarketTape,
    fills: FillReplayTapeV2,
    funding: FundingReplayTapeV2 | None,
    account: AccountConfig,
    contract_sizes: Sequence[float],
    leverages: Sequence[float],
    funding_phase: str = "after_fills_at_close",
    liquidation_fee_rate: float = 0.0,
    output_profile: str = "audit",
    invariant_checks: bool = True,
) -> NativeFillReplayV2Result:
    """Run the explicit V2 tape through one detached Rust call.

    V2 is exact only for close-timestamp market bars. Funding is explicit and
    must be supplied through ``funding``; no rate series is inferred or
    rescheduled at this layer.
    """

    _validate_account_contract(account)
    if tape.bar_timestamp_semantics != "close":
        raise NotImplementedError(
            "FillReplay V2 certifies close-timestamp bars only; pass bar_timestamp_semantics='close'"
        )
    phase = _normalize_choice(funding_phase, _FUNDING_PHASE_CODES, "funding_phase")
    profile = _normalize_choice(output_profile, _OUTPUT_PROFILE_CODES, "output_profile")
    n_symbols = tape.n_symbols
    contract_sizes_array = _contract_array(contract_sizes, n_symbols, "contract_sizes")
    leverages_array = _contract_array(leverages, n_symbols, "leverages")
    funding = funding or FundingReplayTapeV2.empty()
    module = _load_native_module()
    runner = getattr(module, "run_fill_replay_v2_native", None)
    if not callable(runner):
        raise FillReplayV2NativeUnavailable(
            "installed quantbt-native does not expose FillReplay V2; install a matching native wheel"
        )
    payload = dict(
        runner(
            np.ascontiguousarray(tape.timestamps_ns, dtype=np.int64),
            np.ascontiguousarray(tape.closes, dtype=np.float64),
            contract_sizes_array,
            leverages_array,
            float(account.initial_capital),
            float(account.maintenance_ratio),
            fills.bar_index,
            fills.sequence,
            fills.event_id,
            fills.symbol,
            fills.signed_qty,
            fills.price,
            fills.fee,
            funding.bar_index,
            funding.sequence,
            funding.event_id,
            funding.symbol,
            funding.rate,
            funding_phase=phase,
            liquidation_fee_rate=float(liquidation_fee_rate),
            output_profile=profile,
            invariant_checks=bool(invariant_checks),
        )
    )
    return _adapt_payload(tape=tape, payload=payload)


def _adapt_payload(*, tape: PreparedMarketTape, payload: Mapping[str, Any]) -> NativeFillReplayV2Result:
    profile = str(payload["output_profile"])
    score = {
        key: payload[key]
        for key in (
            "final_cash",
            "final_equity",
            "total_realized_pnl",
            "total_fees",
            "total_funding",
            "initial_margin",
            "maintenance_margin",
            "available_equity",
            "liquidated",
            "liquidation_state",
            "accepted_fill_count",
            "rejected_fill_count",
            "accepted_funding_count",
            "rejected_funding_count",
            "account_fingerprint",
            "trace_fingerprint",
        )
    }
    metadata = {
        "engine": payload["engine"],
        "engine_id": "fill_replay_v2_rust",
        "backend": "rust",
        "accounting_authority": "linear_gross_cross_v1",
        "canonical_trace_schema": payload["canonical_trace_schema"],
        "accounting_certified": True,
        "price_accounting_certified": True,
        "fee_accounting_certified": True,
        "funding_certified": True,
        "margin_certified": True,
        "liquidation_certified": True,
        "execution_generation_certified": False,
        "causality_certified": False,
        "data_signature": tape.signature,
        "account_fingerprint": str(score["account_fingerprint"]),
        "trace_fingerprint": str(score["trace_fingerprint"]),
        "accepted_fill_count": int(score["accepted_fill_count"]),
        "rejected_fill_count": int(score["rejected_fill_count"]),
        "accepted_funding_count": int(score["accepted_funding_count"]),
        "rejected_funding_count": int(score["rejected_funding_count"]),
    }
    if profile == "score":
        return NativeFillReplayV2Result(profile=profile, score=score, metadata=metadata)

    n_bars = int(payload["n_bars"])
    n_symbols = int(payload["n_symbols"])
    if n_bars != tape.n_bars or n_symbols != tape.n_symbols:
        raise RuntimeError("Rust FillReplay V2 returned a path shape inconsistent with the market tape")
    index = pd.DatetimeIndex(pd.to_datetime(tape.timestamps_ns, utc=True))
    positions = np.ascontiguousarray(np.asarray(payload["positions"], dtype=np.float64)).reshape(n_bars, n_symbols)
    average_entries = np.ascontiguousarray(np.asarray(payload["average_entries"], dtype=np.float64)).reshape(n_bars, n_symbols)
    cumulative_fees = np.asarray(payload["fees_paid"], dtype=np.float64)
    cumulative_funding = np.asarray(payload["funding_paid"], dtype=np.float64)
    fees = pd.Series(np.diff(np.r_[0.0, cumulative_fees]), index=index, name="fees")
    funding = pd.Series(np.diff(np.r_[0.0, cumulative_funding]), index=index, name="funding")
    position_frame = pd.DataFrame(
        {f"Position_{symbol}": positions[:, column] for column, symbol in enumerate(tape.symbols)},
        index=index,
    )
    average_entry_frame = pd.DataFrame(
        {f"AverageEntry_{symbol}": average_entries[:, column] for column, symbol in enumerate(tape.symbols)},
        index=index,
    )
    margin = pd.DataFrame(
        {
            "initial_margin": np.asarray(payload["initial_margin_path"], dtype=np.float64),
            "maintenance_margin": np.asarray(payload["maintenance_margin_path"], dtype=np.float64),
            "available_equity": np.asarray(payload["available_equity_path"], dtype=np.float64),
        },
        index=index,
    )
    diagnostics = pd.DataFrame(
        {
            "cash": np.asarray(payload["cash"], dtype=np.float64),
            "cumulative_fees": cumulative_fees,
            "cumulative_funding": cumulative_funding,
            "liquidation_state": np.asarray(payload["liquidation_state_path"], dtype=np.int32),
        },
        index=index,
    )
    trace = _trace_from_payload(payload) if profile == "audit" else None
    if trace is not None and trace.fingerprint() != score["trace_fingerprint"]:
        raise RuntimeError("Rust FillReplay V2 canonical trace fingerprint mismatch at the Python boundary")
    return NativeFillReplayV2Result(
        profile=profile,
        score=score,
        equity=pd.Series(np.asarray(payload["equity"], dtype=np.float64), index=index, name="equity"),
        cash=pd.Series(np.asarray(payload["cash"], dtype=np.float64), index=index, name="cash"),
        positions=position_frame,
        average_entries=average_entry_frame,
        fees=fees,
        funding=funding,
        margin=margin,
        diagnostics=diagnostics.join(average_entry_frame),
        canonical_trace=trace,
        metadata=metadata,
    )


def _trace_from_payload(payload: Mapping[str, Any]) -> CanonicalTraceV2:
    count = int(payload["trace_rows"])
    arrays = {
        name: np.asarray(payload[f"trace_{name}"])
        for name in (
            "sequence",
            "bar_index",
            "event_timestamp_ns",
            "effective_timestamp_ns",
            "event_kind",
            "symbol",
            "reason_code",
            "order_status_code",
            "qty",
            "price",
            "fee",
            "cash_before",
            "cash_after",
            "position_before",
            "position_after",
            "realized_pnl_before",
            "realized_pnl_after",
            "initial_margin_before",
            "initial_margin_after",
            "maintenance_margin_before",
            "maintenance_margin_after",
            "state_hash_before",
            "state_hash_after",
            "state_hash_before_present",
            "state_hash_after_present",
        )
    }
    if any(len(values) != count for values in arrays.values()):
        raise RuntimeError("Rust FillReplay V2 trace columns have inconsistent length")
    rows = []
    for index in range(count):
        rows.append(
            CanonicalTraceRowV2(
                sequence=int(arrays["sequence"][index]),
                bar_index=int(arrays["bar_index"][index]),
                event_timestamp_ns=int(arrays["event_timestamp_ns"][index]),
                effective_timestamp_ns=int(arrays["effective_timestamp_ns"][index]),
                event_kind=CanonicalEventKindV2(int(arrays["event_kind"][index])),
                symbol_id=int(arrays["symbol"][index]),
                account_id=0,
                reason_code=int(arrays["reason_code"][index]),
                order_status_code=int(arrays["order_status_code"][index]),
                qty=float(arrays["qty"][index]),
                price=float(arrays["price"][index]),
                fee=float(arrays["fee"][index]),
                cash_before=float(arrays["cash_before"][index]),
                cash_after=float(arrays["cash_after"][index]),
                position_before=float(arrays["position_before"][index]),
                position_after=float(arrays["position_after"][index]),
                realized_pnl_before=float(arrays["realized_pnl_before"][index]),
                realized_pnl_after=float(arrays["realized_pnl_after"][index]),
                initial_margin_before=float(arrays["initial_margin_before"][index]),
                initial_margin_after=float(arrays["initial_margin_after"][index]),
                maintenance_margin_before=float(arrays["maintenance_margin_before"][index]),
                maintenance_margin_after=float(arrays["maintenance_margin_after"][index]),
                state_hash_before=(
                    _canonical_state_hash(arrays["state_hash_before"][index])
                    if bool(arrays["state_hash_before_present"][index])
                    else -1
                ),
                state_hash_after=(
                    _canonical_state_hash(arrays["state_hash_after"][index])
                    if bool(arrays["state_hash_after_present"][index])
                    else -1
                ),
            )
        )
    return CanonicalTraceV2.from_rows(rows)


def _canonical_state_hash(value: object) -> int:
    """Match Rust's V2 `optional_u64` serializer at the Python boundary.

    Canonical Trace V2 stores discrete fields as signed ``i64`` values.  Rust
    deliberately saturates an account's internal ``u64`` fingerprint at
    ``i64::MAX`` before hashing.  The PyO3 payload retains its native unsigned
    representation, so the adapter must apply the same conversion before
    constructing the cross-backend Python trace.
    """

    return min(int(value), (1 << 63) - 1)


def _validate_account_contract(account: AccountConfig) -> None:
    if account.margin_mode != MarginMode.CROSS:
        raise NotImplementedError("FillReplay V2 currently certifies gross cross-margin accounts only")
    if account.oms_mode != OmsMode.NETTING:
        raise NotImplementedError("FillReplay V2 currently certifies netted positions only")
    if float(account.margin_buffer) != 0.0:
        raise NotImplementedError("FillReplay V2 does not approximate AccountConfig.margin_buffer; pass 0.0")


def _load_native_module():
    try:
        return importlib.import_module("_quantbt_native")
    except (ImportError, OSError) as exc:
        raise FillReplayV2NativeUnavailable(
            "FillReplay V2 requires quantbt-native; install a matching native wheel"
        ) from exc


def _contract_array(values: Sequence[float], expected: int, name: str) -> np.ndarray:
    array = np.ascontiguousarray(np.asarray(values, dtype=np.float64).reshape(-1))
    if len(array) != expected or not np.isfinite(array).all() or np.any(array <= 0.0):
        raise FillReplayV2Error(f"{name} must contain one finite value > 0 per symbol")
    return array


def _normalize_choice(value: str, mapping: Mapping[str, int], name: str) -> int:
    normalized = str(value).strip().lower()
    if normalized not in mapping:
        raise FillReplayV2Error(f"{name} must be one of {sorted(mapping)}")
    return mapping[normalized]


def _symbol_codes(values, symbols: Sequence[str], *, label: str, count: int | None = None) -> np.ndarray:
    count = (0 if values is None else len(values)) if count is None else int(count)
    if values is None:
        if len(symbols) != 1:
            raise FillReplayV2Error(f"multi-symbol {label} tape requires a symbol column")
        return np.zeros(count, dtype=np.int64)
    lookup = {str(symbol): index for index, symbol in enumerate(symbols)}
    codes = np.empty(len(values), dtype=np.int64)
    for index, value in enumerate(values):
        if isinstance(value, str):
            key = value.strip()
            if key not in lookup:
                raise FillReplayV2Error(f"unknown {label} symbol {value!r}")
            codes[index] = lookup[key]
        else:
            try:
                candidate = int(value)
            except (TypeError, ValueError) as exc:
                raise FillReplayV2Error(f"invalid {label} symbol {value!r}") from exc
            if candidate < 0 or candidate >= len(symbols):
                raise FillReplayV2Error(f"{label} symbol index {candidate} is outside the market tape")
            codes[index] = candidate
    return codes


def _side_signs(values) -> np.ndarray:
    out = np.empty(len(values), dtype=np.float64)
    for index, value in enumerate(values):
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"buy", "long", "+1", "1"}:
                out[index] = 1.0
            elif normalized in {"sell", "short", "-1"}:
                out[index] = -1.0
            else:
                raise FillReplayV2Error(f"unsupported fill side {value!r}")
        else:
            numeric = float(value)
            if not np.isfinite(numeric) or numeric == 0.0:
                raise FillReplayV2Error("fill side must be finite and non-zero")
            out[index] = float(np.sign(numeric))
    return out


def _float_array(values, *, name: str, positive: bool = False, nonnegative: bool = False, nonzero: bool = False) -> np.ndarray:
    array = np.ascontiguousarray(pd.to_numeric(values, errors="raise").to_numpy(dtype=np.float64) if isinstance(values, pd.Series) else np.asarray(values, dtype=np.float64))
    if not np.isfinite(array).all():
        raise FillReplayV2Error(f"{name} must be finite")
    if positive and np.any(array <= 0.0):
        raise FillReplayV2Error(f"{name} must be > 0")
    if nonnegative and np.any(array < 0.0):
        raise FillReplayV2Error(f"{name} must be >= 0")
    if nonzero and np.any(np.abs(array) <= 0.0):
        raise FillReplayV2Error(f"{name} must be non-zero")
    return array


def _int_array(values, *, name: str, nonnegative: bool = False) -> np.ndarray:
    numeric = _float_array(values, name=name)
    if np.any(numeric != np.floor(numeric)):
        raise FillReplayV2Error(f"{name} must contain integers")
    if nonnegative and np.any(numeric < 0.0):
        raise FillReplayV2Error(f"{name} must be >= 0")
    return np.ascontiguousarray(numeric, dtype=np.int64)


def _uint_array(values, *, name: str) -> np.ndarray:
    numeric = _int_array(values, name=name, nonnegative=True)
    return np.ascontiguousarray(numeric, dtype=np.uint64)


__all__ = [
    "FillReplayTapeV2",
    "FillReplayV2Error",
    "FillReplayV2NativeUnavailable",
    "FundingReplayTapeV2",
    "NativeFillReplayV2Result",
    "run_fill_replay_v2_native",
]
