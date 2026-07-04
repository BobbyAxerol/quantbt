from __future__ import annotations

from _bootstrap import PROJECT_ROOT  # noqa: F401

import pandas as pd

from quantbt import QuantBTEndpoint
from quantbt.adapters.nautilus import NautilusBackendConfig


idx = pd.date_range("2024-01-01", periods=48, freq="1h", tz="UTC")
close = pd.Series([100.0 + (i % 7) for i in range(len(idx))], index=idx)
df = pd.DataFrame(
    {
        "open": close,
        "high": close + 1.0,
        "low": close - 1.0,
        "close": close,
        "volume": 1_000.0,
        "pos_weight": [0.0] * 5 + [1.0] * 20 + [0.0] * 23,
    },
    index=idx,
)

bt = QuantBTEndpoint.nautilus_validation(
    initial_capital=20_000,
    leverage=5,
    alloc_per_trade=10_000,
    use_pyramiding=True,
    fee_rate=0.0002,
    use_funding=False,
    nautilus_config=NautilusBackendConfig(
        timeframe="1h",
        starting_balance=20_000,
        trade_notional=10_000,
        close_positions_on_stop=False,
    ),
)

result = bt.simulate(
    data=df,
    signal_col="pos_weight",
    symbols=["ETHUSDT-PERP.BINANCE"],
)

result.show_metrics()
print(bt.fills_report.tail())
