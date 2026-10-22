# PRE-E06-06 Artifact, Evidence And Cleanup Receipt

## Scope

2026-10-07, Asia/Saigon. Follow the [cleanup runbook](../BUILD_TEST_CLEANUP.md),
[registered phase](../../upgrade/implement.md#qms-pre-e06-06) and
[completed report](../meta_selection/PRE_E06_06_REPORT.md).
Registered incremental ceiling: 2 GiB plus 5 GiB safety headroom; one numeric
worker/thread, one small build environment and two independent core consumers.
No native rebuild, system/container prune, service stop or unrelated cleanup.

## Exact Deleted Scratch

Only these ignored, reviewed, inactive roots were removed:

```text
.maturin/qms08/pre-e06-06/package-v1/build-env
.maturin/qms08/pre-e06-06/package-v1/wheel-consumer
.maturin/qms08/pre-e06-06/package-v1/sdist-consumer
.maturin/qms08/pre-e06-06/package-v1/stage/build
```

Controlled build/consumer/regression children returned before deletion.
The path validator rejects unregistered, symlinked and non-ignored roots.
The local process check found no reference to those disposable roots; process
visibility can be namespace-limited, so scope and controlled child lifetimes
are also required. No unrelated host process was killed.

## Retained And Verified

401 phase file hashes match before/after cleanup. Exact core wheel/sdist,
source stage except its disposable build tree, all passing/failing logs, XML,
JSON, synthetic history and original installed proofs remain. Native 0.4.3
wheel/extension and all predecessor scientific/source receipts verify separately.
All 322 runtime/build files, including 58 Rust files, match entry source.

The current G01 numeric/test environment, project `.venv` and required offline
cache remain. Missing Hypothesis 6.164.0 and sortedcontainers 2.4.0 were reused
from exact RECORD-verified existing test dependencies; 126 destination file
hashes verify, and numeric/native dependencies are unchanged. Failed resolver
and collection attempts remain evidence, not disposable scratch.

Final qualification/doc reruns retain only small new evidence. The rejected
detailed draft exit receipt remains in the ignored lane, including synthetic
negative-test inputs; public output uses counts/digests, not raw payloads.
Its failed privacy check and separately passing rerun are preserved too.
Rechecking a retained cleanup receipt requires unchanged protected hashes,
unchanged runtime source and all four deleted roots still absent; it never
overwrites the original receipt or deletes recreated environments.

## Measured Filesystem Outcome

| Measurement | Bytes |
|---|---:|
| Entry free space | 26,508,767,232 |
| Immediately before cleanup | 25,204,760,576 |
| Immediately after cleanup | 26,415,972,352 |
| Observed free-space change | +1,211,211,776 |

Observed improvement: **1,155.10 MiB**, not a sum of apparent directory sizes.
Free inodes after cleanup: **5,597,326**. This is a shared-host filesystem
observation, not an attribution of every disk write to the phase or an RSS metric.

The exact ignored receipt is `.maturin/qms08/pre-e06-06/cleanup.json`;
the [public source-bound gate](../../benchmarks/optimization/meta_selection/qms_pre_e06_06_closure.json)
records its SHA-256 alongside current artifact/regression hashes.
Cleaned wheel/sdist environments **require fresh installation before rerun**;
stored receipts retain their historical origins, not an assertion that removed
environments remain executable. Use a fresh registered lane, never overwrite
sealed logs or silently reuse unrelated installed modules.

## Boundary

Cleanup is operational evidence only. PRE06 is READY_FOR_E06_LOCAL;
economic/default promotion, current-source remote matrix, release/public-index
qualification and E06/E07 start remain individually owner-controlled.
