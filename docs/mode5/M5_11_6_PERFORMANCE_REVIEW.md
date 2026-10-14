# M5-11.6 Pre-Long-Queue Performance Review

## Scope And Result

The owner requested bottleneck investigation before the long queue. This is a
completed **measurement review**, not an optimization patch, economic study or
whole-phase certificate. No long queue, sampler study, build, remote workflow
or publication was launched. Original alpha sources and financial code remain
unchanged. Read the [phase plan](../../upgrade/implement.md#mode5-m5-11-6) and
[first-origin qualification](M5_11_6_MODE4_REPORT.md).

**Conclusion:** the research bindings and audit-heavy trial path contain
substantial avoidable work. It is not justified to launch the full experiment
unchanged or attribute its cost principally to TPE/Ridge or indicator math.

## Existing Uninstrumented Evidence

These figures reuse all four completed studies and their 579 generation
journals. No financial work was repeated to derive this table.

| Alpha | Whole study, s | Inside generation, s | Generation share | Outside generation, s | Sampler, s |
|---|---:|---:|---:|---:|---:|
| SC | 3,529.38 | 68.62 | 1.94% | 3,460.75 | 1.115 |
| HMA | 4,556.65 | 3,393.60 | 74.48% | 1,163.05 | 3.588 |
| HASH | 1,600.35 | 555.47 | 34.71% | 1,044.88 | 3.138 |
| VWAP | 1,627.89 | 617.64 | 37.94% | 1,010.25 | 3.177 |

Generation includes original preparation and, for native order bindings,
actual-feedback compilation. For SC it primarily prepares a callback factory;
the actual callback execution happens later in endpoint scoring. Therefore
the residual is **not meta-learning time**. All first-origin model-fit counts
are zero; costs of mature fits are not estimated from these controls.

The successful four-worker queue took 4,562.03 seconds (76.03 minutes).
Earlier admission, the retained failed attempt and repair/verification work
are separate costs; the full earlier work session was longer than this queue.
This distinction does not make the current trial path sufficiently efficient.

## Bounded Controls

Two saved native anchors, HMA and SC, were replayed through the original
`WalkForwardEngine.evaluate_params_is` and endpoint scorer on the exact
2020--2021 IS window. Their original config, prepared context, constraints,
price-admissibility policy, seed and reset-flat account contract remain intact.
No candidates were suggested, retuned, selected or forward-tested.

Both controls reproduce the original objective and the exact saved metric
observation `output_ref`, status and sample count. Profiling is observational;
it does not qualify a proposed faster path.

| Control | Instrumented IS evaluation, s | Process elapsed, s | Peak RSS, MiB |
|---|---:|---:|---:|
| HMA | 75.40 | 77.25 | 443.83 |
| SC | 45.50 | 47.19 | 443.45 |

`cProfile` adds overhead. These times locate work and must not be compared
with the uninstrumented trial distribution as a speedup/regression benchmark.
The function times below are cumulative and overlap; do not sum them.

## Confirmed Bottlenecks

### HMA: Repeated Full-Tape Feedback Execution

One 17,544-bar IS control produces 2,746 commands and invokes native execution
**1,923 times**, with 55 same-bar retries. Although the compiler caches numeric
command rows, `CachedTapeRows.execute` constructs a request/new runner and
executes the whole current tape on every relevant change. It does not advance
one persistent financial session through the original timeline.

Measured cumulative costs in this instrumented control:

- Original feedback compiler: **58.15 s**.
- Its execution callback: **26.74 s** over 1,923 calls.
- Packing tapes: **12.37 s**, included in those execution calls.
- Committed-prefix checks: **18.20 s**.
- `events_before` projections: **17.64 s**, included in prefix checks.
- ID-to-name conversion performs about **24.4 million generator iterations**.

This can grow with both tape length and event count. A fast Rust kernel does
not eliminate the cost of thousands of whole-tape runs, repeated packing and
Python reconstruction. Whole-history feature preparation is not the principal
cost in this measured HMA control.

### Both Controls: Duplicate Whole-IS Scoring

`is_subperiods=1` does not currently mean zero additional financial score calls.
`evaluate_params_is` schedules the main IS score and a single shard covering
the same IS calendar. Both controls show **two endpoint fallback runs**.

This is existing semantics, not permission to set the shard count to zero or
drop its statistics. A future optimization must retain logical rows, temporal
summaries, metrics and RNG behavior. Physical reuse needs a declared exact,
deterministic evaluation contract; arbitrary stochastic callbacks cannot be
assumed interchangeable merely because their indexes match.

### Trial Audits: Dense Trace And Oracle Work

The research factory currently requests `profile="audit"` for repeated IS
evaluations as well as final certification. HMA's two endpoint score calls
spend **8.94 s** attaching canonical traces in this instrumented control.

SC's audit/replay-certified route also invokes the static Python oracle once
per score. For its two logical scores, profiling finds two reactive runs,
two additional `run_order_commands` calls and four canonical-trace attachments.
The static calls consume **12.07 s** cumulatively; canonical trace attachment
across the primary/oracle results consumes **8.17 s**, partly overlapping.

Ordinary `full_report()` metric reduction is only **9.81 ms for HMA / 9.37 ms
for SC**, across both calls. The important distinction is dense audit/trace
construction versus the final numeric metrics reducer. Optimizing the latter
cannot explain or remove seconds of execution/audit overhead.

### SC: Per-Bar Callback Plumbing

SC makes 35,088 bar-close callbacks because the 17,544-bar account is scored
twice. Its control shows approximately **14.04 s** in `get_indexer` and
**6.04 s** in `numpy.testing.assert_allclose`. These are inside broader callback
costs, not independent additions. The private binding repeatedly resolves one
timestamp through a pandas list-like indexer and runs a testing assertion on
each bar; `_FoldCallbacks` additionally resolves its local bar index.

These are adapter/checking costs around original decisions. Removing a check
without an equivalent fail-closed financial-state witness would be incorrect.
Positional cursor validation and a narrow numeric comparison are candidates,
not already implemented optimizations or changes to the original alpha logic.

## Recommended Order Before The Long Queue

1. **Separate trial computation/output requirements from final audit.** Keep
   every account path/metric witness and actual-fill feedback needed by Mode 4
   and meta. Defer dense trace rendering and full oracle verification to the
   registered certification controls/selected audits where permitted. A blind
   scalar placeholder or merely changing `profile` without parity is unsafe.
2. **Exact in-evaluation score reuse and callback plumbing.** Preserve both
   logical whole-IS/shard observations while deduplicating physical work only
   under a qualified deterministic contract. Replace repeated timestamp
   searches/testing machinery with equivalent explicit cursor/state checks.
3. **Feedback compiler ownership.** First reduce repeated ID/string projection
   and tape packing without weakening prefix checks. Assess the existing
   persistent Rust reactive/session boundary for actual feedback, instead of
   making a new full-run owner for each command change. Same-bar protection,
   fill ordering, quantity constraints, cancel/OCO, retries and fold carry all
   require independent parity before such a path can replace the current one.

For each performance change, preserve ordered proposals/objectives, seeds,
selection, valid/pruned states, accounting and required evidence. Compare
matched uninstrumented controls and the affected public path before measuring
a speedup. Do not reduce 128 trials, 57 folds, the 16-label panel, maturity
threshold or inference support to reduce cost. Do not route an order/next-open
contract into the incompatible prepared target scorer simply to enable Rust.

No optimized speedup or precise whole-study ETA is claimed. Expanding IS and
event-dependent replay make `76 minutes * 57` an unreliable forecast. The
long queue remains unlaunched pending the performance disposition and budget.

## Custody And Cleanup

Ignored private evidence:
`m5-11-6/attempt-01/performance-review01/{registration,cold-summary,closeout}.json`
and per-control `functions.json`, generation journal and terminal result.
The closeout verifies **962 input pins** and both original metric witnesses.
Retained outputs before closeout are **1,269,141 bytes**, below the 16-MiB cap;
free disk remains over 5 GiB. Two single-threaded controls exited successfully.
No disposable scratch, new environment or build was created, so cleanup is an
explicit **no-deletion receipt**. Previous scientific evidence and the current
native artifact/environment remain unchanged. Private alpha code/parameters
are not copied into this report or public package inputs.
