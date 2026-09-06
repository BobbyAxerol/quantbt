# QuantBT Documentation Map

Use this page as the first stop when deciding which QuantBT document to read.

## Package At A Glance

| Public surface | Contract |
|---|---|
| Install | `pip install quantbt-engine` or `poetry add quantbt-engine` |
| Import | `from quantbt import QuantBTEndpoint` |
| Core release | `quantbt-engine==1.1.0` |
| Native companion | `quantbt-native==0.4.1`, installed automatically on supported Linux x86_64 CPython 3.11-3.13 |
| Native policy | Python auto-routing until fresh route evidence; explicit Rust for certified bounded workloads |

The companion is an internal implementation package. Users do not import it
or choose a second public API. Start with [Native installation](native/install.md)
to verify the pair and [Endpoint contract](endpoint.md) to select a route.

## Start Here

| Need | Read |
|---|---|
| Install the package and understand the core/native pair | [Native companion installation](native/install.md) |
| Choose the right backend | [Backend selection](backend_selection.md) |
| Call QuantBT from notebooks/services | [Endpoint contract](endpoint.md) |
| Choose the correct execution timing contract | [Execution contracts](execution_contracts.md) |
| Migrate SL/TP/trailing alphas to the fast intrabar route | [Fast intrabar](fast_intrabar.md) |
| Run the explicit Rust bounded intrabar authority and inspect its trace contract | [Fast intrabar](fast_intrabar.md#explicit-rust-intrabar-authority) |
| Audit alpha source files before certification | [Alpha certification](alpha_certification.md) |
| Understand vectorized vs event-driven tradeoffs | [Vectorized vs event-driven](vectorized_vs_event_driven.md) |
| Validate leverage, buying power, liquidation, funding | [Margin and leverage](margin_leverage.md) |
| Understand market/limit/stop fill behavior | [Order fill policies](order_fill_policies.md) |
| Build pair trades or baskets | [Pair and basket guide](pair_basket_guide.md) |
| Understand Portfolio Engine V3 roadmap | [Portfolio Engine V3](portfolio_engine_v3.md) |
| Use Nautilus as third-party execution validation, reports, and depth preflight | [Nautilus backend](nautilus_backend.md) |
| Choose a strict causal WFO schedule and read its audit metadata | [Causal walk-forward guide](walkforward_causal.md) |
| Understand WFO parameter selection methodology | [Walk-forward methodology](walkforward_methodology_vi.md) |
| Tune params across signal, intrabar, portfolio, and generic endpoints | [Domain-agnostic optimization](optimization.md) |
| Package, release, or install QuantBT in Pool Alpha | [Packaging and release](release_packaging.md) |
| Publish the governed native/core pair or inspect a TestPyPI proof | [TestPyPI release checklist](testpypi_release_checklist.md) |
| Understand the Python/Rust execution boundary | [Execution-plan architecture](architecture/execution-plan.md) |
| Inspect the Rust crate map and current promotion state | [Native Rust architecture](architecture/native-rust.md) |
| Establish or inspect the V1.1 Rust-primary evidence baseline | [Rust-primary V1.1 baseline](architecture/rust_primary_v1_1_baseline.md) |
| Review the V1.1 independent oracle, execution-clock, accounting, and trace foundation | [Canonical Trace V2](contracts/v1_1_canonical_trace_v2.md) |
| Understand safe native session reuse, reset scopes, retained outputs, and derived-account invalidation | [PERF-02 session reuse](contracts/perf_02_session_reuse.md) |
| Choose dynamic versus run-stable reactive callback binding and inspect command-boundary telemetry | [PERF-03 reactive boundary](performance/perf_03_reactive_boundary.md) |
| Inspect exact native lifecycle matching, scratch reuse, aliases, and certified specialization boundaries | [PERF-04 native matching](performance/perf_04_native_matching.md) |
| Use the explicit Rust same-close target, static-DCA, or prepared target-WFO contract | [V1.1 Direct Target Execution Clock](contracts/v1_1_target_execution_clock.md) |
| Replay supplied fills with Rust-owned linear accounting, funding, margin, and liquidation evidence | [Linear Accounting And FillReplay V2](contracts/v1_1_linear_accounting_fill_replay_v2.md) |
| Understand shared execution costs, online metrics, and lazy native score/compact/audit results | [Execution, Metrics, And Native Result V2](contracts/v1_1_execution_metrics_result.md) |
| Use the explicit certified static command-tape Rust ABI 0.5 route and its ABI 0.4 rollback | [Rust full contract: Phase 61](native_event_rust_full_contract.md#phase-61-static-event-rust-primary-closure) |
| Use the explicit Rust-led numeric every-bar reactive co-runtime | [Rust full contract: Phase 62](native_event_rust_full_contract.md#phase-62-reactive-numeric-co-runtime-r1) |
| Use certified sparse wakes, block intents, or prepared candidate batch work | [Rust full contract: Phase 63](native_event_rust_full_contract.md#phase-63-sparse-wake-block-intent-and-candidate-batch-r2r3r3b) |
| Run a stateful reactive strategy through reset-flat WFO with native scalar scoring | [Reactive WFO (W3)](reactive_wfo.md) |
| Inspect the five-mode public WFO baseline, fallback boundaries, and `%_equity` transition contract before a Rust migration | [Public WFO Baseline V1](performance/public_wfo_baseline_v1.md) |
| Prepare a certified multi-symbol clock and immutable market handle | [Canonical Market And Calendar V2](contracts/v1_1_market_calendar_v2.md) |
| Resolve tick, lot, multiplier, leverage, and fee rules once per market | [Instrument Registry V2](contracts/v1_1_instrument_registry_v2.md) |
| Check exact core/native compatibility or generated maturity claims | [Generated product compatibility](contracts/generated_product_compatibility.md) |
| Build and verify staged core/native wheels | [Native companion installation](native/install.md) |
| Review native release scope, rollback, and release-owner steps | [Native release handoff](migration/native_release_handoff.md) |
| Troubleshoot a native descriptor or wheel mismatch | [Native troubleshooting](native/troubleshooting.md) |
| Reproduce native-event performance claims | [Benchmarking governance](performance/benchmarking.md) |
| Inspect actual-work counters, evidence identity, and promotion freshness | [Native Measurement Contract V1](performance/measurement_contract_v1.md) |
| Configure runtime limits, cancellation, teardown, and shadow safety | [Native runtime governance](native_runtime_governance.md) |
| Review platform wheels, auto-routing evidence, and A5 deletion gates | [Native productization and A5](native_productization_a5.md) |
| Migrate a callback toward a command writer or bounded IR | [Strategy boundary migration](migration/context-writer-ir.md) |
| Inspect the Rust Native Event V2 full contract, bounded target/package routes, and conformance gate | [Rust full contract](native_event_rust_full_contract.md) |
| Understand the pure Rust ABI 0.5 core, arena, and output ownership | [Rust full contract: Phase 53A](native_event_rust_full_contract.md#phase-53a-pure-rust-core) |
| Use the bounded native strategy IR, batch score, or causal fold primitive | [Native strategy IR and batch](native_strategy_ir.md) |
| Run prepared static-IR candidate x fold scoring in a persistent Rust worker pool | [Native WFO Runtime V2](native_wfo_runtime.md) |
| Inspect the shared typed Rust scheduler used by prepared candidate/fold/scenario work | [Shared prepared native evaluation](native_prepared_evaluation.md) |
| Opt into public single-symbol prepared-native WFO scoring and inspect W0/W1/W2 metadata | [Public prepared-native WFO scoring](native_prepared_wfo_public.md) |
| Use the correctness-contained Python options route and inspect capability/settlement evidence | [Options P0 containment](options_p0_containment.md) |
| Review the contract required before any Rust-primary options promotion | [Options V1.2 Rust handoff](options_v1_2_rust_handoff.md) |
| Certify the external Grid alpha on Python/Rust with 2,000-bar parity, RSS, and optimizer evidence | [Grid Phase 47C/47D](grid_native_event_phase47c.md) |

## Strategy Route Map

| Strategy type | Preferred route | Why |
|---|---|---|
| Single-symbol signal research | `QuantBTEndpoint.signal_notional(...)` or `.pct_equity(...)` | Fast scalar signal backtests with stable notebook API |
| Single-symbol SL/TP/trailing | `QuantBTEndpoint.intrabar_bracket(...)` | Strict next-open entry with high/low intrabar exit semantics |
| Explicit Rust SL/TP/trailing | `QuantBTEndpoint.intrabar_bracket_rust(...)` | Bounded one-symbol typed OHLC execution; no auto promotion |
| Stateful event callback | `QuantBTEndpoint.event_driven(input_mode="strategy", ...)` | Stable callback facade with explicit research/optimize/audit profiles |
| Canonical command tape | `QuantBTEndpoint.event_driven(input_mode="orders", ...)` | Full lifecycle contract with capability-gated Rust/Python routing |
| Existing explicit fill tape | `QuantBTEndpoint.fill_replay(...)` | V1 compatibility replay or explicit Rust V2 linear-accounting audit of supplied fills |
| Explicit orders | `QuantBTEndpoint.orders(...)` | Market/limit/stop order lifecycle and fill reports |
| DCA/grid | `QuantBTEndpoint.dca_ladder(...)` | Structural levels, high/low touch detection, trigger-price fills |
| Portfolio matrix | `QuantBTEndpoint.portfolio(...)` | Multi-symbol positions with portfolio-level accounting |
| Pair/basket | `QuantBTEndpoint.basket(...)` | Frozen hedge-ratio units and package diagnostics |
| Arbitrage | `QuantBTEndpoint.arbitrage(...)` | Domain specs for basis, stat-arb, funding, carry, and index-basket routes |
| Options | `QuantBTEndpoint.options(...)` | Option contracts, multi-leg packages, delta hedging, and gamma-scalping adapters |
| Walk-forward optimization | `QuantBTEndpoint.walk_forward(...)` | Calendar-certified folds, lifecycle-isolated strategy calls, causal schedules, OOS stitching, robust calibration, and opt-in prepared Rust scalar scoring |
| Stateful reactive walk-forward | `endpoint.prepare_reactive_walk_forward(...)` | Explicit reset-flat native account folds for R1/R2/R3/R3B strategies; never fabricates a stitched target/equity curve |
| Single holdout train/test | `QuantBTEndpoint.train_test_split(...)` | One train period and one test period using the same eligible WFO scoring stack |
| Standalone Optuna optimization | `OptunaOptimizer` + evaluator adapters | Prepared signal/intrabar/portfolio tuning or generic endpoint fallback |
| Third-party validation | `QuantBTEndpoint.nautilus_validation(...)` or `backend="nautilus"` | Independent event-driven accounting reports |

## Example Map

Runnable examples live under [`examples/`](../examples/README.md).

Use examples as smoke templates, not as performance benchmarks. For benchmark
numbers and threshold rules, use [`benchmarks/`](../benchmarks/README.md).

## Validation Rule

For production-like research:

1. Prototype with `native_vectorized` when the signal is already known.
2. Move order-sensitive strategies to `native_event`.
3. Validate representative runs with Nautilus when execution/accounting evidence
   is needed.
4. Save `result.metadata`, order/fill reports, config, and benchmark artifacts
   with the strategy output.
5. For execution-sensitive alphas, run the alpha certification scanner and do
   not claim production certification below Level 2.

## Native Product Status

`src/quantbt` is the authoritative Python source tree. A byte-identical,
manifest-limited root mirror remains for local Pool Alpha compatibility; test
bootstrap explicitly prioritizes `src/` so local tests cannot accidentally
exercise a stale installed wheel or a mirror instead of the source under
review.
The platform-governed Rust companion exposes explicit certified static command
tapes, bounded Native Strategy IR/batch rows, V2 `target_units`, and same-bar
atomic package market helpers. Automatic Rust promotion is held until fresh,
route-matched current-candidate evidence replaces the historical records. The
Phase 62 numeric every-bar co-runtime and Phase 63 sparse/block/candidate-batch
reactive contracts are explicit: Rust owns
simulation/accounting while Python remains the declared strategy-decision
authority. Default callbacks, generic portfolio, and package/arbitrage routes
remain Python. See [Native capabilities](native/capabilities.md) and [Rust full
contract](native_event_rust_full_contract.md).

The release benchmark is summarized in the repository [README](../README.md#release-benchmark).
The current governed evidence reaches 2.70M bars/s for a 2,000-bar Native
Strategy IR score and 11.25M bars/s for a shared 64-scenario batch, after exact
trace/accounting parity. These numbers are workload-scoped; see
[Benchmarking governance](performance/benchmarking.md) before comparing them.
