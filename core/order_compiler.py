"""
OrderIntent compiler for native event kernels.

The compiler is an internal performance helper: it converts immutable order
intent objects into contiguous ndarray inputs while preserving the old event
kernel semantics.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Sequence, Tuple

import numpy as np
import pandas as pd

from .event import (
    ORDER_TYPE_LIMIT,
    ORDER_TYPE_MARKET,
    ORDER_TYPE_STOP_LIMIT,
    ORDER_TYPE_STOP_MARKET,
    TIF_FOK,
    TIF_GTC,
    TIF_GTD,
    TIF_IOC,
)
from .orders import OrderAction, OrderActivationPolicy, OrderCommand, OrderIntent
from .preprocessor import MarketDataSignature, market_data_signature
from .schema import OrderSide, OrderType, TimeInForce


COMMAND_ACTION_PLACE = 0
COMMAND_ACTION_CANCEL = 1
COMMAND_ACTION_REPLACE = 2
COMMAND_ACTION_AMEND = 3
COMMAND_ACTION_CANCEL_ALL = 4

ACTIVATION_IMMEDIATE = 0
ACTIVATION_ON_PARENT_FIRST_FILL = 1
ACTIVATION_ON_PARENT_FULL_FILL = 2


@dataclass(frozen=True)
class CompiledOrderArrays:
    index_signature: MarketDataSignature
    symbols: Tuple[str, ...]
    sorted_orders: Tuple[Tuple[int, OrderIntent], ...]
    order_ptr: np.ndarray
    order_symbol: np.ndarray
    order_side: np.ndarray
    order_type: np.ndarray
    order_qty: np.ndarray
    order_price: np.ndarray
    order_tif: np.ndarray
    original_index: np.ndarray

    @property
    def n_orders(self) -> int:
        return int(len(self.original_index))


@dataclass(frozen=True)
class CompiledOrderCommandArrays:
    """
    Array contract for native-event lifecycle commands.

    This v2 compiler is intentionally separate from `CompiledOrderArrays` so
    the legacy v1 kernel remains byte-for-byte compatible with old endpoints.
    """

    index_signature: MarketDataSignature
    symbols: Tuple[str, ...]
    sorted_commands: Tuple[Tuple[int, OrderCommand], ...]
    command_ptr: np.ndarray
    command_bar: np.ndarray
    command_action: np.ndarray
    command_symbol: np.ndarray
    command_side: np.ndarray
    command_type: np.ndarray
    command_qty: np.ndarray
    command_price: np.ndarray
    command_trigger_price: np.ndarray
    command_tif: np.ndarray
    command_reduce_only: np.ndarray
    command_order_id: np.ndarray
    command_target_order_id: np.ndarray
    command_parent_order_id: np.ndarray
    command_group_id: np.ndarray
    command_oco_group_id: np.ndarray
    command_activation: np.ndarray
    command_expires_bar: np.ndarray
    original_index: np.ndarray
    id_values: Tuple[str, ...]

    @property
    def n_commands(self) -> int:
        return int(len(self.original_index))


def compile_order_intents(
    idx: pd.DatetimeIndex,
    orders: Sequence[OrderIntent],
    symbol_to_col: Dict[str, int],
) -> CompiledOrderArrays:
    """
    Compile order intents into the exact array contract expected by event v1.

    The sort is stable by effective bar, matching Python's previous
    `sorted(enumerate(orders), key=bar_index)` behavior.
    """
    n_orders = len(orders)
    order_bar_unsorted = np.zeros(n_orders, dtype=np.int64)
    symbol_unsorted = np.zeros(n_orders, dtype=np.int64)
    side_unsorted = np.zeros(n_orders, dtype=np.int64)
    type_unsorted = np.zeros(n_orders, dtype=np.int64)
    qty_unsorted = np.zeros(n_orders, dtype=np.float64)
    price_unsorted = np.zeros(n_orders, dtype=np.float64)
    tif_unsorted = np.zeros(n_orders, dtype=np.int64)
    original_unsorted = np.arange(n_orders, dtype=np.int64)

    idx_ns = idx.view("int64")
    ts_ns = np.zeros(n_orders, dtype=np.int64)
    for k, order in enumerate(orders):
        if order.symbol not in symbol_to_col:
            raise ValueError(f"order symbol {order.symbol!r} is not in symbols")
        ts = pd.Timestamp(order.timestamp)
        if ts.tz is None:
            ts = ts.tz_localize("UTC")
        else:
            ts = ts.tz_convert("UTC")
        ts_ns[k] = ts.value
        symbol_unsorted[k] = symbol_to_col[order.symbol]
        side_unsorted[k] = _side_code(order.side)
        type_unsorted[k] = _order_type_code(order.order_type)
        qty_unsorted[k] = float(order.qty)
        price_unsorted[k] = 0.0 if order.price is None else float(order.price)
        tif_unsorted[k] = _tif_code(order.tif)

    order_bar_unsorted = np.searchsorted(idx_ns, ts_ns, side="left").astype(np.int64)
    if n_orders > 0 and int(order_bar_unsorted.max()) >= len(idx):
        raise ValueError("order timestamp is after the available data")
    order_sort = np.argsort(order_bar_unsorted, kind="stable")

    order_bar = np.ascontiguousarray(order_bar_unsorted[order_sort], dtype=np.int64)
    order_symbol = np.ascontiguousarray(symbol_unsorted[order_sort], dtype=np.int64)
    order_side = np.ascontiguousarray(side_unsorted[order_sort], dtype=np.int64)
    order_type = np.ascontiguousarray(type_unsorted[order_sort], dtype=np.int64)
    order_qty = np.ascontiguousarray(qty_unsorted[order_sort], dtype=np.float64)
    order_price = np.ascontiguousarray(price_unsorted[order_sort], dtype=np.float64)
    order_tif = np.ascontiguousarray(tif_unsorted[order_sort], dtype=np.int64)
    original_index = np.ascontiguousarray(original_unsorted[order_sort], dtype=np.int64)

    order_ptr = np.zeros(len(idx) + 1, dtype=np.int64)
    if n_orders > 0:
        counts = np.bincount(order_bar + 1, minlength=len(idx) + 1)
        order_ptr[:] = np.cumsum(counts, dtype=np.int64)

    sorted_orders = tuple((int(orig_idx), orders[int(orig_idx)]) for orig_idx in original_index)
    return CompiledOrderArrays(
        index_signature=market_data_signature(idx, list(symbol_to_col.keys())),
        symbols=tuple(symbol_to_col.keys()),
        sorted_orders=sorted_orders,
        order_ptr=order_ptr,
        order_symbol=order_symbol,
        order_side=order_side,
        order_type=order_type,
        order_qty=order_qty,
        order_price=order_price,
        order_tif=order_tif,
        original_index=original_index,
    )


def compile_order_commands(
    idx: pd.DatetimeIndex,
    commands: Sequence[OrderCommand],
    symbol_to_col: Dict[str, int],
) -> CompiledOrderCommandArrays:
    """
    Compile lifecycle commands into contiguous arrays for native-event v2.

    The compiler validates timestamps/symbols, keeps a stable command order
    within each bar, and maps sparse string IDs to dense integer codes. No fill
    or accounting logic is performed here; this is only the deterministic input
    contract for a lifecycle kernel or adapter.
    """
    n_commands = len(commands)
    command_bar_unsorted = np.zeros(n_commands, dtype=np.int64)
    action_unsorted = np.zeros(n_commands, dtype=np.int64)
    symbol_unsorted = np.full(n_commands, -1, dtype=np.int64)
    side_unsorted = np.zeros(n_commands, dtype=np.int64)
    type_unsorted = np.full(n_commands, -1, dtype=np.int64)
    qty_unsorted = np.zeros(n_commands, dtype=np.float64)
    price_unsorted = np.zeros(n_commands, dtype=np.float64)
    trigger_unsorted = np.zeros(n_commands, dtype=np.float64)
    tif_unsorted = np.full(n_commands, TIF_GTC, dtype=np.int64)
    reduce_only_unsorted = np.zeros(n_commands, dtype=np.int64)
    order_id_unsorted = np.full(n_commands, -1, dtype=np.int64)
    target_id_unsorted = np.full(n_commands, -1, dtype=np.int64)
    parent_id_unsorted = np.full(n_commands, -1, dtype=np.int64)
    group_id_unsorted = np.full(n_commands, -1, dtype=np.int64)
    oco_id_unsorted = np.full(n_commands, -1, dtype=np.int64)
    activation_unsorted = np.zeros(n_commands, dtype=np.int64)
    expires_bar_unsorted = np.full(n_commands, -1, dtype=np.int64)
    original_unsorted = np.arange(n_commands, dtype=np.int64)

    id_map: Dict[str, int] = {}
    idx_ns = idx.view("int64")
    ts_ns = np.zeros(n_commands, dtype=np.int64)
    for k, command in enumerate(commands):
        ts_ns[k] = _timestamp_ns(command.timestamp)
        action_unsorted[k] = _action_code(command.action)
        if command.symbol is not None:
            if command.symbol not in symbol_to_col:
                raise ValueError(f"command symbol {command.symbol!r} is not in symbols")
            symbol_unsorted[k] = symbol_to_col[command.symbol]
        if command.side is not None:
            side_unsorted[k] = _side_code(command.side)
        if command.order_type is not None:
            type_unsorted[k] = _command_order_type_code(command.order_type)
        if command.qty is not None:
            qty_unsorted[k] = float(command.qty)
        price_unsorted[k] = 0.0 if command.price is None else float(command.price)
        trigger_unsorted[k] = 0.0 if command.trigger_price is None else float(command.trigger_price)
        tif_unsorted[k] = _tif_code(command.tif)
        reduce_only_unsorted[k] = 1 if command.reduce_only else 0
        order_id_unsorted[k] = _id_code(command.order_id, id_map)
        target_id_unsorted[k] = _id_code(command.target_order_id, id_map)
        parent_id_unsorted[k] = _id_code(command.parent_order_id, id_map)
        group_id_unsorted[k] = _id_code(command.group_id, id_map)
        oco_id_unsorted[k] = _id_code(command.oco_group_id, id_map)
        activation_unsorted[k] = _activation_code(command.activation_policy)
        if command.expires_at is not None:
            expires_bar_unsorted[k] = int(np.searchsorted(idx_ns, _timestamp_ns(command.expires_at), side="left"))

    command_bar_unsorted = np.searchsorted(idx_ns, ts_ns, side="left").astype(np.int64)
    if n_commands > 0 and int(command_bar_unsorted.max()) >= len(idx):
        raise ValueError("command timestamp is after the available data")
    order_sort = np.argsort(command_bar_unsorted, kind="stable")

    command_bar = np.ascontiguousarray(command_bar_unsorted[order_sort], dtype=np.int64)
    command_ptr = np.zeros(len(idx) + 1, dtype=np.int64)
    if n_commands > 0:
        counts = np.bincount(command_bar + 1, minlength=len(idx) + 1)
        command_ptr[:] = np.cumsum(counts, dtype=np.int64)

    original_index = np.ascontiguousarray(original_unsorted[order_sort], dtype=np.int64)
    sorted_commands = tuple((int(orig_idx), commands[int(orig_idx)]) for orig_idx in original_index)
    id_values = tuple(sorted(id_map, key=id_map.get))
    return CompiledOrderCommandArrays(
        index_signature=market_data_signature(idx, list(symbol_to_col.keys())),
        symbols=tuple(symbol_to_col.keys()),
        sorted_commands=sorted_commands,
        command_ptr=command_ptr,
        command_bar=np.ascontiguousarray(command_bar, dtype=np.int64),
        command_action=np.ascontiguousarray(action_unsorted[order_sort], dtype=np.int64),
        command_symbol=np.ascontiguousarray(symbol_unsorted[order_sort], dtype=np.int64),
        command_side=np.ascontiguousarray(side_unsorted[order_sort], dtype=np.int64),
        command_type=np.ascontiguousarray(type_unsorted[order_sort], dtype=np.int64),
        command_qty=np.ascontiguousarray(qty_unsorted[order_sort], dtype=np.float64),
        command_price=np.ascontiguousarray(price_unsorted[order_sort], dtype=np.float64),
        command_trigger_price=np.ascontiguousarray(trigger_unsorted[order_sort], dtype=np.float64),
        command_tif=np.ascontiguousarray(tif_unsorted[order_sort], dtype=np.int64),
        command_reduce_only=np.ascontiguousarray(reduce_only_unsorted[order_sort], dtype=np.int64),
        command_order_id=np.ascontiguousarray(order_id_unsorted[order_sort], dtype=np.int64),
        command_target_order_id=np.ascontiguousarray(target_id_unsorted[order_sort], dtype=np.int64),
        command_parent_order_id=np.ascontiguousarray(parent_id_unsorted[order_sort], dtype=np.int64),
        command_group_id=np.ascontiguousarray(group_id_unsorted[order_sort], dtype=np.int64),
        command_oco_group_id=np.ascontiguousarray(oco_id_unsorted[order_sort], dtype=np.int64),
        command_activation=np.ascontiguousarray(activation_unsorted[order_sort], dtype=np.int64),
        command_expires_bar=np.ascontiguousarray(expires_bar_unsorted[order_sort], dtype=np.int64),
        original_index=original_index,
        id_values=id_values,
    )


def order_intents_to_commands(orders: Sequence[OrderIntent]) -> Tuple[OrderCommand, ...]:
    """Convert legacy intents to immediate PLACE lifecycle commands."""
    return tuple(OrderCommand.from_intent(order) for order in orders)


def _side_code(side: OrderSide) -> int:
    return 1 if side is OrderSide.BUY else -1


def _order_type_code(order_type: OrderType) -> int:
    if order_type is OrderType.MARKET:
        return ORDER_TYPE_MARKET
    if order_type is OrderType.LIMIT:
        return ORDER_TYPE_LIMIT
    raise NotImplementedError(f"unsupported order_type={order_type!r}")


def _command_order_type_code(order_type: OrderType) -> int:
    if order_type is OrderType.MARKET:
        return ORDER_TYPE_MARKET
    if order_type is OrderType.LIMIT:
        return ORDER_TYPE_LIMIT
    if order_type is OrderType.STOP_MARKET:
        return ORDER_TYPE_STOP_MARKET
    if order_type is OrderType.STOP_LIMIT:
        return ORDER_TYPE_STOP_LIMIT
    raise NotImplementedError(f"unsupported order_type={order_type!r}")


def _tif_code(tif: TimeInForce) -> int:
    if tif is TimeInForce.GTC:
        return TIF_GTC
    if tif is TimeInForce.IOC:
        return TIF_IOC
    if tif is TimeInForce.FOK:
        return TIF_FOK
    if tif is TimeInForce.GTD:
        return TIF_GTD
    raise NotImplementedError(f"unsupported tif={tif!r}")


def _action_code(action: OrderAction) -> int:
    if action is OrderAction.PLACE:
        return COMMAND_ACTION_PLACE
    if action is OrderAction.CANCEL:
        return COMMAND_ACTION_CANCEL
    if action is OrderAction.REPLACE:
        return COMMAND_ACTION_REPLACE
    if action is OrderAction.AMEND:
        return COMMAND_ACTION_AMEND
    if action is OrderAction.CANCEL_ALL:
        return COMMAND_ACTION_CANCEL_ALL
    raise NotImplementedError(f"unsupported action={action!r}")


def _activation_code(policy: OrderActivationPolicy) -> int:
    if policy is OrderActivationPolicy.IMMEDIATE:
        return ACTIVATION_IMMEDIATE
    if policy is OrderActivationPolicy.ON_PARENT_FIRST_FILL:
        return ACTIVATION_ON_PARENT_FIRST_FILL
    if policy is OrderActivationPolicy.ON_PARENT_FULL_FILL:
        return ACTIVATION_ON_PARENT_FULL_FILL
    raise NotImplementedError(f"unsupported activation_policy={policy!r}")


def _id_code(value: str | None, id_map: Dict[str, int]) -> int:
    if value is None or value == "":
        return -1
    if value not in id_map:
        id_map[value] = len(id_map)
    return id_map[value]


def _timestamp_ns(value: object) -> int:
    ts = pd.Timestamp(value)
    if ts.tz is None:
        ts = ts.tz_localize("UTC")
    else:
        ts = ts.tz_convert("UTC")
    return int(ts.value)
