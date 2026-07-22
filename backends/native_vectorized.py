"""
quantbt.backends.native_vectorized
----------------------------------
V2 backend facade over Numba vectorized kernels.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Union

import numpy as np
import pandas as pd

from ..core.preprocessor import align_series, build_arrays, prepare_funding, validate_datetime
from ..core.constraints import build_quantity_constraints, quantize_target_units_matrix
from ..core.results import BacktestResultV2
from ..core.schema import AccountConfig, BasketLegSpec, BasketSpec, ExecutionConfig, InstrumentSpec
from ..core.vectorized import _engine_units_v2
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
from ..core.orders import OrderIntent
from ..core.preprocessor import make_funding_mask
from ..core.schema import OrderSide
from ..sizing.fast import scale_signal_notional_matrix
from ..sizing.modes import compute_target_units


@dataclass(frozen=True)
class NativeVectorizedConfig:
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


class NativeVectorizedBackend:
    """
    Fast vectorized backend returning BacktestResultV2 diagnostics.

    This initial Phase 2 backend consumes pre-scaled target units. Sizing modes
    remain in the existing public wrappers and will be migrated onto this backend
    incrementally.
    """

    def __init__(self, config: NativeVectorizedConfig):
        self.config = config

    def run_target_units(
        self,
        datetime_index: Union[pd.DatetimeIndex, pd.Series],
        target_units: Dict[str, pd.Series],
        closes: Dict[str, pd.Series],
        highs: Optional[Dict[str, pd.Series]] = None,
        lows: Optional[Dict[str, pd.Series]] = None,
        funding_rate: Union[float, pd.Series, Dict] = 0.0,
        contract_size: Union[float, Dict[str, float]] = 1.0,
        leverage: Optional[Union[float, Dict[str, float]]] = None,
        fee_rate: Optional[Union[float, Dict[str, float]]] = None,
        symbols: Optional[List[str]] = None,
        instruments: Optional[Union[Dict[str, InstrumentSpec], List[InstrumentSpec]]] = None,
        qty_step: Optional[Union[float, Dict[str, float]]] = None,
        lot_size: Optional[Union[float, Dict[str, float]]] = None,
        slot_size: Optional[Union[float, Dict[str, float]]] = None,
        min_qty: Optional[Union[float, Dict[str, float]]] = None,
        min_notional: Optional[Union[float, Dict[str, float]]] = None,
    ) -> BacktestResultV2:
        idx = validate_datetime(datetime_index)
        symbol_list = symbols or list(target_units.keys())
        if set(symbol_list) != set(target_units.keys()) or set(symbol_list) != set(closes.keys()):
            raise ValueError("symbols, target_units, and closes must contain the same keys")

        close_dict = align_series(closes, symbol_list, idx)
        high_dict = align_series(highs, symbol_list, idx, fallback=close_dict)
        low_dict = align_series(lows, symbol_list, idx, fallback=close_dict)
        target_dict = align_series(target_units, symbol_list, idx, fill_val=0.0)
        funding_dict = prepare_funding(funding_rate if self.config.use_funding else 0.0, symbol_list, idx)

        closes_m, highs_m, lows_m, target_m, funding_m, is_funding = build_arrays(
            symbols=symbol_list,
            idx=idx,
            closes_dict=close_dict,
            highs_dict=high_dict,
            lows_dict=low_dict,
            signals_dict=target_dict,
            funding_dict=funding_dict,
        )

        return self._run_target_arrays(
            idx=idx,
            symbol_list=symbol_list,
            closes_m=closes_m,
            highs_m=highs_m,
            lows_m=lows_m,
            target_m=target_m,
            funding_m=funding_m,
            is_funding=is_funding,
            contract_size=contract_size,
            leverage=leverage,
            fee_rate=fee_rate,
            instruments=instruments,
            qty_step=qty_step,
            lot_size=lot_size,
            slot_size=slot_size,
            min_qty=min_qty,
            min_notional=min_notional,
        )

    def _run_target_arrays(
        self,
        idx: pd.DatetimeIndex,
        symbol_list: List[str],
        closes_m: np.ndarray,
        highs_m: np.ndarray,
        lows_m: np.ndarray,
        target_m: np.ndarray,
        funding_m: np.ndarray,
        is_funding: np.ndarray,
        contract_size: Union[float, Dict[str, float]] = 1.0,
        leverage: Optional[Union[float, Dict[str, float]]] = None,
        fee_rate: Optional[Union[float, Dict[str, float]]] = None,
        instruments: Optional[Union[Dict[str, InstrumentSpec], List[InstrumentSpec]]] = None,
        qty_step: Optional[Union[float, Dict[str, float]]] = None,
        lot_size: Optional[Union[float, Dict[str, float]]] = None,
        slot_size: Optional[Union[float, Dict[str, float]]] = None,
        min_qty: Optional[Union[float, Dict[str, float]]] = None,
        min_notional: Optional[Union[float, Dict[str, float]]] = None,
    ) -> BacktestResultV2:
        contract_sizes = self._per_symbol_array(contract_size, symbol_list, default=1.0)
        constraints = build_quantity_constraints(
            symbol_list,
            instruments=instruments,
            qty_step=qty_step,
            lot_size=lot_size,
            slot_size=slot_size,
            min_qty=min_qty,
            min_notional=min_notional,
        )
        target_m = quantize_target_units_matrix(target_m, closes_m, contract_sizes, constraints)
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
            rejected_arr,
            reject_code_arr,
            liq_flag,
            liq_idx,
            liq_reason,
        ) = _engine_units_v2(
            n_bars=len(idx),
            n_syms=len(symbol_list),
            highs=highs_m,
            lows=lows_m,
            closes=closes_m,
            target_units=target_m,
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

        equity = pd.Series(equity_arr, index=idx, name="equity")
        returns = equity.pct_change().fillna(0.0)
        positions = pd.DataFrame(
            {f"Position_{s}": pos_arr[:, j] for j, s in enumerate(symbol_list)},
            index=idx,
        )
        close_df = pd.DataFrame(
            {f"Close_{s}": closes_m[:, j] for j, s in enumerate(symbol_list)},
            index=idx,
        )
        fees = pd.Series(fee_arr, index=idx, name="fees")
        funding = pd.Series(funding_arr, index=idx, name="funding")
        margin = pd.DataFrame(
            {
                "initial_margin": init_margin_arr,
                "maintenance_margin": maint_margin_arr,
            },
            index=idx,
        )
        diagnostics = pd.DataFrame(
            {
                "turnover": turnover_arr,
                "rejected_orders": rejected_arr,
                "reject_code": reject_code_arr,
            },
            index=idx,
        )

        return BacktestResultV2(
            equity=equity,
            returns=returns,
            positions=positions,
            closes=close_df,
            symbols=symbol_list,
            initial_capital=self.config.account.initial_capital,
            leverage=float(np.mean(leverages)),
            liquidated=bool(liq_flag),
            liquidation_bar=int(liq_idx),
            fees=fees,
            funding=funding,
            margin=margin,
            diagnostics=diagnostics,
            metadata={
                "backend": "native_vectorized",
                "engine": "units_v2",
                "fee_rate_oneway": self._fee_rate_metadata(fee_rates, symbol_list),
                "slippage_bps": self.config.execution.slippage_bps,
                "initial_buying_power": self.config.account.initial_capital * float(np.mean(leverages)),
                "liquidation_reason": int(liq_reason),
                "quantity_constraints": constraints.as_dict(),
            },
        )

    def run_signals(
        self,
        datetime_index: Union[pd.DatetimeIndex, pd.Series],
        positions: Dict[str, pd.Series],
        closes: Dict[str, pd.Series],
        highs: Optional[Dict[str, pd.Series]] = None,
        lows: Optional[Dict[str, pd.Series]] = None,
        funding_rate: Union[float, pd.Series, Dict] = 0.0,
        contract_size: Union[float, Dict[str, float]] = 1.0,
        leverage: Optional[Union[float, Dict[str, float]]] = None,
        alloc_per_trade: Union[float, Dict[str, float]] = 100_000.0,
        hedge_type: str = "signal_notional",
        use_pyramiding: bool = True,
        symbols: Optional[List[str]] = None,
        instruments: Optional[Union[Dict[str, InstrumentSpec], List[InstrumentSpec]]] = None,
        qty_step: Optional[Union[float, Dict[str, float]]] = None,
        lot_size: Optional[Union[float, Dict[str, float]]] = None,
        slot_size: Optional[Union[float, Dict[str, float]]] = None,
        min_qty: Optional[Union[float, Dict[str, float]]] = None,
        min_notional: Optional[Union[float, Dict[str, float]]] = None,
    ) -> BacktestResultV2:
        """
        Scale raw position signals into target units, then run the V2 kernel.

        Phase 2 supports target-unit sizing modes here. `%_equity` and
        `dca_ladder` remain on the legacy kernels until their V2 diagnostics
        kernels are added.
        """
        ht = hedge_type.lower().strip()
        if ht in ("%_equity", "pct_equity", "dca_ladder", "dca"):
            raise NotImplementedError(f"NativeVectorizedBackend.run_signals does not yet support hedge_type={hedge_type!r}")

        idx = validate_datetime(datetime_index)
        symbol_list = symbols or list(positions.keys())
        pos_dict = align_series(positions, symbol_list, idx, fill_val=0.0)
        close_dict = align_series(closes, symbol_list, idx)
        alloc = self._per_symbol_mapping(alloc_per_trade, symbol_list, default=100_000.0)

        if ht in ("signal_notional", "signal"):
            high_dict = align_series(highs, symbol_list, idx, fallback=close_dict)
            low_dict = align_series(lows, symbol_list, idx, fallback=close_dict)
            funding_dict = prepare_funding(funding_rate if self.config.use_funding else 0.0, symbol_list, idx)
            closes_m, highs_m, lows_m, signals_m, funding_m, is_funding = build_arrays(
                symbols=symbol_list,
                idx=idx,
                closes_dict=close_dict,
                highs_dict=high_dict,
                lows_dict=low_dict,
                signals_dict=pos_dict,
                funding_dict=funding_dict,
            )
            allocs = np.array([alloc[s] for s in symbol_list], dtype=np.float64)
            target_m = scale_signal_notional_matrix(
                signals=signals_m,
                closes=closes_m,
                allocs=allocs,
                use_pyramiding=use_pyramiding,
            )
            return self._run_target_arrays(
                idx=idx,
                symbol_list=symbol_list,
                closes_m=closes_m,
                highs_m=highs_m,
                lows_m=lows_m,
                target_m=target_m,
                funding_m=funding_m,
                is_funding=is_funding,
                contract_size=contract_size,
                leverage=leverage,
                instruments=instruments,
                qty_step=qty_step,
                lot_size=lot_size,
                slot_size=slot_size,
                min_qty=min_qty,
                min_notional=min_notional,
            )

        target_units = {
            s: compute_target_units(
                hedge_type=hedge_type,
                signal=pos_dict[s],
                close=close_dict[s],
                alloc=alloc[s],
                use_pyramiding=use_pyramiding,
            )
            for s in symbol_list
        }

        return self.run_target_units(
            datetime_index=idx,
            target_units=target_units,
            closes=close_dict,
            highs=highs,
            lows=lows,
            funding_rate=funding_rate,
            contract_size=contract_size,
            leverage=leverage,
            symbols=symbol_list,
            instruments=instruments,
            qty_step=qty_step,
            lot_size=lot_size,
            slot_size=slot_size,
            min_qty=min_qty,
            min_notional=min_notional,
        )

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
        if not isinstance(spec, BasisArbitrageSpec):
            raise TypeError("run_basis_arbitrage requires a BasisArbitrageSpec")
        idx = validate_datetime(datetime_index)
        symbols = [leg.symbol for leg in spec.legs]
        close_dict = align_series(closes, symbols, idx)
        plan = build_arbitrage_order_plan(
            datetime_index=idx,
            spec=spec,
            signal=signal,
            closes=close_dict,
            hedge_ratios=hedge_ratios,
        )
        contract_sizes = self._contract_size_for_spec(spec, contract_size)
        fee_rates = self._fee_rate_for_spec(spec)
        plan = self._apply_atomic_package_margin_policy(idx, plan, close_dict, contract_sizes, fee_rates, leverage)
        basis_funding = self._funding_for_spec(spec, funding_rate)
        target_units = {symbol: plan.target_units[symbol] for symbol in symbols}

        result = self.run_target_units(
            datetime_index=idx,
            target_units=target_units,
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
        leg_pnl_report = self._leg_pnl_report(
            idx=idx,
            symbols=symbols,
            roles={leg.symbol: leg.role for leg in spec.legs},
            result=result,
            closes=close_dict,
            funding=funding_dict,
            contract_sizes=contract_sizes,
            fee_rates=fee_rates,
        )
        package_report = self._package_pnl_report(idx, result, leg_pnl_report)
        result.metadata.update(
            {
                "backend": "native_vectorized",
                "engine": "units_v2_basis_arbitrage",
                "arb_id": spec.arb_id,
                "arb_type": spec.arb_type.value,
                "arbitrage_plan": plan,
                "package_target_units": plan.target_units,
                "package_rejection_report": plan.rejection_report,
                "spread_report": self._basis_spread_report(idx, spec, close_dict, plan.target_units),
                "leg_pnl_report": leg_pnl_report,
                "package_pnl_report": package_report,
                "fee_rate_oneway": fee_rates,
                "contract_size": contract_sizes,
            }
        )
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
        if not isinstance(spec, StatArbPairSpec):
            raise TypeError("run_stat_arb_pair_arbitrage requires a StatArbPairSpec")
        idx = validate_datetime(datetime_index)
        symbols = [leg.symbol for leg in spec.legs]
        close_dict = align_series(closes, symbols, idx)
        basket = self._stat_arb_basket_from_spec(spec)
        rebalance_threshold = spec.hedge_policy.rebalance_threshold
        if not spec.hedge_policy.freeze_on_entry and rebalance_threshold is None:
            rebalance_threshold = 0.0
        plan = build_frozen_basket_orders(
            datetime_index=idx,
            basket=basket,
            signal=signal,
            closes=close_dict,
            hedge_ratios=hedge_ratios,
            rebalance_threshold=rebalance_threshold,
        )
        contract_sizes = self._contract_size_for_spec(spec, contract_size)
        fee_rates = self._fee_rate_for_spec(spec)
        stat_funding = self._funding_for_spec(spec, funding_rate)
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
        target_units = {symbol: arb_plan.target_units[symbol] for symbol in symbols}

        result = self.run_target_units(
            datetime_index=idx,
            target_units=target_units,
            closes=close_dict,
            highs=highs,
            lows=lows,
            funding_rate=stat_funding,
            contract_size=contract_sizes,
            leverage=leverage,
            fee_rate=fee_rates,
            symbols=symbols,
        )
        funding_dict = prepare_funding(stat_funding if self.config.use_funding else 0.0, symbols, idx)
        leg_pnl_report = self._leg_pnl_report(
            idx=idx,
            symbols=symbols,
            roles=self._stat_arb_roles(spec),
            result=result,
            closes=close_dict,
            funding=funding_dict,
            contract_sizes=contract_sizes,
            fee_rates=fee_rates,
        )
        package_report = self._package_pnl_report(idx, result, leg_pnl_report)
        result.metadata.update(
            {
                "backend": "native_vectorized",
                "engine": "units_v2_stat_arb_pair",
                "arb_id": spec.arb_id,
                "arb_type": spec.arb_type.value,
                "arbitrage_plan": arb_plan,
                "package_target_units": arb_plan.target_units,
                "package_rejection_report": arb_plan.rejection_report,
                "basket_plan": plan,
                "basket_target_units": arb_plan.target_units,
                "beta_drift_report": self._stat_arb_beta_drift_report(idx, spec, arb_plan, rebalance_threshold),
                "spread_report": self._stat_arb_spread_report(idx, spec, close_dict, arb_plan),
                "leg_pnl_report": leg_pnl_report,
                "package_pnl_report": package_report,
                "rebalance_threshold": rebalance_threshold,
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
        hedge_ratios: Optional[Dict[str, pd.Series]] = None,
        funding_rate: Union[float, pd.Series, Dict] = 0.0,
        contract_size: Optional[Union[float, Dict[str, float]]] = None,
        leverage: Optional[Union[float, Dict[str, float]]] = None,
    ) -> BacktestResultV2:
        unsupported = (CrossExchangeArbSpec, TriangularArbSpec, OptionsVolArbSpec)
        if isinstance(spec, unsupported):
            raise NotImplementedError(
                f"{type(spec).__name__} is schema-validated but requires a specialized arbitrage engine; "
                "do not route it through generic package execution. "
                "Use QuantBTEndpoint.arbitrage_support_matrix() to inspect supported routes."
            )
        supported = (CalendarSpreadSpec, FundingArbitrageSpec, SpotPerpCashCarrySpec, IndexBasketArbSpec)
        if not isinstance(spec, supported):
            raise TypeError("run_package_arbitrage requires a Phase G package-style arbitrage spec")

        idx = validate_datetime(datetime_index)
        symbols = [leg.symbol for leg in spec.legs]
        close_dict = align_series(closes, symbols, idx)
        plan = build_arbitrage_order_plan(
            datetime_index=idx,
            spec=spec,
            signal=signal,
            closes=close_dict,
            hedge_ratios=hedge_ratios,
        )
        contract_sizes = self._contract_size_for_spec(spec, contract_size)
        fee_rates = self._fee_rate_for_spec(spec)
        plan = self._apply_atomic_package_margin_policy(idx, plan, close_dict, contract_sizes, fee_rates, leverage)
        package_funding = self._funding_for_spec(spec, funding_rate)
        target_units = {symbol: plan.target_units[symbol] for symbol in symbols}

        result = self.run_target_units(
            datetime_index=idx,
            target_units=target_units,
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
        leg_pnl_report = self._leg_pnl_report(
            idx=idx,
            symbols=symbols,
            roles={leg.symbol: leg.role for leg in spec.legs},
            result=result,
            closes=close_dict,
            funding=funding_dict,
            contract_sizes=contract_sizes,
            fee_rates=fee_rates,
        )
        package_report = self._package_pnl_report(idx, result, leg_pnl_report)
        result.metadata.update(
            {
                "backend": "native_vectorized",
                "engine": f"units_v2_{spec.arb_type.value}",
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
    def _per_symbol_array(value, symbols: List[str], default: float) -> np.ndarray:
        if isinstance(value, dict):
            return np.array([float(value.get(s, default)) for s in symbols], dtype=np.float64)
        return np.full(len(symbols), float(value), dtype=np.float64)

    @staticmethod
    def _per_symbol_mapping(value, symbols: List[str], default: float) -> Dict[str, float]:
        if isinstance(value, dict):
            return {s: float(value.get(s, default)) for s in symbols}
        return {s: float(value) for s in symbols}

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
    def _stat_arb_roles(spec: StatArbPairSpec) -> Dict[str, str]:
        symbols = [leg.symbol for leg in spec.legs]
        roles = {leg.symbol: str(leg.role or "leg") for leg in spec.legs}
        if len(symbols) >= 2 and len(set(roles.values())) == 1:
            roles[symbols[0]] = "leg"
            roles[symbols[1]] = "hedge"
        return roles

    @staticmethod
    def _stat_arb_spread_report(
        idx: pd.DatetimeIndex,
        spec: StatArbPairSpec,
        closes: Dict[str, pd.Series],
        plan,
    ) -> pd.DataFrame:
        symbols = [leg.symbol for leg in spec.legs]
        leg_symbol = symbols[0]
        hedge_symbol = symbols[1] if len(symbols) > 1 else symbols[0]
        leg_close = closes[leg_symbol].astype(float)
        hedge_close = closes[hedge_symbol].astype(float)
        ref_ratio = plan.entry_ratios[leg_symbol].replace(0.0, np.nan).astype(float)
        hedge_ratio = (plan.entry_ratios[hedge_symbol].astype(float) / ref_ratio).fillna(0.0)
        spread = leg_close + hedge_ratio * hedge_close
        return pd.DataFrame(
            {
                "leg_symbol": leg_symbol,
                "hedge_symbol": hedge_symbol,
                "leg_close": leg_close,
                "hedge_close": hedge_close,
                "hedge_ratio_to_leg": hedge_ratio,
                "spread": spread,
                "abs_spread": spread.abs(),
            },
            index=idx,
        )

    @staticmethod
    def _stat_arb_basket_from_spec(spec: StatArbPairSpec) -> BasketSpec:
        if spec.sizing_policy.kind is not SizingPolicyKind.TARGET_GROSS_NOTIONAL:
            raise NotImplementedError("Phase E StatArbPairSpec requires target_gross_notional sizing")
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

    def _leg_pnl_report(
        self,
        idx: pd.DatetimeIndex,
        symbols: List[str],
        roles: Dict[str, str],
        result: BacktestResultV2,
        closes: Dict[str, pd.Series],
        funding: Dict[str, pd.Series],
        contract_sizes: Dict[str, float],
        fee_rates: Dict[str, float],
    ) -> pd.DataFrame:
        funding_mask = make_funding_mask(idx)
        cumulative = {symbol: 0.0 for symbol in symbols}
        rows = []
        slippage = self.config.execution.slippage_rate
        for i, ts in enumerate(idx):
            for symbol in symbols:
                cs = float(contract_sizes[symbol])
                close_price = float(closes[symbol].iloc[i])
                prev_units = 0.0 if i == 0 else float(result.positions[f"Position_{symbol}"].iloc[i - 1])
                units = float(result.positions[f"Position_{symbol}"].iloc[i])
                delta = units - prev_units
                price_pnl = 0.0
                if i > 0:
                    price_pnl = prev_units * (close_price - float(closes[symbol].iloc[i - 1])) * cs
                exec_price = close_price * (1.0 + slippage if delta > 0.0 else 1.0 - slippage)
                fee = abs(delta) * exec_price * cs * float(fee_rates[symbol]) if abs(delta) > 1e-12 else 0.0
                slippage_cost = abs(delta) * abs(exec_price - close_price) * cs if abs(delta) > 1e-12 else 0.0
                funding_cost = 0.0
                if self.config.use_funding and funding_mask[i]:
                    funding_cost = prev_units * close_price * cs * float(funding[symbol].iloc[i])
                total_pnl = price_pnl - fee - slippage_cost - funding_cost
                cumulative[symbol] += total_pnl
                rows.append(
                    {
                        "timestamp": ts,
                        "symbol": symbol,
                        "role": roles.get(symbol, "leg"),
                        "units": units,
                        "close": close_price,
                        "notional": abs(units) * close_price * cs,
                        "price_pnl": price_pnl,
                        "fill_pnl": -slippage_cost,
                        "fee": fee,
                        "funding_pnl": -funding_cost,
                        "total_pnl": total_pnl,
                        "cumulative_pnl": cumulative[symbol],
                    }
                )
        return pd.DataFrame(rows)

    @staticmethod
    def _package_pnl_report(idx: pd.DatetimeIndex, result: BacktestResultV2, leg_pnl_report: pd.DataFrame) -> pd.DataFrame:
        grouped = leg_pnl_report.groupby("timestamp", sort=False)
        package_pnl = grouped["total_pnl"].sum().reindex(idx, fill_value=0.0)
        price_pnl = grouped["price_pnl"].sum().reindex(idx, fill_value=0.0)
        fill_pnl = grouped["fill_pnl"].sum().reindex(idx, fill_value=0.0)
        fees = grouped["fee"].sum().reindex(idx, fill_value=0.0)
        funding_pnl = grouped["funding_pnl"].sum().reindex(idx, fill_value=0.0)
        role_pnl = leg_pnl_report.pivot_table(
            index="timestamp",
            columns="role",
            values="total_pnl",
            aggfunc="sum",
            fill_value=0.0,
        ).reindex(idx, fill_value=0.0)
        leg_pnl = role_pnl["leg"] if "leg" in role_pnl else pd.Series(0.0, index=idx)
        hedge_pnl = role_pnl["hedge"] if "hedge" in role_pnl else pd.Series(0.0, index=idx)
        report = pd.DataFrame(
            {
                "price_pnl": price_pnl,
                "fill_pnl": fill_pnl,
                "fees": fees,
                "funding_pnl": funding_pnl,
                "leg_pnl": leg_pnl,
                "hedge_pnl": hedge_pnl,
                "spread_pnl": leg_pnl + hedge_pnl,
                "package_pnl": package_pnl,
                "equity_delta": result.equity.diff().fillna(0.0),
            },
            index=idx,
        )
        report["pnl_residual"] = report["equity_delta"] - report["package_pnl"]
        return report

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
