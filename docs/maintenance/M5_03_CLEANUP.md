# M5-03 Cleanup Receipt

Local cleanup under the [runbook](../BUILD_TEST_CLEANUP.md) and
[phase plan](../../upgrade/implement.md#mode5-m5-03), after numeric tests,
complete regression, calibration, benchmark and private report finished.
Read-only host process review found no active M5-03 worker; unrelated services,
Jupyter kernels and both reused environments were retained.

Only this registered, ignored, inactive scratch root was deleted:

```text
.maturin/mode5-m503/jit/attempt-01
```

It held owned pytest temporaries, Numba cache and Matplotlib configuration.
Root/ancestor symlinks are rejected; synthetic child symlinks are unlinked
without following them. No whole-cache, environment, `.maturin`, evidence,
source, data, Git or Docker deletion occurred.

| Measurement | Actual |
|---|---:|
| Incremental retained/scratch budget | 128 MiB |
| Minimum reserve | 5 GiB |
| Deleted apparent scratch | 4,134,535 bytes / 3.943 MiB |
| Immediate filesystem free-space increase | 5,844,992 bytes / 5.574 MiB |
| Free bytes immediately after | 25,329,324,032 / 23.590 GiB |
| Retained phase payload at cleanup | 1,498,352 bytes / 1.429 MiB |
| Protected hashes unchanged | 765 |
| Retained evidence/harness hashes unchanged | 52 |
| Environments deleted / installs / builds | 0 / 0 / 0 |

Immediate filesystem change includes allocation granularity and concurrent
host writes; it is not equated to apparent bytes. The longer registration-to-
cleanup free-space delta is not a measurement of deletion's reclaimed bytes.
Final sealing adds small retained JSON/source manifests after this measurement;
the incremental budget is rechecked, not silently attributed to reclaimed disk.

Successful and failed logs/XML, exact guide oracle, registrations, calibration,
all private numeric panels, report, final harness copy and prior evidence stay
retained in ignored local lanes. No consumer environment needs reinstall.
No source/native artifact changed. The [seal](../mode5/evidence/m5-03.json)
binds cleanup and final source-bound receipts; the
[report](../mode5/M5_03_STATISTICS_REPORT.md) distinguishes technical from
economic and artifact qualification. Fresh append-only attempts are required
for reruns; do not overwrite a historical receipt.
