# M5-11.6 HMA-Only Performance Amendment

## Authority And Isolation

Owner approval on 2026-10-15 covers five priorities: eliminate duplicate
preparation, reuse immutable inputs, reduce per-bar snapshot/projection work,
pack command deltas, and reduce Python/Rust crossings without changing finance.
This is a bounded performance amendment to the
[approved phase](../../upgrade/implement.md#mode5-m5-11-6), not a new economic
study or activation of M5-11.7/M5-12.

The live queue pins `upgrade/implement.md`, original Python sources and native
artifacts. Editing those files would stop unrelated workers. Therefore this
prospective companion is linked through the
[queue report](M5_11_6_LONG_ROLLING_QUEUE.md); merge its final receipt into the
unified plan only after the active source-pin lifetime ends. The original
manifest and historical receipts remain unchanged. Preserve owner working edits.

Do not signal, reconfigure, replace or benchmark SC, HASH or VWAP. HMA's current
process also remains unchanged during isolated qualification: applying code to
it requires a separately verified state handoff, not a claim of seed-only
restart. A measured prototype is not automatically the live queue's runtime.

## Detailed Guides

- QMS [8 preparation, ownership and route parity](../../upgrade/QUANTBT_1_1_1_META_SELECTION_AND_SAMPLER_MODULE_GUIDE_V1_1_VI.md#s8),
  [10 equivalent work/performance](../../upgrade/QUANTBT_1_1_1_META_SELECTION_AND_SAMPLER_MODULE_GUIDE_V1_1_VI.md#s10),
  [12 honest reporting](../../upgrade/QUANTBT_1_1_1_META_SELECTION_AND_SAMPLER_MODULE_GUIDE_V1_1_VI.md#s12).
- Mode 5 [3 original alpha contracts](../../upgrade/QUANTBT_MODE5_UPGRADE_V1_DIAGNOSTICS_FIRST_GUIDE_VI.md#chapter-3),
  [4.6 causal prefixes/account attribution](../../upgrade/QUANTBT_MODE5_UPGRADE_V1_DIAGNOSTICS_FIRST_GUIDE_VI.md#46-trục-3--dual-perspective-environments-và-chronology),
  [7.5 exact reuse](../../upgrade/QUANTBT_MODE5_UPGRADE_V1_DIAGNOSTICS_FIRST_GUIDE_VI.md#75-targeted-tests-bốn-alpha-không-mặc-định-chạy-lại-t1t2).
- [Execution ownership](../architecture/execution-plan.md),
  [strategy boundary](../adr/ADR-RP-002-strategy-engine-boundary.md),
  [WFO schedules/RNG](../adr/ADR-RP-005-wfo-optimizer-schedules.md),
  [cleanup](../BUILD_TEST_CLEANUP.md).

## Work And Exit Gates

1. **P01 - Freeze and attribution.** Register saved low/high command-count
   configurations from the completed first HMA study, without choosing by
   returns. Score exact 730D IS at the early and late predeclared horizons.
   Split market/preparation, compiler, native transactions, packing, snapshots
   and cold output adaptation; nested timers are not additive disjoint costs.
   No optimizer, new range, seed, objective or alpha formula.
2. **P02 - Preparation.** Pass one exact prepared template to fresh decision
   owners. Reuse immutable market/calendar and indicator components with full
   snapshot/prefix/cutoff/dependency/version identity and bounded clear/reset.
   Never share mutable orders, account, RNG, staged state or learned labels.
3. **P03 - Decision loop.** Snapshot only explicitly qualified mutable fields;
   preserve restore-before-retry, decision truncation, staged risk and fill
   order. Reduce Python projections without discarding requested audit outputs.
4. **P04 - Tape.** Compile new/changed commands with the existing compiler and
   constraints. Stable ID/source ordering, rollback, current-bar amendments and
   exact committed-prefix checks remain mandatory. Avoid full calendar gathers
   when only a bounded current-bar delta is requested.
5. **P05 - Native boundary.** Stage a private copy of the existing native crate,
   reusing FullSession and transactions, not a second financial engine. Add an
   explicit fused/packed capability in a separate candidate artifact; original
   begin/step/commit remain available. Test retry/error/reset/close semantics and
   compare against the original boundary on identical command schedules.
6. **P06 - Matched qualification.** Run fixed saved low/high cases at early/late
   horizons, reference and optimized in balanced order, two repetitions per
   arm. Compare original indicator values, commands, decisions, six financial
   paths, fills, lifecycle, terminal/liquidation and original raw/objective
   units. Include empty/reject/same-bar OCO/rollback, cache mutation/cutoff/reset,
   changed-command and independent candidate isolation tests. No reduced trials,
   horizon or substitute vectorized strategy is an optimization claim.
7. **P07 - Handoff and cleanup.** Retain sources/artifacts/results, report
   measured wall/CPU/RSS/FFI counts, explicit limitations and activation status.
   Verify all live pins and untouched other workers. Commit coherent public
   changes without private alpha code; delete only reviewed inactive scratch.

Performance changes pass only when the original logical decisions/accounting
match. No tolerance relaxation, float32/fast-math, guessed fills, changed stops,
search parallelization or retroactive evidence repair. If a proposed change
does not improve the matched workload, retain its result and do not promote it.

## Resource Registration

Private helper/evidence lane suffix: `hma-perf-v1`, separate from the active
`long-rolling-monthly-v1` lane. Reuse the current Python environment and offline
Rust dependencies. No package installation. Fixed-control execution is serial,
one numeric/adaptive thread; no new adaptive study is authorized.

Retained ceiling 128 MiB; disposable JIT/test scratch <=64 MiB; incremental
native-build forecast <=512 MiB, admitted only with >=5 GiB disk reserve beyond
the remaining forecast. Before each heavy command, also reserve at least
512 MiB available host RAM beyond that command's forecast. Do not stop unrelated
services or adjust the live queue to obtain resources. Reuse an existing Cargo
cache only after inventory; never replace a live loaded extension. Cleanup
uses exact registered paths and protected artifact hashes, with failed results
retained as failures. No CI, push, publication or release.

## Status

APPROVED / IN_PROGRESS. No new benchmark, parity PASS, speedup or live activation
is claimed by this prospective plan. Detailed baseline, ablation, failure and
cleanup receipts must precede the final report.
