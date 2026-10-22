# Continuous Snapshot Constructor Repair

Status: **LOCAL_REPAIR_VERIFIED**. Focused source/guard checks and final V6
wheel/sdist snapshot consumers passed. The overall phase's operational
exceptions have explicit owner acceptance; final handoff review remains separate. No push, CI
dispatch, release or publication is authorized by this note.

## Defect And Exact Scope

Continuous snapshot objects inherited copy/pickle validation but did not seal
their array layouts during construction. Freshly produced evaluations and
retention objects therefore raised `AttributeError: _snapshot_layout` before
copy or serialization. This was a runtime integration defect, not stale pickle
input or a Python/Rust accounting disagreement.

Source commit `bf3f919550a82ac97d6c4c81073a52880d5e3331` adds exactly three
trailing `self._seal_arrays()` calls, after existing validation and freezing:

- [continuous.py](../../src/quantbt/mode5/continuous.py): `ContinuousStream` and
  `ContinuousAccountEvaluation`.
- [continuous_retention.py](../../src/quantbt/mode5/continuous_retention.py):
  `ContinuousAccountRetention`.

The [append-only source amendment](../maintenance/evidence/m5-12-snapshot-source-amendment.json)
pins both paths. It is a source-only qualification, not an artifact certificate.
The shared snapshot base, financial execution, estimator, metric formulas,
defaults, Rust source and ABI are unchanged by this repair. Earlier approved
financial repairs remain separately recorded; their historical certificates
are not reissued as unchanged-source claims.

## Array Safety

Original margin observations retain their two-column `(N, 2)` layout and exact
values. They are not flattened, summed or reconstructed from scalar metadata.
Storage remains immutable and detached from mutable result arrays; clones have
independent NumPy headers, even when immutable backing bytes can be shared.

The [focused snapshot tests](../../tests/mode5/test_continuous_snapshot_seal.py)
cover copy/deepcopy and pickle protocols 4/5, read-only two-column storage,
and shape/dtype/strides mutation rejection directly and recursively through
evaluation and retention. Existing provider/runtime tests retain identity,
accounting and original-result mutation checks.

## Recorded Local Evidence

| Scope | Result | Retained JUnit |
| --- | --- | --- |
| Focused snapshot/provider/runtime source tests | 138 passed, 19.13 s | `snapshot-repair-02.xml` |
| Source guards and qualification tooling | 335 passed, 13.70 s | `snapshot-source-guard.xml` |

These are separate suite results, not an aggregate final regression or an
installed-wheel PASS. Durations are pytest-reported, not performance benchmarks.
Receipts, logs and JUnit remain local under
`upgrade/private/mode5_upgrade_v1/m5-12/attempt-01/`; they are not package inputs.

The earlier `final-23` result remains **733 passed / 10 failed**. The snapshot
pretest blocked by disk admission was **not launched** and is not a PASS.
Reviewed completed-fixture cleanup recovered **276,406,272 bytes**, preserving
**17,870 protected file pins**; that cleanup does not change either disposition.

## Artifact Boundary

The native extension remains the exact retained build with SHA256
`82b998d8cded88258a1c4fc77fb9f22b61773c415bfbece69cef173bc0cf8266`.
Its local `m5-12-local-v4/cp312/native-build.json` provenance is checked by the
[native build verifier](../../tools/m5_12_native_build.py), not inferred from
the package version. No native rebuild is required for these Python-only seals.

V5 core artifacts predate this repair and are superseded by V6 core
wheel/sdist artifacts. Actual final-source installed consumers qualify those
artifacts with exact source/native custody; previous V5 successes are not
relabeled. Each V6 kind passes the 44-case feature roster, including actual
baseline/challenger account copy/deepcopy/pickle4/pickle5 and two-column margin
checks within the unchanged bounded proposal budget. Missing roundtrip
telemetry fails closed. See the [current summary](M5_12_LOCAL_QUALIFICATION_SUMMARY.md)
and [canonical report](M5_12_REPORT_R3.md) for exact artifact hashes and receipts.
There is no remote qualification or public-release certification.
