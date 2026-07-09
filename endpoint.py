"""
Unified public endpoint for notebooks and services.

`QuantBTEndpoint` is the stable integration surface above legacy and V2
backtest engines. It stores *how* to run a backtest at construction time, while
`backtest()` / `simulate()` receive the actual data, signals, orders, or basket
objects.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Dict, Optional, Sequence, Union

import pandas as pd

from .backtester import BacktestEngine
from .backends import NativeEventBackend, NativeEventConfig, NativeVectorizedBackend, NativeVectorizedConfig
from .core.arbitrage import (
    BasisArbitrageSpec,
    CalendarSpreadSpec,
    CrossExchangeArbSpec,
    FundingArbitrageSpec,
    IndexBasketArbSpec,
    OptionsVolArbSpec,
    SpotPerpCashCarrySpec,
    StatArbPairSpec,
    TriangularArbSpec,
    build_arbitrage_order_plan,
)
from .core.basket import build_frozen_basket_orders
from .core.orders import OrderIntent
from .core.results import BacktestResultV2
from .core.schema import AccountConfig, BasketLegSpec, BasketSpec, ExecutionConfig, OrderType, TimeInForce
from .core.types import BacktestResult
from .engines import BacktestEngineV2, PortfolioBacktestEngine
from .metrics import full_report as _full_report
from .viz import quick_plot as _quick_plot
from .viz import tearsheet as _tearsheet
from .walkforward import WalkForwardConfig, WalkForwardEngine


SeriesMap = Dict[str, pd.Series]
FrameMap = Dict[str, pd.DataFrame]


@dataclass(frozen=True)
class EndpointConfig:
    """
    Configuration for `QuantBTEndpoint`.

    Parameters
    ----------
    mode:
        Strategy integration mode. Supported values are `single_signal`,
        `pct_equity`, `signal_notional`, `dca_ladder`, `orders`, `basket`,
        `portfolio`, `arbitrage`, `walk_forward`, and `nautilus_validation`.
    backend:
        Engine selector. Use `auto` for domain-safe defaults, or explicitly set
        `legacy`, `native_vectorized`, `native_event`, or `nautilus`.
    sizing:
        Position sizing contract for signal modes. Examples: `%_equity`,
        `signal_notional`, `notional`, `unit`, `dca_ladder`.
    account:
        Account/margin config used by V2 engines. Legacy runs also read
        `initial_capital`, `leverage`, and `maintenance_ratio` from this object.
    execution:
        Execution/slippage config used by V2 engines. Legacy runs use the
        endpoint `slippage` fraction.
    fee:
        Legacy-style round-trip fee. `BacktestEngine` halves this internally.
    fee_rate:
        V2 one-way fee. If omitted, defaults to `fee / 2`.
    alloc_per_trade:
        Notional allocation for notional sizing modes, or equity fraction for
        `%_equity`.
    use_pyramiding:
        If false, raw signals are snapped to {-1, 0, 1}.
    use_funding:
        Whether funding should be applied where the selected engine supports it.
    funding_rate:
        Scalar, series, or per-symbol mapping of funding rates.
    contract_size:
        Contract multiplier, scalar or per-symbol mapping.
    slippage:
        Legacy execution slippage fraction. Example: `0.0001` is 1 bp.
    portfolio_mode:
        Multi-symbol allocation mode for portfolio endpoint.
    asset_type:
        Asset type used by portfolio endpoint defaults.
    basket:
        Optional basket spec stored at construction time for basket simulations.
    arbitrage_spec:
        Optional arbitrage spec stored at construction time for the future
        ArbitrageBacktestEngine.
    symbols:
        Optional symbol list. Single-symbol endpoints use the first symbol.
    dca_kwargs:
        Extra DCA ladder parameters forwarded to legacy `BacktestEngine`.
    nautilus_config:
        Optional `NautilusBackendConfig` instance for Nautilus validation runs.
    strategy_class:
        Optional strategy callable/class for `walk_forward` mode. The strategy
        must return a Series, DataFrame, or `{symbol: Series}` OOS output.
    walkforward_config:
        Optional `WalkForwardConfig` for split/stitch behavior.
    metadata:
        Free-form service metadata carried by the endpoint.
    """

    mode: str = "single_signal"
    backend: str = "auto"
    sizing: str = "signal_notional"
    account: AccountConfig = field(default_factory=lambda: AccountConfig(initial_capital=100_000.0))
    execution: ExecutionConfig = field(default_factory=ExecutionConfig)
    fee: float = 0.0004
    fee_rate: Optional[float] = None
    alloc_per_trade: Union[float, Dict[str, float]] = 100_000.0
    use_pyramiding: bool = True
    use_funding: bool = True
    funding_rate: Union[float, pd.Series, Dict] = 0.0
    contract_size: Union[float, Dict[str, float]] = 1.0
    slippage: float = 0.0001
    portfolio_mode: str = "longshort"
    asset_type: str = "crypto"
    basket: Optional[BasketSpec] = None
    arbitrage_spec: object = None
    symbols: Optional[Sequence[str]] = None
    dca_kwargs: Dict = field(default_factory=dict)
    nautilus_config: object = None
    strategy_class: object = None
    walkforward_config: Optional[WalkForwardConfig] = None
    walkforward_target_mode: str = "signal_notional"
    metadata: Dict = field(default_factory=dict)

    @property
    def v2_fee_rate(self) -> float:
        return self.fee / 2.0 if self.fee_rate is None else float(self.fee_rate)


class QuantBTEndpoint:
    """
    Stable notebook/service facade for all QuantBT backtest modes.

    Create the endpoint with a factory constructor such as
    `QuantBTEndpoint.pct_equity(...)`, then pass market data and signals to
    `backtest()`. The instance stores the latest `result` and exposes report and
    visualization helpers.
    """

    def __init__(self, config: Optional[EndpointConfig] = None, **kwargs):
        """
        Build an endpoint from an `EndpointConfig` or keyword arguments.

        Examples
        --------
        >>> endpoint = QuantBTEndpoint(mode="single_signal", sizing="signal_notional")
        >>> result = endpoint.backtest(data=df, signal_col="position")
        """
        self.config = config or _config_from_kwargs(**kwargs)
        self.result: Optional[Union[BacktestResult, BacktestResultV2]] = None
        self.engine = None

    @classmethod
    def pct_equity(cls, **kwargs) -> "QuantBTEndpoint":
        """
        Create a legacy `%_equity` endpoint.

        Use this for strategies whose signal is a direction/weight and whose
        order notional should be recomputed from live equity on signal changes.
        `alloc_per_trade` is interpreted as an equity fraction when <= 1.0
        (`0.5` means 50% of current equity), or as a percent when > 1.0.

        Data requirement for `backtest()`:
        a single OHLCV DataFrame with a DatetimeIndex and `close`; `high` and
        `low` are strongly recommended for liquidation checks.
        """
        return cls(_config_from_kwargs(mode="pct_equity", sizing="%_equity", backend="legacy", **kwargs))

    @classmethod
    def signal_notional(cls, backend: str = "native_vectorized", **kwargs) -> "QuantBTEndpoint":
        """
        Create a signal-notional endpoint.

        Signal changes anchor target units at the current price. Between signal
        changes, units are frozen, avoiding price-drift micro-rebalancing. This
        is the recommended default for systematic single-symbol alpha research.

        `backend` can be `native_vectorized` for speed or `native_event` when
        you want generated market rebalance orders and fill records.
        """
        return cls(_config_from_kwargs(mode="signal_notional", sizing="signal_notional", backend=backend, **kwargs))

    @classmethod
    def dca_ladder(cls, **kwargs) -> "QuantBTEndpoint":
        """
        Create a structural DCA/grid ladder endpoint.

        `signal` is a structural level series, not a target weight:
        0 is flat, +1 is base long, +2 allows the first safety order, and so on.
        Negative levels model short ladders. `high` and `low` are required
        because safety orders are simulated as limit fills at grid trigger
        prices.
        """
        return cls(_config_from_kwargs(mode="dca_ladder", sizing="dca_ladder", backend="legacy", **kwargs))

    @classmethod
    def orders(cls, **kwargs) -> "QuantBTEndpoint":
        """
        Create an explicit order simulation endpoint.

        Use `simulate(data=df, orders=[OrderIntent(...), ...])`. Orders are run
        through the native event backend with market/limit fill lifecycle, TIF
        handling, fees, margin checks, and fills in `result.fills`.
        """
        return cls(_config_from_kwargs(mode="orders", backend="native_event", **kwargs))

    @classmethod
    def basket(cls, basket: Optional[BasketSpec] = None, **kwargs) -> "QuantBTEndpoint":
        """
        Create a basket/pair endpoint.

        Use for pair trades and frozen hedge-ratio baskets. Provide a
        `BasketSpec` either here or to `simulate(..., basket=...)`, then pass a
        scalar entry/exit signal and per-symbol price data.
        """
        return cls(_config_from_kwargs(mode="basket", backend="native_event", basket=basket, **kwargs))

    @classmethod
    def arbitrage(cls, arb_type: str, spec, backend: str = "native_event", **kwargs) -> "QuantBTEndpoint":
        """
        Create an arbitrage endpoint.

        Supported today:

        - `BasisArbitrageSpec`: native event, native vectorized, Nautilus
          package-order validation.
        - `StatArbPairSpec`: native event, native vectorized, Nautilus
          package-order validation.
        - `CalendarSpreadSpec`, `FundingArbitrageSpec`,
          `SpotPerpCashCarrySpec`, and `IndexBasketArbSpec`: native event and
          native vectorized package-style execution.

        `CrossExchangeArbSpec`, `TriangularArbSpec`, and `OptionsVolArbSpec`
        are schema-validated but intentionally not executable through the
        generic package route because they require specialized account,
        sequence, latency, or Greek-aware engines.
        """
        metadata = dict(kwargs.pop("metadata", {}))
        metadata["arb_type"] = arb_type
        return cls(
            _config_from_kwargs(
                mode="arbitrage",
                backend=backend,
                arbitrage_spec=spec,
                metadata=metadata,
                **kwargs,
            )
        )

    @staticmethod
    def arbitrage_support_matrix() -> Dict[str, Dict[str, str]]:
        """
        Return the public arbitrage endpoint support matrix.

        Services can call this helper to decide which spec/backend pair is safe
        before constructing a run. A status of `supported` means the endpoint
        can execute the spec. A status of `schema_only` means the dataclass and
        validation exist, but execution should wait for a specialized engine.
        """
        return {
            "BasisArbitrageSpec": {
                "status": "supported",
                "backends": "native_event,native_vectorized,nautilus",
                "route": "run_basis_arbitrage",
                "sizing": "target_notional_to_base_qty or target_base_qty; linear contracts only",
            },
            "StatArbPairSpec": {
                "status": "supported",
                "backends": "native_event,native_vectorized,nautilus",
                "route": "run_stat_arb_pair_arbitrage",
                "sizing": "target_gross_notional; optional dynamic hedge_ratios",
            },
            "CalendarSpreadSpec": {
                "status": "supported",
                "backends": "native_event,native_vectorized",
                "route": "run_package_arbitrage",
                "sizing": "target_notional_to_base_qty or target_base_qty",
            },
            "FundingArbitrageSpec": {
                "status": "supported",
                "backends": "native_event,native_vectorized",
                "route": "run_package_arbitrage",
                "sizing": "target_notional_to_base_qty or target_base_qty",
            },
            "SpotPerpCashCarrySpec": {
                "status": "supported",
                "backends": "native_event,native_vectorized",
                "route": "run_package_arbitrage",
                "sizing": "target_notional_to_base_qty or target_base_qty",
            },
            "IndexBasketArbSpec": {
                "status": "supported",
                "backends": "native_event,native_vectorized",
                "route": "run_package_arbitrage",
                "sizing": "target_gross_notional",
            },
            "CrossExchangeArbSpec": {
                "status": "schema_only",
                "backends": "none",
                "route": "needs venue/account split engine",
                "sizing": "not executable yet",
            },
            "TriangularArbSpec": {
                "status": "schema_only",
                "backends": "none",
                "route": "needs sequenced path execution engine",
                "sizing": "not executable yet",
            },
            "OptionsVolArbSpec": {
                "status": "schema_only",
                "backends": "none",
                "route": "needs option/greeks engine",
                "sizing": "not executable yet",
            },
        }

    @classmethod
    def portfolio(cls, portfolio_mode: str = "longshort", **kwargs) -> "QuantBTEndpoint":
        """
        Create a multi-symbol portfolio endpoint.

        Use `backtest(positions=positions_df, data=data_dict)` where
        `positions_df.columns` are symbols and `data_dict[symbol]` is an OHLCV
        DataFrame. The endpoint wraps `PortfolioBacktestEngine`.
        """
        return cls(_config_from_kwargs(mode="portfolio", backend="legacy_portfolio", portfolio_mode=portfolio_mode, **kwargs))

    @classmethod
    def nautilus_validation(cls, **kwargs) -> "QuantBTEndpoint":
        """
        Create a Nautilus validation endpoint.

        This is for smaller high-fidelity validation runs. It currently supports
        single-symbol signal series using the optional NautilusTrader adapter.
        Nautilus must be installed in the active environment.

        `use_pyramiding` is forwarded to the Nautilus strategy adapter. When it
        is false, fractional signals such as `1.4` are snapped to `1.0`; when it
        is true, the raw signal scale is preserved.
        """
        sizing = kwargs.pop("sizing", kwargs.pop("hedge_type", "signal_notional"))
        return cls(_config_from_kwargs(mode="nautilus_validation", backend="nautilus", sizing=sizing, **kwargs))

    @classmethod
    def walk_forward(
        cls,
        strategy_class,
        split_mode: Union[str, int, pd.Timestamp] = "walk_forward_2022",
        split_frequency: str = "quarterly",
        target_mode: str = "signal_notional",
        window_mode: str = "expanding",
        train_window: Optional[str] = None,
        optimization_mode: str = "none",
        optimization_config: Optional[Dict] = None,
        optuna_trials: int = 0,
        optuna_early_stopping: Optional[int] = None,
        random_seed: int = 42,
        **kwargs,
    ) -> "QuantBTEndpoint":
        """
        Create a walk-forward endpoint.

        The strategy callable/class is invoked once per fold and must return OOS
        signal/position output indexed by timestamp. The stitched OOS output is
        then routed into an existing QuantBT backtest path, so boundary trades
        are charged by the normal engine instead of averaging fold equities.
        Supported optimization modes are `mode_1_decay`, `mode_2_sbb`, and
        `mode_3_flat_minima`. Fixed-parameter runs can leave
        `optimization_mode="none"` and pass `params=...` to `backtest()`.
        """
        optimization_config = dict(optimization_config or {})
        wf_config = kwargs.pop("walkforward_config", None)
        if wf_config is None:
            wf_config = WalkForwardConfig(
                split_mode=split_mode,
                split_frequency=split_frequency,
                window_mode=window_mode,
                train_window=train_window,
                target_mode=target_mode,
                optimization_mode=optimization_mode,
                optuna_trials=optuna_trials,
                optuna_early_stopping=optuna_early_stopping,
                random_seed=random_seed,
                decay_lambda=float(optimization_config.get("decay_lambda", 0.5)),
                decay_gamma=float(optimization_config.get("decay_gamma", 0.5)),
                top_is_fraction=float(optimization_config.get("top_is_fraction", 0.10)),
                top_is_k=optimization_config.get("top_is_k"),
                candidate_selection_metric=str(optimization_config.get("candidate_selection_metric", "robust_decay")),
                candidate_decay_lambda=optimization_config.get("candidate_decay_lambda"),
                candidate_decay_gamma=optimization_config.get("candidate_decay_gamma"),
                sbb_samples=int(optimization_config.get("sbb_samples", 256)),
                sbb_block_length=int(optimization_config.get("sbb_block_length", 20)),
                sbb_decay_lambda=float(optimization_config.get("sbb_decay_lambda", 0.5)),
                sbb_std_penalty=float(optimization_config.get("sbb_std_penalty", 0.1)),
                flat_top_fraction=float(optimization_config.get("flat_top_fraction", 0.1)),
                flat_eps=float(optimization_config.get("flat_eps", 0.15)),
                flat_min_samples=int(optimization_config.get("flat_min_samples", 3)),
                flat_selector=str(optimization_config.get("flat_selector", "medoid")),
                scoring_trading_days=int(optimization_config.get("scoring_trading_days", 365)),
                min_trades_per_year=optimization_config.get("min_trades_per_year"),
                trade_penalty_factor=optimization_config.get("trade_penalty_factor"),
                use_numba=bool(optimization_config.get("use_numba", True)),
            )
        default_sizing = "signal_notional" if target_mode in {"portfolio", "basket", "arbitrage"} else target_mode
        sizing = kwargs.pop("sizing", kwargs.pop("hedge_type", default_sizing))
        backend = kwargs.pop("backend", "auto")
        return cls(
            _config_from_kwargs(
                mode="walk_forward",
                backend=backend,
                sizing=sizing,
                strategy_class=strategy_class,
                walkforward_config=wf_config,
                walkforward_target_mode=target_mode,
                **kwargs,
            )
        )

    def backtest(
        self,
        data=None,
        signal: Optional[pd.Series] = None,
        signal_col: Optional[str] = None,
        positions: Optional[Union[pd.DataFrame, SeriesMap]] = None,
        orders: Optional[Sequence[OrderIntent]] = None,
        basket: Optional[BasketSpec] = None,
        closes: Optional[SeriesMap] = None,
        highs: Optional[SeriesMap] = None,
        lows: Optional[SeriesMap] = None,
        hedge_ratios: Optional[SeriesMap] = None,
        datetime_index: Optional[Union[pd.DatetimeIndex, pd.Series]] = None,
        symbols: Optional[Sequence[str]] = None,
        params: Optional[Dict] = None,
        param_ranges: Optional[Dict] = None,
    ):
        """
        Run the configured backtest and store the result.

        Parameters
        ----------
        data:
            For single-symbol modes, an OHLCV DataFrame. For portfolio/basket
            modes, either a `{symbol: DataFrame}` mapping or omitted when
            `closes/highs/lows` are supplied explicitly.
        signal:
            Single-symbol signal series, or basket entry/exit signal.
        signal_col:
            Column name to read from `data` when `signal` is omitted.
        positions:
            Portfolio positions as DataFrame or `{symbol: Series}` mapping.
        orders:
            Explicit `OrderIntent` sequence for order simulations.
        basket:
            Optional `BasketSpec` overriding the config basket for this run.
        closes/highs/lows:
            Explicit per-symbol price series maps.
        datetime_index:
            Optional common datetime index. Defaults to data/signal index.
        symbols:
            Optional symbol override for this run.
        """
        mode = self.config.mode.lower().strip()
        if mode == "walk_forward":
            return self._run_walk_forward(
                data=data,
                signal=signal,
                signal_col=signal_col,
                positions=positions,
                closes=closes,
                highs=highs,
                lows=lows,
                hedge_ratios=hedge_ratios,
                datetime_index=datetime_index,
                symbols=symbols,
                params=params,
                param_ranges=param_ranges,
            )
        if mode == "arbitrage":
            return self._run_arbitrage(
                data=data,
                signal=signal,
                signal_col=signal_col,
                closes=closes,
                highs=highs,
                lows=lows,
                hedge_ratios=hedge_ratios,
                datetime_index=datetime_index,
                symbols=symbols,
            )
        if mode in ("single_signal", "pct_equity", "signal_notional", "dca_ladder", "nautilus_validation"):
            return self._run_single(data=data, signal=signal, signal_col=signal_col, datetime_index=datetime_index, symbols=symbols)
        if mode == "orders":
            return self._run_orders(data=data, orders=orders, datetime_index=datetime_index, symbols=symbols)
        if mode == "basket":
            return self._run_basket(
                data=data,
                signal=signal,
                signal_col=signal_col,
                basket=basket,
                closes=closes,
                highs=highs,
                lows=lows,
                datetime_index=datetime_index,
                symbols=symbols,
            )
        if mode == "portfolio":
            return self._run_portfolio(
                data=data,
                positions=positions,
                closes=closes,
                highs=highs,
                lows=lows,
                datetime_index=datetime_index,
                symbols=symbols,
            )
        raise ValueError(f"unsupported endpoint mode={self.config.mode!r}")

    def simulate(self, *args, **kwargs):
        """
        Alias for `backtest()` used by order, basket, and Nautilus workflows.

        Services can call `simulate()` when the input is closer to an execution
        simulation than a pure signal backtest. The routing and return contract
        are identical to `backtest()`.
        """
        return self.backtest(*args, **kwargs)

    def full_report(self, trading_days: int = 365) -> Dict:
        """
        Return the full QuantBT metrics dictionary for the latest result.

        Raises
        ------
        RuntimeError
            If no backtest has been run yet.
        """
        return _full_report(self._require_result(), trading_days=trading_days)

    def show_metrics(self, trading_days: int = 365) -> Dict:
        """
        Print key metrics and return the full metrics dictionary.

        This intentionally mirrors the convenience style of legacy
        `BacktestEngine.analyze()` without forcing a plot.
        """
        rpt = self.full_report(trading_days=trading_days)
        print(format_metrics_report(rpt))
        return rpt

    def quick_plot(self, theme: str = "dark", figsize: tuple = (14, 6)):
        """
        Plot cumulative return and drawdown for the latest result.
        """
        return _quick_plot(self._require_result(), theme=theme, figsize=figsize)

    def tearsheet(self, theme: str = "dark", benchmark=None):
        """
        Render the full QuantBT tearsheet for the latest result.
        """
        return _tearsheet(self._require_result(), theme=theme, benchmark=benchmark)

    def export_orders(self, path: Union[str, Path]) -> None:
        """
        Export latest event/Nautilus order report to CSV.

        Native event runs store order diagnostics in
        `result.metadata["order_report"]`; Nautilus runs store raw
        `orders_report`.
        """
        result = self._require_result()
        report = result.metadata.get("order_report")
        if report is None:
            report = result.metadata.get("orders_report")
        if report is None:
            raise RuntimeError("latest result does not contain an order report")
        report.to_csv(path)

    def export_fills(self, path: Union[str, Path]) -> None:
        """
        Export latest fills to CSV.

        Native event fills are converted from `result.fills`; Nautilus fills use
        the raw `fills_report` when available.
        """
        result = self._require_result()
        report = result.metadata.get("fills_report")
        if report is None:
            rows = [getattr(fill, "__dict__", dict(fill=fill)) for fill in getattr(result, "fills", ())]
            report = pd.DataFrame(rows)
        if report.empty:
            raise RuntimeError("latest result does not contain fills")
        report.to_csv(path, index=False)

    @property
    def metrics(self) -> Dict:
        """Return `full_report()` for the latest result."""
        return self.full_report()

    @property
    def latest_orders(self):
        """Return latest explicit/generated orders, or an empty tuple."""
        return getattr(self._require_result(), "orders", ())

    @property
    def fills(self):
        """Return latest fills, or an empty tuple for non-event results."""
        return getattr(self._require_result(), "fills", ())

    @property
    def order_report(self) -> pd.DataFrame:
        """Return latest order report, or an empty DataFrame."""
        return self._require_result().metadata.get("order_report", pd.DataFrame())

    @property
    def fills_report(self) -> pd.DataFrame:
        """Return latest fills report, or an empty DataFrame."""
        return self._require_result().metadata.get("fills_report", pd.DataFrame())

    def _run_single(self, data, signal, signal_col, datetime_index, symbols):
        frame, idx, sig = _normalize_single_data(data=data, signal=signal, signal_col=signal_col, datetime_index=datetime_index)
        backend = _resolve_backend(self.config)
        symbol_list = list(symbols or self.config.symbols or ["DEFAULT"])
        if backend == "legacy":
            self.engine = BacktestEngine(
                Datetime=idx,
                Position=sig,
                Close=frame["close"],
                High=frame.get("high"),
                Low=frame.get("low"),
                fee=self.config.fee,
                use_pyramiding=self.config.use_pyramiding,
                initial_capital=self.config.account.initial_capital,
                leverage=self.config.account.leverage,
                maintenance_ratio=self.config.account.maintenance_ratio,
                contract_size=self.config.contract_size,
                use_funding_rate=self.config.use_funding,
                funding_rate=self.config.funding_rate,
                alloc_per_trade=self.config.alloc_per_trade,
                hedge_type=self.config.sizing,
                slippage=self.config.slippage,
                symbols=None,
                **self.config.dca_kwargs,
            )
            self._store_result(self.engine.result)
            return self.result

        self.engine = BacktestEngineV2(
            data=frame,
            signals=sig,
            symbols=symbol_list,
            backend=backend,
            account=self.config.account,
            execution=self.config.execution,
            fee_rate=self.config.v2_fee_rate,
            use_funding=self.config.use_funding,
            funding_rate=self.config.funding_rate,
            alloc_per_trade=self.config.alloc_per_trade,
            hedge_type=self.config.sizing,
            use_pyramiding=self.config.use_pyramiding,
            contract_size=self.config.contract_size,
            nautilus_config=self.config.nautilus_config,
        )
        self._store_result(self.engine.result)
        return self.result

    def _run_orders(self, data, orders, datetime_index, symbols):
        if not orders:
            raise ValueError("orders endpoint requires orders=[OrderIntent(...), ...]")
        frame, idx, _ = _normalize_single_data(data=data, signal=pd.Series(0.0, index=_infer_index(data, datetime_index)), signal_col=None, datetime_index=datetime_index)
        self.engine = BacktestEngineV2(
            data=frame,
            symbols=list(symbols or self.config.symbols or ["asset"]),
            backend="native_event",
            orders=orders,
            account=self.config.account,
            execution=self.config.execution,
            fee_rate=self.config.v2_fee_rate,
            use_funding=self.config.use_funding,
            funding_rate=self.config.funding_rate,
            contract_size=self.config.contract_size,
        )
        self._store_result(self.engine.result)
        return self.result

    def _run_basket(self, data, signal, signal_col, basket, closes, highs, lows, datetime_index, symbols):
        spec = basket or self.config.basket
        if spec is None:
            raise ValueError("basket endpoint requires a BasketSpec")
        sig = signal if signal is not None else _signal_from_data(data, signal_col)
        if sig is None:
            raise ValueError("basket endpoint requires signal or signal_col")
        close_map, high_map, low_map, idx, symbol_list = _normalize_symbol_data(
            data=data,
            closes=closes,
            highs=highs,
            lows=lows,
            datetime_index=datetime_index,
            symbols=symbols,
        )
        self.engine = BacktestEngineV2(
            backend="native_event",
            basket=spec,
            signal=sig,
            closes=close_map,
            highs=high_map,
            lows=low_map,
            datetime_index=idx,
            symbols=symbol_list,
            account=self.config.account,
            execution=self.config.execution,
            fee_rate=self.config.v2_fee_rate,
            use_funding=self.config.use_funding,
            funding_rate=self.config.funding_rate,
            contract_size=self.config.contract_size,
        )
        self._store_result(self.engine.result)
        return self.result

    def _run_arbitrage(self, data, signal, signal_col, closes, highs, lows, hedge_ratios, datetime_index, symbols):
        spec = self.config.arbitrage_spec
        if spec is None:
            raise ValueError("arbitrage endpoint requires an arbitrage spec")
        phase_g_package_specs = (CalendarSpreadSpec, FundingArbitrageSpec, SpotPerpCashCarrySpec, IndexBasketArbSpec)
        schema_only_specs = (CrossExchangeArbSpec, TriangularArbSpec, OptionsVolArbSpec)
        if isinstance(spec, schema_only_specs):
            raise NotImplementedError(
                f"{type(spec).__name__} is schema-validated but requires a specialized arbitrage engine; "
                "do not route it through generic package execution"
            )
        if not isinstance(spec, (BasisArbitrageSpec, StatArbPairSpec, *phase_g_package_specs)):
            raise NotImplementedError(
                "Arbitrage endpoint supports BasisArbitrageSpec, StatArbPairSpec, and package-style Phase G specs; "
                f"got {type(spec).__name__}"
            )
        backend = _resolve_backend(self.config)
        if backend not in ("native_event", "native_vectorized", "nautilus"):
            raise NotImplementedError("Phase F arbitrage endpoint supports backend='native_event', 'native_vectorized', or 'nautilus'")
        sig = signal if signal is not None else _signal_from_data(data, signal_col)
        if sig is None:
            raise ValueError("arbitrage endpoint requires signal or signal_col")
        spec_symbols = [leg.symbol for leg in spec.legs]
        close_map, high_map, low_map, idx, _ = _normalize_symbol_data(
            data=data,
            closes=closes,
            highs=highs,
            lows=lows,
            datetime_index=datetime_index,
            symbols=symbols or spec_symbols,
        )
        if backend == "nautilus":
            if not isinstance(spec, (BasisArbitrageSpec, StatArbPairSpec)):
                raise NotImplementedError("Phase F Nautilus arbitrage supports BasisArbitrageSpec and StatArbPairSpec only")
            result = self._run_nautilus_arbitrage(
                spec=spec,
                signal=sig,
                close_map=close_map,
                high_map=high_map,
                low_map=low_map,
                idx=idx,
                hedge_ratios=hedge_ratios,
            )
            self._store_result(result)
            return self.result

        if backend == "native_event":
            self.engine = NativeEventBackend(
                NativeEventConfig(
                    account=self.config.account,
                    execution=self.config.execution,
                    fee_rate=self.config.v2_fee_rate,
                    use_funding=self.config.use_funding,
                )
            )
        else:
            self.engine = NativeVectorizedBackend(
                NativeVectorizedConfig(
                    account=self.config.account,
                    execution=self.config.execution,
                    fee_rate=self.config.v2_fee_rate,
                    use_funding=self.config.use_funding,
                )
            )
        if isinstance(spec, BasisArbitrageSpec):
            result = self.engine.run_basis_arbitrage(
                datetime_index=idx,
                spec=spec,
                signal=sig,
                closes=close_map,
                highs=high_map,
                lows=low_map,
                funding_rate=self.config.funding_rate,
                contract_size=self.config.contract_size,
                leverage=self.config.account.leverage,
                hedge_ratios=hedge_ratios,
            )
        elif isinstance(spec, StatArbPairSpec):
            result = self.engine.run_stat_arb_pair_arbitrage(
                datetime_index=idx,
                spec=spec,
                signal=sig,
                closes=close_map,
                highs=high_map,
                lows=low_map,
                funding_rate=self.config.funding_rate,
                contract_size=self.config.contract_size,
                leverage=self.config.account.leverage,
                hedge_ratios=hedge_ratios,
            )
        else:
            result = self.engine.run_package_arbitrage(
                datetime_index=idx,
                spec=spec,
                signal=sig,
                closes=close_map,
                highs=high_map,
                lows=low_map,
                funding_rate=self.config.funding_rate,
                contract_size=self.config.contract_size,
                leverage=self.config.account.leverage,
                hedge_ratios=hedge_ratios,
            )
        self._store_result(result)
        return self.result

    def _run_walk_forward(
        self,
        data,
        signal,
        signal_col,
        positions,
        closes,
        highs,
        lows,
        hedge_ratios,
        datetime_index,
        symbols,
        params,
        param_ranges,
    ):
        if self.config.strategy_class is None:
            raise ValueError("walk_forward endpoint requires strategy_class")
        wf_config = self.config.walkforward_config or WalkForwardConfig(target_mode=self.config.walkforward_target_mode)
        engine = WalkForwardEngine(strategy=self.config.strategy_class, config=wf_config)
        wf_result = engine.run(
            data=data if data is not None else closes,
            params=params,
            param_ranges=param_ranges,
            datetime_index=datetime_index,
        )
        target_mode = self.config.walkforward_target_mode.lower().strip()
        stitched = wf_result.oos_output
        if stitched is None:
            raise ValueError("walk-forward strategy produced no OOS output")

        if target_mode == "portfolio":
            if isinstance(stitched, pd.Series):
                raise TypeError("portfolio walk_forward target_mode requires DataFrame or {symbol: Series} output")
            result = self._run_portfolio(
                data=data,
                positions=stitched,
                closes=closes,
                highs=highs,
                lows=lows,
                datetime_index=datetime_index,
                symbols=symbols,
            )
        elif target_mode == "arbitrage":
            if not isinstance(stitched, pd.Series):
                raise TypeError("arbitrage walk_forward target_mode requires a scalar signal Series output")
            result = self._run_arbitrage(
                data=data,
                signal=stitched,
                signal_col=None,
                closes=closes,
                highs=highs,
                lows=lows,
                hedge_ratios=hedge_ratios,
                datetime_index=datetime_index,
                symbols=symbols,
            )
        elif target_mode == "basket":
            if not isinstance(stitched, pd.Series):
                raise TypeError("basket walk_forward target_mode requires a scalar signal Series output")
            result = self._run_basket(
                data=data,
                signal=stitched,
                signal_col=None,
                basket=self.config.basket,
                closes=closes,
                highs=highs,
                lows=lows,
                datetime_index=datetime_index,
                symbols=symbols,
            )
        else:
            if not isinstance(stitched, pd.Series):
                raise TypeError(f"{target_mode} walk_forward target_mode requires a scalar signal Series output")
            result = self._run_single(
                data=data,
                signal=stitched,
                signal_col=None,
                datetime_index=datetime_index,
                symbols=symbols,
            )

        wf_result.backtest_result = result
        result.metadata["walk_forward"] = {
            "engine": wf_result.metadata["engine"],
            "target_mode": target_mode,
            "n_folds": wf_result.metadata["n_folds"],
            "params": wf_result.params,
            "fold_table": wf_result.fold_table,
            "trial_table": wf_result.trial_table,
            "candidate_table": wf_result.candidate_table,
            "best_trial": wf_result.best_trial,
            "optimization_mode": wf_result.metadata.get("optimization_mode"),
            "data_hash": wf_result.metadata.get("data_hash"),
            "config_hash": wf_result.metadata.get("config_hash"),
            "random_seed": wf_result.metadata.get("random_seed"),
            "top_is_fraction": wf_result.metadata.get("top_is_fraction"),
            "top_is_k": wf_result.metadata.get("top_is_k"),
            "candidate_selection_metric": wf_result.metadata.get("candidate_selection_metric"),
            "scoring_trading_days": wf_result.metadata.get("scoring_trading_days"),
            "min_trades_per_year": wf_result.metadata.get("min_trades_per_year"),
            "trade_penalty_factor": wf_result.metadata.get("trade_penalty_factor"),
            "numba_enabled": wf_result.metadata.get("numba_enabled"),
        }
        result.metadata["walk_forward_result"] = wf_result
        self.engine = engine
        self.result = result
        return result

    def _run_nautilus_arbitrage(self, spec, signal, close_map, high_map, low_map, idx, hedge_ratios):
        from .adapters.nautilus import NautilusBackendConfig, NautilusBacktestEngine

        symbols = [leg.symbol for leg in spec.legs]
        if isinstance(spec, BasisArbitrageSpec):
            plan = build_arbitrage_order_plan(
                datetime_index=idx,
                spec=spec,
                signal=signal,
                closes=close_map,
                hedge_ratios=hedge_ratios,
            )
            extra_metadata = {
                "spread_report": NativeVectorizedBackend(
                    NativeVectorizedConfig(account=self.config.account, execution=self.config.execution)
                )._basis_spread_report(idx, spec, close_map, plan.target_units),
                "package_rejection_report": plan.rejection_report,
            }
        elif isinstance(spec, StatArbPairSpec):
            basket = BasketSpec(
                basket_id=spec.arb_id,
                legs=tuple(BasketLegSpec(symbol=leg.symbol, ratio=float(leg.ratio)) for leg in spec.legs),
                gross_notional=float(spec.sizing_policy.notional),
                freeze_hedge=bool(spec.hedge_policy.freeze_on_entry),
                hedged_margin_offset=float(spec.margin_model.hedged_margin_offset),
            )
            rebalance_threshold = spec.hedge_policy.rebalance_threshold
            if not spec.hedge_policy.freeze_on_entry and rebalance_threshold is None:
                rebalance_threshold = 0.0
            plan = build_frozen_basket_orders(
                datetime_index=idx,
                basket=basket,
                signal=signal,
                closes=close_map,
                hedge_ratios=hedge_ratios,
                order_type=OrderType.MARKET,
                tif=TimeInForce.IOC,
                rebalance_threshold=rebalance_threshold,
            )
            extra_metadata = {
                "beta_drift_report": NativeVectorizedBackend(
                    NativeVectorizedConfig(account=self.config.account, execution=self.config.execution)
                )._stat_arb_beta_drift_report(idx, spec, plan, rebalance_threshold),
                "rebalance_threshold": rebalance_threshold,
            }
        else:
            raise NotImplementedError(f"Nautilus arbitrage does not support {type(spec).__name__}")

        data = _frames_from_symbol_maps(close_map, high_map, low_map, symbols)
        config = self.config.nautilus_config
        if config is None:
            config = NautilusBackendConfig(
                timeframe=str(self.config.metadata.get("timeframe", "1h")),
                starting_balance=self.config.account.initial_capital,
                trade_notional=0.0,
                sizing_mode="notional",
            )
        else:
            config = replace(
                config,
                starting_balance=self.config.account.initial_capital,
                trade_notional=0.0,
                sizing_mode="notional",
            )
        self.engine = NautilusBacktestEngine(config)
        result = self.engine.run_order_packages(
            data=data,
            orders=plan.orders,
            symbols=symbols,
            params={
                "arb_id": spec.arb_id,
                "arb_type": spec.arb_type.value,
                "arbitrage_plan": plan,
                "package_target_units": plan.target_units,
                **extra_metadata,
            },
        )
        result.metadata["engine"] = "nautilus_arbitrage_package"
        return result

    def _run_portfolio(self, data, positions, closes, highs, lows, datetime_index, symbols):
        pos_map = _positions_to_map(positions)
        if not pos_map:
            raise ValueError("portfolio endpoint requires positions DataFrame or mapping")
        close_map, high_map, low_map, idx, _ = _normalize_symbol_data(
            data=data,
            closes=closes,
            highs=highs,
            lows=lows,
            datetime_index=datetime_index,
            symbols=symbols or list(pos_map.keys()),
        )
        self.engine = PortfolioBacktestEngine(
            positions=pos_map,
            closes=close_map,
            highs=high_map,
            lows=low_map,
            datetime_index=idx,
            mode=self.config.portfolio_mode,
            account=self.config.account,
            execution=self.config.execution,
            fee_rate=self.config.fee,
            alloc_per_trade=self.config.alloc_per_trade,
            contract_size=self.config.contract_size,
            hedge_type=self.config.sizing if self.config.sizing else "notional",
            asset_type=self.config.asset_type,
            use_funding=self.config.use_funding,
            funding_rate=self.config.funding_rate,
            leverage=self.config.account.leverage,
            maintenance_ratio=self.config.account.maintenance_ratio,
        )
        self._store_result(self.engine.result)
        return self.result

    def _store_result(self, result):
        _normalize_result_contract(result)
        self.result = result
        return result

    def _require_result(self):
        if self.result is None:
            raise RuntimeError("run backtest() or simulate() before requesting results")
        return self.result


def _normalize_result_contract(result) -> None:
    """
    Make common result artifacts safe to access across all endpoint backends.

    Legacy and vectorized results do not naturally have fills/orders. Notebook
    integrations still benefit from stable empty artifacts instead of
    AttributeError/KeyError.
    """
    metadata = result.metadata
    if not hasattr(result, "orders"):
        setattr(result, "orders", ())
    if not hasattr(result, "fills"):
        setattr(result, "fills", ())

    order_report = metadata.get("order_report")
    if order_report is None:
        order_report = metadata.get("orders_report")
    if order_report is None:
        order_report = pd.DataFrame()
    metadata["order_report"] = order_report
    if metadata.get("orders_report") is None:
        metadata["orders_report"] = order_report

    if metadata.get("fills_report") is None:
        metadata["fills_report"] = _fills_to_frame(getattr(result, "fills", ()))
    if metadata.get("positions_report") is None:
        metadata["positions_report"] = pd.DataFrame()
    if "orders_count" not in metadata:
        metadata["orders_count"] = len(getattr(result, "orders", ()))
    if "fills_count" not in metadata:
        metadata["fills_count"] = len(getattr(result, "fills", ()))


def _fills_to_frame(fills) -> pd.DataFrame:
    rows = []
    for fill in fills:
        row = getattr(fill, "__dict__", None)
        rows.append(dict(row) if row is not None else {"fill": fill})
    return pd.DataFrame(rows)


def format_metrics_report(report: Dict) -> str:
    """
    Format a metrics dictionary as a legacy-style text report.

    The returned string is intentionally plain monospaced text so notebooks,
    terminals, logs, and services all render the same high-signal report.
    """
    lines = [
        ("Initial Capital", _fmt_money(report.get("initial_capital"), decimals=0)),
        ("Final Equity", _fmt_money(report.get("final_equity"), decimals=2)),
        ("Total Return", _fmt_pct(report.get("total_return_pct"), signed=True, decimals=2)),
        ("CAGR", _fmt_pct(report.get("cagr_pct"), signed=True, decimals=2)),
        ("Sharpe Ratio", _fmt_float(report.get("sharpe"), decimals=3)),
        ("Sortino Ratio", _fmt_float(report.get("sortino"), decimals=3)),
        ("Calmar Ratio", _fmt_float(report.get("calmar"), decimals=3)),
        ("Omega Ratio", _fmt_float(report.get("omega"), decimals=3)),
        ("Max Drawdown", _fmt_pct(report.get("max_drawdown_pct"), signed=False, decimals=2)),
        ("Avg Drawdown", _fmt_pct(report.get("avg_drawdown_pct"), signed=False, decimals=2)),
        ("Max DD Duration", _fmt_days(report.get("max_dd_duration_days"))),
        ("Profit Factor", _fmt_float(report.get("profit_factor"), decimals=3)),
        ("Long Hit Rate", _fmt_pct(report.get("long_hitrate_pct"), signed=False, decimals=2)),
        ("Short Hit Rate", _fmt_pct(report.get("short_hitrate_pct"), signed=False, decimals=2)),
        ("Avg Win", _fmt_pct(report.get("avg_win_pct"), signed=True, decimals=3)),
        ("Avg Loss", _fmt_pct(report.get("avg_loss_pct"), signed=True, decimals=3)),
        ("Expectancy", _fmt_pct(report.get("expectancy_pct"), signed=True, decimals=3)),
        ("Number of Trades", _fmt_int(report.get("num_trades"))),
        ("Liquidated", f"{'Yes' if report.get('liquidated') else 'No':>14}"),
    ]
    col_width = max(len(key) for key, _ in lines)
    body = "\n".join(f"  {key:<{col_width}}  {value}" for key, value in lines)
    return f"\n{body}\n"


def _fmt_money(value, decimals: int) -> str:
    if value is None or pd.isna(value):
        return f"{'n/a':>15}"
    return f"$ {float(value):>13,.{decimals}f}"


def _fmt_pct(value, signed: bool, decimals: int) -> str:
    if value is None or pd.isna(value):
        return f"{'n/a':>15}"
    sign = "+" if signed else ""
    return f"{float(value):>{sign}13.{decimals}f}%"


def _fmt_float(value, decimals: int) -> str:
    if value is None or pd.isna(value):
        return f"{'n/a':>14}"
    return f"{float(value):>14.{decimals}f}"


def _fmt_days(value) -> str:
    if value is None or pd.isna(value):
        return f"{'n/a':>16}"
    return f"{int(value):>11d} days"


def _fmt_int(value) -> str:
    if value is None or pd.isna(value):
        return f"{'n/a':>14}"
    return f"{int(value):>14,d}"


def _config_from_kwargs(**kwargs) -> EndpointConfig:
    hedge_type_alias = kwargs.pop("hedge_type", None)
    if hedge_type_alias is not None and "sizing" not in kwargs:
        kwargs["sizing"] = hedge_type_alias

    initial_capital = kwargs.pop("initial_capital", None)
    leverage = kwargs.pop("leverage", None)
    maintenance_ratio = kwargs.pop("maintenance_ratio", None)
    account = kwargs.pop("account", None)
    if account is None:
        account = AccountConfig(
            initial_capital=100_000.0 if initial_capital is None else float(initial_capital),
            leverage=1.0 if leverage is None else float(leverage),
            maintenance_ratio=0.005 if maintenance_ratio is None else float(maintenance_ratio),
        )

    slippage_bps = kwargs.pop("slippage_bps", None)
    execution = kwargs.pop("execution", None)
    if execution is None:
        execution = ExecutionConfig(slippage_bps=0.0 if slippage_bps is None else float(slippage_bps))

    dca_kwargs = kwargs.pop("dca_kwargs", {})
    for key in (
        "dca_base_notional",
        "dca_safety_notional",
        "dca_step_pct",
        "dca_step_scale",
        "dca_volume_scale",
        "dca_max_safety_orders",
        "dca_take_profit_pct",
        "dca_allow_same_bar_exit",
    ):
        if key in kwargs:
            dca_kwargs[key] = kwargs.pop(key)

    return EndpointConfig(account=account, execution=execution, dca_kwargs=dca_kwargs, **kwargs)


def _resolve_backend(config: EndpointConfig) -> str:
    backend = config.backend.lower().strip()
    if backend != "auto":
        if backend == "legacy_portfolio":
            return backend
        if backend not in {"legacy", "native_vectorized", "native_event", "nautilus"}:
            raise ValueError(f"unsupported backend={config.backend!r}")
        return backend
    mode = config.mode.lower().strip()
    sizing = config.sizing.lower().strip()
    if mode in ("pct_equity", "dca_ladder") or sizing in ("%_equity", "pct_equity", "dca_ladder", "dca"):
        return "legacy"
    if mode == "nautilus_validation":
        return "nautilus"
    if mode in ("orders", "basket", "arbitrage"):
        return "native_event"
    return "native_vectorized"


def _normalize_single_data(data, signal, signal_col, datetime_index):
    if data is None:
        raise ValueError("single-symbol endpoint requires data DataFrame")
    frame = _standardize_frame(data, datetime_index)
    sig = signal if signal is not None else _signal_from_data(frame, signal_col)
    if sig is None:
        raise ValueError("single-symbol endpoint requires signal or signal_col")
    sig = sig.copy()
    if isinstance(sig.index, pd.DatetimeIndex):
        sig.index = sig.index.tz_localize("UTC") if sig.index.tz is None else sig.index.tz_convert("UTC")
    sig = sig[~sig.index.duplicated(keep="first")].reindex(frame.index, method="ffill").fillna(0.0)
    return frame, frame.index, sig


def _normalize_symbol_data(data, closes, highs, lows, datetime_index, symbols):
    if closes is not None:
        symbol_list = list(symbols or closes.keys())
        idx = pd.DatetimeIndex(datetime_index if datetime_index is not None else closes[symbol_list[0]].index)
        idx = _ensure_utc_index(idx)
        close_map = {s: _align_series(closes[s], idx) for s in symbol_list}
        high_map = {s: _align_series((highs or closes)[s], idx) for s in symbol_list}
        low_map = {s: _align_series((lows or closes)[s], idx) for s in symbol_list}
        return close_map, high_map, low_map, idx, symbol_list
    if not isinstance(data, dict):
        raise ValueError("multi-symbol endpoint requires data dict or explicit closes")
    symbol_list = list(symbols or data.keys())
    frames = {s: _standardize_frame(data[s], datetime_index=None) for s in symbol_list}
    idx = _ensure_utc_index(datetime_index if datetime_index is not None else frames[symbol_list[0]].index)
    close_map = {s: _align_series(frames[s]["close"], idx) for s in symbol_list}
    high_map = {s: _align_series(frames[s].get("high", frames[s]["close"]), idx) for s in symbol_list}
    low_map = {s: _align_series(frames[s].get("low", frames[s]["close"]), idx) for s in symbol_list}
    return close_map, high_map, low_map, idx, symbol_list


def _frames_from_symbol_maps(close_map, high_map, low_map, symbols) -> FrameMap:
    frames = {}
    for symbol in symbols:
        close = close_map[symbol]
        frames[symbol] = pd.DataFrame(
            {
                "open": close,
                "high": high_map.get(symbol, close),
                "low": low_map.get(symbol, close),
                "close": close,
                "volume": 0.0,
            },
            index=close.index,
        )
    return frames


def _standardize_frame(data, datetime_index=None) -> pd.DataFrame:
    if not isinstance(data, pd.DataFrame):
        raise ValueError("data must be a pandas DataFrame")
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
    if datetime_index is not None:
        frame.index = _ensure_utc_index(datetime_index)
    elif "timestamp" in frame.columns:
        frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True, errors="coerce")
        frame = frame.dropna(subset=["timestamp"]).set_index("timestamp")
    else:
        frame.index = _ensure_utc_index(frame.index)
    frame = frame[~frame.index.duplicated(keep="first")].sort_index()
    if "close" not in frame.columns:
        raise ValueError("data must contain close/Close")
    for col in ("high", "low"):
        if col not in frame.columns:
            frame[col] = frame["close"]
    if "open" not in frame.columns:
        frame["open"] = frame["close"]
    if "volume" not in frame.columns:
        frame["volume"] = 0.0
    return frame


def _signal_from_data(data, signal_col):
    if signal_col is None:
        return None
    if data is None or signal_col not in data:
        raise ValueError(f"signal_col={signal_col!r} not found in data")
    return data[signal_col]


def _positions_to_map(positions) -> Dict[str, pd.Series]:
    if positions is None:
        return {}
    if isinstance(positions, pd.DataFrame):
        return {str(col): positions[col] for col in positions.columns}
    return dict(positions)


def _infer_index(data, datetime_index):
    if datetime_index is not None:
        return _ensure_utc_index(datetime_index)
    if isinstance(data, pd.DataFrame):
        return _standardize_frame(data).index
    raise ValueError("could not infer datetime index")


def _ensure_utc_index(index) -> pd.DatetimeIndex:
    return pd.DatetimeIndex(pd.to_datetime(index, utc=True))


def _align_series(series: pd.Series, idx: pd.DatetimeIndex) -> pd.Series:
    ser = series.copy()
    if isinstance(ser.index, pd.DatetimeIndex):
        ser.index = ser.index.tz_localize("UTC") if ser.index.tz is None else ser.index.tz_convert("UTC")
    return ser[~ser.index.duplicated(keep="first")].reindex(idx, method="ffill")
