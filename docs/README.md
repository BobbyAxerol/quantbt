# QuantBT Documentation Map

Use this page as the first stop when deciding which QuantBT document to read.

## Start Here

| Need | Read |
|---|---|
| Choose the right backend | [Backend selection](backend_selection.md) |
| Call QuantBT from notebooks/services | [Endpoint contract](endpoint.md) |
| Choose the correct execution timing contract | [Execution contracts](execution_contracts.md) |
| Migrate SL/TP/trailing alphas to the fast intrabar route | [Fast intrabar](fast_intrabar.md) |
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
| Check exact core/native compatibility or generated maturity claims | [Generated product compatibility](contracts/generated_product_compatibility.md) |
| Build and verify staged core/native wheels | [Native companion installation](native/install.md) |
| Review native release scope, rollback, and release-owner steps | [Native release handoff](migration/native_release_handoff.md) |
| Troubleshoot a native descriptor or wheel mismatch | [Native troubleshooting](native/troubleshooting.md) |
| Reproduce native-event performance claims | [Benchmarking governance](performance/benchmarking.md) |
| Migrate a callback toward a command writer or bounded IR | [Strategy boundary migration](migration/context-writer-ir.md) |
| Inspect the Rust Native Event V2 full contract, bounded target/package routes, and conformance gate | [Rust full contract](native_event_rust_full_contract.md) |
| Understand the pure Rust ABI 0.5 core, arena, and output ownership | [Rust full contract: Phase 53A](native_event_rust_full_contract.md#phase-53a-pure-rust-core) |
| Use the bounded native strategy IR, batch score, or causal fold primitive | [Native strategy IR and batch](native_strategy_ir.md) |
| Certify the external Grid alpha on Python/Rust with 2,000-bar parity, RSS, and optimizer evidence | [Grid Phase 47C/47D](grid_native_event_phase47c.md) |

## Strategy Route Map

| Strategy type | Preferred route | Why |
|---|---|---|
| Single-symbol signal research | `QuantBTEndpoint.signal_notional(...)` or `.pct_equity(...)` | Fast scalar signal backtests with stable notebook API |
| Single-symbol SL/TP/trailing | `QuantBTEndpoint.intrabar_bracket(...)` | Strict next-open entry with high/low intrabar exit semantics |
| Existing explicit fill tape | `QuantBTEndpoint.fill_replay(...)` | Accounting replay for old alphas before causal migration |
| Explicit orders | `QuantBTEndpoint.orders(...)` | Market/limit/stop order lifecycle and fill reports |
| DCA/grid | `QuantBTEndpoint.dca_ladder(...)` | Structural levels, high/low touch detection, trigger-price fills |
| Portfolio matrix | `QuantBTEndpoint.portfolio(...)` | Multi-symbol positions with portfolio-level accounting |
| Pair/basket | `QuantBTEndpoint.basket(...)` | Frozen hedge-ratio units and package diagnostics |
| Arbitrage | `QuantBTEndpoint.arbitrage(...)` | Domain specs for basis, stat-arb, funding, carry, and index-basket routes |
| Walk-forward optimization | `QuantBTEndpoint.walk_forward(...)` | Folded OOS stitching, anti-leakage candidate selection, and full-sample robust calibration |
| Single holdout train/test | `QuantBTEndpoint.train_test_split(...)` | One train period and one test period using the WFO scoring stack |
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

`src/quantbt` is the authoritative Python source tree. The root mirror is a
checked compatibility mirror during the transition and must be synchronized by
the repository tool, never edited independently. The platform-governed Rust companion
promotes certified static command tapes and bounded Native Strategy IR/batch
rows under `backend="auto"`. It also exposes explicit bounded V2
`target_units` and same-bar atomic package market helpers; generic callback,
reactive, portfolio, and package/arbitrage routes remain Python. See [Native
capabilities](native/capabilities.md) and [Rust full contract](native_event_rust_full_contract.md).
