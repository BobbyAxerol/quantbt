"""
quantbt.metrics.performance
----------------------------
Pure functions.  All accept a BacktestResult (or bare pd.Series of returns)
and return scalars or DataFrames.  No side-effects, no plotting.

All return-based statistics default to daily frequency with 365-day Sharpe
scaling (crypto); pass trading_days=252 for equities.
"""

from __future__ import annotations

from typing import Tuple, Dict

import numpy as np
import pandas as pd

from ..core.types import BacktestResult


# ── helpers ──────────────────────────────────────────────────────────────────

def _daily(result: BacktestResult) -> pd.Series:
    return result.daily_returns


def _equity_daily(result: BacktestResult) -> pd.Series:
    return result.daily_equity


# ── return metrics ───────────────────────────────────────────────────────────

def total_return(result: BacktestResult) -> float:
    """Total return as a decimal (0.25 = 25%)."""
    eq = result.equity
    return (eq.iloc[-1] - result.initial_capital) / result.initial_capital


def cagr(result: BacktestResult, trading_days: int = 365) -> float:
    """Compound annual growth rate."""
    eq    = _equity_daily(result)
    years = len(eq) / trading_days
    if years <= 0:
        return 0.0
    return (eq.iloc[-1] / eq.iloc[0]) ** (1.0 / years) - 1.0


def sharpe(result: BacktestResult, trading_days: int = 365, risk_free: float = 0.0) -> float:
    r  = _daily(result) - risk_free / trading_days
    sd = r.std(ddof=1)
    return (r.mean() / sd) * np.sqrt(trading_days) if sd > 0 else 0.0


def sortino(result: BacktestResult, trading_days: int = 365, mar: float = 0.0) -> float:
    r  = _daily(result)
    d  = r[r < mar] - mar
    dd = np.sqrt((d ** 2).mean()) if len(d) > 0 else 0.0
    return (r.mean() / dd) * np.sqrt(trading_days) if dd > 0 else 0.0


def calmar(result: BacktestResult, trading_days: int = 365) -> float:
    c   = cagr(result, trading_days)
    mdd = max_drawdown(result)
    return c / mdd if mdd > 0 else 0.0


def omega(result: BacktestResult, threshold: float = 0.0) -> float:
    """Omega ratio (Keating & Shadwick)."""
    r    = _daily(result)
    gain = (r[r > threshold] - threshold).sum()
    loss = (threshold - r[r < threshold]).sum()
    return gain / loss if loss > 0 else np.inf


# ── drawdown metrics ─────────────────────────────────────────────────────────

def max_drawdown(result: BacktestResult) -> float:
    """Maximum drawdown as a positive fraction."""
    return float(result.drawdown.max())


def max_drawdown_pct(result: BacktestResult) -> float:
    return max_drawdown(result) * 100.0


def avg_drawdown(result: BacktestResult) -> float:
    """Mean of all drawdown troughs (fraction)."""
    dd = result.drawdown
    return float(dd[dd > 0].mean()) if (dd > 0).any() else 0.0


def drawdown_duration(result: BacktestResult) -> Tuple[int, int]:
    """
    Returns (max_duration_bars, avg_duration_bars).
    Duration counted in calendar days on daily equity.
    """
    eq   = _equity_daily(result)
    peak = eq.cummax()
    in_dd = (peak != eq)

    durations = []
    run = 0
    for v in in_dd:
        if v:
            run += 1
        else:
            if run > 0:
                durations.append(run)
            run = 0
    if run > 0:
        durations.append(run)

    if not durations:
        return 0, 0
    return int(max(durations)), int(np.mean(durations))


# ── trade statistics ─────────────────────────────────────────────────────────

def hitrate(result: BacktestResult) -> Tuple[float, float]:
    """
    Returns (long_hitrate_pct, short_hitrate_pct).
    A bar is a 'win' if the daily return > 0 while the position is active.
    """
    eq_ret   = result.returns
    long_hr  = []
    short_hr = []

    for sym in result.symbols:
        pos = result.positions[f"Position_{sym}"]
        long_mask  = pos > 0
        short_mask = pos < 0

        long_wins  = ((eq_ret > 0) & long_mask).sum()
        long_total = long_mask.sum()

        short_wins  = ((eq_ret > 0) & short_mask).sum()
        short_total = short_mask.sum()

        long_hr.append(long_wins  / long_total  * 100 if long_total  > 0 else 0.0)
        short_hr.append(short_wins / short_total * 100 if short_total > 0 else 0.0)

    return float(np.mean(long_hr)), float(np.mean(short_hr))


def number_of_trades(result: BacktestResult) -> int:
    """Count signal transitions (any symbol)."""
    count = 0
    for sym in result.symbols:
        pos = result.positions[f"Position_{sym}"]
        count += int((pos.diff() != 0).sum())
    return count


def profit_factor(result: BacktestResult) -> float:
    r     = _daily(result)
    gains = r[r > 0].sum()
    loss  = abs(r[r < 0].sum())
    return gains / loss if loss > 0 else np.inf


def avg_win_loss(result: BacktestResult) -> Tuple[float, float]:
    """(avg_win_pct, avg_loss_pct) in percent."""
    r = _daily(result)
    w = r[r > 0].mean() * 100 if (r > 0).any() else 0.0
    l = r[r < 0].mean() * 100 if (r < 0).any() else 0.0
    return float(w), float(l)


def expectancy(result: BacktestResult) -> float:
    """
    Expectancy = HR × avg_win + (1 − HR) × avg_loss
    (uses combined long/short hitrate average)
    """
    lh, sh   = hitrate(result)
    hr       = (lh + sh) / 200.0          # convert to decimal average
    aw, al   = avg_win_loss(result)
    return hr * aw + (1 - hr) * al


# ── rolling metrics ──────────────────────────────────────────────────────────

def rolling_sharpe(
    result:       BacktestResult,
    window:       int = 30,
    trading_days: int = 365,
) -> pd.Series:
    r  = _daily(result)
    mu = r.rolling(window).mean()
    sd = r.rolling(window).std(ddof=1)
    return (mu / sd) * np.sqrt(trading_days)


def rolling_drawdown(result: BacktestResult) -> pd.Series:
    """Rolling drawdown fraction from trailing peak."""
    eq   = _equity_daily(result)
    peak = eq.cummax()
    return (peak - eq) / peak


# ── full report dict ─────────────────────────────────────────────────────────

def full_report(result: BacktestResult, trading_days: int = 365) -> Dict:
    """
    Returns an ordered dict of all key metrics.
    Suitable for programmatic use; viz/tearsheet renders it.
    """
    lh, sh   = hitrate(result)
    aw, al   = avg_win_loss(result)
    md, ad   = drawdown_duration(result)

    return {
        "initial_capital":      result.initial_capital,
        "final_equity":         float(result.equity.iloc[-1]),
        "total_return_pct":     total_return(result) * 100,
        "cagr_pct":             cagr(result, trading_days) * 100,
        "sharpe":               sharpe(result, trading_days),
        "sortino":              sortino(result, trading_days),
        "calmar":               calmar(result, trading_days),
        "omega":                omega(result),
        "max_drawdown_pct":     max_drawdown_pct(result),
        "avg_drawdown_pct":     avg_drawdown(result) * 100,
        "max_dd_duration_days": md,
        "avg_dd_duration_days": ad,
        "profit_factor":        profit_factor(result),
        "long_hitrate_pct":     lh,
        "short_hitrate_pct":    sh,
        "avg_win_pct":          aw,
        "avg_loss_pct":         al,
        "expectancy_pct":       expectancy(result),
        "num_trades":           number_of_trades(result),
        "liquidated":           result.liquidated,
    }
