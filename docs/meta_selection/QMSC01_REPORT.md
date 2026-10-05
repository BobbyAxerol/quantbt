# QMS-C01: Methodology Review And Compatibility Lock

## Disposition

Date: 2026-10-05 (Asia/Saigon). Branch: `feat/meta-selection-samplers`.
Owner choice: **spec and tests first; activation separately**.
Review implementation entry: `b5563de495263d4b5fb8a9953e727c25c90cc441`.
The generated route audit binds source `0d5a24788c32a0031d419d85633292d2fcaa89ec`;
the subsequent global-mutation regression and documentation are separate changes.

This phase reviews additional methods; it does **not** activate additional
meta combinations. Production capability remains Mode 4 / per_fold_causal
on its qualified scalar and sequential/reset-flat W3 lanes. Unsupported
shadow/active combinations still fail before optimization or financial work.
No source under `src/` or `rust/`, dependency, release version, account arithmetic,
Ridge target, sampler, original guide or alpha notebook was changed.

Read the [approved C01 plan](../../upgrade/implement.md#qms-c01---additional-meta-modes-and-schedules)
and [versioned methodology amendment](ADDITIONAL_METHODS_REVIEW.md).
The detailed guide remains authoritative:
[information boundary](../../upgrade/QUANTBT_1_1_1_META_SELECTION_AND_SAMPLER_MODULE_GUIDE_V1_1_VI.md#s3),
[mathematics](../../upgrade/QUANTBT_1_1_1_META_SELECTION_AND_SAMPLER_MODULE_GUIDE_V1_1_VI.md#s5),
[selection](../../upgrade/QUANTBT_1_1_1_META_SELECTION_AND_SAMPLER_MODULE_GUIDE_V1_1_VI.md#s7),
[integration](../../upgrade/QUANTBT_1_1_1_META_SELECTION_AND_SAMPLER_MODULE_GUIDE_V1_1_VI.md#s8).

## Actual Route Audit

The [structured receipt](../../benchmarks/optimization/meta_selection/qms_c01_contract_review.json)
traces actual public endpoint execution with delegated spies. Fixture:
547 deterministic daily bars, one symbol, six attempted trials per study,
seed 731 and default native selectors across five modes.
There are **eight native mode/schedule combinations**, not eight new meta modes.
No mocked selector, fabricated objective or substituted financial result is used.

Counts below describe **one arm**. A separate explicit-meta-off arm must match
the omitted arm, including full search records, native selection, accepted
positions, equity, returns, account contract and Python/NumPy RNG state.

| Mode / schedule | Studies | Attempted rows | Eligible rows | Shortlist rows | Off / RNG |
|---|---:|---:|---:|---:|---|
| 1 / global | 1 | 6 | 5 | 3 | Exact |
| 1 / per_fold_decay | 2 | 12 | 10 | 6 | Exact |
| 1 / per_fold_causal | 2 | 12 | 10 | 6 | Exact |
| 2 / global | 1 | 6 | 5 | 3 | Exact |
| 3 / global | 1 | 6 | 5 | 4 | Exact |
| 4 / global | 1 | 6 | 5 | 4 | Exact |
| 4 / per_fold_causal | 2 | 12 | 10 | 8 | Exact |
| 5 / global | 1 | 6 | 5 | 4 | Exact |

Global routes use one study and one final parameter set, not independent
fold decisions. Mode 5 has one full-sample fold with equal train/test bounds;
that replay is calibration, not forward validation. The default Mode 1/2/3
final selector is robust_decay, whose OOS stage is distinct from adaptive search.
Optional selectors require their own information-role classification.

Nested Mode 1 makes two outer-fold decisions. Each study selects using four
inner validation folds entirely within its outer IS. Mutating only the outer
OOS preserves the first search pool and final inner-decay anchor. Global Mode 4
has later train data inside the earlier test period: changing those observations
changes the shared IS pool, while the first train-window metrics stay identical.
IS-only ranking of a global study is not a chronological per-fold certificate.

## Tests And Exit Gates

The C01 suite adds eight-route native/off parity, nested and global mutation,
14 unsupported shadow/active preflights, default-SBB final-selector tracing,
independent decay/SBB formula checks and negative receipt verification.
Existing regression suites exercise original-result raw metric validity,
centroid own-witness capture, full-pool lower-IS active winners, actual stitched
accounting, future/unavailable labels, family isolation, prepared/reference/Rust
parity and portable decisions. Native scalar trace fields alone are not a
new MetricObservation validity certificate.

Final regression: **184 PASS**, zero failures/errors/skips, 75.76 s, including
**48 C01 checks** and 136 existing/affected checks. Four warnings are the
declared Optuna experimental multivariate/group warnings, not missing native
capabilities. The additional global Mode 4 future-train mutation regression is
committed as `da98a43`. The earlier 183-check run is superseded, not summed.
Final local JUnit SHA-256:
`3f1fa43fce64be5d75f8bc21b4b4b4ec16417cb2e5fbae66a69765d36cc44634`.

```bash
export PYTHONPATH=src:.
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1
export MPLCONFIGDIR=/tmp
export QMS04_NATIVE_EXTENSION="$PWD/.maturin/qms04/_quantbt_native.cpython-312-x86_64-linux-gnu.so"
PY=.maturin/qms08/release-regression-v1/bin/python
"$PY" -m pytest -q \
  tests/meta_selection/test_c01_contract_review.py \
  tests/meta_selection/test_qms03_engine.py \
  tests/meta_selection/test_qms05_public.py \
  tests/meta_selection/test_qms06_prepared.py \
  tests/meta_selection/test_release_gaps.py \
  --junitxml=.maturin/qms08/c01-review/regression-v2.xml
"$PY" -m tools.qms_c01_audit \
  --output .maturin/qms08/c01-review/contract-review-fresh.json
```

Sealed output paths cannot be overwritten. The new source can generate a fresh
receipt with its own source SHA; it must not rewrite historical audit bytes.
Stored public trace SHA-256:
`139391edc301f948efa932fc8c75113f849fb4b8453ccf8070b66411158f70b0`.
Original guide SHA-256:
`adad24b16024ec5d9f3bdaf3a4098a8c60305c1fc181f1c30a0ff0f648a8170d`.

| Gate | Required evidence | Disposition |
|---|---|---|
| C01-T01 | Eight real routes; source symbols/hash; proposed map is not capability | PASS |
| C01-T02 | Exact omitted/off full pools, native winners, account arrays and RNG | PASS |
| C01-T03 | Nested windows within outer IS; outer-OOS mutation invariance | PASS |
| C01-T04 | Unsupported meta fails before optimization/scoring; no invented schedules | PASS |
| C01-T05 | Global/same-sample provenance; actual default-SBB OOS selection | PASS; C01-D01 recorded |
| C01-T06 | Existing active/shadow/raw-validity/prepared/label/account regressions | PASS |
| C01-T07 | Native formulas independently reconcile; no raw-Sharpe substitution | PASS |
| C01-T08 | Protected source/guide, synthetic evidence and docs/secret checks | PASS |
| Additional meta activation | Owner-approved target/cohort, actual implementation and artifact proof | NOT AUTHORIZED |

## Confirmed Finding: C01-D01

**Mode 2 / global, default robust_decay:** adaptive Optuna uses synthetic IS
return proxies, but its final shortlisted candidates are scored/ranked with
real OOS. The existing top-level `oos_used_for_selection` flag says false.
The trace records actual selection stage `oos_candidate_selection`; modifying
only the final forward period preserves the full IS pool but changes the final
candidate-rerank metrics. This is a confirmed metadata discrepancy, not evidence
that the underlying native algorithm changed in C01.

The spec/test approval does not authorize a financial/runtime patch. The gap
is recorded, **not fixed or marked complete**. A separately approved metadata-
only correction must classify the actual selector and pass exact pool/params/
objective/RNG/account parity. Do not mark all Mode 2 selectors OOS-using by name.
This must be resolved before a later Mode 2 meta activation; users must not
read that legacy false flag as proof of an untouched final-selection OOS.

## Activation Choices And Remaining Work

The first proposed additional causal route is **Mode 1 / per_fold_causal**:
preserve the exact inner-decay native anchor; generate original **full outer-IS**
witnesses for every eligible candidate; use unchanged Ridge on a separate
versioned cohort; seal before genuine outer-forward observations. Raw outer IS
and mean inner IS are not interchangeable. This target/cohort choice is a
proposal for owner approval, not new implementation or an economic result.

Current outer-decay and global modes need explicitly selection-adjusted or
retrospective task contracts. Synthetic bootstrap output cannot become a real
forward label; global component folds cannot be backdated into independent
causal origins. Mode 5 would need genuine later forward observations.
All these combinations remain closed.

C02-C05 remain separately planned: W3 process/batch/deadline/carry/multi-symbol,
four-recipe cross-scheduler qualification, persisted exact RNG continuation,
Sobol conditional and mixed-space centroid contracts. There is no forgotten
implementation hidden by an enabled flag. Registered scientific study
replacement, remote/public artifact qualification and publication need their
own approvals.

## Cost And Release Interpretation

There is **no new production hot path**, no new Rust build and no extra meta
evaluation cost added by this phase. Regression duration is test time, not a
WFO speed/RSS benchmark. Nested full-pool outer-IS witnesses would have genuine
extra financial-evaluation cost; measure it if that activation is approved.

The earlier Delta/Gradient RSI ETH study and all historical seals are untouched,
not rerun or retuned. This synthetic review estimates neither new alpha edge
nor improved decay. Existing remote 6/6 qualification remains evidence for its
recorded source, not a consumer proof for unimplemented additional methods.
Prepared release pair remains 1.1.2 / 0.4.3; no merge, tag, release or PyPI upload
is performed in C01.
