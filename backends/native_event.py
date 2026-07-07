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
from ..core.arbitrage import BasisArbitrageSpec, build_arbitrage_order_plan
from ..core.basket import build_frozen_basket_orders
from ..core.orders import Fill, OrderIntent
from ..core.preprocessor import align_series, build_arrays, make_funding_mask, prepare_funding, validate_datetime
from ..core.results import BacktestResultV2
from ..core.schema import (
    AccountConfig,
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

        sorted_orders = sorted(enumerate(orders), key=lambda item: self._bar_index(idx, item[1].timestamp))
        n_orders = len(sorted_orders)
        order_bar = np.zeros(n_orders, dtype=np.int64)
        order_symbol = np.zeros(n_orders, dtype=np.int64)
        order_side = np.zeros(n_orders, dtype=np.int64)
        order_type = np.zeros(n_orders, dtype=np.int64)
        order_qty = np.zeros(n_orders, dtype=np.float64)
        order_price = np.zeros(n_orders, dtype=np.float64)
        order_tif = np.zeros(n_orders, dtype=np.int64)
        original_index = np.zeros(n_orders, dtype=np.int64)

        for k, (orig_idx, order) in enumerate(sorted_orders):
            if order.symbol not in symbol_to_col:
                raise ValueError(f"order symbol {order.symbol!r} is not in symbols")
            order_bar[k] = self._bar_index(idx, order.timestamp)
            order_symbol[k] = symbol_to_col[order.symbol]
            order_side[k] = self._side_code(order.side)
            order_type[k] = self._order_type_code(order.order_type)
            order_qty[k] = float(order.qty)
            order_price[k] = 0.0 if order.price is None else float(order.price)
            order_tif[k] = self._tif_code(order.tif)
            original_index[k] = orig_idx

        order_ptr = np.zeros(len(idx) + 1, dtype=np.int64)
        for bar in order_bar:
            order_ptr[bar + 1] += 1
        for i in range(1, len(order_ptr)):
            order_ptr[i] += order_ptr[i - 1]

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
            order_ptr=order_ptr,
            order_symbol=order_symbol,
            order_side=order_side,
            order_type=order_type,
            order_qty=order_qty,
            order_price=order_price,
            order_tif=order_tif,
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

        fills = self._build_fills(sorted_orders, idx, fill_bar, fill_qty, fill_price, fill_fee)
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
                "original_index": original_index,
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
            symbols=symbols,
        )
        result.metadata["basket_plan"] = plan
        result.metadata["basket_target_units"] = plan.target_units
        result.metadata["basket_execution_policy"] = basket.execution_policy.value
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
        contract_sizes = self._contract_size_for_spec(spec, contract_size)
        fee_rates = self._fee_rate_for_spec(spec)
        basis_funding = self._funding_for_spec(spec, funding_rate)

        plan = build_arbitrage_order_plan(
            datetime_index=idx,
            spec=spec,
            signal=signal,
            closes=closes,
            hedge_ratios=hedge_ratios,
        )
        result = self.run_orders(
            datetime_index=idx,
            orders=plan.orders,
            closes=closes,
            highs=highs,
            lows=lows,
            funding_rate=basis_funding,
            contract_size=contract_sizes,
            leverage=leverage,
            fee_rate=fee_rates,
            symbols=symbols,
        )

        close_dict = align_series(closes, symbols, idx)
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

    def _fee_rate_for_spec(self, spec: BasisArbitrageSpec) -> Dict[str, float]:
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
        spec: BasisArbitrageSpec,
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
