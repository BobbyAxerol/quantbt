# M5-11.6 HMA Performance Cleanup

## Scope

The owner approved isolated HMA performance work, not changes to other alpha
sources or automatic long-study recovery. See the
[performance report](../mode5/M5_11_6_HMA_PERFORMANCE_REPORT.md) and
[queue guard-stop disclosure](../mode5/M5_11_6_LONG_ROLLING_QUEUE.md#current-guard-stop).
This receipt is an operational cleanup record, not full-WFO/economic certification.

## Registration And Preservation

The lane registered 64 MiB retained output, 32 MiB JIT scratch and 384 MiB
isolated build scratch, with the 5-GiB reserve beyond the original queue's
remaining forecast. The build reservation was explicitly closed before finance;
no additional build is admitted in the finance lane. Shared-host disk headroom
still became insufficient during the build and the long supervisor stopped its
workers. Source isolation must not be described as resource isolation.

All 48 successful financial controls, two attribution profiles, original/failed
receipts, all ablations and eight final candidate controls remain. Exact native
artifacts, the complete private helper/source archive, original market/alpha
inputs and the current tooling environment remain. No installer, broad cache
deletion, Git cleanup, other-alpha source edit or queue restart occurred.

## Exact Removals

| Action | Reviewed removal | Observed available-space increase |
|---|---|---:|
| Duplicate seed cleanup | Unused copied release-cache entries at the isolated target root; matched protected original hashes | 218,271,744 bytes |
| Build close | Completed isolated `hma-perf-v1/build-target`; extension/tests/source proof retained first | 189,710,336 bytes |
| Final cleanup | Nine inactive `.nbc`/`.nbi` files under the registered HMA `jit` directory | 200,704 bytes |

The final nine files have apparent size **187,054 bytes**. Final cleanup reviewed
**72 host processes**, verified **367 retained source/evidence pins**, and
rechecked all **708 original queue source pins**. No active FD/map/cwd/executable
reference pointed to the deleted cache. Symlink/unknown-entry guards remained
enabled. The original `rust/target`, original/candidate native binaries and all
other environments were preserved.

Free bytes at final cleanup were **6,013,571,072 -> 6,013,771,776**, approximately
5.60 GiB available afterwards. These per-action deltas are not the entire phase's
net saving: retained outputs and concurrent filesystem activity also change
available space. The final native artifact is outside deleted scratch and remains
hash-verifiable; this is not an installed-wheel consumer receipt.

## Receipts

Private append-only records are under
`upgrade/private/mode5_upgrade_v1/m5-11-6/attempt-01/hma-perf-v1`:

- `seed-cleanup-before.json`, `seed-cleanup-after.json`.
- `native-test-result.json`, `build-cleanup-before.json`, `build-closed.json`.
- `cleanup-final-before.json.gz`, `cleanup-final.json`.
- `helper-source-snapshot.tar.gz`, `summary.json`, `queue-stop-custody.json`.

The interrupted long queue remains `FAIL_OR_GUARD_STOP_RETAINED`. Its completed
folds are preserved, not relabeled PASS or automatically resumed. Prefix-handoff
qualification and full continuous-account closeout remain future work requiring
the owner's next instruction.
