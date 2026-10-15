# M5-11.6 HMA Prefix Handoff

## Approval And Scope

The owner approved an HMA-only background restart on 2026-10-15, following the
[performance qualification](M5_11_6_HMA_PERFORMANCE_REPORT.md) and the
[rolling study](M5_11_6_LONG_ROLLING_QUEUE.md#current-guard-stop).
The old worker is dead: this is a new PID, not SIGCONT or exact recovery of an
interrupted Optuna study. SC, HASH and VWAP are inspected only, not restarted.
The [unified phase](../../upgrade/implement.md#mode5-m5-11-6) and all approved
scientific contracts remain unchanged. Original source pins and receipts must
not be rewritten to admit the restart.

## Work And Gates

1. Register exact custody of the 21 completed HMA folds (2022-01 through
   2023-09), their source/data/native identities and canonical observations.
   Preserve the 54 attempted slots in interrupted fold 21 as failed-run costs;
   they are not a resumable Optuna checkpoint.
2. Qualify a private, fail-closed prefix handoff through the existing WFO/meta
   contracts. Reconstruct native/trial/sampler records, decisions and history in
   chronological order. Review original output witnesses before importing a
   revision; serialized verification flags are not sufficient authority.
3. Check snapshot maturity, candidate/panel/model/decision identities and
   parameter schedules. Explicitly bind the optimized provider dependencies to
   the old logical strategy family with the retained exact financial parity
   witnesses. Do not forge a class, hash, family or evidence receipt.
4. Prefix-only placeholders may carry a typed calendar through orchestration;
   they must never be executed or used to derive financial observations.
   Final assembly must use the original full-calendar continuous-account
   provider and all 57 saved parameter decisions, followed by independent
   original-engine replay of six account paths and fills.
5. Test missing/tampered custody, wrong family/calendar/seed, chronology and
   complete-versus-handoff behavior before launch. No completed optimizer is
   rerun for qualification. Any failed gate is retained and blocks launch.
6. Start one supervised HMA worker from fold ID 21 (October 2023), with its
   original derived seed and all 128 attempts. Continue the remaining 36 folds
   with the qualified delta compiler, unchanged meta/scoring/label policies.
7. Verify the new PID and durable new progress; report other alphas separately.
   Financial completion is not a phase PASS. M4X qualification, economic
   analysis and owner review remain phase exit work.

## Resources And Cleanup

Use the existing environment/native artifact; no build, installation or market
download. Admission checks free bytes and inodes, host RAM and absence of a
duplicate HMA worker. Allocate at most 128 MiB retained output and 32 MiB
reproducible qualification/JIT scratch, within the previously approved queue
budget, with a 5-GiB free disk reserve beyond remaining output forecast. Use one
worker and one numeric thread per pool; keep host available RAM >=512 MiB.
Do not stop unrelated services. The recovery cannot extend the originally
approved 48-hour queue deadline without a separate approval.

Keep all original receipts, finance, private sources, exact native binaries and
the existing environment. Cleanup only registered inactive JIT/test scratch
after owned workers have exited and host references have been checked. Record
actual reclaimed bytes and reverify preserved hashes. Private alpha parameters
and helpers remain ignored and excluded from package artifacts.

Before restart, the owner's additional cleanup request admits exactly reviewed,
inactive, single-link `.rlib`, `.rmeta` and `.d` dependency-cache files in
`rust/target/debug/deps`. The initial inventory is 589 files / 573,496,370
apparent bytes. Host cwd/executable/FD/maps checks and retained-source/evidence/
artifact hash verification are mandatory before deletion. Exact extensions,
test executables, wheel/sdist outputs, historical pair environments, the current
tooling environment and offline registry caches are excluded. A future debug
build must regenerate the deleted dependency cache; this is not an artifact or
financial proof invalidation.

## Status

This is the prospective source-pinned plan, not a launch receipt. The
[pre-restart cleanup receipt](../maintenance/M5_11_6_HMA_RESTART_CLEANUP.md)
records exact inactive dependency removal and retained evidence. Operational
qualification/launch status is recorded separately in
[the handoff status report](M5_11_6_HMA_PREFIX_HANDOFF_STATUS.md); no PID or
recovery PASS is certified by this plan alone.
