"""
Lazy NautilusTrader imports.
"""

from __future__ import annotations

from types import SimpleNamespace


def require_nautilus():
    try:
        from nautilus_trader.adapters.binance import BINANCE_VENUE
        from nautilus_trader.backtest.engine import BacktestEngine, BacktestEngineConfig
        from nautilus_trader.backtest.models import MakerTakerFeeModel
        from nautilus_trader.config import LoggingConfig, RiskEngineConfig
        from nautilus_trader.model.currencies import USDT
        from nautilus_trader.model.data import Bar, BarType
        from nautilus_trader.model.enums import AccountType, OmsType, OrderSide, PositionSide, PriceType, TimeInForce
        from nautilus_trader.model.identifiers import InstrumentId, TraderId
        from nautilus_trader.model.objects import Money
        from nautilus_trader.persistence.wranglers import BarDataWrangler
        from nautilus_trader.test_kit.providers import TestInstrumentProvider
        from nautilus_trader.trading.strategy import Strategy, StrategyConfig
    except ImportError as exc:
        raise ImportError(
            "NautilusTrader adapter requires the optional 'nautilus_trader' package. "
            "Install NautilusTrader in the active environment or use a native quantbt backend."
        ) from exc

    return SimpleNamespace(
        AccountType=AccountType,
        BacktestEngine=BacktestEngine,
        BacktestEngineConfig=BacktestEngineConfig,
        Bar=Bar,
        BarDataWrangler=BarDataWrangler,
        BarType=BarType,
        BINANCE_VENUE=BINANCE_VENUE,
        InstrumentId=InstrumentId,
        LoggingConfig=LoggingConfig,
        MakerTakerFeeModel=MakerTakerFeeModel,
        Money=Money,
        OmsType=OmsType,
        OrderSide=OrderSide,
        PositionSide=PositionSide,
        PriceType=PriceType,
        RiskEngineConfig=RiskEngineConfig,
        Strategy=Strategy,
        StrategyConfig=StrategyConfig,
        TestInstrumentProvider=TestInstrumentProvider,
        TimeInForce=TimeInForce,
        TraderId=TraderId,
        USDT=USDT,
    )
