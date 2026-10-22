# M5-11.6 ETA And Rolling Review

## Disposition

Subsequent owner-approved work is recorded in the
[bounded 730D rolling preflight](M5_11_6_ROLLING_PREFLIGHT.md). It supplies actual
two-fold measurements and qualification; the read-only review below remains
historical, including its withdrawn conversational ETA and unexecuted proposals.

Read-only runtime/receipt review on 2026-10-15, Asia/Saigon. No new finance,
optimizer, build or queue ran. A synthetic transport-only probe reproduced the
final-prefix guard below before any native step. No source was changed by this
review; documentation records the findings for owner approval.

**Withdraw the conversational 4--8-day estimate as a calibrated ETA.** It added
an unmeasured 1--3-day verification allowance and did not establish which checks
would require new search. Existing generic tests, cold accounting readback and
saved-schedule replay are not automatically another full optimizer study.
The estimate is not replaced by a promise that the whole experiment takes hours.

Read the [registered protocol](../../upgrade/implement.md#mode5-m5-11-6),
[original tranche](M5_11_6_MODE4_REPORT.md),
[qualified performance policies](M5_11_6_PERFORMANCE_CLOSURE.md), and
[native transaction controls](M5_11_6_NATIVE_TRANSACTION_CLOSURE.md).
The detailed [meta guide sections 8 and 10](../../upgrade/QUANTBT_1_1_1_META_SELECTION_AND_SAMPLER_MODULE_GUIDE_V1_1_VI.md#s8)
require preserved information/ask-tell semantics and separate component charging.

## Actual Cost Evidence

The completed first-origin baseline contains 512 attempted trials across four
alphas, 506 complete and six pruned. Its four-worker wall time was 4,562.03 s.
These old audit/replay costs are not measurements of a new complete study.

| Alpha | Old whole study, s | Old IS generation p50, s | Old IS generation p95, s | New saved-anchor whole IS evaluation, s |
|---|---:|---:|---:|---:|
| SC | 3,529.38 | 0.495 | 0.547 | 2.939 |
| HMA | 4,556.65 | 24.318 | 41.762 | 16.551 |
| HASH | 1,600.35 | 4.064 | 5.839 | 3.213 |
| VWAP | 1,627.89 | 4.157 | 8.233 | 3.405 |

Generation is **not** whole trial scoring: SC creates its callback factory
cheaply and executes later in the scorer. Do not compare its generation p50 to
the new evaluation time as a regression. The new anchor has two repetitions,
not a measured candidate distribution. Old trial-table exports lack individual
duration fields; sequential log intervals also include inter-trial overhead.

Cold reconciliation finds 579 generations: 507 IS attempts, 68 forward and four
final. There are no duplicate optimizer proposals or exact duplicate IS
generation identities. Each alpha has one repeated selected forward generation
among its 17 forward calls. Its 14 extra logical IS audit rows do not establish
14 additional financial executions. Historical duplicate full-IS shard scoring
is a separate layer and has already been qualified for exact physical reuse.

All generation journals total 405,632 bytes. Measured journal-seal/bookkeeping
overhead is about 0.590 s across 578 successful calls, with aggregate rounding
uncertainty about 0.289 s; this is not a full audit-rendering benchmark. It does
not support blaming hours on the compact progress receipts.

The historical observer cost was 82.01 s summed across four workers; sampler
telemetry was 11.02 s, and cold fit/select was 0.258 s with **zero model fits**.
These overlap broader elapsed totals and must not be added twice. They do not
measure mature-model costs. No evidence supports a blanket extra testing-day
allowance or attributing outside-generation execution costs to Ridge.

## Integration Findings Before Launch

1. **Frozen first-origin runner is still a reference path.** It requests audit,
   lacks the two new qualified metadata opt-ins, prepends the original native
   directory and reaches `compile_native(... feedback_mode="replay_v1")` by
   default. The successful transaction controls explicitly load the candidate,
   set `execution_trial_output="account_paths_v1"` and
   `deterministic_is_shard_reuse="no_rng_v1"`, and select transaction feedback.
   Do not launch the old script unchanged and report it as the optimized run.
2. **Do not blindly enable transactions on final assembly.** The full final
   calendar starts at 2020 with a flat pre-OOS prefix. The decision compiler
   starts at the first OOS bar, while a new transaction owner expects its first
   local market bar. A global override therefore hits `consecutive feedback
   transaction required`. A synthetic dummy-session probe reproduced this
   rejection with zero native steps/financial runs. The 12 successful IS
   controls do not cover this distinct full-calendar final case.
3. **Safe narrow launch policy is available for approval:** transaction feedback
   on independent diagnostic windows, with the already-qualified replay compiler
   and audit retained for final continuous assembly. This preserves original
   carry/protection semantics and avoids a new engine change. Alternatively,
   transaction-first final assembly needs an explicit flat-prefix advancement
   contract and independent carry/account parity, not skipping initial bars.
4. **The generic reuse switch is not the missing accelerator.**
   `WfoExecutionReuseRuntimeV1` intentionally declines Mode 4/per-fold causal
   post-study terminal reuse. Its supported cache does not skip strategy
   compilation or adaptive objectives. Setting `auto` cannot create cross-arm
   financial reuse for these callbacks/tapes. Exact identical-IS shard reuse is
   a separate, qualified policy.
5. **Preserve the exclusive 2026-10-01 analysis end.** Passing the retained
   source's extra October bars into the splitter would add a partial October
   fold. It is a harness-boundary check, not a reason to call the declared
   57-fold protocol complete with a different calendar.

These are launch-integration constraints, not evidence that the native matching
or the saved objective/accounting parity is wrong. The arbitrary original Python
decision/feedback compilation must not be equated with a vectorized kernel's
bars/s benchmark. Further stage profiling is needed to attribute its new cost.

## Avoid An Unnecessary Second Full Search

The registered comparison uses the same IS pool/native anchor. The active
runtime already retains `native_selected_params` and `selected_params` per fold.
Subject to the required bounded actual off/shadow/active ordered-proposal,
objective and RNG proof, one primary chronological search can retain both
decisions and feed two separately owned final accounts. Rebuilding the native
anchor account is not itself another 57-fold optimizer search.

This is a paired research/counterfactual construction from the exact same pool,
not a new adaptive-objective cache and not proof from merely using equal seeds.
Do not replay current forward outcomes into the native anchor, mix arm account
state, omit label observations or claim unrun public off/active parity. Actual
future-mutation selection controls still run with their permitted historical
snapshot; their repeated work is charged, but generic tests/readback do not
automatically require another whole study. If the actual same-pool proof fails,
resolve that failure before reusing the decisions or budget independent searches.

## Rolling Versus Expanding

Same 57 monthly origins, January 2022 through September 2026, complete hourly
data, zero purge/label-horizon exclusions. Table counts one full IS evaluation
per origin, before multiplication by candidates/alphas or physical executions.

| IS Policy | Summed scored days | Summed hourly bars | Share of expanding |
|---|---:|---:|---:|
| Expanding from 2020-01-01 | 90,197 | 2,164,728 | 100% |
| Rolling 730D | 41,610 | 998,640 | 46.13% |
| Rolling 365D | 20,805 | 499,320 | 23.07% |

Rolling limits the financial scoring window. The private adapter deliberately
prepares indicators over the causal prefix through the cutoff, keeping recursive
warmup/history semantics; it does not financially execute that indicator-only
prefix for each diagnostic. Final continuous execution still covers its declared
full account calendar. Thus score-volume ratios are not whole-runtime speedups.
Fixed 365D/730D intervals are not leap-year-aware calendar-year offsets.

Changing expanding to rolling changes IS observations, objective values, adaptive
proposals, selected parameters and meta-family identity. It requires an approved
protocol amendment and a separate compatible history, not relabelling old
expanding results. The 57 forward months, 128 attempts and label panel remain;
shorter IS does not automatically accelerate meta maturity or shorten its archive.

## Conditional Work Models, Not An ETA

Two simple models illustrate uncertainty without inventing new runs:

- Substitute every new saved-anchor time for every candidate. Constant two-year
  cost gives 52.91 aggregate worker-hours and a 33.54-hour HMA lane; scaling by
  expanding scored length gives 114.54 worker-hours and a 72.61-hour HMA lane.
- Rescale each actual old whole-study time by its old/new anchor speed ratio,
  then by scored length. This gives about 72 aggregate worker-hours and a
  42.2-hour HMA lane for expanding. It assumes that anchor speed ratio also
  describes the unmeasured new candidate distribution, which is not certified.

| Policy | Illustrative dominant-lane hours for one search pass |
|---|---:|
| Expanding | about 42--73 |
| Rolling 730D | about 20--34 |
| Rolling 365D | about 10--17 |

These bounds are **two model outputs, not confidence intervals, proven lower
bounds or completion promises**. The rolling figures further assume work scales
with scored duration despite retained prefix preparation. Models exclude
unmeasured mature-meta/observer differences and any independently required
off/active search repetition or mutation search. They do not authorize unsafe
pool reuse. HMA's chronological adaptive lane cannot be divided by four CPUs;
independent alpha lanes may overlap only within the measured memory budget.

## Proposed Next Measurement

No new phase is needed. Before the owner approves a long run, propose a bounded
**30-minute foreground measurement budget**, not an optimizer study:

- Freeze the launch wiring above and the exact candidate binary/source first.
- Reuse three completed first-origin parameter dictionaries per alpha, chosen
  by first/middle/last complete trial ordinal, not economic performance.
- At earliest and latest registered cutoffs, measure expanding, rolling 730D
  and rolling 365D: at most 72 fixed evaluations, zero asks/tells or new trials.
- Report preparation, compilation, financial scoring, output work and native
  session/full-replay counters separately; retain compact timings and the
  independent accounting checks needed for the actual window contract.
- Use at most two independent alpha workers initially, one numerical thread
  each, the existing RAM guards, <=128 MiB retained, no new environment/build,
  and >=5 GiB disk reserve. Register exact scratch before execution; cleanup
  only inactive reproducible scratch. Stop at budget with partial status if
  incomplete, never label a censored panel complete.

The fixed controls calibrate a resource forecast; they are not sampler or
economic evidence and cannot manufacture full-search p95. Any formal admission
must label measured versus extrapolated quantities honestly. The owner must
separately approve replacing expanding with rolling before its economic study.
Neither that amendment nor these proposed evaluations have been executed.

## Review Resources

This review read existing receipts/source, performed calendar arithmetic and a
dummy transport guard probe. It created no financial outputs, JIT cache, new
environment or build scratch. Documentation/compact review retention is below
1 MiB; disk remains about 5.9 GiB with the 5-GiB reserve intact. No deletion is
needed. Earlier source/evidence and the owner's unrelated working changes remain.
