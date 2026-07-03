from __future__ import annotations

from _bootstrap import PROJECT_ROOT  # noqa: F401

import pandas as pd

from quantbt import AccountConfig, BacktestEngineV2, BasketLegSpec, BasketSpec


idx = pd.date_range("2024-01-01", periods=5, freq="1D", tz="UTC")
base = pd.Series([100.0, 100.0, 105.0, 104.0, 103.0], index=idx)
hedge = pd.Series([50.0, 50.0, 52.0, 51.0, 51.5], index=idx)
signal = pd.Series([0.0, 1.0, 1.0, 0.0, 0.0], index=idx)

basket = BasketSpec(
    basket_id="PAIR-001",
    legs=(
        BasketLegSpec(symbol="BASE", ratio=1.0),
        BasketLegSpec(symbol="HEDGE", ratio=-0.5),
    ),
    gross_notional=10_000.0,
)

engine = BacktestEngineV2(
    backend="native_event",
    basket=basket,
    signal=signal,
    closes={"BASE": base, "HEDGE": hedge},
    highs={"BASE": base, "HEDGE": hedge},
    lows={"BASE": base, "HEDGE": hedge},
    datetime_index=idx,
    account=AccountConfig(initial_capital=100_000.0, leverage=5.0),
    use_funding=False,
)

print(engine.result.equity.tail())
print(engine.result.metadata["basket_target_units"])
