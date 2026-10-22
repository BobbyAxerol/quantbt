# M5-09 Cleanup Receipt

## Registered Scope

The [phase registration](../../upgrade/implement.md#mode5-m5-09) authorized only
research dossier assembly and existing-environment tests. Incremental budget
128 MiB; required disk reserve 5 GiB. Initial free space 24.11 GiB; sufficient
inodes were checked separately. No downloads, installs, builds or environments
were created. Exact disposable directory:

`.maturin/mode5-m509/attempt-01`

## Host Review And Deletion

Read-only host `/proc` audit inspected 164 processes: zero owned command/FD
matches, zero permission errors and zero transient races. Git-ignore and
symlink safeguards passed. Only the registered inactive pytest/JIT/plot scratch
was removed. No source, Git, market, alpha, evidence, logs, artifact, private
sandbox or current/referenced environment was deleted.

| Check | Result |
|---|---:|
| Protected prior source/data/evidence hashes | 3,449 unchanged |
| Current shared/private source hashes | 18 unchanged |
| Retained evidence/copy files at cleanup | 77 unchanged |
| Apparent scratch payload | 4,910,350 bytes |
| Retained phase payload at cleanup | 9,524,816 bytes |
| Observed immediate free-space improvement | 7,647,232 bytes / 7.29 MiB |

Filesystem improvement is an observed before/after delta, not guaranteed bytes
solely attributable to this process or a sum of directory sizes. Later report
and documentation receipts add small retained metadata, still under the cap.
All failed attempts, original/repair registrations, scientific inputs and old
seals remain immutable. Current verified source copies are retained for replay.

## Proof And Reuse

Private `host_process_review.json`, `cleanup_preflight.json`,
`cleanup_receipt.json`, `final_source_snapshot.json` and final artifact hashes
remain in the registered M5-09 lane. Reproducing tests may create a new exact
scratch revision with a fresh registration; deleting scratch does not certify
any artifact or make an old failed receipt pass.

See the [phase report](../mode5/M5_09_DOSSIER_REPORT.md) and
[aggregate summary](../mode5/evidence/m5-09.json).
