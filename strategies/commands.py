"""Reusable struct-of-arrays command writer for numeric strategies."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import numpy as np

from ..core.orders import OrderAction, OrderActivationPolicy, OrderCommand
from ..core.schema import OrderSide, OrderType, TimeInForce
from ..errors import EngineErrorContext, ResourceLimitError


_ACTION = {
    OrderAction.PLACE: 0,
    OrderAction.CANCEL: 1,
    OrderAction.REPLACE: 2,
    OrderAction.AMEND: 3,
    OrderAction.CANCEL_ALL: 4,
}
_ORDER_TYPE = {OrderType.MARKET: 0, OrderType.LIMIT: 1, OrderType.STOP_MARKET: 2, OrderType.STOP_LIMIT: 3}
_TIF = {TimeInForce.GTC: 0, TimeInForce.IOC: 1, TimeInForce.FOK: 2, TimeInForce.GTD: 3}
_ACTIVATION = {
    OrderActivationPolicy.IMMEDIATE: 0,
    OrderActivationPolicy.ON_PARENT_FIRST_FILL: 1,
    OrderActivationPolicy.ON_PARENT_FULL_FILL: 2,
}
_ACTION_FROM = {value: key for key, value in _ACTION.items()}
_ORDER_TYPE_FROM = {value: key for key, value in _ORDER_TYPE.items()}
_TIF_FROM = {value: key for key, value in _TIF.items()}
_ACTIVATION_FROM = {value: key for key, value in _ACTIVATION.items()}


@dataclass(frozen=True, slots=True)
class CommandBatchView:
    """Ephemeral valid prefix of a reusable command writer."""

    writer: "CommandWriter"
    generation: int
    length: int

    def _check(self) -> None:
        if self.generation != self.writer.generation:
            raise RuntimeError("CommandBatchView is stale after writer reuse")

    def to_order_commands(self, *, timestamp, symbols: Sequence[str]) -> tuple[OrderCommand, ...]:
        """Materialize the compatibility command contract outside the writer."""

        self._check()
        writer = self.writer
        output = []
        for row in range(self.length):
            action = _ACTION_FROM[int(writer.action[row])]
            symbol_id = int(writer.symbol_id[row])
            side_sign = int(writer.side[row])
            order_type_code = int(writer.order_type[row])
            order_handle = int(writer.order_handle[row])
            target_handle = int(writer.target_handle[row])
            parent_handle = int(writer.parent_handle[row])
            group_handle = int(writer.group_handle[row])
            oco_handle = int(writer.oco_handle[row])
            output.append(
                OrderCommand(
                    timestamp=timestamp,
                    action=action,
                    symbol=None if symbol_id < 0 else symbols[symbol_id],
                    side=None if side_sign == 0 else (OrderSide.BUY if side_sign > 0 else OrderSide.SELL),
                    order_type=None if order_type_code < 0 else _ORDER_TYPE_FROM[order_type_code],
                    qty=None if np.isnan(writer.qty[row]) else float(writer.qty[row]),
                    price=None if np.isnan(writer.price[row]) else float(writer.price[row]),
                    trigger_price=None if np.isnan(writer.trigger_price[row]) else float(writer.trigger_price[row]),
                    tif=_TIF_FROM[int(writer.tif[row])],
                    reduce_only=bool(writer.flags[row] & 1),
                    order_id=None if order_handle < 0 else f"qbt-{order_handle}",
                    target_order_id=None if target_handle < 0 else f"qbt-{target_handle}",
                    parent_order_id=None if parent_handle < 0 else f"qbt-{parent_handle}",
                    group_id=None if group_handle < 0 else f"qbt-{group_handle}",
                    oco_group_id=None if oco_handle < 0 else f"qbt-{oco_handle}",
                    activation_policy=_ACTIVATION_FROM[int(writer.activation[row])],
                )
            )
        return tuple(output)


class CommandWriter:
    """Capacity-managed primitive command buffer reused across callbacks."""

    __slots__ = (
        "initial_capacity", "hard_limit", "length", "capacity", "generation",
        "growth_count", "high_water_mark", "action", "symbol_id", "side",
        "order_type", "tif", "flags", "order_handle", "target_handle",
        "parent_handle", "group_handle", "oco_handle", "activation", "qty",
        "price", "trigger_price", "_next_handle",
    )

    def __init__(self, initial_capacity: int = 8, hard_limit: int = 65_536):
        if initial_capacity <= 0 or hard_limit <= 0 or initial_capacity > hard_limit:
            raise ValueError("command writer requires 0 < initial_capacity <= hard_limit")
        self.initial_capacity = int(initial_capacity)
        self.hard_limit = int(hard_limit)
        self.length = 0
        self.capacity = 0
        self.generation = 0
        self.growth_count = 0
        self.high_water_mark = 0
        self._next_handle = 1
        self._allocate(self.initial_capacity)

    def _allocate(self, capacity: int) -> None:
        old_length = self.length
        int_names = (
            "action", "symbol_id", "side", "order_type", "tif", "flags",
            "order_handle", "target_handle", "parent_handle", "group_handle",
            "oco_handle", "activation",
        )
        float_names = ("qty", "price", "trigger_price")
        old = {name: getattr(self, name, None) for name in (*int_names, *float_names)}
        for name in int_names:
            array = np.full(capacity, -1, dtype=np.int64)
            if old[name] is not None and old_length:
                array[:old_length] = old[name][:old_length]
            setattr(self, name, array)
        for name in float_names:
            array = np.full(capacity, np.nan, dtype=np.float64)
            if old[name] is not None and old_length:
                array[:old_length] = old[name][:old_length]
            setattr(self, name, array)
        self.capacity = int(capacity)

    def _reserve_row(self) -> int:
        if self.length >= self.hard_limit:
            raise ResourceLimitError(
                f"command writer hard limit exceeded: {self.hard_limit}",
                context=EngineErrorContext(ResourceLimitError.error_code, "strategy_callback"),
            )
        if self.length >= self.capacity:
            self._allocate(min(self.hard_limit, max(self.capacity * 2, self.length + 1)))
            self.growth_count += 1
        row = self.length
        self.length += 1
        self.high_water_mark = max(self.high_water_mark, self.length)
        return row

    def reset(self) -> None:
        self.length = 0
        self.generation += 1

    def _handle(self, value: int | None) -> int:
        if value is not None:
            return int(value)
        handle = self._next_handle
        self._next_handle += 1
        return handle

    def _write(
        self,
        *,
        action: OrderAction,
        symbol_id: int = -1,
        side: int | OrderSide = 0,
        order_type: OrderType | None = None,
        qty: float | None = None,
        price: float | None = None,
        trigger_price: float | None = None,
        tif: TimeInForce = TimeInForce.GTC,
        reduce_only: bool = False,
        order_handle: int | None = None,
        target_handle: int | None = None,
        parent_handle: int | None = None,
        group_handle: int | None = None,
        oco_handle: int | None = None,
        activation: OrderActivationPolicy = OrderActivationPolicy.IMMEDIATE,
    ) -> int:
        row = self._reserve_row()
        side_sign = side.sign if isinstance(side, OrderSide) else int(side)
        handle = self._handle(order_handle) if action in {OrderAction.PLACE, OrderAction.REPLACE} else -1
        self.action[row] = _ACTION[action]
        self.symbol_id[row] = int(symbol_id)
        self.side[row] = int(side_sign)
        self.order_type[row] = -1 if order_type is None else _ORDER_TYPE[order_type]
        self.tif[row] = _TIF[tif]
        self.flags[row] = 1 if reduce_only else 0
        self.order_handle[row] = handle
        self.target_handle[row] = -1 if target_handle is None else int(target_handle)
        self.parent_handle[row] = -1 if parent_handle is None else int(parent_handle)
        self.group_handle[row] = -1 if group_handle is None else int(group_handle)
        self.oco_handle[row] = -1 if oco_handle is None else int(oco_handle)
        self.activation[row] = _ACTIVATION[activation]
        self.qty[row] = np.nan if qty is None else float(qty)
        self.price[row] = np.nan if price is None else float(price)
        self.trigger_price[row] = np.nan if trigger_price is None else float(trigger_price)
        return handle

    def market(self, symbol_id: int, side: int | OrderSide, qty: float, **kwargs) -> int:
        return self._write(action=OrderAction.PLACE, symbol_id=symbol_id, side=side, order_type=OrderType.MARKET, qty=qty, **kwargs)

    def limit(self, symbol_id: int, side: int | OrderSide, qty: float, price: float, **kwargs) -> int:
        return self._write(action=OrderAction.PLACE, symbol_id=symbol_id, side=side, order_type=OrderType.LIMIT, qty=qty, price=price, **kwargs)

    def stop_market(self, symbol_id: int, side: int | OrderSide, qty: float, trigger_price: float, **kwargs) -> int:
        return self._write(action=OrderAction.PLACE, symbol_id=symbol_id, side=side, order_type=OrderType.STOP_MARKET, qty=qty, trigger_price=trigger_price, **kwargs)

    def stop_limit(self, symbol_id: int, side: int | OrderSide, qty: float, price: float, trigger_price: float, **kwargs) -> int:
        return self._write(action=OrderAction.PLACE, symbol_id=symbol_id, side=side, order_type=OrderType.STOP_LIMIT, qty=qty, price=price, trigger_price=trigger_price, **kwargs)

    def cancel(self, target_handle: int) -> None:
        self._write(action=OrderAction.CANCEL, target_handle=target_handle)

    def cancel_all(self, *, symbol_id: int = -1) -> None:
        self._write(action=OrderAction.CANCEL_ALL, symbol_id=symbol_id)

    def amend(self, target_handle: int, *, qty=None, price=None, trigger_price=None) -> None:
        self._write(action=OrderAction.AMEND, target_handle=target_handle, qty=qty, price=price, trigger_price=trigger_price)

    def finish(self) -> CommandBatchView:
        return CommandBatchView(self, self.generation, self.length)


__all__ = ["CommandBatchView", "CommandWriter"]
