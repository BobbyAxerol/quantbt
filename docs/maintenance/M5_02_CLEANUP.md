# M5-02 Cleanup Receipt

## Scope And Ownership

Local admission cleanup under the [runbook](../BUILD_TEST_CLEANUP.md) and
[M5-02 plan](../../upgrade/implement.md#mode5-m5-02), after the final five-alpha
pilot, replay qualification, focused tests and private report completed.
Read-only host process inspection found no active M5-02 worker. Unrelated
services and environments were neither stopped nor deleted.

Only these four registered, ignored, inactive JIT scratch roots were deleted:

```text
.maturin/mode5-m502/jit/attempt-01
.maturin/mode5-m502/jit/attempt-02
.maturin/mode5-m502/jit/attempt-03
.maturin/mode5-m502/jit/attempt-04
```

Resolved paths and ignore rules were checked before deletion. Symlinked roots
are rejected; synthetic child symlinks are unlinked without following them.
No recursive cleanup of `.maturin`, private evidence, Git or shared caches.

## Measurements And Preservation

| Measure | Actual observation |
|---|---:|
| Registered incremental budget | 256 MiB |
| Minimum free-space reserve | 5 GiB |
| Deleted scratch apparent bytes | 8,811,732 / 8.404 MiB |
| Immediate filesystem free-space increase | 9,302,016 / 8.871 MiB |
| Free bytes after cleanup | 26,357,186,560 / 24.547 GiB |
| Retained phase payload | 17,458,958 / 16.650 MiB |
| Protected source/input hashes unchanged | 435 |
| Retained evidence/copy hashes unchanged | 232 |
| Environments deleted / artifact builds | 0 / 0 |

The immediate filesystem delta includes concurrent host writes and allocation
granularity; it is not equated to the apparent scratch size. Individual cleanup
receipts also contain their original registration-to-cleanup free-space delta;
that longer interval is not a measurement of bytes reclaimed by deletion.

All successful and failed lanes, logs, registrations, exact alpha copies,
effective schemas/readiness, actual commands/fills/account paths, pilot outcomes
and the final private harness snapshot remain retained. Original alphas and
RSI, market data, detailed guide, prior receipts and QuantBT financial sources
are unchanged. The current tooling environment, primary environment, installed
extensions and offline dependencies remain available. No consumer needs
reinstallation because no environment was removed.

Four append-only `cleanup_receipt.json` files and the aggregate
`cleanup_summary.json` remain in ignored private evidence. The
[sanitized seal](../mode5/evidence/m5-02.json) binds their hashes without exposing
private strategy or economic values. Subsequent financial reruns require a
fresh registered attempt; old receipts and inputs must not be overwritten.
