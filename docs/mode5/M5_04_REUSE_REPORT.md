# M5-04 Shared Diagnostic Reuse Report

**Technical:** COMPLETE_LOCAL_REUSE / TECHNICALLY_VALID, 2026-10-09.
**Scientific:** DESCRIPTIVE_ONLY. No new economic study, tuning or deployment.

## Delivered

- Research-only `tools/mode5_diagnostics`: union requirements compiled into the
  existing computation plan; immutable input buffers and typed panel rows.
- Execution/analysis/selection identities with independent every-access
  role, manifest, cutoff and maturity authorization. Holdout validation rights
  cannot authorize selection, including when the output is already cached.
- Shared bounded LRU ownership, explicit missing-input errors, fresh/reset
  existing execution and no implicit simulation replay for reporting.
- Existing columnar audit writer with a POSIX fsync/atomic export hook, bounded
  chunks/bytes and synchronous backpressure. Completion reconciles externally
  expected trial IDs and table counts; failed/cancelled/interrupted writes
  cannot produce a successful final marker.

This does not change `src`, `rust`, `contracts`, endpoints, Mode 1..4, legacy
Mode 5, scientific objectives/selectors, RNG or ask/tell order. It is not yet a
new pip-installed public diagnostics facade; integration has its own later gate.

## Verification

**981 passed, zero failed/skipped**, including **47 M5-04 tests** and all ten
guide acceptance IDs M5T-031..040. Shared audit/cache, metrics, prior Mode 5
and privacy/release-surface regressions are included. Three known Optuna
experimental warnings remain warnings, not missing cases.

Actual prepared Rust execution matches the Python oracle and scalar output
under the same synthetic contract. Equity, positions, fees, turnover and margin
match within declared numerical tolerances; cached/fresh retained buffers match
exactly. The fixed-fill fee-change control executes again and changes accounting
as expected. Threaded duplicate requests execute once, without mutable account
reuse. This is a bounded fixed-panel control, not parallel adaptive-search proof.

Negative controls cover changed source/effective parameters, market, fee/funding/
instrument, clock, state, warmup, terminal and seed; holdout relabelling, immature
cutoffs, invalid objectives, missing streams, deepcopy/pickle immutability,
Optuna COMPLETE/PRUNED/FAIL cardinality, duplicate/cancelled attempts, slow sinks,
byte/chunk limits, fsync failure, missing/modified/extra audit chunks and absent
completion markers. The final concurrent durable-log control failed before
serialization (duplicate chunk publication) and passes afterward: eight access
rows, one execution and three reuse hits. Failed earlier attempts remain in
private append-only receipts; attempt-01's seal is historical, not the final source.

## Matched Cost

Public synthetic static order fixture, 2,000 bars, prepared Rust v2 linear
account, no funding, compact account plus fill buffers. Twenty-five interleaved
matched pairs; identical input, preparation, contract and returned evidence.

| Query | p50 | p95 | Financial Executions In 25 Measured Queries |
|---|---:|---:|---:|
| Prepared, no output cache | 1.462 ms | 1.910 ms | 25 |
| Exact authorized cache | 0.239 ms | 0.394 ms | 0 |

One initial execution populated the warm cache before measurement. The p50
ratio is **6.11x** for identical-query reuse, not a simulation-kernel upgrade or
a general WFO speedup. These short synthetic cells do not predict a full-alpha
study's runtime. Retained synthetic payload/cache is **128,710 bytes**.

The five-alpha history reanalysis/reuse proof takes **5.847 s**, with same-process
peak RSS **275.84 MiB**, including imports/JIT/reducers and the synthetic
benchmark. Its shared resident cache is **861,199 bytes**. No isolated RSS
improvement is claimed; avoiding execution still requires retaining inputs.

## Historical Evidence

Recovered all **156 available comparison cells**: baseline 80, T1 60, T2 16.
Imported all five sealed account paths: 2,184 hourly bars and 91 complete UTC
days each. Existing M5-03 statistics reconcile exactly; four nonempty campaign
ledgers reconcile money PnL and fees. Ten analysis reductions, five analysis
cache hits and five denied early-cutoff accesses are recorded. **Zero private
alpha simulations or optimizer trials** were performed.

The reviewed masters do not contain the full adaptive 100-trial/path histories.
These comparison cells are not substitutes for that history. RSI's original
export lacks authoritative campaign/separate-cost streams; richer requests
raise `REPLAY_REQUIRED`, not fabricated fills. These are explicit evidence
limits for downstream diagnostics, not permission to omit a bad sample or run
an unregistered sweep. The reviewed 2024 pilot is not untouched validation.

## Handoff

No open implementation blocker/debt within M5-04's registered scope. The
[cleanup receipt](../maintenance/M5_04_CLEANUP.md) verifies source/evidence
preservation; the [final seal](evidence/m5-04-final.json) binds the private report, current
test receipts and final closure. No build, dependency install, CI, push, merge,
tag, version change or publication occurred. M5-05 requires separate approval.

Read the [reuse contract](DIAGNOSTIC_REUSE_V1.md),
[unified plan](../../upgrade/implement.md#mode5-m5-04), and
[detailed guide](../../upgrade/QUANTBT_MODE5_UPGRADE_V1_DIAGNOSTICS_FIRST_GUIDE_VI.md#phase-m5-04--diagnostic-panel-planner-cache-và-provenance).
