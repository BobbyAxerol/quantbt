"""
Nautilus trustee report bundle exporter.

This module is intentionally outside the backtest engines. It consumes a
completed Nautilus-backed `BacktestResultV2` and writes human/audit artifacts:
raw Nautilus reports, normalized trade logs, a run manifest, and optional
QuantStats HTML.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import subprocess
from typing import Any, Dict, Iterable, List, Optional, Tuple

import numpy as np
import pandas as pd

from ..core.results import BacktestResultV2


REPORT_FILES = (
    "equity_curve.csv",
    "returns.csv",
    "account_report.csv",
    "orders_report.csv",
    "fills_report.csv",
    "positions_report.csv",
    "trade_log.csv",
    "fill_log.txt",
    "metrics_summary.json",
    "run_manifest.json",
    "config.json",
)


def export_nautilus_report_bundle(
    result: BacktestResultV2,
    output_dir: str | Path,
    strategy_id: str,
    config: Optional[Dict[str, Any]] = None,
    benchmark_returns: Optional[pd.Series] = None,
    make_quantstats: bool = True,
    quantstats_frequency: str = "1D",
    quantstats_periods_per_year: int = 365,
    print_fills: bool = False,
    fill_log_limit: int = 500,
    fill_log_mode: str = "fills_only",
) -> Path:
    """
    Export a professional evidence bundle for a Nautilus-backed backtest.

    Parameters
    ----------
    result:
        Completed `BacktestResultV2`, normally returned by
        `QuantBTEndpoint.nautilus_validation(...).simulate(...)`.
    output_dir:
        Parent folder where `report_{strategy_id}_{timestamp}` is created.
    strategy_id:
        Stable identifier for the run/report.
    config:
        Optional JSON-serializable run config to save as `config.json`.
    benchmark_returns:
        Optional benchmark returns passed through to QuantStats when supported.
    make_quantstats:
        Generate `quantstats_daily.html` when quantstats is installed.
    quantstats_frequency:
        Resampling frequency for QuantStats input. Default is daily.
    quantstats_periods_per_year:
        Annualization factor passed to QuantStats. Default is 365 for crypto.
    print_fills:
        Print bounded fill/order event lines to stdout while exporting.
    fill_log_limit:
        Maximum number of human-readable event lines to write/print.
    fill_log_mode:
        `fills_only`, `order_events`, or `bars_debug`. `bars_debug` is bounded
        by `fill_log_limit` and uses position-change rows, not every no-op bar.

    Returns
    -------
    Path
        The created report directory.
    """
    if not isinstance(result, BacktestResultV2):
        raise TypeError("export_nautilus_report_bundle requires BacktestResultV2")
    if not strategy_id:
        raise ValueError("strategy_id is required")
    if fill_log_limit < 0:
        raise ValueError("fill_log_limit must be >= 0")

    run_id = _run_id(strategy_id)
    report_dir = Path(output_dir) / f"report_{_slug(strategy_id)}_{run_id}"
    report_dir.mkdir(parents=True, exist_ok=True)

    metadata = dict(result.metadata or {})
    config_payload = _config_payload_from_result(result=result, metadata=metadata)
    if config:
        config_payload["annotations"] = {**dict(config_payload.get("annotations", {})), **dict(config)}

    account_report = _report_frame(metadata.get("account_report"))
    orders_report = _report_frame(metadata.get("orders_report", metadata.get("order_report")))
    fills_report = _report_frame(metadata.get("fills_report"))
    positions_report = _report_frame(metadata.get("positions_report"))

    equity_curve = _equity_frame(result)
    returns_frame = pd.DataFrame({"timestamp": result.returns.index, "returns": result.returns.to_numpy(dtype=float)})
    trade_log = build_nautilus_trade_log(positions_report, fills_report, strategy_id=strategy_id)
    fill_lines = format_nautilus_event_log(
        fills_report=fills_report,
        orders_report=orders_report,
        positions=result.positions,
        mode=fill_log_mode,
        limit=fill_log_limit,
    )

    _write_frame(equity_curve, report_dir / "equity_curve.csv")
    _write_frame(returns_frame, report_dir / "returns.csv")
    _write_frame(account_report, report_dir / "account_report.csv")
    _write_frame(orders_report, report_dir / "orders_report.csv")
    _write_frame(fills_report, report_dir / "fills_report.csv")
    _write_frame(positions_report, report_dir / "positions_report.csv")
    _write_frame(trade_log, report_dir / "trade_log.csv")
    (report_dir / "fill_log.txt").write_text("\n".join(fill_lines) + ("\n" if fill_lines else ""), encoding="utf-8")

    if print_fills:
        for line in fill_lines:
            print(line)

    metrics_summary = _metrics_summary(result=result, trade_log=trade_log, metadata=metadata)
    manifest = _run_manifest(
        result=result,
        strategy_id=strategy_id,
        run_id=run_id,
        metadata=metadata,
        config=config_payload,
        account_report=account_report,
        orders_report=orders_report,
        fills_report=fills_report,
        positions_report=positions_report,
    )

    if make_quantstats:
        _try_write_quantstats_html(
            result=result,
            output_path=report_dir / "quantstats_daily.html",
            frequency=quantstats_frequency,
            periods_per_year=int(quantstats_periods_per_year),
            benchmark_returns=benchmark_returns,
            manifest=manifest,
        )

    _write_json(report_dir / "metrics_summary.json", metrics_summary)
    _write_json(report_dir / "run_manifest.json", manifest)
    _write_json(report_dir / "config.json", config_payload)

    return report_dir


def build_nautilus_trade_log(
    positions_report: Optional[pd.DataFrame],
    fills_report: Optional[pd.DataFrame],
    strategy_id: str,
) -> pd.DataFrame:
    """Build a stable closed-trade table from Nautilus positions/fills reports."""
    columns = [
        "strategy_id",
        "symbol",
        "exchange",
        "instrument_id",
        "position_type",
        "open_datetime",
        "close_datetime",
        "entry_price",
        "exit_price",
        "quantity",
        "realized_pnl",
        "fees",
        "duration_seconds",
        "return_pct",
        "order_ids",
    ]
    positions = _report_frame(positions_report)
    if positions.empty:
        return pd.DataFrame(columns=columns)

    fills = _report_frame(fills_report)
    rows: List[Dict[str, Any]] = []
    for _, pos in positions.iterrows():
        close_dt = _coerce_timestamp_scalar(pos.get("ts_closed", pos.get("closed_time")))
        if pd.isna(close_dt):
            continue
        instrument_id = str(pos.get("instrument_id", ""))
        symbol, exchange = _instrument_parts(instrument_id)
        open_dt = _coerce_timestamp_scalar(pos.get("ts_opened", pos.get("opened_time")))
        entry_price = _coerce_float(pos.get("avg_px_open", pos.get("entry_price", np.nan)))
        exit_price = _coerce_float(pos.get("avg_px_close", pos.get("exit_price", np.nan)))
        quantity = _coerce_float(pos.get("quantity", pos.get("signed_qty", pos.get("qty", np.nan))))
        realized_pnl = _coerce_money(pos.get("realized_pnl", 0.0))
        fees = _fees_for_position(fills=fills, instrument_id=instrument_id, open_dt=open_dt, close_dt=close_dt)
        side = _position_type(pos)
        duration = _duration_seconds(open_dt, close_dt)
        return_pct = _position_return_pct(side=side, entry_price=entry_price, exit_price=exit_price)

        rows.append(
            {
                "strategy_id": strategy_id,
                "symbol": symbol,
                "exchange": exchange,
                "instrument_id": instrument_id,
                "position_type": side,
                "open_datetime": open_dt,
                "close_datetime": close_dt,
                "entry_price": entry_price,
                "exit_price": exit_price,
                "quantity": quantity,
                "realized_pnl": realized_pnl,
                "fees": fees,
                "duration_seconds": duration,
                "return_pct": return_pct,
                "order_ids": _order_ids_for_position(fills=fills, instrument_id=instrument_id, open_dt=open_dt, close_dt=close_dt),
            }
        )

    out = pd.DataFrame(rows, columns=columns)
    if not out.empty:
        out = out.sort_values(["close_datetime", "open_datetime"], kind="stable").reset_index(drop=True)
    return out


def format_nautilus_event_log(
    fills_report: Optional[pd.DataFrame] = None,
    orders_report: Optional[pd.DataFrame] = None,
    positions: Optional[pd.DataFrame] = None,
    mode: str = "fills_only",
    limit: int = 500,
) -> List[str]:
    """Return bounded human-readable event lines for console/file logging."""
    mode = str(mode).lower().strip()
    if mode not in {"fills_only", "order_events", "bars_debug"}:
        raise ValueError("fill_log_mode must be fills_only, order_events, or bars_debug")
    if limit <= 0:
        return []

    if mode == "bars_debug":
        return _position_change_lines(positions, limit=limit)

    report = _report_frame(fills_report)
    source = "FILL"
    if (report.empty or mode == "order_events") and orders_report is not None:
        order_report = _report_frame(orders_report)
        if not order_report.empty:
            report = order_report
            source = "ORDER"
    if report.empty:
        return []

    lines: List[str] = []
    for _, row in report.head(limit).iterrows():
        ts = _event_timestamp(row)
        side = _event_side(row)
        qty = _event_qty(row)
        instrument = str(row.get("instrument_id", row.get("instrument", "")))
        price = _event_price(row)
        fee = _event_fee(row)
        lines.append(f"{ts} {source} {side} {qty:g} {instrument} @ {price:g} fee={fee:g}")
    return lines


def _try_write_quantstats_html(
    result: BacktestResultV2,
    output_path: Path,
    frequency: str,
    periods_per_year: int,
    benchmark_returns: Optional[pd.Series],
    manifest: Dict[str, Any],
) -> None:
    manifest["quantstats_frequency"] = frequency
    manifest["quantstats_periods_per_year"] = int(periods_per_year)
    try:
        import quantstats as qs
    except Exception as exc:
        manifest["quantstats_status"] = f"skipped: {type(exc).__name__}: {exc}"
        return

    returns = _resampled_returns_for_quantstats(result.equity, frequency=frequency)
    if returns.empty:
        manifest["quantstats_status"] = "skipped: empty returns"
        return
    try:
        qs.reports.html(
            returns,
            benchmark=benchmark_returns,
            output=str(output_path),
            title=f"QuantBT Nautilus Report - {manifest.get('strategy_id', '')}",
            periods_per_year=periods_per_year,
        )
        manifest["quantstats_status"] = "written"
        manifest["quantstats_file"] = output_path.name
    except Exception as exc:
        manifest["quantstats_status"] = f"failed: {type(exc).__name__}: {exc}"


def _resampled_returns_for_quantstats(equity: pd.Series, frequency: str = "1D") -> pd.Series:
    eq = equity.copy()
    eq.index = pd.to_datetime(eq.index, utc=True)
    eq = pd.to_numeric(eq, errors="coerce").dropna()
    if eq.empty:
        return pd.Series(dtype=float)
    sampled = eq.resample(frequency).last().dropna()
    return sampled.pct_change().replace([np.inf, -np.inf], np.nan).dropna()


def _equity_frame(result: BacktestResultV2) -> pd.DataFrame:
    equity = pd.to_numeric(result.equity, errors="coerce")
    returns = pd.to_numeric(result.returns.reindex(result.equity.index), errors="coerce").fillna(0.0)
    peak = equity.cummax()
    drawdown = (equity / peak.replace(0.0, np.nan) - 1.0).fillna(0.0)
    return pd.DataFrame(
        {
            "timestamp": result.equity.index,
            "equity": equity.to_numpy(dtype=float),
            "returns": returns.to_numpy(dtype=float),
            "drawdown": drawdown.to_numpy(dtype=float),
        }
    )


def _metrics_summary(result: BacktestResultV2, trade_log: pd.DataFrame, metadata: Dict[str, Any]) -> Dict[str, Any]:
    equity = pd.to_numeric(result.equity, errors="coerce").dropna()
    final_equity = float(equity.iloc[-1]) if not equity.empty else float("nan")
    total_return_pct = (final_equity / float(result.initial_capital) - 1.0) * 100.0 if result.initial_capital else float("nan")
    drawdown = result.drawdown if len(result.equity) else pd.Series(dtype=float)
    orders_report = _report_frame(metadata.get("orders_report", metadata.get("order_report")))
    status_counts = _order_status_counts(orders_report)
    return {
        "initial_capital": float(result.initial_capital),
        "final_equity": final_equity,
        "total_return_pct": float(total_return_pct),
        "max_drawdown_pct": float(drawdown.max() * 100.0) if not drawdown.empty else 0.0,
        "input_mode": metadata.get("input_mode"),
        "order_count_input": _safe_int(metadata.get("order_count_input")),
        "orders_count": int(metadata.get("orders_count", 0) or 0),
        "fills_count": int(metadata.get("fills_count", 0) or 0),
        "positions_count": int(metadata.get("positions_count", 0) or 0),
        "cancelled_count": status_counts["cancelled"],
        "rejected_count": status_counts["rejected"],
        "trade_log_count": int(len(trade_log)),
        "liquidated": bool(result.liquidated),
    }


def _run_manifest(
    result: BacktestResultV2,
    strategy_id: str,
    run_id: str,
    metadata: Dict[str, Any],
    config: Dict[str, Any],
    account_report: pd.DataFrame,
    orders_report: pd.DataFrame,
    fills_report: pd.DataFrame,
    positions_report: pd.DataFrame,
) -> Dict[str, Any]:
    idx = result.equity.index
    status_counts = _order_status_counts(orders_report)
    return {
        "strategy_id": strategy_id,
        "run_id": run_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "backend": metadata.get("backend", "nautilus"),
        "engine": metadata.get("engine", "NautilusTrader BacktestEngine"),
        "execution_model": "event-driven bar execution",
        "instrument_id": metadata.get("instrument_id") or _first_symbol(result),
        "timeframe": metadata.get("timeframe") or _bar_timeframe(metadata.get("bar_type")),
        "data_start": str(idx[0]) if len(idx) else None,
        "data_end": str(idx[-1]) if len(idx) else None,
        "bar_count": int(len(idx)),
        "signal_count": metadata.get("signal_count"),
        "signal_changes": metadata.get("signal_changes"),
        "input_mode": metadata.get("input_mode"),
        "order_count_input": _safe_int(metadata.get("order_count_input")),
        "initial_capital": float(result.initial_capital),
        "leverage": float(result.leverage),
        "alloc_per_trade": metadata.get("trade_notional", metadata.get("alloc_per_trade")),
        "sizing_mode": metadata.get("sizing_mode"),
        "fee_rate": metadata.get("fee_rate"),
        "use_funding": metadata.get("use_funding"),
        "orders_count": int(metadata.get("orders_count", len(orders_report)) or 0),
        "fills_count": int(metadata.get("fills_count", len(fills_report)) or 0),
        "positions_count": int(metadata.get("positions_count", len(positions_report)) or 0),
        "cancelled_count": status_counts["cancelled"],
        "rejected_count": status_counts["rejected"],
        "account_report_rows": int(len(account_report)),
        "account_final_equity": _safe_float(metadata.get("account_final_equity")),
        "reconstructed_final_equity": _safe_float(metadata.get("reconstructed_final_equity")),
        "account_reconstructed_diff": _safe_float(metadata.get("account_reconstructed_diff")),
        "quantbt_git_commit": _git_commit(),
        "nautilus_version": _package_version("nautilus_trader"),
        "python_version": platform.python_version(),
        "data_hash": _hash_frame(result.closes),
        "signal_hash": metadata.get("signal_hash"),
        "config_keys": sorted(config.keys()),
    }


def _config_payload_from_result(result: BacktestResultV2, metadata: Dict[str, Any]) -> Dict[str, Any]:
    run_config = dict(metadata.get("run_config") or {})
    account = dict(run_config.get("account") or {})
    execution = dict(run_config.get("execution") or {})
    fees = dict(run_config.get("fees") or {})
    sizing = dict(run_config.get("sizing") or {})
    funding = dict(run_config.get("funding") or {})
    nautilus = dict(run_config.get("nautilus") or {})

    requested_fee_rate = _safe_float(metadata.get("fee_rate"))
    if requested_fee_rate is None:
        requested_fee_rate = _safe_float(fees.get("one_way_fee_rate"))
    requested_slippage = _safe_float(metadata.get("slippage"))
    if requested_slippage is None:
        requested_slippage = _safe_float(execution.get("legacy_slippage_rate"))
    requested_slippage_bps = _safe_float(metadata.get("slippage_bps"))
    if requested_slippage_bps is None:
        requested_slippage_bps = _safe_float(execution.get("slippage_bps"))

    return {
        "schema_version": 2,
        "backend": metadata.get("backend", "nautilus"),
        "engine": metadata.get("engine", "NautilusTrader BacktestEngine"),
        "instrument": {
            "instrument_id": metadata.get("instrument_id") or _first_symbol(result),
            "bar_type": metadata.get("bar_type"),
            "timeframe": metadata.get("timeframe") or _bar_timeframe(metadata.get("bar_type")),
        },
        "effective_account": {
            "initial_capital": _safe_float(metadata.get("initial_capital")) or float(result.initial_capital),
            "leverage": _safe_float(metadata.get("leverage")) or float(result.leverage),
            "maintenance_ratio": _safe_float(metadata.get("maintenance_ratio")),
            "margin_mode": account.get("margin_mode"),
            "oms_mode": account.get("oms_mode"),
            "base_currency": account.get("base_currency"),
        },
        "effective_sizing": {
            "sizing_mode": metadata.get("sizing_mode") or sizing.get("hedge_type"),
            "hedge_type": sizing.get("hedge_type"),
            "trade_notional": metadata.get("trade_notional"),
            "alloc_per_trade": metadata.get("alloc_per_trade", sizing.get("alloc_per_trade")),
            "use_pyramiding": metadata.get("use_pyramiding", sizing.get("use_pyramiding")),
            "contract_size": sizing.get("contract_size"),
            "contract_size_note": "contract_size is a multiplier for notional/PnL, not the exchange lot size",
            "quantity_constraints": {
                "qty_step": metadata.get("qty_step"),
                "lot_size": metadata.get("lot_size", metadata.get("qty_step")),
                "min_qty": metadata.get("min_qty"),
                "min_notional": metadata.get("min_notional"),
                "price_increment": metadata.get("price_increment"),
                "note": "Use qty_step/lot_size/min_qty/min_notional for Binance-style fractional order constraints.",
            },
        },
        "effective_fees": {
            "requested_fee_rate": requested_fee_rate,
            "requested_fee_convention": "one_way",
            "requested_fee_source": "endpoint.fee_rate",
            "legacy_fee_round_trip_ignored": fees.get("round_trip_fee"),
            "applied_by": "NautilusTrader MakerTakerFeeModel",
            "custom_fee_rate_applied_to_nautilus": False,
        },
        "effective_execution": {
            "requested_slippage_rate": requested_slippage,
            "requested_slippage_bps": requested_slippage_bps,
            "requested_slippage_source": "endpoint.slippage",
            "applied_by": "NautilusTrader bar market execution",
            "custom_slippage_applied_to_nautilus": False,
            "fill_price_policy": execution.get("fill_price_policy"),
            "same_bar_policy": execution.get("same_bar_policy"),
            "allow_partial_fill": execution.get("allow_partial_fill"),
            "reject_on_insufficient_margin": execution.get("reject_on_insufficient_margin"),
        },
        "funding": {
            "use_funding": metadata.get("use_funding", funding.get("use_funding")),
            "funding_rate": metadata.get("funding_rate", funding.get("funding_rate")),
        },
        "nautilus": nautilus,
        "diagnostics": {
            "orders_count": int(metadata.get("orders_count", 0) or 0),
            "fills_count": int(metadata.get("fills_count", 0) or 0),
            "positions_count": int(metadata.get("positions_count", 0) or 0),
        },
        "annotations": {},
    }


def _report_frame(value: Any) -> pd.DataFrame:
    if isinstance(value, pd.DataFrame):
        return value.copy()
    if value is None:
        return pd.DataFrame()
    try:
        return pd.DataFrame(value).copy()
    except Exception:
        return pd.DataFrame()


def _order_status_counts(orders_report: pd.DataFrame) -> Dict[str, int]:
    if orders_report.empty or "status" not in orders_report:
        return {"cancelled": 0, "rejected": 0}
    status = orders_report["status"].astype(str).str.upper()
    return {
        "cancelled": int(status.isin({"CANCELED", "CANCELLED"}).sum()),
        "rejected": int(status.eq("REJECTED").sum()),
    }


def _safe_int(value: Any) -> Optional[int]:
    try:
        if value is None or pd.isna(value):
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _write_frame(frame: pd.DataFrame, path: Path) -> None:
    frame.copy().to_csv(path, index=False)


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str), encoding="utf-8")


def _run_id(strategy_id: str) -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{ts}_{_hash_text(strategy_id + ts)[:8]}"


def _slug(value: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in str(value).strip())
    return cleaned.strip("_") or "strategy"


def _hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _hash_frame(frame: pd.DataFrame) -> str:
    try:
        payload = {
            "rows": int(len(frame)),
            "columns": list(frame.columns),
            "start": str(frame.index[0]) if len(frame) else None,
            "end": str(frame.index[-1]) if len(frame) else None,
        }
        return _hash_text(json.dumps(payload, sort_keys=True, default=str))
    except Exception:
        return "unavailable"


def _git_commit() -> str:
    try:
        root = Path(__file__).resolve().parents[1]
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(root),
            check=True,
            capture_output=True,
            text=True,
        )
        return completed.stdout.strip()
    except Exception:
        return "unavailable"


def _package_version(package: str) -> str:
    try:
        import importlib.metadata as metadata

        return metadata.version(package)
    except Exception:
        return "unavailable"


def _first_symbol(result: BacktestResultV2) -> Optional[str]:
    return result.symbols[0] if result.symbols else None


def _bar_timeframe(bar_type: Any) -> Optional[str]:
    if not bar_type:
        return None
    parts = str(bar_type).split("-")
    if len(parts) >= 4:
        return "-".join(parts[-4:-2])
    return None


def _instrument_parts(instrument_id: str) -> Tuple[Optional[str], Optional[str]]:
    if not instrument_id:
        return None, None
    if "." in instrument_id:
        main, exchange = instrument_id.split(".", 1)
    else:
        main, exchange = instrument_id, None
    symbol = main.split("-")[0] if "-" in main else main
    return symbol, exchange


def _position_type(row: pd.Series) -> Optional[str]:
    entry = str(row.get("entry", row.get("side", ""))).upper()
    if entry in {"BUY", "LONG"}:
        return "LONG"
    if entry in {"SELL", "SHORT"}:
        return "SHORT"
    side = str(row.get("position_side", "")).upper()
    if side in {"LONG", "SHORT"}:
        return side
    return None


def _coerce_timestamp_scalar(value: Any) -> pd.Timestamp:
    return pd.to_datetime(value, utc=True, errors="coerce")


def _coerce_float(value: Any) -> float:
    try:
        return float(value)
    except Exception:
        return _coerce_money(value)


def _safe_float(value: Any) -> Optional[float]:
    try:
        if value is None:
            return None
        out = float(value)
        if np.isnan(out):
            return None
        return out
    except Exception:
        return None


def _coerce_money(value: Any) -> float:
    if value is None:
        return 0.0
    try:
        return float(value)
    except Exception:
        text = str(value)
        if text.startswith("[") and text.endswith("]"):
            text = text.strip("[]").strip().strip("'").replace("'", "")
        for token in text.replace(",", "").split():
            try:
                return float(token)
            except Exception:
                continue
    return 0.0


def _duration_seconds(open_dt: pd.Timestamp, close_dt: pd.Timestamp) -> Optional[float]:
    if pd.isna(open_dt) or pd.isna(close_dt):
        return None
    return float((close_dt - open_dt).total_seconds())


def _position_return_pct(side: Optional[str], entry_price: float, exit_price: float) -> Optional[float]:
    if not np.isfinite(entry_price) or not np.isfinite(exit_price) or entry_price == 0.0:
        return None
    raw = (exit_price / entry_price - 1.0) * 100.0
    return float(raw if side != "SHORT" else -raw)


def _fees_for_position(fills: pd.DataFrame, instrument_id: str, open_dt: pd.Timestamp, close_dt: pd.Timestamp) -> float:
    subset = _fills_for_position(fills, instrument_id, open_dt, close_dt)
    if subset.empty:
        return 0.0
    fee_cols = [col for col in ("commissions", "commission", "fee") if col in subset.columns]
    if not fee_cols:
        return 0.0
    return float(subset[fee_cols[0]].apply(_coerce_money).sum())


def _order_ids_for_position(fills: pd.DataFrame, instrument_id: str, open_dt: pd.Timestamp, close_dt: pd.Timestamp) -> str:
    subset = _fills_for_position(fills, instrument_id, open_dt, close_dt)
    for col in ("client_order_id", "order_id", "venue_order_id"):
        if col in subset.columns:
            return ",".join(str(x) for x in subset[col].dropna().unique())
    return ""


def _fills_for_position(fills: pd.DataFrame, instrument_id: str, open_dt: pd.Timestamp, close_dt: pd.Timestamp) -> pd.DataFrame:
    if fills.empty or pd.isna(open_dt) or pd.isna(close_dt):
        return pd.DataFrame()
    out = fills.copy()
    if "instrument_id" in out.columns:
        out = out[out["instrument_id"].astype(str) == instrument_id]
    ts_col = _timestamp_column(out)
    if ts_col is None:
        return pd.DataFrame()
    out["_ts"] = pd.to_datetime(out[ts_col], utc=True, errors="coerce")
    return out[(out["_ts"] >= open_dt) & (out["_ts"] <= close_dt)]


def _timestamp_column(frame: pd.DataFrame) -> Optional[str]:
    for col in ("ts_last", "ts_event", "ts_init", "timestamp", "time"):
        if col in frame.columns:
            return col
    return None


def _event_timestamp(row: pd.Series) -> str:
    for col in ("ts_last", "ts_event", "ts_init", "timestamp", "time"):
        if col in row.index:
            ts = _coerce_timestamp_scalar(row.get(col))
            if not pd.isna(ts):
                return str(ts)
    return "NaT"


def _event_side(row: pd.Series) -> str:
    for col in ("side", "order_side", "entry"):
        if col in row.index and str(row.get(col, "")).strip():
            return str(row.get(col)).upper()
    return "UNKNOWN"


def _event_qty(row: pd.Series) -> float:
    for col in ("filled_qty", "last_qty", "quantity", "qty"):
        if col in row.index:
            return abs(_coerce_float(row.get(col)))
    return 0.0


def _event_price(row: pd.Series) -> float:
    for col in ("avg_px", "last_px", "price", "avg_px_open"):
        if col in row.index:
            return _coerce_float(row.get(col))
    return 0.0


def _event_fee(row: pd.Series) -> float:
    for col in ("commissions", "commission", "fee"):
        if col in row.index:
            return _coerce_money(row.get(col))
    return 0.0


def _position_change_lines(positions: Optional[pd.DataFrame], limit: int) -> List[str]:
    if positions is None or positions.empty:
        return []
    pos = positions.copy().fillna(0.0)
    changed = pos.diff().abs().sum(axis=1).fillna(pos.abs().sum(axis=1)) > 0.0
    lines: List[str] = []
    for ts, row in pos.loc[changed].head(limit).iterrows():
        state = ", ".join(f"{col}={float(value):g}" for col, value in row.items())
        lines.append(f"{pd.Timestamp(ts)} POSITION {state}")
    return lines
