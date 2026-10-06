# QMS E03-G01 Build And Test Cleanup Receipt

## Scope And Inventory

Owner-authorized cleanup follows the [runbook](../BUILD_TEST_CLEANUP.md) and
[approved repair resource plan](../../upgrade/implement.md#qms-gap-closure-2026-10-06).
Initial available space was approximately 27 GiB; incremental budget was at
most 4 GiB plus at least 5 GiB safety headroom. Reused tooling/offline dependencies
and one fresh installed consumer rather than allocating a consumer per trial.

Reviewed deletion: **only `rust/target/debug/incremental`**, an ignored,
resolved non-symlink directory containing reproducible incremental build cache
(apparent size approximately 224 MiB). Full study, package proof and test
sessions had completed; host process inspection showed no active Cargo/rustc
before deletion. No service was stopped and no unrelated project was touched.

## Executed Cleanup

| Filesystem measurement | Before | After |
|---|---:|---:|
| Used bytes | 73,239,846,912 | 73,009,520,640 |
| Available bytes | 26,956,181,504 | 27,186,507,776 |

Actual measured improvement: **230,326,272 bytes / 219.656 MiB**.
After cleanup approximately **25.319 GiB** remained available. Inode use was
940,823 / 6,553,600 (15%). Host activity can affect filesystem measurements;
these are observed free bytes, not a sum of hard-linked directory sizes.

Protected sorted file/hash inventory, excluding consumer dependencies, covered:

- `.maturin/qms08/g01-package-v1`: exact core wheel/sdist, logs and receipts.
- `.maturin/qms08/g01-package-v1-native`: exact rebuilt native wheel.
- `.maturin/qms08/g01-qms06-v1`: separately built QMS06 fixture.
- `data/local/qms-real-review/e03-g01-replay-v1`: registered private replay.

Aggregate SHA-256 before **and** after:
`cffa888980bc1053704febac3e210bff62f5dff7d51302b2ec6e6a03aafe79c2`.
Working-tree diff SHA before/after was the empty payload
`e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`;
the branch was clean at both checks. Scientific evidence/source was not removed.

## Retained And Reinstallation

Retained the current `.maturin/qms08/g01-package-v1/consumer`, primary tooling,
old E03 compatibility/E05 v3 environments needed for historical replay, offline
dependencies, all failed/passing XML and logs, exact artifacts and private inputs.
No consumer requires reinstallation because none was deleted in this cleanup.
Subsequent builds may regenerate only the removed incremental cache.

The actually loaded current native extension remains bound by its installed
proof and SHA-256 in the [correctness closure](../meta_selection/QMSE03_G01_CLOSURE.md).
No whole-target/cache cleanup, Docker prune, Git housekeeping or evidence
deletion occurred. Cleanup is not an economic, remote or publication gate.
