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

    positions = pd.DataFrame(index=equity.index)
    closes = pd.DataFrame(index=equity.index)
    for sym in symbols:
        positions[f"Position_{sym}"] = 0.0
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
