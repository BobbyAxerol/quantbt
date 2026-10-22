# ACC-01 Detailed Repair And Verification Guide

Date: 2026-10-22, Asia/Saigon. Status: **PROPOSED / AWAITING OWNER APPROVAL**.
This is the detailed guide for the single
[ACC-01 phase](../../upgrade/implement.md#account-metrics-acc-01), not additional
phases or authorization to change runtime. It covers the
[first follow-up](../PORTFOLIO_ACCOUNT_FOLLOWUP_2026-10-21.md) and
[expanded review](EXPANDED_REVIEW_2026-10-22.md): F01-F18, all currently OPEN.
Original [repair](REPAIR_REPORT.md) and review receipts remain historical.

## Goal And Boundaries

Make account inputs, accepted execution, financial events and reported metrics
consistent on the capabilities already implemented. The result must state which
configuration actually applies, which contract is unavailable, and which metric
is undefined. Valid backtests must not silently change economics because a
parameter is ignored, a clock changes units, or a cold report invents flows.

Preserve current gross-cross/netting, supported event clocks, intrabar bracket/
session timing, bounded packages and documented option snapshot/margin models.
Do not add isolated collateral, dual hedge inventory, order-book queues,
latency, tiered/mark-price/partial liquidation or a new option risk model.
Options keep their domain-specific cash/margin/execution contracts: a generic
linear-account validator must not accidentally replace them. Existing supported
option `margin_buffer` behavior must be preserved.

No WFO objective, estimator, sampler, Ridge, selector, scientific gate or private
alpha is changed. A corrected financial path can legitimately change a score
on a formerly defective input; report that numerical difference and source
boundary explicitly. Preserve historical evidence, not the bug. No completed
optimizer/economic study rerun is needed for this phase.

## Architecture And Source Ownership

Follow [execution ownership](../architecture/execution-plan.md#ownership-boundaries),
[strategy/engine boundary](../adr/ADR-RP-002-strategy-engine-boundary.md),
[WFO schedule ownership](../adr/ADR-RP-005-wfo-optimizer-schedules.md),
[Reporting V1](../metrics/REPORTING_CONTRACT_V1.md),
[option containment](../options_p0_containment.md) and the
[cleanup runbook](../BUILD_TEST_CLEANUP.md).

- Normalize/validate once at the public/prepared boundary; reuse small existing
  helpers or add focused modules when responsibility is genuinely shared.
  Direct backend and prepared requests must not bypass endpoint validation.
- Financial execution owns accepted fills, costs, funding and liquidation.
  Add narrowly scoped typed attribution buffers if the current execution output
  cannot explain its own account path. A reporting adapter must not replay the
  strategy/account or infer rejected/forced trades from position differences.
- Keep Python/Numba/Rust domain parity where those implementations support the
  same request. Do not assume an endpoint named `native` ran Rust. Record the
  resolved runtime, loaded extension identity and unsupported routes separately.
- Do not require audit rows on score paths or add per-bar dictionary/FFI work to
  implement metadata validation. Price, fee, funding and account results must
  agree across score/compact/audit profiles on retained comparable fields.
- Keep report estimators/populations/versioned policies unchanged. Report
  repair must leave raw input arrays, result objects and ledgers unchanged.

## Finding Register And Expected Repair

Each row has an independent numeric/control requirement in T01-T18 below.
Implementation must link the regression test and source commit back to its ID.

| ID | Existing defect | Primary source owner | Required behavior |
|---|---|---|---|
| F01 | Zero event multiplier executes for free | `backends/native_event.py`, shared financial-vector validation | Finite positive contract size/leverage at constructor, scalar, mapping and per-run/prepared boundaries; preserve valid heterogeneous vectors |
| F02 | Package report invents costs/funding after liquidation and omits loss | `backends/native_vectorized.py`, actual execution output/leg reports | Use executed fee/funding/slippage/liquidation attribution, reconcile all bars and legs, including the liquidation bar; inspect event package/carry consumers for the same reconstruction |
| F03 | Option opening wallet and metric baseline disagree | `backends/native_option.py`, `options/reporting.py` | Value opening balances in report currency before execution; reject conflict with explicit `account.initial_capital` under a documented numeric tolerance; default wallet remains capital in report currency |
| F04 | Common option fees use raw currency and final-row dump | `options/reporting.py`, fee/ledger event adapters | Aggregate actual applied fees in reporting currency at effective event time; retain original denomination and conversion witness; total reconciles to ledger |
| F05 | Generic event minimum notional ignored | `backends/native_event.py`, constraint lowering | Combine supported generic/instrument/per-run lower bounds explicitly, normally their maximum; enforce actual delta order, preserving documented risk-reduction exemptions |
| F06 | Options silently accept unsupported generic configuration | `NativeOptionConfig` and endpoint lowering | Explicit supported/ignored-default/rejected mapping; reject unsupported non-default account/execution flags before simulation; never override option execution with a linear model |
| F07 | Option margin NaN creates false liquidation | `options/margin.py`, authority validation | Finite domain-valid numeric rates/scenarios/requirements; validate external-validator outputs before admission; preserve approved approximation formula |
| F08 | Vectorized extreme slippage produces nonpositive prices/negative fees | `NativeVectorizedConfig`, execution lowering | Validate the existing proportional-slippage domain and positive execution prices before accepting a run; no clamping into a different model |
| F09 | Result/accounting conversion loses datetime resolution | `core/results.py` | Normalize physical instants to UTC ns before storage; preserve explicit timezone convention, elapsed duration and reconstruction |
| F10 | Mean-leverage metadata overstates universal buying power | vectorized/event result metadata builders | Homogeneous scalar remains meaningful; heterogeneous capacity is unavailable as one scalar, with reason, per-symbol leverage and actual IM/free-margin disclosure |
| F11 | Writable ndarray headers invalidate immutable cache identity | `metrics/reporting/inputs.py`, `snapshots.py`, `cache.py` | Protect canonical headers or reject changed dtype/shape before lookup/reduction; preserve deep-copy/pickle guarantees without O(N) hashing per cache hit |
| F12 | Finite extreme outcome sums overflow JSON provenance | `metrics/reporting/ledger.py`, report serialization | Explicit invalid/undefined status and safe finite/null provenance; no unhandled JSON overflow, fabricated zero PnL or loss of unaffected fields |
| F13 | Expiry realized PnL equals gross payoff | `options/ledger.py`, settlement lifecycle | Retire remaining entry cost basis when settling; separate payoff cashflow, realized PnL and fees; preserve actual cash/position closure and idempotence |
| F14 | Option NaN cash/FX/fees/settlement poisons accounts | options ledger/config/fees/lifecycle and shared conversion | Reject nonfinite financial inputs before mutation; validate used FX coverage/rates; validate signed balances without banning supported debit cash; no invalid `reconciled=True` claim |
| F15 | Option fill/ledger time precedes decision | `options/execution.py`, native option admission, report/hedge adaptation | Keep quote time separate; effective fill/ledger/cost time must agree with decision execution, retaining supported same-time order and freshness rules |
| F16 | Intrabar preparation labels us clocks as ns | `core/market_tape.py`, prepared signatures/native lowering | Normalize UTC ns before packing, matching, signatures and funding alignment; verify reference/kernel/native and session consumers |
| F17 | Nonfinite intrabar funding passes finite certificate | `core/market_tape.py`, validation certificate | Validate all event/Series/mapping rate arrays as finite, signed values; certificate must cover actual funding; reject before execution |
| F18 | Undefined post-bankruptcy period return aborts all reports | reporting adapters/public/account contracts | Preserve valid account/DD and independent ledger/execution groups; mark undefined period metrics with reason; retain strict low-level denominator validation |

F03 uses rejection of conflicting explicit baselines as the proposed compatibility
policy. Never silently convert `1000` wallet / `20000` capital into a -95% trade
return, or silently overwrite the capital request. Documentation must show how
to supply matching report-currency capital and multi-currency balances.

F13 must keep separate currency ledgers when premium and settlement currencies
differ. Arithmetic subtraction of amounts in different currencies is prohibited.
Qualify supported same-currency cases first; for an already-supported mixed
case use explicit existing conversion/cost-basis policy or fail clearly for the
missing report contract. Do not invent a new FX PnL methodology in this repair.

For F18, catch the specific undefined-period condition via a typed disposition
or narrowly classified error. Broadly swallowing `ValueError` would hide bad
scope, ordering, timestamp or identity inputs and is not an acceptable fix.

## W00 - Freeze Evidence And Reproduce

1. Record approved phase, actual Git/source/native identities, versions, dirty
   owner files, protected evidence hashes, available bytes/inodes/RAM and exact
   scratch paths. Review caps before starting test/build workers.
2. Convert the retained synthetic controls into focused regression fixtures,
   with independent expected values, not assertions that mirror a helper.
   Preserve the original observations/failures; use new receipts for reruns.
3. Map F01-F18 to public endpoint, direct backend, prepared route and consumer
   paths. Mark unsupported combinations explicitly; do not count skips as PASS.
4. Read source and historical contract tests before deciding each correction.
   New reproducible defects of these same responsibilities can be logged and
   fixed within this phase; new financial models/scientific changes need separate
   owner scope decisions and cannot be silently folded in.

## W01 - Effective Configuration And Financial Admission

Implement F01/F05/F06/F07/F08/F14 boundary guards with shared small validators
where domains agree. Audit configuration precedence through the endpoint,
dataclass, per-run mapping, prepared request and native request. Return field-
specific errors with no order/account mutation. Supported zero fee/minimum is
valid; nonpositive multiplier/FX is invalid; funding may legitimately be signed.

Produce a compact effective-config matrix for capital, report currency,
leverage, multiplier, fee, slippage, min quantity/notional, margin_buffer,
margin/OMS mode, fill clock, partial fill and funding. Each cell must be
SUPPORTED, EXPLICITLY_REJECTED or COMPATIBILITY_DEFAULT_INACTIVE, with test IDs.
Non-default silently ignored settings are not allowed. Use actual code and
capability registry, not stale prose describing earlier promotion stages.

## W02 - Executed Linear Attribution And Capacity

Implement F02/F10 using authoritative execution outputs for direct targets,
basis/stat-arbitrage/packages and affected event package reports. Inventory
current per-leg arrays before adding buffers. Maintain account equity identity
through entry, partial reduction, reversal, rejection, funding, adverse-OHLC
liquidation and terminal flat state. Costs must be counted once.

Use the current conservative liquidation convention, not a new exchange model.
If a path cannot provide requested attribution, emit explicit unavailability;
claimed supported package reports must receive enough authoritative output to
reconcile. Do not hide a mismatch by skipping liquidation rows or adjusting the
last row with an unexplained residual. Document any defined allocation policy.

## W03 - Option Monetary And Lifecycle Reporting

Implement F03/F04/F13/F15 and integrate W01 option guards. Establish opening
wallet value before the first fill; distinguish currency amounts from report
values throughout fills/fees/cash/PnL. Stamp actual execution and retain quote
time, decision time and conversion provenance separately. Map costs to existing
result events without distributing them artificially across bars.

Check long/short, ITM/OTM, partial close followed by expiry, multiplier != 1,
fees, duplicate settlement rejection, supported liquidation and delta-hedge
report consumers. Correct realized classification without mutating cash twice.
Do not call fee equality a full account reconciliation: metadata must state
what equality is checked, and nonfinite values cannot pass any relevant check.

## W04 - Canonical Clocks And Funding

Implement F09/F16/F17 together at their distinct owning boundaries. Normalize
ns/us/ms/s DatetimeIndex representations to identical UTC instants; preserve
documented naive-timezone rules, reject NaT/duplicate/unordered input and check
overflow. Equivalent timezone representations must not move fills or funding.
Equivalent prepared tapes must have the intended canonical identity; persisted
old invalid clock representations must not be silently accepted as new ones.

The generic eight-hour aggregate funding convention and intrabar explicit
POSITION_AT_EVENT convention are different supported contracts. Preserve both.
For intrabar keep exact event alignment/first-bar rules and event position
ordering; no remapping event-causal rates to a coarse generic proxy. Reject
nonfinite funding before constructing a supposedly finite prepared certificate.

## W05 - Report Isolation And Snapshot Hardening

Implement F11/F12/F18. Account, period, execution, closed-trade and closed-action
groups remain distinct. Lack of an authoritative complete ledger remains
UNAVAILABLE; no inferred trades/actions from equity or position regimes.
Period undefined status must not erase valid bankruptcy return/DD or independent
groups. Do not drop NaNs/rows to manufacture a finite report.

Check every public/cache entrypoint against dtype/shape reinterpretation,
deepcopy/pickle, repeated lookup and fresh reduction. Use stable internal storage
or cheap header checks; maintain immutable content and identity semantics.
Overflow handling must preserve valid populations/sample counts and produce
strict JSON with `null` plus reason where numeric values are not representable.

## W06 - Cross-Route And Source Qualification

Run affected regression incrementally as work packages complete, then one
final-source combined gate. Extend existing test modules where appropriate;
use focused new modules for new responsibilities rather than one giant test.
The following T requirements are minimum obligations, not a prescribed count
of pytest cases. F01-F18 may each need parametrized routes/clock/profile cases.

| Test ID | Required independent oracle/control |
|---|---|
| T01 / F01 | Orders/commands/callback: capital 1000, price 100, qty 1, cs=0 rejects; cs=1 costs fee 1 and IM 100. Exercise positive vectors, zero/negative/NaN/Inf and direct/prepared entrypoints |
| T02 / F02 | Retained liquidation case: actual net -100, actual fees 2, actual funding 0; leg net must equal -100, with no invented second fee 2 or funding +10. Add non-liquidating multi-leg reversal/rejection/slippage/funding controls |
| T03 / F03 | No packages, wallet USD1000: matching baseline reports 0%; declared baseline20000 rejects rather than -95%. Include converted multi-currency matching wallet, empty/omitted balances policy and first-fill costs |
| T04 / F04 | Applied 0.0000021BTC at conversion100000 produces common fee0.21USD at the effective event. Multiple currencies/times/fees sum correctly; no double counting in hedge/settlement reports |
| T05 / F05 | Fresh100-notional entry with generic min200 rejects on orders/commands/callback; matching supported min100 admits. Generic/direct/instrument conflict policy and legal reduce-only close are tested |
| T06 / F06 | ISOLATED/HEDGING and inactive generic OPEN/slippage/minimum options cannot silently run unchanged. Valid option snapshot settings and actually supported option buffer still work |
| T07 / F07 | NaN/Inf/invalid option margin inputs and external requirement outputs reject before false liquidation; valid matched configuration preserves fill/equity and approximation output |
| T08 / F08 | Price100 short1 at20000bps rejects;100bps/.01fee retains fee0.99/equity998.01. Both directions, exactly10000bps, valid zero and positive prices at supported bounds |
| T09 / F09 | Same ns/us daily result reconstructs the same 172800-second horizon and UTC instants; no1970 conversion; full_report/accounting consumer parity for timezone-aware/declared-naive inputs |
| T10 / F10 | Capital1000, leverages1/10, notional100 each has IM110; no universal scalar5500. One common leverage retains meaningful scalar and capacity labels match real margin fields |
| T11 / F11 | `[100,110]` returns10%; header mutation cannot produce stale cached10% versus reinterpreted array. Shape/dtype/base exposure, pickle/deepcopy, uncached/cached and all snapshot kinds remain safe |
| T12 / F12 | Two finite1e308 outcomes yield an explicit overflow disposition with strict JSON, not incidental serialization crash; normal signed-PnL/streak/action controls remain exact |
| T13 / F13 | Entry.02/payoff.20BTC: long realized+.18, short-.18; long OTM-.02. Cash unchanged versus existing correct cash, partial closure cost basis/fees/multipliers and duplicate settlement covered |
| T14 / F14 | NaN/Inf balance/FX/fee/settlement rejects; valid signed wallet and positive FX preserved; unknown conversion fails; invalid identity/fee reconciliation cannot claim valid |
| T15 / F15 | Quote00:00, decision00:30: source quote remains00:00, effective fill/ledger/cost00:30; no exposure or ledger fee before decision. Test quote-age rejection, exact-quote control and same-time ordering |
| T16 / F16 | ns/us intrabar clocks both yield7200seconds in2024; same physical ns event against us market aligns; reference/kernel/native/session time/identity/funding parity where supported |
| T17 / F17 | Long1 at100 with explicit.01 funding costs1, equity999; NaN/Inf event/Series/mapping fails before finite certification; negative finite rates give correct credit |
| T18 / F18 | `[100,0,0]` with period request still reports total return-1, DD1, equity0 and undefined CAGR/affected periods. Valid ledger/execution groups survive; malformed scope/time still errors |

Mandatory route matrix: public scalar `pct_equity`/unit targets; legacy
BacktestEngine/MultiSymbolPortfolio; native vectorized/portfolio; event orders,
commands and generic callbacks under each supported clock; reactive numeric/W3
supported contracts; intrabar bracket and session; bounded basket/basis/stat/
package; options including existing hedge/settlement consumers. Direct/prepared
paths and report profiles must be checked where the changed helper is used.
Do not run impossible domain/backend combinations and call skip qualification.

Use independent handwritten scalar cash/PnL/time/cost expectations plus
Python/Numba/Rust differential tests for matching contracts. Parity alone is
insufficient: both implementations may share the bug. Retain existing close,
next-open, OCO, pending-order, reduce-only and liquidation controls. Review
shared WFO/Mode4/Mode5 reporting consumers with fixed synthetic fixtures and
existing relevant suites; no private alpha optimizer/calibration rerun.

If Rust changes, use targeted Rust unit tests plus a freshly built local exact
wheel/binding against this source. If Rust is unchanged, reuse the retained
artifact only after checking its exact native source/capability hash; the old
primary-environment native0.4.2 cannot certify repaired0.4.3 code. Keep unsupported
routes explicit. This is local repair verification, not M5-12's whole package
wheel/sdist, manylinux matrix, public consumer proof or release.

## W07 - Performance And Retention Check

Use matched synthetic inputs before/after: short public boundary/report call,
2k/100k/1M account reduction, representative option/linear attribution ledgers,
cache hit/miss and score/compact/audit on the affected route. Same request,
profile, data, threads and retained outputs; fresh and warmed timings separate.
Proposed finite measurement protocol: 2 warm-ups, 7 measured repeats per cell,
record samples/median/range and peak RSS, no speed claim from noisy tiny cells.
This does not repeat old broad performance/financial studies.

Acceptance: no per-bar revalidation or default audit replay, no new O(N) cache
hit hashing, no cross-trial mutable state, no new per-bar Python/Rust boundary,
no unexpected retention growth across repeated completed runs. Targeted cold
boundary checks can cost time; disclose measured regressions and cause. Any
unexplained >10% warmed median slowdown on a representative nontrivial cell
requires investigation with paired timings before closure. This is a proposed
engineering investigation threshold, not a claim that performance was measured
or permission to weaken correctness. Changes to financial scope are forbidden
as a way to obtain a faster benchmark.

## W08 - Documentation, Exact Source And Cleanup

1. Update endpoint/config docs, supported/rejected matrix, metrics units and
   scopes, option fee/cash/settlement/time examples, migration notes and result
   metadata schema. Explain intentional new errors and changed defective outputs.
2. Append source-specific amendment/qualification to the current source-guard
   mechanism, with exact old/new blob mappings and negative tamper tests. Do not
   overwrite historical receipts or whitelist arbitrary future source drift.
   Identify any changed native artifact and version pair without bumping version.
3. Produce one F01-F18 closure table: cause, fix, test IDs, baseline/current
   result, source/runtime/artifact, status and limits. Report distinct tests,
   failures, skips and reused evidence honestly. Unrelated old tests are not
   evidence that new paths are correct.
4. Perform privacy/docs/link/source checks, final selected regression and exact
   scratch cleanup. Hash-check retained prior reports/artifacts, owner files and
   new receipts; record actual space change, workers and environments retained.
5. Commit coherent verified work packages on the current feature branch, leave
   unrelated owner work untouched. Update unified current status and M5-12
   handoff only when all required in-scope gates close. No push/merge/tag/CI or
   PyPI/publication/version change follows automatically.

## Resource Admission And Cleanup

Reuse the existing environment/toolchain and the
[approved cleanup procedure](../BUILD_TEST_CLEANUP.md). One financial/test or
build worker, one numeric thread; read-only agents can review disjoint scopes.
Keep available RAM >=512MiB. Initial implementation proposal: retained new
receipts/artifacts <=128MiB, ordinary fixture/JIT scratch <=96MiB; optional native
build incremental scratch <=512MiB only after separate measured disk admission.
Keep >=5GiB free beyond forecast incremental growth. At planning receipt time
only about0.27GiB lies above that reserve: a native build is **not admitted** by
this document's disk observation. Inspect/reclaim exact eligible inactive scratch
or reuse validated artifacts first; do not erase evidence to satisfy the cap.

Register exact ignored attempt directories before implementation. Preserve logs,
failing cases, oracle fixtures, source snapshots and exact wheel outputs. Remove
only owned inactive reproducible scratch after terminal workers; never broadly
purge `target`, `.maturin`, environments, private evidence or system caches.

## Exit Gate, Debt And Rollback

ACC-01 can be COMPLETE_LOCAL_CURRENT_CAPABILITY_CLOSURE only when all F01-F18
have independent regression evidence, correct effective-config propagation,
supported-route parity and correct accounting/report/time/currency identities.
Undefined values and unsupported modes must be explicit, not zero/green.
All changed native paths need exact-binding evidence; source/privacy/docs,
performance disclosure and cleanup must pass. Any unresolved in-scope defect
keeps the phase open, even if its priority is low. No silent deferral as done.

Limits listed above remain capabilities outside this phase, not debt requiring
an exchange simulator. Historical research acceptance remains intact; this
repair does not retrospectively certify its accounts under new source.
M5-12 and CI/release stay separate, with final artifact qualification later.

Rollback is by the scoped commit chain to a recorded prior source/artifact pair
for diagnosis; known-invalid configurations remain explicitly warned/unavailable.
Keep receipts and independent controls. Never restore silent bad execution as a
normal fallback or rewrite old evidence to match the new behavior.
