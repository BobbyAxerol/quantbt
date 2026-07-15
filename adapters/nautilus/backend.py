"""
NautilusTrader backend adapter.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Dict, List, Optional, Sequence

import pandas as pd

from ...core.orders import OrderIntent
from ...core.results import BacktestResultV2
from ...core.schema import OrderSide
from ._dependency import require_nautilus
from .instruments import ensure_utc_ohlcv, make_binance_perpetual, timeframe_to_nautilus
from .reports import result_from_nautilus_reports


@dataclass(frozen=True)
class NautilusBackendConfig:
    instrument_id: str = "BTCUSDT-PERP.BINANCE"
    timeframe: str = "1h"
    starting_balance: float = 10_000.0
    trade_notional: float = 1_000.0
    sizing_mode: str = "signal_notional"
    use_pyramiding: bool = True
    strategy_id: str = "QuantBT-001"
    trader_id: str = "BACKTESTER-001"
    log_level: str = "ERROR"
    bypass_logging: bool = True
    bypass_risk: bool = False
    close_positions_on_stop: bool = False
    force_flat_on_stop: Optional[bool] = None
    use_test_instrument: bool = True
    metadata: Dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.force_flat_on_stop is not None:
            object.__setattr__(self, "close_positions_on_stop", bool(self.force_flat_on_stop))
        if self.starting_balance <= 0.0:
            raise ValueError("starting_balance must be > 0")
        if self.trade_notional < 0.0:
            raise ValueError("trade_notional must be >= 0")
        sizing = self.sizing_mode.lower().strip()
        if sizing in ("dca_ladder", "dca"):
            raise NotImplementedError("Nautilus DCA/grid validation is not implemented yet")
        if sizing not in {"signal_notional", "signal", "notional", "unit", "%_equity", "pct_equity"}:
            raise ValueError("sizing_mode must be one of signal_notional, notional, unit, or %_equity")
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
                starting_balance=Decimal(str(self.config.starting_balance)),
                sizing_mode=self.config.sizing_mode,
                use_pyramiding=self.config.use_pyramiding,
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
                closes={str(instrument.id): df["close"]},
                metadata={
                    "instrument_id": str(instrument.id),
                    "bar_type": str(bar_type),
                    "sizing_mode": self.config.sizing_mode,
                    "trade_notional": self.config.trade_notional,
                    "use_pyramiding": self.config.use_pyramiding,
                    "close_positions_on_stop": self.config.close_positions_on_stop,
                    **self.config.metadata,
                    **(params or {}),
                },
            )
        finally:
            engine.reset()
            engine.dispose()

    def run_order_packages(
        self,
        data: Dict[str, pd.DataFrame],
        orders: Sequence[OrderIntent],
        symbols: Optional[Sequence[str]] = None,
        params: Optional[Dict] = None,
    ) -> BacktestResultV2:
        """
        Run explicit component package orders through NautilusTrader.

        Orders are submitted as market IOC component orders at their original
        timestamps. The returned result exposes raw Nautilus reports plus a
        stable `package_order_map` linking quantbt package intents to symbols,
        target units, and original package metadata.
        """
        if not orders:
            raise ValueError("run_order_packages requires at least one OrderIntent")
        nt = require_nautilus()
        symbol_list = list(symbols or data.keys())
        if not symbol_list:
            raise ValueError("symbols are required")
        missing = sorted(set(symbol_list) - set(data.keys()))
        if missing:
            raise ValueError(f"missing Nautilus data for symbols: {missing}")

        frames = {symbol: ensure_utc_ohlcv(data[symbol]) for symbol in symbol_list}
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

        instruments = {symbol: make_binance_perpetual(symbol, nt) for symbol in symbol_list}
        instrument_ids = {symbol: str(instrument.id) for symbol, instrument in instruments.items()}
        package_order_map = build_nautilus_package_order_table(orders, instrument_ids=instrument_ids)
        engine.add_venue(
            venue=nt.BINANCE_VENUE,
            oms_type=nt.OmsType.NETTING,
            account_type=nt.AccountType.MARGIN,
            base_currency=nt.USDT,
            starting_balances=[nt.Money(self.config.starting_balance, nt.USDT)],
            fee_model=nt.MakerTakerFeeModel(),
            bar_execution=True,
        )
        for instrument in instruments.values():
            engine.add_instrument(instrument)

        bar_types = {}
        for symbol, instrument in instruments.items():
            bar_type = nt.BarType.from_str(
                f"{instrument.id}-{timeframe_to_nautilus(self.config.timeframe)}-LAST-EXTERNAL"
            )
            wrangler = nt.BarDataWrangler(bar_type=bar_type, instrument=instrument)
            engine.add_data(wrangler.process(frames[symbol]))
            bar_types[symbol] = str(bar_type)

        strategy_cls, config_cls = self._make_package_strategy_classes(nt)
        strategy = strategy_cls(
            config=config_cls(
                strategy_id=self.config.strategy_id,
                instrument_ids=[str(instruments[symbol].id) for symbol in symbol_list],
                bar_types=bar_types,
                package_orders=_orders_payload(orders, instrument_ids=instrument_ids),
                close_positions_on_stop=self.config.close_positions_on_stop,
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

            instrument_symbols = [str(instruments[symbol].id) for symbol in symbol_list]
            close_map = {str(instruments[symbol].id): frames[symbol]["close"] for symbol in symbol_list}
            return result_from_nautilus_reports(
                account_report=account_report,
                orders_report=orders_report,
                fills_report=fills_report,
                positions_report=positions_report,
                symbols=instrument_symbols,
                initial_capital=self.config.starting_balance,
                closes=close_map,
                metadata={
                    "backend": "nautilus",
                    "engine": "nautilus_package_orders",
                    "input_mode": "order_packages",
                    "instrument_id": instrument_symbols[0] if len(instrument_symbols) == 1 else None,
                    "instrument_ids": instrument_symbols,
                    "bar_types": bar_types,
                    "sizing_mode": self.config.sizing_mode,
                    "trade_notional": self.config.trade_notional,
                    "use_pyramiding": self.config.use_pyramiding,
                    "package_order_map": package_order_map,
                    "package_orders_count": int(len(package_order_map)),
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
        return make_binance_perpetual(self.config.instrument_id, nt)

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
            starting_balance: Decimal
            signals: Dict[int, float]
            sizing_mode: str = "signal_notional"
            use_pyramiding: bool = True
            close_positions_on_stop: bool = False

        class QuantBTSignalStrategy(nt.Strategy):
            def __init__(self, config: QuantBTSignalConfig):
                super().__init__(config)
                self.instrument_id = nt.InstrumentId.from_str(config.instrument_id)
                self.bar_type = nt.BarType.from_str(config.bar_type)
                self.trade_notional = config.trade_notional
                self.starting_balance = config.starting_balance
                self.sizing_mode = config.sizing_mode.lower().strip()
                self.use_pyramiding = bool(config.use_pyramiding)
                self.signals = config.signals
                self.instrument = None
                self.current_signal = 0.0
                self.first_price = 0.0

            def on_start(self):
                self.instrument = self.cache.instrument(self.instrument_id)
                if self.instrument is None:
                    self.stop()
                    return
                self.subscribe_bars(self.bar_type)

            def on_bar(self, bar):
                raw_signal = float(self.signals.get(int(bar.ts_event), self.current_signal))
                signal = raw_signal if self.use_pyramiding else self._sign(raw_signal)
                signal_changed = signal != self.current_signal
                if self.sizing_mode not in ("notional",) and not signal_changed:
                    return
                price = self.cache.price(self.instrument_id, nt.PriceType.LAST)
                if price is None:
                    return
                price_value = float(price)
                if self.first_price <= 0.0:
                    self.first_price = price_value
                current_qty = self._current_qty()
                target_qty = self._target_qty(signal=signal, price=price_value)
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

            def _target_qty(self, signal: float, price: float) -> float:
                if signal == 0.0 or price <= 0.0:
                    return 0.0
                sizing = self.sizing_mode
                allocation = float(self.trade_notional)
                if sizing in ("signal_notional", "signal", "notional"):
                    return allocation * signal / price
                if sizing == "unit":
                    return 0.0 if self.first_price <= 0.0 else allocation * signal / self.first_price
                if sizing in ("%_equity", "pct_equity"):
                    alloc_pct = allocation / 100.0 if allocation > 1.0 else allocation
                    return self._equity() * alloc_pct * signal / price
                raise RuntimeError(f"unsupported Nautilus sizing_mode={self.sizing_mode!r}")

            def _equity(self) -> float:
                equity = self.portfolio.equity(venue=self.instrument_id.venue)
                if equity is None:
                    return float(self.starting_balance)
                if isinstance(equity, dict):
                    if not equity:
                        return float(self.starting_balance)
                    equity = next(iter(equity.values()))
                try:
                    return float(equity)
                except (TypeError, ValueError):
                    text = str(equity).replace(",", "").strip()
                    return float(text.split()[0])

            @staticmethod
            def _sign(value: float) -> float:
                if value > 0.0:
                    return 1.0
                if value < 0.0:
                    return -1.0
                return 0.0

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

    @staticmethod
    def _make_package_strategy_classes(nt):
        class QuantBTPackageConfig(nt.StrategyConfig, frozen=True):
            instrument_ids: List[str]
            bar_types: Dict[str, str]
            package_orders: Dict[int, List[Dict]]
            close_positions_on_stop: bool = False

        class QuantBTPackageStrategy(nt.Strategy):
            def __init__(self, config: QuantBTPackageConfig):
                super().__init__(config)
                self.instrument_ids = [nt.InstrumentId.from_str(value) for value in config.instrument_ids]
                self.bar_types = [nt.BarType.from_str(value) for value in config.bar_types.values()]
                self.package_orders = config.package_orders
                self.submitted_timestamps = set()
                self.instruments = {}

            def on_start(self):
                for instrument_id in self.instrument_ids:
                    instrument = self.cache.instrument(instrument_id)
                    if instrument is None:
                        self.stop()
                        return
                    self.instruments[str(instrument_id)] = instrument
                for bar_type in self.bar_types:
                    self.subscribe_bars(bar_type)

            def on_bar(self, bar):
                ts_event = int(bar.ts_event)
                if ts_event in self.submitted_timestamps:
                    return
                payload = self.package_orders.get(ts_event)
                if not payload:
                    return
                for item in payload:
                    instrument_id = nt.InstrumentId.from_str(item["instrument_id"])
                    instrument = self.instruments.get(str(instrument_id))
                    if instrument is None:
                        continue
                    side = nt.OrderSide.BUY if item["side"] == "buy" else nt.OrderSide.SELL
                    order = self._make_order(item, instrument_id, instrument, side)
                    self.submit_order(order)
                self.submitted_timestamps.add(ts_event)

            def _make_order(self, item, instrument_id, instrument, side):
                quantity = instrument.make_qty(Decimal(str(item["qty"])))
                tif = self._time_in_force(item.get("tif", "gtc"))
                order_type = str(item.get("order_type", "market")).lower().strip()
                kwargs = {
                    "instrument_id": instrument_id,
                    "order_side": side,
                    "quantity": quantity,
                    "time_in_force": tif,
                    "reduce_only": bool(item.get("reduce_only", False)),
                    "tags": [item["tag"]] if item.get("tag") else None,
                }
                if order_type == "market":
                    return self.order_factory.market(**kwargs)
                if order_type == "limit":
                    return self.order_factory.limit(
                        price=instrument.make_price(Decimal(str(item["price"]))),
                        **kwargs,
                    )
                if order_type == "stop_market":
                    return self.order_factory.stop_market(
                        trigger_price=instrument.make_price(Decimal(str(item["trigger_price"]))),
                        **kwargs,
                    )
                if order_type == "stop_limit":
                    return self.order_factory.stop_limit(
                        price=instrument.make_price(Decimal(str(item["price"]))),
                        trigger_price=instrument.make_price(Decimal(str(item["trigger_price"]))),
                        **kwargs,
                    )
                raise NotImplementedError(f"unsupported Nautilus explicit order_type={order_type!r}")

            @staticmethod
            def _time_in_force(value):
                key = str(value).upper().strip()
                if key in {"GOOD_TIL_CANCEL", "GOOD_TILL_CANCEL"}:
                    key = "GTC"
                try:
                    return getattr(nt.TimeInForce, key)
                except AttributeError as exc:
                    raise NotImplementedError(f"unsupported Nautilus time_in_force={value!r}") from exc

            def on_stop(self):
                for instrument_id in self.instrument_ids:
                    self.cancel_all_orders(instrument_id)
                    if self.config.close_positions_on_stop:
                        self.close_all_positions(instrument_id)

        return QuantBTPackageStrategy, QuantBTPackageConfig


def build_nautilus_package_order_table(
    orders: Sequence[OrderIntent],
    instrument_ids: Optional[Dict[str, str]] = None,
) -> pd.DataFrame:
    rows = []
    for idx, order in enumerate(orders):
        timestamp = pd.Timestamp(order.timestamp)
        if timestamp.tz is None:
            timestamp = timestamp.tz_localize("UTC")
        else:
            timestamp = timestamp.tz_convert("UTC")
        instrument_id = (instrument_ids or {}).get(order.symbol, order.symbol)
        rows.append(
            {
                "package_order_index": idx,
                "timestamp": timestamp,
                "symbol": order.symbol,
                "instrument_id": instrument_id,
                "side": order.side.value if isinstance(order.side, OrderSide) else str(order.side),
                "qty": float(order.qty),
                "order_type": getattr(order.order_type, "value", str(order.order_type)),
                "price": order.price,
                "trigger_price": order.trigger_price,
                "tif": getattr(order.tif, "value", str(order.tif)),
                "reduce_only": bool(order.reduce_only),
                "order_id": order.order_id,
                "tag": order.tag,
                "arb_id": order.metadata.get("arb_id"),
                "arb_type": order.metadata.get("arb_type"),
                "package_policy": order.metadata.get("package_policy"),
                "target_units": order.metadata.get("target_units"),
                "previous_units": order.metadata.get("previous_units"),
            }
        )
    return pd.DataFrame(rows)


def _orders_payload(
    orders: Sequence[OrderIntent],
    instrument_ids: Optional[Dict[str, str]] = None,
) -> Dict[int, List[Dict]]:
    payload: Dict[int, List[Dict]] = {}
    for order in orders:
        timestamp = pd.Timestamp(order.timestamp)
        if timestamp.tz is None:
            timestamp = timestamp.tz_localize("UTC")
        else:
            timestamp = timestamp.tz_convert("UTC")
        side = order.side.value if isinstance(order.side, OrderSide) else str(order.side)
        item = {
            "symbol": order.symbol,
            "instrument_id": (instrument_ids or {}).get(order.symbol, order.symbol),
            "side": side,
            "qty": float(order.qty),
            "order_type": getattr(order.order_type, "value", str(order.order_type)),
            "price": order.price,
            "trigger_price": order.trigger_price,
            "tif": getattr(order.tif, "value", str(order.tif)),
            "reduce_only": bool(order.reduce_only),
            "order_id": order.order_id,
            "tag": order.tag,
        }
        payload.setdefault(int(timestamp.value), []).append(item)
    return payload
