# MET-03 Cleanup

Local source and installed-artifact qualification completed on 2026-10-07.
No services, environments from other phases, data, alpha files, Git objects or
global caches were removed. No Rust build occurred.

## Reporting Performance Follow-Up

The [performance report](../metrics/MET03_PERFORMANCE_REPORT.md) and
[sealed closure](../metrics/evidence/met03/performance-closure.json) cover the
latest source. Removed exact new source consumers `/tmp/quantbt-met03-qa4nbm10`,
`/tmp/quantbt-met03-kgdm0kvy`, `/tmp/quantbt-met03-o1dk4loe` and final build/
sequential consumers `/tmp/quantbt-met03-srglr5h_`; their nested comparison
scratch also completed its owned lifetime. Only owned focused pytest scratch
`/tmp/pytest-of-root/pytest-161` was additionally removed after preserving both
theme figures and verifying its single exact internal `current` symlink.
The initial inventory guard rejection is retained. No general symlink cleanup
exception or deletion of other pytest paths is introduced.

Installed peak: 14,886 files / 694,102,339 apparent bytes. Final consumer cleanup
recovered 13,037,568 actual filesystem bytes; the 1,373,285,390 apparent
hard-linked lifetime bytes are not physically reclaimed bytes. Figure copy/
cleanup reclaimed zero net bytes. The final exact artifacts remain under
`.maturin/met03/run-20261007T220807135175Z/dist/`; historical artifact/evidence
hashes pass, primary tooling/offline cache and all unrelated resources remain.
Cleaned environments need fresh installation to rerun; no Rust rebuild occurred.

## Historical Owner Recheck

The [latest recheck](../metrics/MET03_RECHECK_REPORT.md) has fresh source/artifact
receipts; the original completion below remains historical, not rewritten.
Removed only `/tmp/quantbt-met03-b85co6gr` (source),
`/tmp/quantbt-met03-ovyrob6y` (build/sequential installed consumers), and
`/tmp/quantbt-met03-review-repro` (empty test directories after retained XML).
Peak concurrent files/bytes were 14,886 / 694,093,140, below 20k / 3 GiB.
The final installed cleanup recovered 13,033,472 actual filesystem bytes;
the 1,373,271,846 apparent lifetime bytes are not an actual reclamation claim.
Final repro-directory removal recovered 20,480 bytes. Logs, passing/failing
receipts, offline dependencies, primary tooling and old/new artifacts remain.
New artifacts: `.maturin/met03/run-20261007T204118067245Z/dist/`.
The [new closure](../metrics/evidence/met03/review-closure.json) verifies all
previous evidence/artifact hashes and current source/native identity; all
consumer environments require fresh installation to rerun.

## Reviewed Scratch

- Source qualification `/tmp/quantbt-met03-u9uyuf_8`: isolated dependency/native
  environment, pytest/JIT/matplotlib scratch, removed after process completion.
  Inventory: 12,446 files, 649,018,027 apparent bytes. Exact logs/receipts remain.
- Installed qualification `/tmp/quantbt-met03-uz0rditp`: build/staging and two
  sequential wheel/sdist consumers removed after their independent proofs.
  Concurrent peak: 14,886 files, 694,087,695 apparent bytes. The full lifetime
  inventory has 28,599 entries / 1,373,263,562 apparent bytes; that is not
  concurrent allocation and not reclaimed disk. Hard-linked dependencies remain
  in the offline cache. Final cleanup observed 13,033,472 bytes extra free;
  earlier sequential consumer removals are not falsely added to this figure.
- `/tmp/quantbt-met03-initial`: six reviewed exploratory XML/chart outputs,
  346,018 apparent bytes. JUnit and dark/light figures were preserved before
  removal; observed filesystem improvement 212,992 bytes.
- Failed cache/dependency/DNS attempt scratch was removed by the same owned
  temporary-directory lifetime; failure logs and receipts are retained.

## Preserved

Exact wheel/sdist: `.maturin/met03/run-20261007T200542851857Z/dist/`.
Unchanged sealed native 0.4.3 artifact, all existing `.maturin`/Rust caches,
primary `.venv`, offline UV dependency cache and historical receipts remain.
New dependency wheels fetched for the isolated visualization proof are retained
for offline reruns; source-run net free-space decrease includes these downloads,
not forgotten live consumers. Final free space was 25,563,488,256 bytes.

Source modules and artifact/log hashes are verified by the immutable
[closure receipt](../metrics/evidence/met03/closure.json). Full scratch inventories
and exact resource counters are in the [source receipt](../metrics/evidence/met03/run-20261007T195815741400Z/receipt.json)
and [installed receipt](../metrics/evidence/met03/run-20261007T200542851857Z/receipt.json).
These receipts describe historical installed executions, not environments still
available after cleanup. Reinstall exact retained artifacts to rerun.
