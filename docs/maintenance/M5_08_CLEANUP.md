# M5-08 Cleanup Receipt

## Scope And Review

This is an operational exit receipt, not an economic, installed-wheel or release
certificate. Read the [runbook](../BUILD_TEST_CLEANUP.md),
[phase report](../mode5/M5_08_BATTERY_REPORT.md) and
[public seal](../mode5/evidence/m5-08.json).

The registered incremental disk cap was 512 MiB, with 5 GiB safety reserve and
2 GiB per-process RSS cap. The existing controlled tooling environment was
reused; there was no dependency installation, wheel or Rust build.

After all workers completed, an escalated read-only host review inspected
155 processes: no active M5-08 command, owned-path file descriptor or permission
error remained. The fresh review was required before deletion. Git ignore,
exact ownership and root/ancestor symlink guards passed.

## Exact Removal And Preservation

Only `.maturin/mode5-m508/attempt-01` was removed: reproducible pytest, Numba
and plotting scratch. Its file payload was 5,378,959 bytes; 102 synthetic test
symlinks were unlinked without following their targets. This is not a deletion
of source, research evidence, test environments, dependency caches or artifacts.

All **1,445 protected hashes** and **1,339 retained file hashes** matched after
cleanup. Retained evidence/helper payload at that checkpoint was 30,838,332
bytes, under the registered disk cap. Private alpha/data source, original
historical receipts, negative outcomes, failed attempts, exact paths, native
binary and the current tooling environment remain available.

## Observed Resources

| Measurement | Bytes |
| --- | ---: |
| Filesystem free immediately before | 26,160,852,992 |
| Filesystem free immediately after | 26,168,827,904 |
| Observed immediate increase | 7,974,912 |

The **7.61 MiB observed increase** is distinct from apparent directory payload;
filesystem block accounting and concurrent host activity can differ. No broad
cache prune or unrelated service shutdown ran. Free bytes/inodes were checked
before execution; the reserve remained available throughout.

Maximum fresh financial-worker peak RSS was 335.24 MiB; sampler-process peak
was 289.69 MiB and analysis-process peak was 279.68 MiB. These are individual
process measurements, not simultaneous whole-machine RSS.

The private append-only lane retains registration, command/XML logs, host review,
cleanup JSON, all matrices and the Appendix D seal. New research after closure
must use a new registered scratch lane; this deleted scratch is not a consumer
environment that may be silently reused as installed proof.
