from __future__ import annotations

import numpy as np
import pandas as pd

from quantbt.core.results import BacktestResultV2
from quantbt.metrics.performance import full_report


def test_full_report_falls_back_to_bar_returns_when_daily_returns_are_empty():
    idx = pd.date_range("2025-01-01 00:00", periods=1_000, freq="1min", tz="UTC")
    equity = pd.Series(np.linspace(20_000.0, 190_000.0, len(idx)), index=idx, name="equity")
    result = BacktestResultV2(
        equity=equity,
        returns=equity.pct_change().fillna(0.0),
        positions=pd.DataFrame({"Position_ETHUSDT": np.r_[0.0, np.ones(len(idx) - 1)]}, index=idx),
        closes=pd.DataFrame({"Close_ETHUSDT": 100.0}, index=idx),
        symbols=["ETHUSDT"],
        initial_capital=20_000.0,
    )

    report = full_report(result)

    assert len(result.daily_returns) == 0
    assert report["total_return_pct"] == 850.0
    assert report["cagr_pct"] == 850.0
    assert report["sharpe"] > 0.0
    assert report["avg_win_pct"] > 0.0
    assert report["profit_factor"] == np.inf
