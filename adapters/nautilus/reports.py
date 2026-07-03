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
    closes: Optional[Dict[str, pd.Series]] = None,
    metadata: Optional[Dict] = None,
) -> BacktestResultV2:
    if account_report is None or account_report.empty:
        raise ValueError("account_report is required")

    account = account_report.copy()
    account.index = pd.to_datetime(account.index, utc=True)
    total_col = _pick_total_column(account)
    account_equity = _coerce_money_series(account[total_col], initial_capital)
    account_equity.name = "account_equity"

    if closes is not None:
        close_df = _close_frame(closes=closes, symbols=symbols)
        idx = close_df.index
        positions = _positions_from_fills(fills_report if fills_report is not None else orders_report, symbols, idx)
        equity = _reconstruct_equity_from_fills(
            fills_report=fills_report if fills_report is not None else orders_report,
            closes=close_df,
            symbols=symbols,
            initial_capital=initial_capital,
        )
    else:
        equity = account_equity.copy()
        equity.name = "equity"
        idx = equity.index
        positions = _positions_from_fills(fills_report if fills_report is not None else orders_report, symbols, idx)
        close_df = pd.DataFrame(index=idx)
        for sym in symbols:
            close_df[f"Close_{sym}"] = 0.0

    returns = equity.pct_change().fillna(0.0)

    account_final = float(account_equity.iloc[-1])
    reconstructed_final = float(equity.iloc[-1])

    return BacktestResultV2(
        equity=equity,
        returns=returns,
        positions=positions,
        closes=close_df,
        symbols=symbols,
        initial_capital=initial_capital,
        leverage=leverage,
        metadata={
            "backend": "nautilus",
            "account_report": account_report,
            "account_equity": account_equity,
            "equity_source": "fills_reconstructed" if closes is not None else "account_report",
            "account_final_equity": account_final,
            "reconstructed_final_equity": reconstructed_final,
            "account_reconstructed_diff": reconstructed_final - account_final,
            "orders_report": orders_report,
            "fills_report": fills_report,
            "positions_report": positions_report,
            "orders_count": 0 if orders_report is None else int(len(orders_report)),
            "fills_count": 0 if fills_report is None else int(len(fills_report)),
            "positions_count": 0 if positions_report is None else int(len(positions_report)),
            **(metadata or {}),
        },
    )


def _close_frame(closes: Dict[str, pd.Series], symbols: List[str]) -> pd.DataFrame:
    if not symbols:
        raise ValueError("symbols are required")
    idx = pd.DatetimeIndex(pd.to_datetime(closes[symbols[0]].index, utc=True))
    frame = pd.DataFrame(index=idx)
    for sym in symbols:
        close = closes[sym].copy()
        close.index = pd.DatetimeIndex(pd.to_datetime(close.index, utc=True))
        frame[f"Close_{sym}"] = pd.to_numeric(close.reindex(idx, method="ffill"), errors="coerce").ffill()
    return frame


def _reconstruct_equity_from_fills(
    fills_report: Optional[pd.DataFrame],
    closes: pd.DataFrame,
    symbols: List[str],
    initial_capital: float,
) -> pd.Series:
    equity = pd.Series(initial_capital, index=closes.index, dtype=float, name="equity")
    if len(closes) == 0:
        return equity

    pos = {sym: 0.0 for sym in symbols}
    fills_by_ts = _fills_by_timestamp(fills_report)
    value = float(initial_capital)

    for i, ts in enumerate(closes.index):
        if i > 0:
            prev = closes.index[i - 1]
            for sym in symbols:
                qty = pos[sym]
                if qty != 0.0:
                    value += qty * (
                        float(closes.loc[ts, f"Close_{sym}"]) - float(closes.loc[prev, f"Close_{sym}"])
                    )

        if ts in fills_by_ts:
            for _, fill in fills_by_ts[ts].iterrows():
                sym = str(fill.get("instrument_id", ""))
                if sym not in pos:
                    continue
                signed_qty = _signed_fill_qty(fill)
                fill_price = _coerce_float(fill.get("avg_px", fill.get("price", 0.0)))
                close_price = float(closes.loc[ts, f"Close_{sym}"])
                value += signed_qty * (close_price - fill_price)
                value -= _coerce_commission(fill.get("commissions", 0.0))
                pos[sym] += signed_qty

        equity.iloc[i] = value

    return equity


def _fills_by_timestamp(report: Optional[pd.DataFrame]) -> Dict[pd.Timestamp, pd.DataFrame]:
    if report is None or report.empty:
        return {}
    fills = report.copy()
    ts_col = "ts_last" if "ts_last" in fills.columns else "ts_init"
    if ts_col not in fills.columns:
        return {}
    fills["_timestamp"] = _coerce_timestamp(fills[ts_col])
    fills = fills.dropna(subset=["_timestamp"]).sort_values("_timestamp")
    return {ts: group.drop(columns=["_timestamp"]) for ts, group in fills.groupby("_timestamp", sort=True)}


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


def _signed_fill_qty(row) -> float:
    qty = _coerce_float(row.get("filled_qty", 0.0))
    side = str(row.get("side", "")).upper()
    sign = 1.0 if side == "BUY" else -1.0 if side == "SELL" else 0.0
    return sign * qty


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


def _coerce_commission(value) -> float:
    if isinstance(value, (list, tuple)):
        return sum(_coerce_commission(v) for v in value)
    return abs(_coerce_float(value))
