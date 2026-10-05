# QMS-C05 Local Review Report

## Conclusion

**Spec and independent tests complete; production activation NOT authorized.**
All **366 scoped checks PASS**, including **139 C05-specific** tests, with zero
failed, errored or skipped cases in the final JUnit evidence. Owner methodology
approval is **PENDING**. Do not describe this as an enabled conditional sampler
or mixed centroid in the public endpoint.

The user requested C05 on 2026-10-05 (Asia/Saigon); the
[existing phase rule](../../upgrade/implement.md#qms-c05---conditional-sobol-and-admissible-mixed-space-representatives)
requires new math review before activation. This pass follows that conservative
boundary; it does not infer activation approval from the phase request. Read the
[complete proposed contract](CONDITIONAL_GEOMETRY_REVIEW.md) and unchanged guide
[4](../../upgrade/QUANTBT_1_1_1_META_SELECTION_AND_SAMPLER_MODULE_GUIDE_V1_1_VI.md#s4) and
[5](../../upgrade/QUANTBT_1_1_1_META_SELECTION_AND_SAMPLER_MODULE_GUIDE_V1_1_VI.md#s5).

## What Was Specified And Verified

- Frozen numeric latent layout: conditional/inactive numeric coordinates are
  still allocated and consumed; categories remain independently declared inputs.
  Nested activity, fixed values, log/integer/step transforms and effective
  duplicates use the current shared parameter schema.
- Honest consumption: warm seeds/startup/actual QMC points stay distinct, including
  duplicate/PRUNED/FAIL attempts. No retries, thinning, hidden evaluations or
  power-of-two budget padding. A 128-attempt example with two seeds and one
  independent startup consumes 125 QMC points, not 128.
- Admissible mixed representative: diagnostic center projected only onto unique
  feasible, already evaluated same-IS support using current logical-block
  geometry. It is not an enum average, synthetic centroid or renamed medoid.
- Exact anchor provenance: selected point retains its own evaluation/output,
  raw IS metric and candidate identity under identical market/calendar/strategy/
  schema/seed/account/objective/metric/cutoff bindings. Wrong/stale/forward/averaged
  witnesses are rejected. No new financial evaluation is invented by projection.
- Independent calculations cover numeric/log/lattice values, mixed/activity
  distances, expected Sobol points, tie order and category vocabulary permutation.
  A hand-calculated fixture proves nearest-center projection can differ from
  the summed-distance medoid; the existing medoid policy is not changed.
- Real public preflight remains fail-closed for conditional Sobol and
  categorical/conditional/constrained centroid. Eight existing native routes
  retain original pools, selected behavior, signals, equity/report/account and
  explicit-off RNG behavior. Numeric centroid still gets its own real IS run.

## Evidence And Reproduction

Entry: `681cb00`. Source guard proves **zero** changed production files under
`src/`, Rust, root `quantbt`, contracts or package/dependency/guide bindings.
C04's exact reviewed source guard still passes. The immutable detailed guide SHA
is `adad24b16024ec5d9f3bdaf3a4098a8c60305c1fc181f1c30a0ff0f648a8170d`.

| Group | Passing members | Evidence |
|---|---:|---|
| C05-T01 | 36 | Schema, nested masks, transforms, immutable layout, valid bounds/lattices |
| C05-T02 | 29 | Sequence seeds/prefix/provenance and explicit budget/attempt ledger |
| C05-T03 | 13 | Mixed geometry, support projection, duplicates, ties and admissibility |
| C05-T04 | 20 | Exact-own IS witnesses and fail-closed binding/metric checks |
| C05-T05 | 17 | Actual public guards, eight native routes, RNG and original IS centroid |
| C05-T06 | 24 | Source lock and independent receipt scope/test-evidence validation |
| Related regression | 227 | QMS-02/03/05 samplers/history/public meta; C04 source/financial replay |

Final local JUnit: `.maturin/qms08/c05-review/spec-v3.xml` (139 tests, 11.55s)
and `affected-v1.xml` (227 tests, 58.55s). These are suite durations, **not**
WFO or sampler performance measurements. Optuna's 67 existing experimental
warnings in related regression remain visible; no warning suppression added.
Earlier exploratory logs are retained in ignored storage, not counted as passes.

```bash
env PYTHONPATH=src:. OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 \
    MKL_NUM_THREADS=1 NUMBA_NUM_THREADS=1 MPLCONFIGDIR=/tmp \
    .maturin/qms08/release-regression-v1/bin/python -m pytest -q \
    tests/meta_selection/test_c05_latent_review.py \
    tests/meta_selection/test_c05_representative_review.py \
    tests/meta_selection/test_c05_public_lock.py \
    tests/meta_selection/test_c05_gate.py
```

Independent receipt: `benchmarks/optimization/meta_selection/qms_c05_gate_receipt.json`.
It binds actual final JUnit members, source locks, review-source/doc digests and
eight source/docs/security check logs. `python -m tools.qms_c05_gate --check`
with the receipt's evidence paths re-verifies it; it cannot manufacture runtime
activation, owner approval, remote success or economic/performance superiority.

Ruff, canonical-source, generated native/product/API contract, architecture,
benchmark-entrypoint, documentation-link and tracked-secret gates PASS.
Review references/tools are outside the installed package; no wheel/native
rebuild is needed for this source-unchanged scope and none was performed.

## Remaining Decisions And Capability Ledger

1. Owner accepts/changes the proposed transforms, category/startup streams,
   unique-support weighting and total tie policy before any production change.
2. A separately approved activation must implement actual category RNG/Optuna
   adapter and selector witnesses through the shared seams, not a new engine.
   Qualify WFO/W3/R3B and exact-continuation codecs; the review reference is not
   proof of an actual installed conditional sampler or economic superiority.
3. C01 extra meta route activation and confirmed C01-D01 metadata repair still
   need approval. Carry/multi-symbol financial runtime and public meta batching
   remain outside the approved C02 transport/spec scope. C04 is an owned utility,
   not automatic full WFO/account/strategy resume.
4. Current-source remote matrix and public pair qualification remain separate.
   Prepared pair is still **1.1.2 / 0.4.3**, not published by this phase. Scientific
   study/replacement requires separate approval; no new real-alpha decay study
   was run because no methodology was activated or changed here.

There is no unfinished approved production patch in C05. These are explicit
unactivated capabilities/approval gates, not hidden completion claims. No push,
merge, tag, GitHub release or PyPI upload was performed.
