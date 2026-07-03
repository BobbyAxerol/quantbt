"""
Convert NautilusTrader reports into quantbt result contracts.
"""

from __future__ import annotations

from typing import Dict, List, Optional

import pandas as pd

from ...core.results import BacktestResultV2


def result_from_nautilus_reports(
    account_report: pd.DataFrame,
    symbols: List[str],
    initial_capital: float,
    leverage: float = 1.0,
    orders_report: Optional[pd.DataFrame] = None,
    fills_report: Optional[pd.DataFrame] = None,
    positions_report: Optional[pd.DataFrame] = None,
    metadata: Optional[Dict] = None,
) -> BacktestResultV2:
    if account_report is None or account_report.empty:
        raise ValueError("account_report is required")

    account = account_report.copy()
    account.index = pd.to_datetime(account.index, utc=True)
    total_col = _pick_total_column(account)
    equity = _coerce_money_series(account[total_col], initial_capital)
    equity.name = "equity"
    returns = equity.pct_change().fillna(0.0)

    positions = _positions_from_fills(fills_report if fills_report is not None else orders_report, symbols, equity.index)
    closes = pd.DataFrame(index=equity.index)
    for sym in symbols:
        closes[f"Close_{sym}"] = 0.0

    return BacktestResultV2(
        equity=equity,
        returns=returns,
        positions=positions,
        closes=closes,
        symbols=symbols,
        initial_capital=initial_capital,
        leverage=leverage,
        metadata={
            "backend": "nautilus",
            "orders_report": orders_report,
            "fills_report": fills_report,
            "positions_report": positions_report,
            "orders_count": 0 if orders_report is None else int(len(orders_report)),
            "fills_count": 0 if fills_report is None else int(len(fills_report)),
            "positions_count": 0 if positions_report is None else int(len(positions_report)),
            **(metadata or {}),
        },
    )


def _pick_total_column(account_report: pd.DataFrame) -> str:
    for col in ("total", "total_balance", "balance_total"):
        if col in account_report.columns:
            return col
    numeric_cols = list(account_report.select_dtypes(include="number").columns)
    if numeric_cols:
        return numeric_cols[0]
    raise ValueError("could not find numeric account total column")


def _coerce_money_series(values: pd.Series, initial_capital: float) -> pd.Series:
    equity = pd.to_numeric(values, errors="coerce")
    if equity.isna().any():
        extracted = values.astype(str).str.extract(r"([-+]?\d*\.?\d+(?:[eE][-+]?\d+)?)", expand=False)
        equity = equity.fillna(pd.to_numeric(extracted, errors="coerce"))
    equity = equity.ffill().fillna(initial_capital)
    equity.name = "equity"
    return equity


def _positions_from_fills(report: Optional[pd.DataFrame], symbols: List[str], idx: pd.DatetimeIndex) -> pd.DataFrame:
    positions = pd.DataFrame(index=idx)
    for sym in symbols:
        positions[f"Position_{sym}"] = 0.0

    if report is None or report.empty:
        return positions
    required = {"instrument_id", "side", "filled_qty"}
    if not required <= set(report.columns):
        return positions

    fills = report.copy()
    ts_col = "ts_last" if "ts_last" in fills.columns else "ts_init"
    if ts_col not in fills.columns:
        return positions
    fills["_timestamp"] = _coerce_timestamp(fills[ts_col])
    fills = fills.dropna(subset=["_timestamp"]).sort_values("_timestamp")

    for sym in symbols:
        sub = fills[fills["instrument_id"].astype(str) == sym]
        if sub.empty:
            continue
        signed = []
        for _, row in sub.iterrows():
            qty = _coerce_float(row.get("filled_qty", 0.0))
            side = str(row.get("side", "")).upper()
            sign = 1.0 if side == "BUY" else -1.0 if side == "SELL" else 0.0
            signed.append(sign * qty)
        step = pd.Series(signed, index=pd.DatetimeIndex(sub["_timestamp"]), dtype=float).groupby(level=0).sum().cumsum()
        positions[f"Position_{sym}"] = step.reindex(idx, method="ffill").fillna(0.0)
    return positions


def _coerce_timestamp(values: pd.Series) -> pd.Series:
    if pd.api.types.is_datetime64_any_dtype(values):
        return pd.to_datetime(values, utc=True)
    numeric = pd.to_numeric(values, errors="coerce")
    if numeric.notna().any():
        return pd.to_datetime(numeric, utc=True, unit="ns", errors="coerce")
    return pd.to_datetime(values, utc=True, errors="coerce")


def _coerce_float(value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        extracted = pd.Series([str(value)]).str.extract(r"([-+]?\d*\.?\d+(?:[eE][-+]?\d+)?)", expand=False)
        parsed = pd.to_numeric(extracted, errors="coerce").iloc[0]
        return 0.0 if pd.isna(parsed) else float(parsed)
