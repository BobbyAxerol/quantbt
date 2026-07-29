"""
quantbt.metrics.performance
----------------------------
Pure functions.  All accept a BacktestResult (or bare pd.Series of returns)
and return scalars or DataFrames.  No side-effects, no plotting.

All return-based statistics default to daily frequency with 365-day Sharpe
scaling (crypto); pass trading_days=252 for equities.
"""

from __future__ import annotations

from typing import Dict, Sequence, Tuple

import numpy as np
import pandas as pd

from ..core.types import BacktestResult


# ── helpers ──────────────────────────────────────────────────────────────────

def _daily(result: BacktestResult) -> pd.Series:
    return result.daily_returns


def _equity_daily(result: BacktestResult) -> pd.Series:
    return result.daily_equity


def _finite_returns(series: pd.Series) -> pd.Series:
    r = pd.to_numeric(series, errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()
    return r.astype(float)


def _returns_for_stats(result: BacktestResult) -> pd.Series:
    """
    Return sample used by distribution metrics.

    Daily returns are preferred for stable multi-day reports.  Very short
    intraday/scoped runs can collapse to one daily equity point, producing an
    empty daily return sample; in that case we fall back to bar returns so
    Sharpe, Omega, PF, and avg win/loss do not become artificial 0/inf values.
    """
    daily = _finite_returns(_daily(result))
    if len(daily) > 0:
        return daily
    bar = _finite_returns(result.returns)
    if len(bar) > 0:
        return bar
    return _finite_returns(result.equity.pct_change().fillna(0.0))


def _annualization_periods(result: BacktestResult, trading_days: int) -> float:
    daily = _finite_returns(_daily(result))
    if len(daily) > 0:
        return float(trading_days)
    idx = result.equity.index
    if len(idx) >= 2 and isinstance(idx, pd.DatetimeIndex):
        deltas = idx.to_series().diff().dropna().dt.total_seconds()
        deltas = deltas[deltas > 0.0]
        if len(deltas) > 0:
            median_seconds = float(deltas.median())
            if median_seconds > 0.0:
                return float(365.25 * 24 * 60 * 60 / median_seconds)
    return float(trading_days)


def _elapsed_years(result: BacktestResult, trading_days: int) -> float:
    eq = result.equity.dropna()
    if len(eq) < 2:
        return 0.0
    idx = eq.index
    if isinstance(idx, pd.DatetimeIndex):
        elapsed_days = (idx[-1] - idx[0]).total_seconds() / 86_400.0
        if elapsed_days > 0.0:
            return elapsed_days / 365.25
    daily = _equity_daily(result)
    if len(daily) >= 2:
        return len(daily) / float(trading_days)
    return len(eq) / float(trading_days)


# ── return metrics ───────────────────────────────────────────────────────────

def total_return(result: BacktestResult) -> float:
    """Total return as a decimal (0.25 = 25%)."""
    eq = result.equity
    return (eq.iloc[-1] - result.initial_capital) / result.initial_capital


def cagr(result: BacktestResult, trading_days: int = 365) -> float:
    """Compound annual growth rate."""
    eq = result.equity.dropna()
    if len(eq) >= 2 and isinstance(eq.index, pd.DatetimeIndex):
        elapsed_days = (eq.index[-1] - eq.index[0]).total_seconds() / 86_400.0
        if 0.0 < elapsed_days < 1.0:
            return total_return(result)
    years = _elapsed_years(result, trading_days)
    if years <= 0:
        return 0.0
    growth = eq.iloc[-1] / eq.iloc[0]
    if growth <= 0.0:
        return -1.0
    annual_log = np.log(growth) / years
    if annual_log > 50.0:
        return float(np.expm1(50.0))
    if annual_log < -50.0:
        return float(np.expm1(-50.0))
    return float(np.expm1(annual_log))


def sharpe(result: BacktestResult, trading_days: int = 365, risk_free: float = 0.0) -> float:
    periods = _annualization_periods(result, trading_days)
    r  = _returns_for_stats(result) - risk_free / periods
    sd = r.std(ddof=1)
    return (r.mean() / sd) * np.sqrt(periods) if sd > 0 else 0.0


def sortino(result: BacktestResult, trading_days: int = 365, mar: float = 0.0) -> float:
    periods = _annualization_periods(result, trading_days)
    r  = _returns_for_stats(result)
    d  = r[r < mar] - mar
    dd = np.sqrt((d ** 2).mean()) if len(d) > 0 else 0.0
    if dd == 0.0 and r.mean() > mar:
        return np.inf
    return (r.mean() / dd) * np.sqrt(periods) if dd > 0 else 0.0


def calmar(result: BacktestResult, trading_days: int = 365) -> float:
    c   = cagr(result, trading_days)
    mdd = max_drawdown(result)
    return c / mdd if mdd > 0 else 0.0


def omega(result: BacktestResult, threshold: float = 0.0) -> float:
    """Omega ratio (Keating & Shadwick)."""
    r    = _returns_for_stats(result)
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
    r     = _returns_for_stats(result)
    gains = r[r > 0].sum()
    loss  = abs(r[r < 0].sum())
    return gains / loss if loss > 0 else np.inf


def avg_win_loss(result: BacktestResult) -> Tuple[float, float]:
    """(avg_win_pct, avg_loss_pct) in percent."""
    r = _returns_for_stats(result)
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

def compute_performance_metrics(
    *,
    timestamps: Sequence,
    equity: Sequence[float],
    returns: Sequence[float],
    positions,
    symbols: Sequence[str],
    initial_capital: float,
    liquidated: bool = False,
    trading_days: int = 365,
) -> Dict:
    """
    Shared array-first metric contract.

    This intentionally mirrors `full_report()` semantics so lightweight
    prepared/native-event score paths and public `BacktestResultV2` reports use
    one metric implementation.
    """
    idx = pd.DatetimeIndex(timestamps)
    equity_arr = np.asarray(equity, dtype=np.float64)
    returns_arr = np.asarray(returns, dtype=np.float64)
    pos_arr = np.asarray(positions, dtype=np.float64)
    if pos_arr.ndim == 1:
        pos_arr = pos_arr.reshape(-1, 1)
    if len(equity_arr) == 0:
        raise ValueError("equity path cannot be empty")
    if len(returns_arr) != len(equity_arr):
        raise ValueError("returns must have the same length as equity")
    if pos_arr.shape[0] != len(equity_arr):
        raise ValueError("positions must have the same number of rows as equity")

    stats_returns = _array_returns_for_stats(idx, equity_arr, returns_arr)
    annual_periods = _array_annualization_periods(idx, stats_returns, trading_days)
    elapsed_years = _array_elapsed_years(idx, equity_arr, trading_days)
    drawdown = _array_drawdown(equity_arr)
    max_dd = float(np.nanmax(drawdown)) if len(drawdown) else 0.0
    avg_dd = float(np.nanmean(drawdown[drawdown > 0.0])) if np.any(drawdown > 0.0) else 0.0
    max_dd_duration, avg_dd_duration = _array_drawdown_duration_days(idx, equity_arr)

    final_equity = float(equity_arr[-1])
    total_ret = (final_equity - float(initial_capital)) / float(initial_capital)
    cagr_value = _array_cagr(equity_arr, total_ret, elapsed_years)
    sharpe_value = _array_sharpe(stats_returns, annual_periods)
    sortino_value = _array_sortino(stats_returns, annual_periods)
    omega_value = _array_omega(stats_returns)
    pf_value = _array_profit_factor(stats_returns)
    long_hr, short_hr = _array_hitrate(returns_arr, pos_arr)
    avg_win, avg_loss = _array_avg_win_loss(stats_returns)
    hr = (long_hr + short_hr) / 200.0
    expectancy_value = hr * avg_win + (1.0 - hr) * avg_loss

    return {
        "initial_capital": float(initial_capital),
        "final_equity": final_equity,
        "total_return_pct": float(total_ret * 100.0),
        "cagr_pct": float(cagr_value * 100.0),
        "sharpe": float(sharpe_value),
        "sortino": float(sortino_value),
        "calmar": float(cagr_value / max_dd) if max_dd > 0.0 else 0.0,
        "omega": float(omega_value),
        "max_drawdown_pct": float(max_dd * 100.0),
        "avg_drawdown_pct": float(avg_dd * 100.0),
        "max_dd_duration_days": int(max_dd_duration),
        "avg_dd_duration_days": int(avg_dd_duration),
        "profit_factor": float(pf_value),
        "long_hitrate_pct": float(long_hr),
        "short_hitrate_pct": float(short_hr),
        "avg_win_pct": float(avg_win),
        "avg_loss_pct": float(avg_loss),
        "expectancy_pct": float(expectancy_value),
        "num_trades": int(_array_number_of_trades(pos_arr)),
        "liquidated": bool(liquidated),
    }


def _array_finite_returns(values: np.ndarray) -> np.ndarray:
    arr = np.asarray(values, dtype=np.float64)
    return arr[np.isfinite(arr)]


def _array_daily_equity(idx: pd.DatetimeIndex, equity: np.ndarray) -> np.ndarray:
    if len(equity) == 0:
        return np.empty(0, dtype=np.float64)
    if len(idx) != len(equity):
        return np.asarray(equity, dtype=np.float64)
    day_ns = 86_400_000_000_000
    days = idx.view("int64") // day_ns
    if len(days) == 0:
        return np.empty(0, dtype=np.float64)
    change = np.flatnonzero(days[1:] != days[:-1])
    last_idx = np.concatenate((change, np.array([len(days) - 1], dtype=np.int64)))
    return np.asarray(equity, dtype=np.float64)[last_idx]


def _array_returns_for_stats(idx: pd.DatetimeIndex, equity: np.ndarray, returns: np.ndarray) -> np.ndarray:
    daily_equity = _array_daily_equity(idx, equity)
    if len(daily_equity) >= 2:
        base = daily_equity[:-1]
        daily_returns = np.divide(
            daily_equity[1:] - base,
            base,
            out=np.zeros(len(base), dtype=np.float64),
            where=base != 0.0,
        )
        daily_returns = _array_finite_returns(daily_returns)
        if len(daily_returns) > 0:
            return daily_returns
    bar = _array_finite_returns(returns)
    if len(bar) > 0:
        return bar
    if len(equity) < 2:
        return np.zeros(1, dtype=np.float64)
    base = equity[:-1]
    out = np.divide(equity[1:] - base, base, out=np.zeros(len(base), dtype=np.float64), where=base != 0.0)
    return _array_finite_returns(out)


def _array_annualization_periods(idx: pd.DatetimeIndex, stats_returns: np.ndarray, trading_days: int) -> float:
    daily_equity_returns = len(stats_returns) > 0
    if daily_equity_returns and len(idx) >= 2:
        day_ns = 86_400_000_000_000
        if len(np.unique(idx.view("int64") // day_ns)) >= 2:
            return float(trading_days)
    if len(idx) >= 2:
        ns = idx.view("int64")
        deltas = np.diff(ns).astype(np.float64) / 1_000_000_000.0
        deltas = deltas[deltas > 0.0]
        if len(deltas) > 0:
            median_seconds = float(np.median(deltas))
            if median_seconds > 0.0:
                return float(365.25 * 24 * 60 * 60 / median_seconds)
    return float(trading_days)


def _array_elapsed_years(idx: pd.DatetimeIndex, equity: np.ndarray, trading_days: int) -> float:
    if len(equity) < 2:
        return 0.0
    if len(idx) >= 2:
        elapsed_days = (idx[-1] - idx[0]).total_seconds() / 86_400.0
        if elapsed_days > 0.0:
            return float(elapsed_days / 365.25)
    daily_equity = _array_daily_equity(idx, equity)
    if len(daily_equity) >= 2:
        return float(len(daily_equity) / float(trading_days))
    return float(len(equity) / float(trading_days))


def _array_cagr(equity: np.ndarray, total_ret: float, years: float) -> float:
    if len(equity) >= 2 and years > 0.0:
        elapsed_days = years * 365.25
        if 0.0 < elapsed_days < 1.0:
            return float(total_ret)
    if years <= 0.0:
        return 0.0
    growth = float(equity[-1] / equity[0])
    if growth <= 0.0:
        return -1.0
    annual_log = np.log(growth) / years
    if annual_log > 50.0:
        return float(np.expm1(50.0))
    if annual_log < -50.0:
        return float(np.expm1(-50.0))
    return float(np.expm1(annual_log))


def _array_sharpe(r: np.ndarray, periods: float) -> float:
    if len(r) < 2:
        return 0.0
    sd = float(np.std(r, ddof=1))
    return float((np.mean(r) / sd) * np.sqrt(periods)) if sd > 0.0 else 0.0


def _array_sortino(r: np.ndarray, periods: float, mar: float = 0.0) -> float:
    downside = r[r < mar] - mar
    dd = float(np.sqrt(np.mean(downside ** 2))) if len(downside) > 0 else 0.0
    mean = float(np.mean(r)) if len(r) > 0 else 0.0
    if dd == 0.0 and mean > mar:
        return np.inf
    return float((mean / dd) * np.sqrt(periods)) if dd > 0.0 else 0.0


def _array_omega(r: np.ndarray, threshold: float = 0.0) -> float:
    gain = float(np.sum(r[r > threshold] - threshold))
    loss = float(np.sum(threshold - r[r < threshold]))
    return gain / loss if loss > 0.0 else np.inf


def _array_drawdown(equity: np.ndarray) -> np.ndarray:
    peak = np.maximum.accumulate(equity)
    return np.divide(peak - equity, peak, out=np.zeros_like(equity, dtype=np.float64), where=peak != 0.0)


def _array_drawdown_duration_days(idx: pd.DatetimeIndex, equity: np.ndarray) -> Tuple[int, int]:
    daily_equity = _array_daily_equity(idx, equity)
    if len(daily_equity) == 0:
        return 0, 0
    peak = np.maximum.accumulate(daily_equity)
    in_dd = peak != daily_equity
    durations = []
    run = 0
    for value in in_dd:
        if value:
            run += 1
        elif run > 0:
            durations.append(run)
            run = 0
    if run > 0:
        durations.append(run)
    if not durations:
        return 0, 0
    return int(max(durations)), int(np.mean(durations))


def _array_hitrate(returns: np.ndarray, positions: np.ndarray) -> Tuple[float, float]:
    long_hr = []
    short_hr = []
    for col in range(positions.shape[1]):
        pos = positions[:, col]
        long_mask = pos > 0.0
        short_mask = pos < 0.0
        long_total = int(np.sum(long_mask))
        short_total = int(np.sum(short_mask))
        long_wins = int(np.sum((returns > 0.0) & long_mask))
        short_wins = int(np.sum((returns > 0.0) & short_mask))
        long_hr.append(long_wins / long_total * 100.0 if long_total > 0 else 0.0)
        short_hr.append(short_wins / short_total * 100.0 if short_total > 0 else 0.0)
    return float(np.mean(long_hr)), float(np.mean(short_hr))


def _array_number_of_trades(positions: np.ndarray) -> int:
    if positions.size == 0:
        return 0
    total = 0
    for col in range(positions.shape[1]):
        pos = positions[:, col]
        total += 1
        if len(pos) > 1:
            total += int(np.sum(np.diff(pos) != 0.0))
    return int(total)


def _array_profit_factor(r: np.ndarray) -> float:
    gains = float(np.sum(r[r > 0.0]))
    loss = float(abs(np.sum(r[r < 0.0])))
    return gains / loss if loss > 0.0 else np.inf


def _array_avg_win_loss(r: np.ndarray) -> Tuple[float, float]:
    wins = r[r > 0.0]
    losses = r[r < 0.0]
    win = float(np.mean(wins) * 100.0) if len(wins) > 0 else 0.0
    loss = float(np.mean(losses) * 100.0) if len(losses) > 0 else 0.0
    return win, loss

def full_report(result: BacktestResult, trading_days: int = 365) -> Dict:
    """
    Returns an ordered dict of all key metrics.
    Suitable for programmatic use; viz/tearsheet renders it.
    """
    positions = result.positions[[f"Position_{sym}" for sym in result.symbols]].to_numpy(dtype=np.float64)
    return compute_performance_metrics(
        timestamps=result.equity.index,
        equity=result.equity.to_numpy(dtype=np.float64),
        returns=result.returns.to_numpy(dtype=np.float64),
        positions=positions,
        symbols=result.symbols,
        initial_capital=float(result.initial_capital),
        liquidated=bool(result.liquidated),
        trading_days=trading_days,
    )
