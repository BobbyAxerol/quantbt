# QMS Phase Report - QMS-07

## Scope And Status

2026-10-04, `feat/meta-selection-samplers`, entry `eb167a4`.
Implemented the [QMS-07 plan](../../upgrade/implement.md#qms-07) and
[detailed guide](../../upgrade/QUANTBT_1_1_1_META_SELECTION_AND_SAMPLER_MODULE_GUIDE_V1_1_VI.md#qms-07--rust-first-dsa-tối-ưu-và-parity-xuyên-folds),
including [full-sequence parity](../../upgrade/QUANTBT_1_1_1_META_SELECTION_AND_SAMPLER_MODULE_GUIDE_V1_1_VI.md#s8)
and [information-preserving performance rules](../../upgrade/QUANTBT_1_1_1_META_SELECTION_AND_SAMPLER_MODULE_GUIDE_V1_1_VI.md#s10).

Implementation COMPLETE; technical PASS; performance MEASURED_SCOPED_GAIN;
empirical NOT_ASSESSED; owner review PENDING. The proposed disabled budgets
pass locally but owner acceptance is not invented. QMS-08 is NOT_STARTED.
No endpoint, methodology, financial engine, published version or installed
wheel was changed. Core/native remain **1.1.1 / 0.4.2**.

Local implementation commits: `8f555c9`, `abcaee2`, `2c64e04`.
Evidence/documentation closure is the following commit, not a release/push.
QMS-01..06 receipts remain immutable historical records.

## Delivered

- Profiled entry first: repeated revision serialization/digests dominated the
  new fit path. Optimized that measured work rather than changing Optuna.
- Object-owned, read-only memo for immutable family/task/panel/revision/model
  IDs, snapshot support and complete training rows. Hidden slots are not
  portable fields; canonical JSON/digest bytes are unchanged. Replacement and
  deserialization create empty memos. No global record retention.
- Existing authorized family/corpus/cohort availability index retained.
  Binary cutoff search still resolves exact revisions; iterator traversal avoids
  allocating a prefix list. Rewinds and checkpoint resume remain valid.
- Linear keyed validation of model revision/weight references replaces repeated
  scans. Complete row membership, order and per-origin weights remain unchanged.
- Bounded exact fit/prediction reuse, separate from financial evaluation caches.
  Full context and complete float64 buffer identities are required. Two entries
  maximum, output budget `min(8 MB, max_workspace_bytes / 8)`, independent return
  copies, explicit clear and bypass/eviction without deleting history.
- Existing Rust batch ABI reused. Hoisted one repeated weighted multiplication
  without changing arithmetic association/reduction order. No second engine,
  new FFI symbol, precision reduction, fast-math or parallel reduction.
- Complete reference fit/pool certification and boundary fallback retained;
  no top-K approximation. Winner-only stays linear; requested full rankings
  and all predictions remain available for cold reporting without replay.
- Exact chronological corpus: early Q-floor and tie fixtures, six decisions,
  full panels/actual params, a late correction, mid-run reviewed checkpoint
  resume and a subsequent rewind. Late correction replaces the entire origin.
- Actual compiled private Rust candidate, GIL release and detached output proof.
  Sequential proposals/objectives/stopping, observer RNG and financial paths
  match the entry source. No trial/label/pool/history reduction.

See [numeric identity and lifetime](MODEL.md#exact-reuse-and-lifetime).

## Tests And Gates

[Executed JUnit](../../benchmarks/optimization/meta_selection/qms07_tests.xml):
**467 passed**, zero failures/errors/skips, **128.85 s**; 31 Q7 checks plus
436 prior/affected checks. The 69 warnings are existing Optuna experimental
features, not suppressed failures. This is scoped regression, not the entire
repository or a remote platform matrix.

| Gate | Evidence | Result |
|---|---|---|
| G7-PARITY | Entire chronological sequences, early boundaries, revisions/resume/rewind; actual selections, panels, weights and public accounts | PASS |
| G7-COST_ACCOUNTING | Same full studies/labels/pools; wall/CPU, cold imports/build, copies/FFI/cache/bar counts and eleven profiled stages | PASS |
| G7-MEMORY | No NxN weights/inverse; bounded cache, detached outputs, twenty-iteration RSS/PSS plateau | PASS |
| G7-DISABLED_OVERHEAD | Eight alternating process pairs, three studies per process; local proposed 3%/5% budgets | PASS, owner budget acceptance pending |
| G7-PERF_DISPOSITION | Measured fixed matrices and full public runs; Rust/reference costs and limits disclosed | PASS |
| G7-OWNER | No result/budget/economic/public-release approval invented | PENDING |

Q7-T01..08 executed counts: **4 / 1 / 13 / 3 / 2 / 2 / 5 / 1**.
Numeric tolerances stayed `rtol=1e-9`, `atol=1e-10`; original metric/prepared
comparisons stayed `1e-10`. Logical membership, guard/tie/actual parameters and
sampler records are exact. Public equity/returns/positions match entry byte
digests. Chronological corpus task/revision/panel IDs match exactly; each model
retains a valid digest of its own backend-specific artifact.

Observer publication wall times can differ in public timed runs, so their
artifact IDs need not match. Exact permitted origins, panel labels and weights
are compared independently. The sealed replay fixes those times/revisions to
test the whole chain on identical information, including the first uncertain
decision. Earlier history is never rewritten into a new PASS record.

## Matched Public Measurements

Source, raw samples, traces, profiles and build receipt are in
[evidence](../../benchmarks/optimization/meta_selection/qms07_performance_evidence.json).
[Verifier receipt](../../benchmarks/optimization/meta_selection/qms07_gate_receipt.json)
checks current source/binary hashes, JUnit groups, complete public/chronological
parity, memory and disabled-budget claims.

Synthetic SMA: 850 daily bars, six quarterly studies, six attempted trials each,
seed 731, one Optuna/Rust worker. Support minimum one is an engineering override;
product default twelve origins is unchanged. Both enabled arms acquire the same
32 original observer outcomes and build four learned models. No market-edge or
all-five-mode speed claim is made; the new meta selector supports Mode 4 causal.

Alternating fresh processes: eight disabled pairs (three measured studies per
process), four original-result/meta-reference pairs and four prepared/meta-Rust
pairs. Warm-up and cold import costs are separate. No local test/build process
ran alongside the final measurement lane. An exploratory single-study/process
pilot under concurrent tests failed the working p50 target; its disposition is
retained. Aggregate/no-competing-test protocol was registered before final results.

| Matched full public run | Entry p50 | Current p50 | Elapsed reduction |
|---|---:|---:|---:|
| Original-result Numba, meta reference | 2.743 s | 1.916 s | 30.2% |
| Prepared Rust, meta Rust | 2.329 s | 1.425 s | 38.8% |
| Meta disabled | 0.736 s | 0.756 s | -2.63% (overhead) |

Prepared/meta-Rust p95: **2.600 -> 1.719 s**. Disabled p95:
**0.805 -> 0.798 s**, **-0.82%**. All samples are retained; no best-run selection.
Observed CPU p50: meta reference **2.701 -> 1.912 s**, prepared/meta-Rust
**2.322 -> 1.419 s**. These are this fixture/host, not universal speed guarantees.

### Work And Boundaries

Per prepared study: **36 attempted trials**, **134 native score rows**,
**12,004 scored bars**, **38 execute-score calls** plus **38 witness
materializations** and existing output/diagnostic boundaries. Prepared cache
hits/misses **104/32**, market residency **48,450 bytes**, transient request bytes
**124,328**, witness outputs **4,690 bytes** remain equal to entry.

Meta: **16 numeric calls + 3 qualification probes**, **5,076 owned input-copy
bytes**. Public changing-fold fit/prediction cache hits are **zero**, misses eight;
last entries total **184 bytes**. Whole-WFO improvement is primarily lossless
immutable work reuse, not omitted financial evaluations or fictitious cache hits.

Separate profiled runs reconcile eleven exclusive spans plus an explicit
unattributed residual with total time. They are not latency medians. Fit span
was **2.135 -> 0.030 s**; rank span **0.043 -> 0.034 s**. Main `_call_strategy`
instrumentation saw **38 calls** in both arms. That counter covers the class
seam, not every private callback; 32 observer evaluations are accounted separately.

### Memory And Resources

Process peak-RSS medians, including imports/warm-up:

| Arm | Entry | Current |
|---|---:|---:|
| Meta reference | 285.156 MiB | 282.914 MiB |
| Prepared/meta Rust | 286.428 MiB | 285.084 MiB |
| Disabled | 280.064 MiB | 280.334 MiB |

Small differences are not a certified RSS-saving claim. Fixed numeric workspace
`N=4096,d=24,P=600`, twenty repetitions: after five allocation iterations,
RSS **286.883 MiB** is flat; PSS **244.552-244.554 MiB**; cache **14,592 bytes**.
Scientific archive/model retention remains explicit and is not discarded to
obtain a plateau.

BLAS/OMP/MKL environment caps are one; actual OpenBLAS control reports one.
Existing Numba configuration remains four, with no new meta Numba/JIT path;
existing financial kernels are not reconfigured by this phase. Legacy prepared
parallelism metadata reports configured BLAS four, not the observed cap. This
provenance mismatch is recorded below, not hidden as measured parallelism.

## Numeric Disposition

Matrices preserve all N/d/P inputs, float64, labels/weights and ordering.
Warm fit medians include validation, FFI/owned cloning and output conversion:

| N / d / P | Current Rust | NumPy reference |
|---|---:|---:|
| 180 / 8 / 64 | 0.043 ms | 0.094 ms |
| 4096 / 8 / 600 | 0.432 ms | 0.356 ms |
| 4096 / 24 / 600 | 2.119 ms | 0.746 ms |
| 512 / 64 / 600 | 1.831 ms | 0.383 ms |
| 16384 / 8 / 2000 | 1.549 ms | 1.053 ms |

Native is not uniformly faster than BLAS. The Rust change is a lossless cleanup,
not a medium/high-d speed promotion; explicit qualified NumPy reference remains
available and appropriate there. `require` is an explicit Rust request, not an
automatic performance promise. No guessed hardware crossover is promoted.
Published native 0.4.2 still lacks QMS numeric capability, so auto uses documented
NumPy fallback; candidate feature flags remain off in ordinary builds.

Transform, Gram/solve and score batches are Rust when qualified/requested.
Schema/conditional encoding, scaler/diagnostics, guard/tie/reference verification
and artifact/report adaptation remain measured Python/NumPy. Those are not
advertised as Rust-owned. No duplicate Numba kernel/JIT path was introduced.

Isolated `0.4.3.dev3` build: **48.996 s**, Rust **1.97.1**; Linux x86_64,
CPython 3.12 only. Owned inputs are cloned before GIL release, not zero-copy.
Binary SHA-256:
`247be0acdd5ca874dc0ca84f7f23a73781f968fc659079a56f74906d087237ff`.
Cold imports/run warm-up and native qualification samples are separately retained.
This is not an installed-wheel or multi-platform certification.

## Reproduction

Build the existing QMS-04/QMS-06 private candidates when absent, then:

```bash
.venv/bin/python -m tools.build_qms07_candidate
git archive eb167a4 src examples tools tests/meta_selection --output=/tmp/qms07-entry.tar
mkdir -p /tmp/qms07-entry
tar -xf /tmp/qms07-entry.tar -C /tmp/qms07-entry
env OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 \
  .venv/bin/python -m tools.qms07_performance --entry-tree /tmp/qms07-entry
env OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 \
  QMS04_NATIVE_EXTENSION="$PWD/.maturin/qms04/_quantbt_native.cpython-312-x86_64-linux-gnu.so" \
  .venv/bin/python -m pytest -q tests/meta_selection \
  tests/test_optimization_core.py tests/test_optimization_samplers.py \
  tests/test_optimization_integration.py tests/test_optimization_phase33b.py \
  tests/test_phase49a_walkforward_schedules.py tests/test_phase50_nested_mode1_causal.py \
  tests/test_phase74_public_wfo_native.py tests/test_perf_06_research_audit.py \
  --junitxml=benchmarks/optimization/meta_selection/qms07_tests.xml
```

For the first execution (JUnit not yet present), seal generated evidence without
replaying the financial study:

```python
import json
from tools.qms07_performance import DIRECTORY, validate
evidence = json.loads((DIRECTORY / "qms07_performance_evidence.json").read_text())
receipt = validate(evidence, DIRECTORY / "qms07_tests.xml")
(DIRECTORY / "qms07_gate_receipt.json").write_text(json.dumps(receipt, sort_keys=True, indent=2) + "\n")
```

Then `.venv/bin/python -m tools.qms07_performance --check` verifies bytes,
required groups and decisions; it does not trust a handwritten PASS string.
Do not overwrite sealed QMS-01..06 artifacts to match new source.

## Debt Ledger And Next Decision

No unresolved mandatory QMS-07 implementation/parity blocker remains.
Working budgets pass locally; owner acceptance/review remains pending.

| Item | Disposition |
|---|---|
| Inherited W3 reactive meta full-pool/original-metric seam | Explicitly unsupported under approved optional deferral; ordinary meta-off W3 unchanged. Follow-up needs owner scope approval. |
| Native candidate feature/public pair and installed wheel/remote matrix | QMS-08 qualification, not claimed delivered by a private build. |
| Real-alpha economic acceptance | QMS-08 requires registered data/recipes/support and paired folds; these synthetic engineering runs are not evidence of edge. |
| Legacy parallelism provenance | Configured prepared BLAS=4 differs from observed environment-capped OpenBLAS=1. Follow-up telemetry should distinguish requested/configured/actual; no financial/resource-policy change here. |
| Medium/high-d native solve cost | Measured NumPy reference remains qualified; no forced promotion. Geometry/hardware-aware automatic dispatch is a possible later optimization, not missing Ridge functionality. |

Do not remove reference boundary verification, truncate labels/history or alter
search just to improve these timings. The next phase requires separate approval;
no push, merge, release or economic acceptance is performed by this report.
