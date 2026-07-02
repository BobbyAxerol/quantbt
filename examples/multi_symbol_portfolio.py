from __future__ import annotations

from _bootstrap import PROJECT_ROOT  # noqa: F401

import pandas as pd

from quantbt import AccountConfig, PortfolioBacktestEngine


idx = pd.date_range("2024-01-01", periods=5, freq="1D", tz="UTC")
btc = pd.Series([100.0, 101.0, 103.0, 102.0, 104.0], index=idx)
eth = pd.Series([10.0, 10.2, 10.1, 10.4, 10.3], index=idx)

positions = {
    "BTC": pd.Series([0.0, 1.0, 1.0, 0.0, 0.0], index=idx),
    "ETH": pd.Series([0.0, -1.0, -1.0, 0.0, 0.0], index=idx),
}

engine = PortfolioBacktestEngine(
    positions=positions,
    closes={"BTC": btc, "ETH": eth},
    datetime_index=idx,
    mode="market_neutral",
    account=AccountConfig(initial_capital=100_000.0, leverage=5.0),
    alloc_per_trade={"BTC": 50_000.0, "ETH": 50_000.0},
    use_funding=False,
)

print(engine.result.equity.tail())
