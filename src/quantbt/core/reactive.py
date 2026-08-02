"""
Reactive native-event strategy context.

These records are intentionally lightweight and read-only. Strategies inspect
engine state after each bar and return `OrderCommand` objects for the next bar.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Mapping, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from .orders import OrderCommand
from .schema import OrderSide, OrderType


@dataclass(frozen=True)
class NativeFillEvent:
    timestamp: pd.Timestamp
    symbol: str
    side: OrderSide
    qty: float
    price: float
    fee: float
    order_id: Optional[str] = None
    tag: Optional[str] = None
    campaign_id: Optional[str] = None
    cycle_id: Optional[str] = None
    level_id: Optional[str] = None
    parent_order_id: Optional[str] = None
    oco_group_id: Optional[str] = None
    metadata: Mapping = field(default_factory=dict)


@dataclass(frozen=True)
class NativeOrderEvent:
    timestamp: pd.Timestamp
    bar: int
    event_name: str
    status: int
    order_id: Optional[str] = None
    target_order_id: Optional[str] = None
    parent_order_id: Optional[str] = None
    oco_group_id: Optional[str] = None
    tag: Optional[str] = None
    campaign_id: Optional[str] = None
    cycle_id: Optional[str] = None
    level_id: Optional[str] = None
    original_index: int = -1
    related_original_index: int = -1
    metadata: Mapping = field(default_factory=dict)


@dataclass(frozen=True)
class NativeActiveOrderSnapshot:
    order_id: Optional[str]
    symbol: Optional[str]
    side: Optional[str]
    order_type: Optional[str]
    status: int
    remaining_qty: float
    price: float
    trigger_price: float
    reduce_only: bool
    parent_order_id: Optional[str] = None
    group_id: Optional[str] = None
    oco_group_id: Optional[str] = None
    tag: Optional[str] = None
    campaign_id: Optional[str] = None
    cycle_id: Optional[str] = None
    level_id: Optional[str] = None


@dataclass(frozen=True, slots=True)
class NativeCommandBatch:
    """Optional compact callback container for reactive command batches.

    Existing strategies may continue returning ``list[OrderCommand]`` or a
    tuple.  This wrapper makes the batch boundary explicit for strategies that
    already build a fixed command tuple, without changing command semantics or
    the public ``OrderCommand`` type.
    """

    commands: Tuple[OrderCommand, ...] = field(default_factory=tuple)

    @classmethod
    def from_commands(cls, commands: Sequence[OrderCommand]) -> "NativeCommandBatch":
        return cls(tuple(commands))

    def __iter__(self):
        return iter(self.commands)

    def __len__(self) -> int:
        return len(self.commands)

    def __bool__(self) -> bool:
        return bool(self.commands)


@dataclass(frozen=True)
class NativeStrategyContext:
    bar_index: int
    timestamp: pd.Timestamp
    open: np.ndarray
    high: np.ndarray
    low: np.ndarray
    close: np.ndarray
    volume: np.ndarray
    equity: float
    available_equity: float
    initial_margin: float
    maintenance_margin: float
    positions: Mapping[str, float]
    fills_this_bar: Sequence[NativeFillEvent]
    order_events_this_bar: Sequence[NativeOrderEvent]
    active_orders: Sequence[NativeActiveOrderSnapshot]
    liquidated: bool
    symbols: Tuple[str, ...] = field(default_factory=tuple)
    size_order: Callable[..., float] = field(default=lambda **_: 0.0, repr=False, compare=False)


class NativeEventStrategyError(RuntimeError):
    """Raised when a reactive strategy callback fails."""

    def __init__(self, callback: str, bar_index: int, timestamp: pd.Timestamp, original: Exception):
        self.callback = callback
        self.bar_index = int(bar_index)
        self.timestamp = timestamp
        self.original = original
        super().__init__(
            f"native-event strategy callback {callback!r} failed at "
            f"bar_index={bar_index}, timestamp={timestamp}: {type(original).__name__}: {original}"
        )


class NativeEventStrategyProtocol:
    """
    Optional protocol-like base class for user strategies.

    Subclassing is not required; duck typing is used by the backend.
    """

    def initialize(self, context: NativeStrategyContext) -> Sequence[OrderCommand]:
        return ()

    def on_bar_close(self, context: NativeStrategyContext) -> Sequence[OrderCommand]:
        return ()

    def finalize(self, context: NativeStrategyContext) -> Sequence[OrderCommand]:
        return ()
