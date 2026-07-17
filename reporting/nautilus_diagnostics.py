"""Nautilus validation diagnostics."""

from __future__ import annotations

from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from ..adapters.nautilus.instruments import SUPPORTED_BINANCE_PERP_SPECS, normalize_binance_perp_symbol
from ..core.results import BacktestResultV2


def build_nautilus_pct_equity_diagnostic(
    result: BacktestResultV2,
    *,
    data: pd.DataFrame,
    signal: pd.Series,
    native_fee_round_trip: Optional[float] = None,
    native_fee_one_way: Optional[float] = None,
    native_use_funding: Optional[bool] = None,
    native_slippage: Optional[float] = None,
) -> Dict:
    """
    Compare a Nautilus `%_equity` validation run against native expectations.

    The helper is intentionally diagnostic-only: it does not claim that
    Nautilus and native legacy should match. It highlights the most common
    sources of divergence: fee convention/application, funding, slippage,
    signal transitions, and Binance lot-size constraints.
    """
    if not isinstance(result, BacktestResultV2):
        raise TypeError("build_nautilus_pct_equity_diagnostic requires BacktestResultV2")
    if "close" not in data:
        raise ValueError("data must contain a close column")

    metadata = result.metadata or {}
    idx = _utc_index(data.index)
    sig = _align_signal(signal, idx)
    use_pyramiding = bool(metadata.get("use_pyramiding", _nested(metadata, "run_config", "sizing", "use_pyramiding", default=True)))
    effective_signal = sig.astype(float) if use_pyramiding else np.sign(sig.astype(float))
    transitions = effective_signal.ne(effective_signal.shift(1).fillna(0.0))
    transition_report = pd.DataFrame(
        {
            "timestamp": idx[transitions.to_numpy()],
            "raw_signal": sig.loc[transitions].to_numpy(dtype=float),
            "effective_signal": effective_signal.loc[transitions].to_numpy(dtype=float),
            "close": data.reindex(idx)["close"].loc[transitions].to_numpy(dtype=float),
        }
    )

    orders_count = int(metadata.get("orders_count", len(_frame(metadata.get("orders_report", metadata.get("order_report"))))))
    fills_count = int(metadata.get("fills_count", len(_frame(metadata.get("fills_report")))))
    sizing_mode = str(metadata.get("sizing_mode", _nested(metadata, "run_config", "sizing", "hedge_type", default=""))).lower()
    requested_fee = _safe_float(metadata.get("fee_rate"))
    requested_slippage = _safe_float(metadata.get("slippage"))
    expected_fee = native_fee_one_way
    if expected_fee is None and native_fee_round_trip is not None:
        expected_fee = float(native_fee_round_trip) / 2.0

    constraints = _instrument_constraints(metadata)
    lot_report = _lot_size_risk_report(
        transition_report=transition_report,
        initial_capital=float(result.initial_capital),
        alloc_per_trade=float(metadata.get("trade_notional", metadata.get("alloc_per_trade", 0.0)) or 0.0),
        constraints=constraints,
    )

    checks = {
        "sizing_mode_is_pct_equity": sizing_mode in {"%_equity", "pct_equity"},
        "orders_not_more_than_signal_transitions": orders_count <= int(len(transition_report)),
        "fills_not_more_than_orders": fills_count <= orders_count,
        "fee_convention_matches_native": True if expected_fee is None or requested_fee is None else abs(float(expected_fee) - float(requested_fee)) <= 1e-15,
        "custom_fee_rate_applied_to_nautilus": False,
        "funding_matches_native": True if native_use_funding is None else bool(native_use_funding) is False,
        "slippage_matches_native": True if native_slippage is None else abs(float(native_slippage)) <= 1e-15,
        "custom_slippage_applied_to_nautilus": False,
        "has_lot_size_constraints": constraints.get("qty_step") is not None,
    }
    recommendations = _recommendations(checks, native_use_funding=native_use_funding, native_slippage=native_slippage)
    status = "ok" if all(checks.values()) else "diff"
    return {
        "status": status,
        "checks": checks,
        "signal": {
            "rows": int(len(idx)),
            "raw_transition_count": int(sig.ne(sig.shift(1).fillna(0.0)).sum()),
            "effective_transition_count": int(len(transition_report)),
            "use_pyramiding": use_pyramiding,
            "signal_index_matches_data_index": bool(_utc_index(signal.index).equals(idx)),
            "transition_report": transition_report,
        },
        "orders": {
            "orders_count": orders_count,
            "fills_count": fills_count,
            "positions_count": int(metadata.get("positions_count", 0) or 0),
            "missing_order_events_vs_transitions": max(0, int(len(transition_report)) - orders_count),
        },
        "execution_semantics": {
            "requested_fee_rate": requested_fee,
            "expected_native_one_way_fee_rate": expected_fee,
            "custom_fee_rate_applied_to_nautilus": False,
            "requested_slippage": requested_slippage,
            "native_slippage": native_slippage,
            "custom_slippage_applied_to_nautilus": False,
            "native_use_funding": native_use_funding,
            "nautilus_signal_funding_supported": False,
            "adapter_fill_model": "NautilusTrader bar market execution with instrument maker/taker fee model",
        },
        "instrument_constraints": constraints,
        "lot_size_risk": lot_report,
        "recommendations": recommendations,
    }


def _instrument_constraints(metadata: Dict) -> Dict:
    instrument_id = metadata.get("instrument_id") or _nested(metadata, "run_config", "nautilus", "instrument_id")
    out = {
        "instrument_id": instrument_id,
        "qty_step": metadata.get("qty_step") or metadata.get("lot_size") or metadata.get("size_increment"),
        "lot_size": metadata.get("lot_size") or metadata.get("qty_step") or metadata.get("size_increment"),
        "min_qty": metadata.get("min_qty") or metadata.get("min_quantity"),
        "min_notional": metadata.get("min_notional"),
        "contract_size_note": "contract_size is a multiplier; lot_size/qty_step controls fractional crypto order acceptance",
    }
    if instrument_id:
        try:
            spec = SUPPORTED_BINANCE_PERP_SPECS[normalize_binance_perp_symbol(str(instrument_id))]
            out.update(
                {
                    "qty_step": out["qty_step"] or spec.size_increment,
                    "lot_size": out["lot_size"] or spec.size_increment,
                    "min_qty": out["min_qty"] or spec.min_quantity,
                    "min_notional": out["min_notional"] or "10.0",
                    "price_increment": spec.price_increment,
                    "quantity_precision": spec.size_precision,
                }
            )
        except ValueError:
            pass
    return out


def _lot_size_risk_report(
    *,
    transition_report: pd.DataFrame,
    initial_capital: float,
    alloc_per_trade: float,
    constraints: Dict,
) -> Dict:
    qty_step = _safe_float(constraints.get("qty_step"))
    min_qty = _safe_float(constraints.get("min_qty"))
    if transition_report.empty or qty_step is None:
        return {"status": "unknown", "potential_small_delta_count": 0}
    alloc = alloc_per_trade / 100.0 if alloc_per_trade > 1.0 else alloc_per_trade
    close = pd.to_numeric(transition_report["close"], errors="coerce").replace(0.0, np.nan)
    signal = pd.to_numeric(transition_report["effective_signal"], errors="coerce").abs()
    approx_qty = (initial_capital * alloc * signal / close).fillna(0.0)
    threshold = max(qty_step, min_qty or 0.0)
    small = approx_qty < threshold
    return {
        "status": "ok" if not bool(small.any()) else "risk",
        "potential_small_delta_count": int(small.sum()),
        "qty_step": float(qty_step),
        "min_qty": None if min_qty is None else float(min_qty),
        "min_transition_approx_qty": float(approx_qty.min()) if len(approx_qty) else 0.0,
        "note": "Approximation uses initial capital only; live equity and current position can create smaller deltas later.",
    }


def _recommendations(checks: Dict[str, bool], *, native_use_funding, native_slippage) -> List[str]:
    out: List[str] = []
    if not checks["fee_convention_matches_native"]:
        out.append("Align fee convention: legacy `fee` is round-trip; Nautilus `fee_rate` is metadata one-way today.")
    if not checks["custom_fee_rate_applied_to_nautilus"]:
        out.append("Current Nautilus signal adapter uses Nautilus instrument maker/taker fees, not endpoint custom fee_rate.")
    if native_use_funding:
        out.append("Disable native funding for apples-to-apples, or implement Nautilus funding/carry adapter.")
    if native_slippage and abs(float(native_slippage)) > 0.0:
        out.append("Disable native slippage for apples-to-apples, or implement Nautilus slippage model.")
    if not checks["orders_not_more_than_signal_transitions"]:
        out.append("Inspect signal timestamp alignment and Nautilus order reports; order count exceeds transition count.")
    return out


def _align_signal(signal: pd.Series, idx: pd.DatetimeIndex) -> pd.Series:
    sig = signal.copy()
    if not isinstance(sig.index, pd.DatetimeIndex):
        sig.index = pd.to_datetime(sig.index, utc=True)
    if sig.index.tz is None:
        sig.index = sig.index.tz_localize("UTC")
    else:
        sig.index = sig.index.tz_convert("UTC")
    return sig.reindex(idx, method="ffill").fillna(0.0)


def _utc_index(index) -> pd.DatetimeIndex:
    idx = pd.DatetimeIndex(pd.to_datetime(index, utc=True))
    if idx.tz is None:
        idx = idx.tz_localize("UTC")
    else:
        idx = idx.tz_convert("UTC")
    return idx


def _nested(mapping: Dict, *keys, default=None):
    cur = mapping
    for key in keys:
        if not isinstance(cur, dict) or key not in cur:
            return default
        cur = cur[key]
    return cur


def _frame(value) -> pd.DataFrame:
    return value if isinstance(value, pd.DataFrame) else pd.DataFrame()


def _safe_float(value):
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None
