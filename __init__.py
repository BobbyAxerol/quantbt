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
from .endpoint import EndpointConfig, QuantBTEndpoint, format_metrics_report
from .walkforward import WalkForwardConfig, WalkForwardEngine, WalkForwardFold, WalkForwardResult, stitch_oos_outputs
from .engines import BacktestEngineV2, EventDrivenBacktestEngine, PortfolioBacktestEngine
from .backends   import NativeEventBackend, NativeEventConfig, NativeVectorizedBackend, NativeVectorizedConfig
from .adapters.nautilus import NautilusBacktestEngine
from .core.types import BacktestResult
from .core.results import BacktestResultV2
from .core.orders import BasketIntent, Fill, OrderIntent, Trade
from .core.basket import FrozenBasketPlan, build_frozen_basket_orders
from .core.arbitrage import (
    ArbExecutionPolicy,
    ArbitrageLeg,
    ArbitragePlan,
    ArbitrageSpec,
    ArbitrageType,
    BasisArbitrageSpec,
    CalendarSpreadSpec,
    ContractType,
    CarryModel,
    CarryModelKind,
    CostModel,
    CostModelKind,
    CrossExchangeArbSpec,
    FundingArbitrageSpec,
    HedgePolicy,
    HedgePolicyKind,
    IndexBasketArbSpec,
    LifecycleModel,
    LifecycleModelKind,
    MarginModel,
    MarginModelKind,
    OptionsVolArbSpec,
    PackageExecutionKind,
    PackageRejection,
    SignalModel,
    SignalModelKind,
    SizingPolicy,
    SizingPolicyKind,
    SpotPerpCashCarrySpec,
    SpreadFormula,
    SpreadFormulaKind,
    StatArbPairSpec,
    TriangularArbSpec,
    build_arbitrage_order_plan,
    round_down_to_step,
)
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
    "BacktestEngineV2",
    "EndpointConfig",
    "EventDrivenBacktestEngine",
    "MultiSymbolPortfolio",
    "NautilusBacktestEngine",
    "NativeEventBackend",
    "NativeEventConfig",
    "NativeVectorizedBackend",
    "NativeVectorizedConfig",
    "PortfolioBacktestEngine",
    "QuantBTEndpoint",
    "format_metrics_report",
    "WalkForwardConfig",
    "WalkForwardEngine",
    "WalkForwardFold",
    "WalkForwardResult",
    "stitch_oos_outputs",
    "BacktestResult",
    "BacktestResultV2",
    "AccountConfig",
    "ArbExecutionPolicy",
    "ArbitrageLeg",
    "ArbitragePlan",
    "ArbitrageSpec",
    "ArbitrageType",
    "AssetType",
    "BasisArbitrageSpec",
    "BasketExecutionPolicy",
    "BasketIntent",
    "BasketLegSpec",
    "BasketSpec",
    "CalendarSpreadSpec",
    "CarryModel",
    "CarryModelKind",
    "ContractType",
    "CostModel",
    "CostModelKind",
    "CrossExchangeArbSpec",
    "ExecutionConfig",
    "FeeModel",
    "Fill",
    "FillPricePolicy",
    "FundingArbitrageSpec",
    "FrozenBasketPlan",
    "HedgePolicy",
    "HedgePolicyKind",
    "IndexBasketArbSpec",
    "InstrumentSpec",
    "LifecycleModel",
    "LifecycleModelKind",
    "LiquiditySide",
    "MarginMode",
    "MarginModel",
    "MarginModelKind",
    "OmsMode",
    "OrderIntent",
    "OrderSide",
    "OrderType",
    "OptionsVolArbSpec",
    "PackageExecutionKind",
    "PackageRejection",
    "SameBarPolicy",
    "SignalModel",
    "SignalModelKind",
    "SignalSpec",
    "SizingPolicy",
    "SizingPolicyKind",
    "SpotPerpCashCarrySpec",
    "SpreadFormula",
    "SpreadFormulaKind",
    "StatArbPairSpec",
    "TimeInForce",
    "Trade",
    "TriangularArbSpec",
    "build_arbitrage_order_plan",
    "build_frozen_basket_orders",
    "round_down_to_step",
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
