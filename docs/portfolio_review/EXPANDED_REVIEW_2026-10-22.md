# Expanded Account And Metrics Review

Date: 2026-10-22, Asia/Saigon. Status: **OPEN FINDINGS / PLANNING ONLY**.
This supplements the [twelve original findings](../PORTFOLIO_ACCOUNT_FOLLOWUP_2026-10-21.md),
without modifying their receipts or the earlier completed repair certificate.
The [new machine-readable receipt](evidence/expanded-planning-review.json)
records 22 additional synthetic controls and six additional confirmed findings.
These are observations of defects and matched controls, not 22 passing repair
tests or a comprehensive clean bill of health. All financial executions used
Python with JIT disabled; no new Rust execution, optimizer, build or install ran.

The proposed single [ACC-01 phase](../../upgrade/implement.md#account-metrics-acc-01)
and its [implementation/test guide](CURRENT_CAPABILITY_REPAIR_GUIDE.md) cover
F01-F18. Execution awaits owner approval. Current runtime/release files remain
unchanged at financial source `9c2bfd9`; review HEAD was `bd8df95`.

## F13: Expiry Realized PnL Omits Entry Premium (P2)

An inverse call starts with 1 BTC, buys one contract at 0.02 BTC and expires
with payoff 0.20 BTC. Cash correctly ends at 1.18 BTC, but both ledger and
position `realized_pnl` report 0.20 rather than 0.18 BTC. The short control
ends at 0.82 BTC but reports -0.20 rather than -0.18 BTC. An OTM long correctly
ends with 0.98 BTC but reports realized PnL 0 instead of -0.02 BTC.

[OptionLedger.apply_settlement](../../src/quantbt/options/ledger.py), around
line 152, adds settlement cashflow directly to realized PnL. This differs from
`_apply_position`, which deducts average entry cost when closing by a fill.
`settlement_cashflows` should continue to report gross payoff; realized PnL
must account for the cost basis of the quantity being closed. The demonstrated
cases have the same premium/settlement currency, zero fees and no FX change.
They identify a ledger/report classification defect, not incorrect terminal
cash or evidence of every mixed-currency settlement being wrong.

## F14: Nonfinite Option Money Inputs Reach Accounting (P1)

Beyond F07's margin configuration, actual backend controls accept NaN opening
cash, FX conversion, execution fee and fee-schedule amount. These return NaN
equity instead of failing admission. Invalid FX also causes an extra liquidation
in the control. A NaN settlement price passes `OptionSettlementEvent` and
`settle_option_expiry`, contaminating the wallet with NaN.

Relevant boundaries: [ledger and conversion](../../src/quantbt/options/ledger.py),
[execution configuration](../../src/quantbt/options/execution.py),
[fee schedules](../../src/quantbt/options/fees.py),
[settlement event](../../src/quantbt/backends/native_option.py) and
[payoff conversion](../../src/quantbt/options/lifecycle.py). Existing `<= 0`
or `< 0` tests do not reject NaN. Validation must distinguish permitted signed
cash balances from required-positive FX/prices and nonnegative fees; do not
invent a blanket prohibition on legitimate debit balances.

The invalid cash/FX control can report `equity_identity.reconciled=True`.
That object is an algebraic decomposition, not an independent all-events
reconciliation. Invalid financial values must never receive a valid status.
Fee reconciliation has its own, narrower scope and must be described as such.

## F15: Option Fills And Ledger Events Are Backdated To Quotes (P2)

Quotes at 00:00 and 01:00; package decision at 00:30. The public backend executes
using the permissible 00:00 quote, but stamps both the fill and ledger event
00:00. The equity mutation is recorded at 00:30. The recorded fill therefore
precedes its decision by **1,800 seconds**, and the event sources disagree.
The on-quote-time control has no discrepancy.

[Snapshot execution](../../src/quantbt/options/execution.py), around line 361,
uses the snapshot timestamp for `Fill.timestamp`;
[ledger admission](../../src/quantbt/backends/native_option.py), around line 680,
propagates it. Keep quote/source time as separate provenance; effective execution
time must agree with the actual decision/ledger timeline under this snapshot
execution contract. This finding does not require queue/latency simulation or
new prices. Any hedge/report consumer that buckets these events must be checked.

## F16: Intrabar Preparation Mislabels Timestamp Resolution (P2)

Identical three hourly bars represented as ns/us are accepted. The ns execution
has a 7,200-second horizon in 2024; the us execution has a **7.2-second** horizon
in 1970. A funding event describing the same instant in ns against a us market
is incorrectly rejected as unaligned.

[Market packing](../../src/quantbt/core/market_tape.py), around lines 156,
306 and 415, uses raw resolution-dependent integers as `timestamps_ns`.
This is upstream execution/funding preparation, separate from F09's downstream
`NativeAccountingArrays.from_result` conversion. Test both boundaries; fixing
only one does not fix the other. Normalize UTC resolution before comparison,
signatures and native lowering. Preserve strict alignment and first-bar rules.

## F17: Intrabar Funding NaN Is Certified Finite (P1)

Three constant-price bars at 100, capital 1,000 and a one-unit long entering at
the second open: a valid 0.01 event costs 1, giving equity `[1000,999,999]`.
Replacing the event rate with NaN gives `[1000,NaN,NaN]` while the market tape
certificate says `finite_ok=True`. An explicitly aligned funding Series with
NaN gives the same result.

[Strict funding preparation](../../src/quantbt/core/market_tape.py), around
lines 399-461, checks alignment/shape without rejecting nonfinite values.
Finite signed rates, including negative rates, are valid. Reject NaN/Inf before
execution and ensure certificate scope actually includes funding. No claim is
made about the behavior of a freshly loaded Rust binary on these inputs.

## F18: Undefined Period Returns Abort A Valid Bankruptcy Report (P2)

For equity `[100,0,0]`, equity-only reporting returns total return -100%, final
equity 0, maximum drawdown 100% and undefined CAGR. Requesting period statistics
for exactly the same path raises `ValueError: period return after nonpositive
equity is undefined`, suppressing the whole report.

[Completed-result adaptation](../../src/quantbt/metrics/reporting/adapters.py)
derives period returns before constructing account observations;
[public reporting](../../src/quantbt/metrics/reporting/public.py), around line 51,
does not contain the undefined-denominator case. The
[existing reporting contract](../metrics/REPORTING_CONTRACT_V1.md#baseline-and-samples)
accepts zero/negative subsequent equity. Preserve its valid account/DD and
independent ledger/execution groups, while marking affected period metrics
undefined. Do not fabricate zero returns, drop observations, change estimators
or hide unrelated schema errors with a broad exception handler.

## Rejected Hypotheses And Boundaries

- A missing quote for a held option explicitly raises `missing mark`; this
  control does not demonstrate a zero-valued disappearing position.
- A negative per-run event fee override explicitly raises `fee must be >= 0`;
  matched positive fee costs 1. Static suspicion of a fee-validation bypass
  was rejected. Preserve this negative test in the future repair.
- Full hedge inventory, isolated collateral, tiered/mark-price liquidation,
  execution latency and order-book matching remain separate capabilities.
- The mathematical design of the existing option-margin approximation is not
  changed by this review. ACC-01 validates/configures its declared contract;
  a new risk model would require a separate scientific decision.
- These controls cover bounded current routes, not every endpoint/input or
  every old research receipt. Old receipts remain true of their original source.

## Resources And Evidence

Three serial control processes, one numeric thread, two completed read-only
review agents. Reproduction scripts and observations are retained under the
ignored `upgrade/private/account_metrics_plan_review/attempt-01/` directory;
public receipt hashes them and verifies the previous controls/artifact unchanged.
There are no private strategy/data inputs. No scratch was created or deleted.
Retained review files total 57,482 bytes at receipt creation; available bytes
change from 5,672,235,008 to 5,660,614,656, still above the 5-GiB reserve.
This difference includes host activity and is not a reclamation claim.
No service, notebook, environment, shared cache, version or remote was changed.
