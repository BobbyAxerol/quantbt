# M5-05 Cleanup Receipt

## Registered Scope

One exact phase-owned ignored scratch path was removed twice after successive
registered test/final-review invocations:

```text
.maturin/mode5-m505/attempt-01
```

Incremental budget: 256 MiB with at least 5 GiB reserve; one worker and one
numeric thread. Reused the existing qualified tooling. No build/install,
service shutdown, broad cache deletion or environment removal occurred.

Host `ps -eo pid,args` was checked before each removal. The lane was inactive;
safe recursive removal unlinked synthetic pytest symlinks without following
them into source/data. Raw inputs and retained evidence were not eligible.

## Verified Results

| Removal | Scratch File Payload | Observed Filesystem Recovery |
|---|---:|---:|
| Initial registered tests | 4,528,426 bytes | 5,517,312 bytes (5.26 MiB) |
| Current-source final review | 4,707,262 bytes | 6,479,872 bytes (6.18 MiB) |

Combined immediate recovery: **11,997,184 bytes (11.44 MiB)**. This is not a
claim about total system/phase disk movement; other host activity can change
overall free space. Final immediate free space was **25,290,981,376 bytes**, well
above the safety reserve.

**802 protected input/source/history hashes**, **79 separately protected prior
receipt hashes**, and **10 current environment/test source hashes** remain
unchanged. The second cleanup verified the combined 881 protected hashes and
14 retained current-review/harness files. Initial cleanup separately verified
82 retained evidence/harness files. Later outputs remain retained, not deleted.

Original alphas, market CSV, guide, old specification, all previous phase
evidence, failed/passing attempts, exact artifacts and current environments are
preserved. No private paths were staged for Git or package inclusion.

## Handoff

The current receipt is in the ignored M5-05 `final-review-02` lane. Its
source-bound references are sealed in [M5-05 evidence](../mode5/evidence/m5-05.json).
The [report](../mode5/M5_05_ENVIRONMENT_REPORT.md) distinguishes technical
qualification from economic evidence. Disposable scratch is absent; retained
receipts do not depend on keeping pytest/Numba caches installed.
