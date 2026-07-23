"""
Option package intents and compiler.

This layer turns option-domain package legs into QuantBT `OrderIntent` leaves.
It does not execute orders or maintain a ledger.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Optional, Sequence, Tuple, Union

from ..core.orders import OrderIntent
from ..core.schema import OrderSide, OrderType, TimeInForce


class OptionPackageExecutionPolicy(str, Enum):
    ATOMIC_ALL_OR_NONE = "atomic_all_or_none"
    BEST_EFFORT = "best_effort"
    SEQUENTIAL = "sequential"
    HEDGE_AFTER_PRIMARY = "hedge_after_primary"
    REBALANCE_ONLY = "rebalance_only"


@dataclass(frozen=True)
class OptionPackageLeg:
    """
    One option leg inside a package.

    `side` owns direction. `ratio` is always positive and scales from package
    quantity, so callers cannot hide direction in a negative ratio.
    """

    instrument_id: str
    side: Union[OrderSide, str]
    ratio: float
    order_type: Union[OrderType, str] = OrderType.MARKET
    limit_price: Optional[float] = None
    tif: Union[TimeInForce, str] = TimeInForce.FOK
    role: str = "leg"
    tag: Optional[str] = None
    metadata: Dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "side", _coerce_enum(OrderSide, self.side, "side"))
        object.__setattr__(self, "order_type", _coerce_enum(OrderType, self.order_type, "order_type"))
        object.__setattr__(self, "tif", _coerce_enum(TimeInForce, self.tif, "tif"))
        if not self.instrument_id:
            raise ValueError("instrument_id is required")
        if self.ratio <= 0.0:
            raise ValueError("ratio must be > 0; side owns direction")
        if self.order_type not in (OrderType.MARKET, OrderType.LIMIT):
            raise ValueError("Phase 4 option package legs support market and limit orders only")
        if self.order_type in (OrderType.LIMIT, OrderType.STOP_LIMIT):
            if self.limit_price is None or self.limit_price <= 0.0:
                raise ValueError("limit option legs require limit_price > 0")
        if not self.role:
            raise ValueError("role is required")


@dataclass(frozen=True)
class OptionPackageIntent:
    timestamp_ns: int
    package_id: str
    legs: Tuple[OptionPackageLeg, ...]
    quantity: float = 1.0
    execution_policy: Union[OptionPackageExecutionPolicy, str] = OptionPackageExecutionPolicy.ATOMIC_ALL_OR_NONE
    max_debit: Optional[float] = None
    min_credit: Optional[float] = None
    tag: Optional[str] = None
    metadata: Dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "execution_policy",
            _coerce_enum(OptionPackageExecutionPolicy, self.execution_policy, "execution_policy"),
        )
        object.__setattr__(self, "timestamp_ns", int(self.timestamp_ns))
        object.__setattr__(self, "legs", tuple(self.legs))
        if self.timestamp_ns <= 0:
            raise ValueError("timestamp_ns must be > 0")
        if not self.package_id:
            raise ValueError("package_id is required")
        if len(self.legs) == 0:
            raise ValueError("OptionPackageIntent requires at least one leg")
        if self.quantity <= 0.0:
            raise ValueError("quantity must be > 0")
        if self.max_debit is not None and self.max_debit < 0.0:
            raise ValueError("max_debit must be >= 0")
        if self.min_credit is not None and self.min_credit < 0.0:
            raise ValueError("min_credit must be >= 0")


def compile_option_package_orders(package: OptionPackageIntent) -> Tuple[OrderIntent, ...]:
    """Compile an option package to `OrderIntent` leaves with package metadata."""
    orders = []
    atomicity = _atomicity_label(package.execution_policy)
    for leg_index, leg in enumerate(package.legs):
        metadata = {
            **leg.metadata,
            "package_id": package.package_id,
            "package_type": "option_package",
            "option_package_id": package.package_id,
            "option_leg_index": int(leg_index),
            "option_leg_ratio": float(leg.ratio),
            "option_leg_role": leg.role,
            "option_execution_policy": package.execution_policy.value,
            "atomicity": atomicity,
            "exchange_combo": False,
            "block_trade_style": False,
            "simulated_atomicity": package.execution_policy is OptionPackageExecutionPolicy.ATOMIC_ALL_OR_NONE,
        }
        qty = float(package.quantity) * float(leg.ratio)
        order = OrderIntent(
            timestamp=package.timestamp_ns,
            symbol=leg.instrument_id,
            side=leg.side,
            order_type=leg.order_type,
            qty=qty,
            price=leg.limit_price,
            tif=leg.tif,
            tag=leg.tag or package.tag,
            metadata=metadata,
        )
        orders.append(order)
    return tuple(orders)


def _atomicity_label(policy: OptionPackageExecutionPolicy) -> str:
    if policy is OptionPackageExecutionPolicy.ATOMIC_ALL_OR_NONE:
        return "simulated_all_or_none"
    if policy is OptionPackageExecutionPolicy.HEDGE_AFTER_PRIMARY:
        return "simulated_primary_then_hedge"
    if policy is OptionPackageExecutionPolicy.REBALANCE_ONLY:
        return "simulated_rebalance_only"
    return f"simulated_{policy.value}"


def _coerce_enum(enum_cls, value, field_name: str):
    if isinstance(value, enum_cls):
        return value
    try:
        return enum_cls(str(value))
    except ValueError as exc:
        raise ValueError(f"{field_name} must be one of {[item.value for item in enum_cls]}") from exc
