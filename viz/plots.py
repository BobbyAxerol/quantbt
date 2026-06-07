"""
quantbt.viz.plots
-----------------
Two standalone plot functions that accept a BacktestResult.

quick_plot(result)      Cumulative return + drawdown.  Used by analyze().
tearsheet(result)       Full dashboard: return, drawdown, rolling metrics,
                        monthly heatmap, PnL attribution, position exposure.
"""

from __future__ import annotations

from typing import Optional

import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import matplotlib.gridspec as gridspec
import matplotlib.ticker as ticker
import numpy as np
import pandas as pd
import seaborn as sns

from ..core.types import BacktestResult
from ..metrics.performance import (
    full_report,
    rolling_sharpe,
    rolling_drawdown,
)
from .themes import apply_theme, PALETTE


# ── shared helpers ────────────────────────────────────────────────────────


def _fmt_date(ax, interval_months: int = 3):
    ax.xaxis.set_major_locator(mdates.MonthLocator(interval=interval_months))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    plt.setp(ax.xaxis.get_majorticklabels(), rotation=30, ha="right", fontsize=7)
    ax.tick_params(axis='x', pad=2)

def _annotate_liq(ax, result: BacktestResult, c: dict):
    if result.liquidated and result.liquidation_bar > 0:
        liq_dt = result.equity.index[result.liquidation_bar]
        ax.axvline(liq_dt, color=c["drawdown"], linewidth=1.2, linestyle="--", alpha=0.8)
        ax.text(liq_dt, ax.get_ylim()[1] * 0.95, "  liquidation",
                color=c["drawdown"], fontsize=7, va="top")


# ── quick_plot ────────────────────────────────────────────────────────────────

def quick_plot(
    result:    BacktestResult,
    theme:     str = "dark",
    figsize:   tuple = (14, 6),
    title:     Optional[str] = None,
) -> None:
    """
    Two-panel figure: cumulative return (top) and drawdown (bottom).
    Suitable as a fast sanity-check or inline notebook output.
    """
    c = apply_theme(theme)

    eq  = result.daily_equity
    ret = (eq / eq.iloc[0] - 1) * 100
    dd  = rolling_drawdown(result) * 100      # already daily

    rpt = full_report(result)

    fig, axes = plt.subplots(
        2, 1, figsize=figsize,
        gridspec_kw={"height_ratios": [3, 1], "hspace": 0.04},
        sharex=True,
        facecolor=c["bg"],
    )

    ax_ret, ax_dd = axes

    # ── Return ──
    ax_ret.plot(ret.index, ret.values, color=c["equity"], linewidth=1.8)
    ax_ret.axhline(0, color=c["grid"], linewidth=0.6)
    ax_ret.set_ylabel("Cumulative Return (%)", labelpad=8)
    ax_ret.yaxis.set_major_formatter(ticker.FormatStrFormatter("%.1f%%"))

    # summary label top-right
    label = (
        f"Return {rpt['total_return_pct']:+.1f}%   "
        f"Sharpe {rpt['sharpe']:.2f}   "
        f"MDD {rpt['max_drawdown_pct']:.1f}%"
    )
    ax_ret.set_title(
        title or f"quantbt  |  {result.symbols[0] if len(result.symbols) == 1 else 'Portfolio'}",
        loc="left", fontsize=11, fontweight="normal",
    )
    ax_ret.text(
        0.99, 0.97, label,
        transform=ax_ret.transAxes,
        ha="right", va="top",
        fontsize=8, color=c["text"], alpha=0.85,
    )

    _annotate_liq(ax_ret, result, c)

    # ── Drawdown ──
    ax_dd.fill_between(dd.index, dd.values, 0,
                        color=c["drawdown"], alpha=0.55, linewidth=0)
    ax_dd.plot(dd.index, dd.values, color=c["drawdown"], linewidth=0.8)
    ax_dd.set_ylabel("Drawdown (%)", labelpad=8)
    ax_dd.yaxis.set_major_formatter(ticker.FormatStrFormatter("%.1f%%"))
    ax_dd.invert_yaxis()

    _fmt_date(ax_dd)
    fig.align_ylabels(axes)
    # Thêm dòng này trước plt.show()
    fig.autofmt_xdate(rotation=30, ha='right')
    plt.tight_layout(pad=1.5)
    plt.show()


# ── tearsheet ─────────────────────────────────────────────────────────────────

def tearsheet(
    result:        BacktestResult,
    theme:         str = "dark",
    figsize:       tuple = (16, 20),
    trading_days:  int = 365,
    benchmark:     Optional[pd.Series] = None,
    title:         Optional[str] = None,
) -> None:
    """
    Full performance tearsheet.

    Panels
    ------
    1  Cumulative return (+ optional benchmark)
    2  Underwater drawdown
    3  Rolling 30-day Sharpe
    4  Monthly returns heatmap
    5  Per-symbol PnL contribution
    6  Daily position exposure
    """
    c   = apply_theme(theme)
    rpt = full_report(result, trading_days)

    eq  = result.daily_equity
    ret = (eq / eq.iloc[0] - 1) * 100
    dd  = rolling_drawdown(result) * 100
    rs  = rolling_sharpe(result, window=30, trading_days=trading_days)

    # ── layout ──
    fig = plt.figure(figsize=figsize, facecolor=c["bg"])
    gs  = gridspec.GridSpec(
        6, 2, figure=fig,
        height_ratios=[2.2, 1.0, 1.0, 1.4, 1.4, 1.4],
        hspace=0.45, wspace=0.35,
    )

    # ── 1. cumulative return ──
    ax1 = fig.add_subplot(gs[0, :])
    ax1.plot(ret.index, ret.values, color=c["equity"], linewidth=1.8, label="Strategy")
    if benchmark is not None:
        bm = (benchmark.resample("1D").last().ffill() / benchmark.resample("1D").last().ffill().iloc[0] - 1) * 100
        ax1.plot(bm.index, bm.values, color=c["benchmark"], linewidth=1.2,
                 linestyle="--", label="Benchmark")
    ax1.axhline(0, color=c["grid"], linewidth=0.6)
    ax1.set_ylabel("Cumulative Return (%)")
    ax1.yaxis.set_major_formatter(ticker.FormatStrFormatter("%.1f%%"))
    ax1.legend(loc="upper left")
    _annotate_liq(ax1, result, c)

    # header title
    header = (
        f"Return {rpt['total_return_pct']:+.1f}%   "
        f"CAGR {rpt['cagr_pct']:.1f}%   "
        f"Sharpe {rpt['sharpe']:.2f}   "
        f"Sortino {rpt['sortino']:.2f}   "
        f"Calmar {rpt['calmar']:.2f}   "
        f"MDD {rpt['max_drawdown_pct']:.1f}%"
    )
    ax1.set_title(
        title or "Performance Tearsheet",
        loc="left", fontsize=13, fontweight="normal", pad=12,
    )
    ax1.text(
        0.99, 0.97, header,
        transform=ax1.transAxes,
        ha="right", va="top",
        fontsize=8, color=c["text"], alpha=0.9,
    )

    # ── 2. drawdown ──
    ax2 = fig.add_subplot(gs[1, :], sharex=ax1)
    ax2.fill_between(dd.index, dd.values, 0,
                      color=c["drawdown"], alpha=0.55, linewidth=0)
    ax2.plot(dd.index, dd.values, color=c["drawdown"], linewidth=0.8)
    ax2.set_ylabel("Drawdown (%)")
    ax2.invert_yaxis()
    _annotate_liq(ax2, result, c)

    # ── 3. rolling Sharpe ──
    ax3 = fig.add_subplot(gs[2, :], sharex=ax1)
    ax3.plot(rs.index, rs.values, color=c["neutral"], linewidth=1.4)
    ax3.axhline(0, color=c["grid"], linewidth=0.6)
    ax3.axhline(1, color=c["long"], linewidth=0.6, linestyle="--", alpha=0.6)
    ax3.set_ylabel("Rolling Sharpe (30d)")

    _fmt_date(ax3)

    # ── 4. monthly heatmap ──
    ax4 = fig.add_subplot(gs[3, :])
    _monthly_heatmap(result, ax4, c, trading_days)

    # ── 5. PnL attribution ──
    ax5 = fig.add_subplot(gs[4, :])
    _pnl_attribution(result, ax5, c)

    # ── 6. position exposure ──
    ax6 = fig.add_subplot(gs[5, :], sharex=ax1)
    _position_exposure(result, ax6, c)

    for ax in [ax1, ax2, ax3, ax6]:
        ax.set_xlim(eq.index.min(), eq.index.max())

    fig.align_ylabels([ax1, ax2, ax3, ax6])

    fig.autofmt_xdate(rotation=30, ha='right')
    plt.tight_layout(pad=1.5, rect=[0, 0.02, 1, 1])
    plt.show()


# ── tearsheet sub-panels (private) ───────────────────────────────────────────

def _monthly_heatmap(result: BacktestResult, ax, c: dict, trading_days: int):
    daily = result.daily_equity
    try:
        monthly = daily.resample("ME").last().pct_change().dropna() * 100
    except Exception:
        monthly = daily.resample("M").last().pct_change().dropna() * 100

    years  = sorted(monthly.index.year.unique())
    heat   = pd.DataFrame(0.0, index=years, columns=range(1, 13))
    for idx, val in monthly.items():
        heat.loc[idx.year, idx.month] = val

    vmax = max(abs(heat.values).max(), 1.0)
    sns.heatmap(
        heat, annot=True, fmt=".1f", ax=ax,
        cmap="RdYlGn", center=0, vmin=-vmax, vmax=vmax,
        linewidths=0.4, linecolor=c["border"],
        cbar_kws={"shrink": 0.6, "label": "%"},
        annot_kws={"size": 7},
    )
    ax.set_title("Monthly Returns (%)", loc="left")
    ax.set_xticklabels(
        ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"],
        fontsize=7,
    )
    ax.set_yticklabels(ax.get_yticklabels(), fontsize=7)
    ax.set_xlabel("")
    ax.set_ylabel("")


def _pnl_attribution(result: BacktestResult, ax, c: dict):
    colors = list(PALETTE["dark"].values())[4:]  # cycle through accent colours
    for i, sym in enumerate(result.symbols):
        price_change = result.closes[f"Close_{sym}"].diff().fillna(0)
        prev_pos     = result.positions[f"Position_{sym}"].shift(1).fillna(0)
        contrib      = (prev_pos * price_change).resample("1D").sum().cumsum()
        ax.plot(
            contrib.index, contrib.values,
            label=sym,
            color=colors[i % len(colors)],
            linewidth=1.4,
        )
    ax.axhline(0, color=c["grid"], linewidth=0.6)
    ax.set_ylabel("PnL Contribution")
    ax.legend(loc="upper left", ncol=min(len(result.symbols), 6))
    ax.set_title("Cumulative PnL Contribution per Symbol", loc="left")
    _fmt_date(ax)


def _position_exposure(result: BacktestResult, ax, c: dict):
    colors = list(PALETTE["dark"].values())[4:]
    for i, sym in enumerate(result.symbols):
        pos = result.positions[f"Position_{sym}"].resample("1D").last()
        ax.fill_between(
            pos.index, pos.values, 0,
            where=(pos.values > 0),
            color=c["long"], alpha=0.5,
        )
        ax.fill_between(
            pos.index, pos.values, 0,
            where=(pos.values < 0),
            color=c["short"], alpha=0.5,
        )
    ax.axhline(0, color=c["grid"], linewidth=0.6)
    ax.set_ylabel("Position (units)")
    ax.set_title("Position Exposure", loc="left")
