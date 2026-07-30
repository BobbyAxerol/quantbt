"""
Unified public endpoint for notebooks and services.

`QuantBTEndpoint` is the stable integration surface above legacy and V2
backtest engines. It stores *how* to run a backtest at construction time, while
`backtest()` / `simulate()` receive the actual data, signals, orders, or basket
objects.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass, replace
import hashlib
import json
from pathlib import Path
from typing import Dict, Optional, Sequence, Union
import warnings

import numpy as np
import pandas as pd

from .backtester import BacktestEngine
from .backends import (
    NativeEventBackend,
    NativeEventConfig,
    NativeOptionConfig,
    NativePortfolioBackend,
    NativePortfolioConfig,
    NativeVectorizedBackend,
    NativeVectorizedConfig,
)
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
from .core.execution_depth import (
    NautilusExecutionDepthConfig,
    simulate_nautilus_order_package_depth,
)
from .core.execution_contract import ExecutionContract
from .core.constraints import build_quantity_constraints
from .core.intrabar_reference import (
    IntrabarIntentTape,
    IntrabarLevelMode,
    IntrabarSizingMode,
    run_intrabar_reference,
)
from .core.intrabar_session import IntrabarSessionTape, SessionExecutionPolicy
from .core.intrabar_kernel import FillReplayTape, run_fill_replay_kernel, run_intrabar_kernel, run_intrabar_session_kernel
from .core.market_tape import PreparedMarketTape, prepare_market_tape
from .core.orders import OrderCommand, OrderIntent, order_intents_to_lifecycle_commands
from .core.results import BacktestResultV2, NativeAccountingArrays, NativeEventScoreResult, OptionBacktestResult
from .core.schema import AccountConfig, BasketLegSpec, BasketSpec, ExecutionConfig, InstrumentSpec, OrderSide, OrderType, TimeInForce
from .core.structured_orders import (
    BracketOrderSpec,
    DcaGridSpec,
    build_bracket_order_plan,
    build_dca_grid_order_plan,
)
from .core.types import BacktestResult
from .engines import BacktestEngineV2, OptionBacktestEngine, PortfolioBacktestEngine
from .metrics import full_report as _full_report
from .reporting import build_portfolio_nautilus_validation_report
from .sizing.modes import compute_target_units
from .options.execution import OptionExecutionConfig
from .options.fees import OptionFeeSchedule
from .options.hedging import OptionHedgeConfig
from .options.margin import OptionMarginConfig
from .options.cache import OptionPreparedRunCache
from .options.packages import OptionPackageIntent
from .options.schema import OptionInstrumentRegistry, OptionInstrumentSpec
from .options.strategy import OptionStrategyRun
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
        `portfolio`, `arbitrage`, `options`, `walk_forward`, and
        `nautilus_validation`.
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
    structured_order_spec:
        Optional DCA/grid or bracket/OCO package spec compiled into explicit
        orders for Nautilus structured-order validation.
    symbols:
        Optional symbol list. Single-symbol endpoints use the first symbol.
    dca_kwargs:
        Extra DCA ladder parameters forwarded to legacy `BacktestEngine`.
    nautilus_config:
        Optional `NautilusBackendConfig` instance for Nautilus validation runs.
    nautilus_depth_config:
        Optional `NautilusExecutionDepthConfig` for package-order preflight.
        Existing endpoints are unchanged when this is omitted.
    report_level:
        Native portfolio artifact policy. `full` preserves all audit reports;
        `standard` keeps core audit tables; `minimal` keeps accounting outputs
        for optimizer/service loops. Existing calls default to `full`.
    option_config:
        Optional `NativeOptionConfig` for native option simulations.
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
    instruments: Optional[Union[Dict[str, InstrumentSpec], Sequence[InstrumentSpec]]] = None
    qty_step: Optional[Union[float, Dict[str, float]]] = None
    lot_size: Optional[Union[float, Dict[str, float]]] = None
    slot_size: Optional[Union[float, Dict[str, float]]] = None
    min_qty: Optional[Union[float, Dict[str, float]]] = None
    min_notional: Optional[Union[float, Dict[str, float]]] = None
    slippage: float = 0.0001
    portfolio_mode: str = "longshort"
    betas: Union[float, Dict[str, float], None] = None
    risk_lookback: int = 60
    asset_type: str = "crypto"
    basket: Optional[BasketSpec] = None
    arbitrage_spec: object = None
    structured_order_spec: object = None
    event_engine_version: str = "v1"
    reactive_execution_mode: str = "fast"
    reactive_kernel_mode: str = "replay_certified"
    symbols: Optional[Sequence[str]] = None
    dca_kwargs: Dict = field(default_factory=dict)
    nautilus_config: object = None
    nautilus_depth_config: Optional[NautilusExecutionDepthConfig] = None
    option_config: object = None
    report_level: str = "full"
    audit_sink: str = "memory"
    audit_sink_path: Optional[str] = None
    strategy_class: object = None
    walkforward_config: Optional[WalkForwardConfig] = None
    walkforward_target_mode: str = "signal_notional"
    metadata: Dict = field(default_factory=dict)

    @property
    def v2_fee_rate(self) -> float:
        return self.fee / 2.0 if self.fee_rate is None else float(self.fee_rate)


@dataclass(frozen=True)
class PreparedIntrabarRunner:
    """Prepared single-symbol intrabar runner for repeated WFO/Optuna runs."""

    endpoint: "QuantBTEndpoint"
    tape: PreparedMarketTape
    symbol: str
    contract: ExecutionContract
    profile_metadata: Dict
    session_policy: Optional[SessionExecutionPolicy] = None
    session_tape: Optional[IntrabarSessionTape] = None

    @property
    def market(self) -> PreparedMarketTape:
        return self.tape

    def run(self, intent: IntrabarIntentTape, *, report_level: Optional[str] = None) -> BacktestResultV2:
        config = self.endpoint.config
        level = report_level or config.report_level
        kwargs = {
            "tape": self.tape,
            "intent": intent,
            "account": config.account,
            "contract": self.contract,
            "fee_rate": config.v2_fee_rate,
            "slippage_rate": float(config.execution.slippage_rate),
            "contract_size": _scalar_for_symbol(config.contract_size, self.symbol),
            **self.endpoint._intrabar_execution_kwargs(self.symbol),
            "report_level": level,
        }
        if self.session_policy is not None:
            kernel = run_intrabar_session_kernel(
                **kwargs,
                session_policy=self.session_policy,
                session_tape=self.session_tape,
            )
        else:
            kernel = run_intrabar_kernel(**kwargs)
        idx = kernel.equity.index
        returns = kernel.equity.pct_change().replace([np.inf, -np.inf], np.nan).fillna(0.0)
        diagnostics = pd.DataFrame(
            {
                "average_entry": kernel.average_entry,
                "active_stop": kernel.active_stop,
                "active_take_profit": kernel.active_take_profit,
                "event_flags": kernel.event_flags,
                "initial_margin": kernel.initial_margin,
                "maintenance_margin": kernel.maintenance_margin,
                "fees": kernel.fees,
                "funding": kernel.funding,
            },
            index=idx,
        )
        metadata = {
            **kernel.metadata,
            "input_mode": "intrabar_intent",
            "symbol": self.symbol,
            "phase": "31F_prepared_intrabar_runner",
            "prepared_runner": True,
            "profile_metadata": dict(self.profile_metadata),
            "fills_report": kernel.fills_report,
            "positions_report": pd.DataFrame({f"Position_{self.symbol}": kernel.position}, index=idx),
        }
        result = BacktestResultV2(
            equity=kernel.equity,
            returns=returns,
            positions=pd.DataFrame({f"Position_{self.symbol}": kernel.position.to_numpy(dtype=float)}, index=idx),
            closes=pd.DataFrame({f"Close_{self.symbol}": self.tape.closes[:, 0]}, index=idx),
            symbols=[self.symbol],
            initial_capital=float(config.account.initial_capital),
            leverage=float(config.account.leverage),
            liquidated=bool(kernel.liquidated),
            liquidation_bar=int(kernel.liquidation_bar),
            fills=kernel.fills,
            fees=kernel.fees,
            funding=kernel.funding,
            margin=diagnostics[["initial_margin", "maintenance_margin"]],
            diagnostics=diagnostics,
            metadata=metadata,
        )
        self.endpoint.engine = kernel
        self.endpoint._store_result(result)
        return self.endpoint.result


@dataclass(frozen=True)
class PreparedNativeEventStrategyRunner:
    """Prepared native-event reactive runner for repeated strategy scoring."""

    endpoint: "QuantBTEndpoint"
    idx: pd.DatetimeIndex
    symbols: list
    close_map: SeriesMap
    high_map: SeriesMap
    low_map: SeriesMap
    opens_arr: np.ndarray
    volumes_arr: np.ndarray
    market_arrays: object
    backend: NativeEventBackend
    profile_metadata: Dict
    runs: int = 0
    scores: int = 0

    def run(self, strategy, *, report_level: Optional[str] = None) -> BacktestResultV2:
        """Run the prepared strategy and return the public BacktestResultV2."""
        if strategy is None:
            raise ValueError("prepared native-event runner requires strategy=...")
        config = self.endpoint.config
        level = report_level or config.report_level
        result = self.backend.run_strategy(
            datetime_index=self.idx,
            strategy=strategy,
            closes=self.close_map,
            highs=self.high_map,
            lows=self.low_map,
            opens=None,
            volumes=None,
            funding_rate=config.funding_rate,
            contract_size=config.contract_size,
            leverage=config.account.leverage,
            fee_rate=config.v2_fee_rate,
            symbols=self.symbols,
            instruments=config.instruments,
            qty_step=config.qty_step,
            lot_size=config.lot_size,
            slot_size=config.slot_size,
            min_qty=config.min_qty,
            min_notional=config.min_notional,
            execution_mode=config.reactive_execution_mode,
            reactive_kernel_mode=config.reactive_kernel_mode,
            report_level=level,
            audit_sink=config.audit_sink,
            audit_sink_path=config.audit_sink_path,
            market_arrays=self.market_arrays,
            opens_arr=self.opens_arr,
            volumes_arr=self.volumes_arr,
        )
        result.metadata.setdefault("prepared_native_event_strategy", self.metadata)
        object.__setattr__(self, "runs", self.runs + 1)
        self.endpoint._store_result(result)
        return self.endpoint.result

    simulate = run

    def score(self, strategy, *, trading_days: int = 365) -> NativeEventScoreResult:
        """
        Run the prepared strategy with score artifact retention.

        The returned object stores ndarray accounting arrays and scalar metrics;
        it intentionally does not update `endpoint.result`.
        """
        if strategy is None:
            raise ValueError("prepared native-event score requires strategy=...")
        config = self.endpoint.config
        result = self.backend.run_strategy(
            datetime_index=self.idx,
            strategy=strategy,
            closes=self.close_map,
            highs=self.high_map,
            lows=self.low_map,
            opens=None,
            volumes=None,
            funding_rate=config.funding_rate,
            contract_size=config.contract_size,
            leverage=config.account.leverage,
            fee_rate=config.v2_fee_rate,
            symbols=self.symbols,
            instruments=config.instruments,
            qty_step=config.qty_step,
            lot_size=config.lot_size,
            slot_size=config.slot_size,
            min_qty=config.min_qty,
            min_notional=config.min_notional,
            execution_mode=config.reactive_execution_mode,
            reactive_kernel_mode="single_pass",
            report_level="score",
            audit_sink="none",
            market_arrays=self.market_arrays,
            opens_arr=self.opens_arr,
            volumes_arr=self.volumes_arr,
        )
        accounting = NativeAccountingArrays.from_result(result)
        counters = dict(result.metadata.get("lifecycle_counters") or {})
        score = NativeEventScoreResult(
            accounting=accounting,
            final_positions=accounting.positions[-1].copy(),
            fill_count=int(counters.get("fill_count", 0)),
            rejection_count=int(counters.get("rejected_count", 0)),
            cancellation_count=int(counters.get("canceled_count", 0)),
            liquidated=bool(result.liquidated),
            liquidation_bar=int(result.liquidation_bar),
            metrics={},
            metadata={
                "backend": "native_event",
                "engine": "event_v2_reactive_score",
                "report_level": "score",
                "prepared_native_event_strategy": self.metadata,
                "lifecycle_counters": counters,
                "artifact_plan": result.metadata.get("artifact_plan"),
                "reactive_kernel_mode": result.metadata.get("reactive_kernel_mode"),
                "static_replay_available": result.metadata.get("static_replay_available"),
            },
        )
        object.__setattr__(self, "scores", self.scores + 1)
        return replace(score, metrics=score.full_report(trading_days=trading_days))

    @property
    def metadata(self) -> Dict[str, object]:
        return {
            **self.profile_metadata,
            "runs": int(self.runs),
            "scores": int(self.scores),
            "market_signature": self.market_arrays.signature,
        }


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

    def prepare_service_context(
        self,
        *,
        data=None,
        closes=None,
        highs=None,
        lows=None,
        datetime_index=None,
        symbols=None,
    ) -> "QuantBTPreparedContext":
        """
        Normalize market data once for repeated service/WFO-style replays.

        This is an opt-in performance helper. It does not change normal
        `backtest(...)` behavior and only supports routes whose prepared-array
        parity is locked by tests: single-symbol `signal_notional` with
        `native_vectorized`, and `portfolio` with `native_portfolio`.
        """
        return QuantBTPreparedContext.from_endpoint(
            self,
            data=data,
            closes=closes,
            highs=highs,
            lows=lows,
            datetime_index=datetime_index,
            symbols=symbols,
        )

    def prepare_intrabar(
        self,
        *,
        data,
        datetime_index=None,
        symbols: Optional[Sequence[str]] = None,
        session_tape: Optional[IntrabarSessionTape] = None,
        funding_event_timestamps=None,
        funding_event_rates=None,
    ) -> PreparedIntrabarRunner:
        """
        Prepare strict intrabar market tape once and reuse it for many intents.

        This is an opt-in service/WFO helper. Normal `.backtest(...)` remains
        backward-compatible, while optimizer loops can avoid rebuilding OHLCV,
        funding, validation certificate, data signature, and quantity profiles
        on every trial.
        """
        symbol_list = list(symbols or self.config.symbols or ["DEFAULT"])
        if len(symbol_list) != 1:
            raise ValueError("prepare_intrabar currently supports exactly one symbol")
        tape = prepare_market_tape(
            data=data,
            datetime_index=datetime_index,
            symbols=symbol_list,
            funding_rate=self.config.funding_rate,
            funding_event_timestamps=funding_event_timestamps,
            funding_event_rates=funding_event_rates,
            use_funding=self.config.use_funding,
            validation_mode="strict",
            missing_funding_policy=str(self.config.metadata.get("missing_funding_policy", "raise")),
            source_timezone=self.config.metadata.get("source_timezone"),
            bar_timestamp_semantics=str(self.config.metadata.get("bar_timestamp_semantics", "close")),
        )
        contract = _execution_contract_from_config(self.config)
        session_policy = _session_policy_from_config(self.config)
        if session_policy is not None and session_tape is None:
            raise ValueError("session_tape is required when session_policy is configured")
        if session_tape is not None and len(session_tape.session_id) != tape.n_bars:
            raise ValueError("session_tape length must match prepared market tape length")
        symbol = symbol_list[0]
        profile = {
            "mode": self.config.mode,
            "backend": self.config.backend,
            "account": asdict(self.config.account),
            "execution": asdict(self.config.execution),
            "fee_rate": self.config.v2_fee_rate,
            "contract_size": _scalar_for_symbol(self.config.contract_size, symbol),
            "intrabar": self._intrabar_execution_kwargs(symbol),
            "data_signature": tape.signature,
            "session_policy": None if session_policy is None else session_policy.to_metadata(),
            "session_tape_signature": None if session_tape is None else session_tape.signature,
        }
        profile["prepared_signature"] = _prepared_profile_signature(tape.signature, profile)
        return PreparedIntrabarRunner(
            endpoint=self,
            tape=tape,
            symbol=symbol,
            contract=contract,
            profile_metadata=profile,
            session_policy=session_policy,
            session_tape=session_tape,
        )

    def prepare_native_event_strategy(
        self,
        *,
        data=None,
        closes=None,
        highs=None,
        lows=None,
        datetime_index=None,
        symbols: Optional[Sequence[str]] = None,
    ) -> PreparedNativeEventStrategyRunner:
        """
        Prepare native-event reactive market state once for repeated scoring.

        Normal `native_event_strategy(...).simulate(...)` remains unchanged.
        This helper is for WFO/Optuna/service loops where the same market tape
        is replayed many times with different strategy parameters.
        """
        config = self.config
        if str(config.backend).lower().strip() not in {"native_event", "auto"}:
            raise ValueError("prepare_native_event_strategy requires backend='native_event' or auto")
        symbol_list = list(symbols or config.symbols or (closes.keys() if closes is not None else []))
        if data is not None and not isinstance(data, dict) and not symbol_list:
            symbol_list = ["asset"]
        if not symbol_list:
            raise ValueError("prepare_native_event_strategy requires symbols")
        if data is not None and not isinstance(data, dict):
            if len(symbol_list) != 1:
                raise ValueError("single DataFrame native-event preparation requires exactly one symbol")
            frame = _standardize_frame(data, datetime_index=datetime_index)
            symbol = symbol_list[0]
            idx = frame.index
            close_map = {symbol: frame["close"]}
            high_map = {symbol: frame.get("high", frame["close"])}
            low_map = {symbol: frame.get("low", frame["close"])}
            opens_arr = np.ascontiguousarray(frame[["open"]].to_numpy(dtype=np.float64))
            volumes_arr = np.ascontiguousarray(frame[["volume"]].to_numpy(dtype=np.float64))
        else:
            close_map, high_map, low_map, idx, symbol_list = _normalize_symbol_data(
                data=data,
                closes=closes,
                highs=highs,
                lows=lows,
                datetime_index=datetime_index,
                symbols=symbol_list,
            )
            opens_arr, volumes_arr = _prepared_native_event_open_volume_arrays(data, idx, symbol_list, close_map)
        backend = NativeEventBackend(
            NativeEventConfig(
                account=config.account,
                execution=config.execution,
                fee_rate=config.v2_fee_rate,
                use_funding=bool(config.use_funding),
                report_level=config.report_level,
                audit_sink=config.audit_sink,
                audit_sink_path=config.audit_sink_path,
                reactive_kernel_mode=config.reactive_kernel_mode,
            )
        )
        market = backend.prepare_market_arrays(
            datetime_index=idx,
            closes=close_map,
            highs=high_map,
            lows=low_map,
            funding_rate=config.funding_rate,
            symbols=symbol_list,
        )
        profile = {
            "mode": config.mode,
            "backend": "native_event",
            "event_engine_version": "v2",
            "reactive_execution_mode": config.reactive_execution_mode,
            "reactive_kernel_mode": config.reactive_kernel_mode,
            "account": asdict(config.account),
            "execution": asdict(config.execution),
            "fee_rate": config.v2_fee_rate,
            "report_level": config.report_level,
            "symbols": tuple(symbol_list),
            "bars": int(len(idx)),
            "data_signature": market.signature,
        }
        return PreparedNativeEventStrategyRunner(
            endpoint=self,
            idx=idx,
            symbols=list(symbol_list),
            close_map=close_map,
            high_map=high_map,
            low_map=low_map,
            opens_arr=opens_arr,
            volumes_arr=volumes_arr,
            market_arrays=market,
            backend=backend,
            profile_metadata=profile,
        )

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
    def intrabar_bracket_reference(
        cls,
        *,
        level_mode: Union[str, IntrabarLevelMode] = IntrabarLevelMode.PERCENT_DISTANCE,
        intrabar_sizing_mode: Union[str, IntrabarSizingMode] = IntrabarSizingMode.UNITS,
        close_on_last_bar: bool = True,
        execution_contract: Optional[ExecutionContract] = None,
        session_policy: Optional[SessionExecutionPolicy] = None,
        **kwargs,
    ) -> "QuantBTEndpoint":
        """
        Create the Phase 31B readable intrabar reference endpoint.

        This endpoint is the causal Python oracle for `intrabar_bracket_v1`.
        Strategy output can stay compact: pass a signed `signal`/`signal_col`
        where positive means long entry size, negative means short entry size,
        and zero means no new entry. Optional stop, take-profit, trailing, and
        technical-exit arrays are supplied through `intent_cols` at run time.

        It is intentionally not the future Numba production kernel. Use it to
        verify SL/TP/trailing/reversal semantics and audit fill timing before
        promoting an alpha to the fast intrabar backend.
        """
        metadata = dict(kwargs.pop("metadata", {}))
        mode_value = level_mode.value if hasattr(level_mode, "value") else str(level_mode)
        metadata.setdefault("intrabar_level_mode", mode_value)
        metadata.setdefault("intrabar_sizing_mode", IntrabarSizingMode(intrabar_sizing_mode).value)
        metadata.setdefault("execution_contract_id", "intrabar_bracket_v1")
        contract = execution_contract or ExecutionContract.intrabar_bracket(close_on_last_bar=close_on_last_bar)
        metadata.setdefault("execution_contract", contract.to_metadata())
        if session_policy is not None:
            metadata["session_policy"] = session_policy.to_metadata()
        return cls(
            _config_from_kwargs(
                mode="intrabar_bracket_reference",
                backend="intrabar_reference",
                sizing="intrabar_intent",
                metadata=metadata,
                **kwargs,
            )
        )

    @classmethod
    def intrabar_bracket(
        cls,
        *,
        level_mode: Union[str, IntrabarLevelMode] = IntrabarLevelMode.PERCENT_DISTANCE,
        intrabar_sizing_mode: Union[str, IntrabarSizingMode] = IntrabarSizingMode.UNITS,
        close_on_last_bar: bool = True,
        execution_contract: Optional[ExecutionContract] = None,
        session_policy: Optional[SessionExecutionPolicy] = None,
        report_level: str = "standard",
        **kwargs,
    ) -> "QuantBTEndpoint":
        """
        Create the Phase 31C fast Numba intrabar bracket endpoint.

        Use the same compact input contract as
        `intrabar_bracket_reference(...)`. `report_level="minimal"` is meant
        for optimizers, `standard` returns diagnostics, and `audit` runs a
        deterministic second pass to materialize exact sparse fills.
        """
        metadata = dict(kwargs.pop("metadata", {}))
        mode_value = level_mode.value if hasattr(level_mode, "value") else str(level_mode)
        metadata.setdefault("intrabar_level_mode", mode_value)
        metadata.setdefault("intrabar_sizing_mode", IntrabarSizingMode(intrabar_sizing_mode).value)
        metadata.setdefault("execution_contract_id", "intrabar_bracket_v1")
        contract = execution_contract or ExecutionContract.intrabar_bracket(close_on_last_bar=close_on_last_bar)
        metadata.setdefault("execution_contract", contract.to_metadata())
        if session_policy is not None:
            metadata["session_policy"] = session_policy.to_metadata()
        return cls(
            _config_from_kwargs(
                mode="intrabar_bracket",
                backend="native_intrabar",
                sizing="intrabar_intent",
                report_level=report_level,
                metadata=metadata,
                **kwargs,
            )
        )

    @classmethod
    def fill_replay(cls, *, report_level: str = "audit", **kwargs) -> "QuantBTEndpoint":
        """
        Create a fast accounting replay endpoint for explicit fills.

        Use `backtest(data=df, fill_replay=FillReplayTape_or_DataFrame)`. This
        certifies accounting from supplied fills but does not certify how those
        fills were generated.
        """
        metadata = dict(kwargs.pop("metadata", {}))
        metadata.setdefault("execution_contract_id", "fill_replay_v1")
        metadata.setdefault("execution_contract", ExecutionContract.fill_replay().to_metadata())
        return cls(
            _config_from_kwargs(
                mode="fill_replay",
                backend="native_intrabar",
                sizing="explicit_fills",
                report_level=report_level,
                metadata=metadata,
                **kwargs,
            )
        )

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
    def orders(cls, backend: str = "native_event", **kwargs) -> "QuantBTEndpoint":
        """
        Create an explicit order simulation endpoint.

        Use `simulate(data=df, orders=[OrderIntent(...), ...])`. Orders are run
        through the selected event backend with market/limit fill lifecycle, TIF
        handling, fees, margin checks, and fills in `result.fills`.
        """
        return cls(_config_from_kwargs(mode="orders", backend=backend, **kwargs))

    @classmethod
    def native_event_lifecycle(cls, **kwargs) -> "QuantBTEndpoint":
        """
        Create an explicit native-event v2 lifecycle endpoint.

        Use `simulate(..., order_commands=[OrderCommand(...), ...])` for
        cancel/replace/amend/OCO/parent/stop/GTD lifecycle simulations. Passing
        legacy `orders=[OrderIntent(...)]` is also accepted and converted to
        immediate PLACE commands.
        """
        return cls(
            _config_from_kwargs(
                mode="orders",
                backend="native_event",
                event_engine_version="v2",
                **kwargs,
            )
        )

    @classmethod
    def native_event_strategy(cls, **kwargs) -> "QuantBTEndpoint":
        """
        Create a reactive native-event v2 strategy endpoint.

        Use `simulate(data=df, strategy=obj)` where `obj` optionally implements
        `initialize(context)`, `on_bar_close(context)`, and `finalize(context)`.
        Commands emitted by callbacks become effective from the next bar.
        """
        return cls(
            _config_from_kwargs(
                mode="native_event_strategy",
                backend="native_event",
                event_engine_version="v2",
                **kwargs,
            )
        )

    @classmethod
    def options(
        cls,
        backend: str = "native_option",
        *,
        option_config: Optional[NativeOptionConfig] = None,
        option_execution: Optional[OptionExecutionConfig] = None,
        option_margin: Optional[OptionMarginConfig] = None,
        fee_schedule: Optional[OptionFeeSchedule] = None,
        reporting_currency: str = "USD",
        initial_balances: Optional[Dict[str, float]] = None,
        conversion_rates: Optional[Dict[str, float]] = None,
        settle_expired: bool = False,
        max_spread_bps: Optional[float] = None,
        max_source_latency_ns: Optional[int] = None,
        **kwargs,
    ) -> "QuantBTEndpoint":
        """
        Create a native option simulation endpoint.

        Strategy/template code supplies canonical option-chain rows,
        `OptionInstrumentSpec` definitions, and `OptionPackageIntent` packages
        to `backtest(...)` or `simulate(...)`. The endpoint routes packages
        through snapshot-level option execution, applies fills to the
        multi-currency option ledger, calculates margin, and returns an
        `OptionBacktestResult` with fills/packages/cash/marks/Greeks/settlement
        artifacts.

        Required `backtest()` inputs:
        `chain`, `instruments`, and optional `packages`.
        """
        if backend.lower().strip() != "native_option":
            raise ValueError("options endpoint currently supports backend='native_option' only")
        metadata = dict(kwargs.pop("metadata", {}))
        metadata.setdefault("mode_family", "options")
        endpoint_config = _config_from_kwargs(mode="options", backend=backend, metadata=metadata, **kwargs)
        if option_config is None:
            option_config = NativeOptionConfig(
                account=endpoint_config.account,
                execution=endpoint_config.execution,
                option_execution=option_execution
                or OptionExecutionConfig(fee_rate=endpoint_config.v2_fee_rate, metadata={"source": "QuantBTEndpoint.options"}),
                margin=option_margin or OptionMarginConfig(),
                fee_schedule=fee_schedule,
                reporting_currency=reporting_currency,
                initial_balances=initial_balances,
                conversion_rates=dict(conversion_rates or {}),
                settle_expired=settle_expired,
                max_spread_bps=max_spread_bps,
                max_source_latency_ns=max_source_latency_ns,
                metadata=metadata,
            )
        endpoint_config = replace(endpoint_config, option_config=option_config)
        return cls(endpoint_config)

    @classmethod
    def nautilus_dca_grid(cls, spec: Optional[DcaGridSpec] = None, **kwargs) -> "QuantBTEndpoint":
        """
        Create a Nautilus DCA/grid structured-order validation endpoint.

        The endpoint compiles a `DcaGridSpec` into explicit orders:
        base market entry, safety limit orders, and optional reduce-only
        TP/SL exits. The resulting orders are replayed by Nautilus through the
        same package-order adapter as `orders(backend="nautilus")`.
        """
        if spec is None:
            spec = DcaGridSpec(**_pop_dataclass_kwargs(kwargs, DcaGridSpec))
        return cls(
            _config_from_kwargs(
                mode="nautilus_dca_grid",
                backend="nautilus",
                structured_order_spec=spec,
                symbols=[spec.symbol],
                **kwargs,
            )
        )

    @classmethod
    def nautilus_bracket_orders(cls, spec: Optional[BracketOrderSpec] = None, **kwargs) -> "QuantBTEndpoint":
        """
        Create a Nautilus bracket/OCO structured-order validation endpoint.

        The endpoint compiles a `BracketOrderSpec` into entry plus linked
        reduce-only take-profit and/or stop-loss exits. OCO group metadata is
        preserved and Nautilus cancels sibling exit orders on first exit fill.
        """
        if spec is None:
            spec = BracketOrderSpec(**_pop_dataclass_kwargs(kwargs, BracketOrderSpec))
        return cls(
            _config_from_kwargs(
                mode="nautilus_bracket_orders",
                backend="nautilus",
                structured_order_spec=spec,
                symbols=[spec.symbol],
                **kwargs,
            )
        )

    @classmethod
    def native_event_dca_grid(cls, spec: Optional[DcaGridSpec] = None, **kwargs) -> "QuantBTEndpoint":
        """
        Create a native-event v2 DCA/grid lifecycle endpoint.

        The structured package is compiled into `OrderCommand` records so base,
        safety orders, reduce-only exits, and OCO metadata are audited in
        `command_report` and `order_events`.
        """
        if spec is None:
            spec = DcaGridSpec(**_pop_dataclass_kwargs(kwargs, DcaGridSpec))
        return cls(
            _config_from_kwargs(
                mode="native_event_dca_grid",
                backend="native_event",
                event_engine_version="v2",
                structured_order_spec=spec,
                symbols=[spec.symbol],
                **kwargs,
            )
        )

    @classmethod
    def native_event_bracket_orders(cls, spec: Optional[BracketOrderSpec] = None, **kwargs) -> "QuantBTEndpoint":
        """
        Create a native-event v2 bracket/OCO lifecycle endpoint.

        Entry, take-profit, and stop-loss legs are linked through parent/OCO
        command fields and simulated by the deterministic OHLC lifecycle kernel.
        """
        if spec is None:
            spec = BracketOrderSpec(**_pop_dataclass_kwargs(kwargs, BracketOrderSpec))
        return cls(
            _config_from_kwargs(
                mode="native_event_bracket_orders",
                backend="native_event",
                event_engine_version="v2",
                structured_order_spec=spec,
                symbols=[spec.symbol],
                **kwargs,
            )
        )

    @classmethod
    def basket(cls, basket: Optional[BasketSpec] = None, backend: str = "native_event", **kwargs) -> "QuantBTEndpoint":
        """
        Create a basket/pair endpoint.

        Use for pair trades and frozen hedge-ratio baskets. Provide a
        `BasketSpec` either here or to `simulate(..., basket=...)`, then pass a
        scalar entry/exit signal and per-symbol price data.
        """
        return cls(_config_from_kwargs(mode="basket", backend=backend, basket=basket, **kwargs))

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
                "status": "specialized_route",
                "backends": "native_option",
                "route": "QuantBTEndpoint.options(...) with OptionPackageIntent and Greeks reports",
                "sizing": "option package quantities; Greeks-aware risk belongs to option route",
            },
        }

    @staticmethod
    def options_support_matrix() -> Dict[str, Dict[str, str]]:
        """
        Return the native option endpoint support matrix.

        `supported` means the Phase 7 endpoint can execute the workflow through
        current native option components. `future` means the public schema is
        intentionally reserved but should wait for later phases.
        """
        return {
            "canonical_chain_tape": {
                "status": "supported",
                "backend": "native_option",
                "route": "prepare_option_tape",
                "notes": "long-form option chain with bid/ask/mark/IV/Greeks columns",
            },
            "option_packages": {
                "status": "supported",
                "backend": "native_option",
                "route": "execute_option_package -> OptionLedger",
                "notes": "atomic_all_or_none, best_effort, sequential, hedge_after_primary, rebalance_only",
            },
            "multi_currency_ledger": {
                "status": "supported",
                "backend": "native_option",
                "route": "OptionLedger",
                "notes": "premium cash, fees, realized PnL, settlement cashflow and marked equity",
            },
            "margin": {
                "status": "supported_approx",
                "backend": "native_option",
                "route": "calculate_option_margin",
                "notes": "venue-exact margin requires external validator or later Nautilus/venue adapter",
            },
            "OptionsVolArbSpec": {
                "status": "specialized_route",
                "backend": "native_option",
                "route": "strategy/template emits option packages; endpoint returns Greeks and attribution reports",
                "notes": "not executable through generic arbitrage package route",
            },
            "nautilus_options": {
                "status": "experimental",
                "backend": "nautilus",
                "route": "quantbt.adapters.nautilus.options.validate_option_packages_with_nautilus",
                "notes": "Phase 9 pins Nautilus option constructors and BBO quote semantics; full Nautilus option engine replay remains future",
            },
        }

    @staticmethod
    def nautilus_support_matrix() -> Dict[str, Dict[str, str]]:
        """
        Return the public Nautilus adapter support matrix.

        `supported` means the route is executable through current QuantBT
        endpoints. `planned` means the endpoint contract is reserved in the
        roadmap but runtime execution should not be used yet. `experimental`
        means the route exists for controlled validation, usually with a
        narrower instrument/order scope than native engines.
        """
        return {
            "signal_series": {
                "status": "supported",
                "endpoint": "QuantBTEndpoint.nautilus_validation(...)",
                "scope": "single-symbol target signal replay",
                "order_types": "market delta orders generated by adapter",
                "notes": "supports signal_notional, notional, unit, and %_equity sizing",
            },
            "explicit_orders": {
                "status": "supported",
                "endpoint": "QuantBTEndpoint.orders(backend='nautilus', ...)",
                "scope": "single-symbol OrderIntent replay",
                "order_types": "market, limit, stop_market, stop_limit",
                "notes": "preserves TIF, reduce_only, tags, price and trigger_price where Nautilus supports them",
            },
            "lifecycle_commands": {
                "status": "supported_native_event_adapter_aligned",
                "endpoint": "QuantBTEndpoint.native_event_lifecycle(...) or QuantBTEndpoint.orders(event_engine_version='v2', ...)",
                "scope": "native-event v2 command lifecycle; Nautilus package adapter accepts executable PLACE/REPLACE payloads",
                "order_types": "market, limit, stop_market, stop_limit plus cancel/replace/amend/cancel_all in native-event v2",
                "notes": "Nautilus command path is payload-aligned, not exchange-native cancel/amend parity yet",
            },
            "reactive_strategy": {
                "status": "supported_native_event_mvp",
                "endpoint": "QuantBTEndpoint.native_event_strategy(...)",
                "scope": "on_bar_close strategy callbacks emitting next-bar OrderCommand objects",
                "order_types": "native-event v2 lifecycle commands",
                "notes": "Phase 30D replay-backed MVP with captured command tape and static replay parity; incremental session is Phase 30E",
            },
            "dca_grid": {
                "status": "experimental",
                "endpoint": "QuantBTEndpoint.nautilus_dca_grid(...)",
                "scope": "base order, safety limit orders, TP/SL package",
                "order_types": "market, limit, bracket/OCO exits",
                "notes": "Phase 5.2C; compiles to explicit OrderIntent packages for Nautilus validation",
            },
            "bracket_oco": {
                "status": "experimental",
                "endpoint": "QuantBTEndpoint.nautilus_bracket_orders(...)",
                "scope": "entry plus linked stop-loss/take-profit exits",
                "order_types": "bracket/OCO package",
                "notes": "Phase 5.2C; sibling cancellation is handled by the Nautilus package strategy",
            },
            "basket_pair": {
                "status": "experimental",
                "endpoint": "QuantBTEndpoint.basket(backend='nautilus', ...)",
                "scope": "multi-leg frozen hedge-ratio packages",
                "order_types": "per-leg explicit market/limit orders",
                "notes": "Phase 5.2D; compiles BasketSpec signals into Nautilus package orders",
            },
            "multi_symbol_portfolio": {
                "status": "experimental",
                "endpoint": "QuantBTEndpoint.portfolio(backend='nautilus', ...)",
                "scope": "position-matrix transitions across one Nautilus venue/account",
                "order_types": "per-symbol target delta orders",
                "notes": "Phase 5.2D; supports pre-scalable signal_notional/notional/unit modes",
            },
            "arbitrage_package_orders": {
                "status": "experimental",
                "endpoint": "QuantBTEndpoint.arbitrage(..., backend='nautilus')",
                "scope": "basis/stat-arb package validation",
                "order_types": "package market orders",
                "notes": "supported for selected arbitrage specs; not a general basket endpoint yet",
            },
            "parity_audit": {
                "status": "supported",
                "endpoint": "build_native_nautilus_parity_report(native, nautilus)",
                "scope": "native-vs-Nautilus order/fill/equity comparison",
                "order_types": "reporting helper",
                "notes": "row-level audit exists; summary artifacts live in report bundle and tests",
            },
        }

    @classmethod
    def portfolio(cls, portfolio_mode: str = "longshort", backend: str = "native_portfolio", **kwargs) -> "QuantBTEndpoint":
        """
        Create a multi-symbol portfolio endpoint.

        Use `backtest(positions=positions_df, data=data_dict)` where
        `positions_df.columns` are symbols and `data_dict[symbol]` is an OHLCV
        DataFrame. The endpoint wraps `PortfolioBacktestEngine`.
        """
        return cls(_config_from_kwargs(mode="portfolio", backend=backend, portfolio_mode=portfolio_mode, **kwargs))

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
        Supported optimization modes are `mode_1_decay`, `mode_2_sbb`,
        `mode_3_flat_minima`, `mode_4_is_only_robust`, and
        `mode_5_full_robust`.
        Fixed-parameter runs can leave
        `optimization_mode="none"` and pass `params=...` to `backtest()`.
        """
        optimization_config = dict(optimization_config or {})
        wf_config = kwargs.pop("walkforward_config", None)
        scoring_backend = str(
            optimization_config.get(
                "scoring_backend",
                _default_walkforward_scoring_backend(target_mode=target_mode, optimization_mode=optimization_mode),
            )
        )
        wf_metadata = dict(optimization_config.get("metadata", {}) or {})
        wf_metadata.setdefault("use_prepared_scoring_cache", bool(optimization_config.get("use_prepared_scoring_cache", True)))
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
                candidate_selection_metric=str(
                    optimization_config.get(
                        "candidate_selection_metric",
                        (
                            "is_only_robust"
                            if str(optimization_mode).lower().strip() == "mode_4_is_only_robust"
                            else (
                                "full_robust"
                                if str(optimization_mode).lower().strip() == "mode_5_full_robust"
                                else "robust_decay"
                            )
                        ),
                    )
                ),
                candidate_decay_lambda=optimization_config.get("candidate_decay_lambda"),
                candidate_decay_gamma=optimization_config.get("candidate_decay_gamma"),
                sbb_samples=int(optimization_config.get("sbb_samples", 256)),
                sbb_block_length=int(optimization_config.get("sbb_block_length", 20)),
                sbb_decay_lambda=float(optimization_config.get("sbb_decay_lambda", 0.5)),
                sbb_std_penalty=float(optimization_config.get("sbb_std_penalty", 0.1)),
                sbb_simulation=str(optimization_config.get("sbb_simulation", "stationary")),
                regime_count=int(optimization_config.get("regime_count", 3)),
                regime_lookback=int(optimization_config.get("regime_lookback", 20)),
                regime_weights=optimization_config.get("regime_weights"),
                stress_vol_multiplier=float(optimization_config.get("stress_vol_multiplier", 1.0)),
                garch_p=int(optimization_config.get("garch_p", 1)),
                garch_q=int(optimization_config.get("garch_q", 1)),
                garch_dist=str(optimization_config.get("garch_dist", "t")),
                garch_vol_multiplier=float(optimization_config.get("garch_vol_multiplier", 1.0)),
                flat_top_fraction=float(optimization_config.get("flat_top_fraction", 0.1)),
                flat_eps=float(optimization_config.get("flat_eps", 0.15)),
                flat_min_samples=int(optimization_config.get("flat_min_samples", 3)),
                flat_selector=str(optimization_config.get("flat_selector", "medoid")),
                plateau_quantile=float(optimization_config.get("plateau_quantile", 0.25)),
                plateau_median_weight=float(optimization_config.get("plateau_median_weight", 0.25)),
                plateau_std_penalty=float(optimization_config.get("plateau_std_penalty", 0.50)),
                plateau_size_bonus=float(optimization_config.get("plateau_size_bonus", 0.01)),
                is_subperiods=int(optimization_config.get("is_subperiods", 6)),
                q25_weight=float(optimization_config.get("q25_weight", 0.30)),
                dispersion_penalty=float(optimization_config.get("dispersion_penalty", 0.50)),
                temporal_weight=float(optimization_config.get("temporal_weight", 0.65)),
                plateau_weight=float(optimization_config.get("plateau_weight", 0.35)),
                use_bootstrap_penalty=bool(optimization_config.get("use_bootstrap_penalty", False)),
                use_complexity_penalty=bool(optimization_config.get("use_complexity_penalty", False)),
                scoring_backend=scoring_backend,
                scoring_trading_days=int(optimization_config.get("scoring_trading_days", 365)),
                min_trades_per_year=optimization_config.get("min_trades_per_year"),
                trade_penalty_factor=optimization_config.get("trade_penalty_factor"),
                use_numba=bool(optimization_config.get("use_numba", True)),
                metadata=wf_metadata,
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

    @classmethod
    def train_test_split(
        cls,
        strategy_class,
        test_start: Union[str, int, pd.Timestamp],
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
        Create a single holdout train/test endpoint.

        This is a convenience wrapper around `walk_forward(...)` with
        `split_frequency="single"`. The strategy is optimized on the train
        segment before `test_start`, emits OOS output on the holdout segment,
        then the stitched holdout signal is routed into the selected QuantBT
        target mode. `optimization_mode` accepts the same values as
        walk-forward: `none`, `mode_1_decay`, `mode_2_sbb`,
        `mode_3_flat_minima`, `mode_4_is_only_robust`, and
        `mode_5_full_robust`.
        """
        return cls.walk_forward(
            strategy_class=strategy_class,
            split_mode=test_start,
            split_frequency="single",
            target_mode=target_mode,
            window_mode=window_mode,
            train_window=train_window,
            optimization_mode=optimization_mode,
            optimization_config=optimization_config,
            optuna_trials=optuna_trials,
            optuna_early_stopping=optuna_early_stopping,
            random_seed=random_seed,
            **kwargs,
        )

    def backtest(
        self,
        data=None,
        signal: Optional[pd.Series] = None,
        signal_col: Optional[str] = None,
        positions: Optional[Union[pd.DataFrame, SeriesMap]] = None,
        orders: Optional[Sequence[OrderIntent]] = None,
        order_commands: Optional[Sequence[OrderCommand]] = None,
        strategy=None,
        basket: Optional[BasketSpec] = None,
        closes: Optional[SeriesMap] = None,
        highs: Optional[SeriesMap] = None,
        lows: Optional[SeriesMap] = None,
        hedge_ratios: Optional[SeriesMap] = None,
        datetime_index: Optional[Union[pd.DatetimeIndex, pd.Series]] = None,
        symbols: Optional[Sequence[str]] = None,
        params: Optional[Dict] = None,
        param_ranges: Optional[Dict] = None,
        chain: Optional[pd.DataFrame] = None,
        instruments: Optional[Union[OptionInstrumentRegistry, Sequence[OptionInstrumentSpec], Dict[str, OptionInstrumentSpec]]] = None,
        packages: Optional[Sequence[OptionPackageIntent]] = None,
        strategy_run: Optional[OptionStrategyRun] = None,
        intent: Optional[IntrabarIntentTape] = None,
        intent_cols: Optional[Dict[str, str]] = None,
        session_tape: Optional[IntrabarSessionTape] = None,
        funding_event_timestamps=None,
        funding_event_rates=None,
        fill_replay: Optional[Union[FillReplayTape, pd.DataFrame]] = None,
        underlying: Optional[Union[pd.DataFrame, pd.Series]] = None,
        hedge_policy: Optional[OptionHedgeConfig] = None,
        net_option_delta: Optional[pd.Series] = None,
        settlement_events: Optional[Sequence] = None,
        conversion_rates: Optional[Dict[str, float]] = None,
        prepared_cache: Optional[OptionPreparedRunCache] = None,
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
        if mode == "options":
            return self._run_options(
                chain=chain if chain is not None else data,
                instruments=instruments,
                packages=packages,
                strategy_run=strategy_run,
                underlying=underlying,
                hedge_policy=hedge_policy,
                net_option_delta=net_option_delta,
                settlement_events=settlement_events,
                conversion_rates=conversion_rates,
                prepared_cache=prepared_cache,
            )
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
        if mode == "intrabar_bracket_reference":
            return self._run_intrabar_bracket_reference(
                data=data,
                signal=signal,
                signal_col=signal_col,
                datetime_index=datetime_index,
                symbols=symbols,
                intent=intent,
                intent_cols=intent_cols,
                session_tape=session_tape,
                funding_event_timestamps=funding_event_timestamps,
                funding_event_rates=funding_event_rates,
            )
        if mode == "intrabar_bracket":
            return self._run_intrabar_bracket_fast(
                data=data,
                signal=signal,
                signal_col=signal_col,
                datetime_index=datetime_index,
                symbols=symbols,
                intent=intent,
                intent_cols=intent_cols,
                session_tape=session_tape,
                funding_event_timestamps=funding_event_timestamps,
                funding_event_rates=funding_event_rates,
            )
        if mode == "fill_replay":
            return self._run_fill_replay(
                data=data,
                datetime_index=datetime_index,
                symbols=symbols,
                fill_replay=fill_replay,
            )
        if mode in ("single_signal", "pct_equity", "signal_notional", "dca_ladder", "nautilus_validation"):
            return self._run_single(data=data, signal=signal, signal_col=signal_col, datetime_index=datetime_index, symbols=symbols)
        if mode == "orders":
            return self._run_orders(
                data=data,
                orders=orders,
                order_commands=order_commands,
                datetime_index=datetime_index,
                symbols=symbols,
            )
        if mode == "native_event_strategy":
            return self._run_native_event_strategy(
                data=data,
                strategy=strategy,
                datetime_index=datetime_index,
                symbols=symbols,
            )
        if mode in ("nautilus_dca_grid", "nautilus_bracket_orders", "native_event_dca_grid", "native_event_bracket_orders"):
            return self._run_structured_orders(data=data, datetime_index=datetime_index, symbols=symbols)
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

    def simulate(
        self,
        *args,
        show_order_logs: bool = False,
        order_log_mode: str = "fills_only",
        order_log_limit: int = 500,
        **kwargs,
    ):
        """
        Alias for `backtest()` used by order, basket, and Nautilus workflows.

        Services can call `simulate()` when the input is closer to an execution
        simulation than a pure signal backtest. The routing and return contract
        are identical to `backtest()`.
        """
        result = self.backtest(*args, **kwargs)
        if show_order_logs:
            _print_order_logs(result, mode=order_log_mode, limit=order_log_limit)
        return result

    def full_report(self, trading_days: int = 365, scope: str = "auto") -> Dict:
        """
        Return the full QuantBT metrics dictionary for the latest result.

        Parameters
        ----------
        trading_days:
            Annualization calendar. Use 365 for crypto and 252 for equities.
        scope:
            `auto` uses the natural reporting scope for the endpoint. For
            walk-forward and train/test split runs this means OOS/test bars
            only; other endpoints use the full result. Pass `full` to audit the
            complete stitched timeline, or `test`/`oos` to force OOS reporting.

        Raises
        ------
        RuntimeError
            If no backtest has been run yet.
        """
        return _full_report(self._result_for_report_scope(scope), trading_days=trading_days)

    def show_metrics(self, trading_days: int = 365, scope: str = "auto") -> Dict:
        """
        Print key metrics and return the full metrics dictionary.

        This intentionally mirrors the convenience style of legacy
        `BacktestEngine.analyze()` without forcing a plot.
        """
        rpt = self.full_report(trading_days=trading_days, scope=scope)
        print(format_metrics_report(rpt))
        return rpt

    def quick_plot(self, theme: str = "dark", figsize: tuple = (14, 6), scope: str = "auto"):
        """
        Plot cumulative return and drawdown for the latest result.
        """
        return _quick_plot(self._require_result(), theme=theme, figsize=figsize, scope=scope)

    def tearsheet(self, theme: str = "dark", benchmark=None, scope: str = "auto"):
        """
        Render the full QuantBT tearsheet for the latest result.
        """
        return _tearsheet(self._require_result(), theme=theme, benchmark=benchmark, scope=scope)

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

    def nautilus_pct_equity_diagnostic(
        self,
        *,
        data,
        signal=None,
        signal_col: Optional[str] = None,
        native_fee_round_trip: Optional[float] = None,
        native_fee_one_way: Optional[float] = None,
        native_use_funding: Optional[bool] = None,
        native_slippage: Optional[float] = None,
    ) -> Dict:
        """
        Diagnose why a Nautilus `%_equity` validation run differs from native.

        This helper reports signal transition count, Nautilus order/fill count,
        fee/slippage/funding semantic differences, and exchange lot-size
        constraints. It is diagnostic-only and does not mutate the result.
        """
        from .reporting import build_nautilus_pct_equity_diagnostic

        frame, _, sig = _normalize_single_data(
            data=data,
            signal=signal,
            signal_col=signal_col,
            datetime_index=None,
        )
        return build_nautilus_pct_equity_diagnostic(
            self._require_result(),
            data=frame,
            signal=sig,
            native_fee_round_trip=native_fee_round_trip,
            native_fee_one_way=native_fee_one_way,
            native_use_funding=native_use_funding,
            native_slippage=native_slippage,
        )

    def _run_options(
        self,
        chain,
        instruments,
        packages,
        strategy_run,
        underlying,
        hedge_policy,
        net_option_delta,
        settlement_events,
        conversion_rates,
        prepared_cache,
    ):
        if chain is None:
            raise ValueError("options endpoint requires chain=option_chain_dataframe or data=option_chain_dataframe")
        if instruments is None:
            instruments = self.config.instruments
        if instruments is None:
            raise ValueError("options endpoint requires instruments=OptionInstrumentRegistry/list/mapping")
        config = self.config.option_config
        if config is None:
            config = NativeOptionConfig(
                account=self.config.account,
                execution=self.config.execution,
                option_execution=OptionExecutionConfig(fee_rate=self.config.v2_fee_rate),
                margin=OptionMarginConfig(),
                metadata=dict(self.config.metadata),
            )
        self.engine = OptionBacktestEngine(
            chain=chain,
            instruments=instruments,
            packages=packages or (),
            strategy_run=strategy_run,
            underlying=underlying,
            hedge_policy=hedge_policy,
            net_option_delta=net_option_delta,
            config=config,
            settlement_events=settlement_events or (),
            conversion_rates=conversion_rates,
            prepared_cache=prepared_cache,
        )
        self._store_result(self.engine.result)
        return self.result

    def _run_intrabar_bracket_reference(self, data, signal, signal_col, datetime_index, symbols, intent, intent_cols, session_tape=None, funding_event_timestamps=None, funding_event_rates=None):
        tape, intent, symbol = self._prepare_intrabar_run(data, signal, signal_col, datetime_index, symbols, intent, intent_cols, funding_event_timestamps, funding_event_rates)
        contract = _execution_contract_from_config(self.config)
        session_policy = _session_policy_from_config(self.config)
        if session_policy is not None and session_tape is None:
            raise ValueError("session_tape is required when session_policy is configured")
        oracle = run_intrabar_reference(
            tape=tape,
            intent=intent,
            account=self.config.account,
            contract=contract,
            fee_rate=self.config.v2_fee_rate,
            slippage_rate=float(self.config.execution.slippage_rate),
            contract_size=_scalar_for_symbol(self.config.contract_size, symbol),
            session_policy=session_policy,
            session_tape=session_tape,
            **self._intrabar_execution_kwargs(symbol),
        )
        idx = oracle.equity.index
        returns = oracle.equity.pct_change().replace([np.inf, -np.inf], np.nan).fillna(0.0)
        diagnostics = pd.DataFrame(
            {
                "average_entry": oracle.average_entry,
                "active_stop": oracle.active_stop,
                "active_take_profit": oracle.active_take_profit,
                "event_flags": oracle.event_flags,
                "fees": oracle.fees,
                "funding": oracle.funding,
            },
            index=idx,
        )
        metadata = {
            **oracle.metadata,
            "backend": "intrabar_reference",
            "backend_alias": "intrabar_bracket_reference",
            "engine_id": "intrabar_reference_v1",
            "input_mode": "intrabar_intent",
            "symbol": symbol,
            "validation_certificate": asdict(tape.validation_certificate),
            "strict_market_tape": True,
            "phase": "31B_python_reference_oracle",
            "fills_report": _intrabar_fills_to_frame(oracle.fills),
            "positions_report": pd.DataFrame({f"Position_{symbol}": oracle.position}, index=idx),
        }
        result = BacktestResultV2(
            equity=oracle.equity,
            returns=returns,
            positions=pd.DataFrame({f"Position_{symbol}": oracle.position.to_numpy(dtype=float)}, index=idx),
            closes=pd.DataFrame({f"Close_{symbol}": tape.closes[:, 0]}, index=idx),
            symbols=[symbol],
            initial_capital=float(self.config.account.initial_capital),
            leverage=float(self.config.account.leverage),
            fills=oracle.fills,
            fees=oracle.fees,
            funding=oracle.funding,
            diagnostics=diagnostics,
            metadata=metadata,
        )
        self.engine = oracle
        self._store_result(result)
        return self.result

    def _run_intrabar_bracket_fast(self, data, signal, signal_col, datetime_index, symbols, intent, intent_cols, session_tape=None, funding_event_timestamps=None, funding_event_rates=None):
        tape, intent, symbol = self._prepare_intrabar_run(data, signal, signal_col, datetime_index, symbols, intent, intent_cols, funding_event_timestamps, funding_event_rates)
        contract = _execution_contract_from_config(self.config)
        session_policy = _session_policy_from_config(self.config)
        if session_policy is not None and session_tape is None:
            raise ValueError("session_tape is required when session_policy is configured")
        if session_policy is None and session_tape is not None:
            raise ValueError("session_policy is required when session_tape is supplied")
        kwargs = {
            "tape": tape,
            "intent": intent,
            "account": self.config.account,
            "contract": contract,
            "fee_rate": self.config.v2_fee_rate,
            "slippage_rate": float(self.config.execution.slippage_rate),
            "contract_size": _scalar_for_symbol(self.config.contract_size, symbol),
            **self._intrabar_execution_kwargs(symbol),
            "report_level": self.config.report_level,
        }
        if session_policy is not None:
            kernel = run_intrabar_session_kernel(
                **kwargs,
                session_policy=session_policy,
                session_tape=session_tape,
            )
        else:
            kernel = run_intrabar_kernel(**kwargs)
        idx = kernel.equity.index
        returns = kernel.equity.pct_change().replace([np.inf, -np.inf], np.nan).fillna(0.0)
        diagnostics = pd.DataFrame(
            {
                "average_entry": kernel.average_entry,
                "active_stop": kernel.active_stop,
                "active_take_profit": kernel.active_take_profit,
                "event_flags": kernel.event_flags,
                "initial_margin": kernel.initial_margin,
                "maintenance_margin": kernel.maintenance_margin,
                "fees": kernel.fees,
                "funding": kernel.funding,
            },
            index=idx,
        )
        metadata = {
            **kernel.metadata,
            "input_mode": "intrabar_intent",
            "symbol": symbol,
            "phase": "31C_numba_intrabar_kernel",
            "fills_report": kernel.fills_report,
            "positions_report": pd.DataFrame({f"Position_{symbol}": kernel.position}, index=idx),
        }
        result = BacktestResultV2(
            equity=kernel.equity,
            returns=returns,
            positions=pd.DataFrame({f"Position_{symbol}": kernel.position.to_numpy(dtype=float)}, index=idx),
            closes=pd.DataFrame({f"Close_{symbol}": tape.closes[:, 0]}, index=idx),
            symbols=[symbol],
            initial_capital=float(self.config.account.initial_capital),
            leverage=float(self.config.account.leverage),
            liquidated=bool(kernel.liquidated),
            liquidation_bar=int(kernel.liquidation_bar),
            fills=kernel.fills,
            fees=kernel.fees,
            funding=kernel.funding,
            margin=diagnostics[["initial_margin", "maintenance_margin"]],
            diagnostics=diagnostics,
            metadata=metadata,
        )
        self.engine = kernel
        self._store_result(result)
        return self.result

    def _run_fill_replay(self, data, datetime_index, symbols, fill_replay):
        if fill_replay is None:
            raise ValueError("fill_replay endpoint requires fill_replay=FillReplayTape or DataFrame")
        symbol_list = list(symbols or self.config.symbols or ["DEFAULT"])
        if len(symbol_list) != 1:
            raise ValueError("fill_replay currently supports exactly one symbol")
        symbol = symbol_list[0]
        tape = prepare_market_tape(
            data=data,
            datetime_index=datetime_index,
            symbols=symbol_list,
            funding_rate=self.config.funding_rate,
            use_funding=False,
            validation_mode="strict",
            source_timezone=self.config.metadata.get("source_timezone"),
            bar_timestamp_semantics=str(self.config.metadata.get("bar_timestamp_semantics", "close")),
        )
        if isinstance(fill_replay, FillReplayTape):
            fill_tape = fill_replay
        elif isinstance(fill_replay, pd.DataFrame):
            fill_tape = FillReplayTape.from_frame(
                fill_replay,
                fee_rate=self.config.v2_fee_rate,
                contract_size=_scalar_for_symbol(self.config.contract_size, symbol),
            )
        else:
            raise TypeError("fill_replay must be a FillReplayTape or pandas DataFrame")
        replay = run_fill_replay_kernel(
            tape=tape,
            fill_tape=fill_tape,
            account=self.config.account,
            contract_size=_scalar_for_symbol(self.config.contract_size, symbol),
        )
        idx = replay.equity.index
        returns = replay.equity.pct_change().replace([np.inf, -np.inf], np.nan).fillna(0.0)
        metadata = {
            **replay.metadata,
            "symbol": symbol,
            "phase": "31C_fill_replay_kernel",
            "fills_report": fill_replay.copy() if isinstance(fill_replay, pd.DataFrame) else pd.DataFrame(),
        }
        result = BacktestResultV2(
            equity=replay.equity,
            returns=returns,
            positions=pd.DataFrame({f"Position_{symbol}": replay.position.to_numpy(dtype=float)}, index=idx),
            closes=pd.DataFrame({f"Close_{symbol}": tape.closes[:, 0]}, index=idx),
            symbols=[symbol],
            initial_capital=float(self.config.account.initial_capital),
            leverage=float(self.config.account.leverage),
            fees=replay.fees,
            diagnostics=pd.DataFrame({"event_flags": replay.event_flags, "fees": replay.fees}, index=idx),
            metadata=metadata,
        )
        self.engine = replay
        self._store_result(result)
        return self.result

    def _prepare_intrabar_run(self, data, signal, signal_col, datetime_index, symbols, intent, intent_cols, funding_event_timestamps=None, funding_event_rates=None):
        symbol_list = list(symbols or self.config.symbols or ["DEFAULT"])
        if len(symbol_list) != 1:
            raise ValueError(f"{self.config.mode} currently supports exactly one symbol")
        symbol = symbol_list[0]
        tape = prepare_market_tape(
            data=data,
            datetime_index=datetime_index,
            symbols=symbol_list,
            funding_rate=self.config.funding_rate,
            funding_event_timestamps=funding_event_timestamps,
            funding_event_rates=funding_event_rates,
            use_funding=self.config.use_funding,
            validation_mode="strict",
            missing_funding_policy=str(self.config.metadata.get("missing_funding_policy", "raise")),
            source_timezone=self.config.metadata.get("source_timezone"),
            bar_timestamp_semantics=str(self.config.metadata.get("bar_timestamp_semantics", "close")),
        )
        lookup_frame = None if isinstance(data, PreparedMarketTape) else _strict_lookup_frame(data, datetime_index, source_timezone=self.config.metadata.get("source_timezone"))
        if intent is None:
            level_mode = IntrabarLevelMode(str(self.config.metadata.get("intrabar_level_mode", IntrabarLevelMode.PERCENT_DISTANCE.value)))
            intent = _intrabar_intent_from_endpoint_input(
                frame=lookup_frame,
                index=pd.DatetimeIndex(pd.to_datetime(tape.timestamps_ns, utc=True)),
                signal=signal,
                signal_col=signal_col,
                intent_cols=intent_cols or {},
                level_mode=level_mode,
            )
        return tape, intent, symbol

    def _intrabar_execution_kwargs(self, symbol: str) -> Dict:
        constraints = build_quantity_constraints(
            [symbol],
            instruments=self.config.instruments,
            qty_step=self.config.qty_step,
            lot_size=self.config.lot_size,
            slot_size=self.config.slot_size,
            min_qty=self.config.min_qty,
            min_notional=self.config.min_notional,
        )
        sizing_mode = IntrabarSizingMode(str(self.config.metadata.get("intrabar_sizing_mode", IntrabarSizingMode.UNITS.value)))
        fixed_notional = float(self.config.metadata.get("fixed_notional", self.config.alloc_per_trade if not isinstance(self.config.alloc_per_trade, dict) else self.config.alloc_per_trade.get(symbol, 0.0)))
        equity_fraction = float(self.config.metadata.get("equity_fraction", self.config.alloc_per_trade if not isinstance(self.config.alloc_per_trade, dict) else self.config.alloc_per_trade.get(symbol, 0.0)))
        risk_fraction = float(self.config.metadata.get("risk_fraction", 0.0))
        return {
            "sizing_mode": sizing_mode,
            "fixed_notional": fixed_notional,
            "equity_fraction": equity_fraction,
            "risk_fraction": risk_fraction,
            "qty_step": float(constraints.qty_step[0]),
            "min_qty": float(constraints.min_qty[0]),
            "min_notional": float(constraints.min_notional[0]),
            "tick_size": _tick_size_for_symbol(self.config.instruments, symbol, self.config.metadata.get("tick_size", 0.0)),
        }

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
                instruments=self.config.instruments,
                qty_step=self.config.qty_step,
                lot_size=self.config.lot_size,
                slot_size=self.config.slot_size,
                min_qty=self.config.min_qty,
                min_notional=self.config.min_notional,
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
            instruments=self.config.instruments,
            qty_step=self.config.qty_step,
            lot_size=self.config.lot_size,
            slot_size=self.config.slot_size,
            min_qty=self.config.min_qty,
            min_notional=self.config.min_notional,
            report_level=self.config.report_level,
            audit_sink=self.config.audit_sink,
            audit_sink_path=self.config.audit_sink_path,
            reactive_kernel_mode=self.config.reactive_kernel_mode,
        )
        markers = _intrabar_marker_columns(frame)
        if backend == "native_vectorized" and markers:
            warnings.warn(
                "native_vectorized is close_target_v2 and does not certify intrabar SL/TP/trailing columns "
                f"{markers}; use a future intrabar/fill-replay/event backend for those semantics.",
                RuntimeWarning,
                stacklevel=2,
            )
            self.engine.result.metadata["intrabar_misuse_markers"] = markers
            self.engine.result.metadata["certification_status"] = "uncertified_intrabar_columns_on_close_target"
        self._store_result(self.engine.result)
        return self.result

    def _run_orders(self, data, orders, order_commands, datetime_index, symbols):
        if not orders and not order_commands:
            raise ValueError("orders endpoint requires orders=[OrderIntent(...)] or order_commands=[OrderCommand(...)]")
        frame, idx, _ = _normalize_single_data(data=data, signal=pd.Series(0.0, index=_infer_index(data, datetime_index)), signal_col=None, datetime_index=datetime_index)
        backend = _resolve_backend(self.config)
        event_version = str(self.config.event_engine_version).lower().strip()
        if order_commands is not None:
            event_version = "v2"
        self.engine = BacktestEngineV2(
            data=frame,
            symbols=list(symbols or self.config.symbols or ["asset"]),
            backend=backend,
            orders=orders,
            order_commands=order_commands,
            event_engine_version=event_version,
            account=self.config.account,
            execution=self.config.execution,
            fee_rate=self.config.v2_fee_rate,
            use_funding=self.config.use_funding,
            funding_rate=self.config.funding_rate,
            contract_size=self.config.contract_size,
            instruments=self.config.instruments,
            qty_step=self.config.qty_step,
            lot_size=self.config.lot_size,
            slot_size=self.config.slot_size,
            min_qty=self.config.min_qty,
            min_notional=self.config.min_notional,
            report_level=self.config.report_level,
            audit_sink=self.config.audit_sink,
            audit_sink_path=self.config.audit_sink_path,
            reactive_kernel_mode=self.config.reactive_kernel_mode,
        )
        self._store_result(self.engine.result)
        return self.result

    def _run_native_event_strategy(self, data, strategy, datetime_index, symbols):
        if strategy is None:
            raise ValueError("native_event_strategy endpoint requires strategy=...")
        frame, idx, _ = _normalize_single_data(
            data=data,
            signal=pd.Series(0.0, index=_infer_index(data, datetime_index)),
            signal_col=None,
            datetime_index=datetime_index,
        )
        symbol_list = list(symbols or self.config.symbols or ["asset"])
        self.engine = BacktestEngineV2(
            data=frame,
            symbols=symbol_list,
            backend="native_event",
            strategy=strategy,
            event_engine_version="v2",
            reactive_execution_mode=self.config.reactive_execution_mode,
            account=self.config.account,
            execution=self.config.execution,
            fee_rate=self.config.v2_fee_rate,
            use_funding=self.config.use_funding,
            funding_rate=self.config.funding_rate,
            contract_size=self.config.contract_size,
            instruments=self.config.instruments,
            qty_step=self.config.qty_step,
            lot_size=self.config.lot_size,
            slot_size=self.config.slot_size,
            min_qty=self.config.min_qty,
            min_notional=self.config.min_notional,
            report_level=self.config.report_level,
            audit_sink=self.config.audit_sink,
            audit_sink_path=self.config.audit_sink_path,
            reactive_kernel_mode=self.config.reactive_kernel_mode,
        )
        self._store_result(self.engine.result)
        return self.result

    def _run_structured_orders(self, data, datetime_index, symbols):
        spec = self.config.structured_order_spec
        if spec is None:
            raise ValueError(f"{self.config.mode} endpoint requires a structured order spec")
        frame = _standardize_frame(data, datetime_index=datetime_index)
        symbol_list = list(symbols or self.config.symbols or [spec.symbol])
        if spec.symbol not in symbol_list:
            symbol_list = [spec.symbol]
        if isinstance(spec, DcaGridSpec):
            plan = build_dca_grid_order_plan(spec, close=frame["close"])
        elif isinstance(spec, BracketOrderSpec):
            plan = build_bracket_order_plan(spec)
        else:
            raise TypeError(f"unsupported structured_order_spec={type(spec).__name__}")

        params = {
            "input_mode": plan.package_type,
            "structured_order_plan": plan,
            "structured_order_table": plan.order_table,
            "package_id": plan.package_id,
            "package_type": plan.package_type,
            "package_metadata": plan.metadata,
            "order_count_input": len(plan.orders),
        }
        backend = _resolve_backend(self.config)
        if backend == "native_event":
            commands = order_intents_to_lifecycle_commands(plan.orders)
            self.engine = BacktestEngineV2(
                data=frame,
                symbols=[spec.symbol],
                backend="native_event",
                order_commands=commands,
                event_engine_version="v2",
                account=self.config.account,
                execution=self.config.execution,
                fee_rate=self.config.v2_fee_rate,
                use_funding=self.config.use_funding,
                funding_rate=self.config.funding_rate,
                contract_size=self.config.contract_size,
                instruments=self.config.instruments,
                qty_step=self.config.qty_step,
                lot_size=self.config.lot_size,
                slot_size=self.config.slot_size,
                min_qty=self.config.min_qty,
                min_notional=self.config.min_notional,
                report_level=self.config.report_level,
                audit_sink=self.config.audit_sink,
                audit_sink_path=self.config.audit_sink_path,
            )
            result = self.engine.result
            result.metadata.update(
                {
                    **params,
                    "engine": f"event_v2_{plan.package_type}",
                    "lifecycle_command_count": len(commands),
                    "lifecycle_commands": commands,
                }
            )
        elif backend == "nautilus":
            result = self._run_nautilus_package_orders(
                data={spec.symbol: frame},
                orders=plan.orders,
                symbols=[spec.symbol],
                params=params,
            )
            result.metadata["engine"] = f"nautilus_{plan.package_type}"
        else:
            raise ValueError(f"structured order endpoints require backend='native_event' or 'nautilus', got {backend!r}")
        self._store_result(result)
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
        backend = _resolve_backend(self.config)
        if backend == "nautilus":
            plan = build_frozen_basket_orders(
                datetime_index=idx,
                basket=spec,
                signal=sig,
                closes=close_map,
                order_type=OrderType.MARKET,
                tif=TimeInForce.IOC,
            )
            result = self._run_nautilus_package_orders(
                data=_frames_from_symbol_maps(close_map, high_map, low_map, symbol_list),
                orders=plan.orders,
                symbols=symbol_list,
                params={
                    "input_mode": "basket_package",
                    "basket_id": spec.basket_id,
                    "basket_plan": plan,
                    "basket_target_units": plan.target_units,
                    "basket_execution_policy": spec.execution_policy.value,
                    "package_target_units": plan.target_units,
                    "order_count_input": len(plan.orders),
                },
            )
            result.metadata["engine"] = "nautilus_basket_package"
            self._store_result(result)
            return self.result

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
            if isinstance(spec, OptionsVolArbSpec):
                raise NotImplementedError(
                    "OptionsVolArbSpec must route through QuantBTEndpoint.options(...), not generic arbitrage execution. "
                    "The option route preserves package fills, multi-currency ledger, Greeks, settlement, and margin reports."
                )
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
                    report_level=self.config.report_level,
                    audit_sink=self.config.audit_sink,
                    audit_sink_path=self.config.audit_sink_path,
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
        target_mode = self.config.walkforward_target_mode.lower().strip()
        scorer = (
            _make_walkforward_endpoint_scorer(
                self.config,
                target_mode=target_mode,
                symbols=symbols,
                wf_config=wf_config,
                market_data=data,
                market_closes=closes,
                market_highs=highs,
                market_lows=lows,
                market_datetime_index=datetime_index,
            )
            if wf_config.scoring_backend == "endpoint"
            else None
        )
        engine = WalkForwardEngine(strategy=self.config.strategy_class, config=wf_config, scorer=scorer)
        wf_result = engine.run(
            data=data if data is not None else closes,
            params=params,
            param_ranges=param_ranges,
            datetime_index=datetime_index,
        )
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
            "report_scope": "test" if wf_result.metadata.get("split_frequency") == "single" else "oos",
            "split_frequency": wf_result.metadata.get("split_frequency"),
            "window_mode": wf_result.metadata.get("window_mode"),
            "params": wf_result.params,
            "fold_table": wf_result.fold_table,
            "trial_table": wf_result.trial_table,
            "candidate_table": wf_result.candidate_table,
            "best_trial": wf_result.best_trial,
            "optimization_mode": wf_result.metadata.get("optimization_mode"),
            "validation_claim": wf_result.metadata.get("validation_claim"),
            "full_sample_used_for_selection": wf_result.metadata.get("full_sample_used_for_selection"),
            "oos_used_for_selection": wf_result.metadata.get("oos_used_for_selection"),
            "data_hash": wf_result.metadata.get("data_hash"),
            "config_hash": wf_result.metadata.get("config_hash"),
            "random_seed": wf_result.metadata.get("random_seed"),
            "top_is_fraction": wf_result.metadata.get("top_is_fraction"),
            "top_is_k": wf_result.metadata.get("top_is_k"),
            "candidate_selection_metric": wf_result.metadata.get("candidate_selection_metric"),
            "scoring_trading_days": wf_result.metadata.get("scoring_trading_days"),
            "min_trades_per_year": wf_result.metadata.get("min_trades_per_year"),
            "trade_penalty_factor": wf_result.metadata.get("trade_penalty_factor"),
            "sbb_simulation": wf_result.metadata.get("sbb_simulation"),
            "sbb_samples": wf_result.metadata.get("sbb_samples"),
            "sbb_block_length": wf_result.metadata.get("sbb_block_length"),
            "regime_count": wf_result.metadata.get("regime_count"),
            "regime_lookback": wf_result.metadata.get("regime_lookback"),
            "regime_weights": wf_result.metadata.get("regime_weights"),
            "stress_vol_multiplier": wf_result.metadata.get("stress_vol_multiplier"),
            "garch_p": wf_result.metadata.get("garch_p"),
            "garch_q": wf_result.metadata.get("garch_q"),
            "garch_dist": wf_result.metadata.get("garch_dist"),
            "garch_vol_multiplier": wf_result.metadata.get("garch_vol_multiplier"),
            "plateau_quantile": wf_result.metadata.get("plateau_quantile"),
            "plateau_median_weight": wf_result.metadata.get("plateau_median_weight"),
            "plateau_std_penalty": wf_result.metadata.get("plateau_std_penalty"),
            "plateau_size_bonus": wf_result.metadata.get("plateau_size_bonus"),
            "is_subperiods": wf_result.metadata.get("is_subperiods"),
            "q25_weight": wf_result.metadata.get("q25_weight"),
            "dispersion_penalty": wf_result.metadata.get("dispersion_penalty"),
            "temporal_weight": wf_result.metadata.get("temporal_weight"),
            "plateau_weight": wf_result.metadata.get("plateau_weight"),
            "use_bootstrap_penalty": wf_result.metadata.get("use_bootstrap_penalty"),
            "use_complexity_penalty": wf_result.metadata.get("use_complexity_penalty"),
            "scoring_backend": wf_result.metadata.get("scoring_backend"),
            "numba_enabled": wf_result.metadata.get("numba_enabled"),
        }
        if scorer is not None and hasattr(scorer, "prepared_cache_metadata"):
            result.metadata["walk_forward"]["prepared_scoring_cache"] = scorer.prepared_cache_metadata()
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
        if (
            self.config.mode.lower().strip() == "walk_forward"
            and self.config.walkforward_target_mode.lower().strip() == "portfolio"
            and self.config.backend.lower().strip() not in {"legacy_portfolio", "nautilus"}
        ):
            backend = "native_portfolio"
        else:
            backend = _resolve_backend(self.config)
        if backend == "nautilus":
            symbol_list = list(symbols or pos_map.keys())
            native_reference = PortfolioBacktestEngine(
                positions=pos_map,
                closes=close_map,
                highs=high_map,
                lows=low_map,
                datetime_index=idx,
                mode=self.config.portfolio_mode,
                backend="native_portfolio",
                account=self.config.account,
                execution=self.config.execution,
                fee_rate=self.config.fee,
                alloc_per_trade=self.config.alloc_per_trade,
                contract_size=self.config.contract_size,
                hedge_type=self.config.sizing if self.config.sizing else "signal_notional",
                asset_type=self.config.asset_type,
                use_funding=self.config.use_funding,
                funding_rate=self.config.funding_rate,
                leverage=self.config.account.leverage,
                maintenance_ratio=self.config.account.maintenance_ratio,
                use_pyramiding=self.config.use_pyramiding,
                betas=self.config.betas,
                risk_lookback=self.config.risk_lookback,
                report_level=self.config.report_level,
            ).result
            target_units = native_reference.metadata["target_units_report"].reindex(columns=symbol_list)
            orders = _build_portfolio_orders_from_target_units_for_nautilus(
                target_units=target_units,
                symbols=symbol_list,
                tag=f"portfolio:{self.config.sizing if self.config.sizing else 'signal_notional'}",
            )
            result = self._run_nautilus_package_orders(
                data=_frames_from_symbol_maps(close_map, high_map, low_map, symbol_list),
                orders=orders,
                symbols=symbol_list,
                params={
                    "input_mode": "portfolio_matrix",
                    "portfolio_mode": self.config.portfolio_mode,
                    "portfolio_target_units": target_units,
                    "package_target_units": target_units,
                    "order_count_input": len(orders),
                },
            )
            result.metadata["engine"] = "nautilus_portfolio_matrix"
            result.metadata["native_portfolio_reference_final_equity"] = float(native_reference.equity.iloc[-1])
            result.metadata["portfolio_nautilus_validation_report"] = build_portfolio_nautilus_validation_report(
                native_reference,
                result,
                equity_tolerance=float(self.config.metadata.get("portfolio_nautilus_equity_tolerance", 1e-6)),
                position_tolerance=float(self.config.metadata.get("portfolio_nautilus_position_tolerance", 1e-6)),
            )
            self._store_result(result)
            return self.result

        self.engine = PortfolioBacktestEngine(
            positions=pos_map,
            closes=close_map,
            highs=high_map,
            lows=low_map,
            datetime_index=idx,
            mode=self.config.portfolio_mode,
            backend=backend,
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
            use_pyramiding=self.config.use_pyramiding,
            betas=self.config.betas,
            risk_lookback=self.config.risk_lookback,
            instruments=self.config.instruments,
            qty_step=self.config.qty_step,
            lot_size=self.config.lot_size,
            slot_size=self.config.slot_size,
            min_qty=self.config.min_qty,
            min_notional=self.config.min_notional,
            report_level=self.config.report_level,
        )
        self._store_result(self.engine.result)
        return self.result

    def _run_nautilus_package_orders(self, data, orders, symbols, params):
        from .adapters.nautilus import NautilusBackendConfig, NautilusBacktestEngine

        run_params = dict(params or {})
        run_orders = _annotate_orders_for_depth(orders, run_params)
        depth_result = None
        if self.config.nautilus_depth_config is not None:
            depth_result = simulate_nautilus_order_package_depth(
                orders=run_orders,
                data=data,
                config=self.config.nautilus_depth_config,
            )
            run_orders = depth_result.orders
            run_params.update(
                {
                    "nautilus_depth_enabled": True,
                    "nautilus_depth_order_report": depth_result.order_report,
                    "nautilus_depth_package_report": depth_result.package_report,
                    "nautilus_depth_metadata": depth_result.metadata,
                    "order_count_before_depth": len(orders),
                    "order_count_after_depth": len(run_orders),
                }
            )
        else:
            run_params.setdefault("nautilus_depth_enabled", False)

        config = self.config.nautilus_config
        if config is None:
            config = NautilusBackendConfig(
                instrument_id=symbols[0],
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
        if not run_orders:
            return _empty_nautilus_preflight_result(
                data=data,
                symbols=symbols,
                account=self.config.account,
                metadata={
                    "backend": "nautilus",
                    "engine": "nautilus_package_orders_preflight_rejected",
                    "input_mode": run_params.get("input_mode", "order_packages"),
                    "orders_count": 0,
                    "fills_count": 0,
                    "positions_count": 0,
                    **run_params,
                },
            )
        return self.engine.run_order_packages(
            data=data,
            orders=run_orders,
            symbols=symbols,
            params=run_params,
        )

    def _store_result(self, result):
        _normalize_result_contract(result)
        _attach_endpoint_run_config(result, self.config)
        self.result = result
        return result

    def _require_result(self):
        if self.result is None:
            raise RuntimeError("run backtest() or simulate() before requesting results")
        return self.result

    def _result_for_report_scope(self, scope: str):
        from .core.scopes import scoped_result

        return scoped_result(self._require_result(), scope=scope)


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
    engine = str(metadata.get("engine", "unknown"))
    backend = str(metadata.get("backend", metadata.get("backend_alias", "unknown")))
    metadata.setdefault("backend_alias", backend)
    metadata.setdefault("engine_id", engine)
    metadata.setdefault("kernel_version", engine)
    metadata.setdefault(
        "execution_contract",
        {
            "engine_id": metadata["engine_id"],
            "signal_phase": metadata.get("signal_phase", "unspecified"),
            "fill_phase": metadata.get("fill_phase", "unspecified"),
            "intrabar_exit_model": metadata.get("intrabar_exit_model", "unspecified"),
        },
    )


def _attach_endpoint_run_config(result, config: EndpointConfig) -> None:
    metadata = result.metadata
    payload = _endpoint_run_config_payload(config)
    _sync_applied_nautilus_config(payload, metadata)
    metadata["run_config"] = payload
    metadata.setdefault("initial_capital", payload["account"]["initial_capital"])
    metadata.setdefault("leverage", payload["account"]["leverage"])
    metadata.setdefault("maintenance_ratio", payload["account"]["maintenance_ratio"])
    metadata.setdefault("fee_rate", payload["fees"]["one_way_fee_rate"])
    metadata.setdefault("fee_round_trip", payload["fees"]["round_trip_fee"])
    metadata.setdefault("alloc_per_trade", payload["sizing"]["alloc_per_trade"])
    metadata.setdefault("slippage", payload["execution"]["legacy_slippage_rate"])
    metadata.setdefault("slippage_bps", payload["execution"]["slippage_bps"])
    metadata.setdefault("use_funding", payload["funding"]["use_funding"])


def _sync_applied_nautilus_config(payload: Dict, metadata: Dict) -> None:
    """Keep report run_config aligned with the adapter config that actually ran."""
    if payload.get("backend") != "nautilus":
        return
    nautilus = dict(payload.get("nautilus") or {})
    if not nautilus:
        return

    for source_key, target_key in (
        ("instrument_id", "instrument_id"),
        ("sizing_mode", "sizing_mode"),
        ("trade_notional", "trade_notional"),
        ("use_pyramiding", "use_pyramiding"),
        ("close_positions_on_stop", "close_positions_on_stop"),
    ):
        if metadata.get(source_key) is not None:
            nautilus[target_key] = _jsonable(metadata[source_key])

    if metadata.get("timeframe") is not None:
        nautilus["timeframe"] = _jsonable(metadata["timeframe"])
    if metadata.get("initial_capital") is not None:
        nautilus["starting_balance"] = _jsonable(metadata["initial_capital"])

    payload["nautilus"] = nautilus


def _endpoint_run_config_payload(config: EndpointConfig) -> Dict:
    intrabar_mode = str(config.mode).lower().strip() in {"intrabar_bracket", "intrabar_bracket_reference", "fill_replay"}
    payload = {
        "mode": config.mode,
        "backend": config.backend,
        "portfolio_mode": config.portfolio_mode,
        "asset_type": config.asset_type,
        "account": _jsonable(asdict(config.account)),
        "execution": {
            **_jsonable(asdict(config.execution)),
            "legacy_slippage_rate": None if intrabar_mode else float(config.slippage),
            "slippage_bps": float(config.execution.slippage_bps),
        },
        "fees": {
            "round_trip_fee": float(config.fee),
            "one_way_fee_rate": float(config.v2_fee_rate),
            "explicit_fee_rate": None if config.fee_rate is None else float(config.fee_rate),
        },
        "sizing": {
            "hedge_type": config.sizing,
            "alloc_per_trade": _jsonable(config.alloc_per_trade),
            "use_pyramiding": bool(config.use_pyramiding),
            "contract_size": _jsonable(config.contract_size),
        },
        "funding": {
            "use_funding": bool(config.use_funding),
            "funding_rate": _jsonable(config.funding_rate),
        },
        "dca_kwargs": _jsonable(config.dca_kwargs),
        "structured_order_spec": _jsonable(config.structured_order_spec),
        "symbols": _jsonable(config.symbols),
        "metadata": _jsonable(config.metadata),
        "report_level": config.report_level,
        "audit_sink": config.audit_sink,
        "audit_sink_path": config.audit_sink_path,
    }
    if config.nautilus_config is not None:
        payload["nautilus"] = _jsonable(
            asdict(config.nautilus_config) if is_dataclass(config.nautilus_config) else vars(config.nautilus_config)
        )
    return payload


def _jsonable(value):
    if is_dataclass(value):
        return _jsonable(asdict(value))
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, pd.Series):
        return {
            "type": "Series",
            "name": value.name,
            "rows": int(len(value)),
            "start": str(value.index[0]) if len(value) else None,
            "end": str(value.index[-1]) if len(value) else None,
        }
    if isinstance(value, pd.DataFrame):
        return {
            "type": "DataFrame",
            "rows": int(len(value)),
            "columns": list(value.columns),
            "start": str(value.index[0]) if len(value) else None,
            "end": str(value.index[-1]) if len(value) else None,
        }
    if hasattr(value, "value"):
        return value.value
    return value


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
    mode_name = str(kwargs.get("mode", "")).lower().strip()
    metadata = dict(kwargs.pop("metadata", {}) or {})
    if "tick_size" in kwargs:
        metadata.setdefault("tick_size", kwargs.pop("tick_size"))
    if "source_timezone" in kwargs:
        metadata.setdefault("source_timezone", kwargs.pop("source_timezone"))
    if "missing_funding_policy" in kwargs:
        metadata.setdefault("missing_funding_policy", kwargs.pop("missing_funding_policy"))
    if "bar_timestamp_semantics" in kwargs:
        metadata.setdefault("bar_timestamp_semantics", kwargs.pop("bar_timestamp_semantics"))
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

    legacy_slippage_supplied = "slippage" in kwargs
    legacy_slippage_value = kwargs.get("slippage")
    slippage_bps = kwargs.pop("slippage_bps", None)
    execution = kwargs.pop("execution", None)
    if slippage_bps is not None and execution is not None:
        raise ValueError("pass either execution=ExecutionConfig(...) or slippage_bps=..., not both")
    if slippage_bps is not None and legacy_slippage_supplied:
        raise ValueError("pass either slippage_bps or legacy slippage, not both")
    if execution is None:
        if slippage_bps is not None:
            execution = ExecutionConfig(slippage_bps=float(slippage_bps))
        elif mode_name in {"intrabar_bracket", "intrabar_bracket_reference", "portfolio"} and legacy_slippage_supplied:
            warnings.warn(
                "QuantBT native endpoints use slippage_bps as the source of truth; "
                "legacy slippage was converted to slippage_bps for compatibility.",
                DeprecationWarning,
                stacklevel=3,
            )
            execution = ExecutionConfig(slippage_bps=float(legacy_slippage_value) * 10_000.0)
        else:
            execution = ExecutionConfig(slippage_bps=0.0)

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

    return EndpointConfig(account=account, execution=execution, dca_kwargs=dca_kwargs, metadata=metadata, **kwargs)


def _pop_dataclass_kwargs(kwargs: Dict, dataclass_type) -> Dict:
    fields = getattr(dataclass_type, "__dataclass_fields__", {})
    out = {}
    for key in list(fields):
        if key == "metadata":
            continue
        if key in kwargs:
            out[key] = kwargs.pop(key)
    return out


def _resolve_backend(config: EndpointConfig) -> str:
    backend = config.backend.lower().strip()
    if backend != "auto":
        if backend == "legacy_portfolio":
            return backend
        if backend not in {"legacy", "native_vectorized", "native_event", "native_portfolio", "native_option", "nautilus"}:
            raise ValueError(f"unsupported backend={config.backend!r}")
        return backend
    mode = config.mode.lower().strip()
    sizing = config.sizing.lower().strip()
    if mode == "portfolio":
        return "native_portfolio"
    if mode == "options":
        return "native_option"
    if mode in ("pct_equity", "dca_ladder") or sizing in ("%_equity", "pct_equity", "dca_ladder", "dca"):
        return "legacy"
    if mode == "nautilus_validation":
        return "nautilus"
    if mode in ("orders", "basket", "arbitrage"):
        return "native_event"
    return "native_vectorized"


def _default_walkforward_scoring_backend(target_mode: str, optimization_mode: str) -> str:
    mode = str(target_mode).lower().strip()
    opt_mode = str(optimization_mode).lower().strip()
    if opt_mode == "mode_2_sbb":
        return "proxy"
    if mode in {"pct_equity", "%_equity", "signal_notional", "single_signal", "dca_ladder"}:
        return "endpoint"
    return "proxy"


def _make_walkforward_endpoint_scorer(
    config: EndpointConfig,
    target_mode: str,
    symbols=None,
    wf_config: Optional[WalkForwardConfig] = None,
    market_data=None,
    market_closes=None,
    market_highs=None,
    market_lows=None,
    market_datetime_index=None,
):
    return _WalkForwardEndpointScorer(
        config=config,
        target_mode=target_mode,
        symbols=symbols,
        wf_config=wf_config,
        market_data=market_data,
        market_closes=market_closes,
        market_highs=market_highs,
        market_lows=market_lows,
        market_datetime_index=market_datetime_index,
    )


@dataclass
class QuantBTPreparedContext:
    """
    Run-local prepared market context for repeated endpoint replays.

    The context stores copied prepared market arrays and validates datetime /
    symbol signatures inside the backend on every replay. It is intentionally
    caller-owned and never a mutable global cache.
    """

    endpoint: QuantBTEndpoint
    mode: str
    idx: pd.DatetimeIndex
    symbols: list
    close_map: SeriesMap
    high_map: SeriesMap
    low_map: SeriesMap
    market_arrays: object
    backend: object
    frame: Optional[pd.DataFrame] = None
    runs: int = 0

    @classmethod
    def from_endpoint(
        cls,
        endpoint: QuantBTEndpoint,
        *,
        data=None,
        closes=None,
        highs=None,
        lows=None,
        datetime_index=None,
        symbols=None,
    ) -> "QuantBTPreparedContext":
        config = endpoint.config
        backend_name = _resolve_backend(config)
        mode = config.mode.lower().strip()
        sizing = config.sizing.lower().strip()

        if mode in {"single_signal", "signal_notional"} and backend_name == "native_vectorized" and sizing in {"signal_notional", "signal"}:
            frame = _standardize_frame(data, datetime_index=datetime_index)
            symbol_list = list(symbols or config.symbols or ["DEFAULT"])
            if len(symbol_list) != 1:
                raise ValueError("single-symbol prepared context requires exactly one symbol")
            symbol = symbol_list[0]
            close_map = {symbol: frame["close"]}
            high_map = {symbol: frame.get("high", frame["close"])}
            low_map = {symbol: frame.get("low", frame["close"])}
            backend = NativeVectorizedBackend(
                NativeVectorizedConfig(
                    account=config.account,
                    execution=config.execution,
                    fee_rate=config.v2_fee_rate,
                    use_funding=bool(config.use_funding),
                )
            )
            market = backend.prepare_market_arrays(
                datetime_index=frame.index,
                closes=close_map,
                highs=high_map,
                lows=low_map,
                funding_rate=config.funding_rate,
                symbols=symbol_list,
            )
            return cls(
                endpoint=endpoint,
                mode="single_signal_notional",
                idx=frame.index,
                symbols=symbol_list,
                close_map=close_map,
                high_map=high_map,
                low_map=low_map,
                market_arrays=market,
                backend=backend,
                frame=frame,
            )

        if mode == "portfolio" and backend_name == "native_portfolio":
            close_map, high_map, low_map, idx, symbol_list = _normalize_symbol_data(
                data=data,
                closes=closes,
                highs=highs,
                lows=lows,
                datetime_index=datetime_index,
                symbols=symbols or config.symbols,
            )
            asset_type = config.asset_type.lower()
            default_fee = 0.0004 if asset_type == "crypto" else 0.0001
            fee_oneway = (config.fee if config.fee is not None else default_fee) / 2.0
            backend = NativePortfolioBackend(
                NativePortfolioConfig(
                    account=config.account,
                    execution=config.execution,
                    fee_rate=fee_oneway,
                    use_funding=bool(config.use_funding),
                    report_level=config.report_level,
                )
            )
            market = backend.prepare_market_arrays(
                datetime_index=idx,
                closes=close_map,
                highs=high_map,
                lows=low_map,
                funding_rate=config.funding_rate,
                symbols=symbol_list,
            )
            return cls(
                endpoint=endpoint,
                mode="portfolio",
                idx=idx,
                symbols=list(symbol_list),
                close_map=close_map,
                high_map=high_map,
                low_map=low_map,
                market_arrays=market,
                backend=backend,
            )

        raise NotImplementedError(
            "prepared service context currently supports native_vectorized signal_notional "
            "and native_portfolio only; use normal backtest(...) for this endpoint"
        )

    @property
    def metadata(self) -> Dict[str, object]:
        return {
            "mode": self.mode,
            "symbols": tuple(self.symbols),
            "bars": int(len(self.idx)),
            "runs": int(self.runs),
            "market_signature": self.market_arrays.signature,
        }

    def backtest(self, *, signal=None, signal_col: Optional[str] = None, positions=None):
        """Replay a new signal or position matrix on the prepared market tape."""
        if self.mode == "single_signal_notional":
            result = self._run_single(signal=signal, signal_col=signal_col)
        elif self.mode == "portfolio":
            result = self._run_portfolio(positions=positions)
        else:  # pragma: no cover - guarded by constructor
            raise NotImplementedError(f"unsupported prepared context mode={self.mode!r}")
        self.runs += 1
        result.metadata.setdefault("prepared_service_context", self.metadata)
        self.endpoint._store_result(result)
        return result

    simulate = backtest

    def _run_single(self, *, signal=None, signal_col: Optional[str] = None):
        config = self.endpoint.config
        if signal is None:
            signal = _signal_from_data(self.frame, signal_col)
        if signal is None:
            raise ValueError("prepared single-symbol context requires signal or signal_col")
        raw = _series_to_raw_matrix(signal, self.idx)
        symbol = self.symbols[0]
        return self.backend.run_signals(
            datetime_index=self.idx,
            positions={symbol: pd.Series(0.0, index=self.idx)},
            closes=self.close_map,
            highs=self.high_map,
            lows=self.low_map,
            funding_rate=config.funding_rate,
            contract_size=config.contract_size,
            leverage=config.account.leverage,
            alloc_per_trade=config.alloc_per_trade,
            hedge_type=config.sizing,
            use_pyramiding=config.use_pyramiding,
            symbols=self.symbols,
            market_arrays=self.market_arrays,
            raw_signal_matrix=raw,
            instruments=config.instruments,
            qty_step=config.qty_step,
            lot_size=config.lot_size,
            slot_size=config.slot_size,
            min_qty=config.min_qty,
            min_notional=config.min_notional,
        )

    def _run_portfolio(self, *, positions=None):
        if positions is None:
            raise ValueError("prepared portfolio context requires positions")
        config = self.endpoint.config
        raw = _positions_to_raw_matrix(positions, self.idx, self.symbols)
        return self.backend.run_signals(
            positions=None,
            closes=self.close_map,
            highs=self.high_map,
            lows=self.low_map,
            datetime_index=self.idx,
            mode=config.portfolio_mode,
            alloc_per_trade=config.alloc_per_trade,
            contract_size=config.contract_size,
            hedge_type=config.sizing if config.sizing else "notional",
            funding_rate=config.funding_rate,
            leverage=config.account.leverage,
            maintenance_ratio=config.account.maintenance_ratio,
            asset_type=config.asset_type,
            use_pyramiding=config.use_pyramiding,
            betas=config.betas,
            risk_lookback=config.risk_lookback,
            market_arrays=self.market_arrays,
            raw_signal_matrix=raw,
            instruments=config.instruments,
            qty_step=config.qty_step,
            lot_size=config.lot_size,
            slot_size=config.slot_size,
            min_qty=config.min_qty,
            min_notional=config.min_notional,
            report_level=config.report_level,
        )


class _WalkForwardEndpointScorer:
    """
    Endpoint-backed WFO scorer with run-local prepared market array reuse.

    The cache is intentionally scoped to one scorer instance, which is created
    for one `QuantBTEndpoint.backtest(...)` call. It never caches by pandas
    object identity and every prepared reuse is validated by backend signatures.
    """

    def __init__(
        self,
        config: EndpointConfig,
        target_mode: str,
        symbols=None,
        wf_config: Optional[WalkForwardConfig] = None,
        market_data=None,
        market_closes=None,
        market_highs=None,
        market_lows=None,
        market_datetime_index=None,
    ):
        self.config = config
        self.target_mode = str(target_mode).lower().strip()
        self.score_config = _walkforward_scoring_config(config, self.target_mode)
        self.symbols = None if symbols is None and config.symbols is None else list(symbols or config.symbols or [])
        self.wf_config = wf_config
        self.market_data = market_data
        self.market_closes = market_closes
        self.market_highs = market_highs
        self.market_lows = market_lows
        self.market_datetime_index = market_datetime_index
        self.use_prepared_cache = bool((wf_config.metadata if wf_config is not None else {}).get("use_prepared_scoring_cache", True))
        self.prepared_scoring_report_level = str(
            (wf_config.metadata if wf_config is not None else {}).get("prepared_scoring_report_level", "minimal")
        )
        self._single_backend = None
        self._single_market_maps = {}
        self._single_market_cache = {}
        self._portfolio_backend = None
        self._portfolio_market_maps = {}
        self._portfolio_market_cache = {}
        self._stats = {
            "enabled": bool(self.use_prepared_cache),
            "target_mode": self.target_mode,
            "backend": self.score_config.backend,
            "market_cache_hits": 0,
            "market_cache_misses": 0,
            "market_cache_entries": 0,
            "prepared_runs": 0,
            "fallback_runs": 0,
        }

    def __call__(self, data, output, index, fold, params, context: str, trading_days: int) -> Dict[str, float]:
        try:
            if self._can_score_single_vectorized_prepared(output):
                result = self._score_single_vectorized_prepared(output=output, index=index)
            elif self._can_score_portfolio_prepared(output):
                result = self._score_portfolio_prepared(output=output, index=index)
            else:
                result = self._score_fallback(data=data, output=output, index=index)
            report = result.full_report(trading_days=trading_days, scope="full")
        except Exception as exc:
            raise RuntimeError(
                "walk-forward endpoint scoring failed during "
                f"{context} for fold_id={fold.fold_id}; target_mode={self.target_mode!r}; params={params}"
            ) from exc
        return {
            "sharpe": float(report.get("sharpe", 0.0)),
            "turnover": float(report.get("num_trades", 0.0)),
            "trade_count": float(report.get("num_trades", 0.0)),
            "mean_return": float(report.get("total_return_pct", 0.0)) / 100.0,
            "volatility": 0.0,
            "max_drawdown_pct": float(report.get("max_drawdown_pct", 0.0)),
            "profit_factor": float(report.get("profit_factor", 0.0)),
        }

    def prepared_cache_metadata(self) -> Dict[str, object]:
        meta = dict(self._stats)
        meta["market_cache_entries"] = len(self._portfolio_market_cache) + len(self._single_market_cache)
        meta["prepared_scoring_report_level"] = self.prepared_scoring_report_level
        meta["available"] = (
            self._prepared_single_available()
            or (self.target_mode == "portfolio" and self.score_config.backend == "native_portfolio")
        )
        return meta

    def _prepared_single_available(self) -> bool:
        return (
            self.score_config.mode == "signal_notional"
            and _resolve_backend(self.score_config) == "native_vectorized"
        )

    def _can_score_single_vectorized_prepared(self, output) -> bool:
        return (
            self.use_prepared_cache
            and self._prepared_single_available()
            and isinstance(output, pd.Series)
        )

    def _can_score_portfolio_prepared(self, output) -> bool:
        return (
            self.use_prepared_cache
            and self.score_config.mode == "portfolio"
            and self.score_config.backend == "native_portfolio"
            and isinstance(output, (pd.DataFrame, dict))
        )

    def _score_fallback(self, data, output, index):
        self._stats["fallback_runs"] += 1
        temp = QuantBTEndpoint(self.score_config)
        sliced_data = _slice_wf_data_to_index(data, index)
        symbol_list = self._symbol_list(output)
        if self.score_config.mode == "portfolio":
            return temp.backtest(data=sliced_data, positions=output, symbols=symbol_list)
        return temp.backtest(data=sliced_data, signal=output, symbols=symbol_list)

    def _score_single_vectorized_prepared(self, output: pd.Series, index):
        idx = _ensure_utc_index(index)
        symbol_list = self._symbol_list(output)
        close_map, high_map, low_map = self._single_maps(symbol_list)
        backend = self._single_backend_instance()
        cache_key = self._market_cache_key(idx, symbol_list)
        market = self._single_market_cache.get(cache_key)
        if market is None:
            market = backend.prepare_market_arrays(
                datetime_index=idx,
                closes=close_map,
                highs=high_map,
                lows=low_map,
                funding_rate=self.score_config.funding_rate,
                symbols=symbol_list,
            )
            self._single_market_cache[cache_key] = market
            self._stats["market_cache_misses"] += 1
        else:
            self._stats["market_cache_hits"] += 1

        self._stats["prepared_runs"] += 1
        return backend.run_signals(
            positions={symbol_list[0]: output},
            closes=close_map,
            highs=high_map,
            lows=low_map,
            datetime_index=idx,
            funding_rate=self.score_config.funding_rate,
            contract_size=self.score_config.contract_size,
            leverage=self.score_config.account.leverage,
            alloc_per_trade=self.score_config.alloc_per_trade,
            hedge_type=self.score_config.sizing,
            use_pyramiding=self.score_config.use_pyramiding,
            symbols=symbol_list,
            market_arrays=market,
            instruments=self.score_config.instruments,
            qty_step=self.score_config.qty_step,
            lot_size=self.score_config.lot_size,
            slot_size=self.score_config.slot_size,
            min_qty=self.score_config.min_qty,
            min_notional=self.score_config.min_notional,
        )

    def _score_portfolio_prepared(self, output, index):
        idx = _ensure_utc_index(index)
        symbol_list = self._symbol_list(output)
        close_map, high_map, low_map = self._portfolio_maps(symbol_list)
        backend = self._portfolio_backend_instance()
        cache_key = self._market_cache_key(idx, symbol_list)
        market = self._portfolio_market_cache.get(cache_key)
        if market is None:
            market = backend.prepare_market_arrays(
                datetime_index=idx,
                closes=close_map,
                highs=high_map,
                lows=low_map,
                funding_rate=self.score_config.funding_rate,
                symbols=symbol_list,
            )
            self._portfolio_market_cache[cache_key] = market
            self._stats["market_cache_misses"] += 1
        else:
            self._stats["market_cache_hits"] += 1

        pos_map = _positions_to_map(output)
        raw_signals = NativePortfolioBackend.prepare_signal_matrix(pos_map, idx, symbol_list)
        self._stats["prepared_runs"] += 1
        return backend.run_signals(
            positions=None,
            closes=close_map,
            highs=high_map,
            lows=low_map,
            datetime_index=idx,
            mode=self.score_config.portfolio_mode,
            alloc_per_trade=self.score_config.alloc_per_trade,
            contract_size=self.score_config.contract_size,
            hedge_type=self.score_config.sizing if self.score_config.sizing else "notional",
            funding_rate=self.score_config.funding_rate,
            leverage=self.score_config.account.leverage,
            maintenance_ratio=self.score_config.account.maintenance_ratio,
            asset_type=self.score_config.asset_type,
            use_pyramiding=self.score_config.use_pyramiding,
            betas=self.score_config.betas,
            risk_lookback=self.score_config.risk_lookback,
            market_arrays=market,
            raw_signal_matrix=raw_signals,
            instruments=self.score_config.instruments,
            qty_step=self.score_config.qty_step,
            lot_size=self.score_config.lot_size,
            slot_size=self.score_config.slot_size,
            min_qty=self.score_config.min_qty,
            min_notional=self.score_config.min_notional,
            report_level=self.prepared_scoring_report_level,
        )

    def _single_backend_instance(self) -> NativeVectorizedBackend:
        if self._single_backend is None:
            self._single_backend = NativeVectorizedBackend(
                NativeVectorizedConfig(
                    account=self.score_config.account,
                    execution=self.score_config.execution,
                    fee_rate=self.score_config.v2_fee_rate,
                    use_funding=bool(self.score_config.use_funding),
                )
            )
        return self._single_backend

    def _portfolio_backend_instance(self) -> NativePortfolioBackend:
        if self._portfolio_backend is None:
            asset_type = self.score_config.asset_type.lower()
            default_fee = 0.0004 if asset_type == "crypto" else 0.0001
            fee_oneway = (self.score_config.fee if self.score_config.fee is not None else default_fee) / 2.0
            self._portfolio_backend = NativePortfolioBackend(
                NativePortfolioConfig(
                    account=self.score_config.account,
                    execution=self.score_config.execution,
                    fee_rate=fee_oneway,
                    use_funding=bool(self.score_config.use_funding),
                    report_level=self.prepared_scoring_report_level,
                )
            )
        return self._portfolio_backend

    def _single_maps(self, symbol_list):
        key = tuple(symbol_list)
        if key not in self._single_market_maps:
            if self.market_closes is not None or isinstance(self.market_data, dict):
                close_map, high_map, low_map, _idx, _symbols = _normalize_symbol_data(
                    data=self.market_data,
                    closes=self.market_closes,
                    highs=self.market_highs,
                    lows=self.market_lows,
                    datetime_index=self.market_datetime_index,
                    symbols=symbol_list,
                )
            else:
                frame = _standardize_frame(self.market_data, datetime_index=self.market_datetime_index)
                symbol = symbol_list[0]
                close_map = {symbol: frame["close"]}
                high_map = {symbol: frame.get("high", frame["close"])}
                low_map = {symbol: frame.get("low", frame["close"])}
            self._single_market_maps[key] = (close_map, high_map, low_map)
        return self._single_market_maps[key]

    def _portfolio_maps(self, symbol_list):
        key = tuple(symbol_list)
        if key not in self._portfolio_market_maps:
            close_map, high_map, low_map, _idx, _symbols = _normalize_symbol_data(
                data=self.market_data,
                closes=self.market_closes,
                highs=self.market_highs,
                lows=self.market_lows,
                datetime_index=self.market_datetime_index,
                symbols=symbol_list,
            )
            self._portfolio_market_maps[key] = (close_map, high_map, low_map)
        return self._portfolio_market_maps[key]

    def _symbol_list(self, output) -> list:
        if self.symbols:
            return list(self.symbols)
        if isinstance(output, pd.DataFrame):
            return list(output.columns)
        if isinstance(output, dict):
            return list(output.keys())
        return ["DEFAULT"]

    @staticmethod
    def _market_cache_key(index: pd.DatetimeIndex, symbols: Sequence[str]):
        idx = _ensure_utc_index(index)
        first = None if len(idx) == 0 else int(idx.asi8[0])
        last = None if len(idx) == 0 else int(idx.asi8[-1])
        return (tuple(symbols), int(len(idx)), first, last)


def _walkforward_scoring_config(config: EndpointConfig, target_mode: str) -> EndpointConfig:
    mode = str(target_mode).lower().strip()
    if mode in {"pct_equity", "%_equity"}:
        return replace(config, mode="pct_equity", backend="legacy", sizing="%_equity")
    if mode == "dca_ladder":
        return replace(config, mode="dca_ladder", backend="legacy", sizing="dca_ladder")
    if mode in {"signal_notional", "single_signal"}:
        return replace(config, mode="signal_notional", backend=config.backend, sizing="signal_notional")
    if mode == "portfolio":
        return replace(config, mode="portfolio", backend="native_portfolio")
    raise NotImplementedError(f"endpoint scoring is not implemented for walk-forward target_mode={target_mode!r}")


def _strict_lookup_frame(data, datetime_index=None, *, source_timezone: Optional[str] = None) -> pd.DataFrame:
    if not isinstance(data, pd.DataFrame):
        raise ValueError("intrabar endpoint requires a DataFrame when intent is not supplied explicitly")
    frame = data.copy().rename(
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
        frame.index = _endpoint_strict_index(datetime_index, source_timezone=source_timezone)
    elif "timestamp" in frame.columns:
        frame = frame.set_index(_endpoint_strict_index(frame["timestamp"], source_timezone=source_timezone))
    else:
        frame.index = _endpoint_strict_index(frame.index, source_timezone=source_timezone)
    return frame


def _endpoint_strict_index(value, *, source_timezone: Optional[str] = None) -> pd.DatetimeIndex:
    raw = pd.DatetimeIndex(pd.to_datetime(value, errors="raise"))
    if raw.tz is None:
        if source_timezone is None:
            raise ValueError("intrabar endpoint received timezone-naive data; pass metadata={'source_timezone': ...}")
        raw = raw.tz_localize(source_timezone)
    return raw.tz_convert("UTC")


def _execution_contract_from_config(config: EndpointConfig) -> ExecutionContract:
    meta = config.metadata.get("execution_contract")
    if meta:
        return ExecutionContract.from_metadata(meta)
    contract_id = str(config.metadata.get("execution_contract_id", "intrabar_bracket_v1"))
    if contract_id == "intrabar_bracket_v1":
        return ExecutionContract.intrabar_bracket()
    return ExecutionContract.from_metadata({"engine_id": contract_id})


def _session_policy_from_config(config: EndpointConfig) -> Optional[SessionExecutionPolicy]:
    return SessionExecutionPolicy.from_metadata(config.metadata.get("session_policy"))


def _tick_size_for_symbol(instruments, symbol: str, default: float = 0.0) -> float:
    if isinstance(default, dict):
        fallback = float(default.get(symbol, 0.0))
    else:
        fallback = float(default or 0.0)
    if instruments is None:
        return fallback
    if isinstance(instruments, dict):
        inst = instruments.get(symbol)
        return fallback if inst is None else float(getattr(inst, "tick_size", fallback))
    for inst in instruments:
        if getattr(inst, "symbol", None) == symbol:
            return float(getattr(inst, "tick_size", fallback))
    return fallback


def _prepared_profile_signature(data_signature: str, profile: Dict) -> str:
    payload = dict(profile)
    payload["data_signature"] = data_signature
    raw = json.dumps(_jsonable(payload), sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _intrabar_intent_from_endpoint_input(
    *,
    frame: Optional[pd.DataFrame],
    index: pd.DatetimeIndex,
    signal,
    signal_col: Optional[str],
    intent_cols: Dict[str, str],
    level_mode: IntrabarLevelMode,
) -> IntrabarIntentTape:
    signed_signal = None
    if signal is not None:
        signed_signal = _strict_series_values(signal, index, name="signal")
    elif signal_col is not None:
        signed_signal = _strict_frame_col_values(frame, index, signal_col, dtype=float)
    elif "entry_signal" in intent_cols:
        signed_signal = _strict_frame_col_values(frame, index, intent_cols["entry_signal"], dtype=float)
    elif "signal" in intent_cols:
        signed_signal = _strict_frame_col_values(frame, index, intent_cols["signal"], dtype=float)

    if "entry_side" in intent_cols:
        entry_side = np.sign(_strict_frame_col_values(frame, index, intent_cols["entry_side"], dtype=float)).astype(np.int8)
    elif signed_signal is not None:
        entry_side = np.sign(signed_signal).astype(np.int8)
    else:
        raise ValueError("intrabar endpoint requires signal/signal_col or intent_cols['entry_side']")

    if "entry_size" in intent_cols:
        entry_size = np.abs(_strict_frame_col_values(frame, index, intent_cols["entry_size"], dtype=float))
    elif signed_signal is not None:
        entry_size = np.abs(signed_signal)
    else:
        raise ValueError("intrabar endpoint requires intent_cols['entry_size'] when no signed signal is supplied")

    return IntrabarIntentTape.from_arrays(
        entry_side=entry_side,
        entry_size=entry_size,
        stop_value=_optional_intent_col(frame, index, intent_cols, "stop_value"),
        take_profit_value=_optional_intent_col(frame, index, intent_cols, "take_profit_value"),
        trailing_value=_optional_intent_col(frame, index, intent_cols, "trailing_value"),
        technical_exit=_optional_intent_col(frame, index, intent_cols, "technical_exit", dtype=bool),
        exit_long=_optional_intent_col(frame, index, intent_cols, "exit_long", dtype=bool),
        exit_short=_optional_intent_col(frame, index, intent_cols, "exit_short", dtype=bool),
        level_mode=level_mode,
    )


def _strict_series_values(series, index: pd.DatetimeIndex, *, name: str) -> np.ndarray:
    if not isinstance(series, pd.Series):
        series = pd.Series(series, index=index)
    s = series.copy()
    s.index = pd.DatetimeIndex(pd.to_datetime(s.index, errors="raise", utc=True))
    if not s.index.equals(index):
        raise ValueError(f"{name} index must exactly match the strict market tape index")
    return pd.to_numeric(s, errors="raise").to_numpy(dtype=np.float64)


def _strict_frame_col_values(frame: Optional[pd.DataFrame], index: pd.DatetimeIndex, col: str, *, dtype=float) -> np.ndarray:
    if frame is None:
        raise ValueError(f"intent column {col!r} requires DataFrame data")
    if col not in frame.columns:
        raise ValueError(f"intent column {col!r} not found in data")
    if not pd.DatetimeIndex(frame.index).equals(index):
        raise ValueError(f"intent column {col!r} index must exactly match the strict market tape index")
    if dtype is bool:
        return frame[col].fillna(False).astype(bool).to_numpy(dtype=np.bool_)
    return pd.to_numeric(frame[col], errors="raise").to_numpy(dtype=np.float64)


def _optional_intent_col(frame: Optional[pd.DataFrame], index: pd.DatetimeIndex, cols: Dict[str, str], key: str, *, dtype=float):
    col = cols.get(key)
    if col is None:
        return None
    return _strict_frame_col_values(frame, index, col, dtype=dtype)


def _scalar_for_symbol(value, symbol: str, default: float = 1.0) -> float:
    if isinstance(value, dict):
        return float(value.get(symbol, default))
    return float(default if value is None else value)


def _intrabar_fills_to_frame(fills) -> pd.DataFrame:
    rows = []
    for fill in fills:
        rows.append(
            {
                "bar_index": int(fill.bar_index),
                "sequence": int(fill.sequence),
                "timestamp": pd.Timestamp(fill.timestamp),
                "side": int(fill.side),
                "qty": float(fill.qty),
                "price": float(fill.price),
                "fee": float(fill.fee),
                "reason": fill.reason.value if hasattr(fill.reason, "value") else str(fill.reason),
            }
        )
    return pd.DataFrame(rows)


def _slice_wf_data_to_index(data, index: pd.DatetimeIndex):
    if isinstance(data, pd.DataFrame):
        return data.reindex(index).copy()
    if isinstance(data, pd.Series):
        return data.reindex(index).copy()
    if isinstance(data, dict):
        out = {}
        for key, value in data.items():
            if isinstance(value, (pd.DataFrame, pd.Series)):
                out[key] = value.reindex(index).copy()
            else:
                out[key] = value
        return out
    return data


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


def _intrabar_marker_columns(frame: pd.DataFrame) -> list[str]:
    markers = {
        "exit_price",
        "exit_type",
        "stop_loss",
        "stoploss",
        "sl",
        "take_profit",
        "takeprofit",
        "tp",
        "trailing",
        "trailing_stop",
        "use_sl",
        "use_tp",
        "slpercent",
        "tppercent",
    }
    found = []
    for col in frame.columns:
        key = str(col).lower()
        if key in markers or "trailing" in key or "stop_loss" in key or "take_profit" in key:
            found.append(str(col))
    return found


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


def _prepared_native_event_open_volume_arrays(data, idx: pd.DatetimeIndex, symbols, close_map) -> tuple[np.ndarray, np.ndarray]:
    open_cols = []
    volume_cols = []
    for symbol in symbols:
        close = close_map[symbol]
        if isinstance(data, dict) and symbol in data and isinstance(data[symbol], pd.DataFrame):
            frame = _standardize_frame(data[symbol], datetime_index=None)
            open_cols.append(_align_series(frame.get("open", frame["close"]), idx).to_numpy(dtype=np.float64))
            volume_cols.append(_align_series(frame.get("volume", pd.Series(0.0, index=frame.index)), idx).to_numpy(dtype=np.float64))
        else:
            open_cols.append(close.to_numpy(dtype=np.float64))
            volume_cols.append(np.zeros(len(idx), dtype=np.float64))
    return (
        np.ascontiguousarray(np.column_stack(open_cols), dtype=np.float64),
        np.ascontiguousarray(np.column_stack(volume_cols), dtype=np.float64),
    )


def _empty_nautilus_preflight_result(data, symbols, account: AccountConfig, metadata: Dict) -> BacktestResultV2:
    symbol_list = list(symbols)
    if not symbol_list:
        raise ValueError("symbols are required for empty Nautilus preflight result")
    first = data[symbol_list[0]]
    idx = _ensure_utc_index(first.index)
    equity = pd.Series(float(account.initial_capital), index=idx, name="equity")
    returns = pd.Series(0.0, index=idx, name="returns")
    positions = pd.DataFrame({f"Position_{symbol}": 0.0 for symbol in symbol_list}, index=idx)
    closes = {}
    for symbol in symbol_list:
        frame = data[symbol]
        close = frame["close"] if "close" in frame else frame["Close"]
        close = close.copy()
        close.index = _ensure_utc_index(close.index)
        closes[f"Close_{symbol}"] = close.reindex(idx).ffill().bfill().astype(float)
    return BacktestResultV2(
        equity=equity,
        returns=returns,
        positions=positions,
        closes=pd.DataFrame(closes, index=idx),
        symbols=symbol_list,
        initial_capital=float(account.initial_capital),
        leverage=float(account.leverage),
        metadata=dict(metadata),
    )


def _annotate_orders_for_depth(orders: Sequence[OrderIntent], params: Dict) -> tuple[OrderIntent, ...]:
    package_type = params.get("package_type") or params.get("input_mode")
    package_id = params.get("package_id") or params.get("basket_id") or params.get("arb_id")
    if package_type is None and package_id is None:
        return tuple(orders)
    out = []
    for order in orders:
        metadata = dict(order.metadata)
        if package_type is not None:
            metadata.setdefault("package_type", str(package_type))
        if package_id is not None:
            metadata.setdefault("package_id", str(package_id))
        out.append(replace(order, metadata=metadata))
    return tuple(out)


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


def _series_to_raw_matrix(signal, idx: pd.DatetimeIndex) -> np.ndarray:
    if isinstance(signal, pd.Series):
        ser = signal
    else:
        ser = pd.Series(signal, index=idx)
    if _series_index_matches(ser, idx):
        values = ser.to_numpy(dtype=np.float64, copy=True)
    else:
        values = _align_series(ser, idx).fillna(0.0).to_numpy(dtype=np.float64, copy=True)
    return np.ascontiguousarray(values.reshape(-1, 1), dtype=np.float64)


def _positions_to_raw_matrix(positions, idx: pd.DatetimeIndex, symbols: Sequence[str]) -> np.ndarray:
    symbol_list = list(symbols)
    if isinstance(positions, pd.DataFrame) and all(symbol in positions.columns for symbol in symbol_list):
        frame = positions.loc[:, symbol_list]
        if _frame_index_matches(frame, idx):
            return np.ascontiguousarray(frame.to_numpy(dtype=np.float64, copy=True), dtype=np.float64)
    elif isinstance(positions, dict):
        exact = True
        cols = []
        for symbol in symbol_list:
            series = positions.get(symbol)
            if not isinstance(series, pd.Series) or not _series_index_matches(series, idx):
                exact = False
                break
            cols.append(series.to_numpy(dtype=np.float64, copy=True))
        if exact:
            return np.ascontiguousarray(np.column_stack(cols), dtype=np.float64)

    pos_map = _positions_to_map(positions)
    return NativePortfolioBackend.prepare_signal_matrix(pos_map, idx, symbol_list)


def _series_index_matches(series: pd.Series, idx: pd.DatetimeIndex) -> bool:
    if not isinstance(series.index, pd.DatetimeIndex) or len(series.index) != len(idx):
        return False
    return bool(np.array_equal(_ensure_utc_index(series.index).asi8, idx.asi8))


def _frame_index_matches(frame: pd.DataFrame, idx: pd.DatetimeIndex) -> bool:
    if not isinstance(frame.index, pd.DatetimeIndex) or len(frame.index) != len(idx):
        return False
    return bool(np.array_equal(_ensure_utc_index(frame.index).asi8, idx.asi8))


def _build_portfolio_orders_for_nautilus(
    datetime_index,
    positions: Dict[str, pd.Series],
    closes: Dict[str, pd.Series],
    alloc_per_trade,
    hedge_type: str,
    use_pyramiding: bool,
    symbols,
) -> tuple[tuple[OrderIntent, ...], pd.DataFrame]:
    ht = str(hedge_type).lower().strip()
    if ht in {"%_equity", "pct_equity", "dca_ladder", "dca"}:
        raise NotImplementedError(
            "Nautilus portfolio validation currently supports pre-scalable modes "
            "('signal_notional', 'notional', 'unit'). Use native portfolio for "
            f"hedge_type={hedge_type!r}."
        )
    idx = _ensure_utc_index(datetime_index)
    alloc = _alloc_map(alloc_per_trade, symbols)
    orders = []
    target_cols = {}
    for symbol in symbols:
        signal = _align_series(positions[symbol], idx)
        close = _align_series(closes[symbol], idx)
        target = compute_target_units(
            hedge_type=hedge_type,
            signal=signal,
            close=close,
            alloc=alloc[symbol],
            use_pyramiding=use_pyramiding,
        ).fillna(0.0)
        target_cols[symbol] = target
        prev = 0.0
        for ts, value in target.items():
            current = float(value)
            delta = current - prev
            if abs(delta) > 1e-12:
                orders.append(
                    OrderIntent(
                        timestamp=ts,
                        symbol=symbol,
                        side=OrderSide.BUY if delta > 0.0 else OrderSide.SELL,
                        order_type=OrderType.MARKET,
                        qty=abs(delta),
                        tif=TimeInForce.IOC,
                        tag=f"portfolio:{ht}",
                        metadata={
                            "portfolio_mode": "matrix",
                            "target_units": current,
                            "previous_units": prev,
                        },
                    )
                )
            prev = current
    out = pd.DataFrame({symbol: target_cols[symbol] for symbol in symbols}, index=idx)
    return tuple(sorted(orders, key=lambda order: pd.Timestamp(order.timestamp).value)), out


def _build_portfolio_orders_from_target_units_for_nautilus(
    target_units: pd.DataFrame,
    symbols,
    tag: str,
) -> tuple[OrderIntent, ...]:
    idx = _ensure_utc_index(target_units.index)
    target = target_units.copy()
    target.index = idx
    orders = []
    for symbol in symbols:
        if symbol not in target:
            raise ValueError(f"target_units missing symbol {symbol!r}")
        prev = 0.0
        for ts, value in target[symbol].fillna(0.0).items():
            current = float(value)
            delta = current - prev
            if abs(delta) > 1e-12:
                orders.append(
                    OrderIntent(
                        timestamp=ts,
                        symbol=symbol,
                        side=OrderSide.BUY if delta > 0.0 else OrderSide.SELL,
                        order_type=OrderType.MARKET,
                        qty=abs(delta),
                        tif=TimeInForce.IOC,
                        tag=tag,
                        metadata={
                            "portfolio_mode": "matrix",
                            "target_units": current,
                            "previous_units": prev,
                        },
                    )
                )
            prev = current
    return tuple(sorted(orders, key=lambda order: (pd.Timestamp(order.timestamp).value, str(order.symbol))))


def _alloc_map(value, symbols) -> Dict[str, float]:
    if isinstance(value, dict):
        return {symbol: float(value.get(symbol, 100_000.0)) for symbol in symbols}
    return {symbol: float(value) for symbol in symbols}


def _print_order_logs(result, mode: str = "fills_only", limit: int = 500) -> None:
    try:
        from .reporting.nautilus_bundle import format_nautilus_event_log

        orders_report = result.metadata.get("orders_report")
        if orders_report is None:
            orders_report = result.metadata.get("order_report")
        lines = format_nautilus_event_log(
            fills_report=result.metadata.get("fills_report"),
            orders_report=orders_report,
            positions=getattr(result, "positions", None),
            mode=mode,
            limit=int(limit),
        )
    except Exception as exc:
        print(f"Order log unavailable: {type(exc).__name__}: {exc}")
        return
    for line in lines:
        print(line)


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
