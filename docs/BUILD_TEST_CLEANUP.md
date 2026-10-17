# Build And Test Cleanup

## Scope

Cleanup is a required operational exit gate for every build/test phase, including
failed runs. It is not a financial, empirical, remote or release certificate.
The [unified plan](../upgrade/implement.md#mandatory-buildtest-cleanup-gate) and
[workspace rules](../AGENTS.md#build-and-test-cleanup) govern this procedure.

## Before A Run

1. Measure `df -h` and `df -i` for the actual working filesystem. Check both
   bytes and inodes, including filesystem-reserved space and quotas if relevant.
2. Inventory `rust/target`, `.maturin`, temporary build caches and intended
   consumers. Avoid summing overlapping or hard-linked directory sizes.
3. Estimate peak incremental space for the run and leave at least 5 GiB safety
   headroom beyond that estimate. Stop before creating another environment if
   that budget is unavailable; this is a policy budget, not a performance gate.
4. Record the exact scratch directories and retained outputs. Prefer reusing
   one controlled tooling environment, not a new full dependency environment
   for every small test shard. Independent installed consumers still need
   isolated financial/config/RNG state and exact installed artifacts.
5. Check active host processes before deleting a cache or virtualenv. Sandbox
   process listings can hide host processes. Never kill unrelated services.
6. For checkpointed research, do this review between lanes as well as at phase
   exit. Clean completed test-fixture scratch and superseded consumers before
   admitting another lane. Distinguish the retained ceiling from current usage;
   inspect duplicate snapshots, verbose per-bar JSON and repeated reports
   before increasing the allowance. Do not treat a larger allowance as the
   solution to unexamined storage duplication.

## Retain

- Tracked/untracked source, Git objects/branches and user working changes.
- Alpha/market data, private sandboxes, research outputs and evidence bundles.
- Immutable JSON/XML receipts, benchmark outputs, command/build/consumer logs.
- Exact core/native wheel and sdist files referenced by receipt hashes.
- Source staging files referenced by historical source/artifact verification.
- The primary project environment, current test/build tooling environment and
  historical `pair` environments still referenced by replay harnesses.
- Offline dependencies needed to reinstall consumers; do not remove the only
  cached wheel/source package while networking is unavailable.

Do not edit old evidence to make a cleaned environment look installed. A stored
receipt describes its historical execution. To rerun after environment cleanup,
create a fresh isolated consumer using the retained exact artifacts, record new
logs/receipt, and verify loaded module origins and extension hashes again.

## Eligible Scratch

Only exact paths reviewed for the current cleanup are eligible:

- Inactive Rust incremental compilation cache inside an ignored target tree.
- Superseded or failed installed-consumer virtualenvs identified by `pyvenv.cfg`.
- Build-tool virtualenvs no longer used, after their exact output is retained.
- Disposable caches with no active process or offline dependency requirement.

Removing consumer dependencies is not removing their proof: retained logs,
receipt and exact artifacts remain independently hash-verifiable. However,
that deleted environment cannot be executed until reinstalled. Never delete
an entire evidence lane merely because it contains a disposable virtualenv.

Use exact directory names, verify resolved paths and Git ignore status, and
reject symlinked roots or unreviewed path changes. Do not use broad wildcard
deletion, `git clean -fdx`, whole-`.maturin` removal, Docker/system prune, log
truncation, arbitrary Poetry-environment removal or global cache removal.

## After A Run

1. Preserve evidence/artifacts before deleting scratch, on success or failure.
2. Record protected artifact/log hashes and source state before cleanup.
3. Remove reviewed scratch only after confirming inactivity and ownership.
4. Recheck exact hashes, source/working-tree changes and current native imports.
5. Record before/after filesystem bytes and free space, deleted paths, retained
   environments, cleaned consumers needing reinstall and any exclusions.
6. Commit the coherent rules/plan/report change without unrelated working edits.

Report actual filesystem improvement separately from apparent `du` sizes. A
hard-linked package shared by UV and a virtualenv is freed only after its last
link is removed. Process-held deleted files and filesystem reserves can also
prevent a directory-size reduction from becoming available working space.

## ENOSPC Recovery

Start with known reproducible inactive cache, not source or scientific outputs.
If the sandbox or approval mechanism cannot launch because disk is full, report
that limitation and request host guidance; do not bypass approval or claim that
cleanup happened. Once recovered, preserve the failed build record and use a
fresh output lane. A partially installed consumer is never a passing package
proof. Resume domain work only after disk and evidence checks are complete.

## Recorded Cleanup

The [M4-ML-07 receipt](maintenance/M4_ML_07_CLEANUP.md) records completed local
research owners, three exact inactive scratch roots,135 protected files unchanged
and94,208 actual available bytes recovered. The retained original accounts,
model/query/failure evidence, current tooling and native binaries remain.

The [M4-ML-06 receipt](maintenance/M4_ML_06_CLEANUP.md) records terminal
research/test workers, one exact ignored scratch root, 1,462 protected files
unchanged and 3,141,632 bytes of actual available-space recovery. All source,
original accounts, model/query/failure evidence and current tooling remain.
This registered source-only research closure is not an installed/public proof.

The [M4-ML-03](maintenance/M4_ML_03_CLEANUP.md),
[ML-04](maintenance/M4_ML_04_CLEANUP.md) and
[ML-05](maintenance/M4_ML_05_CLEANUP.md) receipts record terminal research/test
owners, exact ignored fixture cleanup and unchanged protected model/account
evidence. The private CPU-only wheel remains for offline research; no core
environment, native artifact, service or scientific result was removed.
These source-only KEEP_V1 receipts are not final-wheel or public release proofs.

The [M4-ML-01/02 receipt](maintenance/M4_ML_01_02_CLEANUP.md) records exact
inactive fixture cleanup with 425 protected hashes and 170 host processes
reviewed. ML-02 observed +2,211,840 available bytes; all failed/passing replay,
private market/alpha evidence and the reused native/tooling remain. No finance,
environment replacement, build, service stop or release occurred.

The [shared alpha diagnostics receipt](maintenance/SHARED_ALPHA_DIAGNOSTICS_CLEANUP.md)
records 348 passing local checks, removal of one exact owned synthetic test
root, 34 protected source/artifact/evidence hashes unchanged and 2.66 MiB observed
free-space recovery. Initial failed attempts are retained; no financial study,
environment replacement, native rebuild or release occurred.

The [M5-11.6.1 terminal receipt](maintenance/M5_11_6_1_TERMINAL_CLEANUP.md)
records completed quarterly study/verifier owners, two exact inactive test-root
removals and 40,492 protected files unchanged. It distinguishes linked-path
retention from unique-inode bytes and reports the actual -819,200-byte free-space
delta without claiming a net saving. All native/data/source/failure evidence and
current tooling remain; no release or economic promotion follows from cleanup.

The [M5-11.6.1 admission receipt](maintenance/M5_11_6_1_ADMISSION_CLEANUP.md)
records eight completed original HMA controls, 104 pure-tool tests and exact
inactive scratch removal after host-process review. It preserves two agent XML
receipts, verifies 3,022 protected files and observes 0.38 MiB free-space recovery.
Current JIT/native/tooling and all financial/failure evidence remain. This is
not admission of a variant study or quarterly economic certification.

The [M5-11.6 rolling-preflight receipt](maintenance/M5_11_6_ROLLING_PREFLIGHT_CLEANUP.md)
records 16 cells, eight fixed IS controls, 41 exact inactive JIT-cache files,
629 protected hashes and 72 host processes reviewed. Observed recovery is
1.23 MiB; every source, failed/passing evidence, environment and native binary
remains. This is not long economic-study or release certification.

The [M5-11.6 native transaction receipt](maintenance/M5_11_6_NATIVE_TRANSACTION_CLEANUP.md)
records one incremental offline build, 12 bounded saved controls, exact inactive
six-file JIT-cache removal, 540 protected hashes and 72 host processes reviewed.
Candidate/original native binaries, source copies and every failed/passing
receipt remain. The observed free-space delta is negative 40 KiB after receipt
writes/host activity, not a claimed saving. A later owner-isolation guard has its
own source/test amendment; no long WFO, environment removal or release occurs.

The [M5-11.6 performance receipt](maintenance/M5_11_6_PERFORMANCE_CLEANUP.md)
records 16 completed matched account controls, 1,819 protected files verified,
71 host processes reviewed, exact inactive JIT/test scratch removal and 1.43 MiB
observed recovery. Source snapshots, every financial/failure receipt and the
current environment/native artifact remain. Full-tape HMA replay and the long
research phase are not certified as closed by this cleanup.

The [M5-11.6 bounded-tranche receipt](maintenance/M5_11_6_TRANCHE_CLEANUP.md)
records four reaped 128-attempt studies, terminal cold readback, exact inactive
JIT-cache removal and 1,743 protected files unchanged. The no-delete preflight
failure remains retained. Actual available-space recovery is 124 KiB; no source,
financial evidence, current environment or native artifact is removed. The
57-fold research phase and mature-meta gates remain open.

The [M5-11.5 decision receipt](maintenance/M5_11_5_DECISION_CLEANUP.md) removes
three exact inactive scratch roots after all financial and test workers exit,
verifies 4,402 protected files and 170 host PIDs, and retains every account,
failed receipt, artifact and current environment. Its final 5.18-MiB observed
recovery is separate from earlier fixture cleanup and from retained scientific
evidence. No installed-package or economic certification follows from cleanup.

The [M5-11.4 between-lane review](maintenance/M5_11_4_STORAGE_REVIEW_CLEANUP.md)
removes three obsolete consumers and seven inactive fixture roots, verifies
8,779 protected files and nine artifact references, and records a 1.661-GiB
observed available-space increase. It distinguishes current 2.335-GiB evidence
from the prospective 10-GiB ceiling, retains the failed/partial parent and all
account evidence, and does not certify full diagnostic coverage.

The [M5-11.3 forward receipt](maintenance/M5_11_3_FORWARD_CLEANUP.md) records
the closed serial prefix studies and all three annual forward owners, exact
inactive scratch removal, protected source/account retention and terminal
readback of 7,948 pins. No financial rerun, environment deletion, service stop
or broad cache cleanup occurs; adverse economics and failed receipts remain.

The [M5-11 cold-gap receipt](maintenance/M5_11_COLD_GAP_CLEANUP.md) records
registered fixture scratch removal, preserved failed/completed receipts and
three retained source-bound dossiers. Final readback verifies 1,787 pins and
1,392 original probe view records; no finance is repeated. Remaining free space
is capacity, not net savings from the intentionally retained evidence.

The [M5-11.1 owner-stopped tranche receipt](maintenance/M5_11_1_TRANCHE_CLEANUP.md)
records exact research-worker stop/reap custody and inactive HASH Numba-cache
removal, 2,777 retained pin checks and 1.40 MiB observed filesystem recovery.
Complete/failed/censored research evidence, source, current tooling and exact
artifacts remain. An interrupted account's exact work stays unknown; cleanup
does not certify the incomplete phase or terminal order state.

The [M5-11 receipt](maintenance/M5_11_CLEANUP.md) records exact inactive
research-test/native-extraction scratch removal after host process/FD/maps
review, 3,620 protected records (one documented authorized sampler amendment),
115 retained files and 329 current source/harness hashes checked. Observed
filesystem recovery is 15.50 MiB; evidence, failures, private inputs and current
tooling remain. Native extraction requires exact-artifact restoration for rerun.

The [M5-10 receipt](maintenance/M5_10_CLEANUP.md) records exact inactive
build/test/installed-consumer scratch removal after host process/FD/maps review,
2,757 protected, 491 retained and 317 current source/harness hashes unchanged,
and 386.48 MiB observed filesystem recovery. Exact core/native artifacts,
failed/passing receipts, prior/private evidence and current tooling remain.
Cleaned consumers require fresh installation before rerun.

The [M5-09 receipt](maintenance/M5_09_CLEANUP.md) records exact inactive
research-test scratch removal after host process/FD review, 3,449 protected
prior and 18 current source hashes unchanged, and 7.29 MiB observed filesystem
recovery. All dossiers/plans/journals, original/failed/repair receipts, source
copies, data and current environments remain; no financial rerun/build occurred.

The [M5-08.1 receipt](maintenance/M5_08_1_CLEANUP.md) records exact inactive
historical-diagnostic scratch removal after host process/FD review, 2,803
protected and 635 retained hashes unchanged, and 8.26 MiB observed filesystem
recovery. All actual account paths, source copies, failed attempts, current
tooling and artifacts remain retained; no environment or rebuild is involved.

The [M5-08 receipt](maintenance/M5_08_CLEANUP.md) records exact inactive
pytest/JIT/plot scratch removal after host process/FD review, 1,445 protected
and 1,339 retained hashes unchanged, and 7.61 MiB observed filesystem recovery.
All five-alpha paths, sampler/stress evidence, failed attempts, private source,
current tooling and exact artifacts remain retained; no rebuild ran.

The [M5-07 receipt](maintenance/M5_07_CLEANUP.md) verifies 1,359 protected and
21 current source/harness hashes, retains all math/benchmark/failure evidence,
and removes only the inactive registered scratch after host process/FD review.
Actual filesystem recovery is 6.46 MiB; no environment or artifact is removed.

The [M5-06 receipt](maintenance/M5_06_CLEANUP.md) records two exact inactive
scratch removals, 1,055 protected inputs and 21 current source/harness hashes
verified, and 10.86 MiB combined observed filesystem recovery. Native binary
provenance was corrected in a preserved new revision; account/geometry matrices
remain byte-identical, with no additional alpha execution or environment removal.

The [M5-05 receipt](maintenance/M5_05_CLEANUP.md) records two registered inactive
scratch removals, 802 protected inputs, 79 prior receipts and 10 current-source
hashes unchanged, and 11.44 MiB combined observed filesystem recovery. All
evidence, private sources/data, artifacts and current environments remain retained.

The [M5-04 receipt](maintenance/M5_04_CLEANUP.md) records two inactive registered
pytest/JIT scratch removals, 669/743 protected and 73/48 retained hashes unchanged,
and 6.38/5.81 MiB observed filesystem recovery. No environment or artifact was removed.

The [MET-03 receipt](maintenance/MET03_CLEANUP.md) records source/installed
reporting certification, sequential consumer removal, preserved exact artifacts
and failed evidence, and concurrent resource budgets. It distinguishes apparent
hard-linked sizes from measured filesystem recovery; no Rust rebuild occurred.

See the [2026-10-06 receipt](maintenance/CLEANUP_2026-10-06.md) for exact deletions,
retained-file checksums, environment retention and measured disk improvement.
The [E04/E05 follow-up](maintenance/QMS_E04_E05_CLEANUP_2026-10-06.md) records
two inactive consumer removals, exact retained artifacts and 1.09 GiB reclaimed.
The [E03-G01 follow-up](maintenance/QMS_G01_CLEANUP_2026-10-06.md) records only
inactive Rust incremental-cache removal, unchanged protected hashes and 219.656
MiB actual free-space improvement; current consumers/evidence remain retained.
The [PRE-E06-02 receipt](maintenance/QMS_PRE_E06_02_CLEANUP.md) records tooling
reuse, under 1 MiB retained test evidence and unchanged protected hashes; no
disposable build scratch was created or deleted.
The [PRE-E06-06 receipt](maintenance/QMS_PRE_E06_06_CLEANUP.md) records four
exact inactive artifact-consumer/build removals, 401 protected hashes unchanged
and 1,155.10 MiB observed free-space improvement. Exact artifacts, staged source,
passing/failing evidence, current tooling and offline dependencies remain;
cleaned consumers require fresh installation before rerun.
The [E06 receipt](maintenance/QMS_E06_CLEANUP.md) records two new inactive
consumer removals, 93 protected hashes unchanged and 1,135.17 MiB observed
free-space improvement. Exact artifacts, logs, frozen histories and current
tooling remain; E06 consumers require fresh installation before any rerun.
The [E07 receipt](maintenance/QMS_E07_CLEANUP.md) records four exact inactive
build/consumer removals, 941 protected hashes unchanged and 1,151.35 MiB observed
free-space improvement. Exact artifacts, staged source, histories, passing and
failed evidence, tooling and offline dependencies remain; cleaned consumers
require a fresh isolated installation before rerun.
The [E08 receipt](maintenance/QMS_E08_CLEANUP.md) records four exact inactive
build/consumer removals, 410 protected hashes unchanged and 1,155.875 MiB
actual free-space improvement. Exact final artifacts, histories and successful/
failed evidence remain; no broad cache or historical-lane deletion occurred.
The [sampler-helper receipt](maintenance/QMS_SAMPLER_HELPER_CLEANUP.md) records
seven exact inactive build/consumer removals, 740 protected hashes unchanged
and 1,697.207 MiB actual improvement. Failed and passing lanes remain sealed;
the copy-mode disk-budget variance is explicit and future preflight corrected.
The [M5-02 receipt](maintenance/M5_02_CLEANUP.md) records four registered inactive
JIT scratch removals, 435 protected hashes and 232 retained evidence/copy hashes
unchanged. The observed immediate free-space increase is 8.871 MiB; no private
evidence, alpha/data source, shared environment or artifact was removed.
The [M5-03 receipt](maintenance/M5_03_CLEANUP.md) records one registered inactive
pytest/Numba/Matplotlib scratch removal, 765 protected and 52 retained hashes
unchanged, and 5.574 MiB immediate improvement. Both reused environments,
successful/failed receipts, private reanalysis and prior inputs remain retained.
