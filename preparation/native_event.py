"""One-pass preparation for static native-event lifecycle command tapes."""

from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
import json
from typing import Mapping, Sequence

import numpy as np
import pandas as pd

from ..core.constraints import quantize_signed_quantity
from ..core.instrument_contracts import compile_instrument_table
from ..core.order_compiler import CompiledOrderCommandArrays, compile_order_commands
from ..core.orders import OrderAction, OrderCommand
from ..core.preprocessor import align_series, build_market_arrays, prepare_funding, validate_datetime
from ..core.schema import AccountConfig, ExecutionConfig, InstrumentSpec
from ..planning import ExecutionPlan
from .models import (
    PreparationDiagnostics,
    PreparationKeys,
    PreparedAccount,
    PreparedCommandTape,
    PreparedInstruments,
    PreparedMarket,
    PreparedRun,
)


def _hash_parts(*parts) -> str:
    digest = hashlib.sha256()
    for part in parts:
        if isinstance(part, np.ndarray):
            array = np.ascontiguousarray(part)
            digest.update(str(array.dtype).encode("ascii"))
            digest.update(str(array.shape).encode("ascii"))
            digest.update(array.tobytes())
        else:
            digest.update(
                json.dumps(part, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
            )
    return digest.hexdigest()


def _per_symbol(value, symbols: tuple[str, ...], default: float) -> np.ndarray:
    if isinstance(value, Mapping):
        return np.asarray([float(value.get(symbol, default)) for symbol in symbols], dtype=np.float64)
    return np.full(len(symbols), float(value), dtype=np.float64)


def _instrument_map(instruments) -> dict[str, InstrumentSpec]:
    if instruments is None:
        return {}
    if isinstance(instruments, Mapping):
        return {str(symbol): spec for symbol, spec in instruments.items() if spec is not None}
    return {spec.symbol: spec for spec in instruments}


def _optional_value(value, symbol: str, fallback: float) -> float:
    if value is None:
        return float(fallback)
    if isinstance(value, Mapping):
        return float(value.get(symbol, fallback))
    return float(value)


def _resolved_instruments(
    symbols: tuple[str, ...],
    *,
    instruments,
    contract_size,
    qty_step=None,
    lot_size=None,
    slot_size=None,
    min_qty=None,
    min_notional=None,
) -> tuple[InstrumentSpec, ...]:
    source = _instrument_map(instruments)
    explicit_step = qty_step if qty_step is not None else (lot_size if lot_size is not None else slot_size)
    resolved = []
    for symbol in symbols:
        base = source.get(symbol) or InstrumentSpec(symbol=symbol)
        resolved.append(
            replace(
                base,
                contract_size=_optional_value(contract_size, symbol, base.contract_size),
                lot_size=_optional_value(explicit_step, symbol, base.lot_size),
                min_qty=_optional_value(min_qty, symbol, base.min_qty),
                min_notional=_optional_value(min_notional, symbol, base.min_notional),
            )
        )
    return tuple(resolved)


def _apply_quantity_preflight(
    *,
    index: pd.DatetimeIndex,
    commands: Sequence[OrderCommand],
    closes: np.ndarray,
    symbols: tuple[str, ...],
    table,
) -> tuple[tuple[OrderCommand, ...], dict[str, object]]:
    constraints_enabled = bool(
        np.any(table.qty_step > 0.0)
        or np.any(table.min_qty > 0.0)
        or np.any(table.min_notional > 0.0)
    )
    if not constraints_enabled:
        return tuple(commands), {"changed_count": 0, "dropped_count": 0, "dropped_orders": []}
    symbol_to_col = {symbol: col for col, symbol in enumerate(symbols)}
    index_ns = index.view("int64")
    changed = 0
    dropped: list[dict[str, object]] = []
    output: list[OrderCommand] = []
    for command_index, command in enumerate(commands):
        if command.action not in {OrderAction.PLACE, OrderAction.REPLACE} or command.symbol is None:
            output.append(command)
            continue
        if command.symbol not in symbol_to_col:
            raise ValueError(f"command symbol {command.symbol!r} is not in symbols")
        col = symbol_to_col[command.symbol]
        timestamp = pd.Timestamp(command.timestamp)
        timestamp = timestamp.tz_localize("UTC") if timestamp.tz is None else timestamp.tz_convert("UTC")
        bar = min(int(np.searchsorted(index_ns, timestamp.value, side="left")), len(index) - 1)
        price = float(command.price) if command.price is not None else float(closes[bar, col])
        quantity = abs(
            quantize_signed_quantity(
                command.signed_qty,
                price,
                float(table.contract_size[col]),
                float(table.qty_step[col]),
                float(table.min_qty[col]),
                float(table.min_notional[col]),
            )
        )
        if quantity <= 0.0:
            dropped.append(
                {
                    "original_index": command_index,
                    "symbol": command.symbol,
                    "requested_qty": None if command.qty is None else float(command.qty),
                }
            )
            continue
        if command.qty is not None and abs(quantity - float(command.qty)) > 1e-12:
            changed += 1
            command = replace(
                command,
                qty=quantity,
                metadata={
                    **command.metadata,
                    "requested_qty": float(command.qty),
                    "quantity_quantized": True,
                },
            )
        output.append(command)
    return tuple(output), {
        "changed_count": changed,
        "dropped_count": len(dropped),
        "dropped_orders": dropped,
    }


def _primitive_command_tape(compiled: CompiledOrderCommandArrays) -> PreparedCommandTape:
    return PreparedCommandTape(
        symbols=tuple(compiled.symbols),
        id_values=tuple(compiled.id_values),
        command_ptr=compiled.command_ptr,
        command_bar=compiled.command_bar,
        command_action=compiled.command_action,
        command_symbol=compiled.command_symbol,
        command_side=compiled.command_side,
        command_type=compiled.command_type,
        command_qty=compiled.command_qty,
        command_price=compiled.command_price,
        command_trigger_price=compiled.command_trigger_price,
        command_tif=compiled.command_tif,
        command_reduce_only=compiled.command_reduce_only,
        command_order_id=compiled.command_order_id,
        command_target_order_id=compiled.command_target_order_id,
        command_parent_order_id=compiled.command_parent_order_id,
        command_group_id=compiled.command_group_id,
        command_oco_group_id=compiled.command_oco_group_id,
        command_activation=compiled.command_activation,
        command_expires_bar=compiled.command_expires_bar,
        original_index=compiled.original_index,
        fingerprint=compiled.tape_fingerprint,
    )


@dataclass(frozen=True, slots=True)
class NativeEventPreparation:
    prepared: PreparedRun
    effective_commands: tuple[OrderCommand, ...]
    quantity_preflight: Mapping[str, object]
    datetime_index: pd.DatetimeIndex


def prepare_native_event_lifecycle(
    *,
    plan: ExecutionPlan,
    datetime_index,
    commands: Sequence[OrderCommand],
    closes,
    highs=None,
    lows=None,
    opens=None,
    volumes=None,
    funding_rate=0.0,
    symbols: Sequence[str] | None = None,
    instruments=None,
    contract_size=1.0,
    leverage=1.0,
    fee_rate=0.0,
    qty_step=None,
    lot_size=None,
    slot_size=None,
    min_qty=None,
    min_notional=None,
    account: AccountConfig,
    execution: ExecutionConfig,
    use_funding: bool = True,
) -> NativeEventPreparation:
    """Normalize and compile a static lifecycle request exactly once."""

    index = validate_datetime(datetime_index)
    if len(index) == 0:
        raise ValueError("native-event preparation requires at least one market bar")
    symbol_values = tuple(symbols or closes.keys())
    if not symbol_values:
        raise ValueError("native-event preparation requires symbols")
    close_map = align_series(closes, list(symbol_values), index)
    high_map = align_series(highs, list(symbol_values), index, fallback=close_map)
    low_map = align_series(lows, list(symbol_values), index, fallback=close_map)
    funding_map = prepare_funding(funding_rate if use_funding else 0.0, list(symbol_values), index)
    market_arrays = build_market_arrays(
        symbols=list(symbol_values),
        idx=index,
        closes_dict=close_map,
        highs_dict=high_map,
        lows_dict=low_map,
        funding_dict=funding_map,
    )
    if opens is None:
        if plan.contract_id == "event_lifecycle_v3_next_open":
            raise ValueError("event_lifecycle_v3_next_open requires explicit open prices")
        opens_array = np.ascontiguousarray(market_arrays.closes, dtype=np.float64)
    else:
        open_map = align_series(opens, list(symbol_values), index)
        opens_array = np.ascontiguousarray(
            np.column_stack([open_map[symbol].to_numpy(dtype=np.float64) for symbol in symbol_values])
        )
    if volumes is None:
        volumes_array = np.zeros_like(market_arrays.closes)
    else:
        volume_map = align_series(volumes, list(symbol_values), index, fill_val=0.0)
        volumes_array = np.ascontiguousarray(
            np.column_stack([volume_map[symbol].fillna(0.0).to_numpy(dtype=np.float64) for symbol in symbol_values])
        )
    timestamps_ns = np.ascontiguousarray(index.view("int64"), dtype=np.int64)
    market_fingerprint = _hash_parts(
        plan.market_layout.value,
        symbol_values,
        timestamps_ns,
        opens_array,
        market_arrays.highs,
        market_arrays.lows,
        market_arrays.closes,
        volumes_array,
        market_arrays.funding,
        market_arrays.is_funding_bar,
    )
    market = PreparedMarket(
        timestamps_ns=timestamps_ns,
        symbols=symbol_values,
        opens=opens_array,
        highs=market_arrays.highs,
        lows=market_arrays.lows,
        closes=market_arrays.closes,
        volumes=volumes_array,
        funding_rates=market_arrays.funding,
        funding_event_mask=market_arrays.is_funding_bar,
        fingerprint=market_fingerprint,
    )

    specs = _resolved_instruments(
        symbol_values,
        instruments=instruments,
        contract_size=contract_size,
        qty_step=qty_step,
        lot_size=lot_size,
        slot_size=slot_size,
        min_qty=min_qty,
        min_notional=min_notional,
    )
    table = compile_instrument_table(symbol_values, specs)
    leverages = _per_symbol(leverage, symbol_values, account.leverage)
    fee_rates = _per_symbol(fee_rate, symbol_values, 0.0)
    instrument_fingerprint = _hash_parts(table.fingerprint, leverages, fee_rates)
    prepared_instruments = PreparedInstruments(
        table=table,
        leverages=leverages,
        fee_rates=fee_rates,
        fingerprint=instrument_fingerprint,
    )

    effective_commands, preflight = _apply_quantity_preflight(
        index=index,
        commands=commands,
        closes=market.closes,
        symbols=symbol_values,
        table=table,
    )
    compiled = compile_order_commands(
        idx=index,
        commands=effective_commands,
        symbol_to_col={symbol: col for col, symbol in enumerate(symbol_values)},
    )
    command_tape = _primitive_command_tape(compiled)
    account_fingerprint = _hash_parts(
        account.initial_capital,
        account.maintenance_ratio,
        execution.slippage_rate,
        bool(use_funding),
        leverages,
        fee_rates,
    )
    prepared_account = PreparedAccount(
        initial_capital=float(account.initial_capital),
        maintenance_ratio=float(account.maintenance_ratio),
        slippage_rate=float(execution.slippage_rate),
        use_funding=bool(use_funding),
        fingerprint=account_fingerprint,
    )
    combined = _hash_parts(
        plan.plan_fingerprint,
        market_fingerprint,
        instrument_fingerprint,
        command_tape.fingerprint,
        account_fingerprint,
    )
    keys = PreparationKeys(
        plan=plan.plan_fingerprint,
        market=market_fingerprint,
        instruments=instrument_fingerprint,
        commands=command_tape.fingerprint,
        account=account_fingerprint,
        combined=combined,
    )
    diagnostics = PreparationDiagnostics(
        market_bytes=sum(
            array.nbytes
            for array in (
                market.timestamps_ns,
                market.opens,
                market.highs,
                market.lows,
                market.closes,
                market.volumes,
                market.funding_rates,
                market.funding_event_mask,
            )
        ),
        instrument_bytes=sum(
            getattr(table, name).nbytes
            for name in (
                "symbol_code", "venue_code", "contract_type", "tick_size", "qty_step",
                "min_qty", "max_qty", "min_notional", "contract_size", "price_scale",
                "qty_scale", "settlement_code", "fee_model_id", "margin_model_id",
            )
        ) + leverages.nbytes + fee_rates.nbytes,
        command_bytes=sum(array.nbytes for array in command_tape.arrays()),
    )
    prepared = PreparedRun(
        plan=plan,
        market=market,
        instruments=prepared_instruments,
        account=prepared_account,
        command_tape=command_tape,
        keys=keys,
        diagnostics=diagnostics,
    )
    return NativeEventPreparation(
        prepared=prepared,
        effective_commands=effective_commands,
        quantity_preflight=preflight,
        datetime_index=index,
    )


__all__ = ["NativeEventPreparation", "prepare_native_event_lifecycle"]
