# QuantBT

![Python](https://img.shields.io/badge/python-3.11%2B-blue)
[![PyPI](https://img.shields.io/pypi/v/quantbt-engine.svg?label=PyPI)](https://pypi.org/project/quantbt-engine/)
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

QuantBT is published on [PyPI as `quantbt-engine`](https://pypi.org/project/quantbt-engine/).
Install the current public release with `pip install --upgrade quantbt-engine`;
the import remains `from quantbt import QuantBTEndpoint`.

Current portfolio status: `native_portfolio` is the default multi-symbol
backend. It supports long/short, market-neutral, directional, equal-weight,
risk-parity, and beta-neutral portfolio modes, with live-equity sizing and
target exposure contracts. The legacy portfolio route remains available for
historical reproduction.

## Why QuantBT

- One public API for notebooks, services, portfolio research, and validation.
- Native vectorized engines for fast sweeps and large parameter grids.
- Native event-driven engines for market/limit orders, fills, baskets, and
  package execution, with Rust auto-promotion limited to certified workloads.
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

## Event-Driven Quick Start

New event-driven integrations should use the stable facade. Choose an input
mode, a retention profile, and a public backend; the facade keeps matching,
fills, fees, slippage, margin, funding, and PnL in the existing native-event
engine.

```python
from quantbt import QuantBTEndpoint

bt = QuantBTEndpoint.event_driven(
    input_mode="strategy",   # strategy | orders
    profile="research",      # research | optimize | audit
    backend="auto",          # auto | python | rust
    execution_contract="event_lifecycle_v3_next_open",
    initial_capital=20_000,
    leverage=5,
    fee_rate=0.0005,          # one-way fee per fill
    slippage_bps=2.0,
    use_funding=False,
)

result = bt.simulate(data=df, strategy=strategy, symbols=["BTCUSDT"])
bt.show_metrics()
```

Use `profile="research"` for compact notebook results, `"optimize"` for
scalar parameter-search results, and `"audit"` for replay-certified fills and
event artifacts. For an upstream order planner, switch to
`input_mode="orders"` and pass `order_commands=[...]`. The default `auto`
backend follows the release policy; `rust` is an explicit request for the
optional capability-gated native wheel.

An arbitrary `strategy=...` callback remains a Python-authoritative route,
including when `backend="auto"` and a local native wheel is installed. The
current automatic Rust routes are a pre-built static V2/V3 command tape with
at least 10,000 bars, or a bounded `NativeStrategyIR` request with at least
2,000 bars. Inspect `result.metadata["native_event_promotion_v1"]` to see the
resolved backend, threshold, policy rule, and fallback reason for every run.

The compatibility default is the frozen
`event_lifecycle_v2_next_bar_close` behavior. Select
`event_lifecycle_v3_next_open` for real next-open market fills, favorable
limit-gap improvement, adverse stop-gap execution, and conservative flagged
stop-limit ambiguity. V3 requires an `open` column and is parity-tested across
the Python and Rust backends. The machine-readable registry and audit fields
are documented in [Native Event Contract Registry](docs/contracts/contract_registry.md).

The strategy owns signal generation and look-ahead control. QuantBT owns the
causal order lifecycle and accounting. Advanced users can still call
`native_event_strategy(...)` or `native_event_lifecycle(...)` directly when a
custom low-level execution/report combination is required.

See [`docs/endpoint.md`](docs/endpoint.md#stable-event-driven-facade) for the
full strategy protocol, profile matrix, explicit-order example, conflict
rules, and migration guidance. The broader endpoint map is in
[`docs/README.md`](docs/README.md).

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

Latest Phase 49B WFO benchmark (1,000 daily bars, identical seeds, folds,
trials, strategies, account settings, and accounting kernels):

| WFO workload | Phase 49A reference | Phase 49B prepared/scalar | Speedup | Parity |
|---|---:|---:|---:|---|
| Portfolio global, 1 study x 16 trials | 0.386s | 0.330s | 1.17x | exact |
| Single-symbol causal, 6 studies x 16 trials | 4.051s | 1.781s | 2.27x | exact |

Phase 49B prepares aligned WFO fold state once, scores trials directly from
accounting arrays, and compacts completed Optuna ledgers. It does not cache user
strategy signals or alter objectives. The isolated warm peak-RSS difference was
within +/-0.15%, so the result is reported as an RSS plateau rather than a memory
reduction. Reproduce it with
`python benchmarks/run_phase49b_wfo_performance.py --rows 1000 --trials 16`.

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

### Current governed Rust routes and benchmark evidence

Rust is execution-authoritative only where the public request, accounting
contract, installed-wheel parity corpus, and promotion policy have all been
certified. The generated Stage-B policy has this deliberately narrow scope:

| Route | Rust behavior with a matching local companion | Public default elsewhere |
|---|---|---|
| Static V2/V3 `OrderCommand` tape | `auto` at 10,000+ bars | Python |
| Bounded Native Strategy IR, batch, causal-fold scorer | `auto` at 2,000+ bars | Python |
| `run_portfolio_target_market(...)` | explicit Rust helper | no generic endpoint promotion |
| `run_atomic_package_market(...)` | explicit Rust helper | no generic endpoint promotion |
| Python callback/reactive, generic portfolio/basket/arbitrage/options | not promoted | Python |

The bounded Rust strategy IR covers precomputed signal targets, structural
Grid levels, periodic DCA, and fixed bracket/OCO transitions. Python callbacks,
reactive strategies, and generic portfolio/package/arbitrage execution remain
Python compatibility routes by design.

Phase 54B.3 also certifies two intentionally explicit Rust helpers,
`run_portfolio_target_market(...)` and `run_atomic_package_market(...)`, for
linear quote-settled gross-cross `target_units` and one ordered same-bar
all-or-none market package respectively. They do not change generic endpoint
routing or claim venue-native multi-leg execution; the bounded contract,
parity corpus, and benchmark evidence are documented in
[`docs/native_event_rust_full_contract.md`](docs/native_event_rust_full_contract.md).
On the governed 2,000-bar x 8-symbol fixture, their Rust score paths measured
3.594 ms (556,551 bars/s) for target units and 3.512 ms (569,514 bars/s) for
the atomic package, versus Python event-oracle score paths of 33.493 ms and
19.735 ms respectively. These are bounded direct-route measurements; audit
report adaptation is intentionally timed and reported separately.

The local five-repeat public-route evidence below passed exact Python/Rust
canonical-trace and accounting parity before timing. It is deliberately not a
universal Rust speed claim: static public facade time is dominated by common
Python preparation/report adaptation, while typed IR score and shared batch
avoid those per-scenario costs.

| Workload | Bars | Rust median | Rust throughput | Python median | Python throughput |
|---|---:|---:|---:|---:|---:|
| Static public compact | 10,000 | 63.612 ms | 157,203 bars/s | 53.606 ms | 186,545 bars/s |
| Static public audit | 10,000 | 6.024 s | 1,660 bars/s | 5.924 s | 1,688 bars/s |
| Native IR score | 2,000 | 0.741 ms | 2.70M bars/s | 31.565 ms | 63,361 bars/s |
| Native IR batch, 64 scenarios | 128,000 | 11.379 ms | 11.25M bars/s | - | - |
| Native IR causal fold, 64 scenarios | 64,000 | 7.386 ms | 8.67M bars/s | - | - |

The Rust IR score has one boundary call, zero Python callbacks, and no audit
replay. Batch/fold execution has one boundary call and zero prepared-market
copies per scenario; its repeated-run RSS delta was 8-16 KiB on this host. An
audit result is intentionally a cold reporting path: its typed Rust output is
adapted to the normal `BacktestResultV2` without rerunning execution. Full
evidence is in
[`phase54b2/public_routes.md`](benchmarks/native_event/results/phase54b2/public_routes.md)
and the support boundary is in
[`docs/native_strategy_ir.md`](docs/native_strategy_ir.md).

Phase 54B.4 adds an installed-wheel release gate, rather than a new speed
claim. It proves clean core-only fallback, exact core/native-pair handshake,
promotion decisions, and Python/Rust accounting parity for every governed
route. The public `quantbt-engine` wheel remains core-only until a separately
approved native wheel release; see the
[native release handoff](docs/migration/native_release_handoff.md).

### Historical Phase 46F package and dual-backend release evidence

The core distribution is packaged as `quantbt-engine` and imports as
`quantbt`. Its release gate is independent from the optional experimental Rust
wheel:

| Release artifact | Current status | Backend policy |
|---|---|---|
| `quantbt-engine` wheel/sdist | published on PyPI | Python canonical; all existing endpoints remain available |
| `quantbt-native` PyO3 wheel | staged, not published | local Stage-B `auto` only for certified static/IR/batch rows |
| `quantbt-engine[native]` | intentionally empty | no dependency is advertised before native certification |

The committed Phase 46F rerun compares the same prepared static tape and keeps
Python/Rust accounting parity at 100%:

| Workload | Python median | Rust median | Python throughput | Rust throughput | Peak RSS | Parity |
|---|---:|---:|---:|---:|---:|---|
| Low churn, 2,000 bars | 20.33 ms | 0.109 ms | 98,385 bars/s | 18.30M bars/s | 181.97 MB | pass |
| High churn, 2,000 bars | 36.16 ms | 0.140 ms | 55,308 bars/s | 14.33M bars/s | 181.94 MB | pass |
| Prepared RSS reduction | - | - | - | - | -26.1% / -7.6%; absolute budget pass | gate fail |

These are score-kernel measurements, not claims about full facade/report
runtime. The table reports raw median time and bars/second from five warmed
repetitions so the result is readable without an internal speedup convention.
The earlier Phase 45F end-to-end reference is retained in the JSON evidence
for historical comparison. The evidence files are
[`phase46e_release_gate.json`](benchmarks/native_event/phase46e_release_gate.json),
[`phase46f_release_gate.json`](benchmarks/native_event/phase46f_release_gate.json),
[`phase46d1_score_rss.json`](benchmarks/native_event/phase46d1_score_rss.json),
and [`phase45f_release_gate.json`](benchmarks/native_event/phase45f_release_gate.json).

Phase 47C Grid integration evidence uses the external read-only Grid alpha on
the same deterministic 2,000-bar tape in both long-only and long-short modes:

| Mode | Python scalar median | Rust scalar median | Python peak RSS | Rust peak RSS | Fingerprint parity |
|---|---:|---:|---:|---:|---|
| Long-only | 1.138 s | 1.245 s | 265.6 MB | 273.2 MB | pass |
| Long-short | 1.846 s | 1.985 s | 291.1 MB | 293.4 MB | pass |

These are full reactive facade measurements, not pure Rust kernel claims. Rust
is currently slightly slower on this Grid integration but produces the same
command/fill/accounting fingerprint and is explicit fail-fast; `auto` remains
Python. The benchmark runner, five-run RSS slope gate, and scalar/audit
fingerprint contract are documented in
[`docs/grid_native_event_phase47c.md`](docs/grid_native_event_phase47c.md),
with raw JSON under `benchmarks/native_event/results/phase47c/`. The RSS
figures are the current Grid facade evidence; they are not compared directly
to the older ~180 MB core-process profile without a like-for-like baseline.

### Phase 47D Grid optimizer evidence

Phase 47D profiles the real prepared Grid optimizer path by separating alpha
preparation, strategy construction, engine score, and public report work. The
safe patch removes per-bar Grid diagnostics and diagnostic alias columns only
from scalar trials, while public/audit defaults remain unchanged. On the same
2,000-bar deterministic tape:

| Grid mode | Python scalar | Rust scalar | Python throughput | Rust throughput | Peak RSS Python/Rust | Parity |
|---|---:|---:|---:|---:|---:|---|
| Long-only | 0.850 s | 1.086 s | 2,354 bars/s | 1,842 bars/s | 265.4 / 271.2 MB | pass |
| Long-short | 1.412 s | 1.831 s | 1,416 bars/s | 1,092 bars/s | 291.0 / 293.6 MB | pass |

The apples-to-apples prepared scalar profile measured `0.813s` in the local
five-repeat profile. The timing breakdown shows the reactive engine callback
at about `97.9%` and alpha preparation at about `2.2%`, so an indicator cache
was deliberately not added. This evidence does not claim that Rust is faster
for the Python reactive Grid facade; Rust remains explicit experimental and
`auto` remains Python. See
[`docs/grid_native_event_phase47c.md`](docs/grid_native_event_phase47c.md)
for the scalar retention contract, RSS interpretation, and remaining debt.
Raw Phase 47D artifacts are kept under
`benchmarks/native_event/results/phase47d/`.

### Phase 48F final release handoff

The core `quantbt-engine` 1.0.8 artifact gate is now implemented locally and
in the release workflows: exact version/ref validation, wheel and sdist
`twine check`, archive allowlist and secret scan, clean import plus `pip check`,
and a SHA256 release manifest. The TestPyPI workflow is manual and OIDC
protected; it must be run with an unused matching RC version/tag and reviewed
before production PyPI publication. See
[`docs/testpypi_release_checklist.md`](docs/testpypi_release_checklist.md).
`quantbt-native` is intentionally excluded from this core upload, `auto`
remains Python, and explicit Rust remains capability-gated.

### Phase 48C stable event-driven facade evidence

The stable `QuantBTEndpoint.event_driven()` facade was benchmarked on the same
deterministic **2,000-bar** single-symbol baseline as the direct native-event
strategy constructor. Each route ran in a fresh process with five measured
repetitions. The Grid workload is reported separately because indicator
preparation and reactive state-machine work are part of its runtime.

| Common route | Median runtime | Throughput | Peak RSS | Fills | Final Equity | Parity |
|---|---:|---:|---:|---:|---:|---|
| `native_event_strategy` | 161.20 ms | 12,407 bars/s | 184.2 MB | 109 | 19,998.269072 | baseline |
| `event_driven(profile="research")` | 154.54 ms | 12,942 bars/s | 183.4 MB | 109 | 19,998.269072 | pass |

Separate reactive Grid benchmark on 2,000 bars:

| Grid route | Median runtime | Throughput | Peak RSS | Fills | Final Equity | Parity |
|---|---:|---:|---:|---:|---:|---|
| direct `native_event_strategy` | 1.4187 s | 1,410 bars/s | 274.5 MB | 839 | 28,972.788456 | baseline |
| `event_driven(profile="audit")` | 1.3986 s | 1,430 bars/s | 274.5 MB | 839 | 28,972.788456 | pass |

Both comparisons have identical accounting fingerprints, including equity,
positions, fees, funding, margin, lifecycle counters, fills, and liquidation
state. The facade adds no second execution loop; the small runtime difference
is measurement noise and configuration resolution. Reproduce with
`benchmarks/benchmark_phase48c_event_driven.py`; raw evidence is in
[`phase48c_event_driven_facade.md`](benchmarks/phase48c_event_driven_facade.md)
and [`phase48c_event_driven_facade.json`](benchmarks/phase48c_event_driven_facade.json).

The release workflow is documented in
[`docs/release_packaging.md`](docs/release_packaging.md): build and inspect
wheel/sdist, run clean-install and `pip check`, publish an RC to TestPyPI with
OIDC, then publish the final core package through the protected PyPI
environment. The native companion scope, rollback controls, and installed-wheel
certification handoff are in
[`docs/migration/native_release_handoff.md`](docs/migration/native_release_handoff.md).
The exact handoff fields and artifact-hash procedure are in
[`docs/testpypi_release_checklist.md`](docs/testpypi_release_checklist.md).
No long-lived token is required. Native optimization remains an
open, domain-preserving roadmap for portfolio, arbitrage, options, vectorized,
intrabar, and Nautilus adapter workloads; each future route needs its own
parity and RSS certification.

### Pre-48E apples-to-apples native event evidence

The native-event headline below uses one deterministic **2,000-bar**,
single-symbol tape, a fresh process per route, the same compiled command tape,
separate score/audit runs, and seven measured warm repetitions. Runtime is in
seconds, throughput is bars per second, and RSS is peak resident memory. Every
Python/Rust score and audit fingerprint passed accounting and lifecycle parity
(equity, positions, fees, funding, margin, fills, and event counters).

| Workload | Route | Runtime s | Throughput | Peak RSS MB | Parity |
|---|---|---:|---:|---:|---|
| Common low churn | Python score | 0.087736 | 22,796 bars/s | 183.2 | pass |
| Common low churn | Rust score | 0.188448 | 10,613 bars/s | 185.7 | pass |
| Common low churn | Python audit | 0.087327 | 22,902 bars/s | 240.8 | pass |
| Common low churn | Rust audit | 0.176075 | 11,359 bars/s | 243.9 | pass |
| Common high churn | Python score | 0.086609 | 23,092 bars/s | 182.9 | pass |
| Common high churn | Rust score | 0.188299 | 10,621 bars/s | 186.1 | pass |
| Common high churn | Python audit | 0.119269 | 16,769 bars/s | 241.2 | pass |
| Common high churn | Rust audit | 0.198521 | 10,074 bars/s | 243.1 | pass |

The safe Python patch improved the common low-churn score from `0.148483s`
to `0.087736s` on the frozen pre-patch baseline, without skipping any domain
accounting or quantity preflight when constraints are enabled. Explicit order
and Rust full-tape results are also recorded, but they are kept as route-level
evidence rather than used to imply that every reactive strategy is faster in
Rust. Reactive Grid has a separate workload and remains outside this common
native-event headline.

Reproduce the gate with
[`benchmark_pre48e.py`](benchmarks/native_event/benchmark_pre48e.py). Read the
full before/after table and parity fingerprints in
[`pre48e/report.md`](benchmarks/native_event/results/pre48e/report.md); the
raw JSON artifacts are versioned beside it.

### Phase 48E native-event boundary evidence

The Phase 48E rerun keeps the same 2,000-bar tape, seven warm repetitions,
fresh-process routes, separate score/audit profiles, and `atol <= 1e-12`
accounting parity. The full raw result is in
[`phase48e/after.md`](benchmarks/native_event/results/phase48e/after.md).
The common rows are the comparable native-event/event-driven workload; the
explicit rows are a separate compiled-tape workload and must not be read as a
claim that Rust is faster for every Python callback strategy.

| Workload | Route | Runtime s | Throughput | Peak RSS MB | Parity |
|---|---|---:|---:|---:|---|
| Common low churn | Python score | 0.094448 | 21,176 bars/s | 182.0 | pass |
| Common low churn | Rust score | 0.179506 | 11,142 bars/s | 183.9 | pass |
| Common low churn | Python audit | 0.093893 | 21,301 bars/s | 239.0 | pass |
| Common low churn | Rust audit | 0.178550 | 11,201 bars/s | 242.6 | pass |
| Common high churn | Python score | 0.107369 | 18,627 bars/s | 183.5 | pass |
| Common high churn | Rust score | 0.188549 | 10,607 bars/s | 185.2 | pass |
| Common high churn | Python audit | 0.106375 | 18,801 bars/s | 241.1 | pass |
| Common high churn | Rust audit | 0.208654 | 9,585 bars/s | 241.3 | pass |

Phase 48E also reduced the static explicit Rust score to `0.000302s`
(`6,614,704 bars/s`) on the low-churn tape and `0.000392s`
(`5,103,342 bars/s`) on the high-churn tape. Those numbers benefit from the
scalar Rust output contract and prepared command-tape reuse, so they are
reported separately from callback execution. Rust and Python fingerprints,
fees, positions, fills, events, rejection counters, and final equity passed.
At Phase 48E this historical benchmark had `auto` pinned to Python. The later
Phase 54B.2 local Stage-B policy promotes only the certified static/IR/batch
rows documented above; `[native]` remains empty until a public native-wheel
matrix is clean-install certified.

### Phase 48E.1 native production-closure evidence

The Phase 48E.1 rerun uses the same isolated 2,000-bar tape, fresh subprocesses,
seven warm runs, separate score/audit routes, and exact Python/Rust fingerprints.
The complete report is [`phase48e1/after.md`](benchmarks/native_event/results/phase48e1/after.md).
This table separates the explicit prepared-tape path from the generic callback
facade; it is not a universal Rust speed claim.

| Workload | Route | Runtime s | Throughput | Peak RSS MB | Parity |
|---|---|---:|---:|---:|---|
| Common low churn | Python score | 0.085853 | 23,296 bars/s | 182.2 | pass |
| Common low churn | Rust score | 0.218293 | 9,162 bars/s | 185.7 | pass |
| Common low churn | Python audit | 0.095110 | 21,028 bars/s | 239.4 | pass |
| Common low churn | Rust audit | 0.230769 | 8,667 bars/s | 242.1 | pass |
| Common high churn | Python score | 0.091562 | 21,843 bars/s | 182.1 | pass |
| Common high churn | Rust score | 0.222166 | 9,002 bars/s | 185.1 | pass |
| Common high churn | Python audit | 0.104712 | 19,100 bars/s | 239.6 | pass |
| Common high churn | Rust audit | 0.237654 | 8,416 bars/s | 241.4 | pass |
| Explicit low churn | Python score | 0.023777 | 84,114 bars/s | 180.4 | pass |
| Explicit low churn | Rust score | 0.000289 | 6,921,851 bars/s | 181.6 | pass |
| Explicit low churn | Python audit | 0.007385 | 270,814 bars/s | 237.7 | pass |
| Explicit low churn | Rust audit | 0.004357 | 459,060 bars/s | 182.0 | pass |
| Explicit high churn | Python score | 0.021689 | 92,214 bars/s | 180.2 | pass |
| Explicit high churn | Rust score | 0.000366 | 5,461,021 bars/s | 181.9 | pass |
| Explicit high churn | Python audit | 0.013703 | 145,952 bars/s | 239.6 | pass |
| Explicit high churn | Rust audit | 0.006469 | 309,174 bars/s | 183.1 | pass |

Phase 48E.1 also locks typed API 0.4 step results, count-only score sinks,
reusable SoA audit buffers, separate command/lifecycle/fill reports, compact
validated Rust order state, and reset/lifecycle parity. This paragraph records
the historical pre-promotion state; the current Stage-B local policy is the
bounded static/IR/batch policy above. The native extra remains empty until the
CPython 3.11/3.12/3.13 manylinux clean-install workflow passes.

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

Install the released core package:

```bash
pip install --upgrade quantbt-engine
```

Optional optimization, reports, and third-party validation:

```bash
pip install --upgrade "quantbt-engine[optimization,reports,validation]"
```

Walk-forward parameter search specifically requires the `optimization` extra.
Read the [causal WFO guide](docs/walkforward_causal.md) before reporting OOS
metrics from a fold-local schedule.

Development from this repository:

```bash
uv sync --extra optimization --extra reports --extra viz --dev
.venv/bin/python -m pytest -q --ignore=tests/test_real.py --ignore=tests/test_real_endpoints.py --ignore=tests/native_event
```

For core-only package/build validation, use the smaller dependency boundary
used by the native gate:

```bash
uv sync --dev
uv build
uv run twine check dist/*
```

Pool Alpha and notebooks can continue using an editable checkout while a
feature is under development:

```bash
pip install -e /root/bobby/pool_alpha/quantbt
```

For reproducible deployments, pin a published version such as
`pip install quantbt-engine==1.0.9` and keep the unchanged import
`from quantbt import QuantBTEndpoint`.

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

Multi-fold WFO keeps `optimization_schedule="global"` as the compatible
default. Phase 49A also exposes two explicit fold-local schedules:

- `mode_1_decay + per_fold_decay`: one study per fold, with same-fold OOS used
  for final decay candidate selection (`selection_adjusted_oos`);
- `mode_4_is_only_robust + per_fold_causal`: one study per fold, with strict
  IS-only selection before outer OOS execution.
- `mode_1_decay + per_fold_causal`: one outer study per fold, where Mode 1
  decay is measured only on explicit nested inner folds contained in that
  outer IS window; outer OOS remains untouched until parameters are frozen.

Both schedules stitch one continuous target tape and run accounting once with
`fold_boundary_position_policy="carry"`. See the [causal WFO guide]
(docs/walkforward_causal.md), [docs/endpoint.md](docs/endpoint.md), and
[methodology/walk_forward.md](methodology/walk_forward.md) for selection claims,
strictness boundaries, and audit metadata.

Phase 49B keeps this API stable. Endpoint-backed optimization prepares market
and fold state once and uses scalar-only trial reports by default. Audit the
lifecycle through `prepared_wfo_context`, `prepared_scoring_cache`,
`trial_ledger_mode`, and `performance_profile` in walk-forward metadata.
Nested Mode 1 also records `inner_validation`, `inner_fold_table`, and
`chronological_validation_claim` so services can distinguish retrospective,
selection-adjusted, and strict outer-OOS results.

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
| Causal WFO schedules, outer-OOS claims, and audit metadata | [Causal WFO guide](docs/walkforward_causal.md) |
| Walk-forward methodology and anti-leakage scoring | [Walk-forward methodology](docs/walkforward_methodology_vi.md) |
| Opt-in Rust strategy templates, batch scoring, and causal OOS batch folds | [Native strategy IR and batch](docs/native_strategy_ir.md) |
| Python/Rust plan ownership and backend routing | [Execution-plan architecture](docs/architecture/execution-plan.md) |
| Exact staged core/native pair and maturity matrix | [Generated native compatibility](docs/contracts/generated_product_compatibility.md) |
| Build, clean-install, and verify local native wheels | [Native companion installation](docs/native/install.md) |
| Workload-scoped benchmark methodology | [Benchmarking governance](docs/performance/benchmarking.md) |
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
uv sync --extra optimization --extra reports --extra viz --dev
.venv/bin/python -m pytest -q --ignore=tests/test_real.py --ignore=tests/test_real_endpoints.py --ignore=tests/native_event
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
