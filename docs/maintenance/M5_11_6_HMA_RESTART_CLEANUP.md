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

## Additional Owner-Approved Review

The owner then requested removal of unused generated resources and images.
The Docker inventory contains **zero build cache**, four listed images all
referenced by live containers, no stopped containers, and six overlay mounts
matching the six running containers. No orphan overlay was found. Active
collector/dashboard images and mounts were preserved. Two unattached named
volumes contain database/dashboard data, not established disposable scratch;
they were not reclassified as garbage merely because their link count is zero.

After per-directory host-reference and current-source checks, **nine obsolete
installed consumers** under `.maturin/qms08/qualified/cp311|cp312|cp313` were
removed: `sdist`, `core_off` and `core_optimization` only. All required exact
dependency versions remain in each retained historical `pair` environment.
Exact core/native wheels, sdists, source staging, build environments, logs,
receipts and current tooling remain. Repeating these old installed-consumer
proofs requires fresh artifact installation; the removed environments are not
described as still installed.

The initial broader 12-environment deletion was blocked by the safety review
before execution. Per-directory read-only checks established inactivity and
artifact custody; the narrower nine-consumer deletion was subsequently
approved. No bypass or broad Docker/system prune occurred.

| Additional cleanup | Apparent bytes | Observed free-space increase |
|---|---:|---:|
| Two completed pytest fixture roots, 256 files | 9,032,913 | 9,883,648 |
| Nine obsolete consumers, 87,896 files | 4,246,695,969 | 382,410,752 |

Consumer cleanup verified **2,526 protected files** and preserved HMA's active
registration and source pins. Hard-linked dependencies explain why the 4.25-GB
apparent inventory released only about 365 MiB. Available disk afterwards was
**6,907,527,168 bytes**, approximately **6.43 GiB**. The three cleanup actions
observed 967,069,696 bytes of cumulative increase; this is not a claim that all
other host activity stopped or that unused filesystem RAM was forcibly freed.

Private additional receipts are `hma-recovery-cleanup-v1/test-before.json.gz`,
`test-result.json`, and `hma-recovery-consumer-cleanup-v1/before.json.gz` /
`result.json`, adjacent to the original cleanup lane. No service was stopped.

The peer-handoff qualification subsequently closed one additional pytest fixture
root: 292 files / 14,020,918 apparent bytes, with **15,003,648 bytes** observed
recovery. Source, both actual-entry qualification receipts and original/current
registration identities were reverified. Receipt:
`hma-recovery-cleanup-v1/peer-test-result.json`. Cumulative observed increase
across these reviewed actions is **982,073,344 bytes**, approximately 937 MiB;
all scientific evidence remains retained.
