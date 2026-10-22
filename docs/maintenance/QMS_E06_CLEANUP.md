# QMS-E06 Test Consumer Cleanup

2026-10-07 UTC, after all local source, installed and benchmark gates returned.
Follow [the preregistration](../meta_selection/QMSE06_QUALIFICATION.md) and
[cleanup runbook](../BUILD_TEST_CLEANUP.md). This is operational evidence,
not a scientific, remote or release certificate.

## Deleted

Only these two new ignored, reproducible, inactive virtualenv roots:

- `.maturin/qms08/e06-qualification-v1/wheel-consumer`
- `.maturin/qms08/e06-qualification-v1/sdist-consumer`

Validated exact resolved names, no symlink, Git ignore status and `pyvenv.cfg`.
Both consumer jobs had completed. A host-visible process check found no process
using either root; the cleanup tool also rejected active visible references.
No unrelated process or service was stopped.

## Retained And Verified

93 artifact/evidence hashes unchanged before/after deletion, plus all 322
runtime/build source files and the scientific guide seal. Retained exact core
wheel/sdist/native wheel, passing/failing history, new XML/JSON/logs, frozen
history, source staging, Git, `.venv`, G01 tooling and UV offline dependencies.
No external alpha/data, historical receipt or evidence lane was removed.

Observed free-space improvement: **1,190,313,984 bytes / 1,135.171875 MiB**.
This is a filesystem observation, not apparent `du` size or a guarantee that
every byte changed on the host belongs to this phase.

Private detailed receipt:
`.maturin/qms08/e06-qualification-v1/cleanup.json`.
SHA-256: `f55ab3008c8ffa73476ff4f99ba5a063201636370c665068311310ef4d11945b`.
The [public aggregate gate](../../benchmarks/optimization/meta_selection/qms_e06_closure.json)
binds its checksum and exact artifact/source proof. Removed consumers require
fresh installation before any rerun; retained receipts describe their historical
execution and are not rewritten to pretend the environments still exist.
