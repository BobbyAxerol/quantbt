"""
NautilusTrader backend adapter.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Dict, Optional

import pandas as pd

from ...core.results import BacktestResultV2
from ._dependency import require_nautilus
from .instruments import ensure_utc_ohlcv, timeframe_to_nautilus
from .reports import result_from_nautilus_reports


@dataclass(frozen=True)
class NautilusBackendConfig:
    instrument_id: str = "BTCUSDT-PERP.BINANCE"
    timeframe: str = "1h"
    starting_balance: float = 10_000.0
    trade_notional: float = 1_000.0
    strategy_id: str = "QuantBT-001"
    trader_id: str = "BACKTESTER-001"
    log_level: str = "ERROR"
    bypass_logging: bool = True
    bypass_risk: bool = False
    close_positions_on_stop: bool = False
    use_test_instrument: bool = True
    metadata: Dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.starting_balance <= 0.0:
            raise ValueError("starting_balance must be > 0")
        if self.trade_notional < 0.0:
            raise ValueError("trade_notional must be >= 0")
        if "-" not in self.strategy_id:
            raise ValueError("strategy_id must contain '-' for Nautilus order_id_tag extraction")
        if "-" not in self.trader_id:
            raise ValueError("trader_id must contain '-'")


class NautilusBacktestEngine:
    """
    Optional high-fidelity backend powered by NautilusTrader.

    This adapter is intended as a validation/reference backend. It accepts a
    precomputed scalar signal series and submits market delta orders to reach a
    target notional. Research-scale optimizer runs should prefer native quantbt
    backends.
    """

    def __init__(self, config: NautilusBackendConfig):
        self.config = config

    @staticmethod
    def check_available() -> bool:
        require_nautilus()
        return True

    def run_signal_series(
        self,
        data: pd.DataFrame,
        signal: pd.Series,
        params: Optional[Dict] = None,
    ) -> BacktestResultV2:
        nt = require_nautilus()
        df = ensure_utc_ohlcv(data)
        sig = self._align_signal(signal, df.index)

        engine = nt.BacktestEngine(
            config=nt.BacktestEngineConfig(
                trader_id=nt.TraderId(self.config.trader_id),
                logging=nt.LoggingConfig(
                    log_level=self.config.log_level,
                    bypass_logging=self.config.bypass_logging,
                ),
                risk_engine=nt.RiskEngineConfig(bypass=self.config.bypass_risk),
            )
        )

        instrument = self._make_instrument(nt)
        engine.add_venue(
            venue=nt.BINANCE_VENUE,
            oms_type=nt.OmsType.NETTING,
            account_type=nt.AccountType.MARGIN,
            base_currency=nt.USDT,
            starting_balances=[nt.Money(self.config.starting_balance, nt.USDT)],
            fee_model=nt.MakerTakerFeeModel(),
            bar_execution=True,
        )
        engine.add_instrument(instrument)

        bar_type = nt.BarType.from_str(
            f"{instrument.id}-{timeframe_to_nautilus(self.config.timeframe)}-LAST-EXTERNAL"
        )
        wrangler = nt.BarDataWrangler(bar_type=bar_type, instrument=instrument)
        bars = wrangler.process(df)
        engine.add_data(bars)

        strategy_cls, config_cls = self._make_signal_strategy_classes(nt)
        strategy = strategy_cls(
            config=config_cls(
                strategy_id=self.config.strategy_id,
                instrument_id=str(instrument.id),
                bar_type=str(bar_type),
                trade_notional=Decimal(str(self.config.trade_notional)),
                signals={int(ts.value): float(v) for ts, v in sig.items()},
                close_positions_on_stop=self.config.close_positions_on_stop,
                order_id_tag=self.config.strategy_id.rsplit("-", 1)[-1],
            )
        )
        try:
            engine.add_strategy(strategy=strategy)
            engine.run()

            account_report = engine.trader.generate_account_report(nt.BINANCE_VENUE)
            orders_report = engine.trader.generate_orders_report()
            positions_report = engine.trader.generate_positions_report()
            fills_report = None
            if hasattr(engine.trader, "generate_order_fills_report"):
                fills_report = engine.trader.generate_order_fills_report()

            return result_from_nautilus_reports(
                account_report=account_report,
                orders_report=orders_report,
                fills_report=fills_report,
                positions_report=positions_report,
                symbols=[str(instrument.id)],
                initial_capital=self.config.starting_balance,
                metadata={
                    "instrument_id": str(instrument.id),
                    "bar_type": str(bar_type),
                    "close_positions_on_stop": self.config.close_positions_on_stop,
                    **self.config.metadata,
                    **(params or {}),
                },
            )
        finally:
            engine.reset()
            engine.dispose()

    def _make_instrument(self, nt):
        if not self.config.use_test_instrument:
            raise NotImplementedError("custom Nautilus instruments are not wired yet")
        if self.config.instrument_id != "BTCUSDT-PERP.BINANCE":
            raise NotImplementedError("Phase 5 test instrument support is limited to BTCUSDT-PERP.BINANCE")
        return nt.TestInstrumentProvider.btcusdt_perp_binance()

    @staticmethod
    def _align_signal(signal: pd.Series, idx: pd.DatetimeIndex) -> pd.Series:
        sig = signal.copy()
        if sig.index.tz is None:
            sig.index = sig.index.tz_localize("UTC")
        else:
            sig.index = sig.index.tz_convert("UTC")
        return sig.reindex(idx, method="ffill").fillna(0.0)

    @staticmethod
    def _make_signal_strategy_classes(nt):
        class QuantBTSignalConfig(nt.StrategyConfig, frozen=True):
            instrument_id: str
            bar_type: str
            trade_notional: Decimal
            signals: Dict[int, float]
            close_positions_on_stop: bool = False

        class QuantBTSignalStrategy(nt.Strategy):
            def __init__(self, config: QuantBTSignalConfig):
                super().__init__(config)
                self.instrument_id = nt.InstrumentId.from_str(config.instrument_id)
                self.bar_type = nt.BarType.from_str(config.bar_type)
                self.trade_notional = config.trade_notional
                self.signals = config.signals
                self.instrument = None
                self.current_signal = 0.0

            def on_start(self):
                self.instrument = self.cache.instrument(self.instrument_id)
                if self.instrument is None:
                    self.stop()
                    return
                self.subscribe_bars(self.bar_type)

            def on_bar(self, bar):
                signal = float(self.signals.get(int(bar.ts_event), self.current_signal))
                if signal == self.current_signal:
                    return
                price = self.cache.price(self.instrument_id, nt.PriceType.LAST)
                if price is None:
                    return
                current_qty = self._current_qty()
                target_qty = 0.0 if signal == 0.0 else float(self.trade_notional) * signal / float(price)
                delta = target_qty - current_qty
                if abs(delta) < float(self.instrument.size_increment):
                    self.current_signal = signal
                    return
                side = nt.OrderSide.BUY if delta > 0.0 else nt.OrderSide.SELL
                order = self.order_factory.market(
                    instrument_id=self.instrument_id,
                    order_side=side,
                    quantity=self.instrument.make_qty(abs(delta)),
                    time_in_force=nt.TimeInForce.IOC,
                )
                self.submit_order(order)
                self.current_signal = signal

            def _current_qty(self) -> float:
                positions = self.cache.positions_open(instrument_id=self.instrument_id)
                if not positions:
                    return 0.0
                pos = positions[0]
                if pos.side == nt.PositionSide.LONG:
                    return float(pos.quantity)
                if pos.side == nt.PositionSide.SHORT:
                    return -float(pos.quantity)
                return 0.0

            def on_stop(self):
                self.cancel_all_orders(self.instrument_id)
                if self.config.close_positions_on_stop:
                    self.close_all_positions(self.instrument_id)

        return QuantBTSignalStrategy, QuantBTSignalConfig
