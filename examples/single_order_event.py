from __future__ import annotations

from _bootstrap import PROJECT_ROOT  # noqa: F401

import pandas as pd

from quantbt import AccountConfig, EventDrivenBacktestEngine, OrderIntent, OrderSide, OrderType, TimeInForce


idx = pd.date_range("2024-01-01", periods=4, freq="1D", tz="UTC")
df = pd.DataFrame(
    {
        "open": [100.0, 100.0, 110.0, 120.0],
        "high": [100.0, 101.0, 112.0, 121.0],
        "low": [100.0, 99.0, 94.0, 119.0],
        "close": [100.0, 100.0, 110.0, 120.0],
        "volume": [1_000.0, 1_100.0, 1_200.0, 1_300.0],
    },
    index=idx,
)

order = OrderIntent(
    timestamp=idx[1],
    symbol="BTC",
    side=OrderSide.BUY,
    order_type=OrderType.LIMIT,
    qty=10.0,
    price=99.0,
    tif=TimeInForce.GTC,
)

engine = EventDrivenBacktestEngine(
    data=df,
    symbols=["BTC"],
    orders=[order],
    account=AccountConfig(initial_capital=10_000.0, leverage=10.0),
    use_funding=False,
)

print(engine.result.equity.tail())
print(engine.result.metadata["order_report"])
