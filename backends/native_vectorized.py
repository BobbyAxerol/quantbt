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
from ..core.results import BacktestResultV2
from ..core.schema import AccountConfig, BasketLegSpec, BasketSpec, ExecutionConfig
from ..core.vectorized import _engine_units_v2
from ..core.arbitrage import (
    ArbitrageSpec,
    BasisArbitrageSpec,
    SizingPolicyKind,
    StatArbPairSpec,
    build_arbitrage_order_plan,
)
from ..core.basket import build_frozen_basket_orders
from ..core.preprocessor import make_funding_mask
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
        target_units = {symbol: plan.target_units[symbol] for symbol in symbols}

        result = self.run_target_units(
            datetime_index=idx,
            target_units=target_units,
            closes=close_dict,
            highs=highs,
            lows=lows,
            funding_rate=funding_rate,
            contract_size=contract_sizes,
            leverage=leverage,
            fee_rate=fee_rates,
            symbols=symbols,
        )
        funding_dict = prepare_funding(funding_rate if self.config.use_funding else 0.0, symbols, idx)
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
                "engine": "units_v2_stat_arb_pair",
                "arb_id": spec.arb_id,
                "arb_type": spec.arb_type.value,
                "arbitrage_plan": plan,
                "package_target_units": plan.target_units,
                "beta_drift_report": self._stat_arb_beta_drift_report(idx, spec, plan, rebalance_threshold),
                "leg_pnl_report": leg_pnl_report,
                "package_pnl_report": package_report,
                "rebalance_threshold": rebalance_threshold,
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
    def _funding_for_spec(spec: BasisArbitrageSpec, funding_rate: Union[float, pd.Series, Dict]):
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
        package_pnl = leg_pnl_report.groupby("timestamp", sort=False)["total_pnl"].sum().reindex(idx, fill_value=0.0)
        report = pd.DataFrame(
            {
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
        spec: BasisArbitrageSpec,
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
