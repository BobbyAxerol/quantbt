# M5-11 Exact Scratch Cleanup

**PASS**, 2026-10-10. This is an operational receipt, not economic promotion or
current installed-package certification. Read the
[economic report](../mode5/M5_11_ECONOMIC_REPORT.md),
[source-bound summary](../mode5/evidence/m5-11.json) and
[cleanup rules](../BUILD_TEST_CLEANUP.md).

## Registration And Host Review

Before tests/search: one process/one numeric thread; 256 MiB retained budget,
1 GiB incremental scratch and at least 5 GiB free reserve. Filesystem had about
25 GiB free; bytes and inodes were checked separately. Current controlled tooling
was reused; no dependency download/install or native build occurred.

The exact scratch was `.maturin/mode5-m511/attempt-01`, ignored/untracked,
non-symlink and path-verified. It contained disposable pytest/JIT/plot caches and
an extraction of the exact already certified M5-10 native wheel. Host-level
`/proc` cwd/cmdline/FD/maps review inspected **159 processes**, with zero scratch
references, inspection errors or transient races. No service was killed.

## Retention And Deletion

Only that registered inactive scratch was removed. Apparent file payload was
9,018,108 bytes; observed filesystem free-space increase was **16,257,024 bytes
(15.50 MiB)**. This is observed filesystem change, not a claim that apparent
payload and recovered blocks must be equal on an active filesystem.
Free space changed from 26,079,395,840 to 26,095,652,864 bytes.

Checks after cleanup:

- **3,620 protected records verified**: 3,619 original hashes unchanged and one
  exact authorized `wfo_study.py` selection-clock amendment, with retained old/
  new source revision receipts. No other previous source/evidence was modified.
- **115 retained files**, 16,288,383 bytes before cleanup inventory, unchanged.
- **329 current canonical/research/test/harness hashes**, unchanged.
- Original guide, unrelated user spec, five private alpha sources, market data,
  M5-08.1/M5-09/M5-10 evidence, actual paths/campaigns, new/old journals, failed
  attempts, successful receipts and exact core/native wheel/sdist preserved.
- Main project environment, current regression tooling and offline dependencies
  retained. No consumer environment was deleted in this cleanup.

The disposable native extraction must be restored from the retained exact wheel
before rerunning native source regression; an old same-version extension is not
a capability-qualified replacement. Current core wheel/sdist qualification
belongs to M5-12, not these source-local tests. Native extraction was not a clean
PyPI dependency-resolution or remote platform proof.

Private immutable cleanup inventory, host review and final receipt are retained
in `upgrade/private/mode5_upgrade_v1/m5-11/attempt-01`. Failed artifacts/logs keep
their original status. No broad cache prune, evidence/data deletion, source
reset, branch change, push, release or publication occurred.
