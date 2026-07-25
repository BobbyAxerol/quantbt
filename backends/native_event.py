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
    _engine_event_v2,
)
from ..core.constraints import build_quantity_constraints, quantize_signed_quantity
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
from ..core.order_compiler import (
    CompiledOrderArrays,
    CompiledOrderCommandArrays,
    compile_order_commands,
    compile_order_intents,
)
from ..core.orders import Fill, OrderAction, OrderCommand, OrderIntent
from ..core.preprocessor import (
    PreparedMarketArrays,
    align_series,
    build_market_arrays,
    make_funding_mask,
    prepare_funding,
    validate_datetime,
)
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
    InstrumentSpec,
)


def _event_type_name(event_type: int) -> str:
    return {
        0: "place",
        1: "cancel",
        2: "replace",
        3: "amend",
        4: "fill",
        5: "expire",
        6: "activate",
        7: "reject",
    }.get(int(event_type), "unknown")


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

    def prepare_market_arrays(
        self,
        datetime_index: Union[pd.DatetimeIndex, pd.Series],
        closes: Dict[str, pd.Series],
        highs: Optional[Dict[str, pd.Series]] = None,
        lows: Optional[Dict[str, pd.Series]] = None,
        funding_rate: Union[float, pd.Series, Dict] = 0.0,
        symbols: Optional[Sequence[str]] = None,
    ) -> PreparedMarketArrays:
        """
        Normalize OHLC/funding inputs into immutable ndarray-backed market arrays.

        This helper is intended for higher-level optimizers and WFO loops that
        replay many order packages over the same market tape. The returned
        object carries a datetime/symbol signature and `run_orders` rejects it
        if reused against a different index or symbol layout.
        """
        idx = validate_datetime(datetime_index)
        symbol_list = list(symbols) if symbols is not None else list(closes.keys())
        close_dict = align_series(closes, symbol_list, idx)
        high_dict = align_series(highs, symbol_list, idx, fallback=close_dict)
        low_dict = align_series(lows, symbol_list, idx, fallback=close_dict)
        funding_dict = prepare_funding(funding_rate if self.config.use_funding else 0.0, symbol_list, idx)
        return build_market_arrays(
            symbols=symbol_list,
            idx=idx,
            closes_dict=close_dict,
            highs_dict=high_dict,
            lows_dict=low_dict,
            funding_dict=funding_dict,
        )

    @staticmethod
    def compile_orders(
        datetime_index: Union[pd.DatetimeIndex, pd.Series],
        orders: Sequence[OrderIntent],
        symbols: Optional[Sequence[str]] = None,
    ) -> CompiledOrderArrays:
        """
        Compile explicit `OrderIntent` objects into contiguous kernel arrays.

        Use this when the same order package is replayed against the same
        market tape. If `symbols` is omitted it is inferred from first
        occurrence in the order sequence, which is convenient for standalone
        simulations; passing the exact market symbol order is safer for
        multi-symbol portfolio and arbitrage packages.
        """
        idx = validate_datetime(datetime_index)
        symbol_list = list(symbols) if symbols is not None else list(dict.fromkeys(order.symbol for order in orders))
        return compile_order_intents(idx=idx, orders=orders, symbol_to_col={s: j for j, s in enumerate(symbol_list)})

    @staticmethod
    def compile_order_commands(
        datetime_index: Union[pd.DatetimeIndex, pd.Series],
        commands: Sequence[OrderCommand],
        symbols: Optional[Sequence[str]] = None,
    ) -> CompiledOrderCommandArrays:
        """
        Compile lifecycle commands for the native-event v2 contract.

        Phase 30A exposes this helper for adapters and strategy services. It
        does not route commands into the v1 matching kernel; the v2 lifecycle
        kernel is a later phase.
        """
        idx = validate_datetime(datetime_index)
        if symbols is None:
            symbol_list = list(dict.fromkeys(command.symbol for command in commands if command.symbol is not None))
        else:
            symbol_list = list(symbols)
        return compile_order_commands(
            idx=idx,
            commands=commands,
            symbol_to_col={s: j for j, s in enumerate(symbol_list)},
        )

    def run_order_commands(
        self,
        datetime_index: Union[pd.DatetimeIndex, pd.Series],
        commands: Sequence[OrderCommand],
        closes: Dict[str, pd.Series],
        highs: Optional[Dict[str, pd.Series]] = None,
        lows: Optional[Dict[str, pd.Series]] = None,
        funding_rate: Union[float, pd.Series, Dict] = 0.0,
        contract_size: Union[float, Dict[str, float]] = 1.0,
        leverage: Optional[Union[float, Dict[str, float]]] = None,
        fee_rate: Optional[Union[float, Dict[str, float]]] = None,
        symbols: Optional[List[str]] = None,
        market_arrays: Optional[PreparedMarketArrays] = None,
        compiled_commands: Optional[CompiledOrderCommandArrays] = None,
        instruments: Optional[Union[Dict[str, InstrumentSpec], List[InstrumentSpec]]] = None,
        qty_step: Optional[Union[float, Dict[str, float]]] = None,
        lot_size: Optional[Union[float, Dict[str, float]]] = None,
        slot_size: Optional[Union[float, Dict[str, float]]] = None,
        min_qty: Optional[Union[float, Dict[str, float]]] = None,
        min_notional: Optional[Union[float, Dict[str, float]]] = None,
    ) -> BacktestResultV2:
        """
        Execute Phase 30B lifecycle `OrderCommand` tapes through event v2.

        This is intentionally opt-in. Existing `run_orders(OrderIntent...)`
        remains routed to event v1 until endpoint parity is promoted in a later
        phase.
        """
        idx = validate_datetime(datetime_index)
        if symbols is None:
            symbol_list = list(closes.keys())
        else:
            symbol_list = list(symbols)

        if market_arrays is None:
            market_arrays = self.prepare_market_arrays(
                datetime_index=idx,
                closes=closes,
                highs=highs,
                lows=lows,
                funding_rate=funding_rate,
                symbols=symbol_list,
            )
        elif market_arrays.signature != self._market_signature(idx, symbol_list):
            raise ValueError("prepared market arrays do not match datetime_index/symbols")

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
        effective_commands, quantity_preflight = self._apply_command_quantity_constraints(
            idx=idx,
            commands=commands,
            closes=market_arrays.closes,
            symbol_list=symbol_list,
            contract_sizes=contract_sizes,
            constraints=constraints,
        )
        if quantity_preflight["changed_count"] or quantity_preflight["dropped_count"]:
            compiled_commands = None
            commands = tuple(effective_commands)
        else:
            effective_commands = tuple(commands)

        if compiled_commands is None:
            compiled_commands = self.compile_order_commands(
                datetime_index=idx,
                commands=effective_commands,
                symbols=symbol_list,
            )
        elif (
            compiled_commands.index_signature != market_arrays.signature
            or compiled_commands.symbols != tuple(symbol_list)
        ):
            raise ValueError("compiled commands do not match prepared market arrays")

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
            command_status,
            reject_code,
            fill_bar,
            fill_qty,
            fill_price,
            fill_fee,
            active,
            waiting_parent,
            working_qty,
            working_price,
            working_trigger,
            event_count,
            event_bar,
            event_command,
            event_type,
            event_status,
            event_related_command,
            liq_flag,
            liq_idx,
            liq_reason,
        ) = _engine_event_v2(
            n_bars=len(idx),
            n_syms=len(symbol_list),
            n_commands=compiled_commands.n_commands,
            n_ids=len(compiled_commands.id_values),
            command_ptr=compiled_commands.command_ptr,
            command_action=compiled_commands.command_action,
            command_symbol=compiled_commands.command_symbol,
            command_side=compiled_commands.command_side,
            command_type=compiled_commands.command_type,
            command_qty=compiled_commands.command_qty,
            command_price=compiled_commands.command_price,
            command_trigger_price=compiled_commands.command_trigger_price,
            command_tif=compiled_commands.command_tif,
            command_reduce_only=compiled_commands.command_reduce_only,
            command_order_id=compiled_commands.command_order_id,
            command_target_order_id=compiled_commands.command_target_order_id,
            command_parent_order_id=compiled_commands.command_parent_order_id,
            command_group_id=compiled_commands.command_group_id,
            command_oco_group_id=compiled_commands.command_oco_group_id,
            command_activation=compiled_commands.command_activation,
            command_expires_bar=compiled_commands.command_expires_bar,
            highs=market_arrays.highs,
            lows=market_arrays.lows,
            closes=market_arrays.closes,
            funding_rates=market_arrays.funding,
            is_funding_bar=market_arrays.is_funding_bar,
            init_capital=self.config.account.initial_capital,
            leverages=leverages,
            maint_ratio=self.config.account.maintenance_ratio,
            fee_rates=fee_rates,
            contract_sizes=contract_sizes,
            slippage=self.config.execution.slippage_rate,
            use_funding=bool(self.config.use_funding),
        )

        fills = self._build_fills(
            compiled_commands.sorted_commands,
            idx,
            fill_bar,
            fill_qty,
            fill_price,
            fill_fee,
        )
        equity = pd.Series(equity_arr, index=idx, name="equity")
        positions = pd.DataFrame(
            {f"Position_{s}": pos_arr[:, j] for j, s in enumerate(symbol_list)},
            index=idx,
        )
        close_df = pd.DataFrame(
            {f"Close_{s}": market_arrays.closes[:, j] for j, s in enumerate(symbol_list)},
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
        command_report = self._build_command_report(
            compiled_commands,
            command_status,
            reject_code,
            fill_bar,
            fill_qty,
            fill_price,
            fill_fee,
            active,
            waiting_parent,
            working_qty,
            working_price,
            working_trigger,
        )
        order_events = self._build_order_events(
            idx=idx,
            compiled_commands=compiled_commands,
            event_count=int(event_count),
            event_bar=event_bar,
            event_command=event_command,
            event_type=event_type,
            event_status=event_status,
            event_related_command=event_related_command,
        )
        active_orders = command_report[
            (command_report["active"] == True) | (command_report["waiting_parent"] == True)  # noqa: E712
        ].copy()

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
            orders=self._commands_to_order_intents(compiled_commands.sorted_commands),
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
                "engine": "event_v2_lifecycle",
                "fee_rate_oneway": self._fee_rate_metadata(fee_rates, symbol_list),
                "slippage_bps": self.config.execution.slippage_bps,
                "order_report": command_report,
                "command_report": command_report,
                "order_events": order_events,
                "active_orders": active_orders,
                "id_values": compiled_commands.id_values,
                "quantity_constraints": constraints.as_dict(),
                "quantity_preflight": quantity_preflight,
                "initial_buying_power": self.config.account.initial_capital * float(np.mean(leverages)),
                "liquidation_reason": int(liq_reason),
            },
        )

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
        market_arrays: Optional[PreparedMarketArrays] = None,
        compiled_orders: Optional[CompiledOrderArrays] = None,
        instruments: Optional[Union[Dict[str, InstrumentSpec], List[InstrumentSpec]]] = None,
        qty_step: Optional[Union[float, Dict[str, float]]] = None,
        lot_size: Optional[Union[float, Dict[str, float]]] = None,
        slot_size: Optional[Union[float, Dict[str, float]]] = None,
        min_qty: Optional[Union[float, Dict[str, float]]] = None,
        min_notional: Optional[Union[float, Dict[str, float]]] = None,
    ) -> BacktestResultV2:
        idx = validate_datetime(datetime_index)
        symbol_list = symbols or list(closes.keys())

        if market_arrays is None:
            market_arrays = self.prepare_market_arrays(
                datetime_index=idx,
                closes=closes,
                highs=highs,
                lows=lows,
                funding_rate=funding_rate,
                symbols=symbol_list,
            )
        elif market_arrays.signature != self._market_signature(idx, symbol_list):
            raise ValueError("prepared market arrays do not match datetime_index/symbols")

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
        effective_orders, quantity_preflight = self._apply_order_quantity_constraints(
            idx=idx,
            orders=orders,
            closes=market_arrays.closes,
            symbol_list=symbol_list,
            contract_sizes=contract_sizes,
            constraints=constraints,
        )
        if quantity_preflight["changed_count"] or quantity_preflight["dropped_count"]:
            compiled_orders = None
            orders = tuple(effective_orders)
        else:
            effective_orders = tuple(orders)

        if compiled_orders is None:
            compiled_orders = self.compile_orders(datetime_index=idx, orders=effective_orders, symbols=symbol_list)
        elif (
            compiled_orders.index_signature != market_arrays.signature
            or compiled_orders.symbols != tuple(symbol_list)
        ):
            raise ValueError("compiled orders do not match prepared market arrays")
        n_orders = compiled_orders.n_orders
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
            highs=market_arrays.highs,
            lows=market_arrays.lows,
            closes=market_arrays.closes,
            funding_rates=market_arrays.funding,
            is_funding_bar=market_arrays.is_funding_bar,
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
            {f"Close_{s}": market_arrays.closes[:, j] for j, s in enumerate(symbol_list)},
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
                "quantity_constraints": constraints.as_dict(),
                "quantity_preflight": quantity_preflight,
                "initial_buying_power": self.config.account.initial_capital * float(np.mean(leverages)),
                "liquidation_reason": int(liq_reason),
            },
        )

    @staticmethod
    def _apply_order_quantity_constraints(
        *,
        idx: pd.DatetimeIndex,
        orders: Sequence[OrderIntent],
        closes: np.ndarray,
        symbol_list: List[str],
        contract_sizes: np.ndarray,
        constraints,
    ) -> tuple[tuple[OrderIntent, ...], Dict]:
        if not constraints.enabled:
            return tuple(orders), {"changed_count": 0, "dropped_count": 0, "dropped_orders": []}
        sym_to_col = {symbol: j for j, symbol in enumerate(symbol_list)}
        changed = 0
        dropped = []
        out: list[OrderIntent] = []
        idx_ns = idx.view("int64")
        for order_idx, order in enumerate(orders):
            col = sym_to_col[order.symbol]
            ts = pd.Timestamp(order.timestamp)
            if ts.tz is None:
                ts = ts.tz_localize("UTC")
            else:
                ts = ts.tz_convert("UTC")
            bar = int(np.searchsorted(idx_ns, ts.value, side="left"))
            if bar >= len(idx):
                bar = len(idx) - 1
            price = float(order.price) if order.price is not None else float(closes[bar, col])
            signed = order.signed_qty
            q = abs(
                quantize_signed_quantity(
                    signed,
                    price,
                    float(contract_sizes[col]),
                    float(constraints.qty_step[col]),
                    float(constraints.min_qty[col]),
                    float(constraints.min_notional[col]),
                )
            )
            if q <= 0.0:
                dropped.append({"original_index": order_idx, "symbol": order.symbol, "requested_qty": float(order.qty)})
                continue
            if abs(q - float(order.qty)) > 1e-12:
                changed += 1
                out.append(
                    OrderIntent(
                        timestamp=order.timestamp,
                        symbol=order.symbol,
                        side=order.side,
                        order_type=order.order_type,
                        qty=q,
                        price=order.price,
                        trigger_price=order.trigger_price,
                        tif=order.tif,
                        reduce_only=order.reduce_only,
                        order_id=order.order_id,
                        tag=order.tag,
                        metadata={**order.metadata, "requested_qty": float(order.qty), "quantity_quantized": True},
                    )
                )
            else:
                out.append(order)
        return tuple(out), {"changed_count": changed, "dropped_count": len(dropped), "dropped_orders": dropped}

    @staticmethod
    def _apply_command_quantity_constraints(
        *,
        idx: pd.DatetimeIndex,
        commands: Sequence[OrderCommand],
        closes: np.ndarray,
        symbol_list: List[str],
        contract_sizes: np.ndarray,
        constraints,
    ) -> tuple[tuple[OrderCommand, ...], Dict]:
        if not constraints.enabled:
            return tuple(commands), {"changed_count": 0, "dropped_count": 0, "dropped_orders": []}
        sym_to_col = {symbol: j for j, symbol in enumerate(symbol_list)}
        changed = 0
        dropped = []
        out: list[OrderCommand] = []
        idx_ns = idx.view("int64")
        for command_idx, command in enumerate(commands):
            if command.action not in (OrderAction.PLACE, OrderAction.REPLACE) or command.symbol is None:
                out.append(command)
                continue
            if command.symbol not in sym_to_col:
                raise ValueError(f"command symbol {command.symbol!r} is not in symbols")
            col = sym_to_col[command.symbol]
            ts = pd.Timestamp(command.timestamp)
            if ts.tz is None:
                ts = ts.tz_localize("UTC")
            else:
                ts = ts.tz_convert("UTC")
            bar = int(np.searchsorted(idx_ns, ts.value, side="left"))
            if bar >= len(idx):
                bar = len(idx) - 1
            price = float(command.price) if command.price is not None else float(closes[bar, col])
            signed = command.signed_qty
            q = abs(
                quantize_signed_quantity(
                    signed,
                    price,
                    float(contract_sizes[col]),
                    float(constraints.qty_step[col]),
                    float(constraints.min_qty[col]),
                    float(constraints.min_notional[col]),
                )
            )
            if q <= 0.0:
                dropped.append(
                    {
                        "original_index": command_idx,
                        "symbol": command.symbol,
                        "requested_qty": None if command.qty is None else float(command.qty),
                    }
                )
                continue
            if command.qty is not None and abs(q - float(command.qty)) > 1e-12:
                changed += 1
                out.append(
                    OrderCommand(
                        timestamp=command.timestamp,
                        action=command.action,
                        symbol=command.symbol,
                        side=command.side,
                        order_type=command.order_type,
                        qty=q,
                        price=command.price,
                        trigger_price=command.trigger_price,
                        tif=command.tif,
                        reduce_only=command.reduce_only,
                        order_id=command.order_id,
                        target_order_id=command.target_order_id,
                        parent_order_id=command.parent_order_id,
                        group_id=command.group_id,
                        oco_group_id=command.oco_group_id,
                        activation_policy=command.activation_policy,
                        expires_at=command.expires_at,
                        tag=command.tag,
                        metadata={
                            **command.metadata,
                            "requested_qty": float(command.qty),
                            "quantity_quantized": True,
                        },
                    )
                )
            else:
                out.append(command)
        return tuple(out), {"changed_count": changed, "dropped_count": len(dropped), "dropped_orders": dropped}

    @staticmethod
    def _build_command_report(
        compiled_commands: CompiledOrderCommandArrays,
        command_status: np.ndarray,
        reject_code: np.ndarray,
        fill_bar: np.ndarray,
        fill_qty: np.ndarray,
        fill_price: np.ndarray,
        fill_fee: np.ndarray,
        active: np.ndarray,
        waiting_parent: np.ndarray,
        working_qty: np.ndarray,
        working_price: np.ndarray,
        working_trigger: np.ndarray,
    ) -> pd.DataFrame:
        rows = []
        for sorted_idx, (original_idx, command) in enumerate(compiled_commands.sorted_commands):
            rows.append(
                {
                    "original_index": int(original_idx),
                    "sorted_index": int(sorted_idx),
                    "timestamp": command.timestamp,
                    "action": command.action.value,
                    "symbol": command.symbol,
                    "side": None if command.side is None else command.side.value,
                    "order_type": None if command.order_type is None else command.order_type.value,
                    "order_id": command.order_id,
                    "target_order_id": command.target_order_id,
                    "parent_order_id": command.parent_order_id,
                    "group_id": command.group_id,
                    "oco_group_id": command.oco_group_id,
                    "activation_policy": command.activation_policy.value,
                    "status": int(command_status[sorted_idx]),
                    "reject_code": int(reject_code[sorted_idx]),
                    "fill_bar": int(fill_bar[sorted_idx]),
                    "fill_qty": float(fill_qty[sorted_idx]),
                    "fill_price": float(fill_price[sorted_idx]),
                    "fill_fee": float(fill_fee[sorted_idx]),
                    "active": bool(active[sorted_idx]),
                    "waiting_parent": bool(waiting_parent[sorted_idx]),
                    "working_qty": float(working_qty[sorted_idx]),
                    "working_price": float(working_price[sorted_idx]),
                    "working_trigger_price": float(working_trigger[sorted_idx]),
                    "reduce_only": bool(command.reduce_only),
                    "tag": command.tag,
                }
            )
        if not rows:
            return pd.DataFrame()
        return pd.DataFrame(rows).sort_values("original_index", kind="stable").reset_index(drop=True)

    @staticmethod
    def _build_order_events(
        *,
        idx: pd.DatetimeIndex,
        compiled_commands: CompiledOrderCommandArrays,
        event_count: int,
        event_bar: np.ndarray,
        event_command: np.ndarray,
        event_type: np.ndarray,
        event_status: np.ndarray,
        event_related_command: np.ndarray,
    ) -> pd.DataFrame:
        rows = []
        for n in range(event_count):
            command_idx = int(event_command[n])
            related_idx = int(event_related_command[n])
            original_idx = -1
            related_original_idx = -1
            command = None
            if 0 <= command_idx < len(compiled_commands.sorted_commands):
                original_idx = int(compiled_commands.sorted_commands[command_idx][0])
                command = compiled_commands.sorted_commands[command_idx][1]
            if 0 <= related_idx < len(compiled_commands.sorted_commands):
                related_original_idx = int(compiled_commands.sorted_commands[related_idx][0])
            bar = int(event_bar[n])
            rows.append(
                {
                    "timestamp": idx[bar] if 0 <= bar < len(idx) else pd.NaT,
                    "bar": bar,
                    "sorted_index": command_idx,
                    "original_index": original_idx,
                    "event_type": int(event_type[n]),
                    "event_name": _event_type_name(int(event_type[n])),
                    "status": int(event_status[n]),
                    "related_sorted_index": related_idx,
                    "related_original_index": related_original_idx,
                    "order_id": None if command is None else command.order_id,
                    "target_order_id": None if command is None else command.target_order_id,
                    "oco_group_id": None if command is None else command.oco_group_id,
                }
            )
        return pd.DataFrame(rows)

    @staticmethod
    def _commands_to_order_intents(sorted_commands) -> tuple[OrderIntent, ...]:
        orders: list[OrderIntent] = []
        for _, command in sorted_commands:
            if command.action in (OrderAction.PLACE, OrderAction.REPLACE):
                if command.symbol is None or command.side is None or command.order_type is None or command.qty is None:
                    continue
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
                        metadata=dict(command.metadata),
                    )
                )
        return tuple(orders)

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
        instruments: Optional[Union[Dict[str, InstrumentSpec], List[InstrumentSpec]]] = None,
        qty_step: Optional[Union[float, Dict[str, float]]] = None,
        lot_size: Optional[Union[float, Dict[str, float]]] = None,
        slot_size: Optional[Union[float, Dict[str, float]]] = None,
        min_qty: Optional[Union[float, Dict[str, float]]] = None,
        min_notional: Optional[Union[float, Dict[str, float]]] = None,
        market_arrays: Optional[PreparedMarketArrays] = None,
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
            market_arrays=market_arrays,
            instruments=instruments,
            qty_step=qty_step,
            lot_size=lot_size,
            slot_size=slot_size,
            min_qty=min_qty,
            min_notional=min_notional,
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
        market_arrays: Optional[PreparedMarketArrays] = None,
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
        stat_funding = self._funding_for_spec(spec, funding_rate)
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
            funding_rate=stat_funding,
            contract_size=contract_sizes,
            leverage=leverage,
            fee_rate=fee_rates,
            symbols=symbols,
            market_arrays=market_arrays,
        )
        funding_dict = prepare_funding(stat_funding if self.config.use_funding else 0.0, symbols, idx)
        roles = self._stat_arb_roles(spec)
        leg_pnl_report = self._leg_pnl_report(
            idx=idx,
            symbols=symbols,
            roles=roles,
            result=result,
            closes=close_dict,
            funding=funding_dict,
            contract_sizes=contract_sizes,
        )
        package_report = self._package_pnl_report(idx, result, leg_pnl_report)
        beta_drift_report = self._stat_arb_beta_drift_report(
            idx=idx,
            spec=spec,
            plan=arb_plan,
            rebalance_threshold=rebalance_threshold,
        )
        diagnostics = result.diagnostics.copy()
        diagnostics["package_pnl"] = package_report["package_pnl"]
        diagnostics["package_pnl_residual"] = package_report["pnl_residual"]
        result.diagnostics = diagnostics
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
                "spread_report": self._stat_arb_spread_report(idx, spec, close_dict, arb_plan),
                "leg_pnl_report": leg_pnl_report,
                "package_pnl_report": package_report,
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
        market_arrays: Optional[PreparedMarketArrays] = None,
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
            market_arrays=market_arrays,
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
        market_arrays: Optional[PreparedMarketArrays] = None,
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
            market_arrays=market_arrays,
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
    def _market_signature(idx: pd.DatetimeIndex, symbols: List[str]):
        from ..core.preprocessor import market_data_signature

        return market_data_signature(idx, symbols)

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
    def _stat_arb_roles(spec: StatArbPairSpec) -> Dict[str, str]:
        symbols = [leg.symbol for leg in spec.legs]
        roles = {leg.symbol: str(leg.role or "leg") for leg in spec.legs}
        if len(symbols) >= 2 and len(set(roles.values())) == 1:
            roles[symbols[0]] = "leg"
            roles[symbols[1]] = "hedge"
        return roles

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

    def _leg_pnl_report(
        self,
        idx: pd.DatetimeIndex,
        symbols: List[str],
        roles: Dict[str, str],
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
        cumulative = {symbol: 0.0 for symbol in symbols}
        rows = []
        for i, ts in enumerate(idx):
            for symbol in symbols:
                cs = float(contract_sizes[symbol])
                close_price = float(closes[symbol].iloc[i])
                prev_units = 0.0 if i == 0 else float(result.positions[f"Position_{symbol}"].iloc[i - 1])
                units = float(result.positions[f"Position_{symbol}"].iloc[i])
                price_pnl = 0.0
                if i > 0:
                    price_pnl = prev_units * (close_price - float(closes[symbol].iloc[i - 1])) * cs
                funding_cost = 0.0
                if self.config.use_funding and funding_mask[i]:
                    funding_cost = prev_units * close_price * cs * float(funding[symbol].iloc[i])
                fee, fill_pnl = fill_rows.get((ts, symbol), (0.0, 0.0))
                total_pnl = price_pnl + fill_pnl - fee - funding_cost
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
                        "fill_pnl": fill_pnl,
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
        filled_indices = np.flatnonzero(fill_bar >= 0)
        for sorted_idx in filled_indices:
            order = sorted_orders[int(sorted_idx)][1]
            bar = int(fill_bar[sorted_idx])
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
