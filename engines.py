"""
Public V2 engine facades.

These classes keep the old public API untouched while giving new notebooks a
single backend selector for native vectorized, native event-driven, and optional
Nautilus validation runs.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Dict, List, Optional, Sequence, Tuple, Union

import pandas as pd

from .backends import NativeEventBackend, NativeEventConfig, NativeVectorizedBackend, NativeVectorizedConfig
from .core.orders import OrderIntent
from .core.preprocessor import validate_datetime
from .core.results import BacktestResultV2
from .core.schema import AccountConfig, BasketSpec, ExecutionConfig, OrderSide, OrderType, TimeInForce
from .portfolio import MultiSymbolPortfolio
from .sizing.modes import compute_target_units


SeriesMap = Dict[str, pd.Series]


class BacktestEngineV2:
    """
    Backend-selecting facade for upgraded quantbt engines.

    Parameters can be supplied in a dataframe-oriented style (`data` and
    `signals`) or an explicit dictionary style (`closes`, `highs`, `lows`,
    `positions`, `target_units`, `orders`).
    """

    VALID_BACKENDS = {"native_vectorized", "native_event", "nautilus"}

    def __init__(
        self,
        data: Optional[Union[pd.DataFrame, Dict[str, Union[pd.DataFrame, pd.Series]]]] = None,
        signals: Optional[Union[pd.Series, SeriesMap]] = None,
        backend: str = "native_vectorized",
        account: Optional[AccountConfig] = None,
        execution: Optional[ExecutionConfig] = None,
        fee_rate: float = 0.0,
        use_funding: bool = True,
        alloc_per_trade: Union[float, Dict[str, float]] = 100_000.0,
        hedge_type: str = "signal_notional",
        use_pyramiding: bool = True,
        positions: Optional[Union[pd.Series, SeriesMap]] = None,
        target_units: Optional[Union[pd.Series, SeriesMap]] = None,
        orders: Optional[Sequence[OrderIntent]] = None,
        datetime_index: Optional[Union[pd.DatetimeIndex, pd.Series]] = None,
        closes: Optional[SeriesMap] = None,
        highs: Optional[SeriesMap] = None,
        lows: Optional[SeriesMap] = None,
        funding_rate: Union[float, pd.Series, Dict] = 0.0,
        contract_size: Union[float, Dict[str, float]] = 1.0,
        leverage: Optional[Union[float, Dict[str, float]]] = None,
        symbols: Optional[List[str]] = None,
        basket: Optional[BasketSpec] = None,
        signal: Optional[pd.Series] = None,
        hedge_ratios: Optional[SeriesMap] = None,
        nautilus_config=None,
        auto_run: bool = True,
    ):
        self.backend = backend.lower().strip()
        if self.backend not in self.VALID_BACKENDS:
            raise ValueError(f"backend must be one of {sorted(self.VALID_BACKENDS)}")

        self.data = data
        self.signals = signals
        self.account = account or AccountConfig(initial_capital=100_000.0)
        self.execution = execution or ExecutionConfig()
        self.fee_rate = float(fee_rate)
        self.use_funding = bool(use_funding)
        self.alloc_per_trade = alloc_per_trade
        self.hedge_type = hedge_type
        self.use_pyramiding = use_pyramiding
        self.positions = positions
        self.target_units = target_units
        self.orders = tuple(orders or ())
        self.datetime_index = datetime_index
        self.closes = closes
        self.highs = highs
        self.lows = lows
        self.funding_rate = funding_rate
        self.contract_size = contract_size
        self.leverage = leverage
        self.symbols = symbols
        self.basket = basket
        self.signal = signal
        self.hedge_ratios = hedge_ratios
        self.nautilus_config = nautilus_config
        self.result: Optional[BacktestResultV2] = None

        if auto_run:
            self.run()

    def run(self) -> BacktestResultV2:
        if self.backend == "native_vectorized":
            self.result = self._run_native_vectorized()
        elif self.backend == "native_event":
            self.result = self._run_native_event()
        else:
            self.result = self._run_nautilus()
        return self.result

    def _run_native_vectorized(self) -> BacktestResultV2:
        idx, closes, highs, lows, symbols = self._market_data()
        backend = NativeVectorizedBackend(
            NativeVectorizedConfig(
                account=self.account,
                execution=self.execution,
                fee_rate=self.fee_rate,
                use_funding=self.use_funding,
            )
        )

        if self.target_units is not None:
            target_units = _as_series_map(self.target_units, symbols)
            return backend.run_target_units(
                datetime_index=idx,
                target_units=target_units,
                closes=closes,
                highs=highs,
                lows=lows,
                funding_rate=self.funding_rate,
                contract_size=self.contract_size,
                leverage=self.leverage,
                symbols=symbols,
            )

        raw_positions = self.positions if self.positions is not None else self.signals
        if raw_positions is None:
            raise ValueError("native_vectorized requires signals, positions, or target_units")

        return backend.run_signals(
            datetime_index=idx,
            positions=_as_series_map(raw_positions, symbols),
            closes=closes,
            highs=highs,
            lows=lows,
            funding_rate=self.funding_rate,
            contract_size=self.contract_size,
            leverage=self.leverage,
            alloc_per_trade=self.alloc_per_trade,
            hedge_type=self.hedge_type,
            use_pyramiding=self.use_pyramiding,
            symbols=symbols,
        )

    def _run_native_event(self) -> BacktestResultV2:
        idx, closes, highs, lows, symbols = self._market_data()
        backend = NativeEventBackend(
            NativeEventConfig(
                account=self.account,
                execution=self.execution,
                fee_rate=self.fee_rate,
                use_funding=self.use_funding,
            )
        )

        if self.basket is not None:
            basket_signal = self.signal if self.signal is not None else _first_signal(self.signals)
            if basket_signal is None:
                raise ValueError("basket event backtest requires signal or signals")
            return backend.run_basket(
                datetime_index=idx,
                basket=self.basket,
                signal=basket_signal,
                closes=closes,
                highs=highs,
                lows=lows,
                hedge_ratios=self.hedge_ratios,
                funding_rate=self.funding_rate,
                contract_size=self.contract_size,
                leverage=self.leverage,
                symbols=symbols,
            )

        orders = self.orders
        if not orders:
            raw_positions = self.positions if self.positions is not None else self.signals
            if raw_positions is None:
                raise ValueError("native_event requires explicit orders, signals, positions, or a basket")
            orders = tuple(
                _build_market_rebalance_orders(
                    datetime_index=idx,
                    positions=_as_series_map(raw_positions, symbols),
                    closes=closes,
                    alloc_per_trade=self.alloc_per_trade,
                    hedge_type=self.hedge_type,
                    use_pyramiding=self.use_pyramiding,
                    symbols=symbols,
                )
            )
        return backend.run_orders(
            datetime_index=idx,
            orders=orders,
            closes=closes,
            highs=highs,
            lows=lows,
            funding_rate=self.funding_rate,
            contract_size=self.contract_size,
            leverage=self.leverage,
            symbols=symbols,
        )

    def _run_nautilus(self) -> BacktestResultV2:
        from .adapters.nautilus import NautilusBackendConfig, NautilusBacktestEngine

        symbol_override = self.symbols[0] if self.symbols else None
        trade_notional = self.alloc_per_trade if not isinstance(self.alloc_per_trade, dict) else next(
            iter(self.alloc_per_trade.values())
        )
        data = _single_frame(self.data)
        if data is None:
            idx, closes, highs, lows, symbols = self._market_data()
            symbol = symbols[0]
            data = pd.DataFrame(
                {
                    "open": closes[symbol],
                    "high": highs[symbol],
                    "low": lows[symbol],
                    "close": closes[symbol],
                    "volume": 0.0,
                },
                index=idx,
            )

        signal = _first_signal(self.positions if self.positions is not None else self.signals)
        if signal is None:
            raise ValueError("nautilus backend requires a single signal series")

        config = self.nautilus_config
        if config is None:
            config = NautilusBackendConfig(
                instrument_id=symbol_override or "BTCUSDT-PERP.BINANCE",
                starting_balance=self.account.initial_capital,
                trade_notional=float(trade_notional),
                sizing_mode=self.hedge_type,
                use_pyramiding=self.use_pyramiding,
            )
        else:
            updates = {
                "starting_balance": self.account.initial_capital,
                "trade_notional": float(trade_notional),
                "sizing_mode": self.hedge_type,
                "use_pyramiding": self.use_pyramiding,
            }
            if symbol_override and config.instrument_id == "BTCUSDT-PERP.BINANCE":
                updates["instrument_id"] = symbol_override
            config = replace(config, **updates)
        return NautilusBacktestEngine(config).run_signal_series(data=data, signal=signal)

    def _market_data(self) -> Tuple[pd.DatetimeIndex, SeriesMap, SeriesMap, SeriesMap, List[str]]:
        return _market_data(
            data=self.data,
            datetime_index=self.datetime_index,
            closes=self.closes,
            highs=self.highs,
            lows=self.lows,
            symbols=self.symbols,
        )


class EventDrivenBacktestEngine(BacktestEngineV2):
    """Convenience facade pinned to the native event-driven backend."""

    def __init__(self, *args, **kwargs):
        kwargs["backend"] = "native_event"
        super().__init__(*args, **kwargs)


class PortfolioBacktestEngine:
    """
    V2-compatible multi-symbol portfolio facade.

    The default backend intentionally wraps the existing `MultiSymbolPortfolio`
    so old portfolio mode semantics stay unchanged while returning
    `BacktestResultV2` to new metrics and migration code.
    """

    def __init__(
        self,
        positions: Dict[str, pd.Series],
        closes: Dict[str, pd.Series],
        datetime_index: Union[pd.DatetimeIndex, pd.Series],
        mode: str = "longshort",
        backend: str = "legacy_portfolio",
        account: Optional[AccountConfig] = None,
        execution: Optional[ExecutionConfig] = None,
        fee_rate: Optional[float] = None,
        alloc_per_trade: Union[float, Dict[str, float]] = 100_000.0,
        contract_size: Union[float, Dict[str, float], None] = None,
        hedge_type: str = "notional",
        asset_type: str = "crypto",
        use_funding: Optional[bool] = None,
        funding_rate: Union[float, Dict[str, float], None] = None,
        leverage: Optional[Union[float, Dict[str, float]]] = None,
        maintenance_ratio: Optional[float] = None,
        highs: Optional[Dict[str, pd.Series]] = None,
        lows: Optional[Dict[str, pd.Series]] = None,
        auto_run: bool = True,
        **kwargs,
    ):
        self.positions = positions
        self.closes = closes
        self.datetime_index = datetime_index
        self.mode = mode
        self.backend = backend.lower().strip()
        self.account = account or AccountConfig(initial_capital=100_000.0)
        self.execution = execution or ExecutionConfig()
        self.fee_rate = fee_rate
        self.alloc_per_trade = alloc_per_trade
        self.contract_size = contract_size
        self.hedge_type = hedge_type
        self.asset_type = asset_type
        self.use_funding = use_funding if use_funding is not None else asset_type.lower() == "crypto"
        self.funding_rate = funding_rate
        self.leverage = leverage if leverage is not None else self.account.leverage
        self.maintenance_ratio = (
            maintenance_ratio if maintenance_ratio is not None else self.account.maintenance_ratio
        )
        self.highs = highs
        self.lows = lows
        self.kwargs = kwargs
        self.portfolio: Optional[MultiSymbolPortfolio] = None
        self.result: Optional[BacktestResultV2] = None

        if auto_run:
            self.run()

    def run(self) -> BacktestResultV2:
        if self.backend in {"legacy", "legacy_portfolio", "portfolio"}:
            self.portfolio = MultiSymbolPortfolio(
                positions=self.positions,
                closes=self.closes,
                datetime_index=self.datetime_index,
                mode=self.mode,
                fee_rate=self.fee_rate,
                alloc_per_trade=self.alloc_per_trade,
                contract_size=self.contract_size,
                hedge_type=self.hedge_type,
                initial_capital=self.account.initial_capital,
                asset_type=self.asset_type,
                use_funding=self.use_funding,
                funding_rate=self.funding_rate,
                leverage=self.leverage,
                maintenance_ratio=self.maintenance_ratio,
                highs=self.highs,
                lows=self.lows,
                **self.kwargs,
            )
            self.result = BacktestResultV2.from_legacy(self.portfolio.result)
            self.result.metadata["backend"] = "legacy_portfolio"
            return self.result

        if self.backend == "native_vectorized":
            engine = BacktestEngineV2(
                positions=self.positions,
                closes=self.closes,
                highs=self.highs,
                lows=self.lows,
                datetime_index=self.datetime_index,
                backend="native_vectorized",
                account=self.account,
                execution=self.execution,
                fee_rate=self.fee_rate or 0.0,
                use_funding=bool(self.use_funding),
                alloc_per_trade=self.alloc_per_trade,
                hedge_type=self.hedge_type,
                contract_size=self.contract_size or 1.0,
                leverage=self.leverage,
            )
            self.result = engine.result
            return self.result

        raise ValueError("PortfolioBacktestEngine backend must be legacy_portfolio or native_vectorized")


def _market_data(
    data: Optional[Union[pd.DataFrame, Dict[str, Union[pd.DataFrame, pd.Series]]]],
    datetime_index: Optional[Union[pd.DatetimeIndex, pd.Series]],
    closes: Optional[SeriesMap],
    highs: Optional[SeriesMap],
    lows: Optional[SeriesMap],
    symbols: Optional[List[str]],
) -> Tuple[pd.DatetimeIndex, SeriesMap, SeriesMap, SeriesMap, List[str]]:
    if closes is not None:
        symbol_list = symbols or list(closes.keys())
        idx = validate_datetime(datetime_index if datetime_index is not None else closes[symbol_list[0]].index)
        close_map = {s: closes[s] for s in symbol_list}
        high_map = {s: highs[s] for s in symbol_list} if highs is not None else close_map
        low_map = {s: lows[s] for s in symbol_list} if lows is not None else close_map
        return idx, close_map, high_map, low_map, symbol_list

    if data is None:
        raise ValueError("market data is required")

    if isinstance(data, pd.DataFrame):
        symbol = symbols[0] if symbols else "asset"
        idx, close, high, low = _extract_frame_ohlc(data, datetime_index)
        return idx, {symbol: close}, {symbol: high}, {symbol: low}, [symbol]

    symbol_list = symbols or list(data.keys())
    close_map: SeriesMap = {}
    high_map: SeriesMap = {}
    low_map: SeriesMap = {}
    idx = None
    for symbol in symbol_list:
        value = data[symbol]
        if isinstance(value, pd.Series):
            close = value
            high = value
            low = value
            local_idx = validate_datetime(datetime_index if datetime_index is not None else value.index)
        else:
            local_idx, close, high, low = _extract_frame_ohlc(value, datetime_index)
        idx = local_idx if idx is None else idx
        close_map[symbol] = close
        high_map[symbol] = high
        low_map[symbol] = low
    return idx, close_map, high_map, low_map, symbol_list


def _extract_frame_ohlc(
    data: pd.DataFrame,
    datetime_index: Optional[Union[pd.DatetimeIndex, pd.Series]],
) -> Tuple[pd.DatetimeIndex, pd.Series, pd.Series, pd.Series]:
    frame = data.copy()
    rename = {
        "Datetime": "timestamp",
        "Date": "timestamp",
        "Timestamp": "timestamp",
        "Open": "open",
        "High": "high",
        "Low": "low",
        "Close": "close",
        "Volume": "volume",
    }
    frame = frame.rename(columns=rename)
    if datetime_index is not None:
        frame.index = validate_datetime(datetime_index)
    elif "timestamp" in frame.columns:
        frame["timestamp"] = pd.to_datetime(frame["timestamp"], errors="coerce", utc=True)
        frame = frame.dropna(subset=["timestamp"]).set_index("timestamp")
    else:
        frame.index = validate_datetime(frame.index)
    frame = frame[~frame.index.duplicated(keep="first")].sort_index()
    idx = validate_datetime(frame.index)
    if "close" not in frame.columns:
        raise ValueError("data frame must contain close/Close")
    close = pd.Series(frame["close"].to_numpy(), index=idx, name="close")
    high = pd.Series(frame["high"].to_numpy(), index=idx, name="high") if "high" in frame.columns else close
    low = pd.Series(frame["low"].to_numpy(), index=idx, name="low") if "low" in frame.columns else close
    return idx, close, high, low


def _as_series_map(value: Union[pd.Series, SeriesMap], symbols: List[str]) -> SeriesMap:
    if isinstance(value, pd.Series):
        if len(symbols) != 1:
            raise ValueError("single series input requires exactly one symbol")
        return {symbols[0]: value}
    return {s: value[s] for s in symbols}


def _build_market_rebalance_orders(
    datetime_index: pd.DatetimeIndex,
    positions: SeriesMap,
    closes: SeriesMap,
    alloc_per_trade: Union[float, Dict[str, float]],
    hedge_type: str,
    use_pyramiding: bool,
    symbols: List[str],
) -> List[OrderIntent]:
    ht = hedge_type.lower().strip()
    if ht in ("%_equity", "pct_equity", "dca_ladder", "dca"):
        raise NotImplementedError(
            "native_event signal adapter supports pre-scalable target-unit modes "
            "('signal_notional', 'notional', 'unit'). Use explicit orders for "
            f"hedge_type={hedge_type!r}."
        )

    alloc = _per_symbol_mapping(alloc_per_trade, symbols, default=100_000.0)
    orders: List[OrderIntent] = []
    for symbol in symbols:
        signal = positions[symbol].copy()
        close = closes[symbol].copy()
        if isinstance(signal.index, pd.DatetimeIndex):
            signal.index = signal.index.tz_localize("UTC") if signal.index.tz is None else signal.index.tz_convert("UTC")
        if isinstance(close.index, pd.DatetimeIndex):
            close.index = close.index.tz_localize("UTC") if close.index.tz is None else close.index.tz_convert("UTC")
        signal = signal[~signal.index.duplicated(keep="first")].reindex(datetime_index, method="ffill").fillna(0.0)
        close = close[~close.index.duplicated(keep="first")].reindex(datetime_index, method="ffill")
        target_units = compute_target_units(
            hedge_type=hedge_type,
            signal=signal,
            close=close,
            alloc=alloc[symbol],
            use_pyramiding=use_pyramiding,
        ).fillna(0.0)
        prev = 0.0
        for ts, target in target_units.items():
            target = float(target)
            delta = target - prev
            if abs(delta) > 1e-12:
                orders.append(
                    OrderIntent(
                        timestamp=ts,
                        symbol=symbol,
                        side=OrderSide.BUY if delta > 0.0 else OrderSide.SELL,
                        order_type=OrderType.MARKET,
                        qty=abs(delta),
                        tif=TimeInForce.IOC,
                        tag=f"signal_rebalance:{hedge_type}",
                    )
                )
            prev = target
    return sorted(orders, key=lambda order: pd.Timestamp(order.timestamp).value)


def _per_symbol_mapping(value, symbols: List[str], default: float) -> Dict[str, float]:
    if isinstance(value, dict):
        return {s: float(value.get(s, default)) for s in symbols}
    return {s: float(value) for s in symbols}


def _first_signal(value: Optional[Union[pd.Series, SeriesMap]]) -> Optional[pd.Series]:
    if value is None:
        return None
    if isinstance(value, pd.Series):
        return value
    return next(iter(value.values()))


def _single_frame(data) -> Optional[pd.DataFrame]:
    if isinstance(data, pd.DataFrame):
        return data
    if isinstance(data, dict) and data:
        first = next(iter(data.values()))
        return first if isinstance(first, pd.DataFrame) else None
    return None
