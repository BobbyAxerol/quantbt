"""
quantbt
=======
Vectorised Binance-Futures backtest SDK.

Quick start
-----------
Single symbol::

    from quantbt import BacktestEngine

    bt = BacktestEngine(
        Datetime        = df["Datetime"],
        Position        = signal,          # pd.Series of weights
        Close           = df["Close"],
        fee             = 0.0004,
        initial_capital = 20_000,
        leverage        = 10,
        hedge_type      = "signal_notional",
        alloc_per_trade = 100_000,
    )
    bt.analyze()                           # text report + chart
    result = bt.result                     # BacktestResult dataclass

Multi-symbol portfolio::

    from quantbt import MultiSymbolPortfolio

    msp = MultiSymbolPortfolio(
        positions  = {"BTC": pos_btc, "ETH": pos_eth},
        closes     = {"BTC": close_btc, "ETH": close_eth},
        datetime_index = common_dt,
        mode       = "market_neutral",
        asset_type = "crypto",
    )
    msp.analyze()

Advanced — standalone metrics + plots::

    from quantbt.metrics import full_report, sharpe, max_drawdown
    from quantbt.viz     import quick_plot, tearsheet

    rpt = full_report(result)
    quick_plot(result, theme="light")
    tearsheet(result)
"""

from .backtester import BacktestEngine
from .portfolio  import MultiSymbolPortfolio
from .backends   import NativeEventBackend, NativeEventConfig, NativeVectorizedBackend, NativeVectorizedConfig
from .core.types import BacktestResult
from .core.results import BacktestResultV2
from .core.orders import BasketIntent, Fill, OrderIntent, Trade
from .core.basket import FrozenBasketPlan, build_frozen_basket_orders
from .core.schema import (
    AccountConfig,
    AssetType,
    BasketExecutionPolicy,
    BasketLegSpec,
    BasketSpec,
    ExecutionConfig,
    FeeModel,
    FillPricePolicy,
    InstrumentSpec,
    LiquiditySide,
    MarginMode,
    OmsMode,
    OrderSide,
    OrderType,
    SameBarPolicy,
    SignalSpec,
    TimeInForce,
)

from .metrics import (
    full_report,
    sharpe,
    sortino,
    calmar,
    omega,
    cagr,
    total_return,
    max_drawdown,
    max_drawdown_pct,
    hitrate,
    profit_factor,
    rolling_sharpe,
    rolling_drawdown,
)

from .viz import quick_plot, tearsheet, apply_theme

__version__ = "0.1.0"
__author__  = "quantbt"

__all__ = [
    # engines
    "BacktestEngine",
    "MultiSymbolPortfolio",
    "NativeEventBackend",
    "NativeEventConfig",
    "NativeVectorizedBackend",
    "NativeVectorizedConfig",
    "BacktestResult",
    "BacktestResultV2",
    "AccountConfig",
    "AssetType",
    "BasketExecutionPolicy",
    "BasketIntent",
    "BasketLegSpec",
    "BasketSpec",
    "ExecutionConfig",
    "FeeModel",
    "Fill",
    "FillPricePolicy",
    "FrozenBasketPlan",
    "InstrumentSpec",
    "LiquiditySide",
    "MarginMode",
    "OmsMode",
    "OrderIntent",
    "OrderSide",
    "OrderType",
    "SameBarPolicy",
    "SignalSpec",
    "TimeInForce",
    "Trade",
    "build_frozen_basket_orders",
    # metrics
    "full_report",
    "sharpe",
    "sortino",
    "calmar",
    "omega",
    "cagr",
    "total_return",
    "max_drawdown",
    "max_drawdown_pct",
    "hitrate",
    "profit_factor",
    "rolling_sharpe",
    "rolling_drawdown",
    # viz
    "quick_plot",
    "tearsheet",
    "apply_theme",
]
