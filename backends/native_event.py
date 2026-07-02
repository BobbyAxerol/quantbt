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
from ..core.orders import Fill, OrderIntent
from ..core.preprocessor import align_series, build_arrays, prepare_funding, validate_datetime
from ..core.results import BacktestResultV2
from ..core.schema import (
    AccountConfig,
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
    fee_rate: float = 0.0
    use_funding: bool = True

    def __post_init__(self) -> None:
        if self.fee_rate < 0.0:
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
            fee_rate=self.config.fee_rate,
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
                "fee_rate_oneway": self.config.fee_rate,
                "slippage_bps": self.config.execution.slippage_bps,
                "order_report": order_report,
                "initial_buying_power": self.config.account.initial_capital * float(np.mean(leverages)),
                "liquidation_reason": int(liq_reason),
            },
        )

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
