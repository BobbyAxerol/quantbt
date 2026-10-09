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

The [M5-04 receipt](maintenance/M5_04_CLEANUP.md) records one inactive registered
pytest/JIT scratch removal, 669 protected and 73 retained hashes unchanged,
and 6.38 MiB observed filesystem recovery. No environment or artifact was removed.

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
