# M5-11.6 Rolling Preflight Cleanup

## Disposition

2026-10-15, Asia/Saigon. **PASS exact inactive JIT-cache cleanup only.**
This follows the [bounded rolling proof](../mode5/M5_11_6_ROLLING_PREFLIGHT.md)
and [registered phase](../../upgrade/implement.md#mode5-m5-11-6), under the
[cleanup rules](../BUILD_TEST_CLEANUP.md). It is not long economic, remote,
wheel, release or public-package certification.

## Before Deletion

- Registered retained ceiling 128 MiB; scratch ceiling 64 MiB; required disk
  reserve 5 GiB. No environment, install or native build was created.
- Four rolling workers completed and were reaped. All 16 cells/256 attempts
  pass cold reconciliation, with 252 COMPLETE/four PRUNED.
- Eight subsequent fixed IS controls completed sequentially, without any new
  optimizer trial. Their persisted original/transaction paths were reconciled
  again cold before cleanup. A nonblocking worker lock excludes overlap.
- Financial foreground time charged: 65.08 s failed queue + 1,077.70 s passing
  queue + 120.56 s fixed controls = 1,263.34 s, within thirty minutes.
- Host PID namespace/systemd visibility verified; **72 host processes** reviewed
  through cwd, executable, open FDs and mappings. No live scratch reference.
- Exact frozen plan/rules copies retained before subsequent documentation
  amendments, so historical source identities are not lost when plan is updated.
- **629 protected hashes** recorded and verified unchanged after deletion,
  including registered source, all financial/failure evidence, source copies,
  original and candidate native extensions, and receipts.

## Exact Inventory

Only this reviewed ignored ordinary root was removed:

```text
.maturin/mode5-m5116/rolling-preflight-v1
```

Its 41 files were recognized Numba `.nbi`/`.nbc` artifacts for the named
indicator/reference-event functions. Directory, filename, symlink, ignore,
inactivity and per-file hash guards preceded exact unlink/rmdir. Unknown entries
would fail closed; no broad cache deletion or Docker/system prune was used.

| Measure | Bytes |
|---|---:|
| Apparent cache contents | 1,386,263 |
| Allocated blocks | 1,458,176 |
| Available space before | 6,294,929,408 |
| Available space after | 6,296,215,552 |
| Observed available-space increase | 1,286,144 |

Observed recovery is about **1.23 MiB**, separate from apparent/allocated size
and affected by receipt writes/concurrent host activity. Free space remains
about 5.86 GiB, above the reserve. After-run inode review reports 5,514,369 free;
inode availability is not used as a substitute for free bytes.

## Preserved

Every source, original private alpha, retained market, failed/passing financial
receipt, compact account output, native binary and active/current environment
remains. No service or user notebook was stopped. The owner-private v2 retained
tree is 11,628,688 bytes, about 11.1 MiB including terminal source custody.

Future executions must regenerate the removed JIT artifacts. Historical proofs
remain historical; removal does not authorize another search or long queue.
Machine-readable inventory/result and cold IS comparison are retained below
`upgrade/private/mode5_upgrade_v1/m5-11-6/attempt-01/rolling-preflight-v2/cleanup/`.
