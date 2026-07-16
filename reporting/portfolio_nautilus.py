"""Portfolio native-vs-Nautilus validation helpers."""

from __future__ import annotations

from typing import Any, Dict, List

import numpy as np
import pandas as pd

from ..core.results import BacktestResultV2


def build_portfolio_nautilus_position_report(
    native_result: BacktestResultV2,
    nautilus_result: BacktestResultV2,
) -> pd.DataFrame:
    """Return timestamp/symbol position differences between native and Nautilus."""
    native_pos = _position_frame(native_result)
    nautilus_pos = _position_frame(nautilus_result)
    symbols = sorted(set(native_pos.columns) | set(nautilus_pos.columns))
    idx = native_result.equity.index.union(nautilus_result.equity.index).sort_values()
    native_pos = native_pos.reindex(idx).ffill().fillna(0.0).reindex(columns=symbols, fill_value=0.0)
    nautilus_pos = nautilus_pos.reindex(idx).ffill().fillna(0.0).reindex(columns=symbols, fill_value=0.0)

    rows: List[Dict[str, Any]] = []
    for timestamp in idx:
        for symbol in symbols:
            native_value = float(native_pos.loc[timestamp, symbol])
            nautilus_value = float(nautilus_pos.loc[timestamp, symbol])
            rows.append(
                {
                    "timestamp": timestamp,
                    "symbol": symbol,
                    "native_position": native_value,
                    "nautilus_position": nautilus_value,
                    "position_diff": native_value - nautilus_value,
                }
            )
    return pd.DataFrame(rows)


def build_portfolio_nautilus_validation_report(
    native_result: BacktestResultV2,
    nautilus_result: BacktestResultV2,
    *,
    target_tolerance: float = 1e-9,
    position_tolerance: float = 1e-6,
    equity_tolerance: float = 1e-6,
) -> Dict[str, Any]:
    """
    Summarize portfolio package validation between native and Nautilus results.

    This is an institutional audit summary, not a claim that Nautilus is the
    optimizer path. It checks that the submitted Nautilus package matches the
    native target-unit matrix and, when reports are available, compares
    positions and equity.
    """
    native_target = _frame((native_result.metadata or {}).get("target_units_report"))
    nautilus_target = _frame((nautilus_result.metadata or {}).get("portfolio_target_units"))
    package_order_map = _frame((nautilus_result.metadata or {}).get("package_order_map"))
    orders_report = _frame((nautilus_result.metadata or {}).get("orders_report", (nautilus_result.metadata or {}).get("order_report")))
    fills_report = _frame((nautilus_result.metadata or {}).get("fills_report"))

    expected_orders = _expected_order_count(native_target)
    nautilus_orders = int((nautilus_result.metadata or {}).get("orders_count", len(orders_report)))
    if nautilus_orders == 0:
        nautilus_orders = int((nautilus_result.metadata or {}).get("order_count_input", len(package_order_map)))
    nautilus_fills = int((nautilus_result.metadata or {}).get("fills_count", len(fills_report)))
    if nautilus_fills == 0 and nautilus_orders > 0 and len(fills_report) == 0:
        nautilus_fills = int((nautilus_result.metadata or {}).get("order_count_input", 0))

    target_diff = _target_units_diff(native_target, nautilus_target)
    position_report = build_portfolio_nautilus_position_report(native_result, nautilus_result)
    max_position_diff = _max_abs(position_report, "position_diff")
    final_equity_diff = float(native_result.equity.iloc[-1] - nautilus_result.equity.iloc[-1])

    checks = {
        "input_mode_is_portfolio_matrix": (nautilus_result.metadata or {}).get("input_mode") == "portfolio_matrix",
        "target_units_match": target_diff <= float(target_tolerance),
        "order_count_matches_target_transitions": nautilus_orders == expected_orders,
        "fills_do_not_exceed_orders": nautilus_fills <= nautilus_orders,
        "positions_within_tolerance": max_position_diff <= float(position_tolerance),
        "final_equity_within_tolerance": abs(final_equity_diff) <= float(equity_tolerance),
    }
    passed = all(bool(value) for value in checks.values())
    return {
        "status": "pass" if passed else "diff",
        "passed": bool(passed),
        "checks": checks,
        "expected_order_count": int(expected_orders),
        "nautilus_orders": int(nautilus_orders),
        "nautilus_fills": int(nautilus_fills),
        "max_abs_target_units_diff": float(target_diff),
        "max_abs_position_diff": float(max_position_diff),
        "final_equity_diff": float(final_equity_diff),
        "target_tolerance": float(target_tolerance),
        "position_tolerance": float(position_tolerance),
        "equity_tolerance": float(equity_tolerance),
        "native_backend": (native_result.metadata or {}).get("backend"),
        "nautilus_backend": (nautilus_result.metadata or {}).get("backend"),
        "engine": (nautilus_result.metadata or {}).get("engine"),
    }


def _expected_order_count(target_units: pd.DataFrame) -> int:
    if target_units.empty:
        return 0
    prev = target_units.shift(1).fillna(0.0)
    delta = (target_units - prev).abs()
    return int((delta > 1e-12).sum().sum())


def _target_units_diff(native_target: pd.DataFrame, nautilus_target: pd.DataFrame) -> float:
    if native_target.empty or nautilus_target.empty:
        return np.inf
    common_cols = sorted(set(native_target.columns) & set(nautilus_target.columns))
    if not common_cols:
        return np.inf
    idx = native_target.index.union(nautilus_target.index).sort_values()
    left = native_target.reindex(idx).ffill().fillna(0.0).reindex(columns=common_cols)
    right = nautilus_target.reindex(idx).ffill().fillna(0.0).reindex(columns=common_cols)
    arr = (left - right).to_numpy(dtype=float)
    return float(np.nanmax(np.abs(arr))) if arr.size else 0.0


def _position_frame(result: BacktestResultV2) -> pd.DataFrame:
    frame = result.positions.copy()
    frame = frame.rename(columns={col: str(col).replace("Position_", "", 1) for col in frame.columns})
    return frame


def _frame(value) -> pd.DataFrame:
    return value if isinstance(value, pd.DataFrame) else pd.DataFrame()


def _max_abs(frame: pd.DataFrame, column: str) -> float:
    if frame.empty or column not in frame:
        return np.inf
    values = pd.to_numeric(frame[column], errors="coerce").replace([np.inf, -np.inf], np.nan).dropna().abs()
    return float(values.max()) if not values.empty else 0.0
