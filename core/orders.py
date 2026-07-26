"""
quantbt.core.orders
-------------------
Order, fill, and trade records used by event-driven backends and result V2.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Optional, Sequence, Tuple

from .schema import LiquiditySide, OrderSide, OrderType, TimeInForce


class OrderAction(str, Enum):
    """Lifecycle command consumed by the native-event v2 compiler."""

    PLACE = "place"
    CANCEL = "cancel"
    REPLACE = "replace"
    AMEND = "amend"
    CANCEL_ALL = "cancel_all"


class OrderActivationPolicy(str, Enum):
    """When a placed child order becomes eligible for matching."""

    IMMEDIATE = "immediate"
    ON_PARENT_FIRST_FILL = "on_parent_first_fill"
    ON_PARENT_FULL_FILL = "on_parent_full_fill"


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
class OrderCommand:
    """
    Canonical order-lifecycle command for native-event v2 and adapters.

    `OrderIntent` remains the backwards-compatible shorthand for an immediate
    PLACE command. Phase 30A only defines and compiles this contract; lifecycle
    matching is wired into a dedicated v2 engine phase.
    """

    timestamp: object
    action: OrderAction = OrderAction.PLACE
    symbol: Optional[str] = None
    side: Optional[OrderSide] = None
    order_type: Optional[OrderType] = None
    qty: Optional[float] = None
    price: Optional[float] = None
    trigger_price: Optional[float] = None
    tif: TimeInForce = TimeInForce.GTC
    reduce_only: bool = False
    order_id: Optional[str] = None
    target_order_id: Optional[str] = None
    parent_order_id: Optional[str] = None
    group_id: Optional[str] = None
    oco_group_id: Optional[str] = None
    activation_policy: OrderActivationPolicy = OrderActivationPolicy.IMMEDIATE
    expires_at: Optional[object] = None
    tag: Optional[str] = None
    metadata: Dict = field(default_factory=dict)
    tag_prefix: Optional[str] = None

    def __post_init__(self) -> None:
        action = _normalize_order_action(self.action)
        object.__setattr__(self, "action", action)

        activation = _normalize_activation_policy(self.activation_policy)
        object.__setattr__(self, "activation_policy", activation)

        if action in (OrderAction.PLACE, OrderAction.REPLACE):
            if not self.symbol:
                raise ValueError(f"{action.value} command requires symbol")
            if self.side is None:
                raise ValueError(f"{action.value} command requires side")
            if self.order_type is None:
                raise ValueError(f"{action.value} command requires order_type")
            if self.qty is None or self.qty <= 0.0:
                raise ValueError(f"{action.value} command requires qty > 0")
            if self.order_type in (OrderType.LIMIT, OrderType.STOP_LIMIT):
                if self.price is None or self.price <= 0.0:
                    raise ValueError("limit commands require price > 0")
            if self.order_type in (OrderType.STOP_MARKET, OrderType.STOP_LIMIT):
                if self.trigger_price is None or self.trigger_price <= 0.0:
                    raise ValueError("stop commands require trigger_price > 0")
            if action is OrderAction.REPLACE and not self.target_order_id:
                raise ValueError("replace command requires target_order_id")
        elif action in (OrderAction.CANCEL, OrderAction.AMEND):
            if not self.target_order_id:
                raise ValueError(f"{action.value} command requires target_order_id")
            if action is OrderAction.AMEND:
                if self.qty is not None and self.qty <= 0.0:
                    raise ValueError("amend qty must be > 0")
                if self.price is not None and self.price <= 0.0:
                    raise ValueError("amend price must be > 0")
                if self.trigger_price is not None and self.trigger_price <= 0.0:
                    raise ValueError("amend trigger_price must be > 0")
        elif action is OrderAction.CANCEL_ALL:
            pass
        else:
            raise NotImplementedError(f"unsupported order action={action!r}")

    @classmethod
    def from_intent(cls, intent: OrderIntent) -> "OrderCommand":
        return cls(
            timestamp=intent.timestamp,
            action=OrderAction.PLACE,
            symbol=intent.symbol,
            side=intent.side,
            order_type=intent.order_type,
            qty=float(intent.qty),
            price=intent.price,
            trigger_price=intent.trigger_price,
            tif=intent.tif,
            reduce_only=intent.reduce_only,
            order_id=intent.order_id,
            tag=intent.tag,
            metadata=dict(intent.metadata),
        )

    def to_intent(self) -> OrderIntent:
        if self.action is not OrderAction.PLACE:
            raise ValueError("only place commands can be converted to OrderIntent")
        if self.symbol is None or self.side is None or self.order_type is None or self.qty is None:
            raise ValueError("place command is incomplete")
        return OrderIntent(
            timestamp=self.timestamp,
            symbol=self.symbol,
            side=self.side,
            order_type=self.order_type,
            qty=float(self.qty),
            price=self.price,
            trigger_price=self.trigger_price,
            tif=self.tif,
            reduce_only=self.reduce_only,
            order_id=self.order_id,
            tag=self.tag,
            metadata=dict(self.metadata),
        )

    @property
    def signed_qty(self) -> float:
        if self.side is None or self.qty is None:
            return 0.0
        return float(self.qty) * self.side.sign


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


def _normalize_order_action(action: OrderAction | str) -> OrderAction:
    if isinstance(action, OrderAction):
        return action
    return OrderAction(str(action))


def _normalize_activation_policy(policy: OrderActivationPolicy | str) -> OrderActivationPolicy:
    if isinstance(policy, OrderActivationPolicy):
        return policy
    return OrderActivationPolicy(str(policy))


def order_intents_to_lifecycle_commands(
    orders: Sequence[OrderIntent],
    *,
    linked_metadata: bool = True,
) -> Tuple[OrderCommand, ...]:
    """
    Convert `OrderIntent` records into lifecycle-v2 `OrderCommand` records.

    Structured package builders already carry parent/OCO information in
    metadata. This helper lifts those fields into the explicit command contract
    while preserving all old order intent fields for compatibility.
    """
    commands = []
    tag_to_id = {}
    for idx, order in enumerate(orders):
        order_id = order.order_id or order.tag or f"order-{idx}"
        tag_to_id[order.tag] = order_id

    for idx, order in enumerate(orders):
        metadata = dict(order.metadata)
        order_id = order.order_id or order.tag or f"order-{idx}"
        parent_id = None
        oco_group_id = None
        activation = OrderActivationPolicy.IMMEDIATE
        group_id = None
        if linked_metadata:
            group_id = metadata.get("group_id") or metadata.get("package_id") or metadata.get("arb_id")
            leg_role = str(metadata.get("leg_role", "")).lower().strip()
            if order.reduce_only or leg_role in {"take_profit", "stop_loss", "exit"}:
                oco_group_id = metadata.get("oco_group_id")
            parent_ref = metadata.get("parent_order_id") or metadata.get("parent_tag")
            if parent_ref is not None:
                parent_id = tag_to_id.get(parent_ref, str(parent_ref))
                activation = OrderActivationPolicy.ON_PARENT_FIRST_FILL
        commands.append(
            OrderCommand(
                timestamp=order.timestamp,
                action=OrderAction.PLACE,
                symbol=order.symbol,
                side=order.side,
                order_type=order.order_type,
                qty=float(order.qty),
                price=order.price,
                trigger_price=order.trigger_price,
                tif=order.tif,
                reduce_only=order.reduce_only,
                order_id=order_id,
                parent_order_id=parent_id,
                group_id=None if group_id is None else str(group_id),
                oco_group_id=None if oco_group_id is None else str(oco_group_id),
                activation_policy=activation,
                tag=order.tag,
                metadata=metadata,
            )
        )
    return tuple(commands)
