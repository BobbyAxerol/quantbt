# PRE-E06-02 Test And Cleanup Receipt

## Scope And Budget

Follow the [cleanup runbook](../BUILD_TEST_CLEANUP.md) and
[registered phase](../../upgrade/implement.md#qms-pre-e06-02).
Reuse the existing CPython 3.12 G01 consumer with source-first imports and
one numeric thread. No environment, wheel, Rust build or external data copy
was created. The incremental scratch ceiling was 512 MiB, with at least
5 GiB safety headroom; initial available space was 27,014,422,528 bytes.

## Reviewed Cleanup

**Deleted paths: none. Reclaimed bytes: zero.**

This phase generated only small test logs/XML and a source qualification
receipt. These are evidence, not disposable build scratch. Removing them
would lose failure provenance without materially recovering disk space.
No consumer needs reinstallation. No services, Git objects, Docker files,
dependency caches, Rust targets or unrelated projects were changed.

Retain:

- All passing and failing files in `.maturin/qms08/pre-e06-02`.
- The initial failed maturity log at
  `.maturin/qms08/pre-e06-02-maturity-v1.log`, outside that lane.
- The existing G01 consumer/native extension and offline dependencies.
- Historical QMS04/QMS07 extensions needed by their strict version guards.
- All 50 exact artifacts referenced by the previous execution closeout.
- All 69 historical source/scientific seals and the original detailed guide.
- Source, the current public receipt, private research and all user changes.

## Verification

The [source-bound gate](../../benchmarks/optimization/meta_selection/qms_pre_e06_02_closure.json)
checks the original guide hash, exact historical seals/artifacts and both
reviewed funding-binding repairs. Historical qualification is not rewritten
to certify today's amended source.

Final test shards are validated from XML, not from a shell pipeline exit
status. Failed maturity, fixture, tooling and missing-document runs remain
failures; their corrected reruns have separate filenames. Only complete
passing shards enter the current source certificate. All 27 scalar-only
not-applicable cells remain excluded from the PASS count.

## Measured Retention And Resources

The final inspection preserved **488 unique files**, including 40 log/XML
files, current runtime/verification source, exact artifacts and three native
extensions. Their sorted path/SHA-256 inventory has the same aggregate before
and after the cleanup decision:
`4cc5529a0a9976aa4c4d1036a931015a0a1d906d95898d5e305e9fb378526ec8`.
Aggregate hashing uses UTF-8 JSON, sorted keys and compact separators.

The 40 log/XML inventory aggregate is unchanged:
`432697e06d09d92c568a63f2a201259af0f45e8c96371ba71950c1fb27f6a30b`.
The lane's file payload is 753,857 bytes, plus the retained initial maturity
log's 2,889 bytes: **756,746 bytes** total evidence, below 1 MiB.
The source certificate SHA-256 is
`17d6e392e2f5f47115ac0acb34ea7df78a8e88e0d5499936f503f2c43068dd73`.

| Filesystem measurement | Before exit inspection | After exit inspection |
|---|---:|---:|
| Used bytes | 73,202,847,744 | 73,202,905,088 |
| Available bytes | 26,993,180,672 | 26,993,123,328 |
| Used inodes / 6,553,600 | 945,183 | 945,185 |

Observed free-space delta is **-57,344 bytes**, not reclaimed space. Relative
to the phase's starting measurement, available bytes fell by 21,299,200.
These shared-host observations cannot attribute every change to this phase;
they are not a sum of apparent directory sizes or a disk-efficiency benchmark.
No deletion was made and more than 25 GiB remains available.

Core imports resolve to `src/quantbt/__init__.py`. The reused native dependency
is **0.4.3**, loaded from the existing G01 consumer. Its extension SHA-256 is
`e338a0f1549395211dc42332ed15eb43c0bb92f71728ca3181b0268f56a57aba`.
Historical QMS04/QMS07 extension hashes also remain unchanged:
`99e36ede90ebb9ea68e355304f2909ba117faf206e95e57e641bb6bdd8c62f74`
and `247be0acdd5ca874dc0ca84f7f23a73781f968fc659079a56f74906d087237ff`.
No current-source installed-wheel claim follows from source-first imports.

This receipt concerns retention and resource safety, not economic improvement,
performance/RSS, fresh installed-wheel qualification, CI or publication.
See the [phase report](../meta_selection/PRE_E06_02_REPORT.md) for exact tests,
methodology and remaining gates.
