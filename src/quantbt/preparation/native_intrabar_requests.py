"""Immutable Rust intrabar request construction for prepared execution.

The intrabar kernel has a distinct execution contract from command, target,
and package requests, but it must obey the same preparation rules: one owned
market tape, content-addressed request identity, and exactly one controlled
Python-to-Rust intent ingestion.  This module is deliberately a sibling of the
other request builders so ``NativeExecutionPreparationCache`` remains the
single cache/lifetime authority.
"""

from __future__ import annotations

from typing import Any

import numpy as np


def _optional_array(
    value: object | None,
    *,
    default: object,
    dtype: np.dtype,
    bars: int,
    name: str,
) -> tuple[np.ndarray, int, int]:
    """Normalize a full-length intrabar vector or create its explicit default."""

    from .native_execution import _normalise_array  # noqa: PLC0415

    if value is None:
        return np.full(bars, default, dtype=dtype), 0, 0
    array, copies, copied_bytes = _normalise_array(value, dtype=dtype, ndim=1, name=name)
    if array.shape != (bars,):
        raise ValueError(f"native intrabar {name} must have one value per prepared market bar")
    return array, copies, copied_bytes


def prepare_intrabar_request(
    cache: Any,
    market: Any,
    *,
    entry_side: object,
    entry_size: object,
    stop_value: object | None,
    take_profit_value: object | None,
    trailing_value: object | None,
    exit_long: object | None,
    exit_short: object | None,
    level_mode: int,
    initial_capital: float,
    leverage: float,
    maintenance_ratio: float,
    margin_buffer: float,
    contract_size: float,
    fee_rate: float,
    slippage_rate: float,
    sizing_mode: int,
    fixed_notional: float,
    equity_fraction: float,
    risk_fraction: float,
    qty_step: float,
    min_qty: float,
    min_notional: float,
    tick_size: float,
    bar_timestamp_semantics: int,
    same_bar_policy: int,
    take_profit_gap_policy: int,
    close_on_last_bar: bool,
    output_profile: int = 1,
    audit_detail_limit: int = 250_000,
    session_id: object | None = None,
    entry_allowed_at_open: object | None = None,
    force_flat_at_open: object | None = None,
    entry_position_policy: int = 1,
    counter_basis: int = 1,
    protective_reentry_policy: int = 1,
    max_long_entries_per_session: int = -1,
    max_short_entries_per_session: int = -1,
    cancel_pending_on_session_change: bool = True,
    suppress_entry_on_force_flat_bar: bool = True,
    reuse_request: bool = True,
):
    """Build/reuse one immutable single-symbol intrabar Rust request.

    The caller supplies already-resolved numeric contract codes.  Strategy and
    endpoint layers retain responsibility for producing the intent tape; this
    builder owns only validation, cache identity, and native request ownership.

    ``reuse_request=False`` is intentionally narrow.  It is valid only for a
    caller that already owns the immutable prepared market and knows that this
    intent is a one-shot candidate (for example an Optuna/WFO trial).  The
    mutable intent still receives every dtype, shape, finite-value, and domain
    validation below, but the duplicate Python content digest and L4 cache
    lookup are skipped.  Rust still creates the authoritative request
    fingerprint from the exact copied input.  The default remains content-
    addressed reuse for compatibility callers.
    """

    from .native_execution import (  # noqa: PLC0415
        NativePreparedRequest,
        _PREPARATION_SCHEMA,
        _REQUEST_SCHEMA,
        _digest,
        _normalise_array,
    )

    if len(tuple(market.symbols)) != 1:
        raise NotImplementedError("prepared Rust intrabar requests certify one symbol only")
    bars = int(market.core.bars)
    profile = int(output_profile)
    if profile not in {0, 1, 2}:
        raise ValueError("native intrabar output_profile must be 0 (score), 1 (compact), or 2 (audit)")
    if int(audit_detail_limit) <= 0:
        raise ValueError("native intrabar audit_detail_limit must be > 0")

    side, side_copies, side_bytes = _normalise_array(
        entry_side, dtype=np.dtype(np.int8), ndim=1, name="entry_side"
    )
    size, size_copies, size_bytes = _normalise_array(
        entry_size, dtype=np.dtype(np.float64), ndim=1, name="entry_size"
    )
    if side.shape != (bars,) or size.shape != (bars,):
        raise ValueError("native intrabar entry vectors must match prepared market bars")
    if not np.isfinite(size).all() or (size < 0.0).any() or not np.isin(side, (-1, 0, 1)).all():
        raise ValueError("native intrabar entry_side must be -1/0/1 and entry_size must be finite non-negative")

    arrays: dict[str, np.ndarray] = {"entry_side": side, "entry_size": size}
    copies = side_copies + size_copies
    copied_bytes = side_bytes + size_bytes
    for name, value, default, dtype in (
        ("stop_value", stop_value, np.nan, np.dtype(np.float64)),
        ("take_profit_value", take_profit_value, np.nan, np.dtype(np.float64)),
        ("trailing_value", trailing_value, np.nan, np.dtype(np.float64)),
        ("exit_long", exit_long, False, np.dtype(np.bool_)),
        ("exit_short", exit_short, False, np.dtype(np.bool_)),
    ):
        array, count, byte_count = _optional_array(
            value, default=default, dtype=dtype, bars=bars, name=name
        )
        arrays[name] = array
        copies += count
        copied_bytes += byte_count

    session_enabled = any(
        value is not None for value in (session_id, entry_allowed_at_open, force_flat_at_open)
    )
    if session_enabled and not all(
        value is not None for value in (session_id, entry_allowed_at_open, force_flat_at_open)
    ):
        raise ValueError(
            "native intrabar session_id, entry_allowed_at_open, and force_flat_at_open must be supplied together"
        )
    if session_enabled:
        for name, value, dtype in (
            ("session_id", session_id, np.dtype(np.int64)),
            ("entry_allowed_at_open", entry_allowed_at_open, np.dtype(np.bool_)),
            ("force_flat_at_open", force_flat_at_open, np.dtype(np.bool_)),
        ):
            array, count, byte_count = _optional_array(
                value, default=0, dtype=dtype, bars=bars, name=name
            )
            arrays[name] = array
            copies += count
            copied_bytes += byte_count

    scalar_contract = (
        int(level_mode),
        float(initial_capital),
        float(leverage),
        float(maintenance_ratio),
        float(margin_buffer),
        float(contract_size),
        float(fee_rate),
        float(slippage_rate),
        int(sizing_mode),
        float(fixed_notional),
        float(equity_fraction),
        float(risk_fraction),
        float(qty_step),
        float(min_qty),
        float(min_notional),
        float(tick_size),
        int(bar_timestamp_semantics),
        int(same_bar_policy),
        int(take_profit_gap_policy),
        bool(close_on_last_bar),
        profile,
        int(audit_detail_limit),
        bool(session_enabled),
        int(entry_position_policy),
        int(counter_basis),
        int(protective_reentry_policy),
        int(max_long_entries_per_session),
        int(max_short_entries_per_session),
        bool(cancel_pending_on_session_change),
        bool(suppress_entry_on_force_flat_bar),
    )
    numeric_scalars = np.asarray(
        [
            float(initial_capital), float(leverage), float(maintenance_ratio), float(margin_buffer),
            float(contract_size), float(fee_rate), float(slippage_rate), float(fixed_notional),
            float(equity_fraction), float(risk_fraction), float(qty_step), float(min_qty),
            float(min_notional), float(tick_size),
        ],
        dtype=np.float64,
    )
    if not np.isfinite(numeric_scalars).all() or float(initial_capital) <= 0.0 or float(leverage) <= 0.0:
        raise ValueError("native intrabar account and execution scalars must be finite with positive capital/leverage")

    field_order = (
        "entry_side", "entry_size", "stop_value", "take_profit_value", "trailing_value", "exit_long", "exit_short",
        "session_id", "entry_allowed_at_open", "force_flat_at_open",
    )
    key = None
    if bool(reuse_request):
        signature = _digest(
            _REQUEST_SCHEMA,
            _PREPARATION_SCHEMA,
            market.signature,
            "intrabar_bracket_v1",
            scalar_contract,
            *(arrays[name] for name in field_order if name in arrays),
        )
        key = (_REQUEST_SCHEMA, signature)

    with cache._lock:
        if key is not None:
            cached = cache._request_cache.get(key)
            if cached is not None:
                return cached
        native = cache._native()
        if not hasattr(native, "NativeIntrabarRequestCore"):
            raise RuntimeError("installed quantbt-native extension lacks NativeIntrabarRequestCore")
        core = native.NativeIntrabarRequestCore.from_prepared(
            market.core,
            arrays["entry_side"],
            arrays["entry_size"],
            arrays["stop_value"],
            arrays["take_profit_value"],
            arrays["trailing_value"],
            arrays["exit_long"],
            arrays["exit_short"],
            level_mode=int(level_mode),
            initial_capital=float(initial_capital),
            leverage=float(leverage),
            maintenance_ratio=float(maintenance_ratio),
            margin_buffer=float(margin_buffer),
            contract_size=float(contract_size),
            fee_rate=float(fee_rate),
            slippage_rate=float(slippage_rate),
            sizing_mode=int(sizing_mode),
            fixed_notional=float(fixed_notional),
            equity_fraction=float(equity_fraction),
            risk_fraction=float(risk_fraction),
            qty_step=float(qty_step),
            min_qty=float(min_qty),
            min_notional=float(min_notional),
            tick_size=float(tick_size),
            bar_timestamp_semantics=int(bar_timestamp_semantics),
            same_bar_policy=int(same_bar_policy),
            take_profit_gap_policy=int(take_profit_gap_policy),
            close_on_last_bar=bool(close_on_last_bar),
            output_profile=profile,
            audit_detail_limit=int(audit_detail_limit),
            session_id=arrays.get("session_id"),
            entry_allowed_at_open=arrays.get("entry_allowed_at_open"),
            force_flat_at_open=arrays.get("force_flat_at_open"),
            entry_position_policy=int(entry_position_policy),
            counter_basis=int(counter_basis),
            protective_reentry_policy=int(protective_reentry_policy),
            max_long_entries_per_session=int(max_long_entries_per_session),
            max_short_entries_per_session=int(max_short_entries_per_session),
            cancel_pending_on_session_change=bool(cancel_pending_on_session_change),
            suppress_entry_on_force_flat_bar=bool(suppress_entry_on_force_flat_bar),
        )
        request_bytes = int(sum(array.nbytes for array in arrays.values()))
        record = NativePreparedRequest(
            core=core,
            template=None,
            signature=str(core.fingerprint),
            workload="intrabar_bracket_v1",
            request_bytes=request_bytes,
            market_signature=market.signature,
        )
        if key is not None:
            cache._request_cache.put(key, record, size_bytes=request_bytes)
        cache._ingress_copy_count += copies
        cache._ingress_copied_bytes += copied_bytes
        return record


__all__ = ["prepare_intrabar_request"]
