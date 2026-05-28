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
