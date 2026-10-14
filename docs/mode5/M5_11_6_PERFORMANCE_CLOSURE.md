# M5-11.6 Bounded Performance Closure

## Disposition

The owner-approved performance pass implements trial/final output separation,
qualified duplicate-IS score reuse, validated callback cursors and exact encoded
feedback-prefix comparisons. Public endpoints, original alpha sources, financial
semantics, objective, trial/fold/panel budgets and selectors remain unchanged.

**This is not full M5-11.6 completion or long-queue admission.** HMA's feedback
compiler still executes the full native tape repeatedly. The existing wheel
does not expose the current-bar transactional rollback required to replace that
compiler safely with one persistent session. Its replay cost remains explicit;
no next-bar approximation of same-bar protection was introduced.

Read the [phase plan](../../upgrade/implement.md#mode5-m5-11-6),
[original measured bottlenecks](M5_11_6_PERFORMANCE_REVIEW.md) and
[public opt-in policy](../meta_selection/EXECUTION_WFO.md#trial-output-and-exact-full-is-reuse).

## Matched Actual-Alpha Controls

Each control uses the saved native anchor from its completed first-origin
study: ETHUSDT 1h, 2020--2021 IS, original economics/constraints/price policy,
original public Mode 4 evaluator and original metric witness. There are **zero
new proposals**, no optimizer study and no reuse of BTC account outputs as ETH.

Reference subprocesses import six exact pre-patch source snapshots; optimized
subprocesses use the frozen current source and explicitly qualified trial policy.
One alpha lane runs reference/optimized/optimized/reference; at most four lanes
are independent, with one numerical thread each. Both arms retain standard
financial data needed for scoring; the reference additionally performs its
historical per-trial audit/oracle work. The final requested audit is unchanged.

Times below are median whole-IS evaluation wall time, **two samples per arm**,
not `cProfile` times, kernel throughput or a 57-fold WFO benchmark. Initial
samples overlapped an existing lifecycle regression; host contention and cold
JIT/cache effects are visible in the ranges. These controls establish a useful
bounded improvement, not a portable speedup or p95 SLA.

| Alpha | Before, s | After, s | Ratio | Before range, s | After range, s |
|---|---:|---:|---:|---:|---:|
| SC | 43.888 | 2.939 | 14.93x | 29.836--57.941 | 2.473--3.404 |
| HMA | 61.248 | 35.561 | 1.72x | 53.844--68.651 | 34.571--36.551 |
| HASH | 16.896 | 5.157 | 3.28x | 16.556--17.237 | 4.932--5.382 |
| VWAP | 16.898 | 6.231 | 2.71x | 16.366--17.430 | 6.153--6.309 |

| Alpha | Reference process peak RSS, MiB | Optimized process peak RSS, MiB |
|---|---:|---:|
| SC | 537.37 | 298.64 |
| HMA | 454.27 | 321.33 |
| HASH | 428.73 | 298.40 |
| VWAP | 430.57 | 307.42 |

RSS is each subprocess's `ru_maxrss`, taking the larger of two repetitions.
It is not whole-host/PSS, incremental allocation or a long-run plateau result.
Do not extrapolate these selected-anchor ratios to all candidates or multiply
them into a precise full-study ETA; expanding history and event count matter.

## What Changed

1. `execution_trial_output="account_paths_v1"` explicitly uses standard account
   paths/fills with single-pass/native-trace scoring. It defers canonical trace
   construction and per-trial static-oracle replay; selected final execution
   still uses the supplied audit endpoint. No scalar substitute is used for
   original meta observations. Sampled-oracle aliases fail closed to avoid
   removing RNG consumption.
2. An explicit no-RNG, pure deterministic scorer contract reuses only the exact
   whole-IS shard. Both logical metric rows, shard statistics and observations
   remain. Physical fallback scores fall from two to one. Unknown callbacks,
   multiple shards and active incompatible reuse retain reference execution.
3. Callback calendar cursors validate each exact timestamp and preserve fallback,
   gaps, repeats, backwards calls and failure behavior. The scalar position
   guard preserves original tolerance/NaN/Inf semantics; uncommon inputs and
   errors retain the original NumPy assertion.
4. Prefix checks retain every previous account/event/fill field. Encoded IDs are
   compared only with a validated immutable compatible namespace; reordered or
   mutable mappings use the exact-name fallback. Tape packing reuses proven
   stable slot selections but recompiles changed commands and preserves order.

The synthetic micro-controls locate these last savings: 100 checks over 8,000
events/4,000 fills took 1.282 s versus 0.078 s; 200 warm packs of 1,200 commands
took 0.170 s versus 0.129 s (median of three). These are not financial/WFO
speedup claims and are not added to the table's whole-evaluation speedups.

## Endpoint Review

| Alpha | Retained route | Reason not to substitute a similar signal endpoint |
|---|---|---|
| SC | `event_driven`, strategy callback | Observation-close quantity, next-open entry/exit, actual acceptance/pending state |
| HMA | `order_commands`, native tape | Actual-fill gap handling and same-bar protection, later technical exits |
| HASH | `order_commands`, native tape | Actual-fill partial ladder, residual rounding and campaign cooldown |
| VWAP | `order_commands`, native tape | Actual-fill targets, delayed protection amendments and conditional exits |

The three order bindings are not generic Python callbacks during final native
execution; their expensive temporary feedback compilation is a separate stage.
An intrabar or vectorized route is desirable only if its actual timing/sizing/
gap/amendment/campaign semantics match. No unsupported route was substituted
to obtain a better benchmark, and alpha logic was not moved into QuantBT.

## Correctness And Remaining Work

All 16 actual controls pass cold reconciliation. Every retained account buffer
(equity, returns, positions, fees, funding and margin), fill field, liquidation
state, full report, objective, complete logical shard statistics and original
meta observation matches exactly across arms/repetitions. Compiler command,
bar-step, retry and execution counts also match, rather than hiding work.

Focused local regression: 161 cursor/prefix/reuse/compiler cases; 128 public
trial-output/accounting/assembly/price-policy/mature-event/lifecycle cases; two
additional mature tests using the **new** trial/reuse settings. The latter
actually fit/rank with at least 12 matured origins, reproduce the original
decision and account, independently rebuild the account, and preserve earlier
decisions under future OHLCV/funding mutation. Public off/shadow/active controls
also preserve ordered ask/tell, objectives, selected params and Python/NumPy RNG.
Two expected NumPy overflow warnings belong to extreme-value guard oracles.
An additional 113 original private binding/carry/guard/isolation unit fixtures
pass on the current source. These four disjoint shards total **404 cases**;
earlier reruns of the same cases are not added to that coverage count.

**Remaining HMA bottleneck:** the exact saved control still makes 1,923 full
native executions and 55 same-bar retries. The present session API permits
consecutive steps, not rollback and reprocessing of a bar after actual-fill
protection. Removing replay requires a shared native transactional boundary
with lifecycle/accounting differential tests, not resetting an account, moving
protection to the next bar or assuming a fill. This pass does not implement
that API or advertise the replay compiler as a one-session execution.

The original 128-trial results are retained. Long 57-fold search, actual mature
four-alpha meta/no-leakage/account rebuild and R/Q economics remain the phase's
uncompleted work; no evidence from these controls replaces those gates.

## Evidence And Cleanup

Ignored private lane: `m5-11-6/attempt-01/performance-closure01`. It retains
source snapshots, prospective registration, 16 control receipts, account paths
and cold reconciliation. A coordinator preflight missing optional `psutil`
failed **before any financial work**; that source/failure is retained. The
registered replacement uses existing resource helpers, not a new dependency.

No CI, push, merge, new environment, Rust build, version change or publication
was performed. The existing native binary and every prior research receipt
remain retained. See the [exact cleanup receipt](../maintenance/M5_11_6_PERFORMANCE_CLEANUP.md).
