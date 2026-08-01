"""
Portfolio domain audit helpers.

These functions validate accounting and exposure invariants on completed
multi-symbol portfolio results.  They are report-level checks only; they do not
change execution semantics.
"""

from __future__ import annotations

from typing import Dict, Optional

import numpy as np
import pandas as pd


def build_portfolio_domain_audit(
    result,
    *,
    tolerance: float = 1e-9,
    raise_on_fail: bool = False,
) -> Dict:
    """
    Return a compact audit summary for a multi-symbol portfolio result.

    The audit checks that accepted-position attribution reconciles to the equity
    curve, fees reconcile to the per-bar fee series, accepted notionals match
    units times closes times contract size, and exposure-report identities hold.
    Rebalance rows are informational: a non-empty report means the requested
    target matrix differed from accepted positions, usually because a
    portfolio/margin gate rejected a rebalance.
    """
    metadata = getattr(result, "metadata", {}) or {}
    missing = [
        name
        for name in (
            "target_units_report",
            "accepted_units_report",
            "accepted_notional_report",
            "exposure_report",
            "symbol_pnl_report",
        )
        if not isinstance(metadata.get(name), pd.DataFrame)
    ]

    accepted_units = _frame(metadata.get("accepted_units_report"))
    accepted_notional = _frame(metadata.get("accepted_notional_report"))
    exposure_report = _frame(metadata.get("exposure_report"))
    symbol_pnl_report = _frame(metadata.get("symbol_pnl_report"))
    rebalance_report = _frame(metadata.get("rebalance_report"))
    fee_series = _series(metadata.get("fee_series"))

    equity_residual = np.nan
    if not symbol_pnl_report.empty:
        pnl_sum = (
            symbol_pnl_report.assign(
                timestamp=pd.to_datetime(symbol_pnl_report["timestamp"], utc=True),
                total_pnl=pd.to_numeric(symbol_pnl_report["total_pnl"], errors="coerce").fillna(0.0),
            )
            .groupby("timestamp", sort=False)["total_pnl"]
            .sum()
        )
        equity_delta = result.equity.diff().fillna(0.0)
        if getattr(result, "liquidated", False):
            liq_idx = int(getattr(result, "liquidation_bar", -1))
            if liq_idx >= 0:
                equity_delta = equity_delta.iloc[:liq_idx]
                pnl_sum = pnl_sum.reindex(equity_delta.index, fill_value=0.0)
        else:
            pnl_sum = pnl_sum.reindex(equity_delta.index, fill_value=0.0)
        equity_residual = _max_abs((pnl_sum - equity_delta).to_numpy(dtype=float))

    fee_residual = np.nan
    if not symbol_pnl_report.empty and "fee" in symbol_pnl_report:
        pnl_fee = float(pd.to_numeric(symbol_pnl_report["fee"], errors="coerce").fillna(0.0).sum())
        metadata_fee = float(metadata.get("fee_total", fee_series.sum() if not fee_series.empty else 0.0))
        fee_residual = abs(pnl_fee - metadata_fee)

    notional_residual = _accepted_notional_residual(result, accepted_units, accepted_notional)
    exposure_residual = _exposure_identity_residual(exposure_report)

    rebalance_abs_notional = 0.0
    if not rebalance_report.empty and "notional_diff" in rebalance_report:
        rebalance_abs_notional = float(
            pd.to_numeric(rebalance_report["notional_diff"], errors="coerce").fillna(0.0).abs().sum()
        )

    checks = {
        "has_required_reports": not missing,
        "pnl_reconciles_to_equity": _ok(equity_residual, tolerance),
        "fees_reconcile": _ok(fee_residual, tolerance),
        "accepted_notional_reconciles": _ok(notional_residual, tolerance),
        "exposure_identities_reconcile": _ok(exposure_residual, tolerance),
    }
    passed = all(checks.values())
    audit = {
        "status": "pass" if passed else "fail",
        "passed": passed,
        "tolerance": float(tolerance),
        "engine": metadata.get("engine"),
        "backend": metadata.get("backend"),
        "mode": metadata.get("mode"),
        "asset_type": metadata.get("asset_type"),
        "hedge_type": metadata.get("hedge_type"),
        "missing_reports": missing,
        "checks": checks,
        "max_abs_pnl_equity_residual": _float_or_none(equity_residual),
        "max_abs_fee_residual": _float_or_none(fee_residual),
        "max_abs_accepted_notional_residual": _float_or_none(notional_residual),
        "max_abs_exposure_identity_residual": _float_or_none(exposure_residual),
        "rebalance_count": int(len(rebalance_report)),
        "rebalance_abs_notional": float(rebalance_abs_notional),
        "liquidated": bool(getattr(result, "liquidated", False)),
        "liquidation_bar": int(getattr(result, "liquidation_bar", -1)),
        "symbols": list(map(str, getattr(result, "symbols", ()))),
    }
    if raise_on_fail and not passed:
        raise AssertionError(f"portfolio domain audit failed: {audit}")
    return audit


def _accepted_notional_residual(result, accepted_units: pd.DataFrame, accepted_notional: pd.DataFrame) -> float:
    if accepted_units.empty or accepted_notional.empty:
        return np.nan
    closes = getattr(result, "closes", pd.DataFrame()).copy()
    if closes.empty:
        return np.nan
    closes = closes.rename(columns={col: str(col).replace("Close_", "", 1) for col in closes.columns})
    closes = closes.reindex(columns=accepted_units.columns)
    contract_sizes = _contract_sizes_from_metadata(result, accepted_units.columns)
    expected = accepted_units.mul(closes, axis=0).mul(contract_sizes, axis=1)
    expected = expected.reindex_like(accepted_notional)
    return _max_abs((expected - accepted_notional).to_numpy(dtype=float))


def _contract_sizes_from_metadata(result, columns) -> pd.Series:
    metadata = getattr(result, "metadata", {}) or {}
    target = _frame(metadata.get("accepted_notional_report"))
    units = _frame(metadata.get("accepted_units_report"))
    closes = getattr(result, "closes", pd.DataFrame()).copy()
    closes = closes.rename(columns={col: str(col).replace("Close_", "", 1) for col in closes.columns})
    values = {}
    for symbol in columns:
        values[symbol] = 1.0
        if target.empty or units.empty or closes.empty or symbol not in target or symbol not in units or symbol not in closes:
            continue
        denom = units[symbol] * closes[symbol]
        mask = denom.abs() > 1e-12
        if mask.any():
            inferred = (target.loc[mask, symbol] / denom.loc[mask]).replace([np.inf, -np.inf], np.nan).dropna()
            if not inferred.empty:
                values[symbol] = float(inferred.iloc[0])
    return pd.Series(values)


def _exposure_identity_residual(exposure_report: pd.DataFrame) -> float:
    if exposure_report.empty:
        return np.nan
    required = {"long_notional", "short_notional", "gross_notional", "net_notional"}
    if not required.issubset(exposure_report.columns):
        return np.nan
    long_notional = pd.to_numeric(exposure_report["long_notional"], errors="coerce").fillna(0.0)
    short_notional = pd.to_numeric(exposure_report["short_notional"], errors="coerce").fillna(0.0)
    gross_notional = pd.to_numeric(exposure_report["gross_notional"], errors="coerce").fillna(0.0)
    net_notional = pd.to_numeric(exposure_report["net_notional"], errors="coerce").fillna(0.0)
    gross_residual = _max_abs((long_notional + short_notional - gross_notional).to_numpy(dtype=float))
    net_residual = _max_abs((long_notional - short_notional - net_notional).to_numpy(dtype=float))
    return max(gross_residual, net_residual)


def _frame(value) -> pd.DataFrame:
    return value if isinstance(value, pd.DataFrame) else pd.DataFrame()


def _series(value) -> pd.Series:
    return value if isinstance(value, pd.Series) else pd.Series(dtype=float)


def _max_abs(value) -> float:
    if value is None:
        return np.nan
    arr = np.asarray(value, dtype=np.float64)
    arr = arr[np.isfinite(arr)]
    if arr.size == 0:
        return np.nan
    return float(np.max(np.abs(arr)))


def _ok(value: Optional[float], tolerance: float) -> bool:
    if value is None:
        return False
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return False
    return bool(np.isfinite(numeric) and numeric <= float(tolerance))


def _float_or_none(value):
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if not np.isfinite(numeric):
        return None
    return numeric
