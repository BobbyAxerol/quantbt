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
- explicit single-symbol `OrderIntent` replay through
  `QuantBTEndpoint.orders(backend="nautilus", ...)`;
- explicit order types mapped to Nautilus order factory: market, limit,
  stop-market, and stop-limit where the Nautilus route is available;
- explicit order fields preserved where supported: TIF, reduce-only, and tags;
- experimental DCA/grid structured package validation through
  `QuantBTEndpoint.nautilus_dca_grid(...)`;
- experimental bracket/OCO validation through
  `QuantBTEndpoint.nautilus_bracket_orders(...)`, with sibling cancellation
  when a TP/SL exit fills;
- experimental basket/pair package validation through
  `QuantBTEndpoint.basket(backend="nautilus", ...)`;
- experimental multi-symbol portfolio matrix validation through
  `QuantBTEndpoint.portfolio(backend="nautilus", ...)` for pre-scalable modes
  (`signal_notional`, `notional`, `unit`);
- external OHLCV bars through Nautilus `BarDataWrangler`;
- market delta orders to target signal notional for signal-series validation;
- account, orders, fills, and positions reports converted to
  `BacktestResultV2`.

Report bundle:

- `export_nautilus_report_bundle(...)` writes a self-contained evidence folder
  containing raw Nautilus `account_report.csv`, `orders_report.csv`,
  `fills_report.csv`, `positions_report.csv`, normalized `trade_log.csv`,
  `fill_log.txt`, `run_manifest.json`, `metrics_summary.json`,
  `config.json`, equity/returns CSVs, and optional `quantstats_daily.html`.
  `config.json` is auto-filled from endpoint/result run metadata using grouped
  `effective_*` sections for capital, leverage, fees, slippage, sizing,
  funding, instrument, and timeframe. Extra `config={...}` values are saved
  under `annotations`, not mixed into the effective execution settings.
- QuantStats input is daily-resampled from the equity curve by default, which
  is safer for multi-year intraday runs than treating raw 15m returns as daily
  returns. The default annualization is `quantstats_periods_per_year=365` for
  crypto; override it for stocks/futures if needed.
- `fill_log_mode` supports `fills_only`, `order_events`, and `bars_debug`; all
  modes are bounded by `fill_log_limit`.
- Explicit-order runs add `input_mode`, `order_count_input`,
  `cancelled_count`, and `rejected_count` to `run_manifest.json` and
  `metrics_summary.json`.

Parity audit:

- `build_native_nautilus_parity_report(native_result, nautilus_result)` builds
  an order/fill/equity comparison table for explicit-order runs.
- `summarize_native_nautilus_parity_report(...)` returns compact max-diff and
  pass/fail diagnostics for stakeholder review.
- The table includes requested quantity/price, fill price, fee, position after
  fill, equity and diffs.
- Use this report to make native-vs-Nautilus differences visible during
  validation instead of relying only on final equity.

Execution-depth preflight:

- `simulate_nautilus_order_package_depth(...)` is an opt-in deterministic
  preflight layer for package orders before deeper Nautilus simulation.
- It does not replace Nautilus. It validates package-level assumptions that are
  easy to inspect quickly:
  - high/low touch eligibility for limit and stop orders;
  - latency-bar shifting;
  - queue-ahead and volume participation caps;
  - optional partial fills;
  - reduce-only caps to current simulated position;
  - OCO sibling cancellation after the first TP/SL exit fill;
  - all-or-none package rejection for basket/arbitrage groups.
- Existing endpoints do not enable this policy by default.

```python
from quantbt import NautilusExecutionDepthConfig, simulate_nautilus_order_package_depth

preflight = simulate_nautilus_order_package_depth(
    orders=plan.orders,
    data={"BTCUSDT-PERP.BINANCE": df_btc, "ETHUSDT-PERP.BINANCE": df_eth},
    config=NautilusExecutionDepthConfig(
        all_or_none_packages=True,
        allow_partial_fills=True,
        max_participation_rate=0.05,
        queue_ahead_qty=10.0,
        latency_bars=1,
    ),
)

preflight.order_report
preflight.package_report
preflight.orders  # accepted / adjusted orders
```

Not yet in the Nautilus adapter:

- full dynamic DCA ladder state management inside Nautilus;
- exchange-native contingent order-list semantics beyond current package
  strategy cancellation; preflight can audit OCO assumptions, but Phase 5.4B
  still needs deeper Nautilus strategy integration;
- endpoint-wired all-or-none basket package semantics; preflight can already
  reject all legs deterministically before submission;
- portfolio-margin replication beyond diagnostics.

DCA/grid, OCO/bracket, basket, and portfolio Nautilus routes are experimental
validation paths, not the fast research path. Broad research and optimization
should still use native QuantBT engines first, then Nautilus for trustee
execution validation.

Why optional:

- Nautilus provides exchange-like callbacks and an optimized core;
- dependency size and event overhead are not ideal for large optimizer grids;
- native QuantBT remains the default for broad alpha sweeps.

If Nautilus is not installed, `NautilusBacktestEngine.check_available()` raises
a clear `ImportError`.
