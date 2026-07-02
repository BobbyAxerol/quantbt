from __future__ import annotations

from _bootstrap import PROJECT_ROOT  # noqa: F401

import pandas as pd

from quantbt import BacktestEngine


idx = pd.date_range("2024-01-01", periods=6, freq="1D", tz="UTC")
close = pd.Series([100.0, 100.0, 98.0, 96.0, 103.0, 104.0], index=idx)
high = pd.Series([101.0, 100.5, 99.0, 97.0, 104.0, 105.0], index=idx)
low = pd.Series([99.0, 98.5, 96.5, 94.0, 101.0, 103.0], index=idx)
level = pd.Series([0, 3, 3, 3, 0, 0], index=idx)

bt = BacktestEngine(
    Datetime=idx,
    Position=level,
    Close=close,
    High=high,
    Low=low,
    hedge_type="dca_ladder",
    initial_capital=20_000.0,
    leverage=5.0,
    alloc_per_trade=1_000.0,
    dca_step_pct=0.01,
    dca_step_scale=1.0,
    dca_volume_scale=1.5,
    dca_max_safety_orders=2,
    dca_take_profit_pct=0.0,
)

print(bt.result.equity.tail())
print(bt.result.metadata["dca_actual_level"].tail())
