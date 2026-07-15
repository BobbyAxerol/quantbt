# QuantBT

![Python](https://img.shields.io/badge/python-3.10%2B-blue)
![Numba](https://img.shields.io/badge/core-numba-00A86B)
![Backtesting](https://img.shields.io/badge/backtesting-vectorized%20%7C%20event--driven-black)
![Nautilus](https://img.shields.io/badge/nautilus-optional-6f42c1)
![License](https://img.shields.io/badge/license-MIT-lightgrey)

QuantBT is a transparent, high-speed backtesting toolkit for crypto,
multi-symbol portfolios, systematic alphas, and execution validation.

It gives notebooks and services one stable endpoint over several simulation
layers: fast native vectorized research, native event-driven order/fill
simulation, legacy-compatible portfolio modes, walk-forward optimization, and
optional NautilusTrader validation for third-party execution/accounting checks.

The goal is simple: make alpha research fast enough for iteration, strict
enough for institutional-style review, and readable enough that stakeholders can
audit how a result was produced.

## Why QuantBT

- One public API for notebooks, services, portfolio research, and validation.
- Native vectorized engines for fast sweeps and large parameter grids.
- Native event-driven engines for market/limit orders, fills, baskets, and
  arbitrage package execution.
- Optional NautilusTrader adapter for independent event-driven validation.
- Nautilus explicit order replay for single-symbol `OrderIntent` validation.
- Explicit margin, leverage, fees, slippage, funding, and liquidation handling.
- Stable audit artifacts: metrics, plots, raw reports, trade logs, config JSON,
  run manifest, and optional QuantStats HTML.
- Walk-forward and train/test optimization designed to avoid leaking OOS data
  into parameter selection.

## Engine Stack

| Layer | Backend | Best use case |
|---|---|---|
| Fast research | `native_vectorized` | broad sweeps, signal research, WFO scoring |
| Order simulation | `native_event` | explicit orders, fills, baskets, pair trades |
| Legacy compatibility | `legacy`, `legacy_portfolio` | existing `%_equity`, DCA ladder, portfolio workflows |
| Third-party validation | `nautilus` | smaller high-fidelity event-driven checks |

Use the native engines for research velocity. Use Nautilus when the result needs
an external event-driven accounting layer with raw order, fill, position, and
account reports.

## Features

### Single-Symbol Backtests

- `signal_notional`: fixed units between signal changes.
- `%_equity`: legacy equity-fraction sizing.
- `notional`, `unit`, and target-unit style execution through V2 engines.
- Margin, leverage, fee, slippage, funding, liquidation, and contract size
  controls.
- `use_pyramiding=False` snaps signals to `-1/0/1`; `True` preserves fractional
  scales such as `1.4`.

### DCA And Grid

- Structural DCA ladder signals where `0` is flat, `1` is base order, `2+` are
  safety-order levels.
- High/low intrabar limit-touch detection.
- Fill at trigger/grid price rather than free-market close.
- Designed for DCA ladder and grid strategies where position is a structural
  level, not a continuously rebalanced weight.

### Portfolio And Basket

- Multi-symbol portfolio endpoint over position matrices.
- Portfolio modes: `longshort`, `market_neutral`, `directional`, and
  `equal_weight`.
- Basket and pair-trading endpoint with frozen hedge-ratio units.
- Native event engine support for package-style component orders.

### Arbitrage

Supported executable specs:

- `BasisArbitrageSpec`
- `StatArbPairSpec`
- `CalendarSpreadSpec`
- `FundingArbitrageSpec`
- `SpotPerpCashCarrySpec`
- `IndexBasketArbSpec`

Schema-only specs, reserved for specialized engines:

- `CrossExchangeArbSpec`
- `TriangularArbSpec`
- `OptionsVolArbSpec`

Use `QuantBTEndpoint.arbitrage_support_matrix()` to check safe routes before a
service creates a run.

### Walk-Forward Optimization

- Walk-forward split/stitch engine with OOS-scoped metrics.
- Single train/test split endpoint using the same optimization framework.
- Optuna-supported modes:
  - `mode_1_decay`
  - `mode_2_sbb`
  - `mode_3_flat_minima`
- Endpoint-backed scoring for supported single-symbol modes, so objective
  metrics match the actual QuantBT backtest route.
- Train-only robust candidate selection such as `is_plateau_robust`.
- Optional trade-count penalty to avoid overfit low-trade Sharpe traps.

### Nautilus Validation Reports

The Nautilus adapter can validate single-symbol signal strategies with:

- `signal_notional`
- `notional`
- `unit`
- `%_equity`

It can also replay explicit single-symbol `OrderIntent` orders through
`QuantBTEndpoint.orders(backend="nautilus", ...)` for market, limit,
stop-market, and stop-limit order factory routes where Nautilus supports the
instrument/order combination.

For validation work, `build_native_nautilus_parity_report(native, nautilus)`
creates an audit table comparing requested order quantities, fill prices, fees,
positions, equity, and diffs between native event replay and Nautilus replay.
Use `QuantBTEndpoint.nautilus_support_matrix()` to inspect which Nautilus routes
are supported, experimental, or planned before wiring a service.
Experimental Nautilus package validation is available for
`QuantBTEndpoint.basket(backend="nautilus", ...)` and
`QuantBTEndpoint.portfolio(backend="nautilus", ...)` by compiling strategy
state into explicit order packages.

Supported Binance perpetual validation instruments:

`BTCUSDT-PERP.BINANCE`, `ETHUSDT-PERP.BINANCE`, `BNBUSDT-PERP.BINANCE`,
`SOLUSDT-PERP.BINANCE`, `DOGEUSDT-PERP.BINANCE`, `ARBUSDT-PERP.BINANCE`,
`LINKUSDT-PERP.BINANCE`.

The report bundle exports:

- `account_report.csv`
- `orders_report.csv`
- `fills_report.csv`
- `positions_report.csv`
- `trade_log.csv`
- `fill_log.txt`
- `equity_curve.csv`
- `returns.csv`
- `metrics_summary.json`
- `run_manifest.json`
- `config.json`
- optional `quantstats_daily.html`

These artifacts make the run easier to present to stakeholders: the metrics are
not just a final equity number, but an auditable trail from config to orders,
fills, positions, account state, and performance report.

## Install

Minimal research stack:

```bash
pip install numpy pandas numba matplotlib seaborn
```

Workspace or Poetry environment:

```bash
poetry install
```

Optional validation and reporting:

```bash
poetry add nautilus-trader quantstats
```

## Quick Start

```python
from quantbt import QuantBTEndpoint

bt = QuantBTEndpoint.signal_notional(
    backend="native_vectorized",
    initial_capital=20_000,
    leverage=5,
    alloc_per_trade=10_000,
    fee_rate=0.0002,
    slippage_bps=1.0,
    use_funding=False,
)

result = bt.backtest(
    data=df,                    # OHLCV DataFrame
    signal_col="pos_weight",    # 1.0 / -1.0 / 0.0 style signal
    symbols=["ETHUSDT"],
)

result.show_metrics()
result.quick_plot()
```

## Public Endpoint

```python
QuantBTEndpoint.pct_equity(...)          # legacy % equity sizing
QuantBTEndpoint.signal_notional(...)     # fixed units between signal changes
QuantBTEndpoint.dca_ladder(...)          # DCA/grid structural levels
QuantBTEndpoint.orders(...)              # explicit OrderIntent simulation
QuantBTEndpoint.basket(...)              # pair/basket event simulation
QuantBTEndpoint.arbitrage(...)           # arbitrage spec execution
QuantBTEndpoint.portfolio(...)           # multi-symbol portfolio matrix
QuantBTEndpoint.walk_forward(...)        # walk-forward OOS stitching
QuantBTEndpoint.train_test_split(...)    # single holdout split
QuantBTEndpoint.nautilus_validation(...) # optional Nautilus validation
```

## Nautilus Example

```python
from quantbt import QuantBTEndpoint, export_nautilus_report_bundle
from quantbt.adapters.nautilus import NautilusBackendConfig

bt = QuantBTEndpoint.nautilus_validation(
    initial_capital=20_000,
    leverage=5,
    alloc_per_trade=0.5,
    hedge_type="%_equity",
    fee_rate=0.0005,
    slippage=0.0002,
    use_funding=False,
    use_pyramiding=False,
    nautilus_config=NautilusBackendConfig(
        timeframe="1h",
        starting_balance=20_000,
        trade_notional=0.5,
        close_positions_on_stop=False,
    ),
)

result = bt.simulate(
    data=df,
    signal_col="pos_weight",
    symbols=["ETHUSDT-PERP.BINANCE"],
    show_order_logs=True,
    order_log_mode="fills_only",
    order_log_limit=200,
)

result.show_metrics()

report_dir = export_nautilus_report_bundle(
    result=result,
    output_dir="reports",
    strategy_id="eth_validation",
    make_quantstats=True,
    quantstats_periods_per_year=365,
)
```

## Walk-Forward Example

```python
from quantbt import QuantBTEndpoint

wf = QuantBTEndpoint.train_test_split(
    strategy_class=strategy,
    test_start="2025-01-01",
    target_mode="pct_equity",
    optimization_mode="mode_1_decay",
    optimization_config={
        "scoring_backend": "endpoint",
        "candidate_selection_metric": "is_plateau_robust",
        "top_is_fraction": 0.10,
        "min_trades_per_year": 100,
        "trade_penalty_factor": 0.5,
        "use_numba": True,
    },
    optuna_trials=300,
    random_seed=42,
    initial_capital=20_000,
    leverage=5,
    alloc_per_trade=0.5,
    fee=0.0005,
    slippage=0.0002,
    use_pyramiding=False,
)

result = wf.backtest(data=df, param_ranges=param_ranges)
wf.show_metrics(scope="auto")
```

`scope="auto"` reports only the tested/OOS segment for walk-forward and
train/test runs. Pass `scope="full"` when you need to audit the full stitched
timeline.

## Result Helpers

```python
result.show_metrics()
result.full_report()
result.quick_plot()
result.tearsheet()

bt.order_report
bt.fills_report
bt.export_orders("orders.csv")
bt.export_fills("fills.csv")
```

Example console output:

```text
  Initial Capital   $        20,000
  Final Equity      $    106,884.96
  Total Return            +434.42%
  CAGR                     +33.54%
  Sharpe Ratio               1.981
  Sortino Ratio              0.875
  Calmar Ratio               2.885
  Omega Ratio                2.190
  Max Drawdown              11.63%
  Profit Factor              2.190
  Number of Trades             228
  Liquidated                    No
```

## Documentation

- [Endpoint contract](docs/endpoint.md)
- [Backend selection](docs/backend_selection.md)
- [Vectorized vs event-driven](docs/vectorized_vs_event_driven.md)
- [Margin and leverage](docs/margin_leverage.md)
- [Order fill policies](docs/order_fill_policies.md)
- [Nautilus backend](docs/nautilus_backend.md)
- [Pair and basket guide](docs/pair_basket_guide.md)
- [Walk-forward methodology](docs/walkforward_methodology_vi.md)
- [DCA/grid ladder example](examples/dca_grid_ladder.py)
- [Nautilus validation example](examples/nautilus_validation.py)
- [Nautilus explicit order example](examples/nautilus_explicit_orders.py)

## Development

```bash
PYTHONPATH=/path/to/pool_alpha poetry run pytest -q quantbt/tests
```

Contribution workflow:

- work from `dev` or feature branches;
- keep endpoint contracts stable for notebooks and services;
- add focused tests for every engine or accounting change;
- prefer Numba/vectorized paths for hot loops;
- use Nautilus validation where execution/accounting evidence matters.

## Design Principle

QuantBT is not trying to hide the backtest engine behind a black box. It is
designed so a researcher can move from a signal series to a reproducible audit
trail: parameters, market data alignment, target sizing, order generation,
fills, account reports, equity curve, metrics, and optional third-party
Nautilus validation.

That transparency is the product.
