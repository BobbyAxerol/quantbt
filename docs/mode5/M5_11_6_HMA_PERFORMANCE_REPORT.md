# M5-11.6 HMA Performance Qualification

## Scope

This implements the five owner-approved priorities in the
[isolated amendment](M5_11_6_HMA_PERFORMANCE_PLAN.md). Status is
**PASS_FIXED_WINDOW_OPTIMIZATION**, not completion of the 57-fold study,
installed-wheel qualification, or measured full-WFO acceleration.

No optimizer was launched. No private alpha formula, objective, candidate,
horizon, accounting rule or public endpoint changed. The final preferred
candidate uses delta packing and root-owned immutable preparation. It is not
installed into the stopped long queue. Packed/fused native transport is tested
but remains opt-in because fewer calls did not consistently beat delta.

## Measurements

Four cases were chosen prospectively by lowest/highest saved command count,
not returns/objectives. Each scores **730 days / 17,520 hourly bars**, with
permitted preload from 2020. Windows end exclusively at 2022-01-01 and
2026-09-01. Two repeats per arm use one numeric thread on the same shared VPS.
JIT caches are shared; each financial control gets a fresh process and session.
Persistent preparation reuse has ownership tests, not a measured warm-WFO claim.

Times are medians of two repeats. Compile/generate includes preparation, alpha
decisions, command compilation and actual feedback. The final column adds one
independent original-engine audit. Process/import/setup and subsequent report/
observer verification are outside these timers.

| Case | Original Compile | Final Compile | Speedup | Compile + Audit |
|---|---:|---:|---:|---:|
| Early, no orders | 3.685 s | 3.230 s | 1.14x | 6.86 -> 6.49 s |
| Early, many orders | 25.179 s | 16.643 s | 1.51x | 30.27 -> 21.70 s |
| Late, no orders | 6.601 s | 5.459 s | 1.21x | 9.87 -> 9.39 s |
| Late, many orders | 24.041 s | 18.222 s | 1.32x | 28.87 -> 23.77 s |

Order-heavy compilation fell **24.2-33.9%**, or **17.7-28.3%** including audit.
No-order controls improved less. Late order-heavy candidate repeats were
**15.918 and 20.525 s**; shared-host noise is material. These samples do not
establish p95, confidence intervals or the adaptive-study average.

Median process peak RSS decreased about **8-19 MiB** per case. Original peaks
span **456.1-520.2 MiB**, candidate peaks **447.8-501.4 MiB**. This includes
imports/JIT, not native live heap alone. No large RAM reduction is claimed.

All 40 initial ablation controls remain, including regressions: deduplicated
preparation introduced per-bar witness-copy overhead; lean/fused paths were not
uniformly faster. Witness ownership was corrected before eight additional final
controls. Four baseline bundles were hash-verified custody copies, not new runs.

## Implemented Changes

1. Binding consumes a verified pristine prepared template instead of preparing
   the same alpha twice. Eleven feature arrays match the original byte-for-byte.
2. A bounded feature LRU keys source/version, snapshot, permitted prefix/cutoff,
   indicator dependencies and RSI variant. Market validation remains exact.
   Root owns preparation/current native runner; child close does not clear them.
   Each execution still creates a fresh FullSession. Params, decision/cursor,
   order/account and RNG state are not shared between independent candidates.
3. Typed state/staged-level snapshots preserve retry, schedule identity, cursor
   and record rollback. Unknown layouts fail closed. Full requested decisions
   remain; immutable preparation witnesses stay outside per-bar snapshots.
4. Fresh/changed commands are compiled and only current-bar numeric rows gathered.
   IDs, global ordinals, expiry and committed prefixes remain exact. This is not
   O(1): new tuples still require exact prefix checks; the original fresh-row
   compiler still constructs its authoritative calendar pointer.
5. Optional native packed f64/i64 feedback/deferred advance uses the same
   FullSession. An early high-order case reduces boundary calls **53,470 ->
   18,431**, preserving 18,430 steps and 910 same-bar retries. Fewer calls alone
   are not a speedup. Final continuous-account replay remains unchanged.

Generic helpers and a reproducible
[`git apply --check`-validated native patch](../../tools/mode5_research/native_feedback_packed.patch)
are versioned without changing pinned runtime files. HMA-specific bindings,
sources, parameters, native artifact and receipts remain private/ignored.

## Correctness And Custody

- **251 Python tests** and **8 new Rust tests passed** against the separate
  candidate extension, covering lifecycle, OCO/retry, ownership, malformed
  requests, IDs beyond 2^53, funding, liquidation and final flush.
- **48 successful financial controls; zero new optimizer proposals.** Account,
  fill/lifecycle buffers, terminal state, IDs, commands, original decisions,
  staged state, rejections and terminal intents agree exactly. Independent
  original-engine audit agrees; no tolerances were relaxed.
- Original Mode 4 reduction/meta observation runs on the already-executed
  accounts preserve objective, metrics, observation and selection-metadata hashes.
- All **708 original long-queue source pins** remain unchanged. No scientific
  seed, estimator, pool, label or selection gate was changed.

Private summary: `upgrade/private/mode5_upgrade_v1/m5-11-6/attempt-01/hma-perf-v1/summary.json`.
An append-only status wrapper failure reused completed finance rather than
rerunning it. A later admission namespace error failed before finance. A
test-only Rust import failure was corrected with public domain enums. Their
failed receipts/logs remain; none was rewritten as PASS.

## Stopped Queue

The supervisor stopped at **20:45:50 Asia/Saigon, 2026-10-15** because the 5-GiB
reserve plus remaining output forecast was unavailable. VWAP had completed;
the supervisor stopped HMA, HASH and SC. This occurred while the isolated HMA
build shared the filesystem: source isolation was not resource isolation.
No unrelated service was signalled and no alpha was automatically restarted.
See the [current queue status](M5_11_6_LONG_ROLLING_QUEUE.md#current-guard-stop).

HMA retains **21 complete folds, 2022-01 through 2023-09**. Fold 21 (2023-10)
has 54 partial attempts: 53 complete, one pruned; no completed pool/selection/
revision receipt. Readback reconciles all 21 completed search/selection/
observation/revision bundles. They are not full-WFO checkpoints.

## Continuation Proposal

Prefer a separately qualified **manual prefix handoff**, not seed-only resume:

1. Review-import the 21 revisions and both parameter schedules. Deserialization
   defaults to unverified; do not forge verification flags.
2. Preserve family/run/corpus, clocks, maturity and original fold IDs. Provider
   class changes affect strategy fingerprint and need explicit compatibility
   review, not silent substitution.
3. Restart only interrupted fold **21**, seed **21,000,794**, from trial zero;
   then complete **36 folds / 4,608 proposal slots**. Retain/charge the old
   partial work; do not claim its exact Optuna RNG continuation.
4. Verify cold/mature prefix reconstruction: proposal order/objectives, models,
   ranks, labels, chronology and both schedules. Rebuild/replay full continuous
   accounts from all saved params, never concatenate diagnostic equity.

The current runner requires a new output directory and empty MetaHistory.
Exact Optuna continuation exists elsewhere but is not wired into this runner.
Handoff needs implementation and focused qualification before another launch;
it does not inherently require rerunning 21 completed searches.

## Conditional Estimate

The 21 completed searches took **31,972.8 s / 8.88 h**, averaging **25.38 min/fold**,
including the inspection pause. Straight-line old search cost is **15.23 h**
for 36 remaining folds, **24.11 h** for all 57.

For planning only, allowing 70-100% of that cost after optimization plus 5-15%
for longer preload/shared-host variability gives approximately **11-18 h of
remaining search**, or **18-28 h of search from scratch**. These are conditional
model envelopes, not measured full-WFO ETAs or confidence intervals.

Handoff implementation/qualification, observer labels, final continuous assembly/
replay and closeout are additional. The unchanged final replay can be expensive
and is not benchmarked on a complete 57-fold schedule. No new long study, CI,
push, merge or publication is activated by this report.
