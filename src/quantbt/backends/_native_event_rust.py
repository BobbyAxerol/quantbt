"""Optional PyO3 capability probe for the native-event accelerator.

Phase 44A deliberately keeps this module free of matching or accounting
logic.  The Python/Numba implementation remains the execution backend until a
future Rust slice has passed lifecycle and accounting parity certification.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
import importlib
import os
from types import ModuleType
from typing import Callable, Mapping, Optional, Sequence

import numpy as np
import pandas as pd

from ..core.event import ORDER_STATUS_CANCELED, ORDER_STATUS_FILLED, ORDER_STATUS_PENDING, ORDER_STATUS_REJECTED
from ..core.constraints import quantize_signed_quantity
from ..core.orders import OrderAction, OrderActivationPolicy, OrderCommand
from ..core.reactive import NativeActiveOrderSnapshot, NativeFillEvent, NativeOrderEvent, NativeStrategyContext
from ..core.schema import OrderSide, OrderType, TimeInForce


RUST_NATIVE_API_VERSION = "0.3"
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
    trigger_price: float
    reduce_only: bool


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
) -> RustCommandBatch:
    """Compile the R2 lifecycle subset into contiguous primitive buffers.

    Field layout is stable from R1: ``[action, side, type, flags, order_id,
    target_id, mutate_mask, sequence]`` and ``[qty, price, trigger]``.  This
    lets the optional extension evolve without adding Python object work to the
    bar loop.
    """
    command_tuple = tuple(commands)
    codes = np.full((len(command_tuple), _R1_CODE_WIDTH), -1, dtype=np.int64)
    values = np.zeros((len(command_tuple), _R1_VALUE_WIDTH), dtype=np.float64)
    expiry = np.full(len(command_tuple), -1, dtype=np.int64)

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
        extension_status = probe_native_event_rust_extension(module=self._module)
        self._r2_capable = bool(extension_status.capabilities.get("r2_stop_amend_replace_reduce_only_constraints", False))
        if self.constraints.enabled and not self._r2_capable:
            raise NativeEventRustBackendError(
                "installed _quantbt_native wheel is R1-only and cannot apply quantity constraints; rebuild/install R2 or use backend='python'"
            )
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

    def _quantize_r2_commands(self, bar: int, commands: Sequence[OrderCommand]) -> tuple[OrderCommand, ...]:
        """Apply the canonical quantity filter at the same bar as replay preflight.

        Reactive commands cannot be preflighted before a strategy emits them.
        The static replay performs the equivalent filtering over the emitted
        tape; this method makes explicit Rust follow that exact exchange-rule
        contract without changing the command tape or endpoint API.
        """
        if not self.constraints.enabled:
            return tuple(commands)
        out: list[OrderCommand] = []
        close = float(self.market_arrays.closes[int(bar), 0])
        for command in commands:
            if command.action not in (OrderAction.PLACE, OrderAction.REPLACE) or command.qty is None:
                out.append(command)
                continue
            price = float(command.price) if command.price is not None else close
            signed = command.signed_qty
            quantity = abs(
                quantize_signed_quantity(
                    signed,
                    price,
                    float(self.contract_sizes[0]),
                    float(self.constraints.qty_step[0]),
                    float(self.constraints.min_qty[0]),
                    float(self.constraints.min_notional[0]),
                )
            )
            if quantity <= 0.0:
                continue
            if abs(quantity - float(command.qty)) > 1e-12:
                out.append(replace(command, qty=quantity))
            else:
                out.append(command)
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

    def release_bar_payload(self, bar: int) -> None:
        self.fills_by_bar.pop(int(bar), None)
        self.events_by_bar.pop(int(bar), None)

    def process_bar(self, bar: int) -> None:
        if bar <= self.processed_bar:
            return
        for current_bar in range(self.processed_bar + 1, int(bar) + 1):
            commands = self._quantize_r2_commands(current_bar, self.scheduled.pop(current_bar, ()))
            self._require_r2_for_commands(commands)
            batch = compile_rust_r1_command_batch(
                commands,
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
            name = {0: "place", 1: "cancel", 2: "fill", 3: "reject", 4: "amend", 5: "replace"}.get(
                int(event_kind), "reject"
            )
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
        for order_code, side_sign, order_type, qty, price, trigger_price, flags in payload["active_orders"]:
            order_id = self._id_from_code(int(order_code))
            side = OrderSide.BUY if int(side_sign) > 0 else OrderSide.SELL
            kind = {
                _R1_ORDER_MARKET: OrderType.MARKET,
                _R1_ORDER_LIMIT: OrderType.LIMIT,
                _R2_ORDER_STOP_MARKET: OrderType.STOP_MARKET,
                _R2_ORDER_STOP_LIMIT: OrderType.STOP_LIMIT,
            }.get(int(order_type), OrderType.MARKET)
            reduce_only = bool(int(flags) & _R2_FLAG_REDUCE_ONLY)
            pending.append(
                _RustPendingOrder(
                    order_id=order_id,
                    side=side,
                    order_type=kind,
                    qty=float(qty),
                    price=float(price),
                    trigger_price=float(trigger_price),
                    reduce_only=reduce_only,
                )
            )
            snapshots.append(
                NativeActiveOrderSnapshot(
                    order_id=order_id,
                    symbol=self.symbols[0],
                    side=side.value,
                    order_type=kind.value,
                    status=ORDER_STATUS_PENDING,
                    remaining_qty=float(qty),
                    price=float(price),
                    trigger_price=float(trigger_price),
                    reduce_only=reduce_only,
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
