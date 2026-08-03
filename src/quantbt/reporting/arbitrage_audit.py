"""
Arbitrage domain audit helpers.

These functions validate accounting invariants on completed native arbitrage
results.  They are intentionally report-level checks, not execution logic.
"""

from __future__ import annotations

from typing import Dict, Iterable, Optional

import numpy as np
import pandas as pd

from ..core.results import BacktestResultV2


def build_arbitrage_domain_audit(
    result: BacktestResultV2,
    *,
    tolerance: float = 1e-9,
    raise_on_fail: bool = False,
) -> Dict:
    """
    Return a compact audit summary for a native arbitrage result.

    The audit checks that package PnL reconciles to equity deltas, leg PnL sums
    to package PnL, fees reconcile to the result fee series, target-unit symbols
    match result symbols, and final target/position units are flat when the
    strategy exits.
    """
    metadata = result.metadata or {}
    missing = [
        name
        for name in ("package_pnl_report", "leg_pnl_report", "package_target_units")
        if name not in metadata or metadata.get(name) is None
    ]

    package_report = _frame(metadata.get("package_pnl_report"))
    leg_report = _frame(metadata.get("leg_pnl_report"))
    target_units = _frame(metadata.get("package_target_units"))
    rejection_report = _frame(metadata.get("package_rejection_report"))
    order_report = _frame(metadata.get("order_report", metadata.get("orders_report")))

    max_package_residual = _max_abs(package_report.get("pnl_residual")) if not package_report.empty else np.nan
    leg_vs_package_diff = np.nan
    if not leg_report.empty and not package_report.empty and "timestamp" in leg_report and "total_pnl" in leg_report:
        leg_sum = leg_report.groupby(pd.to_datetime(leg_report["timestamp"], utc=True), sort=False)["total_pnl"].sum()
        pkg = _series_from_report(package_report, "package_pnl")
        leg_vs_package_diff = _max_abs((leg_sum.reindex(pkg.index, fill_value=0.0) - pkg).to_numpy(dtype=float))

    fee_residual = np.nan
    if not leg_report.empty and "fee" in leg_report:
        fee_sum = float(pd.to_numeric(leg_report["fee"], errors="coerce").fillna(0.0).sum())
        result_fee = float(result.fees.sum()) if isinstance(result.fees, pd.Series) and not result.fees.empty else 0.0
        fee_residual = abs(fee_sum - result_fee)

    target_symbols = set(map(str, target_units.columns)) if not target_units.empty else set()
    result_symbols = set(map(str, result.symbols))
    target_symbols_match = bool(target_symbols) and target_symbols == result_symbols
    final_target_gross = float(target_units.iloc[-1].abs().sum()) if not target_units.empty else np.nan
    final_position_gross = _final_position_gross(result.positions, result.symbols)

    checks = {
        "has_required_reports": not missing,
        "package_pnl_residual_ok": _ok(max_package_residual, tolerance),
        "leg_pnl_reconciles_to_package": _ok(leg_vs_package_diff, tolerance),
        "fees_reconcile": _ok(fee_residual, tolerance),
        "target_symbols_match": target_symbols_match,
        "final_target_flat": _ok(final_target_gross, tolerance),
        "final_position_flat": _ok(final_position_gross, tolerance),
    }
    passed = all(checks.values())
    status = "pass" if passed else "fail"
    audit = {
        "status": status,
        "passed": passed,
        "tolerance": float(tolerance),
        "engine": metadata.get("engine"),
        "backend": metadata.get("backend"),
        "arb_id": metadata.get("arb_id"),
        "arb_type": metadata.get("arb_type"),
        "missing_reports": missing,
        "checks": checks,
        "max_abs_package_pnl_residual": _float_or_none(max_package_residual),
        "max_abs_leg_vs_package_pnl_diff": _float_or_none(leg_vs_package_diff),
        "max_abs_fee_residual": _float_or_none(fee_residual),
        "final_gross_target_units": _float_or_none(final_target_gross),
        "final_gross_position_units": _float_or_none(final_position_gross),
        "target_symbols": sorted(target_symbols),
        "result_symbols": sorted(result_symbols),
        "order_count": int(len(order_report)),
        "fill_count": int(len(getattr(result, "fills", ()) or ())),
        "rejection_count": int(len(rejection_report)),
    }
    if raise_on_fail and not passed:
        raise AssertionError(f"arbitrage domain audit failed: {audit}")
    return audit


def compare_native_arbitrage_results(
    event_result: BacktestResultV2,
    vectorized_result: BacktestResultV2,
    *,
    tolerance: float = 1e-9,
    raise_on_fail: bool = False,
) -> Dict:
    """
    Compare native event and native vectorized arbitrage outputs.

    This is a high-signal parity check for mock/golden tests.  It does not
    require identical order reports, only accounting-equivalent equity,
    positions, target units, and package residuals.
    """
    equity_diff = _max_abs((event_result.equity - vectorized_result.equity.reindex(event_result.equity.index)).to_numpy(dtype=float))
    position_diff = _max_abs((_position_units(event_result) - _position_units(vectorized_result).reindex(event_result.equity.index)).to_numpy(dtype=float))

    event_target = _frame(event_result.metadata.get("package_target_units"))
    vector_target = _frame(vectorized_result.metadata.get("package_target_units"))
    target_diff = np.nan
    if not event_target.empty and not vector_target.empty:
        target_diff = _max_abs((event_target - vector_target.reindex(event_target.index)).to_numpy(dtype=float))

    event_package = _series_from_report(_frame(event_result.metadata.get("package_pnl_report")), "pnl_residual")
    vector_package = _series_from_report(_frame(vectorized_result.metadata.get("package_pnl_report")), "pnl_residual")
    residual_diff = np.nan
    if not event_package.empty and not vector_package.empty:
        residual_diff = max(_max_abs(event_package.to_numpy(dtype=float)), _max_abs(vector_package.to_numpy(dtype=float)))

    checks = {
        "equity_matches": _ok(equity_diff, tolerance),
        "positions_match": _ok(position_diff, tolerance),
        "target_units_match": _ok(target_diff, tolerance),
        "package_residuals_ok": _ok(residual_diff, tolerance),
    }
    passed = all(checks.values())
    report = {
        "status": "pass" if passed else "fail",
        "passed": passed,
        "tolerance": float(tolerance),
        "event_engine": event_result.metadata.get("engine"),
        "vectorized_engine": vectorized_result.metadata.get("engine"),
        "checks": checks,
        "max_abs_equity_diff": _float_or_none(equity_diff),
        "max_abs_position_diff": _float_or_none(position_diff),
        "max_abs_target_unit_diff": _float_or_none(target_diff),
        "max_abs_package_residual": _float_or_none(residual_diff),
    }
    if raise_on_fail and not passed:
        raise AssertionError(f"native arbitrage parity failed: {report}")
    return report


def _frame(value) -> pd.DataFrame:
    return value if isinstance(value, pd.DataFrame) else pd.DataFrame()


def _series_from_report(report: pd.DataFrame, column: str) -> pd.Series:
    if report.empty or column not in report:
        return pd.Series(dtype=float)
    series = pd.to_numeric(report[column], errors="coerce").fillna(0.0)
    if isinstance(report.index, pd.DatetimeIndex):
        series.index = pd.to_datetime(report.index, utc=True)
    return series.astype(float)


def _position_units(result: BacktestResultV2) -> pd.DataFrame:
    out = result.positions.copy()
    rename = {col: str(col).replace("Position_", "", 1) for col in out.columns}
    out = out.rename(columns=rename)
    return out.reindex(columns=list(result.symbols)).fillna(0.0)


def _final_position_gross(positions: pd.DataFrame, symbols: Iterable[str]) -> float:
    if positions.empty:
        return 0.0
    frame = positions.rename(columns={col: str(col).replace("Position_", "", 1) for col in positions.columns})
    cols = [symbol for symbol in symbols if symbol in frame.columns]
    if not cols:
        return float(positions.iloc[-1].abs().sum())
    return float(frame[cols].iloc[-1].abs().sum())


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
