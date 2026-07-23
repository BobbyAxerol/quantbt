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

Status: completed.

Implemented:

- Added scalar deterministic pricing primitives in `options/pricing.py`.
- Added linear Black-76 call/put price, intrinsic value, and put-call parity
  helpers.
- Added inverse forward-based pricing in base settlement currency, with inverse
  intrinsic and base-currency parity helpers.
- Added `OptionGreeks` and Greek helpers in `options/greeks.py`:
  - linear quote-currency Greeks;
  - inverse native base-currency Greeks;
  - inverse quote-reporting Greeks;
  - explicit static currency scaling helper.
- Added `IVStatus`, `ImpliedVolResult`, and deterministic bisection IV solvers
  in `options/iv.py`.
- Added `TotalVarianceSurface` and `SurfaceDiagnostics` in
  `options/surface.py`:
  - total variance from same-timestamp snapshots;
  - strike-then-expiry interpolation;
  - calendar total variance diagnostic;
  - placeholder flag for butterfly convexity.
- Exported Phase 2 primitives from `quantbt.options` and top-level `quantbt`.

Latest local tests:

- `MPLCONFIGDIR=/tmp PYTHONPATH=/root/bobby/pool_alpha poetry run python -m compileall options __init__.py`
- `MPLCONFIGDIR=/tmp PYTHONPATH=/root/bobby/pool_alpha poetry run pytest -q tests/options`
  - result: `31 passed`
- `rg -n "fastmath" options tests/options`
  - result: no matches
- `MPLCONFIGDIR=/tmp PYTHONPATH=/root/bobby/pool_alpha poetry run python -c "import sys, quantbt; assert quantbt.black76_price(100,100,1,0.2,'call') > 0; assert not any(n.startswith('nautilus_trader') for n in sys.modules); print('phase2_import_smoke=pass')"`
  - result: `phase2_import_smoke=pass`
- `MPLCONFIGDIR=/tmp PYTHONPATH=/root/bobby/pool_alpha poetry run pytest -q tests --ignore=tests/test_real.py --ignore=tests/test_real_endpoints.py`
  - result: `317 passed, 1 skipped, 3 warnings`

Technical debt after Phase 2:

- Pricing and Greeks are scalar deterministic primitives. Phase 3/4 hot paths
  may add vectorized or Numba kernels after tape/execution shapes are stable.
- Inverse pricing uses the Phase 2 forward convention: quote-currency
  Black-76 price divided by forward. Venue-exact Deribit/Binance settlement,
  fees, and margin still require later parity data.
- Theta holds forward and discount fixed. Full curve/rate theta attribution is
  intentionally deferred.
- Surface diagnostics are intentionally minimal. Butterfly convexity and full
  arbitrage-free surface fitting are placeholders, not production-certified
  surface construction.
- IV uses bracketed bisection for determinism and auditability. Faster Newton
  or hybrid solvers can be added later only with parity locks.
- No option tape, selector, execution, ledger, endpoint, expiry, or Nautilus
  adapter behavior is implemented in Phase 2 by design.

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

Status: completed.

Implemented:

- Added `options/tape.py`:
  - `PreparedOptionTape`;
  - `OptionTapeSignature`;
  - `prepare_option_tape(...)`;
  - CSR-style `timestamp_ns` and `row_ptr`;
  - per-row instrument codes, bid/ask/size, mark, forward/index, IV, Greeks,
    OI, volume, and source latency arrays;
  - registry static-field checks;
  - stale source-latency guard;
  - registry, convention, and timestamp compatibility checks.
- Added `options/selectors.py`:
  - `OptionSelectionFilters`;
  - `OptionSelection`;
  - `available_option_rows(...)`;
  - `select_atm_option(...)`;
  - `select_target_delta_option(...)`;
  - `select_target_dte_option(...)`;
  - `select_target_moneyness_option(...)`.
- Added Phase 3 tests:
  - CSR tape shape and signatures;
  - unknown/unlisted instrument rejection;
  - registry strike/kind mismatch rejection;
  - crossed quote and stale source latency rejection;
  - ATM, target-delta, target-DTE, and moneyness selectors;
  - liquidity/spread/OI filters;
  - no-lookahead snapshot selection;
  - stale decision-time quote age rejection;
  - expired contract filtering at decision time.
- Exported Phase 3 tape and selector APIs from `quantbt.options` and top-level
  `quantbt`.

Latest local tests:

- `MPLCONFIGDIR=/tmp PYTHONPATH=/root/bobby/pool_alpha poetry run python -m compileall options __init__.py`
- `MPLCONFIGDIR=/tmp PYTHONPATH=/root/bobby/pool_alpha poetry run pytest -q tests/options`
  - result: `43 passed`
- `MPLCONFIGDIR=/tmp PYTHONPATH=/root/bobby/pool_alpha poetry run python -c "import sys, quantbt; assert quantbt.prepare_option_tape; assert not any(n.startswith('nautilus_trader') for n in sys.modules); print('phase3_import_smoke=pass')"`
  - result: `phase3_import_smoke=pass`
- `rg -n "pivot|unstack|N_bars|dense|fastmath" options tests/options`
  - result: no dense matrix construction or `fastmath`; only documentation/test
    wording contains `dense`.
- `MPLCONFIGDIR=/tmp PYTHONPATH=/root/bobby/pool_alpha poetry run pytest -q tests --ignore=tests/test_real.py --ignore=tests/test_real_endpoints.py`
  - result: `329 passed, 1 skipped, 3 warnings`

Technical debt after Phase 3:

- Tape and selectors are array-first but still Python/NumPy scalar scans at the
  selector layer. Numba kernels should wait until Phase 4 execution package
  shapes are stable.
- Delta/IV selectors trust observable chain columns. Later phases should add
  optional fallback to Phase 2 model Greeks/IV only when explicitly requested
  and tagged as model-derived.
- Source latency and quote age guards are deterministic snapshot guards, not
  real venue L2 replay or queue priority.
- Selector tie-breaks currently use first minimum after canonical sort. If
  strategies need deterministic secondary rules such as max OI or tightest
  spread, add explicit selector policies.
- No option package compiler, execution, ledger, expiry lifecycle, endpoint, or
  Nautilus validation is implemented in Phase 3 by design.

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

Status: completed.

Implemented:

- Added `options/packages.py`:
  - `OptionPackageLeg`;
  - `OptionPackageIntent`;
  - `OptionPackageExecutionPolicy`;
  - `compile_option_package_orders(...)`.
- Enforced package-leg domain rules:
  - `side` owns direction;
  - `ratio` must be positive;
  - Phase 4 supports market and limit option package legs only;
  - limit legs require positive `limit_price`.
- Compiled package legs into existing `OrderIntent` leaves with package
  metadata:
  - package id;
  - leg index;
  - leg ratio;
  - leg role;
  - execution policy;
  - simulated atomicity label;
  - `exchange_combo=False`;
  - `block_trade_style=False`.
- Added `options/execution.py`:
  - `OptionExecutionConfig`;
  - `OptionLimitFidelity`;
  - `OptionDepthFidelity`;
  - `OptionPackageExecutionResult`;
  - `execute_option_package(...)`.
- Implemented snapshot-level option fill behavior:
  - market buy fills at ask;
  - market sell fills at bid;
  - limit `CROSS_ONLY`;
  - limit `MAKER_TOUCH` as explicit simulated maker fidelity;
  - top-of-book size guard;
  - FOK full-fill/reject;
  - IOC partial with residual-risk report;
  - GTC open/partial behavior where feasible;
  - package debit/credit guard.
- Implemented package policies:
  - `ATOMIC_ALL_OR_NONE`;
  - `BEST_EFFORT`;
  - `SEQUENTIAL`;
  - `HEDGE_AFTER_PRIMARY`;
  - `REBALANCE_ONLY`.
- Added Phase 4 tests for package validation, order compilation, AON rollback,
  market bid/ask fills, IOC partials, debit guards, limit fidelity modes,
  primary-then-hedge, and rebalance-to-target behavior.
- Exported Phase 4 package and execution APIs from `quantbt.options` and
  top-level `quantbt`.

Latest local tests:

- `MPLCONFIGDIR=/tmp PYTHONPATH=/root/bobby/pool_alpha poetry run python -m compileall options __init__.py`
- `MPLCONFIGDIR=/tmp PYTHONPATH=/root/bobby/pool_alpha poetry run pytest -q tests/options`
  - result: `54 passed`
- `MPLCONFIGDIR=/tmp PYTHONPATH=/root/bobby/pool_alpha poetry run python -c "import sys, quantbt; assert quantbt.execute_option_package; assert not any(n.startswith('nautilus_trader') for n in sys.modules); print('phase4_import_smoke=pass')"`
  - result: `phase4_import_smoke=pass`
- `MPLCONFIGDIR=/tmp PYTHONPATH=/root/bobby/pool_alpha poetry run pytest -q tests --ignore=tests/test_real.py --ignore=tests/test_real_endpoints.py`
  - result: `340 passed, 1 skipped, 3 warnings`

Technical debt after Phase 4:

- Execution is snapshot/top-of-book only. It is not L2 replay, queue priority,
  or venue-native combo matching.
- Margin report is intentionally a Phase 4 placeholder. Real multi-currency
  ledger, fees by currency, margin, settlement, expiry, and lifecycle are Phase
  5+ work.
- Stop orders and conditional lifecycle orders are rejected in Phase 4; they
  should be added only after lifecycle semantics are implemented.
- `MAKER_TOUCH` is an explicit approximation. It should not be described as
  exchange-native maker queue simulation.
- Package debit/credit guard works on simulated fills in package premium units;
  full portfolio/multi-currency conversion is deferred.
- No endpoint route or Nautilus validation is implemented in Phase 4 by design.

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

Status: completed.

Implemented:

- Added `options/fees.py`:
  - `OptionFeeSchedule`;
  - `OptionFeeResult`;
  - `deribit_inverse_fee_schedule(...)`;
  - `deribit_linear_usdc_fee_schedule(...)`;
  - `calculate_option_fee(...)`.
- Added deterministic per-leg capped fee logic:
  - inverse base-currency fee cap;
  - linear USDC reference-notional fee cap;
  - no package-level fee cap.
- Added `options/ledger.py`:
  - `OptionLedger`;
  - `OptionPosition`;
  - multi-currency cash balances;
  - position quantity and average entry;
  - realized PnL;
  - fee ledger;
  - settlement cashflow ledger;
  - margin-locked bucket;
  - event audit rows;
  - reporting-currency equity identity.
- Added `options/lifecycle.py`:
  - `OptionSettlementRepresentation`;
  - `OptionSettlementResult`;
  - `option_expiry_payoff_per_unit(...)`;
  - `settle_option_expiry(...)`.
- Implemented lifecycle cases:
  - OTM expiry;
  - ITM linear cash payoff;
  - ITM inverse base-currency payoff;
  - Deribit-style linear `economic_cash`;
  - Deribit-style linear `future_then_cash` representation;
  - settlement exactly-once guard.
- Exported Phase 5 APIs from `quantbt.options` and top-level `quantbt`.

Latest local tests:

- `MPLCONFIGDIR=/tmp PYTHONPATH=/root/bobby/pool_alpha poetry run python -m compileall options __init__.py`
- `MPLCONFIGDIR=/tmp PYTHONPATH=/root/bobby/pool_alpha poetry run pytest -q tests/options`
  - result: `63 passed`
- `MPLCONFIGDIR=/tmp PYTHONPATH=/root/bobby/pool_alpha poetry run python -c "import sys, quantbt; assert quantbt.OptionLedger; assert quantbt.settle_option_expiry; assert not any(n.startswith('nautilus_trader') for n in sys.modules); print('phase5_import_smoke=pass')"`
  - result: `phase5_import_smoke=pass`
- `MPLCONFIGDIR=/tmp PYTHONPATH=/root/bobby/pool_alpha poetry run pytest -q tests --ignore=tests/test_real.py --ignore=tests/test_real_endpoints.py`
  - result: `349 passed, 1 skipped, 3 warnings`

Technical debt after Phase 5:

- Ledger is an accounting primitive, not yet wired into a full option backend or
  endpoint.
- Margin locked is present as an auditable bucket, but real margin models and
  liquidation sequencing are Phase 6.
- Fee schedules are Deribit-like deterministic approximations. Venue-exact
  schedules still need versioned venue data and Nautilus/sample parity.
- `future_then_cash` is represented as an audit label with equivalent economic
  cashflow. A later venue adapter may split this into delivery and cash rows.
- Quanto options remain unsupported for lifecycle payoff.
- Reporting conversion is explicit via caller-supplied conversion rates; no FX
  or index feed is implicitly fetched.

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

Status: completed.

Implemented:

- Added `options/hedging.py`:
  - `OptionHedgePolicyType`;
  - `OptionHedgeConfig`;
  - `HedgeDecision`;
  - `HedgePathResult`;
  - `compute_net_option_delta(...)`;
  - `hedge_decision(...)`;
  - `run_delta_hedge_path(...)`.
- Implemented hedge policies:
  - fixed threshold;
  - hysteresis band;
  - time-based;
  - realized-vol scaled band.
- Locked hedge accounting order:
  - hedge PnL for `price[t-1] -> price[t]` uses hedge quantity held at `t-1`;
  - rebalance is evaluated only after current option delta is recomputed.
- Added `options/margin.py`:
  - `OptionMarginModel`;
  - `OptionMarginConfig`;
  - `OptionMarginRequirement`;
  - `ExternalOptionMarginValidator`;
  - `OptionLiquidationAudit`;
  - `calculate_option_margin(...)`;
  - `liquidate_option_positions(...)`.
- Implemented margin models:
  - long-premium-only;
  - standard venue approximation;
  - scenario PM approximation with `venue_exact=false`;
  - no-margin research;
  - external validator interface.
- Implemented liquidation audit:
  - maintenance breach check;
  - adverse bid/ask liquidation;
  - fee reporting;
  - final cash and final positions.
- Exported Phase 6 APIs from `quantbt.options` and top-level `quantbt`.

Latest local tests:

- `MPLCONFIGDIR=/tmp PYTHONPATH=/root/bobby/pool_alpha poetry run python -m compileall options __init__.py`
- `MPLCONFIGDIR=/tmp PYTHONPATH=/root/bobby/pool_alpha poetry run pytest -q tests/options`
  - result: `71 passed`
- `MPLCONFIGDIR=/tmp PYTHONPATH=/root/bobby/pool_alpha poetry run python -c "import sys, quantbt; assert quantbt.OptionHedgeConfig; assert quantbt.OptionMarginConfig; assert not any(n.startswith('nautilus_trader') for n in sys.modules); print('phase6_import_smoke=pass')"`
  - result: `phase6_import_smoke=pass`
- `MPLCONFIGDIR=/tmp PYTHONPATH=/root/bobby/pool_alpha poetry run pytest -q tests --ignore=tests/test_real.py --ignore=tests/test_real_endpoints.py`
  - result: `357 passed, 1 skipped, 3 warnings`

Technical debt after Phase 6:

- Hedge models are deterministic policy primitives, not a full integrated option
  backtest loop yet. Backend wiring is Phase 7.
- Whalley-Wilmott is intentionally not implemented.
- Standard and scenario margin are approximations. Scenario PM explicitly
  reports `venue_exact=false`.
- External venue margin validator is an interface only; no venue adapter is
  implemented in Phase 6.
- Liquidation sequence closes all option positions with adverse BBO prices; it
  is not an exchange liquidation engine, queue model, or partial liquidation
  optimizer.
- Underlying hedge instrument execution and fees are not yet integrated with
  option package execution.

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

Status: completed.

Implementation notes:

- Added `NativeOptionConfig` and `NativeOptionBackend` in
  `backends/native_option.py`.
- Added `OptionBacktestEngine` facade in `engines.py`.
- Added `OptionBacktestResult` in `core/results.py`, compatible with
  `BacktestResultV2` and exposing option audit artifacts.
- Added `QuantBTEndpoint.options(...)` plus `options_support_matrix()`.
- Routed `OptionsVolArbSpec` away from generic arbitrage execution and toward
  the specialized option endpoint.
- Added option report helpers in `metrics/options_analytics.py`.
- Added endpoint/result contract tests covering mock chain execution,
  settlement events, support matrix, full report compatibility, and artifact
  availability.

Validation:

- `MPLCONFIGDIR=/tmp PYTHONPATH=/root/bobby/pool_alpha poetry run pytest -q tests/options`
- `MPLCONFIGDIR=/tmp PYTHONPATH=/root/bobby/pool_alpha poetry run pytest -q tests --ignore=tests/test_real.py --ignore=tests/test_real_endpoints.py`
- `MPLCONFIGDIR=/tmp PYTHONPATH=/root/bobby/pool_alpha poetry run python -c "import sys, quantbt; assert quantbt.NativeOptionConfig; assert quantbt.OptionBacktestResult; assert not any(n.startswith('nautilus_trader') for n in sys.modules); print('phase7_import_smoke=pass')"`

Technical debt after Phase 7:

- Margin remains an explicit native approximation unless an external venue
  validator is provided in later phases.
- Nautilus option validation is still Phase 9, not claimed complete here.
- Strategy templates and golden payoff structures are Phase 8.
- Venue-exact exchange combo behavior and L2 order-book queue priority remain
  later fidelity work.

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

Status: completed.

Implementation notes:

- Added `options/templates/` with V1 package builders:
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
- Builders emit `OptionPackageIntent` and `OptionPackageLeg` only.
- Added golden expiry payoff tests for every V1 structure using a linear USD
  registry and intrinsic payoff assertions.
- Added mock examples under `examples/options/`:
  - Deribit inverse long straddle / gamma-scalping skeleton;
  - linear call vertical;
  - covered call package construction;
  - call calendar spread.
- Exported template builders from `quantbt.options` and top-level `quantbt`.

Validation:

- `MPLCONFIGDIR=/tmp PYTHONPATH=/root/bobby/pool_alpha poetry run python -m compileall options examples/options __init__.py`
- `MPLCONFIGDIR=/tmp PYTHONPATH=/root/bobby/pool_alpha poetry run pytest -q tests/options`
- Runnable examples:
  - `examples/options/linear_spread.py`
  - `examples/options/calendar_spread.py`
  - `examples/options/covered_call.py`
  - `examples/options/deribit_inverse_gamma_scalping.py`

Technical debt after Phase 8:

- Covered call and collar templates correctly emit an underlying leg, but
  Phase 7 native option endpoint still executes option-chain legs only.
  Mixed underlying+option execution is a later adapter/engine fidelity item.
- Payoff tests validate terminal intrinsic shapes, not venue margin or hedging.
- Strategy templates are simple package builders; research signal generation
  and option selection still belong to the strategy/research layer.

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

Status: completed at experimental constructor-pinned validation level.

Implementation notes:

- Added `adapters/nautilus/options.py`:
  - `NautilusOptionValidationConfig`;
  - `NautilusOptionValidationResult`;
  - `inspect_nautilus_option_support`;
  - `make_nautilus_option_instrument`;
  - `build_nautilus_option_quote_table`;
  - `validate_option_packages_with_nautilus`.
- Exported Phase 9 helpers from `quantbt.adapters.nautilus`.
- Pinned and inspected Nautilus `1.230.0` option constructor docs before
  constructing option instruments.
- Mapped QuantBT option specs to Nautilus `CryptoOption` / `OptionContract`
  where constructor compatibility is available.
- Built QuoteTick-equivalent BBO reports with explicit matching semantics:
  market buy at ask, market sell at bid, limit crossed by BBO only.
- Added component-labelled parity reports for:
  - quantity;
  - fill timestamp;
  - fill price;
  - fee;
  - settlement;
  - realized cashflow;
  - final equity.
- Added tests for:
  - missing Nautilus skip behavior;
  - constructor mapping;
  - one linear option round trip;
  - inverse option constructor validation;
  - two-leg spread plus settlement;
  - option plus underlying hedge labelled as future mixed-instrument replay;
  - support matrix exposure.

Validation:

- `MPLCONFIGDIR=/tmp PYTHONPATH=/root/bobby/pool_alpha poetry run pytest -q tests/options`
- `MPLCONFIGDIR=/tmp PYTHONPATH=/root/bobby/pool_alpha poetry run pytest -q tests --ignore=tests/test_real.py --ignore=tests/test_real_endpoints.py`
- `MPLCONFIGDIR=/tmp PYTHONPATH=/root/bobby/pool_alpha poetry run python -c "import sys, quantbt; assert quantbt.QuantBTEndpoint.options_support_matrix()['nautilus_options']['status'] == 'experimental'; assert not any(n.startswith('nautilus_trader') for n in sys.modules); print('phase9_import_smoke=pass')"`

Technical debt after Phase 9:

- Phase 9 does not claim full Nautilus option backtest-engine replay. It pins
  constructors and quote semantics, then labels parity against native option
  accounting.
- Nautilus QuoteTick ingestion and option engine account reports remain future
  work.
- `CryptoOptionSpread` / `OptionSpread` constructors are inspected but package
  validation still uses component option legs, not exchange-native spread
  instruments.
- Mixed underlying/perpetual + option package execution is labelled as future
  work until a multi-instrument option/underlying replay path is implemented.

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

Status: completed.

Implementation notes:

- Added explicit prepared option cache:
  - `OptionPreparedRunCache`;
  - `option_package_cache_key`;
  - signature-checked prepared tape reuse;
  - deterministic compiled package order cache.
- Added optional `prepared_cache` threading through:
  - `NativeOptionBackend.run(...)`;
  - `OptionBacktestEngine`;
  - `QuantBTEndpoint.options(...).backtest(...)`.
- Added `compiled_orders` override to `execute_option_package(...)` while
  preserving the old compile-on-call default.
- Extended option run manifest with:
  - data hash;
  - registry signature hash;
  - convention versions;
  - fee schedule;
  - margin model;
  - pricing model;
  - deterministic replay seed;
  - fidelity manifest.
- Added `benchmarks/run_options_engine.py`.
- Added committed benchmark baseline:
  - `benchmarks/options_phase10_baseline.json`;
  - `benchmarks/options_phase10_baseline.md`.
- Added deterministic fuzz/invalid-data tests in
  `tests/options/test_fuzz_invalid_data.py`.

Validation:

- `MPLCONFIGDIR=/tmp PYTHONPATH=/root/bobby/pool_alpha poetry run pytest -q tests/options`
- `MPLCONFIGDIR=/tmp PYTHONPATH=/root/bobby/pool_alpha poetry run python benchmarks/run_options_engine.py --snapshots 48 --contracts 24 --packages 48 --repeats 2 --output-json benchmarks/options_phase10_baseline.json --output-md benchmarks/options_phase10_baseline.md`
- `MPLCONFIGDIR=/tmp PYTHONPATH=/root/bobby/pool_alpha poetry run pytest -q tests --ignore=tests/test_real.py --ignore=tests/test_real_endpoints.py`

Technical debt after Phase 10:

- Benchmark is a deterministic mock-chain baseline, not a venue production
  latency/profile certification.
- Hedges are counted in the benchmark schema but set to zero because mixed
  underlying option hedging remains future engine work.
- Cython/C++ is not recommended yet; current Phase 10 evidence supports cache
  reuse and facade profiling first.

## Phase 11 - Options Strategy Adapter And Delta-Hedged Contract

Files:

- `options/strategy.py`
- `core/results.py`
- `backends/native_option.py`
- `engines.py`
- `endpoint.py`
- `tests/options/test_strategy_adapter_contract.py`
- `benchmarks/gamma_scalping_backtestsample.py`
- `docs/endpoint.md`

Tasks:

- Add a strategy-layer output contract:
  - `OptionStrategyRun`;
  - `packages`;
  - optional `hedge_policy`;
  - `selected_contracts`;
  - metadata.
- Add a gamma-scalping adapter:
  - `GammaScalpingConfig`;
  - `build_gamma_scalping_strategy_run(...)`;
  - snapshot-local ATM straddle selection;
  - DTE, spread, bid/ask size, volume and OI filters;
  - open/roll/close package generation.
- Extend `QuantBTEndpoint.options(...).backtest(...)` with optional:
  - `strategy_run`;
  - `underlying`;
  - `hedge_policy`;
  - `net_option_delta`.
- Extend `OptionBacktestResult` with first-class delta-hedged artifacts:
  - `option_equity`;
  - `hedge_report`;
  - `combined_equity`;
  - `combined_returns`.
- If a hedge policy is supplied, make `result.equity` represent the combined
  option-plus-hedge equity curve while preserving option-only equity separately.
- Add a pre-trade row at `first_timestamp - 1ns` for hedged option runs so the
  reporting curve starts at declared initial capital before the first fill.
- Update the gamma scalping benchmark to use the public endpoint contract:
  `strategy_run + underlying`, not manual package/hedge plumbing.

Acceptance:

- Existing unhedged `QuantBTEndpoint.options(...)` calls remain compatible.
- Gamma adapter emits packages without inspecting future snapshots for
  selection.
- Hedged runs expose combined equity and option-only equity separately.
- Hedge PnL uses previous hedge quantity for the prior underlying move.
- Real Binance options CSV smoke runs through the same public endpoint contract.

Status: completed.

Implemented:

- Added `OptionStrategyRun`, `GammaScalpingConfig`, and
  `build_gamma_scalping_strategy_run(...)`.
- Added endpoint and engine threading for `strategy_run`, `underlying`,
  `hedge_policy`, and `net_option_delta`.
- Added delta-hedged result artifacts to `OptionBacktestResult`.
- Added a linear quote-currency option equity replay path for full tape MTM.
- Added combined option-plus-hedge equity when a hedge policy is present.
- Updated `benchmarks/gamma_scalping_backtestsample.py` to run synthetic and
  real Binance gamma-scalping samples through `QuantBTEndpoint.options(...)`.
- Documented the gamma-scalping endpoint pattern in `docs/endpoint.md`.

Validation:

- `MPLCONFIGDIR=/tmp PYTHONPATH=/root/bobby/pool_alpha poetry run pytest -q tests/options/test_strategy_adapter_contract.py`
- `MPLCONFIGDIR=/tmp PYTHONPATH=/root/bobby/pool_alpha poetry run pytest -q tests/options`
- `MPLCONFIGDIR=/tmp PYTHONPATH=/root/bobby/pool_alpha poetry run python benchmarks/gamma_scalping_backtestsample.py --snapshots 90 --seed 42`
- `MPLCONFIGDIR=/tmp PYTHONPATH=/root/bobby/pool_alpha:/root/bobby/pool_alpha/alphas_storage/_get_data poetry run python benchmarks/gamma_scalping_backtestsample.py --real-options-csv /root/bobby/pool_alpha/alphas_storage/option_based/options_full_history.csv.gz --underlying-source spot --hedge-timeframe 1h`

Technical debt after Phase 11:

- Delta hedge execution is an accounting path, not yet an order-book/venue
  execution path for the underlying hedge leg.
- Linear quote-currency option path is exact for USD/USDC-style premium and
  settlement. Inverse and quanto hedged combined-equity paths should use the
  multi-currency ledger path or venue-specific conversion audit before being
  called production-certified.
- The gamma adapter is a V1 ATM straddle adapter. More strategy adapters are
  still needed for calendar vol, skew, vertical, dispersion, and option-vol-arb
  workflows.
- If a near-expiry contract disappears from the historical chain before a close
  or settlement event, strategy config should use stricter DTE/liquidity
  filters or provide settlement events. Venue-exact expiry/auto-exercise
  package generation remains a later enhancement.

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

## Historical Start Note

Start with Phase 0, then Phase 1. Do not jump to pricing or endpoint wiring
before schema/convention tests pass. The first code commit should be small:
`AssetType.OPTION`, `options/schema.py`, `options/conventions.py`, and schema
tests only.
