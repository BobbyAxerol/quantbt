# QuantBT Options Engine Execution Plan

Branch note: requested branch `dev/option-engine` cannot be created while the
existing branch `dev` exists, because Git cannot store both `refs/heads/dev`
and `refs/heads/dev/option-engine`. The working branch for this plan is
`feat/option-engine`.

This plan is derived from:

- `upgrade/option_backtest_plan/quantbt_options_engine_verified_design.md`
- `upgrade/option_backtest_plan/learnfromnautilusframework.md`

It is intentionally an implementation-control document, not a replacement for
the detailed design. The implementation must stay additive, preserve existing
QuantBT endpoint behavior, and only promote an options feature when the
domain-accounting tests pass.

## Core Principles

1. **Convention first**
   Option accounting starts from instrument convention, not from a generic
   payoff formula. Linear, inverse, quanto, premium currency, settlement
   currency, multiplier, fee currency, and reporting currency must be explicit.

2. **Ledger first**
   Actual PnL comes from cash, fills, fees, marks, lifecycle events, hedge PnL,
   and settlement cashflows. Greek attribution is explanatory only.

3. **Specialized backend**
   Do not patch generic `native_event` or `native_vectorized` to run options
   directly. Options need `backends/native_option.py` and a bounded
   `quantbt/options/` package.

4. **Ragged option tape**
   Do not represent the option chain as a dense `N_bars x N_contracts` matrix.
   Use long-form canonical data, then compile to a CSR/ragged event tape for
   hot loops.

5. **Bid/ask execution**
   Market buy fills at ask, market sell fills at bid. Mark/mid/model price may
   value positions, but cannot be the default execution price.

6. **No lookahead**
   Contract selection, delta selection, IV, surface, DTE, and expiry settlement
   must use only data observable at the decision timestamp.

7. **BacktestResultV2 compatibility**
   `OptionBacktestResult` can add option-specific artifacts, but must remain
   compatible with metrics, plots, reports, endpoint helpers, and report bundle
   workflows.

8. **Nautilus optional**
   Nautilus is a validation backend. Native option backtesting must not import
   Nautilus at import time or require Nautilus to be installed.

## Public Surface Target

Initial endpoint:

```python
bt = QuantBTEndpoint.options(
    backend="native_option",
    simulation_mode="event",          # event | research
    venue="deribit",
    initial_capital=2.0,
    base_currency="BTC",
    reporting_currency="USD",
    margin_mode="scenario_approximation",
    mark_policy="venue_mark",
    decision_fill_policy="next_snapshot",
    max_quote_age_ns=5_000_000_000,
)

result = bt.simulate(
    chain=option_chain,
    underlying=underlying_tape,
    packages=package_intents,
    instruments=instrument_specs,
)
```

Research helpers may later expose contract selection and surface diagnostics,
but research mode must be labelled as analytics/approximation, not
execution-accurate validation.

Support matrix target:

| Route | Native Option | Native Event | Native Vectorized | Nautilus |
|---|---|---|---|---|
| Single option | supported | unsupported | analytics only | planned validation |
| Multi-leg option package | supported | unsupported | analytics only | planned validation |
| Delta-hedged option package | supported | unsupported | unsupported | planned validation |
| `OptionsVolArbSpec` | supported specialized | schema-only | schema-only | planned validation |

## Phase 0 - Baseline Protection

Purpose: lock current QuantBT behavior before adding options.

Status: completed. See:

- `phase0_baseline_snapshot.json`
- `phase0_baseline_snapshot.md`

Tasks:

- Confirm branch is `feat/option-engine`.
- Run full non-real regression suite.
- Snapshot support matrices:
  - `QuantBTEndpoint.arbitrage_support_matrix()`
  - `QuantBTEndpoint.nautilus_support_matrix()`
- Confirm `import quantbt` works without Nautilus.
- Add an options plan/status section to `upgrade/implement.md` only after the
  first code phase starts.

Acceptance:

- Existing tests pass.
- No public endpoint behavior changes.
- No Nautilus import-time dependency.

## Phase 1 - Domain Schema And Conventions

Files:

- `core/schema.py`
- `options/__init__.py`
- `options/schema.py`
- `options/conventions.py`
- `options/data.py`
- `tests/options/test_phase1_schema_conventions.py`
- `tests/options/test_phase1_data.py`

Tasks:

- Add `AssetType.OPTION` only.
- Add option enums:
  - `OptionKind`
  - `ExerciseStyle`
  - `PremiumConvention`
  - `SettlementStyle`
  - `OptionDecisionFillPolicy`
- Add `OptionInstrumentSpec` extending `InstrumentSpec`.
- Add versioned venue conventions:
  - Deribit inverse BTC/ETH;
  - Deribit linear USDC;
  - Binance European options config, without pretending unsupported details are
    exact.
- Add instrument registry with symbol-to-code mapping and convention signature.
- Add canonical long-form chain schema validator.

Acceptance:

- Linear and inverse instruments cannot be confused.
- Missing premium/settlement/reporting currencies reject.
- Strike, multiplier, expiry, quantity step, venue and underlying fields are
  validated.
- Current non-option schemas remain compatible.

Status: completed.

Implemented:

- Added `AssetType.OPTION` without changing existing asset enum values.
- Added the bounded `quantbt.options` namespace for option schema,
  conventions, registry signatures, and canonical long-form chain validation.
- Added public top-level exports for Phase 1 option schema helpers.
- Added dependency-free Deribit inverse, Deribit linear USDC, and Binance
  European option convention descriptors.
- Added tests for additive imports, inverse-vs-linear convention validation,
  registry signatures, canonical chain normalization, quote guards, expiry
  guards, and duplicate snapshot rejection.

Latest local tests:

- `MPLCONFIGDIR=/tmp PYTHONPATH=/root/bobby/pool_alpha poetry run python -m compileall options core/schema.py __init__.py`
- `MPLCONFIGDIR=/tmp PYTHONPATH=/root/bobby/pool_alpha poetry run pytest -q tests/options/test_phase1_schema_conventions.py tests/options/test_phase1_data.py`
  - result: `12 passed`
- `MPLCONFIGDIR=/tmp PYTHONPATH=/root/bobby/pool_alpha poetry run python -c "import sys, quantbt; assert not any(n.startswith('nautilus_trader') for n in sys.modules); print('phase1_import_smoke=pass')"`
  - result: `phase1_import_smoke=pass`
- `MPLCONFIGDIR=/tmp PYTHONPATH=/root/bobby/pool_alpha poetry run pytest -q tests --ignore=tests/test_real.py --ignore=tests/test_real_endpoints.py`
  - result: `298 passed, 1 skipped, 3 warnings`

Technical debt after Phase 1:

- `OptionInstrumentSpec.multiplier` is currently required to equal the generic
  `InstrumentSpec.contract_size`. This is intentional for Phase 1 parity, but
  a later phase should decide whether option reporting uses one canonical
  multiplier field or keeps both with clearer aliases.
- `OptionInstrumentSpec.qty_step` is an option-domain alias for the generic
  `InstrumentSpec.lot_size`; both are normalized and must match when both are
  provided. Later execution docs should make one wording canonical for users.
- The canonical chain validator currently rejects zero bid/ask quotes. This is
  conservative for executable research input; later tape work may support
  one-sided or zero-bid quotes with explicit quote-status fields.
- Venue conventions are static versioned descriptors. Historical fee, margin,
  settlement, and instrument-specific schedule snapshots still need venue data
  or Nautilus parity samples in later phases.
- Binance option convention support is metadata-safe only. It does not claim
  exact venue margin or settlement behavior yet.
- No pricing, IV, Greeks, execution, ledger, expiry, endpoint, or Nautilus
  adapter behavior is implemented in Phase 1 by design.

## Phase 2 - Pricing, IV, Greeks

Files:

- `options/pricing.py`
- `options/iv.py`
- `options/greeks.py`
- `options/surface.py`
- `tests/options/test_pricing.py`
- `tests/options/test_inverse_conventions.py`
- `tests/options/test_iv.py`
- `tests/options/test_greeks.py`
- `tests/options/test_surface.py`

Tasks:

- Implement Linear Black-76:
  - call;
  - put;
  - intrinsic;
  - parity.
- Implement inverse forward-based pricing:
  - inverse call;
  - inverse put;
  - inverse intrinsic;
  - inverse put-call parity.
- Implement Greeks with explicit units:
  - native settlement-currency Greeks;
  - reporting-currency Greeks;
  - vega internal as per `1.0` vol change, reporting can show per vol point.
- Implement deterministic IV solver:
  - no-arb bounds;
  - bracketed bisection baseline;
  - status enum for invalid cases.
- Implement minimal surface diagnostics:
  - total variance interpolation;
  - static no-arb guard placeholders;
  - no future-expiry data in snapshot calibration.

Acceptance:

- Linear and inverse parity pass.
- IV recovers generated volatility.
- Invalid IV prices reject with status, not silent fallback.
- Finite-difference Greeks match analytic Greeks within tolerance.
- No `fastmath=True` in IV/no-arb critical paths.

## Phase 3 - Data Tape And Selectors

Files:

- `options/tape.py`
- `options/selectors.py`
- `tests/options/test_tape.py`
- `tests/options/test_selectors.py`
- `tests/options/test_no_lookahead.py`

Tasks:

- Normalize long-form option chain.
- Compile to `PreparedOptionTape` / CSR-style ragged arrays:
  - snapshot timestamps;
  - row pointers;
  - instrument codes;
  - bid/ask/size/mark/IV/OI.
- Add stale quote and crossed-book guards.
- Add selectors:
  - ATM;
  - target delta;
  - DTE;
  - moneyness;
  - liquidity/spread/OI filters.
- Add signatures:
  - tape signature;
  - instrument registry signature;
  - convention signature.

Acceptance:

- No dense fixed-universe option matrix is used as canonical chain.
- Expired/unlisted contracts are not selected.
- Delta/IV selection uses only observable snapshot values.
- Prepared tape rejects stale registry/convention/timestamp mismatch.

## Phase 4 - Package Compiler And Options Execution

Files:

- `options/packages.py`
- `options/execution.py`
- `tests/options/test_packages.py`
- `tests/options/test_execution.py`

Tasks:

- Add `OptionPackageLeg`:
  - `side` owns direction;
  - `ratio` is positive only.
- Add `OptionPackageIntent`.
- Compile option package to existing `OrderIntent` leaves with package metadata.
- Implement execution policies:
  - `ATOMIC_ALL_OR_NONE`;
  - `BEST_EFFORT`;
  - `SEQUENTIAL`;
  - `HEDGE_AFTER_PRIMARY`;
  - `REBALANCE_ONLY`.
- Implement option fill model:
  - market buy at ask;
  - market sell at bid;
  - limit maker fidelity modes;
  - FOK/IOC/GTC semantics where feasible;
  - package debit/credit guard;
  - depth/size guard with explicit fidelity label.

Acceptance:

- AON rollback leaves cash, positions, margin and reports unchanged on failure.
- IOC partial reports residual risk.
- Market fills never use mark/mid by default.
- Package metadata states whether atomicity is simulated, exchange combo, or
  block-trade style.

## Phase 5 - Multi-Currency Ledger, Fees, Lifecycle

Files:

- `options/ledger.py`
- `options/fees.py`
- `options/lifecycle.py`
- `tests/options/test_ledger.py`
- `tests/options/test_fees.py`
- `tests/options/test_lifecycle.py`

Tasks:

- Add multi-currency ledger:
  - cash;
  - position quantity;
  - avg entry;
  - realized PnL;
  - fees;
  - settlement cashflows;
  - margin locked.
- Implement premium cashflow:
  - long option pays premium;
  - short option receives premium;
  - fee recorded separately.
- Implement Deribit-like per-leg capped fees:
  - inverse base-currency fee cap;
  - linear USDC fee cap;
  - no package-level fee cap.
- Implement lifecycle:
  - OTM expiry;
  - ITM linear cash payoff;
  - ITM inverse payoff;
  - Deribit linear `economic_cash` and `future_then_cash` representations;
  - settlement audit rows.

Acceptance:

- Equity identity reconciles every event.
- Round trip with no price move equals spread plus fees.
- Inverse BTC premium and USD reporting equity reconcile via conversion rate.
- Settlement closes exactly once.
- Fees are in correct currency and converted only for reporting.

## Phase 6 - Hedging And Margin

Files:

- `options/hedging.py`
- `options/margin.py`
- `tests/options/test_hedging.py`
- `tests/options/test_margin.py`

Tasks:

- Implement hedge policies:
  - fixed threshold;
  - hysteresis band;
  - time-based;
  - realized-vol scaled band.
- Do not implement Whalley-Wilmott until objective, cost units and paper
  reproduction are available.
- Implement margin models:
  - long-premium-only;
  - standard venue approximation;
  - scenario portfolio margin approximation;
  - no-margin research mode;
  - external venue margin validator interface.
- Add liquidation sequence:
  - maintenance margin check;
  - adverse bid/ask liquidation;
  - iterative liquidation audit.

Acceptance:

- Hedge PnL uses previous hedge position for prior price move.
- Hedge rebalance happens after option package fills and Greek recomputation.
- Scenario PM report states `venue_exact=false`.
- Liquidation audit explains breach, orders, fees and final state.

## Phase 7 - Backend, Engine, Endpoint, Result

Files:

- `backends/native_option.py`
- `engines.py`
- `endpoint.py`
- `core/results.py`
- `metrics/options_analytics.py`
- `tests/options/test_endpoint_contract.py`
- `tests/options/test_result_contract.py`

Tasks:

- Add `NativeOptionConfig`.
- Add `NativeOptionBackend`.
- Add `OptionBacktestEngine`.
- Add `OptionBacktestResult` compatible with `BacktestResultV2`.
- Add `QuantBTEndpoint.options(...)`.
- Add `options_support_matrix()`.
- Wire `OptionsVolArbSpec` to specialized option route only.
- Add required option reports:
  - fills;
  - packages;
  - cash balances;
  - marks;
  - Greeks;
  - settlements;
  - margin;
  - attribution;
  - run manifest.

Acceptance:

- `QuantBTEndpoint.options(...)` runs mock chain examples.
- Existing endpoints still pass tests.
- `import quantbt` still does not require Nautilus.
- Result supports `.show_metrics()`, `.full_report()`, and report bundle paths
  where current `BacktestResultV2` supports them.

## Phase 8 - Strategy Templates And Golden Payoff Tests

Files:

- `options/templates/*.py`
- `examples/options/*.py`
- `tests/options/test_strategy_payoffs.py`

Tasks:

- Implement package builders only, not accounting logic:
  - long/short call;
  - long/short put;
  - straddle;
  - strangle;
  - vertical;
  - butterfly;
  - condor;
  - calendar;
  - covered call;
  - collar;
  - risk reversal.
- Add expiry payoff grid tests.
- Add mock examples:
  - Deribit inverse gamma scalping;
  - linear spread;
  - covered call;
  - calendar.

Acceptance:

- Golden payoff tests pass for all V1 structures.
- Templates only emit package intents; they do not compute PnL manually.

## Phase 9 - Nautilus Validation

Files:

- `adapters/nautilus/options.py`
- `tests/options/test_nautilus_options.py`
- `docs/nautilus_backend.md`

Tasks:

- Keep Nautilus optional.
- Pin/inspect Nautilus version before constructing option instruments.
- Map to:
  - `CryptoOption`;
  - `CryptoOptionSpread`;
  - `OptionContract`;
  - `OptionSpread` where appropriate.
- Use Nautilus quote-driven matching:
  - market buy at ask;
  - market sell at bid;
  - limit fills when BBO crosses limit policy.
- Validate representative cases:
  - one linear option round trip;
  - one inverse option if exact adapter convention is supported;
  - two-leg spread;
  - option plus perpetual/underlying delta hedge;
  - expiry settlement;
  - fees and account reports.
- Export component-specific parity:
  - quantity;
  - fill timestamp;
  - fill price;
  - fee;
  - settlement;
  - realized cashflow;
  - final equity.

Acceptance:

- Missing Nautilus or incompatible version skips clearly.
- Validation reports never claim full mapping unless constructor compatibility
  and instrument conventions are pinned.
- Native and Nautilus differences are component-labelled, not hidden in one
  final-equity tolerance.

## Phase 10 - Performance And Production Hardening

Files:

- `benchmarks/run_options_engine.py`
- `benchmarks/options_*.json`
- `benchmarks/options_*.md`
- `tests/options/test_fuzz_invalid_data.py`

Tasks:

- Add prepared tape cache.
- Add compiled package cache.
- Benchmark:
  - snapshots;
  - quotes;
  - packages;
  - fills;
  - hedges;
  - contracts;
  - memory.
- Add deterministic replay with random seed.
- Add fuzz tests for invalid data.
- Add run manifest:
  - data hash;
  - convention version;
  - fee schedule;
  - margin model;
  - pricing model;
  - fidelity manifest.

Acceptance:

- Large mock chain benchmark has parity guards.
- Prepared tape rejects stale signatures.
- Cython/C++ is only considered after Numba/profile evidence shows pure kernel
  bottlenecks.

## V1 Completion Criteria

V1 can be called usable only when:

- current QuantBT regression suite passes;
- `QuantBTEndpoint.options(...)` runs;
- linear and inverse conventions are separate and tested;
- bid/ask fills and per-leg fees use correct units;
- premium cashflow is not double-counted;
- hedge PnL uses previous hedge quantity for prior price move;
- multi-currency equity reconciles each event;
- linear and inverse expiry settlement pass;
- AON package rollback is atomic;
- key strategy payoff grids pass;
- Greeks finite-difference tests pass;
- IV solver recovers known volatility;
- result artifacts are `BacktestResultV2` compatible;
- run manifest contains convention, fee, margin and data hashes;
- at least one inverse gamma-scalping example and one linear spread example are
  archived;
- Nautilus or venue official parity samples exist for the supported validation
  subset.

## Non-Goals Until Later

- Exact Deribit Portfolio Margin clone without official/API validation.
- True L2 queue-priority execution unless real L2 data is provided.
- Whalley-Wilmott hedge policy without dimensional/paper benchmark validation.
- Generic `native_event` options execution.
- Advertising Nautilus options mapping as complete before version-pinned
  compatibility tests.
- Cross-venue volatility arbitrage production semantics before collateral,
  transfer, latency and borrow constraints are implemented.

## Immediate Next Step

Start with Phase 0, then Phase 1. Do not jump to pricing or endpoint wiring
before schema/convention tests pass. The first code commit should be small:
`AssetType.OPTION`, `options/schema.py`, `options/conventions.py`, and schema
tests only.
