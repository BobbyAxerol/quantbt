# Nautilus Backend

The Nautilus adapter is an optional high-fidelity backend for validation.

```python
from quantbt import AccountConfig, BacktestEngineV2

engine = BacktestEngineV2(
    data=df,
    signals=signal,
    symbols=["BTCUSDT-PERP.BINANCE"],
    backend="nautilus",
    account=AccountConfig(initial_capital=10_000, leverage=10),
    alloc_per_trade=1_000,
)
result = engine.result
```

Current Phase 5 adapter scope:

- single-symbol signal series;
- `BTCUSDT-PERP.BINANCE` test instrument;
- external OHLCV bars through Nautilus `BarDataWrangler`;
- market delta orders to target signal notional;
- account/orders/fills/positions reports converted into `BacktestResultV2`.

Why optional:

- Nautilus provides exchange-like semantics and a Rust/Cython core;
- dependency size and callback overhead are not ideal for large optimizer grids;
- native QuantBT remains the default research path.

If Nautilus is not installed, `NautilusBacktestEngine.check_available()` raises
a clear `ImportError`.
