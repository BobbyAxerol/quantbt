"""
quantbt.core.schema
-------------------
Domain configuration objects shared by native and optional adapter backends.

These dataclasses are intentionally lightweight and dependency-free beyond the
standard library. Hot loops should receive ndarray views derived from these
objects, not the objects themselves.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Optional


class AssetType(str, Enum):
    CRYPTO = "crypto"
    STOCK = "stock"
    FUTURE = "future"
    FX = "fx"


class MarginMode(str, Enum):
    CASH = "cash"
    ISOLATED = "isolated"
    CROSS = "cross"
    PORTFOLIO = "portfolio"


class OmsMode(str, Enum):
    NETTING = "netting"
    HEDGING = "hedging"


class OrderSide(str, Enum):
    BUY = "buy"
    SELL = "sell"

    @property
    def sign(self) -> float:
        return 1.0 if self is OrderSide.BUY else -1.0


class OrderType(str, Enum):
    MARKET = "market"
    LIMIT = "limit"
    STOP_MARKET = "stop_market"
    STOP_LIMIT = "stop_limit"


class TimeInForce(str, Enum):
    GTC = "gtc"
    IOC = "ioc"
    FOK = "fok"
    GTD = "gtd"


class LiquiditySide(str, Enum):
    MAKER = "maker"
    TAKER = "taker"


class FillPricePolicy(str, Enum):
    CLOSE = "close"
    OPEN = "open"
    TOUCH = "touch"
    NEXT_OPEN = "next_open"


class SameBarPolicy(str, Enum):
    CONSERVATIVE = "conservative"
    ENTRY_FIRST = "entry_first"
    EXIT_FIRST = "exit_first"


@dataclass(frozen=True)
class FeeModel:
    maker: float = 0.0
    taker: float = 0.0

    def __post_init__(self) -> None:
        if self.maker < 0.0 or self.taker < 0.0:
            raise ValueError("fee rates must be >= 0")

    def rate_for(self, liquidity: LiquiditySide) -> float:
        return self.maker if liquidity is LiquiditySide.MAKER else self.taker


@dataclass(frozen=True)
class InstrumentSpec:
    symbol: str
    asset_type: AssetType = AssetType.CRYPTO
    contract_size: float = 1.0
    tick_size: float = 0.0
    lot_size: float = 0.0
    min_qty: float = 0.0
    min_notional: float = 0.0
    price_precision: Optional[int] = None
    qty_precision: Optional[int] = None
    fee_model: FeeModel = field(default_factory=FeeModel)
    metadata: Dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.symbol:
            raise ValueError("symbol is required")
        if self.contract_size <= 0.0:
            raise ValueError("contract_size must be > 0")
        if self.tick_size < 0.0 or self.lot_size < 0.0:
            raise ValueError("tick_size and lot_size must be >= 0")
        if self.min_qty < 0.0 or self.min_notional < 0.0:
            raise ValueError("min_qty and min_notional must be >= 0")
        if self.price_precision is not None and self.price_precision < 0:
            raise ValueError("price_precision must be >= 0")
        if self.qty_precision is not None and self.qty_precision < 0:
            raise ValueError("qty_precision must be >= 0")


@dataclass(frozen=True)
class AccountConfig:
    initial_capital: float
    base_currency: str = "USD"
    leverage: float = 1.0
    maintenance_ratio: float = 0.005
    margin_mode: MarginMode = MarginMode.CROSS
    oms_mode: OmsMode = OmsMode.NETTING
    margin_buffer: float = 0.0
    metadata: Dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.initial_capital <= 0.0:
            raise ValueError("initial_capital must be > 0")
        if self.leverage <= 0.0:
            raise ValueError("leverage must be > 0")
        if self.maintenance_ratio < 0.0:
            raise ValueError("maintenance_ratio must be >= 0")
        if self.margin_buffer < 0.0:
            raise ValueError("margin_buffer must be >= 0")

    @property
    def initial_buying_power(self) -> float:
        return self.initial_capital * self.leverage


@dataclass(frozen=True)
class ExecutionConfig:
    fill_price_policy: FillPricePolicy = FillPricePolicy.CLOSE
    same_bar_policy: SameBarPolicy = SameBarPolicy.CONSERVATIVE
    slippage_bps: float = 0.0
    allow_partial_fill: bool = False
    reject_on_insufficient_margin: bool = True
    min_order_notional: float = 0.0
    metadata: Dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.slippage_bps < 0.0:
            raise ValueError("slippage_bps must be >= 0")
        if self.min_order_notional < 0.0:
            raise ValueError("min_order_notional must be >= 0")

    @property
    def slippage_rate(self) -> float:
        return self.slippage_bps / 10_000.0


@dataclass(frozen=True)
class SignalSpec:
    timestamp: object
    symbol: str
    value: float
    kind: str = "weight"
    metadata: Dict = field(default_factory=dict)


@dataclass(frozen=True)
class BasketLegSpec:
    symbol: str
    ratio: float
    metadata: Dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.symbol:
            raise ValueError("symbol is required")


@dataclass(frozen=True)
class BasketSpec:
    basket_id: str
    legs: tuple[BasketLegSpec, ...]
    gross_notional: float
    freeze_hedge: bool = True
    hedged_margin_offset: float = 0.0
    metadata: Dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.basket_id:
            raise ValueError("basket_id is required")
        if len(self.legs) == 0:
            raise ValueError("basket must contain at least one leg")
        if self.gross_notional < 0.0:
            raise ValueError("gross_notional must be >= 0")
        if not 0.0 <= self.hedged_margin_offset <= 1.0:
            raise ValueError("hedged_margin_offset must be in [0, 1]")
