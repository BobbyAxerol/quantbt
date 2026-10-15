# M5-11.6 HMA Restart Cleanup

The owner requested cleanup before restarting HMA. This is an operational
receipt, not a financial, recovery or economic certificate. The
[handoff plan](../mode5/M5_11_6_HMA_PREFIX_HANDOFF.md) retains the original study
scope and excludes automatic restart of SC/HASH/VWAP.

## Exact Removal

Only 589 inactive, single-link `.rlib`, `.rmeta` and `.d` files under the ignored
`rust/target/debug/deps` directory were removed. These are reproducible Rust
debug dependency archives/metadata, not the release extension used by HMA.
Future debug builds must regenerate them from retained sources/dependencies.

Host cwd, executable, FD and memory-map review covered **72 processes** before
deletion. **7,434 protected files** were hash-verified afterwards, including
the original 708 queue source pins, original/candidate native artifacts,
completed/failed financial evidence and retained package artifacts. No service
was stopped. No environment, alpha/market input, wheel/sdist, exact extension,
test executable, Git object or offline dependency registry was removed.

| Measurement | Bytes |
|---|---:|
| Apparent removed file size | 573,496,370 |
| Free before deletion | 5,977,952,256 |
| Free after deletion | 6,552,727,552 |
| Observed filesystem increase | 574,775,296 |
| Available RAM after review | 3,835,293,696 |

Available disk after cleanup is approximately **6.10 GiB**. Filesystem deltas
include allocation granularity and concurrent host activity; apparent bytes
are not substituted for actual free-space change. RAM availability is an
observation, not a claim that deleting disk cache released that much RAM.

## Custody

The private append-only inventory and receipt are at
`upgrade/private/mode5_upgrade_v1/m5-11-6/attempt-01/hma-recovery-cleanup-v1`:
`before.json.gz` and `result.json`. Receipt time is 2026-10-15 22:03:50
Asia/Saigon. The original queue remains stopped; this cleanup alone does not
authorize bypassing the prefix-handoff qualification gate.
