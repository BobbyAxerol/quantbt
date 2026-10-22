# QMS Phase Report - QMS-04

## Source And Scope

2026-10-04, branch `feat/meta-selection-samplers`, entry `ac3bd15`.
Implemented only the approved [QMS-04 plan](../../upgrade/implement.md#qms-04)
and linked [detailed guide](../../upgrade/QUANTBT_1_1_1_META_SELECTION_AND_SAMPLER_MODULE_GUIDE_V1_1_VI.md#qms-04--ridge-reference-ranking-và-decision-artifacts).
Core and installed native stay `1.1.1`/`0.4.2`; no public endpoint signature,
financial kernel, metric formula, sampler trajectory or user alpha changed.
Source remains canonical `src/quantbt`.

The new PyO3 numeric module is feature-gated, off in the baseline build. Its
local candidate wheel is `0.4.3.dev1`, built in a temporary versioned tree and
loaded in a private namespace. It does not overwrite installed 0.4.2 or claim
public financial pairing/manylinux-matrix certification. Historical receipts
are preserved, not regenerated with new source or invented owner approval.

## Delivered

- Focused numeric runtime, learner/model, guarded selector and strict artifact
  modules. No new financial engine or unrestricted history/file input exists.
- Exact `ridge_origin_sum_v1`, no intercept: valid non-anchor rows total one
  per origin. Revisions replace/reweight the full origin; empty-label revisions
  remain provenance, not fake support. Default minimum remains twelve origins.
- Independent whitened-row solve, Rust serial Gram/Cholesky, finite/SPD,
  conditioning/residual and workspace checks; no inverse, N-by-N weights,
  hidden jitter, fast-math or feature/candidate reduction.
- One contiguous historical transform and one fit call across all origins.
  One current transform/rank batch; inputs owned before GIL release. Typed
  outputs retain all predictions/IDs, not current forward labels.
- Signed-min-Y policy with predicted-Q floor, exact zero anchor, native
  cold-start/whole-pool OOD fallback, typed invalid-input errors and deterministic
  minimum-based tie set/distance/canonical-ID ordering. Complete ranking is
  optional and recoverable from retained scores without financial replay.
- Whole-reference decision verification for native proposals. Near Q/tie
  boundaries or guard/tie/winner disagreement uses complete reference fit/rank,
  not top-K repair. This verification cost is measured, not hidden.
- Immutable full model and proposal/shadow bundles: schema/vocabulary/masks,
  scaler, coefficients, reference sufficient statistics, exact snapshot/revision
  and fit-row references, permissions, numeric/support/policy versions and clocks.
  Safe restore requires reviewed ID and explicit availability. Weights-only,
  missing basis, duplicate JSON fields, nonfinite or tampered payloads fail.
- Raw-best/native/meta/actual distinctions: pure proposal has no executed
  choice; shadow records the native anchor. Public WFO activation is not added.

Methodology and exact internal contracts: [MODEL.md](MODEL.md).

## Tests And Technical Gates

[Executed JUnit](../../benchmarks/optimization/meta_selection/qms04_tests.xml):
**352 passed, zero failures/errors/skips**, 76.70 s; 41 Q4 checks and 311
prior/affected checks. Also **2 Rust unit tests passed**, none ignored.
The 65 exposed warnings are existing Optuna experimental-feature notices.

Q4-T01..08 counts: **5/2/3/6/3/11/2/9**. Native-contract cases were executed
with the actual candidate extension, not missing-capability branches.

```bash
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 \
QMS04_NATIVE_EXTENSION="$PWD/.maturin/qms04/_quantbt_native.cpython-312-x86_64-linux-gnu.so" \
.venv/bin/python -m pytest -q tests/meta_selection \
  tests/test_optimization_core.py tests/test_optimization_samplers.py \
  tests/test_optimization_integration.py tests/test_optimization_phase33b.py \
  tests/test_phase49a_walkforward_schedules.py \
  tests/test_phase50_nested_mode1_causal.py \
  tests/test_phase74_public_wfo_native.py tests/test_perf_06_research_audit.py \
  --junitxml=benchmarks/optimization/meta_selection/qms04_tests.xml
```

| Gate | Executed evidence | Result |
|---|---|---|
| G4-MATH | Augmented least-squares reference, Gram/b/beta, origin weights, units/lambda and chunk/reorder tolerance | PASS |
| G4-POLICY | Actual fitted guide 5.7 chooses y, Q rejects x/z; signed/tie policy, exact anchor and native boundary decision parity | PASS |
| G4-SERIALIZATION | Complete bundle restores prediction/winner, no-replay ranking; missing basis/vocabulary and rehashed tampering fail | PASS |
| G4-SUPPORT | Cold start, failed/undefined/unverified records, OOD, future/mismatched models and unavailable revisions | PASS |
| G4-RESOURCE | Actual compiled native batches, version/ownership/copy/workspace evidence and resolved fallback/block costs | PASS |
| G4-OWNER | No acceptance decision invented | PENDING |

The [receipt](../../benchmarks/optimization/meta_selection/qms04_gate_receipt.json)
pins tests and [source/cost evidence](../../benchmarks/optimization/meta_selection/qms04_ridge_evidence.json).
Canonical-source, architecture/import, lint, documentation and benchmark-governance
checks are separate. QMS-02/03 source-lock tests permit only the exact QMS-04
feature/export additions by stripping those bytes before comparison. They still
lock all financial Rust, package versions, metrics, account and sampler code;
the historical evidence itself is not rewritten.

No full-repository suite, remote CI, release install matrix or economic
superiority claim is made. QMS-08 owns broad final qualification.

## Original Engine Integration

The original QuantBT SMA/Mode-4 fixture supplies engine-produced labels on
synthetic OHLCV, not private alpha or real-market edge evidence. Fit occurs
only after both forward revisions are available; those labels are never
retroactively used to select parameters for an earlier cutoff.

| Fixture | Support origins | Valid labels | Full fit including reference/cold artifacts | Fit FFI calls | Owned numeric input copies |
|---|---:|---:|---:|---:|---:|
| Medoid | 2 | 8 | 137.251 ms | 2 | 657 bytes |
| Centroid | 2 | 10 | 175.738 ms | 2 | 793 bytes |

Both explicitly override the twelve-origin integration default for engineering
proof only. Native/reference beta and full model restore pass. Fitter extra
financial evaluations: **zero**. The observer remains separate and its original
cost/counts are retained in evidence. These rows are complete small-model fit
costs, not solver time, economic certification, or a medoid/centroid speed test.

## Fixed-Matrix Costs

Same float64 inputs/weights/lambda, no removed dimensions/candidates. One warm-up,
15 measured calls, one BLAS/OpenMP thread; medians below include host validation,
conversion/dispatch and native owned copies. Qualification time, p95, hashes,
owned bytes and used blocks are retained in evidence.

| N | d | P | Rust primary fit | NumPy primary fit | Rust primary rank | NumPy primary rank |
|---:|---:|---:|---:|---:|---:|---:|
| 180 | 8 | 64 | 0.0515 ms | 0.0915 ms | 0.0196 ms | 0.0156 ms |
| 4,096 | 8 | 600 | 0.4913 ms | 0.3058 ms | 0.0322 ms | 0.0202 ms |
| 4,096 | 24 | 600 | 3.3525 ms | 0.6629 ms | 0.0487 ms | 0.0242 ms |
| 16,384 | 8 | 2,000 | 1.9386 ms | 1.0797 ms | 0.0532 ms | 0.0308 ms |

Rust helps this small fit (~1.78x), but the larger scalar Gram loop and current
rank bridge lose to NumPy BLAS. Full certified fit, including independent
reference validation, costs Rust/NumPy **0.3779/0.2018**, **1.1382/0.4938**,
**4.2015/0.9127**, **2.8862/1.1621 ms** respectively. No public native numeric
performance promotion or whole-WFO acceleration claim is made.

Parameter encoding/scaler/diagnostics/artifacts are declared NumPy/Python
blocks; require applies to native transform/Gram-solve/rank. Installed 0.4.2
auto falls back with missing capability; require fails. Numba is not used,
so no hidden JIT time or an untested extra implementation is claimed.

Process peak RSS: **290.027 MiB**, cumulative imports/financial JIT/native fit
in one process. It is not isolated native memory saving or plateau evidence.
No N-by-N allocation exists; exact workspace/owned-input sizes are recorded.

## Handoff

QMS-04 implementation COMPLETE; five technical gates PASS; performance
MEASURED_BLOCKS_NO_PUBLIC_PROMOTION; empirical NOT_ASSESSED; owner review PENDING.
No missing functional block remains in this registered mathematical/artifact
phase. Measured native performance holds are explicit; QMS-07 owns the registered
further DSA/performance work. Public causal integration (QMS-05), prepared/host
handoff (QMS-06) and final economic/package gates (QMS-08) are not advertised
as delivered here.

Build: `.venv/bin/python -m tools.build_qms04_candidate`.
Example: `.venv/bin/python -m examples.wfo_meta_ridge` (baseline fallback), or
pass `--extension .maturin/qms04/_quantbt_native.cpython-312-x86_64-linux-gnu.so`
for actual native blocks. Reproduction/verification commands are in the unified
plan. First implementation commit: `412f507`; final evidence/docs are committed
separately. No push, merge, version/tag release or automatic QMS-05 advancement.
