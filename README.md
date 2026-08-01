# QuantBT

![Python](https://img.shields.io/badge/python-3.11%2B-blue)
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

Current portfolio status: `native_portfolio` is the default multi-symbol
backend. It supports long/short, market-neutral, directional, equal-weight,
risk-parity, and beta-neutral portfolio modes, with live-equity sizing and
target exposure contracts. The legacy portfolio route remains available for
historical reproduction.

## Why QuantBT

- One public API for notebooks, services, portfolio research, and validation.
- Native vectorized engines for fast sweeps and large parameter grids.
- Native event-driven engines for market/limit orders, fills, baskets, and
  arbitrage package execution.
- Prepared service contexts for repeated signal/portfolio replays on the same
  market tape without re-normalizing pandas data each run.
- Native portfolio engine with target weights, target notionals, target units,
  gross/net exposure, risk parity, beta neutrality, margin reports, and
  per-symbol attribution.
- Optional NautilusTrader adapter for independent event-driven validation.
- Nautilus explicit order replay for single-symbol `OrderIntent` validation.
- Explicit margin, leverage, fees, slippage, funding, and liquidation handling.
- Stable audit artifacts: metrics, plots, raw reports, trade logs, config JSON,
  run manifest, and optional QuantStats HTML.
- Nautilus certification bundles with parity CSVs, tolerance profiles, known
  differences, and explicit skip/pass status for optional trustee workflows.
- Nautilus package-depth preflight with OHLCV volume caps and synthetic-book
  stress tests for spread, queue, participation, partial-fill, and package
  rejection assumptions.
- Walk-forward and train/test optimization designed to avoid leaking OOS data
  into parameter selection, plus full-sample robust calibration for final
  production parameter discovery.
- Domain-agnostic Optuna optimization adapters for prepared signal, intrabar,
  portfolio, and generic endpoint workflows.

## Performance Philosophy

QuantBT is built for research loops where speed matters as much as accounting
clarity. The public API stays Pythonic, but the heavy computation path is pushed
toward NumPy/Numba kernels so large signal matrices, parameter sweeps,
walk-forward runs, and multi-symbol portfolios can run close to native compiled
performance without forcing researchers into a C++ or C# codebase.

The intent is not to be a black-box replacement for mature execution engines.
LEAN/QuantConnect brings a large C# institutional platform, NautilusTrader
brings a Rust-backed event-driven trading stack, vectorbt is excellent for
vectorized research, and Backtrader remains a widely used Python event-driven
framework. QuantBT sits between those worlds: fast native-vectorized and
Numba-accelerated research paths for iteration, native event simulation for
transparent order accounting, and optional Nautilus validation when a run needs
third-party execution evidence.

Benchmarks are versioned under `benchmarks/` rather than hidden in marketing
claims. Phase 7 currently measures bars x symbols, order count, event count,
warmup/compile time, runtime, memory, throughput, and threshold pass/fail across
native vectorized, native event, portfolio, and optional Nautilus routes. The
rule is simple: keep hot loops near C/C++-style runtime with Numba first, profile
before optimizing, and only consider Cython/C++ when a proven hotspot cannot be
fixed safely in the Python/Numba stack.

Latest Phase 7 standard runtime benchmark after the Phase 11E native portfolio
default switch on this workspace:

| Route | Workload | Runtime | Throughput | Peak Memory | Threshold |
|---|---:|---:|---:|---:|---|
| `native_vectorized` | 25,000 bars x 20 symbols | 0.463s | 1,079,402 bar-symbols/s | 145.3 MB | pass |
| `native_event` | 25,000 explicit orders, cold preparation | 3.041s | 164,442 events/s | 99.4 MB | threshold miss; profiling target |
| `native_event_prepared` | 25,000 explicit orders, prepared replay | 1.621s | 308,545 events/s | 30.4 MB | threshold miss; faster reuse path |
| `portfolio_legacy` | 25,000 bars x 20 symbols | 1.669s | 299,575 bar-symbols/s | 236.3 MB | threshold miss |
| `native_portfolio` | 25,000 bars x 20 symbols | 1.750s | 285,724 bar-symbols/s | 236.1 MB | default; full audit/report route |
| `nautilus` | optional validation route | skipped | - | - | run with `--include-nautilus` |

The portfolio numbers measure the full facade with diagnostics, exposure
reports, per-symbol attribution, contract validation, and equity-aware sizing.
They are intentionally treated as correctness-first default routes; pure kernel
and reporting-layer profiling remains the next speed follow-up before any
Cython/C++ work. See `benchmarks/phase9_optimization_report.md`,
`benchmarks/phase7_profile_report.md`, and
`benchmarks/portfolio_real_parity_report.md` for parity and optimization
history.

Latest Phase 14C service-loop optimization benchmark:

| Workload | Cold / full route | Prepared / minimal route | Speedup | Parity |
|---|---:|---:|---:|---|
| Single-symbol WFO | 1.007s | 0.883s | 1.14x | pass |
| Portfolio WFO | 0.440s | 0.326s | 1.35x | pass |
| Native-event order replay | 0.0096s | 0.0046s | 2.10x | pass |
| Arbitrage package replay | 0.0746s | 0.0663s | 1.13x | pass |
| Native portfolio reports | 0.0410s full | 0.0233s minimal | 1.76x | pass |

Phase 14C added run-local prepared market-array reuse for WFO/service loops and
`report_level="full" | "standard" | "minimal"` for native portfolio reports.
The default remains `full`; lighter report levels are opt-in for optimizers and
services, and parity tests lock core accounting equality before any speed claim.

Latest Phase 16 service-context closure benchmark:

| Workload | Normal endpoint | Prepared context | Speedup | Parity |
|---|---:|---:|---:|---|
| Single-symbol signal_notional replays | 0.0711s | 0.0390s | 1.82x | pass |
| Native portfolio replays | 0.3115s | 0.0695s | 4.48x | pass |
| Native portfolio reports | 0.0755s full | 0.0394s minimal | 1.92x | pass |

Phase 16 adds `endpoint.prepare_service_context(...)`, an opt-in helper for
services that replay many signals or position matrices against one fixed market
tape. Normal `.backtest(...)` remains defensive and backward-compatible.
Cython/C++ remains deferred because the larger benchmark still points to
facade/report overhead rather than pure Numba kernels.

Latest Phase 31 intrabar execution benchmark:

| Route | Workload | Runtime | Throughput | Ratio | Parity |
|---|---:|---:|---:|---:|---|
| `close_target_v2_pure_kernel` | 25,000 bars | 0.0087s | 2,879,313 bars/s | baseline | baseline |
| `intrabar_bracket_v1_minimal` | 25,000 bars, 2,000 fills | 0.0118s | 2,115,865 bars/s | 1.36x close-target | oracle-checked |
| `intrabar_bracket_v1_audit` | 25,000 bars, fill ledger | 0.0527s | 474,427 bars/s | 4.46x minimal | pass |
| `intrabar_session_bracket_v1_minimal` | 25,000 bars, session state | 0.0117s | 2,145,495 bars/s | 0.99x minimal | reference-checked |
| `intrabar_session_bracket_v1_audit` | 25,000 bars, session ledger | 0.0499s | 501,156 bars/s | 4.22x minimal | pass |
| `intrabar_reference_python` | 25,000 bars | 0.2394s | 104,419 bars/s | 20.26x slower than minimal | truth model |
| `fill_replay_v1_kernel` | 25,000 bars, 2,000 fills | 0.0124s | 2,013,664 bars/s | 1.05x minimal | accounting |
| `native_event_explicit_orders_facade` | 25,000 bars, 2,000 market orders | 0.0761s | 328,618 bars/s | 6.44x minimal | speed reference |

Phase 31 adds execution-contract certification for close-target, fast intrabar
SL/TP/trailing, optional session-aware intraday execution state, and explicit
fill replay paths. The fast intrabar kernel is about 20.3x faster than the
readable Python oracle on the committed benchmark; the session kernel keeps the
non-session hot path separate while adding entry windows, EOD force-flat,
per-session quota, stale-signal cancellation, and re-entry suppression.

Latest Phase 32C optimization overhead benchmark:

| Measurement | Result |
|---|---:|
| Optimizer overhead | 0.0174s for 24 trials |
| Optimizer overhead / trial | 0.000723s |
| Prepared signal evaluator | 2.03x faster than normal endpoint replay |
| Intrabar first vs warm run | 3.70x first/warm ratio |
| Parity | pass, final equity diff 0.0 |

Phase 32C consolidates safe walk-forward optimization primitives with the new
domain-agnostic optimizer core while keeping WFO fold isolation and robust
selection semantics inside `walkforward.py`. Read
[`docs/optimization.md`](docs/optimization.md) and
`benchmarks/results/optimization_overhead.md` for signal, intrabar, portfolio,
arbitrage/grid/options fallback examples and benchmark details.

Ecosystem positioning:

| Tool | Core strength | Runtime model | QuantBT role beside it |
|---|---|---|---|
| QuantBT | transparent research, WFO, portfolio, arbitrage, validation endpoints | Python API with NumPy/Numba hot paths | primary alpha research and auditable simulation layer |
| LEAN / QuantConnect | large institutional C# platform and live/research ecosystem | C# engine | external benchmark for platform breadth, but heavier adapter work for custom notebooks |
| NautilusTrader | high-fidelity event-driven execution and accounting | Rust-backed trading stack | optional third-party trustee for execution/account validation |
| vectorbt | very fast vectorized research | NumPy/Numba vectorization | closest research-speed peer; QuantBT adds domain-specific accounting and validation routes |
| Backtrader | classic Python event-driven strategy simulation | Python event loop | useful reference style; QuantBT focuses on faster vectorized/event hybrid workflows |

## Engine Stack

| Layer | Backend | Best use case |
|---|---|---|
| Fast research | `native_vectorized` | broad sweeps, signal research, WFO scoring |
| Order simulation | `native_event` | explicit orders, fills, baskets, pair trades |
| Native portfolio | `native_portfolio` | default multi-symbol portfolio matrix with risk/exposure reports |
| Legacy compatibility | `legacy`, `legacy_portfolio` | historical reproduction and single-symbol legacy routes |
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
- For crypto, `contract_size` is a notional/PnL multiplier. Exchange fractional
  lots are governed by shared venue constraints:
  `qty_step`/`lot_size`/`slot_size`/`min_qty`/`min_notional`, applied across
  native legacy, native vectorized, native event/order, native portfolio, and
  Nautilus validation routes.

### DCA And Grid

- Structural DCA ladder signals where `0` is flat, `1` is base order, `2+` are
  safety-order levels.
- High/low intrabar limit-touch detection.
- Fill at trigger/grid price rather than free-market close.
- Designed for DCA ladder and grid strategies where position is a structural
  level, not a continuously rebalanced weight.

### Portfolio And Basket

- Multi-symbol portfolio endpoint over position matrices. The default backend
  is `native_portfolio`; use `backend="legacy_portfolio"` only for historical
  reproduction.
- Portfolio modes: `longshort`, `market_neutral`, `directional`,
  `equal_weight`, `risk_parity`, and `beta_neutral`.
- Portfolio sizing: `signal_notional`, `%_equity`, `target_weight`,
  `target_notional`, `target_units`, `fixed_notional`, `gross_exposure`, and
  `net_exposure`.
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
  - `mode_4_is_only_robust`
  - `mode_5_full_robust`
- Endpoint-backed scoring for supported single-symbol modes, so objective
  metrics match the actual QuantBT backtest route.
- Train-only robust candidate selection such as `is_plateau_robust` and
  `is_only_robust`.
- Full-sample robust calibration selectors: `full_robust`,
  `full_plateau_robust`, `full_temporal_robust`, and `full_best`.
- Optional trade-count penalty to avoid overfit low-trade Sharpe traps.
- Shared domain-agnostic optimizer primitives for search-space parsing,
  duplicate detection, early stopping, objective helpers, constraints, and
  candidate selection.

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
Experimental Nautilus package validation is available for DCA/grid,
bracket/OCO, basket, and portfolio workflows by compiling strategy state into
explicit order packages.

Package-depth validation is opt-in. `depth_model="ohlcv_volume_cap"` is the
default Level-1 preflight, `depth_model="synthetic_book"` creates deterministic
Level-2 stress books from spread/depth assumptions, and future
`depth_model="l2_replay"` is intentionally gated until real venue snapshots,
incremental updates, and trade prints are provided.

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
QuantBTEndpoint.nautilus_dca_grid(...)   # Nautilus DCA/grid package validation
QuantBTEndpoint.nautilus_bracket_orders(...) # Nautilus bracket/OCO validation
QuantBTEndpoint.basket(...)              # pair/basket event simulation
QuantBTEndpoint.arbitrage(...)           # arbitrage spec execution
QuantBTEndpoint.portfolio(...)           # multi-symbol portfolio matrix
QuantBTEndpoint.walk_forward(...)        # walk-forward OOS stitching
QuantBTEndpoint.train_test_split(...)    # single holdout split
QuantBTEndpoint.nautilus_validation(...) # optional Nautilus validation
```

The native portfolio parity audit is stored at
`benchmarks/portfolio_real_parity_report.md`.

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

diag = bt.nautilus_pct_equity_diagnostic(
    data=df,
    signal_col="pos_weight",
    native_fee_round_trip=0.0005,
    native_use_funding=False,
    native_slippage=0.0002,
)

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

Start with the [documentation map](docs/README.md) if you are deciding which
backend, endpoint, or strategy route to use.

| Need | Read |
|---|---|
| Public API contract for notebooks/services | [Endpoint contract](docs/endpoint.md) |
| Backend choice by strategy type | [Backend selection](docs/backend_selection.md) |
| Speed vs execution-fidelity tradeoff | [Vectorized vs event-driven](docs/vectorized_vs_event_driven.md) |
| Leverage, buying power, margin, liquidation | [Margin and leverage](docs/margin_leverage.md) |
| Market/limit/stop fill behavior | [Order fill policies](docs/order_fill_policies.md) |
| Nautilus validation and report bundles | [Nautilus backend](docs/nautilus_backend.md) |
| Pair, basket, hedge-ratio package behavior | [Pair and basket guide](docs/pair_basket_guide.md) |
| Walk-forward methodology and anti-leakage scoring | [Walk-forward methodology](docs/walkforward_methodology_vi.md) |
| Runnable smoke templates | [Examples index](examples/README.md) |

Key examples:

- [DCA/grid ladder](examples/dca_grid_ladder.py)
- [Multi-symbol portfolio](examples/multi_symbol_portfolio.py)
- [Pair/basket event package](examples/pair_basket_event.py)
- [Basis arbitrage](examples/arbitrage_basis.py)
- [Walk-forward train/test split](examples/walk_forward_train_test.py)
- [Nautilus validation](examples/nautilus_validation.py)
- [Nautilus explicit orders](examples/nautilus_explicit_orders.py)

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
