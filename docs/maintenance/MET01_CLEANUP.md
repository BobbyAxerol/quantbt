# MET-01 Resource And Cleanup Receipt

Registered before execution in the [phase plan](../../upgrade/implement.md#metrics-met-01):
64 MiB incremental budget, <=512 new inodes, 5 GiB safety headroom. Reuse
`.venv`, no new environment/native build or dependency download. Initial
baseline free disk 25,769,504,768 bytes; roughly 5.59 million available inodes.

Each qualification run creates an exact private temporary root under
`/tmp/quantbt-met01-*`; pytest/matplotlib/Numba caches are directed there.
Child processes complete before `TemporaryDirectory` removes that run's exact
root. No process/service is killed and no historical cache, source, Git,
alpha, dataset, environment, wheel or scientific receipt is deleted.

| Retained run receipt | Removed exact inactive scratch | Result |
|---|---|---|
| [18:27:01](../metrics/evidence/met01/run-20261007T182701901759Z/receipt.json) | `/tmp/quantbt-met01-lfy6_p8q` | FAIL retained; 322 protected hashes unchanged |
| [18:28:07](../metrics/evidence/met01/run-20261007T182807407279Z/receipt.json) | `/tmp/quantbt-met01-6v4oe2i7` | Intermediate PASS retained; 322 hashes unchanged |
| [18:30:05](../metrics/evidence/met01/run-20261007T183005354531Z/receipt.json) | `/tmp/quantbt-met01-lfqd18zq` | Test-oracle FAIL retained; 322 hashes unchanged |
| [18:31:09](../metrics/evidence/met01/run-20261007T183109306830Z/receipt.json) | `/tmp/quantbt-met01-g7ehn366` | Current numeric PASS; protected/log hashes preserved |

Last numeric run: before free disk 25,766,412,288; after 25,766,309,888 bytes
(difference -102,400). Inodes 5,592,367 -> 5,592,361. Kept 80,550 bytes of
run evidence before its receipt. The previous failed/pass evidence remains
separate and immutable; removing scratch did not rewrite a FAIL into PASS.
The observed filesystem delta includes concurrent host/Git activity and
retained evidence, not a claim of reclaimed performance/RSS savings.

Exact source/log/fixture/QS/extension hashes are in the receipts. The unchanged
native tooling extension is recorded only, not a current native execution
certificate. Report/docs-only final checks do not need a new build environment.
Future report/artifact qualification must register its own budget and inputs.
