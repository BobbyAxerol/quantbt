from __future__ import annotations

from _bootstrap import PROJECT_ROOT  # noqa: F401

import pandas as pd

from quantbt import AccountConfig, BacktestEngineV2


idx = pd.date_range("2024-01-01", periods=5, freq="1h", tz="UTC")
df = pd.DataFrame(
    {
        "open": [100.0, 101.0, 102.0, 101.0, 103.0],
        "high": [101.0, 103.0, 103.0, 104.0, 105.0],
        "low": [99.0, 100.0, 100.5, 100.0, 102.0],
        "close": [101.0, 102.0, 101.0, 103.0, 104.0],
        "volume": [1_000.0, 1_100.0, 1_200.0, 1_300.0, 1_400.0],
    },
    index=idx,
)
signal = pd.Series([0.0, 1.0, 1.0, 0.0, 0.0], index=idx)

engine = BacktestEngineV2(
    data=df,
    signals=signal,
    symbols=["BTCUSDT-PERP.BINANCE"],
    backend="nautilus",
    account=AccountConfig(initial_capital=10_000.0, leverage=10.0),
    alloc_per_trade=1_000.0,
    use_funding=False,
)

print(engine.result.equity.tail())
