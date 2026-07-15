"""Parity helpers for native-vs-Nautilus audit reports."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from ..core.orders import Fill, OrderIntent
from ..core.results import BacktestResultV2


PARITY_COLUMNS = [
    "row",
    "timestamp",
    "symbol",
    "side",
    "requested_qty",
    "requested_price",
    "native_fill_price",
    "nautilus_fill_price",
    "fill_price_diff",
    "native_fee",
    "nautilus_fee",
    "fee_diff",
    "native_position_after",
    "nautilus_position_after",
    "position_diff",
    "native_equity",
    "nautilus_equity",
    "equity_diff",
    "native_status",
    "nautilus_status",
]


def build_nautilus_depth_parity_summary(result: BacktestResultV2) -> Dict[str, Any]:
    """
    Summarize preflight-vs-Nautilus package execution counts.

    This helper is for Phase 5.4 package workflows where an optional
    execution-depth preflight may reject, cancel, or partially adjust orders
    before accepted orders are submitted to Nautilus.
    """
    metadata = result.metadata or {}
    depth_order_report = _report_frame(metadata.get("nautilus_depth_order_report"))
    depth_package_report = _report_frame(metadata.get("nautilus_depth_package_report"))
    package_order_map = _report_frame(metadata.get("package_order_map"))
    orders_report = _report_frame(metadata.get("orders_report", metadata.get("order_report")))
    fills_report = _report_frame(metadata.get("fills_report"))
    depth_enabled = bool(metadata.get("nautilus_depth_enabled", False))
    accepted = int(metadata.get("order_count_after_depth", len(package_order_map)))
    before = int(metadata.get("order_count_before_depth", accepted))
    nautilus_orders = int(metadata.get("orders_count", len(orders_report)))
    nautilus_fills = int(metadata.get("fills_count", len(fills_report)))
    rejected = _status_count(depth_order_report, "rejected")
    partial = _status_count(depth_order_report, "partial")
    canceled = _status_count(depth_order_report, "canceled")
    submitted_matches = nautilus_orders == accepted or (accepted == 0 and nautilus_orders == 0)
    summary = {
        "status": "pass" if submitted_matches else "execution_count_diff",
        "passed": bool(submitted_matches),
        "depth_enabled": depth_enabled,
        "input_orders": before,
        "accepted_after_depth": accepted,
        "nautilus_orders": nautilus_orders,
        "nautilus_fills": nautilus_fills,
        "depth_rejected": rejected,
        "depth_partial": partial,
        "depth_canceled": canceled,
        "package_rows": int(len(depth_package_report)),
        "engine": metadata.get("engine"),
        "input_mode": metadata.get("input_mode"),
    }
    if not depth_enabled:
        summary["status"] = "not_enabled"
        summary["passed"] = False
    return summary


def summarize_native_nautilus_parity_report(
    parity_report: pd.DataFrame,
    fill_price_tolerance: float = 1e-9,
    fee_tolerance: float = 1e-9,
    position_tolerance: float = 1e-9,
    equity_tolerance: float = 1e-6,
) -> Dict[str, Any]:
    """Return compact institutional audit diagnostics for a parity table."""
    frame = parity_report.copy()
    summary = {
        "rows": int(len(frame)),
        "native_filled_rows": int(frame["native_fill_price"].notna().sum()) if "native_fill_price" in frame else 0,
        "nautilus_filled_rows": int(frame["nautilus_fill_price"].notna().sum()) if "nautilus_fill_price" in frame else 0,
        "max_abs_fill_price_diff": _max_abs(frame, "fill_price_diff"),
        "max_abs_fee_diff": _max_abs(frame, "fee_diff"),
        "max_abs_position_diff": _max_abs(frame, "position_diff"),
        "max_abs_equity_diff": _max_abs(frame, "equity_diff"),
        "fill_price_tolerance": float(fill_price_tolerance),
        "fee_tolerance": float(fee_tolerance),
        "position_tolerance": float(position_tolerance),
        "equity_tolerance": float(equity_tolerance),
    }
    summary["passed"] = bool(
        summary["max_abs_fill_price_diff"] <= fill_price_tolerance
        and summary["max_abs_fee_diff"] <= fee_tolerance
        and summary["max_abs_position_diff"] <= position_tolerance
        and summary["max_abs_equity_diff"] <= equity_tolerance
    )
    if summary["passed"]:
        summary["status"] = "pass"
    elif summary["max_abs_fill_price_diff"] > fill_price_tolerance or summary["max_abs_position_diff"] > position_tolerance:
        summary["status"] = "execution_diff"
    else:
        summary["status"] = "accounting_diff"
    return summary


def build_native_nautilus_parity_report(
    native_result: BacktestResultV2,
    nautilus_result: BacktestResultV2,
) -> pd.DataFrame:
    """
    Build an execution audit table comparing native event and Nautilus results.

    The report is intentionally tolerant of source formats. Native results are
    usually dataclass-backed (`orders` and `fills`), while Nautilus results are
    report-backed (`orders_report`, `fills_report`, `package_order_map`). Rows
    are aligned by order/fill sequence, which is stable for deterministic
    single-symbol explicit-order replay.
    """
    native_orders = _orders_from_result(native_result)
    native_fills = _fills_from_result(native_result)
    nautilus_orders = _orders_from_result(nautilus_result)
    nautilus_fills = _fills_from_result(nautilus_result)
    row_count = max(len(native_orders), len(nautilus_orders), len(native_fills), len(nautilus_fills))

    rows: List[Dict[str, Any]] = []
    for row in range(row_count):
        native_order = _row(native_orders, row)
        nautilus_order = _row(nautilus_orders, row)
        native_fill = _row(native_fills, row)
        nautilus_fill = _row(nautilus_fills, row)

        timestamp = _first_non_null(
            _get(native_fill, "timestamp"),
            _get(nautilus_fill, "timestamp"),
            _get(native_order, "timestamp"),
            _get(nautilus_order, "timestamp"),
        )
        if timestamp is not None and not pd.isna(timestamp):
            timestamp = _coerce_ts(timestamp)
        symbol = _first_non_null(
            _get(native_order, "symbol"),
            _get(nautilus_order, "symbol"),
            _get(native_fill, "symbol"),
            _get(nautilus_fill, "symbol"),
        )
        side = _first_non_null(
            _get(native_order, "side"),
            _get(nautilus_order, "side"),
            _get(native_fill, "side"),
            _get(nautilus_fill, "side"),
        )
        requested_qty = _first_float(_get(native_order, "qty"), _get(nautilus_order, "qty"))
        requested_price = _first_float(_get(native_order, "price"), _get(nautilus_order, "price"))
        native_price = _safe_float(_get(native_fill, "price"))
        nautilus_price = _safe_float(_get(nautilus_fill, "price"))
        native_fee = _safe_float(_get(native_fill, "fee"))
        nautilus_fee = _safe_float(_get(nautilus_fill, "fee"))
        native_equity = _equity_at(native_result, timestamp)
        nautilus_equity = _equity_at(nautilus_result, timestamp)
        native_pos = _position_at(native_result, symbol, timestamp)
        nautilus_pos = _position_at(nautilus_result, symbol, timestamp)

        rows.append(
            {
                "row": row,
                "timestamp": timestamp,
                "symbol": symbol,
                "side": side,
                "requested_qty": requested_qty,
                "requested_price": requested_price,
                "native_fill_price": native_price,
                "nautilus_fill_price": nautilus_price,
                "fill_price_diff": _diff(native_price, nautilus_price),
                "native_fee": native_fee,
                "nautilus_fee": nautilus_fee,
                "fee_diff": _diff(native_fee, nautilus_fee),
                "native_position_after": native_pos,
                "nautilus_position_after": nautilus_pos,
                "position_diff": _diff(native_pos, nautilus_pos),
                "native_equity": native_equity,
                "nautilus_equity": nautilus_equity,
                "equity_diff": _diff(native_equity, nautilus_equity),
                "native_status": _get(native_order, "status"),
                "nautilus_status": _get(nautilus_order, "status"),
            }
        )
    return pd.DataFrame(rows, columns=PARITY_COLUMNS)


def _orders_from_result(result: BacktestResultV2) -> pd.DataFrame:
    package_map = _report_frame(result.metadata.get("package_order_map"))
    if not package_map.empty:
        out = pd.DataFrame(
            {
                "timestamp": pd.to_datetime(package_map.get("timestamp"), utc=True, errors="coerce"),
                "symbol": package_map.get("symbol", package_map.get("instrument_id")),
                "side": package_map.get("side"),
                "qty": pd.to_numeric(package_map.get("qty"), errors="coerce"),
                "price": pd.to_numeric(package_map.get("price"), errors="coerce"),
                "status": pd.Series([None] * len(package_map), dtype=object),
            }
        )
        orders_report = _report_frame(result.metadata.get("orders_report", result.metadata.get("order_report")))
        if not orders_report.empty and "status" in orders_report:
            out.loc[: len(orders_report) - 1, "status"] = list(orders_report["status"].head(len(out)))
        return out

    if result.orders:
        rows = []
        for order in result.orders:
            rows.append(
                {
                    "timestamp": _coerce_ts(order.timestamp),
                    "symbol": order.symbol,
                    "side": _enum_value(order.side),
                    "qty": float(order.qty),
                    "price": order.price,
                    "status": None,
                }
            )
        order_report = _report_frame(result.metadata.get("order_report"))
        if not order_report.empty and "status" in order_report:
            for idx, status in enumerate(order_report["status"].head(len(rows))):
                rows[idx]["status"] = status
        return pd.DataFrame(rows)
    return pd.DataFrame(columns=["timestamp", "symbol", "side", "qty", "price", "status"])


def _fills_from_result(result: BacktestResultV2) -> pd.DataFrame:
    fills_report = _report_frame(result.metadata.get("fills_report"))
    if fills_report.empty:
        fills_report = _report_frame(result.metadata.get("orders_report"))
    if not fills_report.empty:
        filled = fills_report
        if "status" in filled:
            filled = filled[filled["status"].astype(str).str.upper().eq("FILLED")]
        return pd.DataFrame(
            {
                "timestamp": _timestamp_column(filled),
                "symbol": filled.get("instrument_id", filled.get("symbol")),
                "side": filled.get("side"),
                "qty": pd.to_numeric(filled.get("filled_qty", filled.get("quantity")), errors="coerce"),
                "price": pd.to_numeric(filled.get("avg_px", filled.get("price")), errors="coerce"),
                "fee": filled.apply(_row_fee, axis=1),
            }
        ).reset_index(drop=True)

    if result.fills:
        rows = []
        for fill in result.fills:
            rows.append(
                {
                    "timestamp": _coerce_ts(fill.timestamp),
                    "symbol": fill.symbol,
                    "side": _enum_value(fill.side),
                    "qty": float(fill.qty),
                    "price": float(fill.price),
                    "fee": float(fill.fee),
                }
            )
        return pd.DataFrame(rows)
    return pd.DataFrame(columns=["timestamp", "symbol", "side", "qty", "price", "fee"])


def _report_frame(value: Any) -> pd.DataFrame:
    if isinstance(value, pd.DataFrame):
        return value.copy()
    if value is None:
        return pd.DataFrame()
    try:
        return pd.DataFrame(value).copy()
    except Exception:
        return pd.DataFrame()


def _status_count(frame: pd.DataFrame, status: str) -> int:
    if frame.empty or "status" not in frame:
        return 0
    return int(frame["status"].astype(str).str.lower().eq(status).sum())


def _max_abs(frame: pd.DataFrame, column: str) -> float:
    if column not in frame:
        return 0.0
    series = pd.to_numeric(frame[column], errors="coerce").abs().dropna()
    return float(series.max()) if not series.empty else 0.0


def _timestamp_column(frame: pd.DataFrame) -> pd.Series:
    for key in ("ts_last", "ts_event", "timestamp", "ts_init"):
        if key in frame:
            return pd.to_datetime(frame[key], utc=True, errors="coerce")
    return pd.Series(pd.NaT, index=frame.index)


def _row_fee(row: pd.Series) -> float:
    for key in ("fee", "fees", "commissions"):
        if key in row and row[key] is not None:
            return _money_float(row[key])
    return 0.0


def _money_float(value: Any) -> float:
    if isinstance(value, (int, float, np.number)):
        return float(value)
    text = str(value).replace(",", "").replace("[", "").replace("]", "").strip()
    if not text or text.lower() == "nan":
        return 0.0
    try:
        return float(text.split()[0])
    except (TypeError, ValueError, IndexError):
        return 0.0


def _equity_at(result: BacktestResultV2, timestamp: Any) -> float:
    if timestamp is None or pd.isna(timestamp) or result.equity.empty:
        return float("nan")
    ts = _coerce_ts(timestamp)
    series = result.equity.sort_index()
    loc = series.index.searchsorted(ts, side="right") - 1
    if loc < 0:
        return float("nan")
    return float(series.iloc[loc])


def _position_at(result: BacktestResultV2, symbol: Any, timestamp: Any) -> float:
    if symbol is None or timestamp is None or pd.isna(timestamp) or result.positions.empty:
        return float("nan")
    col = _position_column(result.positions, str(symbol))
    if col is None:
        return float("nan")
    ts = _coerce_ts(timestamp)
    frame = result.positions.sort_index()
    loc = frame.index.searchsorted(ts, side="right") - 1
    if loc < 0:
        return float("nan")
    return _safe_float(frame[col].iloc[loc])


def _position_column(positions: pd.DataFrame, symbol: str) -> Optional[str]:
    candidates = [f"Position_{symbol}", symbol]
    if symbol.endswith("-PERP.BINANCE"):
        candidates.append(f"Position_{symbol.removesuffix('-PERP.BINANCE')}")
    for col in candidates:
        if col in positions.columns:
            return col
    suffix = symbol.split(".")[0]
    for col in positions.columns:
        if str(col).endswith(symbol) or str(col).endswith(suffix):
            return col
    return None


def _coerce_ts(value: Any) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    if ts.tz is None:
        return ts.tz_localize("UTC")
    return ts.tz_convert("UTC")


def _safe_float(value: Any) -> float:
    try:
        if value is None or pd.isna(value):
            return float("nan")
        return float(value)
    except (TypeError, ValueError):
        return _money_float(value)


def _first_float(*values: Any) -> float:
    for value in values:
        number = _safe_float(value)
        if not np.isnan(number):
            return number
    return float("nan")


def _diff(left: float, right: float) -> float:
    if np.isnan(left) or np.isnan(right):
        return float("nan")
    return float(right - left)


def _row(frame: pd.DataFrame, idx: int) -> Optional[pd.Series]:
    if frame is None or frame.empty or idx >= len(frame):
        return None
    return frame.iloc[idx]


def _get(row: Optional[pd.Series], key: str) -> Any:
    if row is None or key not in row:
        return None
    return row[key]


def _first_non_null(*values: Any) -> Any:
    for value in values:
        if value is not None and not (isinstance(value, float) and np.isnan(value)) and not pd.isna(value):
            if key := _maybe_enum_value(value):
                return key
            return value
    return None


def _maybe_enum_value(value: Any) -> Any:
    if hasattr(value, "value"):
        return value.value
    return None


def _enum_value(value: Any) -> Any:
    return value.value if hasattr(value, "value") else value
