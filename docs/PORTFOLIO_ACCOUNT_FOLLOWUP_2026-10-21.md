# Current-Capability Account And Metrics Follow-Up

Date: 2026-10-21 UTC. Reviewed checkout: `1bd3d3d`; financial source remains
the exact approved `9c2bfd9` tree. This is an assessment, **not a repair or
release**. It does not propose an order-book simulator, exchange-exact
liquidation, isolated wallets or hedge inventory.

The [previous repair](portfolio_review/REPAIR_REPORT.md) and its passing receipts
remain valid evidence for their executed controls. They are not proof that all
other configuration/reporting paths are free of defects. This follow-up finds
additional gaps within existing capabilities, including related code outside
the repaired generic portfolio attribution path.

## Method And Evidence

- Five retained scripts execute 32 small controls, including matched positive
  controls and deliberately invalid-input rejection controls. No optimizer,
  private alpha, market download, build, installation, JIT or CI is involved.
- Generic event controls exercise `run_orders`, `run_order_commands` and
  `run_strategy` with `native_backend="python"`; vectorized controls use the
  current Numba kernel's Python execution with JIT disabled. The new cases have
  not been requalified on a freshly loaded Rust extension.
- Option controls reuse the existing public synthetic option fixtures. The
  report does not change their margin approximation or interpret it as a venue
  certificate.
- All findings below were reproduced by the main review process; static-only
  suggestions were not promoted into confirmed findings.
- Machine-readable observations, input/source hashes and no-scratch cleanup
  disposition: [follow-up receipt](portfolio_review/evidence/followup-review.json).

## Priority Findings

### F01: Invalid Event Multiplier Still Executes (P1)

All three generic event entrypoints accept `contract_size=0`. One BUY contract
at price100 produces one fill and position1, but equity stays1000, fees0 and
initial margin0. The matched multiplier1 control pays fee1 and locks margin100.
The boundary must reject a nonpositive multiplier rather than simulate free
exposure. [Override validation](../src/quantbt/backends/native_event.py), line7402.

Do not generalize this to all invalid fees: `fee_rate=-0.01` was explicitly
rejected on all three routes and is a passing negative control.

### F02: Package Attribution Invents Post-Liquidation Flows (P1)

Public `NativeVectorizedBackend.run_basis_arbitrage` on a constant-close
two-leg account, capital100, leverage100, notional1000 per leg and fee0.001:

| Observation | Actual account | Leg report |
| --- | --- | --- |
| Equity path | `[100, 98, 0, 0]` | Not an equity path |
| Fees at liquidation bar | 0 | 2 |
| Funding at liquidation bar | 0 | +10 credit |
| Whole net PnL | -100 | +6 |

The kernel liquidates before funding. The cold report reconstructs costs from
the position transition to flat, invents a normal close/funding event and omits
the declared liquidation write-down. Raw account arrays are not the same as
this incorrect report. [Leg reducer](../src/quantbt/backends/native_vectorized.py), line1635.

### F03: Option Opening Wallet And Metric Baseline Can Disagree (P1)

An empty options run with `initial_balances={"USD": 1000}` and
`AccountConfig(initial_capital=20000)` returns equity `[1000,1000,1000]`, no
fills, but `total_return_pct=-95`. Matching the declared capital to1000 returns0%.
The mismatch must be rejected or resolved through an explicit opening-baseline
contract; it must not be reported as investment loss.
[Opening wallet](../src/quantbt/backends/native_option.py), line206;
[reported capital](../src/quantbt/options/reporting.py), line203.

The existing `accounting_reconciliation.reconciled=True` in this control checks
fee aggregation, not whole-account opening-baseline consistency. Do not cite
that boolean as proof of full accounting reconciliation.

### F04: Common Option Fee Series Has The Wrong Currency Contract (P1)

Reporting currencyUSD, BTC conversion100000 and one synthetic option fill:
the authoritative ledger fee is0.0000021BTC =0.21USD. `result.fees.sum()` is
0.0000021, however, and is placed entirely at the final retained row.
The common fee series is neither reporting-currency aligned nor event-time
aligned. The ledger's converted fee reconciliation is correct; consumers of
the common result field can misinterpret the cost by100000x.
[Common fee adaptation](../src/quantbt/options/reporting.py), line189.

### F05: Generic Event Minimum Notional Is Ignored (P2)

On orders, commands and callback strategy, setting
`ExecutionConfig(min_order_notional=200)` still accepts a fresh100-notional
entry. Passing `min_notional=200` directly to the same backend rejects it.
This is configuration propagation, not a reduce-only exemption or a new
execution model. [Constraint construction](../src/quantbt/backends/native_event.py), line4888.

### F06: Options Accept Inactive Generic Configuration (P2)

Changing option `AccountConfig` to `ISOLATED/HEDGING` produces the same equity,
positions and one fill as the default. Likewise generic `ExecutionConfig`
with OPEN, slippage1000bps and minimum1e9 produces the same0.021 fill and the
same final equity19949.79. These flags are accepted without taking effect.
[Option config validation](../src/quantbt/backends/native_option.py), line81.

The correct containment is explicit unsupported/inactive-option handling. This
finding does **not** require implementing isolated/hedging or forcing the
linear close-fill model onto the option snapshot executor. The option-specific
configuration remains a distinct contract.

### F07: Nonfinite Option Margin Configuration Alters Execution (P2)

`OptionMarginConfig(long_option_margin_rate=NaN)` is accepted. The matched
default run has one fill, position1 and final equity19949.79; the invalid run
has two fills, ends flat and returns19899.79. Nonfinite margin reaches the
maintenance comparison and creates an extra liquidation. Invalid input must
fail at the boundary. [Validation](../src/quantbt/options/margin.py), line51;
[maintenance comparison](../src/quantbt/options/authority.py), line47.

This does not review or replace the scientific formula of the existing margin
approximation; that formula remains a separate contract review question.

### F08: Vectorized Slippage Can Produce Negative Execution Prices (P2)

`slippage_bps=20000`, price100, a fresh short1 and fee_rate0.01 is accepted.
The implied sell price is-100, recorded fee is-1 and equity becomes801.
The matched100bps control records positive fee0.99 and equity998.01. The generic
portfolio already rejects this invalid price-producing slippage; vectorized
configuration must apply the equivalent boundary guard.
[Vectorized config](../src/quantbt/backends/native_vectorized.py), line79.

### F09: Result-To-Array Conversion Loses Clock Resolution (P2)

`NativeAccountingArrays.from_result` stores raw resolution-dependent integers
and reconstructs them as nanoseconds. For equivalent daily ns/us result
indices, the authoritative horizon is172800seconds in both cases; the us
conversion reconstructs172.8seconds and moves the starting date to1970.
Ordinary `result.full_report()` already agrees between ns/us after the prior
repair; this remaining defect is in the conversion boundary and downstream
consumers, not that repaired reducer.
[Conversion and reconstruction](../src/quantbt/core/results.py), lines199/222.

### F10: Mean-Leverage Buying Power Remains On Other Routes (P2)

Capital1000, two symbols with leverage1/10: vectorized and all three tested
event routes still advertise `initial_buying_power=5500`. Actual IM for100
notional on each symbol is110, correctly recorded. There is no universal
allocation-independent5500 notional capacity. Match the generic portfolio's
unavailable scalar plus explicit leverage/margin disclosure.
[Vectorized metadata](../src/quantbt/backends/native_vectorized.py), line849;
[event metadata](../src/quantbt/backends/native_event.py), line5035.

## Lower-Priority Hardening

### F11: Read-Only Array Headers Can Still Break Cache Identity (P3)

After caching `[100,110]`, assigning `observations.equity.dtype=np.int64`
succeeds while element storage remains read-only. The identity is unchanged;
cached total return stays0.1, uncached reduction becomes
`4.637440978796413e16`. This requires explicit ndarray-header mutation, not
ordinary element writes. Protect or validate the exposed header/shape/dtype
contract without hashing the full account path on every cache lookup.
[Snapshot identity](../src/quantbt/metrics/reporting/inputs.py), line108;
[cache lookup](../src/quantbt/metrics/reporting/cache.py), line40.

### F12: Finite Ledger Inputs Can Overflow Strict JSON Provenance (P3)

Two finite recorded outcomes of1e308 each cause `reduce_ledger` to abort with
`ValueError: Out of range float values are not JSON compliant: inf`. Some metric
values are guarded, but aggregate provenance bypasses those guards. Explicit
invalid-metric/report status is preferable to an accidental serialization
exception. This is an extreme numeric-boundary case, not evidence that normal
strategy outcomes currently overflow.
[Provenance aggregation](../src/quantbt/metrics/reporting/ledger.py), line215.

## What Is Not A New Bug

- Unimplemented isolated wallets, hedge inventory, venue tiers, mark-price
  liquidation, queue/latency models are intentionally outside this review.
- Declared legacy period/state metrics are not closed-trade/action estimators.
  Their new population labels do not manufacture an outcome ledger.
- Closed-trade/action UNAVAILABLE with missing authoritative ledger/horizon
  is correct fail-closed behavior.
- The repaired generic portfolio arithmetic controls and direct ns/us metric
  controls remain passing historical evidence. Other paths must not inherit
  that certification by endpoint-name similarity.
- No claim is made that a newly discovered Python-path defect was reproduced
  in Rust; parity/containment for each modified boundary belongs to a repair.

## Recommended Bounded Closure

1. Fix current-contract monetary and clock/report correctness: F01-F04/F09.
   Consume authoritative execution/currency/baseline evidence, not synthetic
   reconstruction from target or position changes.
2. Standardize financial input and effective-config validation across the
   current routes: F05-F08/F10. Reject unsupported settings; do not add a venue
   simulator or alter strategy methodology.
3. Close F11/F12 with focused boundary tests, then run relevant route/parity
   regression and cleanup. Full release/package qualification remains separate.

No implementation phase was launched or added to the unified plan. No
production source, release identity or owner working edit was changed. This
report must not be labelled a clean release gate; the findings remain OPEN.
