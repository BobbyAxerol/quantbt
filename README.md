# QuantBT

[![PyPI](https://img.shields.io/pypi/v/quantbt-engine.svg?label=quantbt-engine)](https://pypi.org/project/quantbt-engine/)
[![Python](https://img.shields.io/pypi/pyversions/quantbt-engine.svg)](https://pypi.org/project/quantbt-engine/)
[![CI](https://github.com/BobbyAxerol/quantbt/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/BobbyAxerol/quantbt/actions/workflows/ci.yml)
[![Native](https://img.shields.io/badge/Rust-PyO3-orange)](https://pypi.org/project/quantbt-native/)
[![License](https://img.shields.io/badge/license-MIT-lightgrey)](LICENSE)

QuantBT is a transparent backtesting engine for systematic research,
event-driven execution, multi-symbol portfolios, arbitrage, options, and
walk-forward validation.

The public API stays Pythonic. NumPy and Numba power portable research paths,
while a governed Rust/PyO3 companion accelerates certified event workloads.
Every backend returns the same result surface for metrics, plots, reports, and
audit metadata.

```python
from quantbt import QuantBTEndpoint
```

## Install

```bash
pip install --upgrade quantbt-engine
# or
poetry add quantbt-engine
```

The distribution name is **`quantbt-engine`**; the import name is
**`quantbt`**.

On Linux x86_64 with glibc and CPython 3.11-3.13, installation also resolves
the exact pre-built **`quantbt-native`** companion. Users do not need Cargo,
Rust, Maturin, a second import, or a different endpoint. Unsupported platforms
retain the complete Python/Numba API.

Release pair:

| Distribution | Version | Purpose |
|---|---:|---|
| `quantbt-engine` | `1.1.0` | Public API, Python/Numba engines, reports, compatibility oracle |
| `quantbt-native` | `0.4.1` | Internal PyO3 extension for certified Rust workloads |

Optional features:

```bash
pip install "quantbt-engine[optimization,viz,reports]"
pip install "quantbt-engine[validation]"  # NautilusTrader, Python 3.12+
```

Walk-forward parameter search requires the `optimization` extra.

Verify the installed pair:

```python
from importlib.metadata import PackageNotFoundError, version

print("core:", version("quantbt-engine"))
try:
    print("native:", version("quantbt-native"))
except PackageNotFoundError:
    print("native: unavailable; Python/Numba fallback is active")
```

Read the [native installation matrix](docs/native/install.md) for supported
platforms, backend controls, and troubleshooting.

## Quick Start

```python
from quantbt import QuantBTEndpoint

bt = QuantBTEndpoint.signal_notional(
    initial_capital=20_000,
    leverage=5,
    alloc_per_trade=10_000,
    fee_rate=0.0005,   # canonical one-way fee per fill
    slippage_bps=1.0,
    use_funding=False,
)

result = bt.backtest(
    data=df,                    # DatetimeIndex + OHLCV
    signal_col="pos_weight",   # target signal, e.g. -1.0 / 0.0 / 1.0
    symbols=["ETHUSDT"],
)

result.show_metrics()
result.quick_plot()  # requires: pip install "quantbt-engine[viz]"
```

`initial_capital` is equity/initial margin. Leverage defines buying power;
it does not multiply `alloc_per_trade`. `fee_rate` is always one-way. Legacy
`fee` remains accepted and is converted at the compatibility boundary.

## Choose An Endpoint

`QuantBTEndpoint` is the stable integration surface for notebooks and
services. Pick the route from the behavior the strategy needs, not from the
implementation language.

| Research need | Factory | Primary input | Default execution authority |
|---|---|---|---|
| Equity-relative single-symbol signals | `pct_equity(...)` | signal series | legacy-compatible Python |
| Fast fixed-notional signals | `signal_notional(...)` | signal series | native vectorized / Numba |
| Causal SL/TP/trailing | `intrabar_bracket(...)` | intent tape or columns | native intrabar / Numba |
| Stateful event strategy | `event_driven(input_mode="strategy")` | strategy protocol | Python callback engine |
| Canonical command tape | `event_driven(input_mode="orders")` | `OrderCommand` tape | auto: certified Rust or Python |
| Legacy explicit orders | `orders(...)` | `OrderIntent` list | native event |
| Structural DCA/grid levels | `dca_ladder(...)` | ladder signal + OHLC | compatibility engine |
| Multi-symbol portfolio | `portfolio(...)` | target matrix | native portfolio / Numba |
| Pair or basket package | `basket(...)` | `BasketSpec` | native event package |
| Basis, stat-arb, carry, funding | `arbitrage(...)` | arbitrage spec | native event package |
| Option strategy/package | `options(...)` | option spec + market data | native option engine |
| Walk-forward optimization | `walk_forward(...)` | strategy + parameter space | WFO orchestration |
| One train/test holdout | `train_test_split(...)` | strategy + parameter space | WFO scoring stack |
| Third-party execution validation | `nautilus_validation(...)` | signal/data | NautilusTrader |

The full parameter, data, result, and support contracts are in the
[endpoint guide](docs/endpoint.md). For a decision tree, read
[backend selection](docs/backend_selection.md).

## Event-Driven Facade

New order-sensitive integrations should use `event_driven(...)`. Its three
profiles change result retention, not fill or accounting semantics.

```python
bt = QuantBTEndpoint.event_driven(
    input_mode="strategy",          # strategy | orders
    profile="research",             # research | optimize | audit
    backend="auto",                 # auto | python | rust
    execution_contract="event_lifecycle_v3_next_open",
    initial_capital=20_000,
    leverage=5,
    fee_rate=0.0005,
    slippage_bps=2.0,
)

result = bt.simulate(
    data=df,
    strategy=strategy,
    symbols=["BTCUSDT"],
)
```

| Profile | Intended use | Retained output |
|---|---|---|
| `optimize` | high-volume scoring | scalar score and compact accounting |
| `research` | normal notebook/service run | equity, fills, metrics, compact metadata |
| `audit` | certification and investigation | lifecycle trace, order/fill ledgers, full diagnostics |

An arbitrary Python callback remains Python-authoritative. Rust promotion is
reserved for typed, callback-free workloads whose capability handshake,
contract fingerprint, scale threshold, and parity gate all pass. Inspect
`result.metadata["native_event_backend_resolved"]` for the selected backend
and `result.metadata["native_event_promotion_v1"]` for the policy reason.

## Canonical Multi-Symbol Market V2

For an exact, reusable multi-symbol clock, prepare market data and venue rules
once before running a static command tape. `exact` rejects equal-length but
shifted source timestamps; it never relabels values by row count. The prepared
route owns one immutable UTC clock, explicit observation flags, and one
instrument registry for quantity, multiplier, leverage, and one-way fee rules.

```python
from quantbt import PreparedMarketCacheV2, QuantBTEndpoint

cache = PreparedMarketCacheV2(max_entries=4)
market = QuantBTEndpoint.prepare_market(
    {"BTCUSDT": btc, "ETHUSDT": eth},
    calendar_policy="exact",       # exact | intersection | union | primary_clock
    cache=cache,
)
instruments = QuantBTEndpoint.prepare_instruments(
    symbols=market.symbols,
    contract_size={"BTCUSDT": 1.0, "ETHUSDT": 1.0},
    leverage={"BTCUSDT": 3.0, "ETHUSDT": 2.0},
    fee_rate=0.0005,
)

bt = QuantBTEndpoint.event_driven(input_mode="orders", backend="auto")
result = bt.backtest(
    data=None,
    order_commands=commands,
    symbols=list(market.symbols),
    prepared_market=market,
    prepared_instruments=instruments,
)
```

The current V1.1 static event, bounded target, and atomic package adapters
consume this contract. `union`/`primary_clock` data with missing observations
is retained faithfully but fails closed when lowered to a current OHLC kernel;
it is never fabricated through generic forward-fill. Legacy endpoints remain
available for historical reproduction. Read the [market/calendar contract](docs/contracts/v1_1_market_calendar_v2.md)
and [instrument registry contract](docs/contracts/v1_1_instrument_registry_v2.md)
before certifying a multi-symbol run.

## Rust Acceleration

Rust is an execution implementation behind the normal endpoint, not a second
user-facing API. `backend="auto"` is correctness-first: it promotes only
governed rows and otherwise records a structured Python fallback.

Current automatic Rust scope:

- static V2/V3 command tapes with at least 10,000 bars;
- bounded Native Strategy IR score/audit requests with at least 2,000 bars;
- Native Strategy IR batch and causal-fold scoring.

Current explicit-only Rust scope:

- linear quote-settled `target_units` portfolio market execution;
- one ordered, same-bar, all-or-none atomic market package.

Python remains authoritative for arbitrary callbacks, reactive strategies,
generic portfolio/basket/arbitrage/options routes, complex cross-margin, and
dynamic strategy state outside the bounded IR. See the generated
[compatibility matrix](docs/contracts/generated_product_compatibility.md).

### Release Benchmark

The table below reports committed warm-median evidence for the governed
`1.1.0` / `0.4.1` pair. Accounting and canonical-trace parity pass before any
timing is accepted.

| Workload | Fixture | Rust median | Rust throughput | Python oracle | Relative speed | Parity |
|---|---:|---:|---:|---:|---:|---|
| Native Strategy IR score | 2,000 bars | 0.741 ms | 2.70M bars/s | 31.565 ms | 42.6x | exact trace/accounting |
| Native Strategy IR batch | 64 x 2,000 bars | 11.379 ms | 11.25M bars/s | n/a | shared batch | exact serial/batch |
| Causal-fold batch | 64,000 bars | 7.386 ms | 8.67M bars/s | n/a | shared batch | exact fold isolation |
| Portfolio `target_units` score | 2,000 bars x 8 symbols | 3.594 ms | 556,551 bars/s | 33.493 ms | 9.3x | exact, `atol=1e-12` |
| Atomic package score | 2,000 bars x 8 symbols | 3.512 ms | 569,514 bars/s | 19.735 ms | 5.6x | exact, `atol=1e-12` |

The fastest paths make one Python-to-Rust call, create no Python callbacks,
and do not construct audit rows during scoring. Audit reports are adapted from
typed Rust buffers on the cold path without replaying execution.

These are workload-scoped measurements, not a universal claim against another
framework or every QuantBT endpoint. For example, the 10,000-bar static compact
facade measured 63.612 ms in Rust versus 53.606 ms in Python because common
preparation and report adaptation dominate that sparse fixture. The speed gain
is strongest for typed score, batch, portfolio-target, and package hot paths.

Evidence:

- [public Rust route benchmark](benchmarks/native_event/results/phase54b2/public_routes.md)
- [public route JSON](benchmarks/native_event/results/phase54b2/public_routes.json)
- [portfolio/package JSON](benchmarks/native_event/results/phase54b3/portfolio_package.json)
- [benchmark governance](docs/performance/benchmarking.md)

## Core Capabilities

- Market, limit, stop-market, stop-limit, cancel, amend, replace, reduce-only,
  GTC/GTD/IOC/FOK, parent-child, and OCO lifecycle contracts.
- Fees, slippage, funding, leverage, margin, liquidation, quantity steps,
  minimum quantity, and minimum notional constraints.
- Target weight, target notional, target units, risk parity, beta neutrality,
  gross/net exposure limits, and per-symbol attribution.
- Basis, calendar spread, funding, stat-arb pair, spot-perp carry, and index
  basket specifications.
- Linear and inverse option contracts, multi-leg spreads, covered calls,
  delta-hedged options, and gamma-scalping adapters.
- Five WFO optimization modes, strict fold-local causal schedules, train/test
  holdouts, Optuna integration, prepared scoring, and selection audit metadata.
- Optional NautilusTrader execution validation and stakeholder report bundles.

Capabilities are contract-scoped. A supported schema is not automatically a
claim of venue-native microstructure, L2 queue priority, or cross-margin parity.

## Results And Audit

All public routes converge on a stable result surface:

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

Depending on the route/profile, metadata includes execution contracts,
backend promotion decisions, data signatures, fold tables, selected trials,
order lifecycle events, funding/margin diagnostics, and parity artifacts.

For WFO and train/test endpoints, `scope="auto"` reports only the tested/OOS
window. Use `scope="full"` for the complete stitched timeline.

## Documentation

Start with the [documentation map](docs/README.md).

| Topic | Guide |
|---|---|
| Public factories, parameters, data, and results | [Endpoint contract](docs/endpoint.md) |
| Choose vectorized, intrabar, event, portfolio, or Nautilus | [Backend selection](docs/backend_selection.md) |
| Install and verify the Rust companion | [Native installation](docs/native/install.md) |
| Exact Rust maturity and promotion scope | [Native capabilities](docs/native/capabilities.md) |
| Execution timing and fill semantics | [Execution contracts](docs/execution_contracts.md) |
| Margin, buying power, and liquidation | [Margin and leverage](docs/margin_leverage.md) |
| Causal WFO schedules and claims | [Causal walk-forward](docs/walkforward_causal.md) |
| WFO methodology | [Walk-forward methodology](methodology/walk_forward.md) |
| Portfolio modes and migration | [Portfolio Engine V3](docs/portfolio_engine_v3.md) |
| Pair and basket packages | [Pair and basket guide](docs/pair_basket_guide.md) |
| Nautilus validation and bundles | [Nautilus backend](docs/nautilus_backend.md) |
| Reproduce benchmark evidence | [Benchmarking governance](docs/performance/benchmarking.md) |
| Runnable examples | [Examples](examples/README.md) |

## Development

```bash
uv sync --extra optimization --extra reports --extra viz --dev
.venv/bin/python -m pytest -q \
  --ignore=tests/test_real.py \
  --ignore=tests/test_real_endpoints.py \
  --ignore=tests/native_event
```

Work on `dev` or a feature branch. Preserve public endpoint compatibility,
lock accounting changes with focused parity tests, and publish benchmark claims
only with committed reproducible evidence. See [CONTRIBUTING.md](CONTRIBUTING.md).

## Design Principle

QuantBT does not treat final equity as sufficient evidence. A trusted run must
be traceable from market data and parameters through targets, orders, fills,
costs, account state, equity, metrics, and backend selection.

Transparency is part of the execution contract.
