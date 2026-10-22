# ACC-01 Configuration And Migration

Date: 2026-10-22. This describes the implementation in `e13ce0e` (clocks and
funding), `7ba67b8` (reporting), `00e7f16` (options), and
`0969ffeba78f2f0e905ceaf658c8ad75c46e0dc0` (linear execution), with exact-source
amendment tooling in `f7960a3` and final sibling-admission source `70fe9f7`.
It is a configuration/migration reference, not
the phase closure report or a test-run receipt. Test links below identify
source controls; no tests, builds, benchmarks or financial runs were performed
for this documentation subtask. Final gates, performance, artifacts and phase
status belong to the main ACC-01 closeout.

Read with the [repair guide](CURRENT_CAPABILITY_REPAIR_GUIDE.md),
[endpoint contract](../endpoint.md), [option containment](../options_p0_containment.md)
and [Reporting V1](../metrics/PUBLIC_REPORTING.md). Historical receipts retain
their original source and claim boundaries. Neither these changes nor their
source amendments establish external validation, full-package/installed
qualification, a new backend promotion, or release approval.

## Effective Configuration Matrix

The columns describe `NativeEventConfig` orders/commands/callbacks,
`NativeVectorizedConfig` close targets, `NativePortfolioConfig` close targets,
and `NativeOptionConfig`. They do not make every endpoint/backend combination
interchangeable. In particular, a backend named `native` need not execute Rust.

Cell labels: **S = SUPPORTED**, **R = EXPLICITLY_REJECTED**,
**D = COMPATIBILITY_DEFAULT_INACTIVE**. S applies only to the named domain and
boundary. D permits the stated default without implementing its generic
semantics. The final sibling-admission controls below close G1/G2. Test keys
are linked in the final section.

| Field/request | Linear Event | Linear Vectorized | Linear Portfolio | Options |
|---|---|---|---|---|
| `account.initial_capital` | S: positive finite [L1] | S: positive finite [L1] | S: positive finite [L1] | S: converted opening wallet must match [O2] |
| Currency authority | D: `base_currency="USD"` is not an FX account [L1] | D: same [L1] | D: same [L1] | S: `reporting_currency`, wallet and explicit conversion rates; generic `base_currency` default inactive [O1/O2] |
| Leverage | S: positive finite scalar/per-symbol vector [L2] | S: positive finite scalar/vector [L2] | S: positive finite scalar/vector [L1] | D: generic `1.0`; R: other generic leverage [O1] |
| Maintenance ratio | S: finite nonnegative [L1] | S: finite nonnegative [L1] | S: finite nonnegative [L1] | D: generic `0.005`; S: option-margin rates; R: changed generic ratio [O1] |
| Contract multiplier | S: positive finite `contract_size` [L2] | S: positive finite `contract_size` [L3] | S: positive finite `contract_size` [L1/L4] | S: `OptionInstrumentSpec.multiplier == contract_size > 0`, not the generic endpoint scalar [O3] |
| One-way fees | S: nonnegative finite scalar/map [L2] | S: nonnegative finite scalar/map [L2] | S: nonnegative finite config scalar [L1] | S: option execution rate or authoritative fee schedule, with currency [O1/O2/O4] |
| Proportional `slippage_bps` | S: `0 <= bps < 10000` [L2] | S: same [L2] | S: same [L1] | D: generic `0`; R: nonzero generic slippage; execution uses BBO [O1/O4] |
| Quantity steps / `min_qty` | S: resolved order constraints [L4] | S: rounded targets, increasing-delta minima [L3/L4] | S: rounded targets, increasing-delta minima [L1/L4] | D: unset; R: supplied generic constraints; use option instrument spec [G2] |
| `min_notional` / `execution.min_order_notional` | S: maximum of instrument, run and generic notional lower bounds [L2] | S: instrument/run constraints; R: positive generic `min_order_notional` [L3] | S: resolved instrument/run constraint combined with generic lower bound [L1] | D: generic execution minimum `0`; R: positive generic execution minimum [O1] and supplied endpoint minimum [G2] |
| `account.margin_buffer` | D: `0`; R: positive [L1] | D: `0`; R: positive [L1] | D: `0`; R: positive [L1] | S: finite nonnegative report-currency buffer [O2] |
| Margin / OMS model | S: gross cross/netting; R: isolated, cash, portfolio margin or hedging [L1] | S/R: same [L1] | S/R: same [L1] | D: generic cross/netting; R: other generic modes; S: option margin models [O1/O4] |
| Fill clock | S: named V2-close/V3-next-open event contract [E1]; D: generic CLOSE default [G1] | S: CLOSE target contract; R: other generic policies [L3] | S: CLOSE target contract; R: other generic policies [L1] | S: decision-time execution against observable snapshot; D: generic CLOSE; R: other generic policies [O1/O2] |
| Partial fills | D: generic `False`; R: `True` [G1] | D: `False`; R: `True` [L3] | D: `False`; R: `True` [L1] | S: `option_execution.allow_partial_fill`; D: generic `False`; R: generic `True` [O1/O4] |
| Same-bar / margin-rejection flags | D: CONSERVATIVE / `True`; R: alternatives [G1] | D: those defaults; R: alternatives [L3] | D: those defaults; R: alternatives [L1] | D: those generic defaults; R: alternatives [O1] |
| Funding | S: `use_funding` and generic UTC eight-hour interval aggregation [L1] | S: same [L2] | S: same [L1] | D: generic zero rate; explicit funding-off allowed; R: nonzero/Series/map rate, no option funding model [G2] |

### Precedence And Route Boundaries

- A supplied endpoint `account` owns capital/leverage/maintenance; the scalar
  convenience keywords build an account only when one is not supplied.
  `execution=` and `slippage_bps=` are mutually exclusive. Native endpoint
  `fee_rate` is one-way; absent that, legacy round-trip `fee` is divided by two.
- A supplied `option_config` is used as the complete option backend config;
  factory financial overrides conflict and raise rather than silently merge.
  Without one, `options()`
  lowers the endpoint account/execution into `NativeOptionConfig`. An explicit
  `option_execution` supplies its own rate; otherwise it is built from the
  endpoint one-way rate. A `fee_schedule` determines applied fees, even when
  quoted execution fees differ. Do not combine conflicting config styles.
- Option run-level `conversion_rates` update configured rates by currency;
  the resulting rates are checked before financial execution. Direct
  `NativeOptionBackend.run(reporting_currency=...)` can override its report
  currency; the public factory selects it at construction. All wallet/fee
  conversion requirements must still be satisfied.
- Linear run-level leverage, fee and multiplier vectors apply on interfaces
  that expose them, including prepared lowering. Missing mapping entries use
  that interface's default. Package leg fees/multipliers have their own spec
  lowering; inspect the actual request, not a mean result leverage.
- Quantity-step precedence is `qty_step`, then `lot_size`, then legacy
  `slot_size`, then instrument default. Explicit `min_qty` replaces its
  instrument default. Event notional minima additionally retain the maximum
  instrument/run/generic lower bound; vectorized and portfolio use the shared
  explicit-over-instrument resolution, with portfolio adding the generic floor.
  Do not assume identical override rules across these fields.
- Event `prepare_rust_batched_runner` and `prepare_native_strategy_ir` explicitly
  reject a positive generic `min_order_notional`; use constrained
  `run_order_commands` instead. Preparation is not permission to drop a rule.

### Generic Option Defaults

Only `AccountConfig.initial_capital` and `margin_buffer` affect the option
account. The following generic values are accepted solely for compatibility;
changing them raises the indicated `OptionCapabilityError.code` at config
construction and is rechecked on direct backend entry:

| Generic Fields | Inactive Defaults | Non-Default Error |
|---|---|---|
| `base_currency`, `leverage`, `maintenance_ratio`, `margin_mode`, `oms_mode` | `USD`, `1.0`, `0.005`, CROSS, NETTING | `OPTION_GENERIC_ACCOUNT_CONFIG_UNSUPPORTED` |
| `fill_price_policy`, `same_bar_policy` | CLOSE, CONSERVATIVE | `OPTION_GENERIC_EXECUTION_CONFIG_UNSUPPORTED` |
| `slippage_bps`, `min_order_notional` | `0.0`, `0.0` | `OPTION_GENERIC_EXECUTION_CONFIG_UNSUPPORTED` |
| `allow_partial_fill`, `reject_on_insufficient_margin` | `False`, `True` | `OPTION_GENERIC_EXECUTION_CONFIG_UNSUPPORTED` |

Account/execution `metadata` is excluded from these comparisons; it is not an
economic control. Configure `reporting_currency`, `option_execution`, and
`option_margin` (backend config field `margin`) instead. There is no equivalent
option bps-slippage, generic minimum-notional, isolated-collateral or dual-hedge
model to migrate to. Remove the unsupported request or select an actually
supported domain contract; do not substitute a silent default.

## Linear Admission And Attribution Migration

**F01/F05/F08.** Remove zero/nonfinite contract sizes or leverage; zero no longer
means a free or disabled instrument. Disable its orders/targets instead.
Fee rates and quantity minima may be zero, but must be finite/nonnegative.
Slippage at or above `10000` bps is rejected because this existing proportional
model must keep both buy and sell execution prices positive; it is not clamped.
At price 100, short one with 100 bps and 1% fee gives fill 99, fee 0.99 and
equity 998.01 from capital 1000, not a negative-price/negative-fee fill [L2].

Event generic notional floors now actually apply to orders, commands and
callbacks. At price 100, a fresh quantity-one order is rejected by minimum 200
and admitted by minimum 100. A smaller run override cannot erase an instrument
or generic event floor. Minima apply to the actual increasing delta, not the
carried position. Supported risk reductions remain exempt; a `reduce_only`
quantity exceeding the position closes it without reversing [L1/L2/L3].

**F02.** Package leg reports consume executed fee, slippage, funding and
liquidation buffers. They no longer recreate costs from requested targets or
post-liquidation position changes. For close-target liquidation, the remaining
account-equity adjustment is allocated by each open leg's gross close-mark
notional; it is a reporting allocation under the existing zero-equity
liquidation convention, not an exchange liquidation fill or an exit fee.
`price_pnl + fill_pnl - fee + funding_pnl + liquidation_pnl` gives leg total;
positive funding cost appears as negative `funding_pnl`. Reports reconcile
every bar, including liquidation, or raise instead of plugging a residual.

The regression with capital 100, entry fees 2 and liquidation has account
`[100, 98, 0, 0]`: leg fees total 2, funding 0, liquidation PnL -98 and total
PnL -100. No second exit fee or later funding is invented. Consumers can inspect
`leg_pnl_authority="executed_account_buffers_v1"`; the internal attribution
buffer is consumed, not published as an extra retained result path. Ordinary
direct-target/score results do not acquire a ledger merely for reporting [L2].

**F10.** For common leverage, `initial_buying_power = capital * leverage`
remains meaningful. Heterogeneous leverage now yields
`metadata["initial_buying_power"] = None`, not capital times mean leverage.
Event/vectorized metadata adds `buying_power_model="allocation_dependent"`,
`buying_power_reason`, `leverage_by_symbol`, and
`result_leverage_role="legacy_arithmetic_mean_summary_not_capacity"`.
Portfolio also exposes per-symbol leverage and null initial capacity; its
exposure report uses unavailable/NaN `buying_power` with actual margin fields.
Use `sum(abs(notional_s) / leverage_s)` and the route's available-margin field:
capital 1000, notionals 100/100 and leverage 1/10 require IM 110, leaving 890
before other costs. There is no universal notional capacity of 5500 [L1/L2].

## Option Wallet And Financial Admission

**F03/F06/F07/F14.** Value cash before the first fill in `reporting_currency`.
The opening value must satisfy Python `math.isclose(wallet_value,
account.initial_capital, rel_tol=1e-10, abs_tol=1e-8)`, equivalently a difference
no greater than `max(1e-10 * max(abs(wallet_value), abs(capital)), 1e-8)`.
The absolute tolerance is in reporting-currency units. Capital is not silently
overwritten and a mismatched wallet is not booked as a trade loss.

Omitted `initial_balances` and `{}` both mean capital deposited in reporting
currency. An explicitly populated all-zero wallet is different and fails the
positive-capital match. Finite signed balances remain valid, including debit
cash, if their converted total matches. Non-report currency requires an
explicit finite positive conversion rate; report currency converts at 1.
These are constant run rates, not a historical FX series.

For example, these constructors describe matching USD 1000 baselines without
running an account:

```python
from quantbt import QuantBTEndpoint

cash_only = QuantBTEndpoint.options(
    initial_capital=1000.0,
    reporting_currency="USD",
    initial_balances={"USD": 1000.0},
)
mixed_wallet = QuantBTEndpoint.options(
    initial_capital=1000.0,
    reporting_currency="USD",
    initial_balances={"USD": 500.0, "BTC": 0.005},
    conversion_rates={"BTC": 100000.0},
)
```

A USD 1000 wallet with declared capital 20000 now raises before execution,
instead of reporting -95% on an unchanged wallet. A run FX override may itself
make an otherwise matching wallet invalid. Result metadata records
`opening_equity`, `opening_wallet_policy`, `opening_balance_tolerance`, and
`effective_generic_config` with the supported/inactive fields and domain
authorities [O1/O2].

Option `margin_buffer` remains supported: admission requires post-cost equity
to cover option IM plus the report-currency buffer. `margin_timeline_report`
shows `available_collateral = equity - (initial_margin + buffer)`; maintenance
uses the option requirement, not the inactive generic ratio. Margin rates,
scenario shocks, external requirements, cash, FX, fee results and settlement
amounts must be finite and domain-valid. External-validator requirements are
checked for nonnegative finite margin/detail values, matching currency and
boolean `venue_exact`; the validator receives a clone. Existing approximation formulas
are unchanged, not upgraded to venue-exact risk [O1/O2/O4].

## Option Time, Fees And Settlement

**F04/F15.** A quote at 00:00 can support a decision at 00:30 if the existing
freshness policy permits it. `Fill.timestamp`, effective ledger time, account
snapshots and common fee time are 00:30, never 00:00. Preserve
`quote_timestamp_ns` separately from `decision_timestamp_ns` and
`effective_timestamp_ns`; a ledger override cannot backdate the effective fill.
Use `option_execution.max_quote_age_ns` for freshness. Same-time packages are
ordered by `(timestamp_ns, package_id)`, not input order [O2/O3].

`fills_report` separates `execution_fee` (quote), `applied_fee`, `fee_currency`,
`fee_conversion_rate`, `fee_reporting_currency`, `fee_reporting_value`, and
`fee_conversion_timestamp_ns`. The policy is explicitly
`constant_run_rate_at_effective_event`. Applied fee 0.0000021 BTC at 100000
USD/BTC gives common `result.fees` of 0.21 USD at the effective event. Multiple
fills at one instant aggregate there; costs are not dumped into the final row
or spread across bars. `contract_notional` includes the instrument multiplier;
do not reinterpret the raw fill quantity-times-price as a report-currency
notional [O2/O4].

`accounting_reconciliation["reconciled"]` means applied fill fees match ledger
fees by denomination and converted common fees. Its `reconciliation_scope` is
`applied_fill_fees_equal_ledger_fees_not_full_account_reconciliation`.
`common_fee_reporting_value` and `ledger_fee_reporting_value` use report units.
This flag alone does not certify the full account; inspect `equity_identity`,
cash, marks, settlement and margin evidence separately. Nonfinite monetary
values cannot establish reconciliation [O1/O2].

Option and delta-hedge consumers retain the authoritative event snapshots,
option positions, fees, multipliers and settlements. There is no synthetic
`first_timestamp - 1ns` row. The first recorded return includes any first-fill
cost relative to declared capital; `option_equity` is the option-only path and
`equity` includes the hedge when requested. Underlying prices may be carried
forward only from observable data, never backfilled from the future. Option
result indices are UTC instants represented as timezone-naive values; use the
explicit UTC reporting/accounting declaration below [O2].

**F13.** Expiry now retires the remaining signed entry premium basis exactly
once. Gross payoff cashflow, realized PnL and fees are distinct. In the inverse
BTC fixture, long entry 0.02 and payoff 0.20 realize +0.18 BTC; short realizes
-0.18; long OTM realizes -0.02. The already-correct payoff cash movement does
not change. Partial closes leave only remaining quantity/multiplier basis to
retire; fees remain separate. Duplicate settlement raises without mutation.

If premium and settlement denominations differ, preserve
`realized_pnl_by_currency`, not an arithmetic subtraction of unlike currencies.
For premium 100 USD and payoff 5000 USDC, the realized components are
`{"USD": -100, "USDC": 5000}`. The mixed-currency settlement event's scalar
`realized_pnl` is `None`; per-position realized PnL is not a cross-currency
total. Any report-currency aggregation needs the explicit conversion policy.
This repair adds no FX attribution methodology or settlement model [O3].

## Clocks And Funding Migration

**F09/F16.** `NativeAccountingArrays.from_result` normalizes physical instants
to UTC nanoseconds before integer storage; `.datetime_index` reconstructs an
ns-resolution UTC-aware clock. ns/us/ms/s inputs preserve the same elapsed
duration, not reinterpreted integers near 1970. Aware timestamps may have any
timezone. Naive completed results require `naive_timezone="UTC"` explicitly;
other naive accounting declarations are rejected. The source result is not
modified. Empty, NaT, duplicate, unordered and ns-overflow clocks fail [C1].

Strict `prepare_market_tape` separately accepts `source_timezone` to localize
naive market/funding input, then converts to UTC ns before alignment, signatures,
certificates and native lowering. Explicit event-rate Series must align by
physical instant, not merely length. Equivalent physical tapes have canonical
identities; obsolete certificates now fail with a request to reprepare from
source. The validator is `market_tape_v2`, not permission to reuse an old
incorrectly scaled persisted tape [C1].

**F17.** Funding remains two different contracts:

- Generic linear preparation aggregates UTC 00:00/08:00/16:00 events in the
  carried interval and settles with its documented close-price proxy. A daily
  interval can contain three events. A rate is per event or the resulting
  interval sum, not automatically per bar [L1].
- Strict intrabar `POSITION_AT_EVENT` uses explicit exactly aligned events or
  aligned Series/mappings and the declared open/close timestamp semantics.
  Explicit first-bar events are rejected because no prior interval exists;
  an aligned first-row rate is validated but its event mask stays false.
  At an open-stamped event, funding precedes the new entry; at a close-stamped
  event, funding can see that entry. It is not remapped to the generic calendar.
  Nonzero scalar funding is not a substitute for event-causal input [C1].

All active packed/event/Series/mapping rates, including aligned first-row rates,
must be finite before a `finite_ok=True` certificate. Finite negative rates are
valid: long one at 100 with +0.01 funding costs 1; -0.01 credits 1. Preserve
the event clock when migrating, rather than replacing NaN rates with zero [C1].

## Reporting And Snapshot Migration

**F18.** With opt-in Reporting V1 and an explicit return witness, equity
`[100, 0, 0]` preserves account total return -1, max drawdown 1 and final equity
0. Elapsed CAGR/Calmar and period-return metrics that need the zero denominator
are `status="undefined"`, `value=null`, with a nonpositive-equity reason.
Period count/sample counts and first undefined time remain disclosed. Valid
independent execution, closed-trade and closed-action groups survive if their
own witnesses exist; missing ledgers remain `unavailable`, not inferred.

Do not drop bankruptcy rows or invent zero period returns. A terminal zero
with positive prior denominators, such as `[100, 100, 0]`, can still have valid
arithmetic period statistics while geometric statistics are undefined.
The low-level derivation API still raises typed `UndefinedPeriodReturn`;
the completed-result adapter catches only that disposition. Bad timestamps,
scope, masks, identities and unrelated `ValueError`s still raise. Legacy
reports and scientific objective dictionaries are not replaced by this grouped
contract [R3].

**F11.** Reporting snapshots keep immutable byte storage and private ndarray
headers. NumPy may still permit assigning a new dtype/shape/strides/data header;
reducers, cache lookup and retained episode readers reject changed headers with
`reporting snapshot array header changed; construct a new snapshot`. Content
immutability alone is not enough for a valid cache identity. Construct a fresh
snapshot, for example with `dataclasses.replace`, to change observations.
Copy/deepcopy/pickle reconstruction revalidates and recomputes identities.
Warm typed-reducer cache hits check headers, not an O(N) content hash. Public
calls still freshly snapshot/hash mutable completed-result input, including on
cache hits. Pickle remains unsafe for untrusted input [R1].

**F12.** Two finite 1e308 outcomes can overflow their sum. Affected metrics
are `invalid` with null values and numeric-overflow reasons; provenance uses
null plus `numeric_issues` keyed by the affected path. Counts, membership,
costs, holding periods and other representable statistics remain available.
If one action's combined PnL overflows, its sign-dependent classifications are
invalid, not a fabricated breakeven. Ratios with overflowed loss denominators
are not reported as zero. Strict JSON remains finite/null, and a no-loss
population retains its distinct `no_loss` status. Read status/reason/unit/sample
count, not only the numeric value [R2].

## Remaining Limits And Sibling Admission

Linear accounts remain gross-cross/netting with the existing simultaneous
adverse-OHLC/zero-equity liquidation convention. Simultaneous adverse marks
need not be a realizable joint market path. There is no isolated collateral,
dual hedge inventory, exchange tiers, mark-price or partial liquidation model.
Options remain Python-primary snapshot BBO execution with their existing
cash/margin/settlement contracts. Maker-touch and opted-in future-then-cash
bridges remain research approximations. No queues, latency, new option risk,
historical FX or new financial/scientific models are introduced.

Documentation inspection identified two additional same-responsibility admission
gaps; the final ACC-01 addendum closes them with targeted controls:

- **G1:** `NativeEventConfig.__post_init__` now rejects non-default generic `fill_price_policy`,
  `same_bar_policy`, `allow_partial_fill`, or
  `reject_on_insufficient_margin`. Use the named event `execution_contract`
  for clocks; generic CLOSE remains an inactive default even for named V3.
  Slippage and minimum-notional retain their supported controls.
  Source: [event backend](../../src/quantbt/backends/native_event.py).
- **G2:** Options reject non-default generic `contract_size`, supplied generic
  quantity constraints/clock and nonzero or Series/mapping `funding_rate` at
  factory and direct execution boundaries. Instrument multiplier and option
  execution remain the authorities. Default scalar multiplier1/zero funding
  are inactive; explicit `use_funding=False` is permitted. A complete
  `option_config` plus facade financial overrides raises
  `OPTION_CONFIG_OVERRIDE_CONFLICT`. Source:
  [endpoint admission](../../src/quantbt/options/endpoint_validation.py).

G1/G2 controls are in [endpoint-admission tests](../../tests/options/test_acc01_endpoint_admission.py).
They do not add partial-fill/event clock or generic option funding capabilities.

## Source Test References

These are regression source references, not new execution or qualification
claims. F/T labels match the repair guide; historical controls remain scoped
to their own contracts.

| Key | Test File | Named Controls / Findings |
|---|---|---|
| L1 | [test_portfolio_account_review_fixes.py](../../tests/test_portfolio_account_review_fixes.py) | `test_account_capabilities_fail_closed`, `test_nonfinite_account_values_rejected`, `test_order_minima_apply_to_increasing_delta_and_allow_reduction`, funding, fees and heterogeneous capacity |
| L2 | [test_acc01_event_vectorized.py](../../tests/test_acc01_event_vectorized.py) | T01/F01 positive vectors; T02/F02 liquidation and non-liquidating package identity; T05/F05 maximum minima and reduce-only; T08/F08 positive fills; T10/F10 capacity |
| L3 | [test_vectorized_account_review_fixes.py](../../tests/test_vectorized_account_review_fixes.py) | Increasing-delta minima, reductions, fees, slippage, first-bar and adverse-OHLC timing; alternate-config rejection is also explicit in `NativeVectorizedConfig` |
| L4 | [test_shared_quantity_constraints.py](../../tests/test_shared_quantity_constraints.py), [test_portfolio_legacy_review_fixes.py](../../tests/test_portfolio_legacy_review_fixes.py) | Quantity aliases, public linear routes, multiplier sizing and legacy capability rejection |
| E1 | [test_phase51a_v3_next_open.py](../../tests/native_event/contract/test_phase51a_v3_next_open.py) | Named V2/V3 clocks, real opens, gap rules, explicit/reactive/prepared causality, first/final bar |
| O1 | [test_acc01_configuration.py](../../tests/options/test_acc01_configuration.py) | T06/F06 generic option rejection; T07/F07 finite/external margin; T14/F14 financial/config admission |
| O2 | [test_acc01_reporting.py](../../tests/options/test_acc01_reporting.py) | T03/F03 matching/mismatched wallets on direct/tape/cache/endpoint; T04/F04 fee currencies; T15/F15 decision time, freshness, same-time ordering; supported buffer and hedge consumers |
| O3 | [test_acc01_lifecycle.py](../../tests/options/test_acc01_lifecycle.py) | T13/F13 long/short ITM/OTM, multiplier/partial basis, mixed currencies, duplicate settlement; T14/F14 mutation safety; T15/F15 backdating rejection |
| O4 | [test_phase4_execution.py](../../tests/options/test_phase4_execution.py), [test_phase5_fees.py](../../tests/options/test_phase5_fees.py), [test_phase6_margin.py](../../tests/options/test_phase6_margin.py) | Existing BBO/partial-fill/fidelity, fee-cap and approximation/external-margin contracts |
| C1 | [test_acc01_clocks_funding.py](../../tests/test_acc01_clocks_funding.py) | T09/F09 UTC accounting/report roundtrip; T16/F16 canonical market/event/session identities; T17/F17 finite signed funding, first-bar/alignment and event-position ordering |
| R1 | [test_acc01_snapshot_headers.py](../../tests/metrics/test_acc01_snapshot_headers.py) | T11/F11 account/return/execution/episode headers, cache and fresh reduction, private bases, copy/pickle and no warm content scan |
| R2 | [test_acc01_ledger_overflow.py](../../tests/metrics/test_acc01_ledger_overflow.py) | T12/F12 JSON-safe finite-input overflow, unaffected populations/statistics, no false zero ratios or breakevens |
| R3 | [test_acc01_bankruptcy_reporting.py](../../tests/metrics/test_acc01_bankruptcy_reporting.py) | T18/F18 independent report groups, undefined periods, strict low-level errors, cache and malformed-input controls |
| S1 | [test_acc01_source_guard.py](../../tests/test_acc01_source_guard.py) | Exact amended blobs, tamper rejection, digest locks and no reissued historical financial claims; not a financial or package qualification |
