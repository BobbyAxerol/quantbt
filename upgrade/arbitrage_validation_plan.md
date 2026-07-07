# Arbitrage Validation Status And Test Plan

Date: 2026-07-07
Branch: dev

This note is intentionally conservative. It records what has been tested, what
is only a foundation, and what must still be validated before QuantBT arbitrage
can be treated as institutional-grade for research production.

## Current Status

Arbitrage is implemented through Phase G.1.

Implemented and tested:

- Phase A: public arbitrage schema and deterministic package order plan.
- Phase B: advanced schema models and validation guardrails.
- Phase C: native-event basis arbitrage for package market entry/exit.
- Phase D: native-event stat-arb pair via frozen basket execution.
- Phase E: native-vectorized arbitrage fast path for basis and stat-arb.
- Phase F: Nautilus package-order validation adapter.
- Phase G.1: advanced package-style specs and generic native event/vectorized
  execution for calendar spread, funding arbitrage, spot-perp cash carry, and
  index-basket arbitrage.

Not fully complete:

- Cross-exchange arbitrage execution.
- Triangular arbitrage execution.
- Options volatility arbitrage execution.
- Venue-specific margin offsets for real exchanges.
- Quarterly/futures instrument wiring in Nautilus.
- Real exchange precision/min-notional fixtures for all symbols and venues.
- Real strategy notebooks / historical-data parity reports.

## Why Phase G.1

Phase G in the roadmap contains several arbitrage families with different
execution truth models. Some can be represented as a frozen package of target
units. Others cannot.

Phase G.1 means:

- Advanced specs now have domain validation.
- Package-style advanced arbs can run through native event and vectorized
  engines.
- Specialized arbs intentionally remain explicit gaps instead of being forced
  into the wrong engine.

Package-style specs currently supported by generic engines:

- `CalendarSpreadSpec`
- `FundingArbitrageSpec`
- `SpotPerpCashCarrySpec`
- `IndexBasketArbSpec`

Specialized specs intentionally not executed by generic engines:

- `CrossExchangeArbSpec`: needs venue/account split, transfer/borrow constraints,
  and venue-specific margin.
- `TriangularArbSpec`: needs order sequence, latency, partial-fill propagation,
  and path PnL.
- `OptionsVolArbSpec`: needs option instruments, Greeks, IV surface, expiry,
  exercise/assignment, and delta/vega hedge behavior.

## Tests Already Added

Unit and integration tests exist under:

- `tests/test_phase8_arbitrage_phase_a.py`
- `tests/test_phase8_arbitrage_phase_b.py`
- `tests/test_phase8_arbitrage_phase_c.py`
- `tests/test_phase8_arbitrage_phase_d.py`
- `tests/test_phase8_arbitrage_phase_e.py`
- `tests/test_phase8_arbitrage_phase_f.py`
- `tests/test_phase8_arbitrage_phase_g.py`

Current full test suite result after Phase G.1:

- `86 passed`

Important covered cases:

- Equal base quantity basis sizing, not equal notional sizing.
- Frozen units until exit.
- Atomic all-or-none package rejection on precision/min-notional failure.
- Best-effort package behavior with rejected legs visible.
- Per-leg fee rates in native event and vectorized paths.
- Funding applied only to `funding_enabled=True` legs.
- Package PnL decomposition into leg PnL and package PnL reports.
- Stat-arb beta/hedge-ratio freeze on entry.
- Optional beta drift rebalance threshold.
- Native event vs native vectorized parity under deterministic market-fill
  assumptions.
- Nautilus package-order mapping and optional Nautilus package-order smoke.
- Domain validation for advanced specs.
- Generic engine refusal for specialized specs that need a separate execution
  model.

## What Has Not Been Proven Yet

The tests above are necessary but not sufficient. They prove deterministic
mechanics on controlled data, not real production correctness.

Still unproven:

- Real Binance USD-M / COIN-M contract precision across many symbols.
- Real quarterly/futures contract instrument setup in Nautilus.
- Funding timestamp alignment against exchange funding windows on real data.
- Liquidation parity across package hedges under stressed intrabar high/low.
- Slippage and fee parity between native event, vectorized, and Nautilus.
- Partial-fill semantics for package trades.
- Cross-venue account/margin behavior.
- Real basis trade PnL against independent exchange/account calculations.
- Real stat-arb strategy behavior from notebook/service entrypoints.
- Multi-day/multi-year performance and memory behavior for large universes.

## Required Test Matrix Before Trusting Arbitrage

### 1. Native Engine Golden Tests

Add more deterministic tests for:

- Long basis and short basis.
- Open, hold, exit, re-enter.
- Entry at bar 1 and no accidental bar-0 fills.
- Fees on entry and exit per leg.
- Slippage on buy vs sell legs.
- Funding positive, negative, and zero.
- Funding paid by long and received by short.
- Liquidation under worst intrabar high/low.
- Margin reject on one leg and full package rejection.
- Best-effort package with visible residual exposure.
- `qty_step`, `min_qty`, `min_notional`, and `contract_size` interactions.
- Missing data / NaN data / timezone data.

### 2. Native Event vs Vectorized Parity

For every package-style spec:

- same target units;
- same equity curve under zero slippage;
- same fees and funding;
- same package PnL;
- same final positions;
- visible and explained divergence when event behavior cannot be vectorized.

Required specs:

- basis;
- calendar spread;
- funding arb;
- stat-arb pair;
- index basket;
- spot-perp cash carry.

### 3. Nautilus Adapter Compatibility

Need to validate:

- package order timestamps map to Nautilus bar timestamps correctly;
- multi-instrument order submission happens once per package timestamp;
- fills map back to package ids and leg roles;
- account report vs reconstructed equity difference stays explainable;
- native event vs Nautilus on synthetic deterministic market data;
- unsupported instruments fail clearly;
- quarterly/futures instruments are added before trusting basis futures in
  Nautilus.

Current Nautilus caveat:

- The helper supports Binance perpetual test/synthetic instruments. It does not
  yet model Binance quarterly futures. Basis validation between perpetual and
  quarterly in Nautilus is therefore not complete.

### 4. Real Strategy Tests

Need real notebook/service validation for:

- basis trading: BTCUSDT perpetual vs BTCUSDT quarterly;
- funding arbitrage: two perpetual venues or two perpetual instruments;
- stat-arb pair: e.g. BTC/ETH or SOL/ETH with dynamic beta;
- index/basket: ETF/index proxy vs basket components;
- spot-perp cash carry: spot vs perpetual/future.

For each real strategy:

- run native event;
- run native vectorized;
- run Nautilus if instrument support exists;
- compare final equity, trade count, target units, fills, fees, funding, and
  drawdown;
- inspect `package_target_units`, `leg_pnl_report`, `package_pnl_report`,
  `carry_report`, and `spread_report` / `beta_drift_report`;
- save the report output and sample rows.

## Can The Agent Simulate Strategies?

Yes, the agent can generate synthetic strategies and data for deterministic
tests. This is enough for:

- engine mechanics;
- parity between native event and vectorized;
- funding/fee/slippage math;
- package target-unit behavior;
- rejection and validation cases.

The user should provide or confirm real data/strategy notebooks for:

- exchange-specific contract details;
- real quarterly/futures symbols;
- real funding rates;
- real alpha signals;
- expected behavior from an external reference or manual calculation.

Synthetic tests can prove consistency. Real strategy tests are needed to prove
the assumptions match the user's trading domain.

## Remaining Phases Estimate

Recommended phases before calling arbitrage contribution-ready:

### Phase H - Deterministic Golden Test Expansion

Goal:

- Add the full native engine golden matrix for package mechanics.

Expected output:

- More tests for margin, liquidation, slippage, funding, precision, and
  rejection.

### Phase I - Nautilus Instrument And Parity Hardening

Goal:

- Add quarterly/futures instrument support or a documented synthetic future
  fixture.
- Run native event vs Nautilus parity on deterministic package fills.

Expected output:

- Nautilus basis validation no longer limited to perpetual-only instruments.

### Phase J - Real Strategy Validation Harness

Goal:

- Add scripts/notebooks that run real strategies from user data and save
  comparison reports.

Expected output:

- Reproducible outputs for basis, stat-arb pair, and basket-style arbitrage.

### Phase K - Specialized Arb Engines

Goal:

- Implement cross-exchange, triangular, and options-vol engines separately.

Expected output:

- No forced generic package model for execution types that need sequencing,
  venue/account state, latency, or Greeks.

### Phase L - Documentation And Public Examples

Goal:

- Write user-facing docs and minimal examples for every supported arbitrage
  type.

Expected output:

- A contributor can run examples and understand which backend to choose.

Rough estimate:

- Package-style arbitrage contribution-ready: 3 more focused phases
  (H, I, J).
- Full arbitrage family contribution-ready including cross/tri/options:
  5 or more phases depending on instrument data and execution assumptions.

## Current Recommendation

For user strategies needed soon:

- Use `StatArbPairSpec` and `IndexBasketArbSpec` if the strategy is a package of
  frozen target units.
- Use `BasisArbitrageSpec` native event/vectorized for internal validation.
- Treat Nautilus basis validation as incomplete until quarterly/futures
  instrument support is added.
- Do not use `CrossExchangeArbSpec`, `TriangularArbSpec`, or
  `OptionsVolArbSpec` for production simulation yet.

The next best phase is Phase H: expand deterministic golden tests before adding
more features.
