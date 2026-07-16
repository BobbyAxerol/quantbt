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
    TIF_FOK,
    TIF_GTC,
    TIF_GTD,
    TIF_IOC,
)
from .orders import OrderIntent
from .preprocessor import MarketDataSignature, market_data_signature
from .schema import OrderSide, OrderType, TimeInForce


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


def _side_code(side: OrderSide) -> int:
    return 1 if side is OrderSide.BUY else -1


def _order_type_code(order_type: OrderType) -> int:
    if order_type is OrderType.MARKET:
        return ORDER_TYPE_MARKET
    if order_type is OrderType.LIMIT:
        return ORDER_TYPE_LIMIT
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
