"""Cold portfolio report construction from executed account buffers."""

from __future__ import annotations

from typing import Dict, List, Optional

import numpy as np
import pandas as pd


def _build_symbol_pnl_report(
    *,
    idx: pd.DatetimeIndex,
    symbols: List[str],
    accepted_units_arr: np.ndarray,
    closes_arr: np.ndarray,
    funding_rates_arr: np.ndarray,
    is_funding_bar: np.ndarray,
    contract_sizes: np.ndarray,
    fee_arr: np.ndarray,
    slippage_arr: np.ndarray,
    attribution: Optional[np.ndarray] = None,
) -> pd.DataFrame:
    n_bars, n_syms = accepted_units_arr.shape
    if n_bars == 0 or n_syms == 0:
        return pd.DataFrame()
    prev_units = np.vstack([np.zeros((1, n_syms), dtype=np.float64), accepted_units_arr[:-1]])
    prev_close = np.vstack([closes_arr[0:1], closes_arr[:-1]])
    cs = contract_sizes.reshape(1, -1)
    mark_pnl = prev_units * (closes_arr - prev_close) * cs
    funding_cost = prev_units * closes_arr * cs * funding_rates_arr
    funding_cost = np.where(is_funding_bar.reshape(-1, 1).astype(bool), funding_cost, 0.0)
    trade_delta = np.abs(accepted_units_arr - prev_units)
    trade_notional = trade_delta * closes_arr * cs
    total_trade_notional = trade_notional.sum(axis=1, keepdims=True)
    share = np.divide(
        trade_notional,
        total_trade_notional,
        out=np.zeros_like(trade_notional),
        where=total_trade_notional != 0.0,
    )
    fee = fee_arr.reshape(-1, 1) * share
    slippage = slippage_arr.reshape(-1, 1) * share
    liquidation_adjustment = np.zeros_like(mark_pnl)
    if attribution is not None:
        fee = attribution[:, :, 0]
        slippage = attribution[:, :, 1]
        funding_cost = attribution[:, :, 2]
        liquidation_adjustment = attribution[:, :, 3]
    total_pnl = mark_pnl - funding_cost - fee - slippage - liquidation_adjustment

    return pd.DataFrame(
        {
            "timestamp": np.tile(np.asarray(idx, dtype=object), n_syms),
            "symbol": np.repeat(np.asarray(symbols, dtype=object), n_bars),
            "position_units": accepted_units_arr.T.reshape(-1),
            "close": closes_arr.T.reshape(-1),
            "mark_pnl": mark_pnl.T.reshape(-1),
            "funding_cost": funding_cost.T.reshape(-1),
            "funding_pnl": (-funding_cost).T.reshape(-1),
            "fee": fee.T.reshape(-1),
            "fee_pnl": (-fee).T.reshape(-1),
            "slippage_cost": slippage.T.reshape(-1),
            "slippage_pnl": (-slippage).T.reshape(-1),
            "liquidation_adjustment": liquidation_adjustment.T.reshape(-1),
            "liquidation_pnl": (-liquidation_adjustment).T.reshape(-1),
            "total_pnl": total_pnl.T.reshape(-1),
        }
    )

def _build_exposure_report(
    *,
    accepted_notional_arr: np.ndarray,
    target_notional_arr: np.ndarray,
    equity_arr: np.ndarray,
    idx: pd.DatetimeIndex,
    leverages: np.ndarray,
    maintenance_ratio: float,
    betas: np.ndarray,
) -> pd.DataFrame:
    abs_accepted = np.abs(accepted_notional_arr)
    gross = abs_accepted.sum(axis=1)
    net = accepted_notional_arr.sum(axis=1)
    initial_margin = (abs_accepted / leverages.reshape(1, -1)).sum(axis=1)
    maintenance_margin = gross * float(maintenance_ratio)
    beta_exposure = (accepted_notional_arr * betas.reshape(1, -1)).sum(axis=1)
    target_gross = np.abs(target_notional_arr).sum(axis=1)
    target_beta_exposure = (target_notional_arr * betas.reshape(1, -1)).sum(axis=1)
    mean_leverage = float(np.mean(leverages))
    gross_leverage = np.divide(gross, equity_arr, out=np.zeros_like(gross), where=equity_arr != 0.0)
    net_exposure_pct = np.divide(net, equity_arr, out=np.zeros_like(net), where=equity_arr != 0.0)
    return pd.DataFrame(
        {
            "long_notional": np.where(accepted_notional_arr > 0.0, accepted_notional_arr, 0.0).sum(axis=1),
            "short_notional": np.where(accepted_notional_arr < 0.0, -accepted_notional_arr, 0.0).sum(axis=1),
            "gross_notional": gross,
            "net_notional": net,
            "beta_exposure_notional": beta_exposure,
            "target_gross_notional": target_gross,
            "target_beta_exposure_notional": target_beta_exposure,
            "initial_margin": initial_margin,
            "maintenance_margin": maintenance_margin,
            "equity": equity_arr,
            "available_equity_after_im": equity_arr - initial_margin,
            "buying_power": (equity_arr * mean_leverage if np.all(leverages == leverages[0])
                             else np.full(len(equity_arr), np.nan)),
            "available_margin": np.maximum(equity_arr - initial_margin, 0.0),
            "gross_leverage": gross_leverage,
            "net_exposure_pct": net_exposure_pct,
        },
        index=idx,
    )

def _build_rebalance_report(
    *,
    idx: pd.DatetimeIndex,
    symbols: List[str],
    target_units_arr: np.ndarray,
    accepted_units_arr: np.ndarray,
    closes_arr: np.ndarray,
    contract_sizes: np.ndarray,
    tradable_mask: np.ndarray,
    quantity_constraints: Dict[str, Dict[str, float]],
) -> pd.DataFrame:
    diff = target_units_arr - accepted_units_arr
    row_idx, col_idx = np.nonzero(np.abs(diff) > 1e-10)
    if len(row_idx) == 0:
        return pd.DataFrame(
            columns=["timestamp", "symbol", "target_units", "accepted_units", "unit_diff", "notional_diff", "reason"]
        )
    unit_diff = diff[row_idx, col_idx]
    notional_diff = unit_diff * closes_arr[row_idx, col_idx] * contract_sizes[col_idx]
    symbol_arr = np.asarray(symbols, dtype=object)
    reasons = []
    for r, c in zip(row_idx, col_idx):
        symbol = symbols[int(c)]
        target = float(target_units_arr[r, c])
        close = float(closes_arr[r, c])
        cs = float(contract_sizes[c])
        constraints = quantity_constraints.get(symbol, {})
        min_qty = float(constraints.get("min_qty", 0.0) or 0.0)
        min_notional = float(constraints.get("min_notional", 0.0) or 0.0)
        previous = float(accepted_units_arr[r - 1, c]) if r > 0 else 0.0
        reduction = previous * target >= 0.0 and abs(target) <= abs(previous)
        abs_delta = abs(target - previous)
        notional = abs_delta * close * cs if np.isfinite(close) else np.nan
        if not np.isfinite(target):
            reasons.append("INVALID_TARGET")
        elif not np.isfinite(close) or close <= 0.0:
            reasons.append("NON_TRADABLE")
        elif not bool(tradable_mask[r, c]):
            reasons.append("STALE_PRICE")
        elif not reduction and min_qty > 0.0 and 0.0 < abs_delta < min_qty:
            reasons.append("MIN_QTY")
        elif not reduction and min_notional > 0.0 and np.isfinite(notional) and 0.0 < notional < min_notional:
            reasons.append("MIN_NOTIONAL")
        else:
            reasons.append("POST_COST_MARGIN")
    return pd.DataFrame(
        {
            "timestamp": idx.take(row_idx),
            "symbol": symbol_arr[col_idx],
            "target_units": target_units_arr[row_idx, col_idx],
            "accepted_units": accepted_units_arr[row_idx, col_idx],
            "unit_diff": unit_diff,
            "notional_diff": notional_diff,
            "reason": reasons,
        }
    )

def _build_reconciliation_report(
    *,
    initial_capital: float,
    equity_arr: np.ndarray,
    fee_arr: np.ndarray,
    slippage_arr: np.ndarray,
    turnover_arr: np.ndarray,
    positions: pd.DataFrame,
    target_units_report: pd.DataFrame,
    accepted_units_report: pd.DataFrame,
    symbol_pnl_report: pd.DataFrame,
) -> Dict[str, float]:
    if symbol_pnl_report is None or symbol_pnl_report.empty:
        symbol_fee = 0.0
        symbol_slippage = 0.0
        symbol_pnl = 0.0
    else:
        symbol_fee = float(symbol_pnl_report["fee"].sum())
        symbol_slippage = float(symbol_pnl_report["slippage_cost"].sum())
        symbol_pnl = float(symbol_pnl_report["total_pnl"].sum())
    positions_values = positions.to_numpy(dtype=np.float64, copy=False)
    accepted_values = accepted_units_report.to_numpy(dtype=np.float64, copy=False)
    return {
        "fee_total": float(np.sum(fee_arr)),
        "symbol_fee_total": symbol_fee,
        "fee_diff": float(np.sum(fee_arr) - symbol_fee),
        "slippage_total": float(np.sum(slippage_arr)),
        "symbol_slippage_total": symbol_slippage,
        "slippage_diff": float(np.sum(slippage_arr) - symbol_slippage),
        "turnover_total": float(np.sum(turnover_arr)),
        "symbol_total_pnl": symbol_pnl,
        "equity_pnl": float(equity_arr[-1] - initial_capital) if len(equity_arr) else 0.0,
        "equity_symbol_pnl_diff": float((equity_arr[-1] - initial_capital) - symbol_pnl) if len(equity_arr) else 0.0,
        "max_result_position_diff": float(np.nanmax(np.abs(positions_values - accepted_values))) if positions_values.size else 0.0,
        "max_target_accepted_diff": float(np.nanmax(np.abs(target_units_report.to_numpy(dtype=np.float64, copy=False) - accepted_values))) if accepted_values.size else 0.0,
    }
