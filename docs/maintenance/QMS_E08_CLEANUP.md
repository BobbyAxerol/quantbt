# QMS-E08 Cleanup Receipt

## Scope And Budget

Owner approved local E08 work and required cleanup. The registered lane is
`.maturin/qms08/e08-qualification-v1`, with at most 3 GiB incremental scratch
and 5 GiB safety headroom. Builds/tests/consumers ran sequentially. The sealed
native wheel was reused because native source and default build identity did
not change; no Rust rebuild, global-cache purge or service shutdown was needed.

Read the [cleanup runbook](../BUILD_TEST_CLEANUP.md) and
[E08 report](../meta_selection/QMSE08_REPORT.md). Cleanup is operational, not
an economic, remote or public-release certificate.

## Exact Removed Scratch

Only these ignored inactive directories were deleted after all workers returned
and a host-visible process check found no references:

- `.maturin/qms08/e08-qualification-v1/package-v1/cp312/build-env`
- `.maturin/qms08/e08-qualification-v1/package-v1/cp312/pair`
- `.maturin/qms08/e08-qualification-v1/package-v1/cp312/sdist`
- `.maturin/qms08/e08-qualification-v1/package-v1/cp312/stage/build`

The cleanup rejects unreviewed names, symlink roots, missing virtualenv markers
and active consumers. The negative tests pass. It does not remove the staged
canonical source, dist artifacts, Git, private data or historical evidence lanes.

## Measured Result

| Field | Actual |
|---|---:|
| Filesystem available bytes before | 24,646,836,224 |
| Filesystem available bytes after | 25,858,859,008 |
| Actual free-byte improvement | **1,212,022,784** |
| Actual improvement in MiB | **1,155.875** |
| Free inodes after | 5,593,038 |
| Protected file hashes unchanged | **410** |

These are filesystem observations, not a sum of hard-linked `du` sizes. Exact
wheel/sdist/native files, successful and failed logs/XML, all new histories,
staged source and receipt payloads remain hash-verifiable. Existing
`.maturin/qms08/g01-package-v1/consumer`, primary environments and offline
dependency cache remain available. Deleted consumers require fresh isolated
installation from the retained artifacts before any rerun.

The ignored raw receipt is
`.maturin/qms08/e08-qualification-v1/cleanup.json`; its SHA256 and exact local
qualification references are sealed in the
[tracked E08 closure](../../benchmarks/optimization/meta_selection/qms_e08_closure.json).
Source/artifact verification before and after deletion matched exactly.
No push, CI dispatch, merge, tag, publication or gate waiver occurred.
