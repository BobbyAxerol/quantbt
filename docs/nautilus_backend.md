# Nautilus Backend

The Nautilus adapter is an optional validation backend for smaller, high-fidelity
single-symbol runs. Native QuantBT engines remain the fast research path.

```python
from quantbt import AccountConfig, BacktestEngineV2, export_nautilus_report_bundle

engine = BacktestEngineV2(
    data=df,
    signals=signal,
    symbols=["ETHUSDT-PERP.BINANCE"],
    backend="nautilus",
    hedge_type="signal_notional",
    account=AccountConfig(initial_capital=20_000, leverage=5),
    alloc_per_trade=10_000,
    use_pyramiding=True,
    use_funding=False,
)

result = engine.result
result.show_metrics()

report_dir = export_nautilus_report_bundle(
    result=result,
    output_dir="reports",
    strategy_id="eth_nautilus_validation",
    make_quantstats=True,
    quantstats_periods_per_year=365,
    print_fills=True,
    fill_log_limit=300,
)
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
- sizing modes: `signal_notional`, `notional`, `unit`, and `%_equity`;
- endpoint/engine-level `use_pyramiding`, where `False` snaps raw signals to
  direction only and `True` preserves fractional signal scale;
- external OHLCV bars through Nautilus `BarDataWrangler`;
- market delta orders to target signal notional;
- account, orders, fills, and positions reports converted to
  `BacktestResultV2`.

Report bundle:

- `export_nautilus_report_bundle(...)` writes a self-contained evidence folder
  containing raw Nautilus `account_report.csv`, `orders_report.csv`,
  `fills_report.csv`, `positions_report.csv`, normalized `trade_log.csv`,
  `fill_log.txt`, `run_manifest.json`, `metrics_summary.json`,
  `config.json`, equity/returns CSVs, and optional `quantstats_daily.html`.
  `config.json` is auto-filled from endpoint/result run metadata, including
  capital, leverage, fees, slippage, sizing, funding, instrument, and timeframe.
- QuantStats input is daily-resampled from the equity curve by default, which
  is safer for multi-year intraday runs than treating raw 15m returns as daily
  returns. The default annualization is `quantstats_periods_per_year=365` for
  crypto; override it for stocks/futures if needed.
- `fill_log_mode` supports `fills_only`, `order_events`, and `bars_debug`; all
  modes are bounded by `fill_log_limit`.

Not yet in the Nautilus adapter:

- DCA/grid ladder limit simulation;
- explicit order replay;
- pair/basket trading;
- multi-symbol portfolio validation.

Those workflows should use native QuantBT backends today.

Why optional:

- Nautilus provides exchange-like callbacks and an optimized core;
- dependency size and event overhead are not ideal for large optimizer grids;
- native QuantBT remains the default for broad alpha sweeps.

If Nautilus is not installed, `NautilusBacktestEngine.check_available()` raises
a clear `ImportError`.
