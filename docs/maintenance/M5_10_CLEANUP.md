# M5-10 Cleanup Receipt

2026-10-10; [public integration report](../mode5/M5_10_PUBLIC_RUNTIME_REPORT.md),
[summary](../mode5/evidence/m5-10.json),
[rules](../BUILD_TEST_CLEANUP.md).

## Budget And Review

Registration preceded execution: 256 MiB retained evidence, 2 GiB incremental
scratch, at least 5 GiB free reserve. Initial free bytes: 26,222,923,776.
Final retained payload is 45,239,184 bytes (43.14 MiB); removable scratch
payload is 367,659,286 bytes (350.63 MiB). The owned lane remained within its
budget. Source, failed/successful receipts, private data and prior evidence
were registered as protected, never disposable.

A host-level process audit inspected 162 processes, command paths, cwd, open
FDs and library maps. Zero scratch references, inspection errors or transient
races were recorded. No services or unrelated processes were stopped. Resolved
path, non-symlink root, Git ignore and absence of tracked files were checked.

## Exact Removal

Only `.maturin/mode5-m510/attempt-01` was removed. It contained disposable
pytest/Numba/plot scratch, build staging and the inactive fresh core/native
installed consumers. Current controlled build/test tooling and older replay
consumers remain. No recursive whole-cache, Git, data, Docker or evidence
deletion occurred.

| Measure | Actual value |
|---|---:|
| Free bytes immediately before | 25,729,265,664 |
| Free bytes immediately after | 26,134,515,712 |
| Observed free-space improvement | 405,250,048 bytes / 386.48 MiB |
| Protected hashes reverified | 2,757 |
| Retained file hashes reverified | 491 |
| Current source/harness hashes reverified | 317 |

Observed filesystem change is not inferred from apparent directory sizes;
block allocation and concurrent filesystem activity can differ from payload
bytes. Raw preflight, host review and cleanup JSON remain in the ignored
`upgrade/private/mode5_upgrade_v1/m5-10/attempt-01` lane.

## Retained And Reproducible

Exact core wheel, sdist, sdist-rebuilt wheel and current/old native artifacts,
all build/install/test logs, successful and failed receipts, account controls,
benchmark panels, source staging copies and protected input hashes remain.
Private alpha sources and prior M5/QMS/MET evidence are unchanged.

The deleted consumer environments are historical PASS receipts, not still-live
installations. A rerun needs a fresh isolated installation from retained exact
artifacts, with new module-origin/capability checks and an append-only receipt.
Offline dependencies and one current controlled tooling environment are kept.
No remote workflow, publication or live financial deployment was performed.
