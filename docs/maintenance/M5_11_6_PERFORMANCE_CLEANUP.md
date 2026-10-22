# M5-11.6 Performance Test Cleanup

## Scope

This receipt closes disposable test/control scratch only. It does not certify
the long four-alpha WFO, economic improvement, native transactional-session
implementation, packaging or a release. See the
[bounded performance report](../mode5/M5_11_6_PERFORMANCE_CLOSURE.md).

## Reviewed And Removed

- `.maturin/mode5-m5116/attempt-01/performance-tests`
- `/tmp/m5116-callback-cursor-tests`

All financial controls and test processes had exited. A read-only host preflight
confirmed `systemd` PID 1 and the full host PID namespace, not sandbox-only
visibility. The deletion pass reviewed **71 host processes for each root**,
including cwd, executable, open file descriptors and memory mappings. No live
reference, symlink, unexpected artifact or source file was eligible.

Only **41 reproducible Numba `.nbc`/`.nbi` files** and the registered ordinary
empty test directories were removed. The project scratch passed Git-ignore
validation; the temporary root was separately registered. No cache wildcard,
environment removal, service stop or evidence cleanup was used.

| Measurement | Bytes |
|---|---:|
| Apparent deleted files | 1,386,247 |
| Allocated deleted files | 1,458,176 |
| Available before deletion | 6,419,972,096 |
| Available after deletion | 6,421,475,328 |
| Observed available-space increase | 1,503,232 |

Observed filesystem recovery is about **1.43 MiB**, not a sum of apparent
directory sizes. Free disk remains above the 5-GiB reserve.

## Preserved

Before/after hashes agree for **1,819 protected files**, including original and
failed research receipts, current source/private helpers, market inputs and
retained controls. The cleanup does not rewrite old source certificates; exact
pre-patch copies remain alongside the new source-bound lane.

The performance lane retains **9,674,794 bytes** including source snapshots,
16 account controls, failure receipts, cold reconciliation and cleanup custody,
below its 128-MiB allowance. None of those 9.23 MiB is disposable test scratch.
The current environment and qualified native binary are unchanged. Native SHA:

```text
2959f5388c6a8e57bdef5a6dafe76da3624ef57dba379f7ca686e9bf202ad26b
```

Private custody is under
`upgrade/private/mode5_upgrade_v1/m5-11-6/attempt-01/performance-closure01/cleanup`:
`inventory.json` and `result.json`. The matched-control `closeout.json` verifies
376 current/reference input pins and reconciles every retained financial buffer.
Replaying a removed JIT cache regenerates it within a newly registered budget;
there is no need to rebuild Rust or recreate the retained environment.
