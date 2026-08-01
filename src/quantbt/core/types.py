"""
quantbt.core.types
------------------
Shared dataclasses.  BacktestResult is the single output contract used by
metrics, viz, and optimizer modules — nothing downstream imports BacktestEngine.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

import numpy as np
import pandas as pd


@dataclass
class BacktestResult:
    """
    Immutable output of a single backtest run.

    Attributes
    ----------
    equity        Equity curve indexed by DatetimeIndex (UTC).
    returns       Bar-frequency net return series.
    positions     DataFrame, one column per symbol, target units per bar.
    closes        DataFrame, one column per symbol, close prices.
    symbols       Ordered list of symbol names.
    initial_capital
    leverage
    liquidated    True if the account was margin-called.
    liquidation_bar   Integer bar index of liquidation, -1 if none.
    metadata      Arbitrary dict for storing run parameters.
    """

    equity:             pd.Series
    returns:            pd.Series
    positions:          pd.DataFrame
    closes:             pd.DataFrame
    symbols:            List[str]
    initial_capital:    float
    leverage:           float
    liquidated:         bool                    = False
    liquidation_bar:    int                     = -1
    metadata:           Dict                    = field(default_factory=dict)

    # ── computed on first access ──────────────────────────────────────────
    @property
    def drawdown(self) -> pd.Series:
        """Drawdown series as a positive fraction (0 = at peak, 1 = 100% loss)."""
        peak = self.equity.cummax()
        return (peak - self.equity) / peak.replace(0, np.nan)

    @property
    def daily_equity(self) -> pd.Series:
        return self.equity.resample("1D").last().ffill().dropna()

    @property
    def daily_returns(self) -> pd.Series:
        return self.daily_equity.pct_change().dropna()

    def full_report(self, trading_days: int = 365, scope: str = "auto") -> Dict:
        """Return the standard QuantBT metrics dictionary for this result."""
        from .scopes import scoped_result
        from ..metrics.performance import full_report

        return full_report(scoped_result(self, scope=scope), trading_days=trading_days)

    def show_metrics(self, trading_days: int = 365, scope: str = "auto") -> Dict:
        """Print a legacy-style metrics report and return the metrics dict."""
        from ..endpoint import format_metrics_report

        report = self.full_report(trading_days=trading_days, scope=scope)
        print(format_metrics_report(report))
        return report

    def quick_plot(self, theme: str = "dark", figsize: tuple = (14, 6), scope: str = "auto"):
        """Plot cumulative return and drawdown for this result."""
        from ..viz import quick_plot

        return quick_plot(self, theme=theme, figsize=figsize, scope=scope)

    def tearsheet(self, theme: str = "dark", benchmark=None, scope: str = "auto"):
        """Render the QuantBT tearsheet for this result."""
        from ..viz import tearsheet

        return tearsheet(self, theme=theme, benchmark=benchmark, scope=scope)
