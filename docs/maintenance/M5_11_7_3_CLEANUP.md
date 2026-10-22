# M5-11.7.3 Reporting Cleanup

**Status:** PASS_EXACT_INACTIVE_FIXTURE_CLEANUP, 2026-10-19 UTC.
This closes the operational gate only; see [source qualification](../diagnostics/M5_11_7_3_IMPLEMENTATION_REPORT.md)
and [the cleanup rules](../BUILD_TEST_CLEANUP.md).

Admission recorded 5,674,426,368 free bytes and 5,473,669 free inodes.
Ceilings were retained 128 MiB, scratch 64 MiB, parent 256 MiB and report
worker 512 MiB, with one numeric thread and a 5 GiB reserve. No environment,
native build, market download or financial study was admitted.

After every test/report/cost worker exited, host process cwd/FD inspection found
no active or unreadable users of the exact ignored fixture root:
`upgrade/private/mode5_upgrade_v1/m5-11-7-3/attempt-01/scratch`.
The root was not a symlink; 58 pytest convenience links resolved internally,
with no external targets. No process or service was stopped.

Only that directory was deleted: 1,212,572 logical file bytes and 3,612,672
allocated bytes. Free space changed from 5,667,794,944 to 5,671,632,896 bytes;
free inodes from 5,472,864 to 5,473,595. **Observed immediate recovery was
3,837,952 bytes / 3.66 MiB**. This differs from allocated scratch bytes on a
shared host; it is not a guaranteed savings forecast or global-cache total.

Before/after checks preserve 259 protected inputs, four prior receipts,
44 current source/tool files and 34 retained outputs. Retained phase bytes at
removal were 2,635,335, with 61,077,876 parent bytes including then-live scratch;
final small closure receipts stay within their registered ceilings. The
5 GiB disk reserve remained intact.

Source, alpha/market data, positive/negative/failed evidence, snapshots,
artifacts, current environment and useful offline dependencies remain. No
Docker/cache/mount pruning or unrelated service action occurred. The private
`cleanup.json` and terminal qualification retain exact before/after pins;
M5-12, remote and publication were not activated.
