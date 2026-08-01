"""Optional PyO3 capability probe for the native-event accelerator.

Phase 44A deliberately keeps this module free of matching or accounting
logic.  The Python/Numba implementation remains the execution backend until a
future Rust slice has passed lifecycle and accounting parity certification.
"""

from __future__ import annotations

from dataclasses import dataclass
import importlib
import os
from types import ModuleType
from typing import Callable, Mapping, Optional, Sequence

import numpy as np
import pandas as pd

from ..core.event import ORDER_STATUS_CANCELED, ORDER_STATUS_FILLED, ORDER_STATUS_PENDING, ORDER_STATUS_REJECTED
from ..core.orders import OrderAction, OrderActivationPolicy, OrderCommand
from ..core.reactive import NativeActiveOrderSnapshot, NativeFillEvent, NativeOrderEvent, NativeStrategyContext
from ..core.schema import OrderSide, OrderType, TimeInForce


RUST_NATIVE_API_VERSION = "0.3"
_VALID_BACKENDS = frozenset({"auto", "python", "rust", "replay_certified"})
_R1_ACTION_PLACE = 0
_R1_ACTION_CANCEL = 1
_R1_ORDER_MARKET = 0
_R1_ORDER_LIMIT = 1
_R1_CODE_WIDTH = 8
_R1_VALUE_WIDTH = 3


class NativeEventRustBackendError(RuntimeError):
    """Raised when an explicitly requested Rust backend cannot be used."""


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


@dataclass(frozen=True)
class NativeEventBackendSelection:
    """Internal backend decision without changing the public endpoint API."""

    requested: str
    resolved: str
    extension: NativeEventRustExtensionStatus


@dataclass(frozen=True)
class RustCommandBatch:
    """Contiguous R1 command buffers plus the Python-side identity table."""

    codes: np.ndarray
    values: np.ndarray
    expiry: np.ndarray
    commands: tuple[OrderCommand, ...]


@dataclass(frozen=True)
class _RustPendingOrder:
    order_id: Optional[str]
    side: OrderSide
    order_type: OrderType
    qty: float
    price: float


def _empty_status(reason: str) -> NativeEventRustExtensionStatus:
    return NativeEventRustExtensionStatus(
        available=False,
        compatible=False,
        executable=False,
        version=None,
        api_version=None,
        capabilities={},
        reason=reason,
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
    except Exception as exc:  # pragma: no cover - protects optional binary imports.
        return _empty_status(f"failed to query _quantbt_native metadata: {exc}")

    if not isinstance(raw_capabilities, Mapping):
        raw_capabilities = {}
    capabilities = {str(name): bool(enabled) for name, enabled in raw_capabilities.items()}
    compatible = api_version == RUST_NATIVE_API_VERSION
    if not compatible:
        return NativeEventRustExtensionStatus(
            available=True,
            compatible=False,
            executable=False,
            version=version,
            api_version=api_version,
            capabilities=capabilities,
            reason=(
                "_quantbt_native API version mismatch: "
                f"expected {RUST_NATIVE_API_VERSION!r}, received {api_version!r}"
            ),
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
    )


def resolve_native_event_backend(
    requested: Optional[str] = None,
    *,
    extension_status: Optional[NativeEventRustExtensionStatus] = None,
) -> NativeEventBackendSelection:
    """Resolve the internal native-event backend under the R0 rollout policy.

    ``auto`` intentionally resolves to Python during R0, even with the wheel
    installed.  ``rust`` is explicit and therefore fails loudly until a later
    Rust feature slice certifies an executable reactive session.
    """
    selected = str(requested or os.getenv("QUANTBT_NATIVE_BACKEND", "auto")).lower().strip()
    if selected not in _VALID_BACKENDS:
        valid = ", ".join(sorted(_VALID_BACKENDS))
        raise ValueError(f"QUANTBT_NATIVE_BACKEND must be one of: {valid}")

    status = extension_status
    if selected == "rust":
        status = status or probe_native_event_rust_extension()
        if not status.available or not status.compatible or not status.executable:
            detail = status.reason or "unknown native extension state"
            raise NativeEventRustBackendError(f"native-event backend='rust' is unavailable: {detail}")
        return NativeEventBackendSelection(requested=selected, resolved="rust", extension=status)

    # R0 rollout contract: never auto-enable a just-built extension.
    status = status or _empty_status("Rust extension was not queried because the Python backend was selected")
    resolved = "replay_certified" if selected == "replay_certified" else "python"
    return NativeEventBackendSelection(requested=selected, resolved=resolved, extension=status)


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
    """Reject every feature outside the R1 parity-certified surface."""
    if len(symbols) != 1:
        raise NativeEventRustBackendError("Rust R1 supports exactly one symbol; use backend='python' for multi-symbol")
    if constraints.enabled:
        raise NativeEventRustBackendError("Rust R1 does not support quantity constraints; use backend='python'")
    if use_funding:
        raise NativeEventRustBackendError("Rust R1 does not support funding; use backend='python'")
    if float(maintenance_ratio) != 0.0:
        raise NativeEventRustBackendError(
            "Rust R1 does not support liquidation semantics; set maintenance_ratio=0.0 or use backend='python'"
        )


def compile_rust_r1_command_batch(
    commands: Sequence[OrderCommand],
    *,
    symbol: str,
    intern_id: Callable[[Optional[str]], int],
) -> RustCommandBatch:
    """Compile the R1 lifecycle subset into contiguous primitive buffers."""
    command_tuple = tuple(commands)
    codes = np.full((len(command_tuple), _R1_CODE_WIDTH), -1, dtype=np.int64)
    values = np.zeros((len(command_tuple), _R1_VALUE_WIDTH), dtype=np.float64)
    expiry = np.full(len(command_tuple), -1, dtype=np.int64)

    for sequence, command in enumerate(command_tuple):
        codes[sequence, 7] = sequence
        if command.action is OrderAction.PLACE:
            if command.symbol != symbol:
                raise NativeEventRustBackendError(f"Rust R1 command symbol must be {symbol!r}")
            if command.side not in (OrderSide.BUY, OrderSide.SELL):
                raise NativeEventRustBackendError("Rust R1 PLACE requires BUY or SELL")
            if command.order_type not in (OrderType.MARKET, OrderType.LIMIT):
                raise NativeEventRustBackendError("Rust R1 supports MARKET and LIMIT orders only")
            if command.tif is not TimeInForce.GTC:
                raise NativeEventRustBackendError("Rust R1 supports GTC only")
            if command.reduce_only or command.parent_order_id or command.oco_group_id or command.group_id:
                raise NativeEventRustBackendError("Rust R1 does not support reduce-only, parent, group, or OCO orders")
            if command.activation_policy is not OrderActivationPolicy.IMMEDIATE:
                raise NativeEventRustBackendError("Rust R1 supports immediate order activation only")
            if command.expires_at is not None or command.trigger_price is not None:
                raise NativeEventRustBackendError("Rust R1 does not support expiry or trigger prices")
            codes[sequence, 0] = _R1_ACTION_PLACE
            codes[sequence, 1] = command.side.sign
            codes[sequence, 2] = _R1_ORDER_MARKET if command.order_type is OrderType.MARKET else _R1_ORDER_LIMIT
            codes[sequence, 3] = 0
            codes[sequence, 4] = intern_id(command.order_id)
            values[sequence, 0] = float(command.qty or 0.0)
            values[sequence, 1] = float(command.price or 0.0)
        elif command.action is OrderAction.CANCEL:
            codes[sequence, 0] = _R1_ACTION_CANCEL
            codes[sequence, 5] = intern_id(command.target_order_id)
        else:
            raise NativeEventRustBackendError("Rust R1 supports PLACE and CANCEL commands only")
    return RustCommandBatch(codes=codes, values=values, expiry=expiry, commands=command_tuple)


class RustReactiveSessionAdapter:
    """R1 bridge: Python callbacks around one Rust state transition per bar."""

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
        retain_terminal_orders: bool = True,
    ) -> None:
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
        self.use_funding = False
        self.retain_terminal_orders = bool(retain_terminal_orders)
        self._module = _require_r1_extension()
        self._id_to_code: dict[str, int] = {}
        self._id_values: list[str] = []
        self._commands_by_id: dict[str, OrderCommand] = {}
        self.scheduled: dict[int, list[OrderCommand]] = {}
        self.pending: list[_RustPendingOrder] = []
        self.orders: list[_RustPendingOrder] = []
        self.fills: list[NativeFillEvent] = []
        self.events: list[NativeOrderEvent] = []
        self.fills_by_bar: dict[int, list[NativeFillEvent]] = {}
        self.events_by_bar: dict[int, list[NativeOrderEvent]] = {}
        self.current_pos = np.zeros(1, dtype=np.float64)
        self.equity = float(initial_capital)
        self.liquidated = False
        self.liquidation_bar = -1
        self.liquidation_reason = 0
        self.processed_bar = -1
        n_bars = len(idx)
        self.equity_path = np.zeros(n_bars, dtype=np.float64)
        self.pos_path = np.zeros((n_bars, 1), dtype=np.float64)
        self.fee_path = np.zeros(n_bars, dtype=np.float64)
        self.turnover_path = np.zeros(n_bars, dtype=np.float64)
        self.funding_path = np.zeros(n_bars, dtype=np.float64)
        self.initial_margin_path = np.zeros(n_bars, dtype=np.float64)
        self.maintenance_margin_path = np.zeros(n_bars, dtype=np.float64)
        self.rejected_bar = np.zeros(n_bars, dtype=np.int64)
        self.canceled_bar = np.zeros(n_bars, dtype=np.int64)
        self._active_snapshot_cache: tuple[NativeActiveOrderSnapshot, ...] = ()
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
        if symbol != self.symbols[0]:
            raise ValueError(f"unknown symbol={symbol!r}")
        if price <= 0.0:
            raise ValueError("price must be > 0")
        return abs(float(notional) / (float(price) * float(self.contract_sizes[0])))

    def schedule(self, bar: int, commands: Sequence[OrderCommand]) -> None:
        if commands and int(bar) < len(self.idx):
            self.scheduled.setdefault(int(bar), []).extend(commands)

    def release_bar_payload(self, bar: int) -> None:
        self.fills_by_bar.pop(int(bar), None)
        self.events_by_bar.pop(int(bar), None)

    def process_bar(self, bar: int) -> None:
        if bar <= self.processed_bar:
            return
        for current_bar in range(self.processed_bar + 1, int(bar) + 1):
            batch = compile_rust_r1_command_batch(
                self.scheduled.pop(current_bar, ()),
                symbol=self.symbols[0],
                intern_id=self._intern_id,
            )
            for command in batch.commands:
                if command.order_id:
                    self._commands_by_id[command.order_id] = command
            payload = self._core.step(current_bar, batch.codes, batch.values, batch.expiry)
            self._consume_step(current_bar, payload)
            self.processed_bar = current_bar

    def _consume_step(self, bar: int, payload) -> None:
        self.equity = float(payload["equity"])
        self.current_pos[0] = float(payload["position"])
        self.equity_path[bar] = self.equity
        self.pos_path[bar, 0] = self.current_pos[0]
        self.fee_path[bar] = float(payload["fee"])
        self.turnover_path[bar] = float(payload["turnover"])
        self.initial_margin_path[bar] = float(payload["initial_margin"])
        self.maintenance_margin_path[bar] = float(payload["maintenance_margin"])
        fills = []
        for order_code, side_sign, qty, price, fee in payload["fills"]:
            order_id = self._id_from_code(int(order_code))
            command = self._commands_by_id.get(order_id or "")
            fill = NativeFillEvent(
                timestamp=self.idx[bar],
                symbol=self.symbols[0],
                side=OrderSide.BUY if int(side_sign) > 0 else OrderSide.SELL,
                qty=float(qty),
                price=float(price),
                fee=float(fee),
                order_id=order_id,
                tag=None if command is None else command.tag,
                metadata={} if command is None else dict(command.metadata),
            )
            fills.append(fill)
            self.fills.append(fill)
        if fills:
            self.fills_by_bar[bar] = fills
        events = []
        for event_kind, status, order_code, target_code in payload["events"]:
            name = {0: "place", 1: "cancel", 2: "fill", 3: "reject"}.get(int(event_kind), "reject")
            if name == "reject":
                self.rejected_bar[bar] += 1
            if name == "cancel":
                self.canceled_bar[bar] += 1
            event = NativeOrderEvent(
                timestamp=self.idx[bar],
                bar=bar,
                event_name=name,
                status=int(status),
                order_id=self._id_from_code(int(order_code)),
                target_order_id=self._id_from_code(int(target_code)),
            )
            events.append(event)
            self.events.append(event)
        if events:
            self.events_by_bar[bar] = events
        pending = []
        snapshots = []
        for order_code, side_sign, order_type, qty, price in payload["active_orders"]:
            order_id = self._id_from_code(int(order_code))
            side = OrderSide.BUY if int(side_sign) > 0 else OrderSide.SELL
            kind = OrderType.MARKET if int(order_type) == _R1_ORDER_MARKET else OrderType.LIMIT
            pending.append(_RustPendingOrder(order_id=order_id, side=side, order_type=kind, qty=float(qty), price=float(price)))
            snapshots.append(
                NativeActiveOrderSnapshot(
                    order_id=order_id,
                    symbol=self.symbols[0],
                    side=side.value,
                    order_type=kind.value,
                    status=ORDER_STATUS_PENDING,
                    remaining_qty=float(qty),
                    price=float(price),
                    trigger_price=0.0,
                    reduce_only=False,
                )
            )
        self.pending = pending
        self._active_snapshot_cache = tuple(snapshots)

    @staticmethod
    def _is_pending(state: _RustPendingOrder) -> bool:
        return True

    def context(self, bar: int) -> NativeStrategyContext:
        self.process_bar(bar)
        return NativeStrategyContext(
            bar_index=int(bar),
            timestamp=self.idx[int(bar)],
            open=self.opens_arr[int(bar)],
            high=self.market_arrays.highs[int(bar)],
            low=self.market_arrays.lows[int(bar)],
            close=self.market_arrays.closes[int(bar)],
            volume=self.volumes_arr[int(bar)],
            equity=float(self.equity),
            available_equity=float(self.equity - self.initial_margin_path[int(bar)]),
            initial_margin=float(self.initial_margin_path[int(bar)]),
            maintenance_margin=float(self.maintenance_margin_path[int(bar)]),
            positions={self.symbols[0]: float(self.current_pos[0])},
            fills_this_bar=tuple(self.fills_by_bar.get(int(bar), ())),
            order_events_this_bar=tuple(self.events_by_bar.get(int(bar), ())),
            active_orders=self._active_snapshot_cache,
            liquidated=False,
            symbols=self.symbols_tuple,
            size_order=self.size_helper,
        )


__all__ = [
    "NativeEventBackendSelection",
    "NativeEventRustBackendError",
    "NativeEventRustExtensionStatus",
    "RUST_NATIVE_API_VERSION",
    "RustCommandBatch",
    "RustReactiveSessionAdapter",
    "compile_rust_r1_command_batch",
    "probe_native_event_rust_extension",
    "resolve_native_event_backend",
    "validate_rust_r1_support",
]
