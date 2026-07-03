"""
quantbt.core.orders
-------------------
Order, fill, and trade records used by event-driven backends and result V2.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional

from .schema import LiquiditySide, OrderSide, OrderType, TimeInForce


@dataclass(frozen=True)
class OrderIntent:
    timestamp: object
    symbol: str
    side: OrderSide
    order_type: OrderType
    qty: float
    price: Optional[float] = None
    trigger_price: Optional[float] = None
    tif: TimeInForce = TimeInForce.GTC
    reduce_only: bool = False
    order_id: Optional[str] = None
    tag: Optional[str] = None
    metadata: Dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.symbol:
            raise ValueError("symbol is required")
        if self.qty <= 0.0:
            raise ValueError("qty must be > 0")
        if self.order_type in (OrderType.LIMIT, OrderType.STOP_LIMIT):
            if self.price is None or self.price <= 0.0:
                raise ValueError("limit orders require price > 0")
        if self.order_type in (OrderType.STOP_MARKET, OrderType.STOP_LIMIT):
            if self.trigger_price is None or self.trigger_price <= 0.0:
                raise ValueError("stop orders require trigger_price > 0")

    @property
    def signed_qty(self) -> float:
        return self.qty * self.side.sign


@dataclass(frozen=True)
class BasketIntent:
    timestamp: object
    basket_id: str
    signal: float
    gross_notional: Optional[float] = None
    tag: Optional[str] = None
    metadata: Dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.basket_id:
            raise ValueError("basket_id is required")


@dataclass(frozen=True)
class Fill:
    timestamp: object
    symbol: str
    side: OrderSide
    qty: float
    price: float
    fee: float = 0.0
    liquidity: LiquiditySide = LiquiditySide.TAKER
    order_id: Optional[str] = None
    trade_id: Optional[str] = None
    metadata: Dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.symbol:
            raise ValueError("symbol is required")
        if self.qty <= 0.0:
            raise ValueError("qty must be > 0")
        if self.price <= 0.0:
            raise ValueError("price must be > 0")
        if self.fee < 0.0:
            raise ValueError("fee must be >= 0")

    @property
    def signed_qty(self) -> float:
        return self.qty * self.side.sign

    @property
    def notional(self) -> float:
        return self.qty * self.price


@dataclass(frozen=True)
class Trade:
    symbol: str
    qty: float
    side: OrderSide
    opened_at: object
    closed_at: object
    avg_entry: float
    avg_exit: float
    realized_pnl: float
    fees: float = 0.0
    trade_id: Optional[str] = None
    metadata: Dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.symbol:
            raise ValueError("symbol is required")
        if self.qty <= 0.0:
            raise ValueError("qty must be > 0")
        if self.avg_entry <= 0.0 or self.avg_exit <= 0.0:
            raise ValueError("avg_entry and avg_exit must be > 0")
        if self.fees < 0.0:
            raise ValueError("fees must be >= 0")
