# Nautilus Backend

The Nautilus adapter is an optional validation backend for smaller, high-fidelity
single-symbol runs. Native QuantBT engines remain the fast research path.

```python
from quantbt import AccountConfig, BacktestEngineV2

engine = BacktestEngineV2(
    data=df,
    signals=signal,
    symbols=["ETHUSDT-PERP.BINANCE"],
    backend="nautilus",
    account=AccountConfig(initial_capital=20_000, leverage=5),
    alloc_per_trade=10_000,
    use_funding=False,
)

result = engine.result
result.show_metrics()
```

Supported Binance USDT perpetual validation instruments:

- `BTCUSDT-PERP.BINANCE`
- `ETHUSDT-PERP.BINANCE`
- `BNBUSDT-PERP.BINANCE`
- `SOLUSDT-PERP.BINANCE`
- `DOGEUSDT-PERP.BINANCE`
- `ARBUSDT-PERP.BINANCE`
- `LINKUSDT-PERP.BINANCE`

The adapter also accepts shorthand such as `ETHUSDT`, `SOL`, or `LINK`.
`ARP` is treated as an alias for `ARB`.

Scope:

- single-symbol signal series;
- external OHLCV bars through Nautilus `BarDataWrangler`;
- market delta orders to target signal notional;
- account, orders, fills, and positions reports converted to
  `BacktestResultV2`.

Why optional:

- Nautilus provides exchange-like callbacks and an optimized core;
- dependency size and event overhead are not ideal for large optimizer grids;
- native QuantBT remains the default for broad alpha sweeps.

If Nautilus is not installed, `NautilusBacktestEngine.check_available()` raises
a clear `ImportError`.
