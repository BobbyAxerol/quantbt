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

from .backends import (
    NativeEventBackend,
    NativeEventConfig,
    NativeOptionBackend,
    NativeOptionConfig,
    NativePortfolioBackend,
    NativePortfolioConfig,
    NativeVectorizedBackend,
    NativeVectorizedConfig,
)
from .api import execute_native_event_lifecycle
from .core.orders import OrderAction, OrderCommand, OrderIntent, order_intents_to_lifecycle_commands
from .core.instrument_registry_v2 import InstrumentRegistryV2
from .core.market_calendar_v2 import PreparedMarketHandleV2
from .core.preprocessor import validate_datetime
from .core.results import BacktestResultV2, OptionBacktestResult
from .core.schema import AccountConfig, BasketSpec, ExecutionConfig, InstrumentSpec, OrderSide, OrderType, TimeInForce
from .options.cache import OptionPreparedRunCache
from .options.hedging import OptionHedgeConfig
from .options.packages import OptionPackageIntent
from .options.schema import OptionInstrumentRegistry, OptionInstrumentSpec
from .options.strategy import OptionStrategyRun
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
        native_backend: Optional[str] = None,
        backend_policy: Optional[str] = None,
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
        order_commands: Optional[Sequence[OrderCommand]] = None,
        strategy=None,
        event_engine_version: str = "v1",
        execution_contract=None,
        reactive_execution_mode: str = "fast",
        reactive_kernel_mode: str = "replay_certified",
        audit_mode: Optional[str] = None,
        oracle_sample_rate: float = 0.0,
        oracle_sample_seed: int = 0,
        report_level: str = "audit",
        audit_sink: str = "memory",
        audit_sink_path: Optional[str] = None,
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
        instruments: Optional[Union[Dict[str, InstrumentSpec], List[InstrumentSpec]]] = None,
        qty_step: Optional[Union[float, Dict[str, float]]] = None,
        lot_size: Optional[Union[float, Dict[str, float]]] = None,
        slot_size: Optional[Union[float, Dict[str, float]]] = None,
        min_qty: Optional[Union[float, Dict[str, float]]] = None,
        min_notional: Optional[Union[float, Dict[str, float]]] = None,
        prepared_market: Optional[PreparedMarketHandleV2] = None,
        prepared_instruments: Optional[InstrumentRegistryV2] = None,
        calendar_contract: str = "legacy_v1",
        auto_run: bool = True,
    ):
        self.backend = backend.lower().strip()
        if self.backend not in self.VALID_BACKENDS:
            raise ValueError(f"backend must be one of {sorted(self.VALID_BACKENDS)}")

        self.data = data
        self.native_backend = native_backend
        self.backend_policy = backend_policy
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
        self.order_commands = tuple(order_commands or ())
        self.strategy = strategy
        self.event_engine_version = str(event_engine_version).lower().strip()
        self.execution_contract = execution_contract
        self.reactive_execution_mode = str(reactive_execution_mode).lower().strip()
        self.reactive_kernel_mode = str(reactive_kernel_mode).lower().strip()
        self.audit_mode = audit_mode
        self.oracle_sample_rate = float(oracle_sample_rate)
        self.oracle_sample_seed = int(oracle_sample_seed)
        self.report_level = str(report_level)
        self.audit_sink = str(audit_sink)
        self.audit_sink_path = audit_sink_path
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
        self.instruments = instruments
        self.qty_step = qty_step
        self.lot_size = lot_size
        self.slot_size = slot_size
        self.min_qty = min_qty
        self.min_notional = min_notional
        self.prepared_market = prepared_market
        self.prepared_instruments = prepared_instruments
        self.calendar_contract = str(calendar_contract).lower().strip()
        if self.calendar_contract not in {"legacy_v1", "exact_v2"}:
            raise ValueError("calendar_contract must be legacy_v1 or exact_v2")
        if (self.prepared_market is None) != (self.prepared_instruments is None):
            raise ValueError("prepared_market and prepared_instruments must be supplied together")
        # A V2 handle is intrinsically calendar-exact.  Keep the historical
        # default for legacy callers, but never label a prepared V2 execution
        # as legacy alignment in its audit metadata.
        if self.prepared_market is not None:
            self.calendar_contract = "exact_v2"
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
                instruments=self.instruments,
                qty_step=self.qty_step,
                lot_size=self.lot_size,
                slot_size=self.slot_size,
                min_qty=self.min_qty,
                min_notional=self.min_notional,
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
            instruments=self.instruments,
            qty_step=self.qty_step,
            lot_size=self.lot_size,
            slot_size=self.slot_size,
            min_qty=self.min_qty,
            min_notional=self.min_notional,
        )

    def _run_native_event(self) -> BacktestResultV2:
        if self.prepared_market is not None:
            if self.strategy is not None or self.basket is not None or not (self.order_commands or self.orders):
                raise NotImplementedError(
                    "PreparedMarketHandleV2 currently lowers explicit static order tapes only; "
                    "reactive/basket/signal lowering remains on its certified route"
                )
            view = self.prepared_market.execution_view()
            if tuple(self.symbols or view.symbols) != view.symbols:
                raise ValueError("prepared market symbols must match normalized V2 symbol order")
            idx = pd.to_datetime(view.timestamps_ns, utc=True)
            symbols = list(view.symbols)
            # Static V2 preparation consumes the handle's contiguous arrays.
            # Empty compatibility maps ensure this dispatcher never normalizes
            # or packs pandas inputs before the prepared lifecycle route.
            closes: SeriesMap = {}
            highs: SeriesMap = {}
            lows: SeriesMap = {}
        else:
            idx, closes, highs, lows, symbols = self._market_data()

        def make_compatibility_backend() -> NativeEventBackend:
            return NativeEventBackend(
                NativeEventConfig(
                    account=self.account,
                    execution=self.execution,
                    fee_rate=self.fee_rate,
                    use_funding=self.use_funding,
                    report_level=self.report_level,
                    audit_sink=self.audit_sink,
                    audit_sink_path=self.audit_sink_path,
                    reactive_kernel_mode=self.reactive_kernel_mode,
                    audit_mode=self.audit_mode,
                    oracle_sample_rate=self.oracle_sample_rate,
                    oracle_sample_seed=self.oracle_sample_seed,
                    native_backend=self.native_backend,
                    backend_policy=self.backend_policy,
                    execution_contract=(
                        self.execution_contract
                        if self.execution_contract is not None
                        else "event_lifecycle_v2_next_bar_close"
                    ),
                )
            )

        if self.strategy is not None:
            backend = make_compatibility_backend()
            if self.prepared_market is not None:
                opens, volumes = None, None
            else:
                opens, volumes = _market_open_volume(
                    data=self.data,
                    datetime_index=idx,
                    closes=closes,
                    symbols=symbols,
                )
            return backend.run_strategy(
                datetime_index=idx,
                strategy=self.strategy,
                closes=closes,
                highs=highs,
                lows=lows,
                opens=opens,
                volumes=volumes,
                funding_rate=self.funding_rate,
                contract_size=self.contract_size,
                leverage=self.leverage,
                fee_rate=self.fee_rate,
                symbols=symbols,
                instruments=self.instruments,
                qty_step=self.qty_step,
                lot_size=self.lot_size,
                slot_size=self.slot_size,
                min_qty=self.min_qty,
                min_notional=self.min_notional,
                execution_mode=self.reactive_execution_mode,
                reactive_kernel_mode=self.reactive_kernel_mode,
                report_level=self.report_level,
                audit_sink=self.audit_sink,
                audit_sink_path=self.audit_sink_path,
            )

        if self.basket is not None:
            backend = make_compatibility_backend()
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
                instruments=self.instruments,
                qty_step=self.qty_step,
                lot_size=self.lot_size,
                slot_size=self.slot_size,
                min_qty=self.min_qty,
                min_notional=self.min_notional,
            )

        if self.order_commands or self.event_engine_version in {
            "v2",
            "event_v2",
            "lifecycle",
            "lifecycle_v2",
            "v3",
            "event_v3",
            "lifecycle_v3",
            "event_lifecycle_v2_next_bar_close",
            "event_lifecycle_v3_next_open",
        }:
            commands = self.order_commands
            if not commands and self.orders:
                commands = order_intents_to_lifecycle_commands(self.orders)
            if not commands:
                raw_positions = self.positions if self.positions is not None else self.signals
                if raw_positions is None:
                    raise ValueError("native_event v2 requires order_commands, orders, signals, positions, or a basket")
                generated_orders = tuple(
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
                commands = order_intents_to_lifecycle_commands(generated_orders)
            if self.prepared_market is not None:
                opens, volumes = None, None
            else:
                opens, volumes = _market_open_volume(
                    data=self.data,
                    datetime_index=idx,
                    closes=closes,
                    symbols=symbols,
                )
            outcome = execute_native_event_lifecycle(
                datetime_index=idx,
                commands=commands,
                closes=closes,
                highs=highs,
                lows=lows,
                opens=opens,
                volumes=volumes,
                funding_rate=self.funding_rate,
                contract_size=self.contract_size,
                leverage=self.leverage,
                fee_rate=self.fee_rate,
                symbols=symbols,
                account=self.account,
                execution=self.execution,
                native_backend=self.native_backend,
                backend_policy=self.backend_policy,
                execution_contract=(
                    self.execution_contract
                    if self.execution_contract is not None
                    else "event_lifecycle_v2_next_bar_close"
                ),
                report_level=self.report_level,
                audit_sink=self.audit_sink,
                audit_sink_path=self.audit_sink_path,
                use_funding=self.use_funding,
                instruments=self.instruments,
                qty_step=self.qty_step,
                lot_size=self.lot_size,
                slot_size=self.slot_size,
                min_qty=self.min_qty,
                min_notional=self.min_notional,
                market_handle=self.prepared_market,
                instrument_registry=self.prepared_instruments,
                calendar_contract=self.calendar_contract,
            )
            self.execution_plan = outcome.preparation.prepared.plan
            self.prepared_run = outcome.preparation.prepared
            self.native_event_backend = outcome.engine
            return outcome.result

        orders = self.orders
        backend = make_compatibility_backend()
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
            instruments=self.instruments,
            qty_step=self.qty_step,
            lot_size=self.lot_size,
            slot_size=self.slot_size,
            min_qty=self.min_qty,
            min_notional=self.min_notional,
        )

    def _run_nautilus(self) -> BacktestResultV2:
        from .adapters.nautilus import NautilusBackendConfig, NautilusBacktestEngine

        symbol_override = self.symbols[0] if self.symbols else None
        trade_notional = self.alloc_per_trade if not isinstance(self.alloc_per_trade, dict) else next(
            iter(self.alloc_per_trade.values())
        )
        if self.orders or self.order_commands:
            idx, closes, highs, lows, symbols = self._market_data()
            package_orders = self.orders
            input_mode = "explicit_orders"
            if self.order_commands:
                package_orders = _commands_to_package_order_intents(self.order_commands)
                input_mode = "lifecycle_commands"
            data = _frames_for_nautilus(
                data=self.data,
                datetime_index=idx,
                closes=closes,
                highs=highs,
                lows=lows,
                symbols=symbols,
            )
            config = self.nautilus_config
            updates = {
                "starting_balance": self.account.initial_capital,
                "trade_notional": 0.0,
                "sizing_mode": "notional",
            }
            if symbol_override:
                updates["instrument_id"] = symbol_override
            if config is None:
                config = NautilusBackendConfig(
                    instrument_id=symbol_override or symbols[0],
                    starting_balance=self.account.initial_capital,
                    trade_notional=0.0,
                    sizing_mode="notional",
                )
            else:
                config = replace(config, **updates)
            package_params = {
                "input_mode": input_mode,
                "order_count_input": int(len(package_orders)),
            }
            if self.order_commands:
                package_params["command_count_input"] = int(len(self.order_commands))
            return NautilusBacktestEngine(config).run_order_packages(
                data=data,
                orders=package_orders,
                symbols=symbols,
                params=package_params,
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


class OptionBacktestEngine:
    """
    Native option facade returning `OptionBacktestResult`.

    Parameters
    ----------
    chain:
        Canonical long-form option chain rows.
    instruments:
        Option instrument registry, sequence, or mapping.
    packages:
        Option package intents generated by a strategy/template layer.
    config:
        Native option backend configuration.
    """

    def __init__(
        self,
        *,
        chain: Optional[pd.DataFrame] = None,
        instruments: Optional[OptionInstrumentRegistry | Sequence[OptionInstrumentSpec] | Dict[str, OptionInstrumentSpec]] = None,
        packages: Sequence[OptionPackageIntent] = (),
        strategy_run: Optional[OptionStrategyRun] = None,
        underlying: Optional[Union[pd.DataFrame, pd.Series]] = None,
        hedge_policy: Optional[OptionHedgeConfig] = None,
        net_option_delta: Optional[pd.Series] = None,
        config: Optional[NativeOptionConfig] = None,
        settlement_events: Optional[Sequence] = None,
        conversion_rates: Optional[Dict[str, float]] = None,
        prepared_cache: Optional[OptionPreparedRunCache] = None,
        auto_run: bool = True,
    ):
        self.chain = chain
        self.instruments = instruments
        self.strategy_run = strategy_run
        self.packages = tuple(packages or (strategy_run.packages if strategy_run is not None else ()))
        self.underlying = underlying
        self.hedge_policy = hedge_policy or (strategy_run.hedge_policy if strategy_run is not None else None)
        self.net_option_delta = net_option_delta
        self.config = config or NativeOptionConfig()
        self.settlement_events = tuple(settlement_events or ())
        self.conversion_rates = conversion_rates
        self.prepared_cache = prepared_cache
        self.backend = NativeOptionBackend(self.config)
        self.result: Optional[OptionBacktestResult] = None

        if auto_run:
            self.run()

    def run(self) -> OptionBacktestResult:
        if self.chain is None:
            raise ValueError("OptionBacktestEngine requires chain")
        if self.instruments is None:
            raise ValueError("OptionBacktestEngine requires instruments")
        self.result = self.backend.run(
            chain=self.chain,
            instruments=self.instruments,
            packages=self.packages,
            settlement_events=self.settlement_events,
            conversion_rates=self.conversion_rates,
            prepared_cache=self.prepared_cache,
            underlying=self.underlying,
            hedge_policy=self.hedge_policy,
            net_option_delta=self.net_option_delta,
        )
        if self.strategy_run is not None:
            self.result.metadata["strategy_run"] = self.strategy_run.metadata
            self.result.metadata["selected_contracts"] = self.strategy_run.selected_contracts
            self.result.run_manifest["strategy_run"] = self.strategy_run.metadata
            self.result.metadata["run_manifest"] = self.result.run_manifest
        return self.result


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
        backend: str = "native_portfolio",
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
        instruments: Optional[Union[Dict[str, InstrumentSpec], List[InstrumentSpec]]] = None,
        qty_step: Optional[Union[float, Dict[str, float]]] = None,
        lot_size: Optional[Union[float, Dict[str, float]]] = None,
        slot_size: Optional[Union[float, Dict[str, float]]] = None,
        min_qty: Optional[Union[float, Dict[str, float]]] = None,
        min_notional: Optional[Union[float, Dict[str, float]]] = None,
        report_level: str = "full",
        auto_run: bool = True,
        **kwargs,
    ):
        legacy_slippage = kwargs.pop("slippage", None)
        if execution is None and legacy_slippage is not None:
            execution = ExecutionConfig(slippage_bps=float(legacy_slippage) * 10_000.0)
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
        self.instruments = instruments
        self.qty_step = qty_step
        self.lot_size = lot_size
        self.slot_size = slot_size
        self.min_qty = min_qty
        self.min_notional = min_notional
        self.report_level = report_level
        self.kwargs = kwargs
        self.portfolio: Optional[MultiSymbolPortfolio] = None
        self.result: Optional[BacktestResultV2] = None

        if auto_run:
            self.run()

    def run(self) -> BacktestResultV2:
        if self.backend in {"legacy", "legacy_portfolio", "portfolio"}:
            asset_type = self.asset_type.lower()
            default_fee = 0.0004 if asset_type == "crypto" else 0.0001
            fee_oneway = self.fee_rate if self.fee_rate is not None else default_fee / 2.0
            legacy_kwargs = {
                key: value
                for key, value in self.kwargs.items()
                if key not in {"use_pyramiding", "betas", "risk_lookback"}
            }
            self.portfolio = MultiSymbolPortfolio(
                positions=self.positions,
                closes=self.closes,
                datetime_index=self.datetime_index,
                mode=self.mode,
                fee_rate=fee_oneway,
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
                **legacy_kwargs,
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
                instruments=self.instruments,
                qty_step=self.qty_step,
                lot_size=self.lot_size,
                slot_size=self.slot_size,
                min_qty=self.min_qty,
                min_notional=self.min_notional,
            )
            self.result = engine.result
            return self.result

        if self.backend == "native_portfolio":
            asset_type = self.asset_type.lower()
            default_fee = 0.0004 if asset_type == "crypto" else 0.0001
            fee_oneway = self.fee_rate if self.fee_rate is not None else default_fee / 2.0
            default_contract = 1.0 if asset_type == "crypto" else 100.0
            backend = NativePortfolioBackend(
                NativePortfolioConfig(
                    account=self.account,
                    execution=self.execution,
                    fee_rate=fee_oneway,
                    use_funding=bool(self.use_funding),
                    report_level=self.report_level,
                )
            )
            self.result = backend.run_signals(
                positions=self.positions,
                closes=self.closes,
                highs=self.highs,
                lows=self.lows,
                datetime_index=self.datetime_index,
                mode=self.mode,
                alloc_per_trade=self.alloc_per_trade,
                contract_size=self.contract_size if self.contract_size is not None else default_contract,
                hedge_type=self.hedge_type,
                funding_rate=self.funding_rate if self.funding_rate is not None else 0.0001,
                leverage=self.leverage,
                maintenance_ratio=self.maintenance_ratio,
                asset_type=self.asset_type,
                use_pyramiding=bool(self.kwargs.get("use_pyramiding", True)),
                betas=self.kwargs.get("betas"),
                risk_lookback=int(self.kwargs.get("risk_lookback", 60)),
                instruments=self.instruments,
                qty_step=self.qty_step,
                lot_size=self.lot_size,
                slot_size=self.slot_size,
                min_qty=self.min_qty,
                min_notional=self.min_notional,
                report_level=self.report_level,
            )
            return self.result

        raise ValueError("PortfolioBacktestEngine backend must be legacy_portfolio, native_vectorized, or native_portfolio")


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


def _market_open_volume(
    data: Optional[Union[pd.DataFrame, Dict[str, Union[pd.DataFrame, pd.Series]]]],
    datetime_index: pd.DatetimeIndex,
    closes: SeriesMap,
    symbols: List[str],
) -> Tuple[SeriesMap, SeriesMap]:
    opens: SeriesMap = {}
    volumes: SeriesMap = {}
    if isinstance(data, pd.DataFrame):
        if len(symbols) != 1:
            raise ValueError("single DataFrame reactive run requires one symbol")
        frame = _extract_frame_ohlcv(data, datetime_index)
        opens[symbols[0]] = frame["open"]
        volumes[symbols[0]] = frame["volume"]
        return opens, volumes
    if isinstance(data, dict):
        for symbol in symbols:
            value = data[symbol]
            if isinstance(value, pd.DataFrame):
                frame = _extract_frame_ohlcv(value, datetime_index)
                opens[symbol] = frame["open"]
                volumes[symbol] = frame["volume"]
            else:
                close = closes[symbol]
                opens[symbol] = close
                volumes[symbol] = pd.Series(0.0, index=close.index, name="volume")
        return opens, volumes
    for symbol in symbols:
        close = closes[symbol]
        opens[symbol] = close
        volumes[symbol] = pd.Series(0.0, index=close.index, name="volume")
    return opens, volumes


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


def _frames_for_nautilus(
    data: Optional[Union[pd.DataFrame, Dict[str, Union[pd.DataFrame, pd.Series]]]],
    datetime_index: pd.DatetimeIndex,
    closes: SeriesMap,
    highs: SeriesMap,
    lows: SeriesMap,
    symbols: List[str],
) -> Dict[str, pd.DataFrame]:
    if isinstance(data, pd.DataFrame):
        if len(symbols) != 1:
            raise ValueError("single DataFrame Nautilus order replay requires one symbol")
        return {symbols[0]: _extract_frame_ohlcv(data, datetime_index)}
    if isinstance(data, dict):
        frames = {}
        for symbol in symbols:
            value = data[symbol]
            if isinstance(value, pd.DataFrame):
                frames[symbol] = _extract_frame_ohlcv(value, datetime_index)
            else:
                close = pd.Series(value.to_numpy(), index=datetime_index, name="close")
                frames[symbol] = _frame_from_ohlc(close, close, close)
        return frames
    return {symbol: _frame_from_ohlc(closes[symbol], highs[symbol], lows[symbol]) for symbol in symbols}


def _extract_frame_ohlcv(data: pd.DataFrame, datetime_index: pd.DatetimeIndex) -> pd.DataFrame:
    frame = data.copy()
    frame = frame.rename(
        columns={
            "Datetime": "timestamp",
            "Date": "timestamp",
            "Timestamp": "timestamp",
            "Open": "open",
            "High": "high",
            "Low": "low",
            "Close": "close",
            "Volume": "volume",
        }
    )
    frame.index = datetime_index
    if "close" not in frame.columns:
        raise ValueError("data frame must contain close/Close")
    for col in ("open", "high", "low"):
        if col not in frame.columns:
            frame[col] = frame["close"]
    if "volume" not in frame.columns:
        frame["volume"] = 0.0
    return frame[["open", "high", "low", "close", "volume"]].copy()


def _frame_from_ohlc(close: pd.Series, high: pd.Series, low: pd.Series) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "open": close,
            "high": high,
            "low": low,
            "close": close,
            "volume": 0.0,
        },
        index=close.index,
    )


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


def _commands_to_package_order_intents(commands: Sequence[OrderCommand]) -> Tuple[OrderIntent, ...]:
    orders: List[OrderIntent] = []
    for command in commands:
        if command.action not in (OrderAction.PLACE, OrderAction.REPLACE):
            continue
        if command.symbol is None or command.side is None or command.order_type is None or command.qty is None:
            continue
        metadata = {
            **dict(command.metadata),
            "command_action": command.action.value,
            "target_order_id": command.target_order_id,
            "parent_order_id": command.parent_order_id,
            "group_id": command.group_id,
            "oco_group_id": command.oco_group_id,
            "activation_policy": command.activation_policy.value,
        }
        orders.append(
            OrderIntent(
                timestamp=command.timestamp,
                symbol=command.symbol,
                side=command.side,
                order_type=command.order_type,
                qty=float(command.qty),
                price=command.price,
                trigger_price=command.trigger_price,
                tif=command.tif,
                reduce_only=command.reduce_only,
                order_id=command.order_id,
                tag=command.tag,
                metadata=metadata,
            )
        )
    return tuple(orders)


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
