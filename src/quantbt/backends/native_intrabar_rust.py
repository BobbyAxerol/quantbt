"""Explicit Rust authority adapter for ``intrabar_bracket_v1``.

This module is intentionally narrow: the Python reference remains the readable
oracle and the Numba implementation remains the rollback comparator.  The Rust
request executes one complete bounded single-symbol OHLC tape without a Python
per-bar callback or a Python accounting replay.
"""

from __future__ import annotations

import importlib
from dataclasses import dataclass
from typing import Any, Dict, Optional

import numpy as np
import pandas as pd

from ..core.execution_contract import ExecutionContract, IntrabarSameBarPolicy, TakeProfitGapPolicy
from ..core.intrabar_kernel import NativeIntrabarKernelResult
from ..core.intrabar_reference import IntrabarFill, IntrabarFillReason, IntrabarIntentTape, IntrabarLevelMode, IntrabarSizingMode
from ..core.intrabar_session import (
    EntryPositionPolicy,
    IntrabarSessionTape,
    ProtectiveExitReentryPolicy,
    SessionCounterBasis,
    SessionExecutionPolicy,
)
from ..core.market_tape import PreparedMarketTape
from ..core.schema import AccountConfig
from ..preparation.native_execution import (
    NativeExecutionPreparationCache,
    NativePreparedMarket,
    NativePreparedRequest,
)


class RustIntrabarUnavailable(RuntimeError):
    """Raised when an explicit Rust intrabar request cannot be executed."""


_LEVEL_CODE = {
    IntrabarLevelMode.ABSOLUTE_PRICE.value: 1,
    IntrabarLevelMode.PRICE_DISTANCE.value: 2,
    IntrabarLevelMode.PERCENT_DISTANCE.value: 3,
}
_SIZING_CODE = {
    IntrabarSizingMode.UNITS.value: 1,
    IntrabarSizingMode.FIXED_NOTIONAL.value: 2,
    IntrabarSizingMode.PCT_EQUITY.value: 3,
    IntrabarSizingMode.RISK_PER_TRADE.value: 4,
}
_SAME_BAR_CODE = {
    IntrabarSameBarPolicy.CONSERVATIVE.value: 1,
    IntrabarSameBarPolicy.STOP_FIRST.value: 2,
    IntrabarSameBarPolicy.TP_FIRST.value: 3,
    IntrabarSameBarPolicy.OHLC_PATH.value: 4,
    IntrabarSameBarPolicy.OLHC_PATH.value: 5,
}
_TP_GAP_CODE = {
    TakeProfitGapPolicy.LIMIT_PRICE_CONSERVATIVE.value: 1,
    TakeProfitGapPolicy.OPEN_PRICE_IMPROVEMENT.value: 2,
}
_SESSION_ENTRY_CODE = {
    EntryPositionPolicy.CURRENT_BEHAVIOR.value: 1,
    EntryPositionPolicy.FLAT_ONLY.value: 2,
    EntryPositionPolicy.REVERSE.value: 3,
}
_SESSION_COUNTER_CODE = {
    SessionCounterBasis.FILLED_ENTRY.value: 1,
    SessionCounterBasis.ACCEPTED_ENTRY.value: 2,
}
_SESSION_REENTRY_CODE = {
    ProtectiveExitReentryPolicy.ALLOW.value: 1,
    ProtectiveExitReentryPolicy.SUPPRESS_SIGNAL_BAR.value: 2,
}
_REASON_CODE = {
    1: IntrabarFillReason.ENTRY,
    2: IntrabarFillReason.TECHNICAL_EXIT,
    3: IntrabarFillReason.REVERSAL_EXIT,
    4: IntrabarFillReason.REVERSAL_ENTRY,
    5: IntrabarFillReason.STOP_LOSS,
    6: IntrabarFillReason.TAKE_PROFIT,
    7: IntrabarFillReason.LIQUIDATION,
    8: IntrabarFillReason.FINAL_CLOSE,
    9: IntrabarFillReason.SESSION_FORCED_EXIT,
}


def _native_module() -> Any:
    try:
        native = importlib.import_module("_quantbt_native")
    except Exception as exc:  # pragma: no cover - environment dependent
        raise RustIntrabarUnavailable(
            "intrabar_bracket_rust requires an installed compatible quantbt-native extension"
        ) from exc
    required = ("FullPreparedMarketCore", "NativeIntrabarRequestCore")
    missing = [name for name in required if not hasattr(native, name)]
    if missing:
        raise RustIntrabarUnavailable(
            "installed quantbt-native extension lacks Rust intrabar authority: " + ", ".join(missing)
        )
    return native


def _float_tape(value, n: int) -> np.ndarray:
    if value is None:
        return np.full(n, np.nan, dtype=np.float64)
    return np.ascontiguousarray(value, dtype=np.float64)


def _bool_tape(value, n: int) -> np.ndarray:
    if value is None:
        return np.zeros(n, dtype=np.bool_)
    return np.ascontiguousarray(value, dtype=np.bool_)


def _prepare_market(
    tape: PreparedMarketTape,
    *,
    cache: Optional[NativeExecutionPreparationCache],
) -> tuple[Any, str, int]:
    arrays = {
        "timestamps_ns": np.ascontiguousarray(tape.timestamps_ns, dtype=np.int64),
        "opens": np.ascontiguousarray(tape.opens, dtype=np.float64),
        "highs": np.ascontiguousarray(tape.highs, dtype=np.float64),
        "lows": np.ascontiguousarray(tape.lows, dtype=np.float64),
        "closes": np.ascontiguousarray(tape.closes, dtype=np.float64),
        "volumes": np.ascontiguousarray(tape.volumes, dtype=np.float64),
        "funding": np.ascontiguousarray(tape.funding_rates, dtype=np.float64),
        "funding_mask": np.ascontiguousarray(tape.funding_event_mask, dtype=np.bool_),
    }
    if cache is not None:
        prepared = cache.prepare_market(symbols=tape.symbols, **arrays)
        return prepared.core, prepared.signature, int(prepared.prepared_bytes)
    native = _native_module()
    # Keep the direct path byte-for-byte equivalent to
    # NativeExecutionPreparationCache.prepare_market().  PyO3 exposes this
    # constructor positionally, whereas the cache also records the immutable
    # content signature for repeated runs.
    core = native.FullPreparedMarketCore(
        arrays["timestamps_ns"],
        arrays["opens"],
        arrays["highs"],
        arrays["lows"],
        arrays["closes"],
        arrays["volumes"],
        arrays["funding"],
        arrays["funding_mask"],
    )
    return core, tape.signature, int(getattr(core, "prepared_bytes", 0))


def _profile_code(report_level: str) -> int:
    value = str(report_level or "standard").lower().strip()
    if value in {"minimal", "standard", "compact", "full"}:
        return 1
    if value in {"audit", "debug"}:
        return 2
    if value in {"score", "optimizer", "scoring"}:
        return 0
    raise ValueError("report_level must be minimal, standard, audit, or score")


def _contract_codes(contract: ExecutionContract, tape: PreparedMarketTape) -> tuple[int, int, int]:
    if contract.engine_id != "intrabar_bracket_v1":
        raise ValueError("Rust intrabar adapter requires intrabar_bracket_v1")
    same_bar = contract.same_bar_policy.value
    if same_bar not in _SAME_BAR_CODE:
        raise NotImplementedError(
            "Rust intrabar route does not execute "
            f"same_bar_policy={same_bar!r}; use intrabar_bracket_reference "
            "for diagnostic rejection or a lower-timeframe route"
        )
    return (
        1 if tape.bar_timestamp_semantics == "close" else 2,
        _SAME_BAR_CODE[same_bar],
        _TP_GAP_CODE[contract.take_profit_gap_policy.value],
    )


def _session_kwargs(
    session_policy: Optional[SessionExecutionPolicy],
    session_tape: Optional[IntrabarSessionTape],
) -> Dict[str, Any]:
    if (session_policy is None) != (session_tape is None):
        raise ValueError("session_policy and session_tape must be supplied together")
    if session_policy is None:
        return {}
    policy = SessionExecutionPolicy.from_metadata(session_policy.to_metadata())
    return {
        "session_id": np.ascontiguousarray(session_tape.session_id, dtype=np.int64),
        "entry_allowed_at_open": np.ascontiguousarray(session_tape.entry_allowed_at_open, dtype=np.bool_),
        "force_flat_at_open": np.ascontiguousarray(session_tape.force_flat_at_open, dtype=np.bool_),
        "entry_position_policy": _SESSION_ENTRY_CODE[policy.entry_position_policy.value],
        "counter_basis": _SESSION_COUNTER_CODE[policy.counter_basis.value],
        "protective_reentry_policy": _SESSION_REENTRY_CODE[policy.protective_exit_reentry_policy.value],
        "max_long_entries_per_session": -1
        if policy.max_long_entries_per_session is None
        else int(policy.max_long_entries_per_session),
        "max_short_entries_per_session": -1
        if policy.max_short_entries_per_session is None
        else int(policy.max_short_entries_per_session),
        "cancel_pending_on_session_change": bool(policy.cancel_pending_on_session_change),
        "suppress_entry_on_force_flat_bar": bool(policy.suppress_entry_on_force_flat_bar),
    }


def _materialize_fills(
    payload: Dict[str, Any],
    timestamps_ns: np.ndarray,
    *,
    index: Optional[pd.DatetimeIndex] = None,
) -> tuple[IntrabarFill, ...]:
    bars = np.asarray(payload["fill_bar"], dtype=np.int64)
    sequence = np.asarray(payload["fill_sequence"], dtype=np.int64)
    sides = np.asarray(payload["fill_side"], dtype=np.int8)
    qty = np.asarray(payload["fill_qty"], dtype=np.float64)
    price = np.asarray(payload["fill_price"], dtype=np.float64)
    fee = np.asarray(payload["fill_fee"], dtype=np.float64)
    reasons = np.asarray(payload["fill_reason"], dtype=np.int16)
    if index is None:
        index = pd.DatetimeIndex(pd.to_datetime(timestamps_ns, utc=True))
    return tuple(
        IntrabarFill(
            bar_index=int(bar),
            sequence=int(seq),
            timestamp=pd.Timestamp(index[int(bar)]),
            side=int(side),
            qty=float(amount),
            price=float(fill_price),
            fee=float(fill_fee),
            reason=_REASON_CODE[int(reason)],
        )
        for bar, seq, side, amount, fill_price, fill_fee, reason in zip(
            bars, sequence, sides, qty, price, fee, reasons
        )
    )


def _fills_report(fills: tuple[IntrabarFill, ...], payload: Dict[str, Any]) -> pd.DataFrame:
    ambiguity = np.asarray(payload["fill_ambiguity"], dtype=np.bool_)
    same_bar_policy = np.asarray(payload["fill_same_bar_policy"], dtype=np.uint8)
    if len(ambiguity) != len(fills) or len(same_bar_policy) != len(fills):
        raise RuntimeError("Rust intrabar audit fill columns do not match the materialized fill count")
    return pd.DataFrame(
        [
            {
                "bar_index": fill.bar_index,
                "sequence": fill.sequence,
                "timestamp": fill.timestamp,
                "side": fill.side,
                "qty": fill.qty,
                "price": fill.price,
                "fee": fill.fee,
                "reason": fill.reason.value,
                "ambiguity_flag": bool(ambiguity[index]),
                "same_bar_policy_id": int(same_bar_policy[index]),
            }
            for index, fill in enumerate(fills)
        ]
    )


@dataclass(frozen=True, slots=True)
class PreparedRustIntrabarMarketV1:
    """Immutable market owner used by repeated bounded intrabar requests.

    The handle is intentionally created only from a validated
    :class:`PreparedMarketTape`.  It owns the content-addressed Rust market and
    its one-time timestamp index, so a prepared WFO/service runner can validate
    each changing intent without hashing or rebuilding the immutable OHLCV tape
    on every candidate.
    """

    cache: NativeExecutionPreparationCache
    market: NativePreparedMarket
    tape_signature: str
    datetime_index: pd.DatetimeIndex
    bar_timestamp_semantics: str


def prepare_rust_intrabar_market(
    *,
    tape: PreparedMarketTape,
    native_preparation_cache: Optional[NativeExecutionPreparationCache] = None,
) -> PreparedRustIntrabarMarketV1:
    """Prepare one immutable Rust market owner for repeated intrabar intents."""

    if tape.n_symbols != 1:
        raise NotImplementedError("Rust intrabar authority is certified for one symbol only")
    _native_module()
    cache = native_preparation_cache or NativeExecutionPreparationCache()
    market = cache.prepare_market(
        timestamps_ns=np.ascontiguousarray(tape.timestamps_ns, dtype=np.int64),
        opens=np.ascontiguousarray(tape.opens, dtype=np.float64),
        highs=np.ascontiguousarray(tape.highs, dtype=np.float64),
        lows=np.ascontiguousarray(tape.lows, dtype=np.float64),
        closes=np.ascontiguousarray(tape.closes, dtype=np.float64),
        volumes=np.ascontiguousarray(tape.volumes, dtype=np.float64),
        funding=np.ascontiguousarray(tape.funding_rates, dtype=np.float64),
        funding_mask=np.ascontiguousarray(tape.funding_event_mask, dtype=np.bool_),
        symbols=tape.symbols,
    )
    return PreparedRustIntrabarMarketV1(
        cache=cache,
        market=market,
        tape_signature=tape.signature,
        datetime_index=pd.DatetimeIndex(pd.to_datetime(tape.timestamps_ns, utc=True)),
        bar_timestamp_semantics=tape.bar_timestamp_semantics,
    )


@dataclass(frozen=True, slots=True)
class PreparedRustIntrabarRequestV1:
    """A cached immutable intrabar request ready for one native execution.

    This is intentionally an internal adapter surface.  It lets the shared
    prepared-evaluation runtime reuse the exact intrabar market/request owner
    without recreating the OHLCV tape or silently replaying accounting in
    Python.  Public ``run_rust_intrabar_kernel`` continues to materialize its
    regular result only after the request has executed.
    """

    request: NativePreparedRequest
    prepared_market: PreparedRustIntrabarMarketV1
    prepared_market_signature: str
    source_market_bytes: int
    output_profile: int


def prepare_rust_intrabar_request(
    *,
    tape: PreparedMarketTape,
    intent: IntrabarIntentTape,
    account: AccountConfig,
    contract: ExecutionContract,
    fee_rate: float = 0.0,
    slippage_rate: float = 0.0,
    contract_size: float = 1.0,
    sizing_mode: IntrabarSizingMode | str = IntrabarSizingMode.UNITS,
    fixed_notional: float = 0.0,
    equity_fraction: float = 0.0,
    risk_fraction: float = 0.0,
    qty_step: float = 0.0,
    min_qty: float = 0.0,
    min_notional: float = 0.0,
    tick_size: float = 0.0,
    session_policy: Optional[SessionExecutionPolicy] = None,
    session_tape: Optional[IntrabarSessionTape] = None,
    report_level: str = "standard",
    native_preparation_cache: Optional[NativeExecutionPreparationCache] = None,
    audit_detail_limit: Optional[int] = None,
    prepared_market: Optional[PreparedRustIntrabarMarketV1] = None,
    reuse_request: bool = True,
) -> PreparedRustIntrabarRequestV1:
    """Lower one validated intrabar tape into an immutable cached request.

    ``report_level='score'`` is accepted here for internal scalar evaluation.
    The public result adapter continues to reject score-only output because it
    cannot honestly provide dense ``BacktestResultV2`` paths from it.
    """

    if tape.n_symbols != 1:
        raise NotImplementedError("Rust intrabar authority is certified for one symbol only")
    if len(intent.entry_side) != tape.n_bars:
        raise ValueError("intent length must match market tape")
    _native_module()
    bar_timestamp_semantics, same_bar_policy, take_profit_gap_policy = _contract_codes(contract, tape)
    n = tape.n_bars
    level_mode = intent.level_mode.value if hasattr(intent.level_mode, "value") else str(intent.level_mode)
    sizing = sizing_mode.value if hasattr(sizing_mode, "value") else str(sizing_mode)
    profile = _profile_code(report_level)
    if audit_detail_limit is None:
        # At most three fills plus one ambiguity marker can occur per bar.
        audit_detail_limit = max(1, n * 4 + 4)

    if prepared_market is None:
        prepared_market = prepare_rust_intrabar_market(
            tape=tape,
            native_preparation_cache=native_preparation_cache,
        )
    else:
        if native_preparation_cache is not None and native_preparation_cache is not prepared_market.cache:
            raise ValueError("prepared_market must use the supplied native_preparation_cache")
        if prepared_market.tape_signature != tape.signature:
            raise ValueError("prepared Rust intrabar market does not match tape signature")
        if prepared_market.bar_timestamp_semantics != tape.bar_timestamp_semantics:
            raise ValueError("prepared Rust intrabar market does not match tape timestamp semantics")
    cache = prepared_market.cache
    market = prepared_market.market
    request = cache.intrabar_request(
        market,
        entry_side=np.ascontiguousarray(intent.entry_side, dtype=np.int8),
        entry_size=np.ascontiguousarray(intent.entry_size, dtype=np.float64),
        stop_value=_float_tape(intent.stop_value, n),
        take_profit_value=_float_tape(intent.take_profit_value, n),
        trailing_value=_float_tape(intent.trailing_value, n),
        exit_long=_bool_tape(intent.exit_long if intent.exit_long is not None else intent.technical_exit, n),
        exit_short=_bool_tape(intent.exit_short if intent.exit_short is not None else intent.technical_exit, n),
        level_mode=_LEVEL_CODE[level_mode],
        initial_capital=float(account.initial_capital),
        leverage=float(account.leverage),
        maintenance_ratio=float(account.maintenance_ratio),
        margin_buffer=float(account.margin_buffer),
        contract_size=float(contract_size),
        fee_rate=float(fee_rate),
        slippage_rate=float(slippage_rate),
        sizing_mode=_SIZING_CODE[sizing],
        fixed_notional=float(fixed_notional),
        equity_fraction=float(equity_fraction),
        risk_fraction=float(risk_fraction),
        qty_step=float(qty_step),
        min_qty=float(min_qty),
        min_notional=float(min_notional),
        tick_size=float(tick_size),
        bar_timestamp_semantics=bar_timestamp_semantics,
        same_bar_policy=same_bar_policy,
        take_profit_gap_policy=take_profit_gap_policy,
        close_on_last_bar=bool(contract.close_on_last_bar),
        output_profile=profile,
        audit_detail_limit=int(audit_detail_limit),
        reuse_request=bool(reuse_request),
        **_session_kwargs(session_policy, session_tape),
    )
    return PreparedRustIntrabarRequestV1(
        request=request,
        prepared_market=prepared_market,
        prepared_market_signature=market.signature,
        source_market_bytes=int(market.prepared_bytes),
        output_profile=profile,
    )


def run_rust_intrabar_kernel(
    *,
    tape: PreparedMarketTape,
    intent: IntrabarIntentTape,
    account: AccountConfig,
    contract: ExecutionContract,
    fee_rate: float = 0.0,
    slippage_rate: float = 0.0,
    contract_size: float = 1.0,
    sizing_mode: IntrabarSizingMode | str = IntrabarSizingMode.UNITS,
    fixed_notional: float = 0.0,
    equity_fraction: float = 0.0,
    risk_fraction: float = 0.0,
    qty_step: float = 0.0,
    min_qty: float = 0.0,
    min_notional: float = 0.0,
    tick_size: float = 0.0,
    session_policy: Optional[SessionExecutionPolicy] = None,
    session_tape: Optional[IntrabarSessionTape] = None,
    report_level: str = "standard",
    native_preparation_cache: Optional[NativeExecutionPreparationCache] = None,
    audit_detail_limit: Optional[int] = None,
    prepared_market: Optional[PreparedRustIntrabarMarketV1] = None,
    reuse_request: bool = True,
) -> NativeIntrabarKernelResult:
    """Run the bounded contract in Rust and adapt SoA only after execution."""

    prepared_request = prepare_rust_intrabar_request(
        tape=tape,
        intent=intent,
        account=account,
        contract=contract,
        fee_rate=fee_rate,
        slippage_rate=slippage_rate,
        contract_size=contract_size,
        sizing_mode=sizing_mode,
        fixed_notional=fixed_notional,
        equity_fraction=equity_fraction,
        risk_fraction=risk_fraction,
        qty_step=qty_step,
        min_qty=min_qty,
        min_notional=min_notional,
        tick_size=tick_size,
        session_policy=session_policy,
        session_tape=session_tape,
        report_level=report_level,
        native_preparation_cache=native_preparation_cache,
        audit_detail_limit=audit_detail_limit,
        prepared_market=prepared_market,
        reuse_request=reuse_request,
    )
    profile = prepared_request.output_profile
    if profile == 0:
        raise ValueError(
            "report_level='score' is a direct NativeIntrabarRequestCore primitive and cannot "
            "produce the public BacktestResultV2 surface; use minimal, standard, or audit"
        )
    payload = dict(prepared_request.request.core.execute())

    n = tape.n_bars
    _bar_timestamp_semantics, same_bar_policy, _take_profit_gap_policy = _contract_codes(contract, tape)
    sizing = sizing_mode.value if hasattr(sizing_mode, "value") else str(sizing_mode)

    index = prepared_request.prepared_market.datetime_index
    fills = _materialize_fills(payload, tape.timestamps_ns, index=index) if profile == 2 else ()
    fills_report = _fills_report(fills, payload) if profile == 2 else pd.DataFrame()
    ambiguity_bar = (
        np.asarray(payload["ambiguity_bar"], dtype=np.int64)
        if profile == 2
        else np.empty(0, dtype=np.int64)
    )
    ambiguity_policy = (
        np.asarray(payload["ambiguity_policy"], dtype=np.uint8)
        if profile == 2
        else np.empty(0, dtype=np.uint8)
    )
    session_enabled = bool(payload["session_execution_enabled"])
    metadata = {
        "engine": "intrabar_bracket_rust_v1" if not session_enabled else "intrabar_session_bracket_rust_v1",
        "engine_id": "intrabar_bracket_v1",
        "backend": "rust_intrabar",
        "backend_alias": "rust_intrabar_session" if session_enabled else "rust_intrabar",
        "kernel_version": "bracket_intrabar_rust_v1" if not session_enabled else "session_intrabar_rust_v1",
        "execution_contract": contract.to_metadata(),
        "data_signature": tape.signature,
        "validation_certificate": tape.validation_certificate.__dict__.copy(),
        "report_level": str(report_level).lower().strip(),
        "two_pass_audit": False,
        "fill_count": int(payload["fill_count"]),
        "ambiguity_count": int(payload["ambiguity_count"]),
        "rejected_count": int(payload["rejected_count"]),
        "liquidated": bool(payload["liquidated"]),
        "liquidation_bar": int(payload["liquidation_bar"]),
        "funding_timing_certified": True,
        "funding_event_alignment": "exact_bar_timestamp",
        "bar_timestamp_semantics": tape.bar_timestamp_semantics,
        "funding_event_price_reference": "open" if tape.bar_timestamp_semantics == "open" else "close",
        "sizing_mode": sizing,
        "sizing": {
            "fixed_notional": float(fixed_notional),
            "equity_fraction": float(equity_fraction),
            "risk_fraction": float(risk_fraction),
        },
        "quantity_constraints": {
            "qty_step": float(qty_step),
            "min_qty": float(min_qty),
            "min_notional": float(min_notional),
            "tick_size": float(tick_size),
        },
        "rust_intrabar_authority": True,
        "native_execution_runtime_class": "whole_run_native",
        "native_execution_model_id": str(payload["execution_model_id"]),
        "native_execution_request_fingerprint": str(payload["request_fingerprint"]),
        "native_execution_terminal_fingerprint": str(payload["terminal_fingerprint"]),
        "prepared_market_signature": prepared_request.prepared_market_signature,
        "source_market_bytes": int(prepared_request.source_market_bytes),
        "prepared_market_owner": "reused" if prepared_market is not None else "one_shot",
        "request_cache_policy": "content_addressed" if reuse_request else "ephemeral_validated",
        "boundary_calls": 1,
        "python_callbacks": 0,
        "audit_detail_truncated": bool(payload["audit_detail_truncated"]),
        "audit_detail_retained_rows": int(payload["audit_detail_retained_rows"]),
        "audit_detail_dropped_rows": int(payload["audit_detail_dropped_rows"]),
        "ambiguity_policy_id": int(same_bar_policy),
        "ambiguity_bar": ambiguity_bar,
        "ambiguity_policy": ambiguity_policy,
    }
    if session_enabled:
        metadata.update(
            {
                "session_execution_enabled": True,
                "session_policy": session_policy.to_metadata(),
                "session_tape_signature": session_tape.signature,
                "session_reset_count": int(payload["session_reset_count"]),
                "session_forced_exit_count": int(payload["session_forced_exit_count"]),
                "entry_window_blocked_count": int(payload["entry_window_blocked_count"]),
                "long_quota_blocked_count": int(payload["long_quota_blocked_count"]),
                "short_quota_blocked_count": int(payload["short_quota_blocked_count"]),
                "flat_only_blocked_count": int(payload["flat_only_blocked_count"]),
                "stale_session_signal_count": int(payload["stale_session_signal_count"]),
                "reentry_suppressed_count": int(payload["reentry_suppressed_count"]),
            }
        )
    else:
        metadata["session_execution_enabled"] = False
    return NativeIntrabarKernelResult(
        equity=pd.Series(np.asarray(payload["equity"], dtype=np.float64), index=index, name="equity"),
        position=pd.Series(np.asarray(payload["position"], dtype=np.float64), index=index, name=f"Position_{tape.symbols[0]}"),
        average_entry=pd.Series(np.asarray(payload["average_entry"], dtype=np.float64), index=index, name="average_entry"),
        active_stop=pd.Series(np.asarray(payload["active_stop"], dtype=np.float64), index=index, name="active_stop"),
        active_take_profit=pd.Series(np.asarray(payload["active_take_profit"], dtype=np.float64), index=index, name="active_take_profit"),
        fees=pd.Series(np.asarray(payload["fees"], dtype=np.float64), index=index, name="fees"),
        funding=pd.Series(np.asarray(payload["funding"], dtype=np.float64), index=index, name="funding"),
        event_flags=pd.Series(np.asarray(payload["event_flags"], dtype=np.uint32), index=index, name="event_flags"),
        initial_margin=pd.Series(np.asarray(payload["initial_margin"], dtype=np.float64), index=index, name="initial_margin"),
        maintenance_margin=pd.Series(np.asarray(payload["maintenance_margin"], dtype=np.float64), index=index, name="maintenance_margin"),
        fills=fills,
        fills_report=fills_report,
        ambiguity_count=int(payload["ambiguity_count"]),
        rejected_count=int(payload["rejected_count"]),
        fill_count=int(payload["fill_count"]),
        liquidated=bool(payload["liquidated"]),
        liquidation_bar=int(payload["liquidation_bar"]),
        report_level=str(report_level).lower().strip(),
        metadata=metadata,
    )
