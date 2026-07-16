"""
quantbt.backends.native_event
-----------------------------
Native event-driven backend using a Numba matching kernel.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Union

import numpy as np
import pandas as pd

from ..core.event import (
    ORDER_TYPE_LIMIT,
    ORDER_TYPE_MARKET,
    TIF_FOK,
    TIF_GTC,
    TIF_GTD,
    TIF_IOC,
    _engine_event_v1,
)
from ..core.arbitrage import (
    ArbitrageSpec,
    ArbitragePlan,
    BasisArbitrageSpec,
    CalendarSpreadSpec,
    CrossExchangeArbSpec,
    FundingArbitrageSpec,
    IndexBasketArbSpec,
    OptionsVolArbSpec,
    PackageExecutionKind,
    PackageRejection,
    SizingPolicyKind,
    SpotPerpCashCarrySpec,
    StatArbPairSpec,
    TriangularArbSpec,
    build_arbitrage_order_plan,
)
from ..core.basket import build_frozen_basket_orders
from ..core.order_compiler import compile_order_intents
from ..core.orders import Fill, OrderIntent
from ..core.preprocessor import align_series, build_arrays, make_funding_mask, prepare_funding, validate_datetime
from ..core.results import BacktestResultV2
from ..core.schema import (
    AccountConfig,
    BasketLegSpec,
    BasketSpec,
    ExecutionConfig,
    LiquiditySide,
    OrderSide,
    OrderType,
    TimeInForce,
)


@dataclass(frozen=True)
class NativeEventConfig:
    account: AccountConfig
    execution: ExecutionConfig = field(default_factory=ExecutionConfig)
    fee_rate: Union[float, Dict[str, float]] = 0.0
    use_funding: bool = True

    def __post_init__(self) -> None:
        if isinstance(self.fee_rate, dict):
            if any(float(rate) < 0.0 for rate in self.fee_rate.values()):
                raise ValueError("fee_rate must be >= 0")
        elif float(self.fee_rate) < 0.0:
            raise ValueError("fee_rate must be >= 0")


class NativeEventBackend:
    """
    Event-driven backend for explicit OrderIntent sequences.

    Phase 3 supports market and limit orders on OHLC bars. Limit orders fill at
    the order price when high/low touches the level. Market orders fill at the
    current close with configured slippage.
    """

    def __init__(self, config: NativeEventConfig):
        self.config = config

    def run_orders(
        self,
        datetime_index: Union[pd.DatetimeIndex, pd.Series],
        orders: Sequence[OrderIntent],
        closes: Dict[str, pd.Series],
        highs: Optional[Dict[str, pd.Series]] = None,
        lows: Optional[Dict[str, pd.Series]] = None,
        funding_rate: Union[float, pd.Series, Dict] = 0.0,
        contract_size: Union[float, Dict[str, float]] = 1.0,
        leverage: Optional[Union[float, Dict[str, float]]] = None,
        fee_rate: Optional[Union[float, Dict[str, float]]] = None,
        symbols: Optional[List[str]] = None,
    ) -> BacktestResultV2:
        idx = validate_datetime(datetime_index)
        symbol_list = symbols or list(closes.keys())
        symbol_to_col = {s: j for j, s in enumerate(symbol_list)}

        close_dict = align_series(closes, symbol_list, idx)
        high_dict = align_series(highs, symbol_list, idx, fallback=close_dict)
        low_dict = align_series(lows, symbol_list, idx, fallback=close_dict)
        zero_signals = {s: pd.Series(0.0, index=idx) for s in symbol_list}
        funding_dict = prepare_funding(funding_rate if self.config.use_funding else 0.0, symbol_list, idx)
        closes_m, highs_m, lows_m, _, funding_m, is_funding = build_arrays(
            symbols=symbol_list,
            idx=idx,
            closes_dict=close_dict,
            highs_dict=high_dict,
            lows_dict=low_dict,
            signals_dict=zero_signals,
            funding_dict=funding_dict,
        )

        compiled_orders = compile_order_intents(idx=idx, orders=orders, symbol_to_col=symbol_to_col)
        n_orders = compiled_orders.n_orders

        contract_sizes = self._per_symbol_array(contract_size, symbol_list, default=1.0)
        leverages = self._per_symbol_array(
            self.config.account.leverage if leverage is None else leverage,
            symbol_list,
            default=self.config.account.leverage,
        )
        fee_rates = self._per_symbol_array(
            self.config.fee_rate if fee_rate is None else fee_rate,
            symbol_list,
            default=0.0,
        )

        (
            equity_arr,
            pos_arr,
            fee_arr,
            turnover_arr,
            funding_arr,
            init_margin_arr,
            maint_margin_arr,
            rejected_bar,
            canceled_bar,
            order_status,
            reject_code,
            fill_bar,
            fill_qty,
            fill_price,
            fill_fee,
            liq_flag,
            liq_idx,
            liq_reason,
        ) = _engine_event_v1(
            n_bars=len(idx),
            n_syms=len(symbol_list),
            n_orders=n_orders,
            order_ptr=compiled_orders.order_ptr,
            order_symbol=compiled_orders.order_symbol,
            order_side=compiled_orders.order_side,
            order_type=compiled_orders.order_type,
            order_qty=compiled_orders.order_qty,
            order_price=compiled_orders.order_price,
            order_tif=compiled_orders.order_tif,
            highs=highs_m,
            lows=lows_m,
            closes=closes_m,
            funding_rates=funding_m,
            is_funding_bar=is_funding,
            init_capital=self.config.account.initial_capital,
            leverages=leverages,
            maint_ratio=self.config.account.maintenance_ratio,
            fee_rates=fee_rates,
            contract_sizes=contract_sizes,
            slippage=self.config.execution.slippage_rate,
            use_funding=bool(self.config.use_funding),
        )

        fills = self._build_fills(compiled_orders.sorted_orders, idx, fill_bar, fill_qty, fill_price, fill_fee)
        equity = pd.Series(equity_arr, index=idx, name="equity")
        positions = pd.DataFrame(
            {f"Position_{s}": pos_arr[:, j] for j, s in enumerate(symbol_list)},
            index=idx,
        )
        close_df = pd.DataFrame(
            {f"Close_{s}": closes_m[:, j] for j, s in enumerate(symbol_list)},
            index=idx,
        )

        diagnostics = pd.DataFrame(
            {
                "turnover": turnover_arr,
                "rejected_orders": rejected_bar,
                "canceled_orders": canceled_bar,
            },
            index=idx,
        )
        order_report = pd.DataFrame(
            {
                "original_index": compiled_orders.original_index,
                "status": order_status,
                "reject_code": reject_code,
                "fill_bar": fill_bar,
                "fill_qty": fill_qty,
                "fill_price": fill_price,
                "fill_fee": fill_fee,
            }
        ).sort_values("original_index", kind="stable")

        return BacktestResultV2(
            equity=equity,
            returns=equity.pct_change().fillna(0.0),
            positions=positions,
            closes=close_df,
            symbols=symbol_list,
            initial_capital=self.config.account.initial_capital,
            leverage=float(np.mean(leverages)),
            liquidated=bool(liq_flag),
            liquidation_bar=int(liq_idx),
            orders=tuple(orders),
            fills=tuple(fills),
            fees=pd.Series(fee_arr, index=idx, name="fees"),
            funding=pd.Series(funding_arr, index=idx, name="funding"),
            margin=pd.DataFrame(
                {
                    "initial_margin": init_margin_arr,
                    "maintenance_margin": maint_margin_arr,
                },
                index=idx,
            ),
            diagnostics=diagnostics,
            metadata={
                "backend": "native_event",
                "engine": "event_v1",
                "fee_rate_oneway": self._fee_rate_metadata(fee_rates, symbol_list),
                "slippage_bps": self.config.execution.slippage_bps,
                "order_report": order_report,
                "initial_buying_power": self.config.account.initial_capital * float(np.mean(leverages)),
                "liquidation_reason": int(liq_reason),
            },
        )

    def run_basket(
        self,
        datetime_index: Union[pd.DatetimeIndex, pd.Series],
        basket: BasketSpec,
        signal: pd.Series,
        closes: Dict[str, pd.Series],
        highs: Optional[Dict[str, pd.Series]] = None,
        lows: Optional[Dict[str, pd.Series]] = None,
        hedge_ratios: Optional[Dict[str, pd.Series]] = None,
        funding_rate: Union[float, pd.Series, Dict] = 0.0,
        contract_size: Union[float, Dict[str, float]] = 1.0,
        leverage: Optional[Union[float, Dict[str, float]]] = None,
        fee_rate: Optional[Union[float, Dict[str, float]]] = None,
        rebalance_threshold: Optional[float] = None,
        symbols: Optional[List[str]] = None,
    ) -> BacktestResultV2:
        """
        Build frozen basket orders from a scalar signal and execute them.

        Basket legs are sized once on signal transitions and held constant until
        the next transition. Phase 4 carries all-or-none policy in metadata; the
        current matching kernel executes generated leg orders best-effort.
        """
        plan = build_frozen_basket_orders(
            datetime_index=datetime_index,
            basket=basket,
            signal=signal,
            closes=closes,
            hedge_ratios=hedge_ratios,
            order_type=OrderType.MARKET,
            tif=TimeInForce.IOC,
            rebalance_threshold=rebalance_threshold,
        )
        result = self.run_orders(
            datetime_index=datetime_index,
            orders=plan.orders,
            closes=closes,
            highs=highs,
            lows=lows,
            funding_rate=funding_rate,
            contract_size=contract_size,
            leverage=leverage,
            fee_rate=fee_rate,
            symbols=symbols,
        )
        result.metadata["basket_plan"] = plan
        result.metadata["basket_target_units"] = plan.target_units
        result.metadata["basket_execution_policy"] = basket.execution_policy.value
        return result

    def run_stat_arb_pair_arbitrage(
        self,
        datetime_index: Union[pd.DatetimeIndex, pd.Series],
        spec: StatArbPairSpec,
        signal: pd.Series,
        closes: Dict[str, pd.Series],
        highs: Optional[Dict[str, pd.Series]] = None,
        lows: Optional[Dict[str, pd.Series]] = None,
        hedge_ratios: Optional[Dict[str, pd.Series]] = None,
        funding_rate: Union[float, pd.Series, Dict] = 0.0,
        contract_size: Optional[Union[float, Dict[str, float]]] = None,
        leverage: Optional[Union[float, Dict[str, float]]] = None,
    ) -> BacktestResultV2:
        """
        Execute a Phase D stat-arb pair through the frozen basket planner.

        Dynamic hedge-ratio series are sampled at entry and held frozen until
        exit. If `spec.hedge_policy.rebalance_threshold` is set, only hedge
        ratio drift beyond that threshold can trigger a package rebalance; price
        movement alone does not create micro-rebalancing orders.
        """
        if not isinstance(spec, StatArbPairSpec):
            raise TypeError("run_stat_arb_pair_arbitrage requires a StatArbPairSpec")
        basket = self._stat_arb_basket_from_spec(spec)
        idx = validate_datetime(datetime_index)
        symbols = [leg.symbol for leg in spec.legs]
        close_dict = align_series(closes, symbols, idx)
        contract_sizes = self._contract_size_for_spec(spec, contract_size)
        fee_rates = self._fee_rate_for_spec(spec)
        rebalance_threshold = spec.hedge_policy.rebalance_threshold
        if not spec.hedge_policy.freeze_on_entry and rebalance_threshold is None:
            rebalance_threshold = 0.0

        plan = build_frozen_basket_orders(
            datetime_index=idx,
            basket=basket,
            signal=signal,
            closes=close_dict,
            hedge_ratios=hedge_ratios,
            order_type=OrderType.MARKET,
            tif=TimeInForce.IOC,
            rebalance_threshold=rebalance_threshold,
        )
        arb_plan = self._apply_atomic_package_margin_policy(
            idx=idx,
            plan=ArbitragePlan(
                spec=spec,
                orders=plan.orders,
                target_units=plan.target_units,
                signals=plan.signals,
                entry_ratios=plan.entry_ratios,
                rejections=(),
                metadata=plan.metadata,
            ),
            closes=close_dict,
            contract_sizes=contract_sizes,
            fee_rates=fee_rates,
            leverage=leverage,
        )

        result = self.run_orders(
            datetime_index=idx,
            orders=arb_plan.orders,
            closes=close_dict,
            highs=highs,
            lows=lows,
            funding_rate=funding_rate,
            contract_size=contract_sizes,
            leverage=leverage,
            fee_rate=fee_rates,
            symbols=symbols,
        )
        beta_drift_report = self._stat_arb_beta_drift_report(
            idx=idx,
            spec=spec,
            plan=arb_plan,
            rebalance_threshold=rebalance_threshold,
        )
        result.metadata.update(
            {
                "backend": "native_event",
                "engine": "event_v1_stat_arb_pair",
                "arb_id": spec.arb_id,
                "arb_type": spec.arb_type.value,
                "arbitrage_plan": arb_plan,
                "package_target_units": arb_plan.target_units,
                "package_rejection_report": arb_plan.rejection_report,
                "basket_plan": plan,
                "basket_target_units": arb_plan.target_units,
                "beta_drift_report": beta_drift_report,
                "rebalance_threshold": rebalance_threshold,
                "fee_rate_oneway": fee_rates,
                "contract_size": contract_sizes,
            }
        )
        return result

    def run_basis_arbitrage(
        self,
        datetime_index: Union[pd.DatetimeIndex, pd.Series],
        spec: BasisArbitrageSpec,
        signal: pd.Series,
        closes: Dict[str, pd.Series],
        highs: Optional[Dict[str, pd.Series]] = None,
        lows: Optional[Dict[str, pd.Series]] = None,
        funding_rate: Union[float, pd.Series, Dict] = 0.0,
        contract_size: Optional[Union[float, Dict[str, float]]] = None,
        leverage: Optional[Union[float, Dict[str, float]]] = None,
        hedge_ratios: Optional[Dict[str, pd.Series]] = None,
    ) -> BacktestResultV2:
        """
        Execute a minimal native-event USDM linear basis arbitrage backtest.

        Phase C models a package trade: signal transitions generate all leg
        orders at the same timestamp, units are frozen until the next signal
        transition, and reports decompose package PnL into leg-level mark,
        fill, fee, and funding components.
        """
        if not isinstance(spec, BasisArbitrageSpec):
            raise TypeError("run_basis_arbitrage requires a BasisArbitrageSpec")

        idx = validate_datetime(datetime_index)
        symbols = [leg.symbol for leg in spec.legs]
        close_dict = align_series(closes, symbols, idx)
        contract_sizes = self._contract_size_for_spec(spec, contract_size)
        fee_rates = self._fee_rate_for_spec(spec)
        basis_funding = self._funding_for_spec(spec, funding_rate)

        plan = build_arbitrage_order_plan(
            datetime_index=idx,
            spec=spec,
            signal=signal,
            closes=close_dict,
            hedge_ratios=hedge_ratios,
        )
        plan = self._apply_atomic_package_margin_policy(idx, plan, close_dict, contract_sizes, fee_rates, leverage)
        result = self.run_orders(
            datetime_index=idx,
            orders=plan.orders,
            closes=close_dict,
            highs=highs,
            lows=lows,
            funding_rate=basis_funding,
            contract_size=contract_sizes,
            leverage=leverage,
            fee_rate=fee_rates,
            symbols=symbols,
        )

        funding_dict = prepare_funding(basis_funding if self.config.use_funding else 0.0, symbols, idx)
        leg_pnl_report = self._basis_leg_pnl_report(
            idx=idx,
            spec=spec,
            result=result,
            closes=close_dict,
            funding=funding_dict,
            contract_sizes=contract_sizes,
        )
        package_pnl = leg_pnl_report.groupby("timestamp", sort=False)["total_pnl"].sum().reindex(idx, fill_value=0.0)
        package_report = pd.DataFrame(
            {
                "package_pnl": package_pnl,
                "equity_delta": result.equity.diff().fillna(0.0),
            },
            index=idx,
        )
        package_report["pnl_residual"] = package_report["equity_delta"] - package_report["package_pnl"]
        spread_report = self._basis_spread_report(idx, spec, close_dict, plan.target_units)

        diagnostics = result.diagnostics.copy()
        diagnostics["package_pnl"] = package_report["package_pnl"]
        diagnostics["package_pnl_residual"] = package_report["pnl_residual"]
        result.diagnostics = diagnostics
        result.metadata.update(
            {
                "backend": "native_event",
                "engine": "event_v1_basis_arbitrage",
                "arb_id": spec.arb_id,
                "arb_type": spec.arb_type.value,
                "arbitrage_plan": plan,
                "package_target_units": plan.target_units,
                "package_rejection_report": plan.rejection_report,
                "spread_report": spread_report,
                "leg_pnl_report": leg_pnl_report,
                "package_pnl_report": package_report,
                "fee_rate_oneway": fee_rates,
                "contract_size": contract_sizes,
            }
        )
        return result

    def run_package_arbitrage(
        self,
        datetime_index: Union[pd.DatetimeIndex, pd.Series],
        spec: ArbitrageSpec,
        signal: pd.Series,
        closes: Dict[str, pd.Series],
        highs: Optional[Dict[str, pd.Series]] = None,
        lows: Optional[Dict[str, pd.Series]] = None,
        funding_rate: Union[float, pd.Series, Dict] = 0.0,
        contract_size: Optional[Union[float, Dict[str, float]]] = None,
        leverage: Optional[Union[float, Dict[str, float]]] = None,
        hedge_ratios: Optional[Dict[str, pd.Series]] = None,
    ) -> BacktestResultV2:
        """
        Execute Phase G package-style advanced arbitrage specs.

        This route is intentionally limited to advanced arbitrage types whose
        execution can be represented as frozen package target units. Types that
        require sequencing, cross-venue account state, or options Greeks remain
        explicit NotImplemented paths.
        """
        unsupported = (CrossExchangeArbSpec, TriangularArbSpec, OptionsVolArbSpec)
        if isinstance(spec, unsupported):
            raise NotImplementedError(f"{type(spec).__name__} requires a specialized Phase G+ engine")
        supported = (CalendarSpreadSpec, FundingArbitrageSpec, SpotPerpCashCarrySpec, IndexBasketArbSpec)
        if not isinstance(spec, supported):
            raise TypeError("run_package_arbitrage requires a Phase G package-style arbitrage spec")

        idx = validate_datetime(datetime_index)
        symbols = [leg.symbol for leg in spec.legs]
        close_dict = align_series(closes, symbols, idx)
        contract_sizes = self._contract_size_for_spec(spec, contract_size)
        fee_rates = self._fee_rate_for_spec(spec)
        package_funding = self._funding_for_spec(spec, funding_rate)
        plan = build_arbitrage_order_plan(
            datetime_index=idx,
            spec=spec,
            signal=signal,
            closes=close_dict,
            hedge_ratios=hedge_ratios,
        )
        plan = self._apply_atomic_package_margin_policy(idx, plan, close_dict, contract_sizes, fee_rates, leverage)
        result = self.run_orders(
            datetime_index=idx,
            orders=plan.orders,
            closes=close_dict,
            highs=highs,
            lows=lows,
            funding_rate=package_funding,
            contract_size=contract_sizes,
            leverage=leverage,
            fee_rate=fee_rates,
            symbols=symbols,
        )

        funding_dict = prepare_funding(package_funding if self.config.use_funding else 0.0, symbols, idx)
        leg_pnl_report = self._basis_leg_pnl_report(
            idx=idx,
            spec=spec,
            result=result,
            closes=close_dict,
            funding=funding_dict,
            contract_sizes=contract_sizes,
        )
        package_pnl = leg_pnl_report.groupby("timestamp", sort=False)["total_pnl"].sum().reindex(idx, fill_value=0.0)
        package_report = pd.DataFrame(
            {
                "package_pnl": package_pnl,
                "equity_delta": result.equity.diff().fillna(0.0),
            },
            index=idx,
        )
        package_report["pnl_residual"] = package_report["equity_delta"] - package_report["package_pnl"]
        diagnostics = result.diagnostics.copy()
        diagnostics["package_pnl"] = package_report["package_pnl"]
        diagnostics["package_pnl_residual"] = package_report["pnl_residual"]
        result.diagnostics = diagnostics
        result.metadata.update(
            {
                "backend": "native_event",
                "engine": f"event_v1_{spec.arb_type.value}",
                "arb_id": spec.arb_id,
                "arb_type": spec.arb_type.value,
                "arbitrage_plan": plan,
                "package_target_units": plan.target_units,
                "package_rejection_report": plan.rejection_report,
                "spread_report": self._basis_spread_report(idx, spec, close_dict, plan.target_units),
                "leg_pnl_report": leg_pnl_report,
                "package_pnl_report": package_report,
                "carry_report": self._carry_report(idx, spec, result, close_dict, funding_dict, contract_sizes),
                "fee_rate_oneway": fee_rates,
                "contract_size": contract_sizes,
            }
        )
        return result

    @staticmethod
    def _bar_index(idx: pd.DatetimeIndex, timestamp) -> int:
        ts = pd.Timestamp(timestamp)
        if ts.tz is None:
            ts = ts.tz_localize("UTC")
        else:
            ts = ts.tz_convert("UTC")
        pos = idx.searchsorted(ts, side="left")
        if pos >= len(idx):
            raise ValueError("order timestamp is after the available data")
        return int(pos)

    def _apply_atomic_package_margin_policy(
        self,
        idx: pd.DatetimeIndex,
        plan: ArbitragePlan,
        closes: Dict[str, pd.Series],
        contract_sizes: Dict[str, float],
        fee_rates: Dict[str, float],
        leverage: Optional[Union[float, Dict[str, float]]],
    ) -> ArbitragePlan:
        spec = plan.spec
        if spec.execution_policy.kind not in (PackageExecutionKind.ATOMIC_ALL_OR_NONE, PackageExecutionKind.BEST_EFFORT):
            return plan

        symbols = [leg.symbol for leg in spec.legs]
        current_units = {symbol: 0.0 for symbol in symbols}
        equity = float(self.config.account.initial_capital)
        target_rows = []
        orders = []
        rejections = list(plan.rejections)
        leverages = self._leverage_mapping(leverage, symbols)
        slippage = self.config.execution.slippage_rate

        for i, ts in enumerate(idx):
            if i > 0:
                prev_ts = idx[i - 1]
                for symbol in symbols:
                    units = current_units[symbol]
                    if units != 0.0:
                        equity += units * (
                            float(closes[symbol].loc[ts]) - float(closes[symbol].loc[prev_ts])
                        ) * float(contract_sizes[symbol])

            original_desired = {symbol: float(plan.target_units.loc[ts, symbol]) for symbol in symbols}
            changed_symbols = [
                symbol for symbol in symbols
                if abs(original_desired[symbol] - current_units[symbol]) > 1e-12
            ]
            if changed_symbols:
                if spec.execution_policy.kind is PackageExecutionKind.ATOMIC_ALL_OR_NONE:
                    allowed, details = self._atomic_package_has_margin(
                        ts=ts,
                        symbols=symbols,
                        current_units=current_units,
                        desired_units=original_desired,
                        closes=closes,
                        contract_sizes=contract_sizes,
                        fee_rates=fee_rates,
                        leverages=leverages,
                        equity=equity,
                        slippage=slippage,
                    )
                    if not allowed:
                        rejections.append(
                            PackageRejection(
                                timestamp=ts,
                                arb_id=spec.arb_id,
                                reason="insufficient_margin_atomic",
                                failed_legs=tuple(changed_symbols),
                                metadata={"details": details, "policy": spec.execution_policy.kind.value},
                            )
                        )
                    else:
                        self._append_package_orders(orders, ts, spec, symbols, current_units, original_desired)
                        equity -= float(details.get("cost", 0.0))
                        current_units = original_desired
                else:
                    for symbol in symbols:
                        if abs(original_desired[symbol] - current_units[symbol]) <= 1e-12:
                            continue
                        candidate_units = dict(current_units)
                        candidate_units[symbol] = original_desired[symbol]
                        allowed, details = self._atomic_package_has_margin(
                            ts=ts,
                            symbols=symbols,
                            current_units=current_units,
                            desired_units=candidate_units,
                            closes=closes,
                            contract_sizes=contract_sizes,
                            fee_rates=fee_rates,
                            leverages=leverages,
                            equity=equity,
                            slippage=slippage,
                        )
                        if not allowed:
                            rejections.append(
                                PackageRejection(
                                    timestamp=ts,
                                    arb_id=spec.arb_id,
                                    reason="insufficient_margin_best_effort",
                                    failed_legs=(symbol,),
                                    metadata={"details": details, "policy": spec.execution_policy.kind.value},
                                )
                            )
                            continue
                        self._append_package_orders(orders, ts, spec, [symbol], current_units, candidate_units)
                        equity -= float(details.get("cost", 0.0))
                        current_units = candidate_units

            target_rows.append({symbol: current_units[symbol] for symbol in symbols})

        return ArbitragePlan(
            spec=spec,
            orders=tuple(orders),
            target_units=pd.DataFrame(target_rows, index=idx),
            signals=plan.signals,
            entry_ratios=plan.entry_ratios,
            rejections=tuple(rejections),
            metadata={**plan.metadata, "execution_margin_policy": "package_preflight"},
        )

    @staticmethod
    def _append_package_orders(
        orders: List[OrderIntent],
        ts,
        spec: ArbitrageSpec,
        symbols: List[str],
        current_units: Dict[str, float],
        desired_units: Dict[str, float],
    ) -> None:
        for symbol in symbols:
            delta = desired_units[symbol] - current_units[symbol]
            if abs(delta) <= 1e-12:
                continue
            side = OrderSide.BUY if delta > 0.0 else OrderSide.SELL
            orders.append(
                OrderIntent(
                    timestamp=ts,
                    symbol=symbol,
                    side=side,
                    order_type=spec.execution_policy.order_type,
                    qty=abs(delta),
                    tif=spec.execution_policy.tif,
                    tag=spec.arb_id,
                    metadata={
                        "arb_id": spec.arb_id,
                        "arb_type": spec.arb_type.value,
                        "package_policy": spec.execution_policy.kind.value,
                        "hedge_policy": spec.hedge_policy.kind.value,
                        "sizing_policy": spec.sizing_policy.kind.value,
                        "target_units": desired_units[symbol],
                        "previous_units": current_units[symbol],
                    },
                )
            )

    def _atomic_package_has_margin(
        self,
        ts,
        symbols: List[str],
        current_units: Dict[str, float],
        desired_units: Dict[str, float],
        closes: Dict[str, pd.Series],
        contract_sizes: Dict[str, float],
        fee_rates: Dict[str, float],
        leverages: Dict[str, float],
        equity: float,
        slippage: float,
    ) -> tuple[bool, Dict[str, float]]:
        cur_im = 0.0
        margin_delta_sum = 0.0
        cost_sum = 0.0
        for symbol in symbols:
            close_price = float(closes[symbol].loc[ts])
            cs = float(contract_sizes[symbol])
            lev = float(leverages[symbol])
            current = float(current_units[symbol])
            target = float(desired_units[symbol])
            cur_im += abs(current) * close_price * cs / lev
            delta = target - current
            if abs(delta) <= 1e-12:
                continue
            exec_price = close_price * (1.0 + slippage if delta > 0.0 else 1.0 - slippage)
            old_im = abs(current) * close_price * cs / lev
            new_im = abs(target) * exec_price * cs / lev
            margin_delta_sum += new_im - old_im
            cost_sum += abs(delta) * exec_price * cs * float(fee_rates[symbol])
            cost_sum += abs(delta) * abs(exec_price - close_price) * cs

        available = max(0.0, float(equity) - cur_im)
        required = cost_sum + max(0.0, margin_delta_sum)
        return required <= available + 1e-12, {
            "available": available,
            "required": required,
            "current_initial_margin": cur_im,
            "margin_delta": margin_delta_sum,
            "cost": cost_sum,
        }

    def _leverage_mapping(self, leverage, symbols: List[str]) -> Dict[str, float]:
        default = float(self.config.account.leverage)
        if isinstance(leverage, dict):
            return {symbol: float(leverage.get(symbol, default)) for symbol in symbols}
        if leverage is None:
            return {symbol: default for symbol in symbols}
        return {symbol: float(leverage) for symbol in symbols}

    @staticmethod
    def _side_code(side: OrderSide) -> int:
        return 1 if side is OrderSide.BUY else -1

    @staticmethod
    def _order_type_code(order_type: OrderType) -> int:
        if order_type is OrderType.MARKET:
            return ORDER_TYPE_MARKET
        if order_type is OrderType.LIMIT:
            return ORDER_TYPE_LIMIT
        raise NotImplementedError(f"unsupported order_type={order_type!r}")

    @staticmethod
    def _tif_code(tif: TimeInForce) -> int:
        if tif is TimeInForce.GTC:
            return TIF_GTC
        if tif is TimeInForce.IOC:
            return TIF_IOC
        if tif is TimeInForce.FOK:
            return TIF_FOK
        if tif is TimeInForce.GTD:
            return TIF_GTD
        raise NotImplementedError(f"unsupported tif={tif!r}")

    @staticmethod
    def _per_symbol_array(value, symbols: List[str], default: float) -> np.ndarray:
        if isinstance(value, dict):
            return np.array([float(value.get(s, default)) for s in symbols], dtype=np.float64)
        return np.full(len(symbols), float(value), dtype=np.float64)

    @staticmethod
    def _fee_rate_metadata(fee_rates: np.ndarray, symbols: List[str]):
        if len(fee_rates) == 0:
            return 0.0
        if np.allclose(fee_rates, fee_rates[0]):
            return float(fee_rates[0])
        return {symbol: float(fee_rates[i]) for i, symbol in enumerate(symbols)}

    def _fee_rate_for_spec(self, spec: ArbitrageSpec) -> Dict[str, float]:
        default_rates = self.config.fee_rate
        out: Dict[str, float] = {}
        for leg in spec.legs:
            if leg.fee_rate is not None:
                out[leg.symbol] = float(leg.fee_rate)
            elif isinstance(default_rates, dict):
                out[leg.symbol] = float(default_rates.get(leg.symbol, 0.0))
            else:
                out[leg.symbol] = float(default_rates)
        return out

    @staticmethod
    def _contract_size_for_spec(
        spec: ArbitrageSpec,
        contract_size: Optional[Union[float, Dict[str, float]]],
    ) -> Dict[str, float]:
        out = {leg.symbol: float(leg.contract_size) for leg in spec.legs}
        if contract_size is None:
            return out
        if isinstance(contract_size, dict):
            out.update({symbol: float(value) for symbol, value in contract_size.items()})
            return out
        return {leg.symbol: float(contract_size) for leg in spec.legs}

    @staticmethod
    def _funding_for_spec(spec: ArbitrageSpec, funding_rate: Union[float, pd.Series, Dict]):
        funding_symbols = {leg.symbol for leg in spec.legs if leg.funding_enabled}
        if isinstance(funding_rate, dict):
            return {
                leg.symbol: funding_rate.get(leg.symbol, 0.0) if leg.symbol in funding_symbols else 0.0
                for leg in spec.legs
            }
        return {leg.symbol: funding_rate if leg.symbol in funding_symbols else 0.0 for leg in spec.legs}

    @staticmethod
    def _stat_arb_basket_from_spec(spec: StatArbPairSpec) -> BasketSpec:
        if spec.sizing_policy.kind is not SizingPolicyKind.TARGET_GROSS_NOTIONAL:
            raise NotImplementedError("Phase D StatArbPairSpec requires target_gross_notional sizing")
        return BasketSpec(
            basket_id=spec.arb_id,
            legs=tuple(BasketLegSpec(symbol=leg.symbol, ratio=float(leg.ratio)) for leg in spec.legs),
            gross_notional=float(spec.sizing_policy.notional),
            freeze_hedge=bool(spec.hedge_policy.freeze_on_entry),
            hedged_margin_offset=float(spec.margin_model.hedged_margin_offset),
            metadata={
                "arb_type": spec.arb_type.value,
                "hedge_policy": spec.hedge_policy.kind.value,
                "sizing_policy": spec.sizing_policy.kind.value,
            },
        )

    @staticmethod
    def _stat_arb_beta_drift_report(
        idx: pd.DatetimeIndex,
        spec: StatArbPairSpec,
        plan,
        rebalance_threshold: Optional[float],
    ) -> pd.DataFrame:
        symbols = [leg.symbol for leg in spec.legs]
        reference_symbol = symbols[0]
        rows = []
        for ts in idx:
            ref_units = float(plan.target_units.loc[ts, reference_symbol])
            ref_ratio = float(plan.entry_ratios.loc[ts, reference_symbol])
            active = abs(ref_units) > 1e-12 and abs(ref_ratio) > 1e-12
            for symbol in symbols:
                units = float(plan.target_units.loc[ts, symbol])
                current_ratio = float(plan.entry_ratios.loc[ts, symbol])
                if active:
                    frozen_ratio_to_ref = units / ref_units
                    current_ratio_to_ref = current_ratio / ref_ratio
                    abs_drift = abs(current_ratio_to_ref - frozen_ratio_to_ref)
                    rel_drift = abs_drift / max(abs(frozen_ratio_to_ref), 1e-12)
                else:
                    frozen_ratio_to_ref = 0.0
                    current_ratio_to_ref = 0.0
                    abs_drift = 0.0
                    rel_drift = 0.0
                rows.append(
                    {
                        "timestamp": ts,
                        "symbol": symbol,
                        "reference_symbol": reference_symbol,
                        "target_units": units,
                        "frozen_ratio_to_ref": frozen_ratio_to_ref,
                        "current_ratio_to_ref": current_ratio_to_ref,
                        "abs_beta_drift": abs_drift,
                        "rel_beta_drift": rel_drift,
                        "rebalance_threshold": rebalance_threshold,
                        "breached": (
                            rebalance_threshold is not None
                            and rel_drift > rebalance_threshold
                            and symbol != reference_symbol
                        ),
                    }
                )
        return pd.DataFrame(rows)

    def _basis_leg_pnl_report(
        self,
        idx: pd.DatetimeIndex,
        spec: BasisArbitrageSpec,
        result: BacktestResultV2,
        closes: Dict[str, pd.Series],
        funding: Dict[str, pd.Series],
        contract_sizes: Dict[str, float],
    ) -> pd.DataFrame:
        fill_rows = {}
        for fill in result.fills:
            ts = pd.Timestamp(fill.timestamp)
            if ts.tz is None:
                ts = ts.tz_localize("UTC")
            else:
                ts = ts.tz_convert("UTC")
            key = (ts, fill.symbol)
            fee, fill_pnl = fill_rows.get(key, (0.0, 0.0))
            close_price = float(closes[fill.symbol].loc[ts])
            cs = float(contract_sizes[fill.symbol])
            fill_pnl += fill.signed_qty * (close_price - float(fill.price)) * cs
            fee += float(fill.fee)
            fill_rows[key] = (fee, fill_pnl)

        funding_mask = make_funding_mask(idx)
        cumulative = {leg.symbol: 0.0 for leg in spec.legs}
        rows = []
        for i, ts in enumerate(idx):
            for leg in spec.legs:
                symbol = leg.symbol
                cs = float(contract_sizes[symbol])
                close_price = float(closes[symbol].iloc[i])
                prev_pos = 0.0 if i == 0 else float(result.positions[f"Position_{symbol}"].iloc[i - 1])
                units = float(result.positions[f"Position_{symbol}"].iloc[i])
                price_pnl = 0.0
                if i > 0:
                    price_pnl = prev_pos * (close_price - float(closes[symbol].iloc[i - 1])) * cs
                funding_cost = 0.0
                if self.config.use_funding and funding_mask[i]:
                    funding_cost = prev_pos * close_price * cs * float(funding[symbol].iloc[i])
                fee, fill_pnl = fill_rows.get((ts, symbol), (0.0, 0.0))
                total_pnl = price_pnl + fill_pnl - fee - funding_cost
                cumulative[symbol] += total_pnl
                rows.append(
                    {
                        "timestamp": ts,
                        "symbol": symbol,
                        "role": leg.role,
                        "units": units,
                        "close": close_price,
                        "notional": abs(units) * close_price * cs,
                        "price_pnl": price_pnl,
                        "fill_pnl": fill_pnl,
                        "fee": fee,
                        "funding_pnl": -funding_cost,
                        "total_pnl": total_pnl,
                        "cumulative_pnl": cumulative[symbol],
                    }
                )
        return pd.DataFrame(rows)

    @staticmethod
    def _basis_spread_report(
        idx: pd.DatetimeIndex,
        spec: ArbitrageSpec,
        closes: Dict[str, pd.Series],
        target_units: pd.DataFrame,
    ) -> pd.DataFrame:
        symbols = [leg.symbol for leg in spec.legs]
        base_symbol = spec.spread_formula.base_symbol
        quote_symbol = spec.spread_formula.quote_symbol
        if base_symbol is None:
            base_symbol = next((leg.symbol for leg in spec.legs if leg.ratio < 0.0), symbols[0])
        if quote_symbol is None:
            quote_symbol = next((leg.symbol for leg in spec.legs if leg.ratio > 0.0), symbols[-1])

        base_close = closes[base_symbol].astype(float)
        quote_close = closes[quote_symbol].astype(float)
        spread = quote_close - base_close
        ratio_spread = quote_close / base_close.replace(0.0, np.nan) - 1.0
        expiry = next((leg.expiry for leg in spec.legs if leg.symbol == quote_symbol and leg.expiry is not None), None)
        if expiry is None:
            expiry = next((leg.expiry for leg in spec.legs if leg.expiry is not None), None)
        if expiry is None:
            annualized = pd.Series(np.nan, index=idx, dtype=float)
        else:
            days_to_expiry = pd.Series(
                [(expiry - ts).total_seconds() / 86_400.0 for ts in idx],
                index=idx,
                dtype=float,
            )
            annualized = ratio_spread * (365.0 / days_to_expiry.where(days_to_expiry > 0.0))

        report = pd.DataFrame(
            {
                "base_symbol": base_symbol,
                "quote_symbol": quote_symbol,
                "base_close": base_close,
                "quote_close": quote_close,
                "spread": spread,
                "ratio_spread": ratio_spread,
                "annualized_basis": annualized,
            },
            index=idx,
        )
        for symbol in symbols:
            report[f"target_units_{symbol}"] = target_units[symbol]
        return report

    @staticmethod
    def _carry_report(
        idx: pd.DatetimeIndex,
        spec: ArbitrageSpec,
        result: BacktestResultV2,
        closes: Dict[str, pd.Series],
        funding: Dict[str, pd.Series],
        contract_sizes: Dict[str, float],
    ) -> pd.DataFrame:
        rows = []
        funding_mask = make_funding_mask(idx)
        for i, ts in enumerate(idx):
            for leg in spec.legs:
                symbol = leg.symbol
                prev_units = 0.0 if i == 0 else float(result.positions[f"Position_{symbol}"].iloc[i - 1])
                close_price = float(closes[symbol].iloc[i])
                notional = abs(prev_units) * close_price * float(contract_sizes[symbol])
                funding_cost = 0.0
                if funding_mask[i] and leg.funding_enabled:
                    funding_cost = prev_units * close_price * float(contract_sizes[symbol]) * float(funding[symbol].iloc[i])
                rows.append(
                    {
                        "timestamp": ts,
                        "symbol": symbol,
                        "role": leg.role,
                        "funding_enabled": bool(leg.funding_enabled),
                        "borrow_rate": float(spec.carry_model.borrow_rate),
                        "cash_yield": float(spec.carry_model.cash_yield),
                        "notional": notional,
                        "funding_cost": funding_cost,
                    }
                )
        return pd.DataFrame(rows)

    @staticmethod
    def _build_fills(sorted_orders, idx, fill_bar, fill_qty, fill_price, fill_fee) -> List[Fill]:
        fills: List[Fill] = []
        for sorted_idx, (_, order) in enumerate(sorted_orders):
            bar = int(fill_bar[sorted_idx])
            if bar < 0:
                continue
            fills.append(
                Fill(
                    timestamp=idx[bar],
                    symbol=order.symbol,
                    side=order.side,
                    qty=float(fill_qty[sorted_idx]),
                    price=float(fill_price[sorted_idx]),
                    fee=float(fill_fee[sorted_idx]),
                    liquidity=(
                        LiquiditySide.TAKER
                        if order.order_type is OrderType.MARKET
                        else LiquiditySide.MAKER
                    ),
                    order_id=order.order_id,
                    metadata={"source": "native_event"},
                )
            )
        return fills
