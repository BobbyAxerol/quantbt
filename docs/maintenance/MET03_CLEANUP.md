# MET-03 Cleanup

Local source and installed-artifact qualification completed on 2026-10-07.
No services, environments from other phases, data, alpha files, Git objects or
global caches were removed. No Rust build occurred.

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
