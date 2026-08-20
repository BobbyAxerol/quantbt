"""Optional PyO3 adapter for the certified native-event Rust slices.

Python remains the full-featured reactive implementation. Rust is explicit and
capability-gated for the certified single-symbol batched tape contract; audit
buffers are adapted back to the common Python result surface outside the score
hot path.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
import importlib
import os
from time import perf_counter_ns
from types import ModuleType
from typing import Callable, Mapping, Optional, Sequence

import numpy as np
import pandas as pd

from ..core.event import ORDER_STATUS_PENDING
from ..core.event_contracts import EventClockContract, get_event_clock_contract
from ..core.constraints import quantize_signed_quantity
from ..core.order_compiler import CompiledOrderCommandArrays, command_tape_fingerprint
from ..core.orders import OrderAction, OrderActivationPolicy, OrderCommand
from ..core.reactive import NativeActiveOrderSnapshot, NativeFillEvent, NativeOrderEvent, NativeStrategyContext
from ..core.schema import OrderSide, OrderType, TimeInForce
from ..core.native_event_capabilities import (
    normalize_native_event_capabilities,
    semantic_descriptor_fingerprint,
    validate_native_event_semantic_descriptor,
)
from ..core.native_event_promotion import (
    NativePromotionContext,
    NativePromotionDecision,
    NativePromotionError,
    resolve_native_event_promotion,
)
from ..core.generated_product_contracts import NATIVE_EVENT_CORE_PACKAGE_VERSION
from ..core.product_contracts import (
    NativePackageCompatibilityError,
    require_native_package_pair,
    validate_native_runtime_product_descriptor,
)
from ..errors import CommandValidationError, EngineErrorContext, NativeProtocolError
from ..preparation.cache import ResetScope
from ..strategies.commands import CommandBatchView


RUST_NATIVE_API_VERSION = "0.4"
_VALID_BACKENDS = frozenset({"auto", "python", "rust", "replay_certified"})
_R1_ACTION_PLACE = 0
_R1_ACTION_CANCEL = 1
_R2_ACTION_AMEND = 2
_R2_ACTION_REPLACE = 3
_R1_ORDER_MARKET = 0
_R1_ORDER_LIMIT = 1
_R2_ORDER_STOP_MARKET = 2
_R2_ORDER_STOP_LIMIT = 3
_R1_CODE_WIDTH = 8
_R1_VALUE_WIDTH = 3
_R2_FLAG_REDUCE_ONLY = 1
_R2_MUTATE_QTY = 1
_R2_MUTATE_PRICE = 2
_R2_MUTATE_TRIGGER = 4
_FULL_CODE_WIDTH = 16
_FULL_VALUE_WIDTH = 3
_FULL_OUTPUT_POSITIONS = 1
_FULL_OUTPUT_FILLS = 2
_FULL_OUTPUT_EVENTS = 4
_FULL_OUTPUT_ACTIVE_ORDERS = 8


def _step_value(payload, key: str, default=None):
    """Read a legacy dict or the API 0.4 typed Rust step result."""

    if isinstance(payload, Mapping):
        return payload.get(key, default)
    return getattr(payload, key, default)


def _step_has(payload, key: str) -> bool:
    if isinstance(payload, Mapping):
        return key in payload
    return hasattr(payload, key)


class NativeEventRustBackendError(NativeProtocolError):
    """Raised when an explicitly requested Rust backend cannot be used."""


@dataclass(slots=True)
class _ScheduledPrimitiveBatch:
    """Owned primitive callback batch awaiting its effective market bar."""

    codes: np.ndarray
    values: np.ndarray
    expiry: np.ndarray
    command_count: int


@dataclass(frozen=True)
class NativeEventRustExtensionStatus:
    """Import and compatibility state of the optional ``_quantbt_native`` wheel."""

    available: bool
    compatible: bool
    executable: bool
    version: Optional[str]
    api_version: Optional[str]
    capabilities: Mapping[str, bool]
    reason: Optional[str] = None
    canonical_capabilities: Mapping[str, bool] = field(default_factory=dict)
    semantic_descriptor: Mapping[str, object] = field(default_factory=dict)
    product_descriptor: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class NativeEventBackendSelection:
    """Internal backend decision without changing the public endpoint API."""

    requested: str
    resolved: str
    extension: NativeEventRustExtensionStatus
    promotion: NativePromotionDecision


@dataclass(frozen=True)
class RustCommandBatch:
    """Contiguous R1 command buffers plus the Python-side identity table."""

    codes: np.ndarray
    values: np.ndarray
    expiry: np.ndarray
    commands: tuple[OrderCommand, ...]


@dataclass(frozen=True, slots=True)
class RustBatchedScoreResult:
    """Scalar result returned by one Rust full-tape call."""

    final_equity: float
    final_position: float
    total_fee: float
    total_turnover: float
    fill_count: int
    event_count: int
    rejected_count: int
    canceled_count: int
    max_initial_margin: float
    max_maintenance_margin: float
    bars: int
    metadata: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class RustBatchedAuditResult:
    """Contiguous SoA audit buffers returned by one Rust full-tape call."""

    equity: np.ndarray
    positions: np.ndarray
    fees: np.ndarray
    turnover: np.ndarray
    initial_margin: np.ndarray
    maintenance_margin: np.ndarray
    fill_bar: np.ndarray
    fill_order_id: np.ndarray
    fill_side: np.ndarray
    fill_qty: np.ndarray
    fill_price: np.ndarray
    fill_fee: np.ndarray
    event_bar: np.ndarray
    event_kind: np.ndarray
    event_status: np.ndarray
    event_order_id: np.ndarray
    event_target_id: np.ndarray
    total_fee: float
    total_turnover: float
    fill_count: int
    event_count: int
    rejected_count: int
    canceled_count: int
    max_initial_margin: float
    max_maintenance_margin: float
    metadata: Mapping[str, object] = field(default_factory=dict)
    id_values: tuple[str, ...] = ()

    @property
    def final_equity(self) -> float:
        """Final equity without materializing a second result object."""

        return float(self.equity[-1]) if len(self.equity) else 0.0

    @property
    def final_position(self) -> float:
        """Final single-symbol position from the audit path."""

        return float(self.positions[-1]) if len(self.positions) else 0.0

    def to_backtest_result(
        self,
        *,
        datetime_index: pd.DatetimeIndex,
        closes: pd.Series | pd.DataFrame,
        symbol: str,
        initial_capital: float,
        leverage: float = 1.0,
        metadata: Optional[Mapping[str, object]] = None,
        include_fills: bool = True,
    ):
        """Adapt a Rust audit into the common :class:`BacktestResultV2`.

        The Rust boundary intentionally returns typed scalar/SoA data rather
        than Python domain objects.  This adapter is the single report
        boundary: it creates the same equity, position, fee, margin,
        ``fills_report`` and ``order_report`` surfaces used by native-event
        Python results.  It is an audit/report operation, not part of the
        batched score hot path.
        """

        from ..core.results import BacktestResultV2
        from ..core.orders import Fill
        from ..core.schema import OrderSide

        idx = pd.DatetimeIndex(datetime_index)
        if len(idx) != len(self.equity):
            raise ValueError("datetime_index length must match Rust audit equity path")
        if isinstance(closes, pd.DataFrame):
            if symbol in closes.columns:
                close_series = closes[symbol]
            elif f"Close_{symbol}" in closes.columns:
                close_series = closes[f"Close_{symbol}"]
            elif len(closes.columns) == 1:
                close_series = closes.iloc[:, 0]
            else:
                raise KeyError(f"close data does not contain symbol={symbol!r}")
        else:
            close_series = closes
        close_series = pd.Series(close_series, index=idx, dtype=float)
        equity = pd.Series(np.asarray(self.equity, dtype=np.float64), index=idx, name="equity")
        positions = pd.DataFrame(
            {f"Position_{symbol}": np.asarray(self.positions, dtype=np.float64)},
            index=idx,
        )
        fees = pd.Series(np.asarray(self.fees, dtype=np.float64), index=idx, name="fees")
        funding = pd.Series(0.0, index=idx, name="funding")
        margin = pd.DataFrame(
            {
                "initial_margin": np.asarray(self.initial_margin, dtype=np.float64),
                "maintenance_margin": np.asarray(self.maintenance_margin, dtype=np.float64),
            },
            index=idx,
        )
        diagnostics = pd.DataFrame(
            {
                "turnover": np.asarray(self.turnover, dtype=np.float64),
                "rejected_orders": np.bincount(
                    np.asarray(self.event_bar, dtype=np.int64)[
                        np.asarray(self.event_kind, dtype=np.int64) == 3
                    ],
                    minlength=len(idx),
                ),
                "canceled_orders": np.bincount(
                    np.asarray(self.event_bar, dtype=np.int64)[
                        np.asarray(self.event_kind, dtype=np.int64) == 1
                    ],
                    minlength=len(idx),
                ),
            },
            index=idx,
        )

        id_values = tuple(self.id_values or self.metadata.get("id_values", ()))

        def order_id(code: int) -> Optional[str]:
            return id_values[int(code)] if 0 <= int(code) < len(id_values) else None

        fills_report = pd.DataFrame(
            {
                "bar": np.asarray(self.fill_bar, dtype=np.int64),
                "timestamp": [idx[int(bar)] for bar in self.fill_bar],
                "order_id": [order_id(code) for code in self.fill_order_id],
                "side": ["BUY" if int(side) > 0 else "SELL" for side in self.fill_side],
                "qty": np.asarray(self.fill_qty, dtype=np.float64),
                "price": np.asarray(self.fill_price, dtype=np.float64),
                "fee": np.asarray(self.fill_fee, dtype=np.float64),
                "symbol": symbol,
            }
        )
        order_report = pd.DataFrame(
            {
                "bar": np.asarray(self.event_bar, dtype=np.int64),
                "timestamp": [idx[int(bar)] for bar in self.event_bar],
                "event_kind": np.asarray(self.event_kind, dtype=np.int64),
                "event_status": np.asarray(self.event_status, dtype=np.int64),
                "order_id": [order_id(code) for code in self.event_order_id],
                "target_order_id": [order_id(code) for code in self.event_target_id],
                "symbol": symbol,
            }
        )
        fill_objects = ()
        if include_fills:
            fill_objects = tuple(
                Fill(
                    timestamp=idx[int(bar)],
                    symbol=symbol,
                    side=OrderSide.BUY if int(side) > 0 else OrderSide.SELL,
                    qty=float(qty),
                    price=float(price),
                    fee=float(fee),
                    order_id=order_id(order_code),
                    metadata={"backend": "rust_batched", "bar": int(bar)},
                )
                for bar, order_code, side, qty, price, fee in zip(
                    self.fill_bar,
                    self.fill_order_id,
                    self.fill_side,
                    self.fill_qty,
                    self.fill_price,
                    self.fill_fee,
                )
            )
        result_metadata = {
            "backend": "native_event",
            "engine": "event_v2_rust_batched_audit",
            "report_level": "audit",
            "native_event_backend_requested": "rust",
            "native_event_backend_resolved": "rust",
            "fills_report": fills_report,
            "event_ledger": {
                "bar": self.event_bar,
                "kind": self.event_kind,
                "status": self.event_status,
                "order_id": self.event_order_id,
                "target_id": self.event_target_id,
            },
            "order_report": order_report,
            "command_report": order_report,
            "id_values": id_values,
            "lifecycle_counters": {
                "fill_count": int(self.fill_count),
                "event_count": int(self.event_count),
                "rejected_count": int(self.rejected_count),
                "canceled_count": int(self.canceled_count),
            },
            "rust_audit_adapter": "RustBatchedAuditResult.to_backtest_result",
        }
        if metadata:
            result_metadata.update(dict(metadata))
        return BacktestResultV2(
            equity=equity,
            returns=equity.pct_change().replace([np.inf, -np.inf], np.nan).fillna(0.0),
            positions=positions,
            closes=pd.DataFrame({f"Close_{symbol}": close_series.to_numpy()}, index=idx),
            symbols=[symbol],
            initial_capital=float(initial_capital),
            leverage=float(leverage),
            liquidated=False,
            orders=(),
            fills=fill_objects,
            fees=fees,
            funding=funding,
            margin=margin,
            diagnostics=diagnostics,
            metadata=result_metadata,
        )


@dataclass(frozen=True, slots=True)
class RustFullAuditResult:
    """Full-contract Rust SoA result, including multi-symbol/funding state."""

    equity: np.ndarray
    positions: np.ndarray
    fees: np.ndarray
    turnover: np.ndarray
    funding: np.ndarray
    initial_margin: np.ndarray
    maintenance_margin: np.ndarray
    fill_bar: np.ndarray
    fill_order_id: np.ndarray
    fill_symbol: np.ndarray
    fill_side: np.ndarray
    fill_qty: np.ndarray
    fill_price: np.ndarray
    fill_fee: np.ndarray
    fill_reason: np.ndarray
    fill_ambiguity: np.ndarray
    event_bar: np.ndarray
    event_kind: np.ndarray
    event_status: np.ndarray
    event_order_id: np.ndarray
    event_target_id: np.ndarray
    event_symbol: np.ndarray
    event_reject_code: np.ndarray
    total_fee: float
    total_turnover: float
    total_funding: float
    fill_count: int
    event_count: int
    rejected_count: int
    canceled_count: int
    max_initial_margin: float
    max_maintenance_margin: float
    liquidated: bool
    liquidation_bar: int
    liquidation_reason: int
    id_values: tuple[str, ...] = ()
    command_report: Optional[pd.DataFrame] = None
    command_metadata: Mapping[str, Mapping[str, object]] = field(default_factory=dict)

    @property
    def final_equity(self) -> float:
        return float(self.equity[-1]) if len(self.equity) else 0.0

    def to_backtest_result(
        self,
        *,
        datetime_index: pd.DatetimeIndex,
        closes: pd.DataFrame,
        symbols: Sequence[str],
        initial_capital: float,
        leverage: float,
        metadata: Optional[Mapping[str, object]] = None,
    ):
        """Materialize the common result surface outside the Rust hot path."""
        from ..core.results import BacktestResultV2
        from ..core.orders import Fill
        from ..core.schema import OrderSide

        idx = pd.DatetimeIndex(datetime_index)
        equity = pd.Series(self.equity, index=idx, name="equity")
        positions = pd.DataFrame(
            {f"Position_{symbol}": self.positions[:, col] for col, symbol in enumerate(symbols)},
            index=idx,
        )
        close_frame = pd.DataFrame(
            {f"Close_{symbol}": closes[symbol].to_numpy(dtype=np.float64) for symbol in symbols},
            index=idx,
        )

        def order_id(code: int) -> Optional[str]:
            return self.id_values[int(code)] if 0 <= int(code) < len(self.id_values) else None

        fill_meta = [
            self.command_metadata.get(order_id(code) or "", {}) for code in self.fill_order_id
        ]
        fills_report = pd.DataFrame({
            "bar": self.fill_bar,
            "timestamp": [idx[int(bar)] for bar in self.fill_bar],
            "order_id": [order_id(code) for code in self.fill_order_id],
            "symbol": [symbols[int(code)] for code in self.fill_symbol],
            "side": ["BUY" if int(side) > 0 else "SELL" for side in self.fill_side],
            "qty": self.fill_qty,
            "price": self.fill_price,
            "fee": self.fill_fee,
            "fill_reason_code": self.fill_reason,
            "fill_ambiguity_code": self.fill_ambiguity,
            "tag": [meta.get("tag") for meta in fill_meta],
            "campaign_id": [meta.get("campaign_id") for meta in fill_meta],
            "cycle_id": [meta.get("cycle_id") for meta in fill_meta],
            "level_id": [meta.get("level_id") for meta in fill_meta],
        })
        order_report = pd.DataFrame({
            "bar": self.event_bar,
            "timestamp": [idx[int(bar)] for bar in self.event_bar],
            "event_kind": self.event_kind,
            "event_status": self.event_status,
            "order_id": [order_id(code) for code in self.event_order_id],
            "target_order_id": [order_id(code) for code in self.event_target_id],
            "symbol": [None if int(code) < 0 else symbols[int(code)] for code in self.event_symbol],
            "reject_code": self.event_reject_code,
        })
        fills = tuple(
            Fill(
                timestamp=idx[int(bar)], symbol=symbols[int(symbol)],
                side=OrderSide.BUY if int(side) > 0 else OrderSide.SELL,
                qty=float(qty), price=float(price), fee=float(fee), order_id=order_id(order_code),
                metadata={"backend": "rust_full_contract", "bar": int(bar)},
            )
            for bar, order_code, symbol, side, qty, price, fee in zip(
                self.fill_bar, self.fill_order_id, self.fill_symbol, self.fill_side,
                self.fill_qty, self.fill_price, self.fill_fee,
            )
        )
        diagnostics = pd.DataFrame({
            "turnover": self.turnover,
            "rejected_orders": np.bincount(self.event_bar[self.event_kind == 7], minlength=len(idx)),
            "canceled_orders": np.bincount(self.event_bar[self.event_kind == 1], minlength=len(idx)),
        }, index=idx)
        result_metadata = {
            "backend": "native_event",
            "engine": "event_v2_rust_full_contract",
            "report_level": "audit",
            "native_event_backend_requested": "rust",
            "native_event_backend_resolved": "rust",
            "fills_report": fills_report,
            "order_report": order_report,
            "command_report": (
                self.command_report.copy(deep=False)
                if self.command_report is not None
                else pd.DataFrame()
            ),
            "id_values": self.id_values,
            "liquidation_reason": int(self.liquidation_reason),
            "lifecycle_counters": {
                "fill_count": int(self.fill_count), "event_count": int(self.event_count),
                "rejected_count": int(self.rejected_count), "canceled_count": int(self.canceled_count),
            },
            "event_ledger": {
                "bar": self.event_bar,
                "kind": self.event_kind,
                "status": self.event_status,
                "order_id": self.event_order_id,
                "target_id": self.event_target_id,
            },
            "rust_contract": "native_event_v2_full_contract",
        }
        if metadata:
            result_metadata.update(dict(metadata))
        return BacktestResultV2(
            equity=equity,
            returns=equity.pct_change().replace([np.inf, -np.inf], np.nan).fillna(0.0),
            positions=positions,
            closes=close_frame,
            symbols=list(symbols),
            initial_capital=float(initial_capital),
            leverage=float(leverage),
            liquidated=bool(self.liquidated),
            liquidation_bar=int(self.liquidation_bar),
            orders=(), fills=fills,
            fees=pd.Series(self.fees, index=idx, name="fees"),
            funding=pd.Series(self.funding, index=idx, name="funding"),
            margin=pd.DataFrame({"initial_margin": self.initial_margin, "maintenance_margin": self.maintenance_margin}, index=idx),
            diagnostics=diagnostics,
            metadata=result_metadata,
        )


@dataclass(frozen=True, slots=True)
class RustBatchedChunkResult:
    """Sparse result for one stateful ``run_until`` continuation chunk.

    The arrays contain only fills/order events observed in the chunk.  No
    dense equity or position path is materialized; the caller can request a
    full audit separately when it needs bar-by-bar diagnostics.
    """

    start_bar: int
    stop_bar: int
    final_equity: float
    final_position: float
    total_fee: float
    total_turnover: float
    fill_count: int
    event_count: int
    rejected_count: int
    canceled_count: int
    max_initial_margin: float
    max_maintenance_margin: float
    liquidation_seen: bool
    wake_bar: np.ndarray
    wake_kind: np.ndarray
    fill_bar: np.ndarray
    fill_order_id: np.ndarray
    fill_side: np.ndarray
    fill_qty: np.ndarray
    fill_price: np.ndarray
    fill_fee: np.ndarray
    event_bar: np.ndarray
    event_kind: np.ndarray
    event_status: np.ndarray
    event_order_id: np.ndarray
    event_target_id: np.ndarray
    metadata: Mapping[str, object] = field(default_factory=dict)


@dataclass
class RustCommandBuffer:
    """Capacity-managed primitive buffers reused across Rust callback bars."""

    codes: np.ndarray = field(default_factory=lambda: np.empty((0, _R1_CODE_WIDTH), dtype=np.int64))
    values: np.ndarray = field(default_factory=lambda: np.empty((0, _R1_VALUE_WIDTH), dtype=np.float64))
    expiry: np.ndarray = field(default_factory=lambda: np.empty(0, dtype=np.int64))

    def reserve(self, size: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        if size > len(self.codes):
            capacity = max(int(size), max(8, len(self.codes) * 2))
            self.codes = np.empty((capacity, _R1_CODE_WIDTH), dtype=np.int64)
            self.values = np.empty((capacity, _R1_VALUE_WIDTH), dtype=np.float64)
            self.expiry = np.empty(capacity, dtype=np.int64)
        return self.codes[:size], self.values[:size], self.expiry[:size]


@dataclass
class RustFullCommandBuffer:
    """Capacity-managed buffers for the API 0.4 full command ABI.

    The public compiler remains the source of truth for command meaning and
    ordering. This object only owns reusable contiguous storage so repeated
    static or reactive runs do not allocate a new ``(n, 16)``/``(n, 3)`` pair
    for every call.
    """

    codes: np.ndarray = field(default_factory=lambda: np.empty((0, _FULL_CODE_WIDTH), dtype=np.int64))
    values: np.ndarray = field(default_factory=lambda: np.empty((0, _FULL_VALUE_WIDTH), dtype=np.float64))
    expiry: np.ndarray = field(default_factory=lambda: np.empty(0, dtype=np.int64))
    growth_count: int = 0
    commands_compiled: int = 0

    @property
    def capacity(self) -> int:
        """Number of command rows currently reserved."""

        return int(len(self.codes))

    def reserve(self, size: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        size = int(size)
        if size < 0:
            raise ValueError("command buffer size must be >= 0")
        if size > self.capacity:
            capacity = max(size, max(8, self.capacity * 2))
            self.codes = np.empty((capacity, _FULL_CODE_WIDTH), dtype=np.int64)
            self.values = np.empty((capacity, _FULL_VALUE_WIDTH), dtype=np.float64)
            self.expiry = np.empty(capacity, dtype=np.int64)
            self.growth_count += 1
        self.commands_compiled += size
        codes = self.codes[:size]
        values = self.values[:size]
        expiry = self.expiry[:size]
        codes.fill(-1)
        values.fill(0.0)
        expiry.fill(-1)
        return codes, values, expiry

    def clear(self) -> None:
        """Release storage and reset counters for explicit cache cleanup."""

        self.codes = np.empty((0, _FULL_CODE_WIDTH), dtype=np.int64)
        self.values = np.empty((0, _FULL_VALUE_WIDTH), dtype=np.float64)
        self.expiry = np.empty(0, dtype=np.int64)
        self.growth_count = 0
        self.commands_compiled = 0


@dataclass(slots=True)
class _RustNativeProjection:
    """Compact callback projection copied from authoritative Rust state."""

    positions: np.ndarray
    equity: float
    initial_margin: float = 0.0
    maintenance_margin: float = 0.0
    total_fee: float = 0.0
    total_funding: float = 0.0
    total_turnover: float = 0.0
    fill_count: int = 0
    event_count: int = 0
    rejected_count: int = 0
    canceled_count: int = 0
    liquidated: bool = False
    liquidation_bar: int = -1
    liquidation_reason: int = 0
    fill_cursor: tuple[int, int] = (0, 0)
    event_cursor: tuple[int, int] = (0, 0)
    order_delta_cursor: tuple[int, int] = (0, 0)
    position_delta_cursor: tuple[int, int] = (0, 0)


def _empty_status(reason: str) -> NativeEventRustExtensionStatus:
    return NativeEventRustExtensionStatus(
        available=False,
        compatible=False,
        executable=False,
        version=None,
        api_version=None,
        capabilities={},
        reason=reason,
        canonical_capabilities={},
        semantic_descriptor={},
        product_descriptor={},
    )


def _load_extension() -> Optional[ModuleType]:
    return importlib.import_module("_quantbt_native")


def _read_native_value(module: ModuleType, name: str) -> Optional[object]:
    value = getattr(module, name, None)
    return value() if callable(value) else value


def probe_native_event_rust_extension(
    module: Optional[ModuleType] = None,
    *,
    module_loader: Optional[Callable[[], Optional[ModuleType]]] = None,
) -> NativeEventRustExtensionStatus:
    """Return extension compatibility without enabling a Rust execution path.

    ``module`` and ``module_loader`` are test seams.  Runtime callers should
    leave both unset so the optional extension is imported normally.
    """
    if module is None:
        loader = _load_extension if module_loader is None else module_loader
        try:
            module = loader()
        except (ImportError, OSError) as exc:
            return _empty_status(f"unable to import _quantbt_native: {exc}")
    if module is None:
        return _empty_status("quantbt-native is not installed; install a compatible native wheel first")

    try:
        version_value = _read_native_value(module, "version")
        version = str(version_value if version_value is not None else getattr(module, "__version__", "")) or None
        api_value = _read_native_value(module, "api_version")
        api_version = str(api_value) if api_value is not None else None
        raw_capabilities = _read_native_value(module, "capabilities")
        raw_descriptor = _read_native_value(module, "semantic_descriptor")
        raw_product_descriptor = _read_native_value(module, "product_descriptor")
    except Exception as exc:  # pragma: no cover - protects optional binary imports.
        return _empty_status(f"failed to query _quantbt_native metadata: {exc}")

    if not isinstance(raw_capabilities, Mapping):
        raw_capabilities = {}
    capabilities = {str(name): bool(enabled) for name, enabled in raw_capabilities.items()}
    canonical_capabilities = normalize_native_event_capabilities(capabilities)
    semantic_descriptor = dict(raw_descriptor) if isinstance(raw_descriptor, Mapping) else {}
    product_descriptor = dict(raw_product_descriptor) if isinstance(raw_product_descriptor, Mapping) else {}
    # 0.3 remains readable for the legacy R1/R2 classes. Full V2 capability
    # is gated independently by the explicit 0.4 capability keys below.
    compatible = api_version in {"0.3", RUST_NATIVE_API_VERSION}
    descriptor_error = None
    if compatible and api_version == RUST_NATIVE_API_VERSION:
        try:
            validate_native_event_semantic_descriptor(semantic_descriptor)
            if version is None:
                raise NativePackageCompatibilityError(
                    "_quantbt_native did not report a native package version"
                )
            pair = require_native_package_pair(NATIVE_EVENT_CORE_PACKAGE_VERSION, version)
            validate_native_runtime_product_descriptor(product_descriptor, pair=pair)
        except (TypeError, ValueError) as exc:
            compatible = False
            descriptor_error = str(exc)
        except NativePackageCompatibilityError as exc:
            compatible = False
            descriptor_error = str(exc)
    if not compatible:
        return NativeEventRustExtensionStatus(
            available=True,
            compatible=False,
            executable=False,
            version=version,
            api_version=api_version,
            capabilities=capabilities,
            reason=(
                descriptor_error
                if descriptor_error is not None
                else (
                    "_quantbt_native API version mismatch: "
                    f"expected {RUST_NATIVE_API_VERSION!r}, received {api_version!r}"
                )
            ),
            canonical_capabilities=canonical_capabilities,
            semantic_descriptor=semantic_descriptor,
            product_descriptor=product_descriptor,
        )

    executable = bool(capabilities.get("reactive_session", False))
    reason = None if executable else "_quantbt_native does not advertise the required R1 reactive_session capability"
    return NativeEventRustExtensionStatus(
        available=True,
        compatible=True,
        executable=executable,
        version=version,
        api_version=api_version,
        capabilities=capabilities,
        reason=reason,
        canonical_capabilities=canonical_capabilities,
        semantic_descriptor=semantic_descriptor,
        product_descriptor=product_descriptor,
    )


def resolve_native_event_backend(
    requested: Optional[str] = None,
    *,
    extension_status: Optional[NativeEventRustExtensionStatus] = None,
    backend_policy: Optional[str] = None,
    workload_id: str = "event_python_callback_v2_v3",
    execution_contract_id: str = "event_lifecycle_v2_next_bar_close",
    strategy_mode: str = "python_callback_compat",
    profile: str = "audit",
    account_model: str = "linear_quote_settled_gross_cross",
    bars: int = 0,
    symbol_count: int = 1,
    required_capabilities: Sequence[str] = (),
    environment: Optional[Mapping[str, str]] = None,
) -> NativeEventBackendSelection:
    """Resolve native-event routing through the versioned product policy.

    The function remains the compatibility seam for direct backend users.  It
    keeps the old ``auto`` behavior until an enabled registry rule is promoted,
    and it probes the extension only when a request can actually use Rust.
    """

    environment = os.environ if environment is None else environment
    selected = str(requested or environment.get("QUANTBT_NATIVE_BACKEND", "auto")).lower().strip()
    status = extension_status

    def context(current: Optional[NativeEventRustExtensionStatus]) -> NativePromotionContext:
        return NativePromotionContext(
            requested_backend=selected,
            backend_policy=backend_policy,
            workload_id=workload_id,
            execution_contract_id=execution_contract_id,
            strategy_mode=strategy_mode,
            profile=profile,
            account_model=account_model,
            bars=int(bars),
            symbol_count=int(symbol_count),
            required_capabilities=tuple(str(item) for item in required_capabilities),
            native_available=None if current is None else current.available,
            native_compatible=None if current is None else current.compatible,
            native_executable=None if current is None else current.executable,
            native_capabilities=(
                () if current is None else tuple(name for name, enabled in current.capabilities.items() if enabled)
            ),
            native_reason=None if current is None else current.reason,
            native_version=None if current is None else current.version,
            native_api_version=None if current is None else current.api_version,
            native_capability_fingerprint=(
                None
                if current is None or not current.semantic_descriptor
                else semantic_descriptor_fingerprint(current.semantic_descriptor)
            ),
        )

    try:
        decision = resolve_native_event_promotion(context(status), environment=environment)
        if decision.native_probe_required:
            status = status or probe_native_event_rust_extension()
            decision = resolve_native_event_promotion(context(status), environment=environment)
    except NativePromotionError as exc:
        raise NativeEventRustBackendError(str(exc)) from exc

    if selected == "rust" and decision.resolved_backend != "rust":
        detail = decision.native_reason or decision.reason
        raise NativeEventRustBackendError(f"native-event backend='rust' is unavailable: {detail}")

    status = status or _empty_status("Rust extension was not queried because the Python backend was selected")
    return NativeEventBackendSelection(
        requested=selected,
        resolved=decision.resolved_backend,
        extension=status,
        promotion=decision,
    )


def _require_r1_extension() -> ModuleType:
    module = _load_extension()
    status = probe_native_event_rust_extension(module=module)
    if not status.available or not status.compatible or not status.executable:
        detail = status.reason or "unknown native extension state"
        raise NativeEventRustBackendError(f"native-event Rust R1 is unavailable: {detail}")
    if not hasattr(module, "ReactiveSessionCore"):
        raise NativeEventRustBackendError("_quantbt_native is compatible but lacks ReactiveSessionCore")
    return module


def validate_rust_r1_support(
    *,
    symbols: Sequence[str],
    constraints,
    use_funding: bool,
    maintenance_ratio: float,
) -> None:
    """Reject every feature outside the R2 single-symbol surface.

    The historic function name remains an internal compatibility alias for
    callers introduced with R1. R2 adds lifecycle commands and quantity
    filters, but funding/liquidation and multi-symbol remain Python-only.
    """
    if len(symbols) != 1:
        raise NativeEventRustBackendError("Rust R1 supports exactly one symbol; use backend='python' for multi-symbol")
    if use_funding:
        raise NativeEventRustBackendError("Rust R2 does not support funding; use backend='python'")
    if float(maintenance_ratio) != 0.0:
        raise NativeEventRustBackendError(
            "Rust R2 does not support liquidation semantics; set maintenance_ratio=0.0 or use backend='python'"
        )


def compile_rust_r1_command_batch(
    commands: Sequence[OrderCommand],
    *,
    symbol: str,
    intern_id: Callable[[Optional[str]], int],
    buffer: Optional[RustCommandBuffer] = None,
) -> RustCommandBatch:
    """Compile the R2 lifecycle subset into contiguous primitive buffers.

    Field layout is stable from R1: ``[action, side, type, flags, order_id,
    target_id, mutate_mask, sequence]`` and ``[qty, price, trigger]``.  This
    lets the optional extension evolve without adding Python object work to the
    bar loop.
    """
    command_tuple = tuple(commands)
    if buffer is None:
        codes = np.full((len(command_tuple), _R1_CODE_WIDTH), -1, dtype=np.int64)
        values = np.zeros((len(command_tuple), _R1_VALUE_WIDTH), dtype=np.float64)
        expiry = np.full(len(command_tuple), -1, dtype=np.int64)
    else:
        codes, values, expiry = buffer.reserve(len(command_tuple))
        codes.fill(-1)
        values.fill(0.0)
        expiry.fill(-1)

    for sequence, command in enumerate(command_tuple):
        codes[sequence, 7] = sequence
        if command.action in (OrderAction.PLACE, OrderAction.REPLACE):
            if command.symbol != symbol:
                raise NativeEventRustBackendError(f"Rust R2 command symbol must be {symbol!r}")
            if command.side not in (OrderSide.BUY, OrderSide.SELL):
                raise NativeEventRustBackendError("Rust R2 PLACE/REPLACE requires BUY or SELL")
            if command.order_type not in (
                OrderType.MARKET,
                OrderType.LIMIT,
                OrderType.STOP_MARKET,
                OrderType.STOP_LIMIT,
            ):
                raise NativeEventRustBackendError("Rust R2 supports MARKET, LIMIT, STOP_MARKET, and STOP_LIMIT only")
            if command.tif is not TimeInForce.GTC:
                raise NativeEventRustBackendError("Rust R2 supports GTC only")
            if command.parent_order_id or command.oco_group_id or command.group_id:
                raise NativeEventRustBackendError("Rust R2 does not support parent, group, or OCO orders")
            if command.activation_policy is not OrderActivationPolicy.IMMEDIATE:
                raise NativeEventRustBackendError("Rust R2 supports immediate order activation only")
            if command.expires_at is not None or command.trigger_price is not None:
                if command.expires_at is not None:
                    raise NativeEventRustBackendError("Rust R2 does not support expiry; use backend='python'")
            codes[sequence, 0] = _R1_ACTION_PLACE if command.action is OrderAction.PLACE else _R2_ACTION_REPLACE
            codes[sequence, 1] = command.side.sign
            codes[sequence, 2] = {
                OrderType.MARKET: _R1_ORDER_MARKET,
                OrderType.LIMIT: _R1_ORDER_LIMIT,
                OrderType.STOP_MARKET: _R2_ORDER_STOP_MARKET,
                OrderType.STOP_LIMIT: _R2_ORDER_STOP_LIMIT,
            }[command.order_type]
            codes[sequence, 3] = _R2_FLAG_REDUCE_ONLY if command.reduce_only else 0
            codes[sequence, 4] = intern_id(command.order_id)
            codes[sequence, 5] = intern_id(command.target_order_id)
            values[sequence, 0] = float(command.qty or 0.0)
            values[sequence, 1] = float(command.price or 0.0)
            values[sequence, 2] = float(command.trigger_price or 0.0)
        elif command.action is OrderAction.CANCEL:
            codes[sequence, 0] = _R1_ACTION_CANCEL
            codes[sequence, 5] = intern_id(command.target_order_id)
        elif command.action is OrderAction.AMEND:
            codes[sequence, 0] = _R2_ACTION_AMEND
            codes[sequence, 5] = intern_id(command.target_order_id)
            mask = 0
            if command.qty is not None:
                mask |= _R2_MUTATE_QTY
                values[sequence, 0] = float(command.qty)
            if command.price is not None:
                mask |= _R2_MUTATE_PRICE
                values[sequence, 1] = float(command.price)
            if command.trigger_price is not None:
                mask |= _R2_MUTATE_TRIGGER
                values[sequence, 2] = float(command.trigger_price)
            codes[sequence, 6] = mask
        else:
            raise NativeEventRustBackendError("Rust R2 supports PLACE, CANCEL, AMEND, and REPLACE commands only")
    return RustCommandBatch(codes=codes, values=values, expiry=expiry, commands=command_tuple)


def compile_rust_batched_tape(
    compiled_commands: CompiledOrderCommandArrays,
    *,
    symbol: str,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Convert the canonical command compiler output to the Rust tape ABI.

    The conversion is deliberately performed once per static tape, not once
    per bar or per trial.  The canonical compiler remains the source of truth
    for bar ordering and dense order identifiers.
    """
    if tuple(compiled_commands.symbols) != (symbol,):
        raise NativeEventRustBackendError("Rust batched tape supports exactly one symbol")
    commands = tuple(command for _, command in compiled_commands.sorted_commands)
    n = len(commands)
    codes = np.full((n, _R1_CODE_WIDTH), -1, dtype=np.int64)
    values = np.zeros((n, _R1_VALUE_WIDTH), dtype=np.float64)
    expiry = np.ascontiguousarray(compiled_commands.command_expires_bar, dtype=np.int64)
    if n:
        codes[:, 0] = np.asarray(compiled_commands.command_action, dtype=np.int64)
        codes[:, 1] = np.asarray(compiled_commands.command_side, dtype=np.int64)
        codes[:, 2] = np.asarray(compiled_commands.command_type, dtype=np.int64)
        codes[:, 3] = np.asarray(compiled_commands.command_reduce_only, dtype=np.int64)
        codes[:, 4] = np.asarray(compiled_commands.command_order_id, dtype=np.int64)
        codes[:, 5] = np.asarray(compiled_commands.command_target_order_id, dtype=np.int64)
        values[:, 0] = np.asarray(compiled_commands.command_qty, dtype=np.float64)
        values[:, 1] = np.asarray(compiled_commands.command_price, dtype=np.float64)
        values[:, 2] = np.asarray(compiled_commands.command_trigger_price, dtype=np.float64)
        codes[:, 7] = np.arange(n, dtype=np.int64)

    for row, command in enumerate(commands):
        if command.symbol not in (None, symbol):
            raise NativeEventRustBackendError(f"Rust batched command symbol must be {symbol!r}")
        if command.action in (OrderAction.PLACE, OrderAction.REPLACE):
            if command.tif is not TimeInForce.GTC:
                raise NativeEventRustBackendError("Rust batched tape supports GTC only")
            if command.parent_order_id or command.group_id or command.oco_group_id:
                raise NativeEventRustBackendError("Rust batched tape does not support parent, group, or OCO orders")
            if command.activation_policy is not OrderActivationPolicy.IMMEDIATE:
                raise NativeEventRustBackendError("Rust batched tape supports immediate activation only")
            if command.expires_at is not None:
                raise NativeEventRustBackendError("Rust batched tape does not support expiry")
            if command.action is OrderAction.REPLACE:
                # CompiledOrderCommandArrays uses the canonical compiler
                # codes (REPLACE=2, AMEND=3), while the stable reactive R2
                # ABI uses AMEND=2, REPLACE=3.
                codes[row, 0] = _R2_ACTION_REPLACE
        elif command.action is OrderAction.CANCEL:
            if command.tif is not TimeInForce.GTC:
                raise NativeEventRustBackendError("Rust batched tape supports GTC only")
        elif command.action is OrderAction.AMEND:
            codes[row, 0] = _R2_ACTION_AMEND
            mask = 0
            if command.qty is not None:
                mask |= _R2_MUTATE_QTY
            if command.price is not None:
                mask |= _R2_MUTATE_PRICE
            if command.trigger_price is not None:
                mask |= _R2_MUTATE_TRIGGER
            codes[row, 6] = mask
        else:
            raise NativeEventRustBackendError("Rust batched tape supports PLACE, CANCEL, AMEND, and REPLACE only")
        if command.expires_at is not None or int(expiry[row]) != -1:
            raise NativeEventRustBackendError("Rust batched tape does not support expiry")

    return (
        np.ascontiguousarray(compiled_commands.command_ptr, dtype=np.int64),
        np.ascontiguousarray(codes, dtype=np.int64),
        np.ascontiguousarray(values, dtype=np.float64),
        np.ascontiguousarray(expiry, dtype=np.int64),
    )


def compile_rust_full_tape(
    compiled_commands: CompiledOrderCommandArrays,
    *,
    buffer: Optional[RustFullCommandBuffer] = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Compile the complete V2 command schema into the Rust 0.4 ABI.

    Code layout is intentionally explicit and integer-only for relationship
    fields.  The compiler's stable row order remains authoritative.
    """
    commands = tuple(command for _, command in compiled_commands.sorted_commands)
    n = len(commands)
    if buffer is None:
        codes = np.full((n, _FULL_CODE_WIDTH), -1, dtype=np.int64)
        values = np.zeros((n, _FULL_VALUE_WIDTH), dtype=np.float64)
        expiry = np.full(n, -1, dtype=np.int64)
    else:
        codes, values, expiry = buffer.reserve(n)
    if n:
        expiry[:] = np.asarray(compiled_commands.command_expires_bar, dtype=np.int64)
    if n:
        codes[:, 0] = np.asarray(compiled_commands.command_action, dtype=np.int64)
        codes[:, 1] = np.asarray(compiled_commands.command_symbol, dtype=np.int64)
        codes[:, 2] = np.asarray(compiled_commands.command_side, dtype=np.int64)
        codes[:, 3] = np.asarray(compiled_commands.command_type, dtype=np.int64)
        codes[:, 4] = np.asarray(compiled_commands.command_tif, dtype=np.int64)
        codes[:, 5] = np.asarray(compiled_commands.command_reduce_only, dtype=np.int64)
        codes[:, 6] = np.asarray(compiled_commands.command_order_id, dtype=np.int64)
        codes[:, 7] = np.asarray(compiled_commands.command_target_order_id, dtype=np.int64)
        codes[:, 8] = np.asarray(compiled_commands.command_parent_order_id, dtype=np.int64)
        codes[:, 9] = np.asarray(compiled_commands.command_group_id, dtype=np.int64)
        codes[:, 10] = np.asarray(compiled_commands.command_oco_group_id, dtype=np.int64)
        codes[:, 11] = np.asarray(compiled_commands.command_activation, dtype=np.int64)
        codes[:, 12] = np.arange(n, dtype=np.int64)
        values[:, 0] = np.asarray(compiled_commands.command_qty, dtype=np.float64)
        values[:, 1] = np.asarray(compiled_commands.command_price, dtype=np.float64)
        values[:, 2] = np.asarray(compiled_commands.command_trigger_price, dtype=np.float64)
    for row, command in enumerate(commands):
        if command.action.value not in {"place", "cancel", "cancel_all", "amend", "replace"}:
            raise NativeEventRustBackendError(f"unsupported full-contract action={command.action!r}")
        if command.expires_at is not None and int(expiry[row]) < 0:
            raise NativeEventRustBackendError("compiled full tape lost command expiry")
    return (
        np.ascontiguousarray(compiled_commands.command_ptr, dtype=np.int64),
        codes,
        values,
        expiry,
    )


def compile_rust_full_reactive_batch(
    commands: Sequence[OrderCommand],
    *,
    symbols: Sequence[str],
    intern_id: Callable[[Optional[str]], int],
    idx: pd.DatetimeIndex,
    buffer: Optional[RustFullCommandBuffer] = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Compile one callback batch for the full ABI without Python objects."""
    rows = tuple(commands)
    if buffer is None:
        codes = np.full((len(rows), _FULL_CODE_WIDTH), -1, dtype=np.int64)
        values = np.zeros((len(rows), _FULL_VALUE_WIDTH), dtype=np.float64)
        expiry = np.full(len(rows), -1, dtype=np.int64)
    else:
        codes, values, expiry = buffer.reserve(len(rows))
    symbol_to_code = {symbol: col for col, symbol in enumerate(symbols)}
    order_type = {OrderType.MARKET: 0, OrderType.LIMIT: 1, OrderType.STOP_MARKET: 2, OrderType.STOP_LIMIT: 3}
    tif = {TimeInForce.GTC: 0, TimeInForce.IOC: 1, TimeInForce.FOK: 2, TimeInForce.GTD: 3}
    action = {OrderAction.PLACE: 0, OrderAction.CANCEL: 1, OrderAction.REPLACE: 2, OrderAction.AMEND: 3, OrderAction.CANCEL_ALL: 4}
    activation = {
        OrderActivationPolicy.IMMEDIATE: 0,
        OrderActivationPolicy.ON_PARENT_FIRST_FILL: 1,
        OrderActivationPolicy.ON_PARENT_FULL_FILL: 2,
    }
    for row, command in enumerate(rows):
        codes[row, 0] = action[command.action]
        codes[row, 1] = -1 if command.symbol is None else symbol_to_code[command.symbol]
        codes[row, 2] = 0 if command.side is None else int(command.side.sign)
        codes[row, 3] = -1 if command.order_type is None else order_type[command.order_type]
        codes[row, 4] = tif[command.tif]
        codes[row, 5] = 1 if command.reduce_only else 0
        codes[row, 6] = intern_id(command.order_id)
        codes[row, 7] = intern_id(command.target_order_id)
        codes[row, 8] = intern_id(command.parent_order_id)
        codes[row, 9] = intern_id(command.group_id)
        codes[row, 10] = intern_id(command.oco_group_id)
        codes[row, 11] = activation[command.activation_policy]
        codes[row, 12] = row
        values[row, 0] = 0.0 if command.qty is None else float(command.qty)
        values[row, 1] = 0.0 if command.price is None else float(command.price)
        values[row, 2] = 0.0 if command.trigger_price is None else float(command.trigger_price)
        if command.expires_at is not None:
            ts = pd.Timestamp(command.expires_at)
            if ts.tz is None:
                ts = ts.tz_localize("UTC")
            else:
                ts = ts.tz_convert("UTC")
            expiry[row] = int(np.searchsorted(idx.asi8, ts.value, side="left"))
    return np.ascontiguousarray(codes), np.ascontiguousarray(values), np.ascontiguousarray(expiry)


def _command_tape_fingerprint(compiled_commands: CompiledOrderCommandArrays) -> str:
    """Return the compile-time identity of an immutable primitive tape."""

    stored = getattr(compiled_commands, "tape_fingerprint", "")
    return stored or command_tape_fingerprint(compiled_commands)


def _build_rust_command_intent_report(
    compiled_commands: CompiledOrderCommandArrays,
) -> pd.DataFrame:
    """Build the command-intent surface independently from lifecycle events.

    Rust owns execution lifecycle rows. The immutable compiler tape owns the
    requested command semantics, so this report is deliberately an intent
    table rather than an alias of ``order_report``.
    """

    rows = []
    for sorted_index, (original_index, command) in enumerate(compiled_commands.sorted_commands):
        metadata = dict(command.metadata)
        rows.append(
            {
                "original_index": int(original_index),
                "sorted_index": int(sorted_index),
                "timestamp": command.timestamp,
                "action": command.action.value,
                "symbol": command.symbol,
                "side": None if command.side is None else command.side.value,
                "order_type": None if command.order_type is None else command.order_type.value,
                "order_id": command.order_id,
                "target_order_id": command.target_order_id,
                "parent_order_id": command.parent_order_id,
                "group_id": command.group_id,
                "oco_group_id": command.oco_group_id,
                "qty": None if command.qty is None else float(command.qty),
                "price": None if command.price is None else float(command.price),
                "trigger_price": None if command.trigger_price is None else float(command.trigger_price),
                "tif": command.tif.value,
                "reduce_only": bool(command.reduce_only),
                "activation_policy": command.activation_policy.value,
                "expires_at": command.expires_at,
                "tag": command.tag,
                "tag_prefix": command.tag_prefix,
                "campaign_id": metadata.get("campaign_id"),
                "cycle_id": metadata.get("cycle_id"),
                "level_id": metadata.get("level_id"),
                "report_kind": "command_intent",
            }
        )
    return pd.DataFrame(rows)


def _payload_value(payload, key: str):
    """Read both the R2 dict boundary and the R2.1 typed score boundary."""

    if isinstance(payload, Mapping):
        return payload[key]
    return getattr(payload, key)


class RustFullRunner:
    """Prepared full-contract Rust tape runner for explicit Rust execution."""

    def __init__(
        self,
        *,
        idx: pd.DatetimeIndex,
        symbols: Sequence[str],
        market_arrays,
        contract_sizes: np.ndarray,
        leverages: np.ndarray,
        fee_rates: np.ndarray,
        initial_capital: float,
        maintenance_ratio: float,
        slippage: float,
        use_funding: bool,
        event_contract: EventClockContract | str = "event_lifecycle_v2_next_bar_close",
        opens_arr: Optional[np.ndarray] = None,
        volumes_arr: Optional[np.ndarray] = None,
        prepared_market_core=None,
        max_tape_cache_bytes: int = 64 * 1024 * 1024,
    ) -> None:
        self.idx = pd.DatetimeIndex(idx)
        self.symbols = tuple(symbols)
        self.contract_sizes = np.ascontiguousarray(contract_sizes, dtype=np.float64)
        self.leverages = np.ascontiguousarray(leverages, dtype=np.float64)
        self.fee_rates = np.ascontiguousarray(fee_rates, dtype=np.float64)
        self.initial_capital = float(initial_capital)
        self.maintenance_ratio = float(maintenance_ratio)
        self.slippage = float(slippage)
        self.use_funding = bool(use_funding)
        self.event_contract = get_event_clock_contract(event_contract)
        if int(max_tape_cache_bytes) < 0:
            raise ValueError("max_tape_cache_bytes must be >= 0")
        self.max_tape_cache_bytes = int(max_tape_cache_bytes)
        if len(self.symbols) == 0 or market_arrays.closes.shape[1] != len(self.symbols):
            raise NativeEventRustBackendError("full Rust runner symbols do not match prepared market arrays")
        self._module = _require_r1_extension()
        status = probe_native_event_rust_extension(module=self._module)
        required = {
            "native_event_v2_full_contract", "native_event_v2_multisymbol",
            "native_event_v2_funding", "native_event_v2_liquidation",
            "native_event_v2_cancel_all_oco", "native_event_v2_tif_expiry",
            "native_event_v2_relationships", "native_event_v2_quantity_preflight",
        }
        missing = sorted(name for name in required if not status.capabilities.get(name, False))
        if missing:
            raise NativeEventRustBackendError(
                "installed _quantbt_native wheel lacks Rust full-contract capabilities: " + ", ".join(missing)
            )
        self.prepared_market_core = prepared_market_core
        if self.prepared_market_core is None:
            shape = market_arrays.closes.shape
            zeros = np.zeros(shape, dtype=np.float64)
            opens = zeros if opens_arr is None else np.ascontiguousarray(opens_arr, dtype=np.float64)
            volumes = zeros if volumes_arr is None else np.ascontiguousarray(volumes_arr, dtype=np.float64)
            self.prepared_market_core = self._module.FullPreparedMarketCore(
                np.ascontiguousarray(self.idx.asi8, dtype=np.int64),
                opens,
                np.ascontiguousarray(market_arrays.highs, dtype=np.float64),
                np.ascontiguousarray(market_arrays.lows, dtype=np.float64),
                np.ascontiguousarray(market_arrays.closes, dtype=np.float64),
                volumes,
                np.ascontiguousarray(market_arrays.funding, dtype=np.float64),
                np.ascontiguousarray(market_arrays.is_funding_bar, dtype=np.bool_),
            )
        self._command_buffer = RustFullCommandBuffer()
        self._cached_tape_fingerprint: Optional[str] = None
        self._cached_tape_arrays: Optional[tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]] = None
        self._cached_tape_bytes = 0
        self._session = None

    def _new_session(self):
        if self._session is None:
            self._session = self._module.FullReactiveSessionCore.from_prepared(
                self.prepared_market_core,
                self.contract_sizes,
                self.leverages,
                self.fee_rates,
                self.initial_capital,
                self.maintenance_ratio,
                self.slippage,
                self.use_funding,
            )
        else:
            self._session.reset()
        if not hasattr(self._session, "set_event_contract"):
            if self.event_contract.contract_code != 2:
                raise NativeEventRustBackendError(
                    "installed _quantbt_native wheel does not expose versioned event contracts"
                )
        else:
            self._session.set_event_contract(self.event_contract.contract_code)
        return self._session

    def _tape_arrays(self, compiled_commands: CompiledOrderCommandArrays):
        fingerprint = getattr(compiled_commands, "tape_fingerprint", "") or _command_tape_fingerprint(
            compiled_commands
        )
        if fingerprint == self._cached_tape_fingerprint and self._cached_tape_arrays is not None:
            return self._cached_tape_arrays
        arrays = compile_rust_full_tape(compiled_commands, buffer=self._command_buffer)
        byte_size = sum(int(array.nbytes) for array in arrays)
        if byte_size <= self.max_tape_cache_bytes:
            self._cached_tape_fingerprint = fingerprint
            self._cached_tape_arrays = arrays
            self._cached_tape_bytes = byte_size
        else:
            self.clear_tape_cache()
        return arrays

    @property
    def tape_cache_bytes(self) -> int:
        """Resident bytes held by the bounded full-contract tape cache."""

        return int(self._cached_tape_bytes)

    def clear_tape_cache(self) -> None:
        """Release compiled tape arrays while retaining prepared market state."""

        self._cached_tape_fingerprint = None
        self._cached_tape_arrays = None
        self._cached_tape_bytes = 0
        self._command_buffer.clear()

    def clear_caches(self) -> None:
        """Release runner-local tape/session caches without mutating market data."""

        self.clear_tape_cache()
        self._session = None

    def cache_info(self) -> Mapping[str, int]:
        """Return observable bounded-cache and command-buffer counters."""

        info = {
            "tape_cache_bytes": self.tape_cache_bytes,
            "tape_cache_entries": int(self._cached_tape_arrays is not None),
            "command_buffer_capacity": self._command_buffer.capacity,
            "command_buffer_growth_count": self._command_buffer.growth_count,
            "commands_compiled": self._command_buffer.commands_compiled,
        }
        if self._session is not None and hasattr(self._session, "order_arena_counters"):
            slots, capacity, compactions, removed = self._session.order_arena_counters()
            info.update(
                {
                    "order_arena_slots": int(slots),
                    "order_arena_capacity": int(capacity),
                    "order_compactions": int(compactions),
                    "terminal_orders_removed": int(removed),
                }
            )
        if self._session is not None and hasattr(self._session, "step_buffer_capacities"):
            fills, events, active = self._session.step_buffer_capacities()
            info.update(
                {
                    "step_fill_buffer_capacity": int(fills),
                    "step_event_buffer_capacity": int(events),
                    "step_active_order_buffer_capacity": int(active),
                }
            )
        if self._session is not None and hasattr(self._session, "margin_recompute_count"):
            info["margin_recompute_count"] = int(self._session.margin_recompute_count())
        if self._session is not None and hasattr(self._session, "engine_scan_counters"):
            expiry, matching, relationship = self._session.engine_scan_counters()
            info.update(
                {
                    "expiry_scan_count": int(expiry),
                    "matching_scan_count": int(matching),
                    "relationship_scan_count": int(relationship),
                }
            )
        return info

    def run_tape_score(self, compiled_commands: CompiledOrderCommandArrays) -> Mapping[str, object]:
        ptr, codes, values, expiry = self._tape_arrays(compiled_commands)
        return self._new_session().run_tape_score(ptr, codes, values, expiry)

    def run_tape_compact(self, compiled_commands: CompiledOrderCommandArrays) -> Mapping[str, object]:
        """Run one tape with dense account paths but without audit row ledgers.

        This is an internal research/metrics helper. It preserves the same
        matching and accounting path as score/audit while avoiding fill/event
        materialization; endpoint report adaptation remains outside Rust.
        """

        ptr, codes, values, expiry = self._tape_arrays(compiled_commands)
        session = self._new_session()
        if not hasattr(session, "run_tape_compact"):
            raise NativeEventRustBackendError(
                "installed _quantbt_native wheel does not expose the ABI 0.5 compact static-tape profile"
            )
        payload = dict(session.run_tape_compact(ptr, codes, values, expiry))
        for key in (
            "equity", "positions", "fees", "turnover", "funding", "initial_margin", "maintenance_margin",
        ):
            payload[key] = np.ascontiguousarray(np.asarray(payload[key]), dtype=np.float64)
        payload["positions"] = payload["positions"].reshape(len(self.idx), len(self.symbols))
        return payload

    def run_tape_audit(self, compiled_commands: CompiledOrderCommandArrays) -> RustFullAuditResult:
        ptr, codes, values, expiry = self._tape_arrays(compiled_commands)
        payload = self._new_session().run_tape_audit(ptr, codes, values, expiry)
        float_keys = (
            "equity", "positions", "fees", "turnover", "funding", "initial_margin",
            "maintenance_margin", "fill_qty", "fill_price", "fill_fee",
        )
        int_keys = (
            "fill_bar", "fill_order_id", "fill_symbol", "fill_side", "event_bar",
            "event_kind", "event_status", "event_order_id", "event_target_id",
            "event_symbol", "event_reject_code",
        )
        arrays = {
            key: np.ascontiguousarray(np.asarray(payload[key]), dtype=np.float64)
            for key in float_keys
        }
        arrays.update(
            {
                key: np.ascontiguousarray(np.asarray(payload[key]), dtype=np.int64)
                for key in int_keys
            }
        )
        arrays["fill_reason"] = np.ascontiguousarray(
            np.asarray(payload.get("fill_reason", np.zeros(len(arrays["fill_bar"]), dtype=np.int64)))
        )
        arrays["fill_ambiguity"] = np.ascontiguousarray(
            np.asarray(payload.get("fill_ambiguity", np.zeros(len(arrays["fill_bar"]), dtype=np.int64)))
        )
        arrays["positions"] = np.asarray(arrays["positions"], dtype=np.float64).reshape(len(self.idx), len(self.symbols))
        return RustFullAuditResult(
            **arrays,
            total_fee=float(payload["total_fee"]), total_turnover=float(payload["total_turnover"]),
            total_funding=float(payload["total_funding"]), fill_count=int(payload["fill_count"]),
            event_count=int(payload["event_count"]), rejected_count=int(payload["rejected_count"]),
            canceled_count=int(payload["canceled_count"]), max_initial_margin=float(payload["max_initial_margin"]),
            max_maintenance_margin=float(payload["max_maintenance_margin"]), liquidated=bool(payload["liquidated"]),
            liquidation_bar=int(payload["liquidation_bar"]), liquidation_reason=int(payload["liquidation_reason"]),
            id_values=tuple(compiled_commands.id_values),
            command_report=_build_rust_command_intent_report(compiled_commands),
            command_metadata={
                command.order_id: dict(command.metadata)
                for _, command in compiled_commands.sorted_commands
                if command.order_id
            },
        )


class RustBatchedRunner:
    """Single-symbol Rust full-tape runner with prepared-market reuse.

    This is an explicit experimental backend.  It accepts a precompiled
    static command tape and never invokes arbitrary Python strategy callbacks.
    Unsupported funding, liquidation, quantity constraints, TIF and package
    semantics fail before crossing the Rust boundary.
    """

    def __init__(
        self,
        *,
        idx: pd.DatetimeIndex,
        symbols: Sequence[str],
        market_arrays,
        contract_size: float = 1.0,
        leverage: float = 1.0,
        fee_rate: float = 0.0,
        initial_capital: float = 1_000.0,
        maintenance_ratio: float = 0.0,
        slippage: float = 0.0,
        use_funding: bool = False,
        prepared_market_core=None,
        max_tape_cache_bytes: int = 64 * 1024 * 1024,
    ) -> None:
        if len(symbols) != 1:
            raise NativeEventRustBackendError("Rust batched runner supports exactly one symbol")
        if use_funding:
            raise NativeEventRustBackendError("Rust batched runner does not support funding")
        if float(maintenance_ratio) != 0.0:
            raise NativeEventRustBackendError("Rust batched runner does not support liquidation")
        if float(contract_size) <= 0.0 or float(leverage) <= 0.0:
            raise ValueError("contract_size and leverage must be > 0")
        if float(fee_rate) < 0.0 or float(slippage) < 0.0:
            raise ValueError("fee_rate and slippage must be >= 0")
        if int(max_tape_cache_bytes) < 0:
            raise ValueError("max_tape_cache_bytes must be >= 0")
        self.idx = pd.DatetimeIndex(idx)
        self.symbols = tuple(symbols)
        self.contract_size = float(contract_size)
        self.leverage = float(leverage)
        self.fee_rate = float(fee_rate)
        self.initial_capital = float(initial_capital)
        self.maintenance_ratio = float(maintenance_ratio)
        self.slippage = float(slippage)
        self.max_tape_cache_bytes = int(max_tape_cache_bytes)
        self._module = _require_r1_extension()
        status = probe_native_event_rust_extension(module=self._module)
        required = (
            "rust_batched_tape",
            "rust_batched_tape_score",
            "rust_batched_tape_audit",
            "rust_batched_tape_sparse",
        )
        missing = [name for name in required if not status.capabilities.get(name, False)]
        if missing:
            raise NativeEventRustBackendError(
                "installed _quantbt_native wheel lacks Rust batched capabilities: " + ", ".join(missing)
            )
        self.prepared_market_core = prepared_market_core
        self._cached_tape_fingerprint: Optional[str] = None
        self._cached_tape_arrays: Optional[tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]] = None
        self._cached_tape_bytes = 0
        if self.prepared_market_core is None:
            close = np.ascontiguousarray(market_arrays.closes[:, 0], dtype=np.float64)
            self.prepared_market_core = self._module.PreparedMarketCore(
                np.ascontiguousarray(self.idx.asi8, dtype=np.int64),
                close,
                np.ascontiguousarray(market_arrays.highs[:, 0], dtype=np.float64),
                np.ascontiguousarray(market_arrays.lows[:, 0], dtype=np.float64),
                close,
                np.zeros(len(self.idx), dtype=np.float64),
                np.zeros(len(self.idx), dtype=np.float64),
                np.zeros(len(self.idx), dtype=np.bool_),
            )

    def open_sparse_session(
        self,
        compiled_commands: Optional[CompiledOrderCommandArrays] = None,
    ) -> "RustBatchedSession":
        """Open a stateful sparse session over one compiled command tape.

        ``run_until`` keeps the Rust lifecycle state between calls.  The
        tape is compiled once and the session only returns sparse fills/events
        plus scalar accounting, so strategy services do not pay for a dense
        per-bar result path on every chunk.
        """
        return RustBatchedSession(self, compiled_commands)

    # A descriptive alias for callers that use the shorter session wording.
    new_sparse_session = open_sparse_session

    def _new_session(self):
        return self._module.ReactiveSessionCore.from_prepared(
            self.prepared_market_core,
            self.contract_size,
            self.leverage,
            self.fee_rate,
            self.initial_capital,
            self.maintenance_ratio,
            self.slippage,
            False,
        )

    def _tape_arrays(self, compiled_commands: CompiledOrderCommandArrays):
        fingerprint = getattr(compiled_commands, "tape_fingerprint", "") or _command_tape_fingerprint(
            compiled_commands
        )
        if fingerprint == self._cached_tape_fingerprint and self._cached_tape_arrays is not None:
            return self._cached_tape_arrays
        arrays = compile_rust_batched_tape(compiled_commands, symbol=self.symbols[0])
        byte_size = sum(int(array.nbytes) for array in arrays)
        if byte_size <= self.max_tape_cache_bytes:
            self._cached_tape_fingerprint = fingerprint
            self._cached_tape_arrays = arrays
            self._cached_tape_bytes = byte_size
        else:
            self.clear_tape_cache()
        return arrays

    @property
    def tape_cache_bytes(self) -> int:
        """Current resident size of the bounded primitive tape cache."""

        return int(self._cached_tape_bytes)

    def clear_tape_cache(self) -> None:
        """Release cached command arrays and their fingerprint immediately."""

        self._cached_tape_fingerprint = None
        self._cached_tape_arrays = None
        self._cached_tape_bytes = 0

    def run_tape_score(self, compiled_commands: CompiledOrderCommandArrays) -> RustBatchedScoreResult:
        """Run a complete static tape through one PyO3 call and return scalars."""
        ptr, codes, values, expiry = self._tape_arrays(compiled_commands)
        payload = self._new_session().run_tape_score(ptr, codes, values, expiry)
        return RustBatchedScoreResult(
            final_equity=float(_payload_value(payload, "final_equity")),
            final_position=float(_payload_value(payload, "final_position")),
            total_fee=float(_payload_value(payload, "total_fee")),
            total_turnover=float(_payload_value(payload, "total_turnover")),
            fill_count=int(_payload_value(payload, "fill_count")),
            event_count=int(_payload_value(payload, "event_count")),
            rejected_count=int(_payload_value(payload, "rejected_count")),
            canceled_count=int(_payload_value(payload, "canceled_count")),
            max_initial_margin=float(_payload_value(payload, "max_initial_margin")),
            max_maintenance_margin=float(_payload_value(payload, "max_maintenance_margin")),
            bars=int(_payload_value(payload, "bars")),
            metadata={"backend": "rust_batched", "mode": "score", "pycalls": 1},
        )

    def run_tape_audit(self, compiled_commands: CompiledOrderCommandArrays) -> RustBatchedAuditResult:
        """Run a complete tape and return contiguous struct-of-arrays audit data."""
        ptr, codes, values, expiry = self._tape_arrays(compiled_commands)
        payload = self._new_session().run_tape_audit(ptr, codes, values, expiry)
        arrays = {key: np.ascontiguousarray(np.asarray(payload[key])) for key in (
            "equity", "positions", "fees", "turnover", "initial_margin", "maintenance_margin",
            "fill_bar", "fill_order_id", "fill_side", "fill_qty", "fill_price", "fill_fee",
            "event_bar", "event_kind", "event_status", "event_order_id", "event_target_id",
        )}
        return RustBatchedAuditResult(
            **arrays,
            total_fee=float(payload["total_fee"]),
            total_turnover=float(payload["total_turnover"]),
            fill_count=int(payload["fill_count"]),
            event_count=int(payload["event_count"]),
            rejected_count=int(payload["rejected_count"]),
            canceled_count=int(payload["canceled_count"]),
            max_initial_margin=float(payload["max_initial_margin"]),
            max_maintenance_margin=float(payload["max_maintenance_margin"]),
            metadata={"backend": "rust_batched", "mode": "audit", "pycalls": 1},
            id_values=tuple(compiled_commands.id_values),
        )


class RustBatchedSession:
    """Stateful single-symbol sparse continuation over a static tape."""

    def __init__(
        self,
        runner: RustBatchedRunner,
        compiled_commands: Optional[CompiledOrderCommandArrays] = None,
    ) -> None:
        self.runner = runner
        self.compiled_commands = compiled_commands
        self._core = runner._new_session()
        self._tape_arrays_cache = (
            None if compiled_commands is None else runner._tape_arrays(compiled_commands)
        )
        self.next_bar = 0

    @staticmethod
    def _arrays(payload: Mapping[str, object]) -> dict[str, np.ndarray]:
        return {
            key: np.ascontiguousarray(np.asarray(payload[key]))
            for key in (
                "wake_bar",
                "wake_kind",
                "fill_bar",
                "fill_order_id",
                "fill_side",
                "fill_qty",
                "fill_price",
                "fill_fee",
                "event_bar",
                "event_kind",
                "event_status",
                "event_order_id",
                "event_target_id",
            )
        }

    def run_until(
        self,
        stop_bar: int,
        command_batch: Optional[CompiledOrderCommandArrays] = None,
        *,
        wake_on_fill: bool = True,
        wake_on_order_event: bool = True,
        wake_on_liquidation: bool = True,
    ) -> RustBatchedChunkResult:
        """Advance through ``stop_bar`` without crossing Python per bar.

        The first call starts at bar zero and later calls continue at the bar
        after the previous chunk.  ``command_batch`` is optional after a tape
        was supplied to :meth:`open_sparse_session`; replacing the tape
        mid-session is rejected to avoid an accounting mismatch.
        """
        if command_batch is not None:
            if self.compiled_commands is not None and command_batch is not self.compiled_commands:
                raise NativeEventRustBackendError("cannot replace the command tape during a sparse session")
            self.compiled_commands = command_batch
        if self.compiled_commands is None:
            raise NativeEventRustBackendError("run_until requires a compiled command tape")
        stop = int(stop_bar)
        if stop < self.next_bar:
            raise ValueError("run_until stop_bar must advance beyond the previous chunk")
        if self._tape_arrays_cache is None:
            self._tape_arrays_cache = self.runner._tape_arrays(self.compiled_commands)
        ptr, codes, values, expiry = self._tape_arrays_cache
        payload = self._core.run_until(
            stop,
            ptr,
            codes,
            values,
            expiry,
            bool(wake_on_fill),
            bool(wake_on_order_event),
            bool(wake_on_liquidation),
        )
        arrays = self._arrays(payload)
        self.next_bar = stop + 1
        return RustBatchedChunkResult(
            start_bar=int(payload["start_bar"]),
            stop_bar=int(payload["stop_bar"]),
            final_equity=float(payload["final_equity"]),
            final_position=float(payload["final_position"]),
            total_fee=float(payload["total_fee"]),
            total_turnover=float(payload["total_turnover"]),
            fill_count=int(payload["fill_count"]),
            event_count=int(payload["event_count"]),
            rejected_count=int(payload["rejected_count"]),
            canceled_count=int(payload["canceled_count"]),
            max_initial_margin=float(payload["max_initial_margin"]),
            max_maintenance_margin=float(payload["max_maintenance_margin"]),
            liquidation_seen=bool(payload["liquidation_seen"]),
            **arrays,
            metadata={
                "backend": "rust_batched",
                "mode": "sparse",
                "pycalls": 1,
                "dense_paths_materialized": False,
                "wake_on_fill": bool(wake_on_fill),
                "wake_on_order_event": bool(wake_on_order_event),
                "wake_on_liquidation": bool(wake_on_liquidation),
            },
        )

    def reset(self) -> None:
        """Reset lifecycle/accounting while retaining Rust buffer capacity."""

        self._core.reset()
        self.next_bar = 0


class RustReactiveSessionAdapter:
    """R2 bridge: Python callbacks around one Rust state transition per bar."""

    def __init__(
        self,
        *,
        idx: pd.DatetimeIndex,
        symbols: Sequence[str],
        market_arrays,
        opens_arr: np.ndarray,
        volumes_arr: np.ndarray,
        constraints,
        contract_sizes: np.ndarray,
        leverages: np.ndarray,
        fee_rates: np.ndarray,
        initial_capital: float,
        maintenance_ratio: float,
        slippage: float,
        use_funding: bool,
        event_contract: EventClockContract | str = "event_lifecycle_v2_next_bar_close",
        retain_terminal_orders: bool = True,
        score_requirements=None,
        prepared_market_core=None,
    ) -> None:
        self._module = _require_r1_extension()
        extension_status = probe_native_event_rust_extension(module=self._module)
        self._full_contract = bool(extension_status.capabilities.get("native_event_v2_full_contract", False))
        if not self._full_contract:
            validate_rust_r1_support(
                symbols=symbols,
                constraints=constraints,
                use_funding=use_funding,
                maintenance_ratio=maintenance_ratio,
            )
        self.idx = idx
        self.symbols = list(symbols)
        self.symbols_tuple = tuple(symbols)
        self.market_arrays = market_arrays
        self.opens_arr = opens_arr
        self.volumes_arr = volumes_arr
        self.constraints = constraints
        self.contract_sizes = np.asarray(contract_sizes, dtype=np.float64)
        self.leverages = np.asarray(leverages, dtype=np.float64)
        self.fee_rates = np.asarray(fee_rates, dtype=np.float64)
        self.initial_capital = float(initial_capital)
        self.maintenance_ratio = float(maintenance_ratio)
        self.slippage = float(slippage)
        self.use_funding = bool(use_funding)
        self.event_contract = get_event_clock_contract(event_contract)
        self.retain_terminal_orders = bool(retain_terminal_orders)
        self.score_requirements = score_requirements
        self.scalar_score = bool(
            score_requirements is not None
            and score_requirements.need_trade_stats
            and not score_requirements.need_equity_path
            and not score_requirements.need_position_path
            and not score_requirements.need_fee_path
            and not score_requirements.need_funding_path
            and not score_requirements.need_margin_path
        )
        self.retain_fill_ledger = bool(score_requirements is None or score_requirements.need_fill_ledger)
        self.retain_event_ledger = bool(score_requirements is None or score_requirements.need_event_ledger)
        self.emit_context_fills = bool(
            score_requirements is None or score_requirements.need_context_fills
        )
        self.emit_context_events = bool(
            score_requirements is None or score_requirements.need_context_events
        )
        self.emit_context_active_orders = bool(
            score_requirements is None or score_requirements.need_context_active_orders
        )
        self.emit_context_positions = bool(
            score_requirements is None or score_requirements.need_context_positions
        )
        self.emit_context_margin = bool(
            score_requirements is None or score_requirements.need_context_margin
        )
        self.compact_score_state = bool(
            score_requirements is not None
            and not score_requirements.need_context_fills
            and not score_requirements.need_context_events
            and not score_requirements.need_context_active_orders
            and not score_requirements.need_context_positions
            and not score_requirements.need_context_margin
            and not score_requirements.need_fill_ledger
            and not score_requirements.need_event_ledger
            and not score_requirements.need_terminal_orders
        )
        self._r2_capable = bool(extension_status.capabilities.get("r2_stop_amend_replace_reduce_only_constraints", False))
        self._prepared_market_core_capable = bool(extension_status.capabilities.get("prepared_market_core", False))
        if self.constraints.enabled and not self._r2_capable:
            raise NativeEventRustBackendError(
                "installed _quantbt_native wheel is R1-only and cannot apply quantity constraints; rebuild/install R2 or use backend='python'"
            )
        self._id_to_code: dict[str, int] = {}
        self._id_values: list[str] = []
        self._commands_by_id: dict[str, OrderCommand] = {}
        self._command_buffer = RustCommandBuffer()
        self._full_command_buffer = RustFullCommandBuffer()
        self.execution_counters = {
            "bars_processed": 0,
            "bars_with_commands": 0,
            "contexts_materialized": 0,
            "timestamp_objects_materialized": 0,
            "commands_compiled": 0,
            "command_buffer_growths": 0,
            "bytes_copied_to_rust": 0,
            "active_snapshot_materializations": 0,
            "empty_command_batches_skipped": 0,
            "constraint_preflight_calls": 0,
            "constraint_preflight_skipped": 0,
            "commands_retimed": 0,
            "commands_quantized": 0,
            "pyo3_calls": 0,
            "gil_reacquisitions": 0,
            "callback_projection_bytes": 0,
            "market_bytes_copied": 0,
            "command_bytes_copied": 0,
            "result_bytes_copied": 0,
            "position_delta_rows": 0,
            "order_delta_rows": 0,
            "primitive_command_batches": 0,
            "primitive_command_rows": 0,
            "writer_python_command_objects": 0,
        }
        self.scheduled: dict[int, list[OrderCommand]] = {}
        self._scheduled_primitive: dict[int, list[_ScheduledPrimitiveBatch]] = {}
        self._writer_order_handles: set[int] = set()
        self.fills: list[NativeFillEvent] = []
        self.events: list[NativeOrderEvent] = []
        self.fills_by_bar: dict[int, list[NativeFillEvent]] = {}
        self.events_by_bar: dict[int, list[NativeOrderEvent]] = {}
        self._projection = _RustNativeProjection(
            positions=np.zeros(len(self.symbols), dtype=np.float64),
            equity=float(initial_capital),
        )
        self.processed_bar = -1
        self.generation = 0
        self.closed = False
        self.poisoned = False
        self.reset_count = 0
        n_bars = len(idx)
        self.equity_path = None if self.scalar_score else np.zeros(n_bars, dtype=np.float64)
        self.pos_path = None if self.scalar_score else np.zeros((n_bars, len(self.symbols)), dtype=np.float64)
        self.fee_path = None if self.scalar_score else np.zeros(n_bars, dtype=np.float64)
        self.turnover_path = None if self.scalar_score else np.zeros(n_bars, dtype=np.float64)
        self.funding_path = None if self.scalar_score else np.zeros(n_bars, dtype=np.float64)
        self.initial_margin_path = None if self.scalar_score else np.zeros(n_bars, dtype=np.float64)
        self.maintenance_margin_path = None if self.scalar_score else np.zeros(n_bars, dtype=np.float64)
        self.rejected_bar = None if self.scalar_score else np.zeros(n_bars, dtype=np.int64)
        self.canceled_bar = None if self.scalar_score else np.zeros(n_bars, dtype=np.int64)
        self.empty_fills: tuple[NativeFillEvent, ...] = ()
        self.empty_events: tuple[NativeOrderEvent, ...] = ()
        self.empty_active_orders: tuple[NativeActiveOrderSnapshot, ...] = ()
        self._active_snapshot_cache: tuple[NativeActiveOrderSnapshot, ...] = ()
        if self.scalar_score:
            # Import lazily to avoid the native_event <-> Rust adapter import
            # cycle. The class is shared with Python scalar scoring so metric
            # definitions remain identical across backends.
            from .native_event import _OnlineScoreState

            self.online_score = _OnlineScoreState(self.initial_capital, len(self.symbols))
        else:
            self.online_score = None
        self.prepared_market_core = prepared_market_core
        if self._full_contract and hasattr(self._module, "FullPreparedMarketCore"):
            if self.prepared_market_core is None:
                self.prepared_market_core = self._module.FullPreparedMarketCore(
                    np.ascontiguousarray(idx.asi8, dtype=np.int64),
                    np.ascontiguousarray(opens_arr, dtype=np.float64),
                    np.ascontiguousarray(market_arrays.highs, dtype=np.float64),
                    np.ascontiguousarray(market_arrays.lows, dtype=np.float64),
                    np.ascontiguousarray(market_arrays.closes, dtype=np.float64),
                    np.ascontiguousarray(volumes_arr, dtype=np.float64),
                    np.ascontiguousarray(market_arrays.funding, dtype=np.float64),
                    np.ascontiguousarray(market_arrays.is_funding_bar, dtype=np.bool_),
                )
            self._core = self._module.FullReactiveSessionCore.from_prepared(
                self.prepared_market_core,
                np.ascontiguousarray(self.contract_sizes, dtype=np.float64),
                np.ascontiguousarray(self.leverages, dtype=np.float64),
                np.ascontiguousarray(self.fee_rates, dtype=np.float64),
                float(initial_capital), float(maintenance_ratio), float(slippage), bool(use_funding),
            )
            if not hasattr(self._core, "set_event_contract"):
                if self.event_contract.contract_code != 2:
                    raise NativeEventRustBackendError(
                        "installed _quantbt_native wheel does not expose versioned event contracts"
                    )
            else:
                self._core.set_event_contract(self.event_contract.contract_code)
            # Accounting and the live position vector are always required by
            # the Python adapter.  Other projections are requested only when
            # the strategy/ledger can observe them.
            output_mask = _FULL_OUTPUT_POSITIONS
            if self.retain_fill_ledger or self.emit_context_fills:
                output_mask |= _FULL_OUTPUT_FILLS
            if self.retain_event_ledger or self.emit_context_events:
                output_mask |= _FULL_OUTPUT_EVENTS
            if self.emit_context_active_orders:
                output_mask |= _FULL_OUTPUT_ACTIVE_ORDERS
            self._core.set_output_mask(output_mask)
        elif self._prepared_market_core_capable and hasattr(self._module, "PreparedMarketCore"):
            if self.prepared_market_core is None:
                self.prepared_market_core = self._module.PreparedMarketCore(
                    np.ascontiguousarray(idx.asi8, dtype=np.int64),
                    np.ascontiguousarray(opens_arr[:, 0], dtype=np.float64),
                    np.ascontiguousarray(market_arrays.highs[:, 0], dtype=np.float64),
                    np.ascontiguousarray(market_arrays.lows[:, 0], dtype=np.float64),
                    np.ascontiguousarray(market_arrays.closes[:, 0], dtype=np.float64),
                    np.ascontiguousarray(volumes_arr[:, 0], dtype=np.float64),
                    np.zeros(n_bars, dtype=np.float64),
                    np.zeros(n_bars, dtype=np.bool_),
                )
            self._core = self._module.ReactiveSessionCore.from_prepared(
                self.prepared_market_core,
                float(self.contract_sizes[0]),
                float(self.leverages[0]),
                float(self.fee_rates[0]),
                float(initial_capital),
                float(maintenance_ratio),
                float(slippage),
                False,
            )
        else:
            self.prepared_market_core = None
            self._core = self._module.ReactiveSessionCore(
                np.ascontiguousarray(idx.asi8, dtype=np.int64),
                np.ascontiguousarray(opens_arr[:, 0], dtype=np.float64),
                np.ascontiguousarray(market_arrays.highs[:, 0], dtype=np.float64),
                np.ascontiguousarray(market_arrays.lows[:, 0], dtype=np.float64),
                np.ascontiguousarray(market_arrays.closes[:, 0], dtype=np.float64),
                np.ascontiguousarray(volumes_arr[:, 0], dtype=np.float64),
                np.zeros(n_bars, dtype=np.float64),
                np.zeros(n_bars, dtype=np.bool_),
                float(self.contract_sizes[0]),
                float(self.leverages[0]),
                float(self.fee_rates[0]),
                float(initial_capital),
                float(maintenance_ratio),
                float(slippage),
                False,
            )
        self.size_helper = self._size_order

    @property
    def current_pos(self) -> np.ndarray:
        return self._projection.positions

    @property
    def equity(self) -> float:
        return self._projection.equity

    @property
    def last_initial_margin(self) -> float:
        return self._projection.initial_margin

    @property
    def last_maintenance_margin(self) -> float:
        return self._projection.maintenance_margin

    @property
    def total_fee(self) -> float:
        return self._projection.total_fee

    @property
    def total_funding(self) -> float:
        return self._projection.total_funding

    @property
    def total_turnover(self) -> float:
        return self._projection.total_turnover

    @property
    def fill_count(self) -> int:
        return self._projection.fill_count

    @property
    def event_count(self) -> int:
        return self._projection.event_count

    @property
    def rejected_count(self) -> int:
        return self._projection.rejected_count

    @property
    def canceled_count(self) -> int:
        return self._projection.canceled_count

    @property
    def liquidated(self) -> bool:
        return self._projection.liquidated

    @property
    def liquidation_bar(self) -> int:
        return self._projection.liquidation_bar

    @property
    def liquidation_reason(self) -> int:
        return self._projection.liquidation_reason

    def _intern_id(self, value: Optional[str]) -> int:
        if value is None:
            return -1
        if value not in self._id_to_code:
            self._id_to_code[value] = len(self._id_values)
            self._id_values.append(value)
        return self._id_to_code[value]

    def _id_from_code(self, value: int) -> Optional[str]:
        return self._id_values[value] if 0 <= int(value) < len(self._id_values) else None

    def _size_order(self, symbol: str, notional: float, price: float, side: OrderSide = OrderSide.BUY) -> float:
        if symbol not in self.symbols:
            raise ValueError(f"unknown symbol={symbol!r}")
        if price <= 0.0:
            raise ValueError("price must be > 0")
        column = self.symbols.index(symbol)
        return abs(float(notional) / (float(price) * float(self.contract_sizes[column])))

    def _quantize_r2_commands(self, bar: int, commands: Sequence[OrderCommand]) -> tuple[OrderCommand, ...]:
        """Apply the canonical quantity filter at the same bar as replay preflight.

        Reactive commands cannot be preflighted before a strategy emits them.
        The static replay performs the equivalent filtering over the emitted
        tape; this method makes explicit Rust follow that exact exchange-rule
        contract without changing the command tape or endpoint API.
        """
        if not self.constraints.enabled:
            self.execution_counters["constraint_preflight_skipped"] += int(bool(commands))
            return tuple(commands)
        self.execution_counters["constraint_preflight_calls"] += int(bool(commands))
        out: list[OrderCommand] = []
        for command in commands:
            if command.action not in (OrderAction.PLACE, OrderAction.REPLACE) or command.qty is None:
                out.append(command)
                continue
            try:
                column = self.symbols.index(command.symbol)
            except ValueError as exc:
                raise NativeEventRustBackendError(
                    f"quantity preflight received unknown symbol={command.symbol!r}"
                ) from exc
            close = float(self.market_arrays.closes[int(bar), column])
            price = float(command.price) if command.price is not None else close
            signed = command.signed_qty
            quantity = abs(
                quantize_signed_quantity(
                    signed,
                    price,
                    float(self.contract_sizes[column]),
                    float(self.constraints.qty_step[column]),
                    float(self.constraints.min_qty[column]),
                    float(self.constraints.min_notional[column]),
                )
            )
            if quantity <= 0.0:
                continue
            if abs(quantity - float(command.qty)) > 1e-12:
                out.append(replace(command, qty=quantity))
            else:
                out.append(command)
        self.execution_counters["commands_quantized"] += len(commands)
        return tuple(out)

    @staticmethod
    def _commands_require_r2(commands: Sequence[OrderCommand]) -> bool:
        return any(
            command.action in (OrderAction.AMEND, OrderAction.REPLACE)
            or command.reduce_only
            or command.order_type in (OrderType.STOP_MARKET, OrderType.STOP_LIMIT)
            for command in commands
        )

    def _require_r2_for_commands(self, commands: Sequence[OrderCommand]) -> None:
        if self._commands_require_r2(commands) and not self._r2_capable:
            raise NativeEventRustBackendError(
                "installed _quantbt_native wheel is R1-only and cannot execute R2 lifecycle commands; rebuild/install R2 or use backend='python'"
            )

    def schedule(self, bar: int, commands: Sequence[OrderCommand]) -> None:
        if commands and int(bar) < len(self.idx):
            self.scheduled.setdefault(int(bar), []).extend(commands)

    def schedule_command_batch(self, bar: int, batch: CommandBatchView) -> dict[str, object]:
        """Compile a numeric writer batch without allocating ``OrderCommand``.

        The arrays become session-owned because the strategy writer is reused
        on the next callback. Quantity filters execute at the same effective
        bar as the compatibility command path.
        """

        if not self._full_contract:
            raise NativeEventRustBackendError(
                "numeric command batches require native_event_v2_full_contract"
            )
        batch._check()
        n_rows = int(batch.length)
        if n_rows == 0 or int(bar) >= len(self.idx):
            return {
                "changed_count": 0,
                "dropped_count": 0,
                "accepted_count": 0,
                "dropped_rows": (),
            }
        writer = batch.writer
        actions = np.asarray(writer.action[:n_rows], dtype=np.int64)
        symbol_ids = np.asarray(writer.symbol_id[:n_rows], dtype=np.int64)
        sides = np.asarray(writer.side[:n_rows], dtype=np.int64)
        order_types = np.asarray(writer.order_type[:n_rows], dtype=np.int64)
        quantities = np.asarray(writer.qty[:n_rows], dtype=np.float64).copy()
        prices = np.asarray(writer.price[:n_rows], dtype=np.float64)
        place_like = np.isin(actions, (0, 2))
        if np.any(place_like & ((symbol_ids < 0) | (symbol_ids >= len(self.symbols)))):
            raise CommandValidationError("numeric PLACE/REPLACE requires a valid symbol_id")
        if np.any(place_like & (sides == 0)):
            raise CommandValidationError("numeric PLACE/REPLACE requires a non-zero side")
        if np.any(place_like & ((order_types < 0) | (order_types > 3))):
            raise CommandValidationError("numeric PLACE/REPLACE requires a supported order type")
        if np.any(place_like & (~np.isfinite(quantities) | (quantities <= 0.0))):
            raise CommandValidationError("numeric PLACE/REPLACE requires qty > 0")
        for source_row in np.flatnonzero(place_like):
            order_handle = int(writer.order_handle[source_row])
            if order_handle in self._writer_order_handles:
                raise CommandValidationError(f"duplicate numeric order_handle={order_handle}")
            self._writer_order_handles.add(order_handle)

        accepted = np.ones(n_rows, dtype=np.bool_)
        changed_count = 0
        dropped_count = 0
        dropped_rows: list[int] = []
        if self.constraints.enabled:
            self.execution_counters["constraint_preflight_calls"] += 1
            for row in np.flatnonzero(place_like):
                symbol_id = int(symbol_ids[row])
                reference_price = (
                    float(prices[row])
                    if np.isfinite(prices[row]) and float(prices[row]) > 0.0
                    else float(self.market_arrays.closes[int(bar), symbol_id])
                )
                original = float(quantities[row])
                quantized = abs(
                    quantize_signed_quantity(
                        original * int(sides[row]),
                        reference_price,
                        float(self.contract_sizes[symbol_id]),
                        float(self.constraints.qty_step[symbol_id]),
                        float(self.constraints.min_qty[symbol_id]),
                        float(self.constraints.min_notional[symbol_id]),
                    )
                )
                if quantized <= 0.0:
                    accepted[row] = False
                    dropped_count += 1
                    dropped_rows.append(int(row))
                else:
                    quantities[row] = quantized
                    changed_count += int(abs(quantized - original) > 1e-12)
            self.execution_counters["commands_quantized"] += n_rows
        else:
            self.execution_counters["constraint_preflight_skipped"] += 1

        rows = np.flatnonzero(accepted)
        codes = np.full((len(rows), _FULL_CODE_WIDTH), -1, dtype=np.int64)
        values = np.zeros((len(rows), _FULL_VALUE_WIDTH), dtype=np.float64)
        expiry = np.full(len(rows), -1, dtype=np.int64)
        for out_row, source_row in enumerate(rows):
            action = int(actions[source_row])
            codes[out_row, 0] = action
            codes[out_row, 1] = int(symbol_ids[source_row])
            codes[out_row, 2] = int(sides[source_row])
            codes[out_row, 3] = int(order_types[source_row])
            codes[out_row, 4] = int(writer.tif[source_row])
            codes[out_row, 5] = int(writer.flags[source_row] & 1)
            for target_col, handle_array in (
                (6, writer.order_handle),
                (7, writer.target_handle),
                (8, writer.parent_handle),
                (9, writer.group_handle),
                (10, writer.oco_handle),
            ):
                handle = int(handle_array[source_row])
                codes[out_row, target_col] = self._intern_id(f"qbt-{handle}") if handle >= 0 else -1
            codes[out_row, 11] = int(writer.activation[source_row])
            codes[out_row, 12] = int(source_row)
            values[out_row, 0] = 0.0 if np.isnan(quantities[source_row]) else float(quantities[source_row])
            values[out_row, 1] = 0.0 if np.isnan(writer.price[source_row]) else float(writer.price[source_row])
            values[out_row, 2] = (
                0.0 if np.isnan(writer.trigger_price[source_row]) else float(writer.trigger_price[source_row])
            )
        self._scheduled_primitive.setdefault(int(bar), []).append(
            _ScheduledPrimitiveBatch(codes, values, expiry, len(rows))
        )
        self.execution_counters["primitive_command_batches"] += 1
        self.execution_counters["primitive_command_rows"] += len(rows)
        return {
            "changed_count": int(changed_count),
            "dropped_count": int(dropped_count),
            "accepted_count": int(len(rows)),
            "dropped_rows": tuple(dropped_rows),
        }

    def release_bar_payload(self, bar: int) -> None:
        self.fills_by_bar.pop(int(bar), None)
        self.events_by_bar.pop(int(bar), None)

    def process_bar(self, bar: int) -> None:
        if self.closed:
            raise NativeProtocolError(
                "Rust reactive session is closed",
                context=EngineErrorContext(NativeProtocolError.error_code, "engine_run", bar_index=int(bar)),
            )
        if self.poisoned:
            raise NativeProtocolError(
                "Rust reactive session is poisoned after a prior native failure",
                context=EngineErrorContext(NativeProtocolError.error_code, "engine_run", bar_index=int(bar)),
            )
        if bar <= self.processed_bar:
            return
        for current_bar in range(self.processed_bar + 1, int(bar) + 1):
            step_started_ns = perf_counter_ns()
            primitive_batches = self._scheduled_primitive.pop(current_bar, ())
            commands = self._quantize_r2_commands(current_bar, self.scheduled.pop(current_bar, ()))
            self._require_r2_for_commands(commands)
            if primitive_batches and commands:
                raise NativeProtocolError(
                    "one Rust bar cannot mix primitive-writer and legacy-object command batches",
                    context=EngineErrorContext(
                        NativeProtocolError.error_code,
                        "command_compile",
                        bar_index=int(current_bar),
                    ),
                )
            if self._full_contract:
                if primitive_batches:
                    if len(primitive_batches) == 1:
                        primitive = primitive_batches[0]
                        full_codes, full_values, full_expiry = (
                            primitive.codes,
                            primitive.values,
                            primitive.expiry,
                        )
                    else:
                        full_codes = np.ascontiguousarray(
                            np.concatenate([item.codes for item in primitive_batches], axis=0)
                        )
                        full_values = np.ascontiguousarray(
                            np.concatenate([item.values for item in primitive_batches], axis=0)
                        )
                        full_expiry = np.ascontiguousarray(
                            np.concatenate([item.expiry for item in primitive_batches], axis=0)
                        )
                    command_count = int(sum(item.command_count for item in primitive_batches))
                else:
                    full_codes, full_values, full_expiry = compile_rust_full_reactive_batch(
                        commands,
                        symbols=self.symbols,
                        intern_id=self._intern_id,
                        idx=self.idx,
                        buffer=self._full_command_buffer,
                    )
                    command_count = len(commands)
                batch = None
            else:
                batch = compile_rust_r1_command_batch(
                    commands,
                    symbol=self.symbols[0],
                    intern_id=self._intern_id,
                    buffer=self._command_buffer,
                )
                command_count = len(commands)
            try:
                if self._full_contract:
                    for command in commands:
                        if command.order_id:
                            self._commands_by_id[command.order_id] = command
                    step_method = getattr(self._core, "step_typed", self._core.step)
                    payload = step_method(current_bar, full_codes, full_values, full_expiry)
                else:
                    for command in batch.commands:
                        if command.order_id:
                            self._commands_by_id[command.order_id] = command
                    payload = self._core.step(current_bar, batch.codes, batch.values, batch.expiry)
            except Exception as exc:
                self.poisoned = True
                raise NativeProtocolError(
                    f"Rust reactive step failed: {type(exc).__name__}: {exc}",
                    context=EngineErrorContext(
                        NativeProtocolError.error_code,
                        "engine_run",
                        bar_index=int(current_bar),
                        timestamp_ns=int(self.idx.asi8[current_bar]),
                    ),
                ) from exc
            self._consume_step(current_bar, payload)
            self.processed_bar = current_bar
            self.execution_counters["bars_processed"] += 1
            self.execution_counters["commands_compiled"] += int(command_count)
            self.execution_counters["command_buffer_growths"] = self._full_command_buffer.growth_count
            self.execution_counters["bytes_copied_to_rust"] += int(
                full_codes.nbytes + full_values.nbytes + full_expiry.nbytes
                if self._full_contract
                else batch.codes.nbytes + batch.values.nbytes + batch.expiry.nbytes
            )
            self.execution_counters["pyo3_calls"] += 1
            self.execution_counters["gil_reacquisitions"] += 1
            self.execution_counters["command_bytes_copied"] = self.execution_counters["bytes_copied_to_rust"]
            self.execution_counters["native_step_ns"] = self.execution_counters.get("native_step_ns", 0) + (
                perf_counter_ns() - step_started_ns
            )

    def _consume_step(self, bar: int, payload) -> None:
        projection = self._projection
        projection.equity = float(_step_value(payload, "equity", 0.0))
        if self._full_contract:
            positions = _step_value(payload, "positions")
            if positions is not None:
                projection.positions[:] = np.asarray(positions, dtype=np.float64)
        else:
            projection.positions[0] = float(_step_value(payload, "position", 0.0))
        fee = float(_step_value(payload, "fee", 0.0))
        turnover = float(_step_value(payload, "turnover", 0.0))
        funding = float(_step_value(payload, "funding", 0.0)) if self._full_contract else 0.0
        initial_margin = float(_step_value(payload, "initial_margin", 0.0))
        maintenance_margin = float(_step_value(payload, "maintenance_margin", 0.0))
        projection.initial_margin = initial_margin
        projection.maintenance_margin = maintenance_margin
        projection.total_fee = float(_step_value(payload, "total_fee", projection.total_fee + fee))
        projection.total_turnover = float(_step_value(payload, "total_turnover", projection.total_turnover + turnover))
        projection.total_funding = float(_step_value(payload, "total_funding", projection.total_funding + funding))
        if self.equity_path is not None:
            self.equity_path[bar] = projection.equity
        if self.pos_path is not None:
            self.pos_path[bar, :] = projection.positions
        if self.fee_path is not None:
            self.fee_path[bar] = fee
        if self.turnover_path is not None:
            self.turnover_path[bar] = turnover
        if self.funding_path is not None:
            self.funding_path[bar] = funding
        if self.initial_margin_path is not None:
            self.initial_margin_path[bar] = initial_margin
        if self.maintenance_margin_path is not None:
            self.maintenance_margin_path[bar] = maintenance_margin
        projection.liquidated = bool(_step_value(payload, "liquidated", False))
        projection.liquidation_bar = int(_step_value(payload, "liquidation_bar", -1))
        projection.liquidation_reason = int(_step_value(payload, "liquidation_reason", 0))
        if self.online_score is not None:
            self.online_score.observe(
                self.idx.asi8[bar],
                projection.equity,
                projection.positions,
                initial_margin,
                maintenance_margin,
            )
        reported_fill_count = _step_has(payload, "fill_count")
        reported_event_counts = _step_has(payload, "event_count")
        if reported_fill_count:
            projection.fill_count = int(_step_value(payload, "fill_end", projection.fill_count + int(_step_value(payload, "fill_count", 0))))
        if reported_event_counts:
            projection.event_count = int(_step_value(payload, "event_end", projection.event_count + int(_step_value(payload, "event_count", 0))))
            rejected = int(_step_value(payload, "rejected_count", 0))
            canceled = int(_step_value(payload, "canceled_count", 0))
            projection.rejected_count = int(_step_value(payload, "total_rejected", projection.rejected_count + rejected))
            projection.canceled_count = int(_step_value(payload, "total_canceled", projection.canceled_count + canceled))
            if self.rejected_bar is not None:
                self.rejected_bar[bar] += rejected
            if self.canceled_bar is not None:
                self.canceled_bar[bar] += canceled
        fills = []
        for fill_row in (_step_value(payload, "fills") or ()):
            if self._full_contract:
                order_code, symbol_code, side_sign, qty, price, fee = fill_row
                symbol = self.symbols[int(symbol_code)]
            else:
                order_code, side_sign, qty, price, fee = fill_row
                symbol = self.symbols[0]
            order_id = self._id_from_code(int(order_code))
            command = self._commands_by_id.get(order_id or "")
            fill = NativeFillEvent(
                timestamp=self.idx[bar],
                symbol=symbol,
                side=OrderSide.BUY if int(side_sign) > 0 else OrderSide.SELL,
                qty=float(qty),
                price=float(price),
                fee=float(fee),
                order_id=order_id,
                tag=None if command is None else command.tag,
                metadata={} if command is None else dict(command.metadata),
            )
            fills.append(fill)
            if not reported_fill_count:
                projection.fill_count += 1
            if self.retain_fill_ledger:
                self.fills.append(fill)
        if fills:
            self.fills_by_bar[bar] = fills
        events = []
        for event_row in (_step_value(payload, "events") or ()):
            if self._full_contract:
                event_kind, status, order_code, target_code = event_row[:4]
                reject_code = int(event_row[5]) if len(event_row) > 5 else 0
            else:
                event_kind, status, order_code, target_code = event_row
                reject_code = 0
            name = ({0: "place", 1: "cancel", 2: "replace", 3: "amend", 4: "fill", 5: "expire", 6: "activate", 7: "reject"} if self._full_contract else {0: "place", 1: "cancel", 2: "fill", 3: "reject", 4: "amend", 5: "replace"}).get(
                int(event_kind), "reject"
            )
            # The public Python ledger identifies an OCO cancellation by the
            # filled order (the initiating action) and stores the canceled
            # sibling in ``target_order_id``. Rust keeps the reverse relation
            # internally to make sibling mutation direct. Normalize only at
            # the boundary so both backends expose one stable event contract.
            public_order_code = int(order_code)
            public_target_code = int(target_code)
            if name == "cancel" and public_order_code >= 0 and public_target_code >= 0:
                public_order_code, public_target_code = public_target_code, public_order_code
            event = NativeOrderEvent(
                timestamp=self.idx[bar],
                bar=bar,
                event_name=name,
                status=int(status),
                order_id=self._id_from_code(public_order_code),
                target_order_id=self._id_from_code(public_target_code),
                metadata={"reject_code": reject_code},
            )
            events.append(event)
            if not reported_event_counts:
                projection.event_count += 1
                if name == "reject":
                    if self.rejected_bar is not None:
                        self.rejected_bar[bar] += 1
                    projection.rejected_count += 1
                if name == "cancel":
                    if self.canceled_bar is not None:
                        self.canceled_bar[bar] += 1
                    projection.canceled_count += 1
            if self.retain_event_ledger:
                self.events.append(event)
        if events:
            self.events_by_bar[bar] = events
        snapshots = self._decode_active_order_rows(_step_value(payload, "active_orders") or ())
        if self.emit_context_active_orders:
            self._active_snapshot_cache = snapshots
            self.execution_counters["active_snapshot_materializations"] += 1
        else:
            self._active_snapshot_cache = self.empty_active_orders
        projection.fill_cursor = (
            int(_step_value(payload, "fill_begin", max(0, projection.fill_count - len(fills)))),
            int(_step_value(payload, "fill_end", projection.fill_count)),
        )
        projection.event_cursor = (
            int(_step_value(payload, "event_begin", max(0, projection.event_count - len(events)))),
            int(_step_value(payload, "event_end", projection.event_count)),
        )
        projection.order_delta_cursor = (
            int(_step_value(payload, "order_delta_begin", projection.event_cursor[0])),
            int(_step_value(payload, "order_delta_end", projection.event_cursor[1])),
        )
        projection.position_delta_cursor = (
            int(_step_value(payload, "position_delta_begin", 0)),
            int(_step_value(payload, "position_delta_end", 0)),
        )
        self.execution_counters["order_delta_rows"] += projection.order_delta_cursor[1] - projection.order_delta_cursor[0]
        self.execution_counters["position_delta_rows"] += projection.position_delta_cursor[1] - projection.position_delta_cursor[0]
        projection_bytes = int(projection.positions.nbytes)
        projection_bytes += len(fills) * 48 + len(events) * 48 + len(snapshots) * 96
        self.execution_counters["callback_projection_bytes"] += projection_bytes
        self.execution_counters["result_bytes_copied"] += projection_bytes

    def _decode_active_order_rows(self, rows) -> tuple[NativeActiveOrderSnapshot, ...]:
        """Convert Rust active-order rows only when a consumer requests them."""

        snapshots = []
        for active_row in rows:
            if self._full_contract:
                order_code, symbol_code, side_sign, order_type, qty, price, trigger_price, tif, flags, parent, group, oco, activation, waiting_parent = active_row
                active_symbol = self.symbols[int(symbol_code)]
                parent_order_id = self._id_from_code(int(parent))
                group_id = self._id_from_code(int(group))
                oco_group_id = self._id_from_code(int(oco))
            else:
                order_code, side_sign, order_type, qty, price, trigger_price, flags = active_row
                active_symbol = self.symbols[0]
                parent_order_id = None
                group_id = None
                oco_group_id = None
            order_id = self._id_from_code(int(order_code))
            command = self._commands_by_id.get(order_id or "")
            side = OrderSide.BUY if int(side_sign) > 0 else OrderSide.SELL
            kind = {
                _R1_ORDER_MARKET: OrderType.MARKET,
                _R1_ORDER_LIMIT: OrderType.LIMIT,
                _R2_ORDER_STOP_MARKET: OrderType.STOP_MARKET,
                _R2_ORDER_STOP_LIMIT: OrderType.STOP_LIMIT,
            }.get(int(order_type), OrderType.MARKET)
            reduce_only = bool(int(flags) & _R2_FLAG_REDUCE_ONLY)
            snapshots.append(
                NativeActiveOrderSnapshot(
                    order_id=order_id,
                    symbol=active_symbol,
                    side=side.value,
                    order_type=kind.value,
                    status=ORDER_STATUS_PENDING,
                    remaining_qty=float(qty),
                    price=float(price),
                    trigger_price=float(trigger_price),
                    reduce_only=reduce_only,
                    parent_order_id=parent_order_id,
                    group_id=group_id,
                    oco_group_id=oco_group_id,
                    tag=None if command is None else command.tag,
                    campaign_id=None if command is None else command.metadata.get("campaign_id"),
                    cycle_id=None if command is None else command.metadata.get("cycle_id"),
                    level_id=None if command is None else command.metadata.get("level_id"),
                )
            )
        return tuple(snapshots) if snapshots else self.empty_active_orders

    def materialize_terminal_active_orders(self) -> tuple[NativeActiveOrderSnapshot, ...]:
        """Fetch the terminal active-order report without another native step."""

        if self.emit_context_active_orders:
            return self._active_snapshot_cache
        if not self._full_contract or not hasattr(self._core, "terminal_active_orders"):
            return self._active_snapshot_cache
        self._active_snapshot_cache = self._decode_active_order_rows(self._core.terminal_active_orders())
        self.execution_counters["active_snapshot_materializations"] += 1
        return self._active_snapshot_cache

    def reset(self, scope: ResetScope | str = ResetScope.ACCOUNT_AND_ORDERS) -> None:
        """Reset mutable native state while retaining immutable market/capacity."""

        if self.closed:
            raise NativeProtocolError("cannot reset a closed Rust reactive session")
        scope = scope if isinstance(scope, ResetScope) else ResetScope(str(scope).lower().strip())
        if scope in {ResetScope.ACCOUNT_ONLY, ResetScope.RESULT_BUFFERS}:
            raise NotImplementedError(
                f"Rust reactive session does not support isolated {scope.value!r}; "
                "use account_and_orders, scenario_state, or full_rebuild"
            )
        if scope is ResetScope.FULL_REBUILD:
            raise NotImplementedError("full_rebuild must be performed by the backend preparation layer")
        self._core.reset()
        self._projection = _RustNativeProjection(
            positions=np.zeros(len(self.symbols), dtype=np.float64),
            equity=float(self.initial_capital),
        )
        for array in (
            self.equity_path, self.pos_path, self.fee_path, self.turnover_path,
            self.funding_path, self.initial_margin_path, self.maintenance_margin_path,
            self.rejected_bar, self.canceled_bar,
        ):
            if array is not None:
                array.fill(0)
        self.scheduled.clear()
        self._scheduled_primitive.clear()
        self._writer_order_handles.clear()
        self.fills.clear()
        self.events.clear()
        self.fills_by_bar.clear()
        self.events_by_bar.clear()
        self._commands_by_id.clear()
        self._id_to_code.clear()
        self._id_values.clear()
        self._active_snapshot_cache = self.empty_active_orders
        self.processed_bar = -1
        self.generation += 1
        self.poisoned = False
        self.reset_count += 1
        if self.online_score is not None:
            from .native_event import _OnlineScoreState

            trading_days = int(self.online_score.trading_days)
            self.online_score = _OnlineScoreState(self.initial_capital, len(self.symbols))
            self.online_score.trading_days = trading_days

    def close(self) -> None:
        self.closed = True
        self.generation += 1
        self.scheduled.clear()
        self._scheduled_primitive.clear()
        self.fills_by_bar.clear()
        self.events_by_bar.clear()

    def context(self, bar: int) -> NativeStrategyContext:
        self.process_bar(bar)
        self.execution_counters["contexts_materialized"] += 1
        initial_margin = (
            float(self.initial_margin_path[int(bar)])
            if self.initial_margin_path is not None
            else float(self.last_initial_margin)
        )
        maintenance_margin = (
            float(self.maintenance_margin_path[int(bar)])
            if self.maintenance_margin_path is not None
            else float(self.last_maintenance_margin)
        )
        return NativeStrategyContext(
            bar_index=int(bar),
            timestamp=self.idx[int(bar)],
            open=self.opens_arr[int(bar)],
            high=self.market_arrays.highs[int(bar)],
            low=self.market_arrays.lows[int(bar)],
            close=self.market_arrays.closes[int(bar)],
            volume=self.volumes_arr[int(bar)],
            equity=float(self.equity),
            available_equity=float(self.equity - initial_margin),
            initial_margin=initial_margin if self.emit_context_margin else 0.0,
            maintenance_margin=maintenance_margin if self.emit_context_margin else 0.0,
            positions=(
                {symbol: float(self.current_pos[col]) for col, symbol in enumerate(self.symbols)}
                if self.emit_context_positions else {}
            ),
            fills_this_bar=(
                tuple(self.fills_by_bar.get(int(bar), ()))
                if self.emit_context_fills else self.empty_fills
            ),
            order_events_this_bar=(
                tuple(self.events_by_bar.get(int(bar), ()))
                if self.emit_context_events else self.empty_events
            ),
            active_orders=(
                self._active_snapshot_cache
                if self.emit_context_active_orders else self.empty_active_orders
            ),
            liquidated=bool(self.liquidated),
            symbols=self.symbols_tuple,
            size_order=self.size_helper,
        )


__all__ = [
    "NativeEventBackendSelection",
    "NativeEventRustBackendError",
    "NativeEventRustExtensionStatus",
    "RUST_NATIVE_API_VERSION",
    "RustCommandBatch",
    "RustCommandBuffer",
    "RustFullCommandBuffer",
    "RustBatchedAuditResult",
    "RustFullAuditResult",
    "RustBatchedChunkResult",
    "RustBatchedRunner",
    "RustFullRunner",
    "RustBatchedScoreResult",
    "RustBatchedSession",
    "RustReactiveSessionAdapter",
    "compile_rust_batched_tape",
    "compile_rust_full_tape",
    "compile_rust_full_reactive_batch",
    "compile_rust_r1_command_batch",
    "probe_native_event_rust_extension",
    "resolve_native_event_backend",
    "validate_rust_r1_support",
]
