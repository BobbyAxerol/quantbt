# Meta Endpoint Coverage For Owner Release Review

## Decision Boundary

Original inventory: `39185fe`; local execution amendment: `a139f35`,
2026-10-06 (UTC). This is a review of
existing executable adapters and their actual evidence, not approval to expose
every row in the next release. The owner will select the version's endpoint
scope before broader activation. CI/CD, final artifact qualification and public
proof are deferred until that scope is settled. No push or publication here.

C01 nested Mode 1 and C05 conditional sampling/support projection now have
separate **local implementation approval**. Their activation plan is recorded
in [the sequential unified plan](../../upgrade/implement.md#qms-pre-e06-action-plan).
They are **not implemented runtime capabilities yet**. The original review
documents and receipts describe their earlier spec-only work; preserve them.
The [PRE-E06 source-bound inventory](PRE_E06_BASELINE.md) separates actual
discovery/preflight, original account/metric witnesses, retained tests and
missing active/matured qualification at that historical inventory. The separate
[PRE-E06-02 execution report](PRE_E06_02_REPORT.md) owns current-source matured
coverage; it does not confer economic, installed-final-pair or public promotion.

## Executable And Tested Now

All generic WFO rows below currently use `QuantBTEndpoint.walk_forward`,
Mode 4 / `per_fold_causal`, explicit authoritative endpoint scoring and opt-in
meta. Calling a standalone endpoint does not automatically attach meta.
Meta off preserves the original strategy, search and accounting behavior.

| WFO target / surface | Actual financial owner and scope | Executed evidence |
|---|---|---|
| `signal_notional` / `single_signal` | Native vectorized or native event; frozen scalar units | E03 original pool/RNG/account tests, wheel/sdist, real Gradient/Delta RSI off/active |
| `notional` | Native vectorized or native event; constant-quote targets | E03 tests, wheel/sdist, real RSI; matched prepared/vectorized study |
| `unit` | Native vectorized or native event; window-start unit scaling | E03 tests, wheel/sdist, real RSI; G01 repaired full prepared/vectorized study |
| `pct_equity` / `%_equity` | Original legacy/Numba equity-transition account | E03 tests, wheel/sdist and real RSI off/active |
| `dca_ladder` | Original structural high/low ladder and signed level caps | E03 tests, wheel/sdist, real OHLC with owner-approved simple simulated ladder; not a real proprietary grid alpha |
| `portfolio` | Original native_portfolio shared account; ordered position matrix/calendar | E04 122 scoped software checks, wheel/sdist, real ETH/BTC RSI diagnostic and saved-param account replay |
| `basket` | Original native_event frozen best-effort basket | E05 original account/witness tests and wheel/sdist; real-alpha economic study not executed |
| `arbitrage` | Original native_event bounded linear non-expiring basis/statistical pair, frozen hedge | E05 original account/witness tests and wheel/sdist; quarterly uses the separate `delivery_arbitrage` row, not this contract |
| `intrabar` | Explicit original intrabar intent/session endpoint; continuous final execution | Local intent/protection/session/account tests; synthetic on/off study; no real-market promotion |
| `event_driven` | Generic callback factory and original event account, not numeric W3 | Local callback/fill-feedback, pool/labels, shadow and active rebuild tests; synthetic qualification |
| `order_commands` | Explicit original command tape; pending orders continue across folds | Local typed tape/cancel/account tests and synthetic qualification |
| `delivery_arbitrage` | Explicit multi-leg orders plus `pre_expiry_flatten_v1`; new-leg roll commands | Independent v2/v3 fill/fee/expiry checks and synthetic qualification; no cash settlement or real venue admission |
| Prepared W3 reactive WFO | Separate prepared numeric route; Mode 4 causal, sequential, one symbol, reset-flat, inprocess or safe Linux fork/COW | QMS-06/C02/C03 original witnesses, active applied selection, process/deadline/sampler tests and wheel/sdist; domain-specific real grid/MRS economic study not executed |

Evidence links: [E03 historical assessment](QMSE03_REPORT.md),
[G01 current correctness closure](QMSE03_G01_CLOSURE.md),
[E04 software](QMSE04_REPORT.md), [E04 real diagnostic](QMSE04_REAL_DIAGNOSTIC.md),
[E05 bounded packages](QMSE05_REPORT.md), [C02 W3 transport](QMSC02_REPORT.md)
and [C03 sampler/scheduler qualification](QMSC03_REPORT.md).
The new [execution-route report](EXECUTION_WFO_REPORT.md) records source/tests,
installed artifacts, synthetic R/Q dispositions, performance and exact limits.
Counts belong to their own historical scopes; do not sum overlapping suites.

Current-source PRE-E06-02 adds actual default-maturity fit/rank/application on
all thirteen rows at three registered cutoffs, including numeric W3 reset-flat.
Its 623 distinct scoped PASS include future-input/label/artifact mutations,
original measurement and stitched-account replay. The 27 scalar-only N/A cells
are excluded. This separate source proof does not recertify historical installed
artifacts, enable a new mode or establish economic improvement.

**Native event distinction:** E03 uses signals translated to rebalance orders.
That did not certify arbitrary callbacks, command tapes or intrabar execution.
The new [execution adapter](EXECUTION_WFO.md) qualifies them independently
through typed WFO windows and their original financial engines. Arbitrary
alpha features remain caller-owned; no blanket grid/DCA economic claim.
W3 has a different strategy protocol and segmented account contract.

## Not Implemented Or Not Admitted

| Requested surface | Missing gate |
|---|---|
| Real intrabar or callback/order economic promotion | Software adapter exists; synthetic conformance does not replace a registered real-alpha study |
| Hold-through-expiry quarterly settlement / real venue admission | Executable pre-expiry flatten/roll exists; authoritative settlement source/provider and financial runtime remain separate |
| Options / Nautilus validation meta | Explicit domain evaluation/WFO adapter; standalone engine availability is not meta support |
| W3 carry, shared multi-symbol, public meta batch, Mode 2 bootstrap | Separately approved financial/scheduler/label semantics and runtime implementation |
| Meta outside current Mode 4 causal | C01 approved local nested Mode 1 implementation still pending; global/decay remains unapproved |
| Conditional Sobol / mixed support representative | C05 approved local implementation/continuation/installed gates still pending |

## What The Real Tests Establish

Software correctness and economic gain are independent. Eight E03 real-data
pairs finished, but **0/8** pass the registered forward-Q lower-bound criterion.
For pct-equity, forward-Q point mean is about **+1.001**, with interval
**[-0.155, 2.516]**; that is promising but not a reliable improvement certificate.
Do not choose a route or retune the experiment until it becomes positive.

E04's ETH/BTC portfolio diagnostic is complete: accounting replay difference
is zero, final equity improves, but forward-Q interval **[-2.0571, 1.9639]**
contains zero and 99.69% of point decay reduction comes from lower IS.
Its outcome remains **NOT_PROMOTED**. This single test does not prove portfolio
meta is universally ineffective or that parameter-sensitive alphas necessarily
benefit. The owner has not accepted a blanket research-only release disposition;
the endpoint release choice remains pending.

## Quarterly Data Inventory Correction

The earlier E05 report examined the sandbox's 2025 archives. A separate read-only
inventory of the central loader store now finds 25 BTC and 25 ETH quarterly
symbol directories, 137 Parquet files per asset, 4,865,028 BTC and 4,863,409 ETH
rows. Timestamp metadata spans 2021-02-03/04 through 2026-10-06. Neither alpha,
loader nor data was modified and no download was invoked.

These are **file-metadata bounds**, not verified continuous usable history,
matured task origins, pristine locked data or settlement witnesses. Do not keep
claiming all available price data is limited to 2025; equally, do not claim the
central store closes real venue expiry/roll/settlement semantics. That admission gate stays
open pending exact instruments/events/account contracts and per-window validation.

## Historical First-Release Suggestion

Start with scalar WFO (`signal_notional`, `notional`, `unit`, `pct_equity`) as
explicit research opt-ins. Decide structural ladder and bounded W3 separately:
their software gates are real, but simulated/numeric protocol evidence is not
domain-specific economic qualification. Portfolio and bounded package adapters
may remain experimental or excluded from this release, according to owner choice.
No default meta promotion, universal decay claim or automatic endpoint coverage.
That earlier suggestion is not an owner scope decision. The subsequent required
execution amendment includes intrabar, callbacks, commands and bounded pre-expiry
delivery. Their current software scope is above; economic/default exposure and
remaining capabilities still require separate review.

## Verification And Cleanup

This pass ran documentation-anchor validation, the exact E05/G01 source guard
and baseline diff checks for Python/Rust, the detailed guide and sealed real-data
receipts: PASS. It did not rerun backtests, refit a model or build distributions;
the test counts above describe retained executed evidence, not new executions.

Available filesystem bytes before/after were 27,170,123,776 / 27,164,340,224
(shared-host observations, not task allocation accounting); inodes had 15% use.
No new consumer/native build/cache lane was created, no alpha/data/evidence was
deleted and no cleanup removal was warranted. Current environments and retained
artifacts remain available. No remote workflow, push, merge, tag or upload ran.

That paragraph describes the earlier inventory-only review. The subsequent
owner-approved execution amendment did implement/test four routes, build fresh
core artifacts and remove its own inactive scratch. Read the current
[execution closeout/report](EXECUTION_WFO_REPORT.md); it supersedes availability
claims, never rewrites historical receipts or upgrades their economic outcome.
