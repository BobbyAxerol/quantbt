"""Minimal train/test split example using the walk-forward adapter."""

from __future__ import annotations

from _bootstrap import PROJECT_ROOT  # noqa: F401

import pandas as pd

from quantbt import QuantBTEndpoint


idx = pd.date_range("2023-01-01", periods=120, freq="1D", tz="UTC")
close = pd.Series([100.0 + i * 0.05 + (i % 9) * 0.2 for i in range(len(idx))], index=idx)
data = pd.DataFrame(
    {
        "open": close,
        "high": close + 0.5,
        "low": close - 0.5,
        "close": close,
        "volume": 1_000.0,
    },
    index=idx,
)


def strategy(data, params, train_index, test_index, fold):
    """Return only the test-index signal; the engine handles fold stitching."""
    window = int(params.get("window", 10))
    frame = data.loc[: test_index[-1]]
    signal = (frame["close"] > frame["close"].rolling(window).mean()).astype(float)
    return signal.reindex(test_index).fillna(0.0)


bt = QuantBTEndpoint.train_test_split(
    strategy_class=strategy,
    test_start="2023-04-01",
    target_mode="signal_notional",
    initial_capital=20_000.0,
    leverage=5.0,
    alloc_per_trade=1_000.0,
    fee_rate=0.0,
    use_funding=False,
)

result = bt.backtest(data=data, symbols=["BTC"], params={"window": 10})

result.show_metrics()
print(result.metadata["walk_forward"]["fold_table"])
