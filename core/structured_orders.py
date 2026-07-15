"""
Structured order package compilers.

These helpers convert transparent strategy-package specs into explicit
``OrderIntent`` objects. They intentionally do not contain alpha logic; the
generated orders are passed to event backends such as Nautilus for execution
simulation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional, Sequence

import pandas as pd

from .orders import OrderIntent
from .schema import OrderSide, OrderType, TimeInForce


@dataclass(frozen=True)
class StructuredOrderPlan:
    package_id: str
    package_type: str
    orders: tuple[OrderIntent, ...]
    order_table: pd.DataFrame
    metadata: Dict = field(default_factory=dict)


@dataclass(frozen=True)
class BracketOrderSpec:
    """
    Entry plus linked take-profit/stop-loss exits.

    ``exit_timestamp`` defaults to the entry timestamp. In bar-based validation,
    callers may set it to the next bar to model contingent exits becoming
    active only after the entry fill is known.
    """

    symbol: str
    entry_timestamp: object
    side: OrderSide
    qty: float
    package_id: str = "BRACKET-001"
    entry_order_type: OrderType = OrderType.MARKET
    entry_price: Optional[float] = None
    entry_trigger_price: Optional[float] = None
    take_profit_price: Optional[float] = None
    stop_loss_price: Optional[float] = None
    exit_timestamp: Optional[object] = None
    entry_tif: TimeInForce = TimeInForce.IOC
    exit_tif: TimeInForce = TimeInForce.GTC
    reduce_only_exits: bool = True
    tag: Optional[str] = None
    metadata: Dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "side", _coerce_enum(OrderSide, self.side))
        object.__setattr__(self, "entry_order_type", _coerce_enum(OrderType, self.entry_order_type))
        object.__setattr__(self, "entry_tif", _coerce_enum(TimeInForce, self.entry_tif))
        object.__setattr__(self, "exit_tif", _coerce_enum(TimeInForce, self.exit_tif))
        if not self.symbol:
            raise ValueError("BracketOrderSpec.symbol is required")
        if self.qty <= 0.0:
            raise ValueError("BracketOrderSpec.qty must be > 0")
        if self.take_profit_price is None and self.stop_loss_price is None:
            raise ValueError("BracketOrderSpec requires take_profit_price or stop_loss_price")


@dataclass(frozen=True)
class DcaGridSpec:
    """
    Deterministic DCA/grid order package.

    Base entry is a market order. Safety orders are GTC limits at grid prices.
    Optional TP/SL exits are reduce-only OCO siblings sized to the maximum
    planned ladder quantity, which is conservative for validation and auditable
    in ``metadata``.
    """

    symbol: str
    entry_timestamp: object
    side: OrderSide
    package_id: str = "DCA-GRID-001"
    base_qty: Optional[float] = None
    base_notional: Optional[float] = None
    entry_price: Optional[float] = None
    safety_order_count: int = 0
    safety_qty: Optional[float] = None
    safety_notional: Optional[float] = None
    step_pct: float = 0.01
    step_scale: float = 1.0
    volume_scale: float = 1.0
    take_profit_pct: Optional[float] = None
    stop_loss_pct: Optional[float] = None
    take_profit_price: Optional[float] = None
    stop_loss_price: Optional[float] = None
    exit_timestamp: Optional[object] = None
    entry_tif: TimeInForce = TimeInForce.IOC
    safety_tif: TimeInForce = TimeInForce.GTC
    exit_tif: TimeInForce = TimeInForce.GTC
    reduce_only_exits: bool = True
    tag: Optional[str] = None
    metadata: Dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "side", _coerce_enum(OrderSide, self.side))
        object.__setattr__(self, "entry_tif", _coerce_enum(TimeInForce, self.entry_tif))
        object.__setattr__(self, "safety_tif", _coerce_enum(TimeInForce, self.safety_tif))
        object.__setattr__(self, "exit_tif", _coerce_enum(TimeInForce, self.exit_tif))
        if not self.symbol:
            raise ValueError("DcaGridSpec.symbol is required")
        if self.base_qty is None and self.base_notional is None:
            raise ValueError("DcaGridSpec requires base_qty or base_notional")
        if self.base_qty is not None and self.base_qty <= 0.0:
            raise ValueError("DcaGridSpec.base_qty must be > 0")
        if self.base_notional is not None and self.base_notional <= 0.0:
            raise ValueError("DcaGridSpec.base_notional must be > 0")
        if self.safety_order_count < 0:
            raise ValueError("DcaGridSpec.safety_order_count must be >= 0")
        if self.safety_order_count and self.safety_qty is None and self.safety_notional is None:
            raise ValueError("DcaGridSpec safety orders require safety_qty or safety_notional")
        if self.step_pct <= 0.0 or self.step_scale <= 0.0 or self.volume_scale <= 0.0:
            raise ValueError("DCA step_pct, step_scale, and volume_scale must be > 0")


def build_bracket_order_plan(spec: BracketOrderSpec) -> StructuredOrderPlan:
    ts_entry = _utc_timestamp(spec.entry_timestamp)
    ts_exit = _utc_timestamp(spec.exit_timestamp or spec.entry_timestamp)
    package_id = spec.package_id
    oco_group_id = f"{package_id}:oco"
    tag_prefix = spec.tag or package_id

    common = {
        "package_id": package_id,
        "package_type": "bracket_oco",
        "structured_type": "bracket_oco",
        "oco_group_id": oco_group_id,
        "oco_policy": "cancel_sibling_on_first_exit_fill",
    }
    entry = OrderIntent(
        timestamp=ts_entry,
        symbol=spec.symbol,
        side=spec.side,
        order_type=spec.entry_order_type,
        qty=float(spec.qty),
        price=spec.entry_price,
        trigger_price=spec.entry_trigger_price,
        tif=spec.entry_tif,
        tag=f"{tag_prefix}:entry",
        metadata={**spec.metadata, **common, "leg_role": "entry"},
    )
    orders = [entry]
    exit_side = _opposite_side(spec.side)
    if spec.take_profit_price is not None:
        orders.append(
            OrderIntent(
                timestamp=ts_exit,
                symbol=spec.symbol,
                side=exit_side,
                order_type=OrderType.LIMIT,
                qty=float(spec.qty),
                price=float(spec.take_profit_price),
                tif=spec.exit_tif,
                reduce_only=spec.reduce_only_exits,
                tag=f"{tag_prefix}:take-profit",
                metadata={**spec.metadata, **common, "leg_role": "take_profit", "parent_tag": entry.tag},
            )
        )
    if spec.stop_loss_price is not None:
        orders.append(
            OrderIntent(
                timestamp=ts_exit,
                symbol=spec.symbol,
                side=exit_side,
                order_type=OrderType.STOP_MARKET,
                qty=float(spec.qty),
                trigger_price=float(spec.stop_loss_price),
                tif=spec.exit_tif,
                reduce_only=spec.reduce_only_exits,
                tag=f"{tag_prefix}:stop-loss",
                metadata={**spec.metadata, **common, "leg_role": "stop_loss", "parent_tag": entry.tag},
            )
        )
    return _structured_plan(package_id, "bracket_oco", orders, metadata={**spec.metadata, **common})


def build_dca_grid_order_plan(spec: DcaGridSpec, close: pd.Series) -> StructuredOrderPlan:
    close = _prepare_close(close)
    ts_entry = _utc_timestamp(spec.entry_timestamp)
    if ts_entry not in close.index:
        raise ValueError("DCA entry_timestamp must exist in close index")
    entry_price = float(spec.entry_price if spec.entry_price is not None else close.loc[ts_entry])
    if entry_price <= 0.0:
        raise ValueError("DCA entry_price must be > 0")

    package_id = spec.package_id
    oco_group_id = f"{package_id}:exit-oco"
    tag_prefix = spec.tag or package_id
    base_qty = float(spec.base_qty if spec.base_qty is not None else float(spec.base_notional) / entry_price)
    side_sign = spec.side.sign
    common = {
        "package_id": package_id,
        "package_type": "dca_grid",
        "structured_type": "dca_grid",
        "oco_group_id": oco_group_id,
        "oco_policy": "cancel_sibling_on_first_exit_fill",
        "entry_price_reference": entry_price,
    }

    orders = [
        OrderIntent(
            timestamp=ts_entry,
            symbol=spec.symbol,
            side=spec.side,
            order_type=OrderType.MARKET,
            qty=base_qty,
            tif=spec.entry_tif,
            tag=f"{tag_prefix}:base",
            metadata={
                **spec.metadata,
                **common,
                "leg_role": "base",
                "ladder_level": 1,
                "target_units": side_sign * base_qty,
            },
        )
    ]

    total_qty = base_qty
    weighted_cost = entry_price * base_qty
    for safety_index in range(int(spec.safety_order_count)):
        level = safety_index + 2
        deviation = _cumulative_grid_deviation(spec.step_pct, spec.step_scale, safety_index)
        trigger = entry_price * (1.0 - deviation if spec.side is OrderSide.BUY else 1.0 + deviation)
        if trigger <= 0.0:
            raise ValueError("DCA grid trigger price must be > 0")
        qty_base = float(spec.safety_qty if spec.safety_qty is not None else float(spec.safety_notional) / trigger)
        qty = qty_base * (float(spec.volume_scale) ** safety_index)
        total_qty += qty
        weighted_cost += trigger * qty
        orders.append(
            OrderIntent(
                timestamp=ts_entry,
                symbol=spec.symbol,
                side=spec.side,
                order_type=OrderType.LIMIT,
                qty=qty,
                price=trigger,
                tif=spec.safety_tif,
                tag=f"{tag_prefix}:safety-{safety_index + 1}",
                metadata={
                    **spec.metadata,
                    **common,
                    "leg_role": "safety",
                    "ladder_level": level,
                    "grid_deviation": deviation,
                    "target_units": side_sign * total_qty,
                },
            )
        )

    avg_full_ladder = weighted_cost / total_qty
    ts_exit = _utc_timestamp(spec.exit_timestamp or spec.entry_timestamp)
    exit_side = _opposite_side(spec.side)
    tp_price = spec.take_profit_price
    if tp_price is None and spec.take_profit_pct is not None:
        tp_price = avg_full_ladder * (1.0 + spec.take_profit_pct if spec.side is OrderSide.BUY else 1.0 - spec.take_profit_pct)
    sl_price = spec.stop_loss_price
    if sl_price is None and spec.stop_loss_pct is not None:
        sl_price = entry_price * (1.0 - spec.stop_loss_pct if spec.side is OrderSide.BUY else 1.0 + spec.stop_loss_pct)

    exit_meta = {
        **spec.metadata,
        **common,
        "exit_quantity_policy": "max_planned_ladder_qty",
        "max_planned_ladder_qty": total_qty,
        "full_ladder_avg_entry": avg_full_ladder,
    }
    if tp_price is not None:
        orders.append(
            OrderIntent(
                timestamp=ts_exit,
                symbol=spec.symbol,
                side=exit_side,
                order_type=OrderType.LIMIT,
                qty=total_qty,
                price=float(tp_price),
                tif=spec.exit_tif,
                reduce_only=spec.reduce_only_exits,
                tag=f"{tag_prefix}:take-profit",
                metadata={**exit_meta, "leg_role": "take_profit"},
            )
        )
    if sl_price is not None:
        orders.append(
            OrderIntent(
                timestamp=ts_exit,
                symbol=spec.symbol,
                side=exit_side,
                order_type=OrderType.STOP_MARKET,
                qty=total_qty,
                trigger_price=float(sl_price),
                tif=spec.exit_tif,
                reduce_only=spec.reduce_only_exits,
                tag=f"{tag_prefix}:stop-loss",
                metadata={**exit_meta, "leg_role": "stop_loss"},
            )
        )

    return _structured_plan(
        package_id,
        "dca_grid",
        orders,
        metadata={
            **spec.metadata,
            **common,
            "max_planned_ladder_qty": total_qty,
            "full_ladder_avg_entry": avg_full_ladder,
            "safety_order_count": int(spec.safety_order_count),
        },
    )


def _structured_plan(package_id: str, package_type: str, orders: Sequence[OrderIntent], metadata: Dict) -> StructuredOrderPlan:
    table = pd.DataFrame(
        [
            {
                "timestamp": _utc_timestamp(order.timestamp),
                "symbol": order.symbol,
                "side": order.side.value,
                "qty": float(order.qty),
                "order_type": order.order_type.value,
                "price": order.price,
                "trigger_price": order.trigger_price,
                "tif": order.tif.value,
                "reduce_only": bool(order.reduce_only),
                "tag": order.tag,
                "leg_role": order.metadata.get("leg_role"),
                "package_id": order.metadata.get("package_id"),
                "oco_group_id": order.metadata.get("oco_group_id"),
                "ladder_level": order.metadata.get("ladder_level"),
            }
            for order in orders
        ]
    )
    return StructuredOrderPlan(package_id=package_id, package_type=package_type, orders=tuple(orders), order_table=table, metadata=metadata)


def _cumulative_grid_deviation(step_pct: float, step_scale: float, safety_index: int) -> float:
    deviation = 0.0
    step = float(step_pct)
    for _ in range(safety_index + 1):
        deviation += step
        step *= float(step_scale)
    return deviation


def _prepare_close(close: pd.Series) -> pd.Series:
    out = close.copy()
    out.index = pd.DatetimeIndex(out.index)
    out.index = out.index.tz_localize("UTC") if out.index.tz is None else out.index.tz_convert("UTC")
    return out.sort_index()


def _utc_timestamp(value) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    return ts.tz_localize("UTC") if ts.tz is None else ts.tz_convert("UTC")


def _opposite_side(side: OrderSide) -> OrderSide:
    return OrderSide.SELL if side is OrderSide.BUY else OrderSide.BUY


def _coerce_enum(enum_cls, value):
    if isinstance(value, enum_cls):
        return value
    return enum_cls(str(value).lower().strip())
