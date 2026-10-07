# PRE-E06-04 Execution Report

## Conclusion

**COMPLETE_LOCAL_APPROVED_SCOPE**: conditional numeric Sobol, admissible
evaluated-support representatives and owned exact continuation are implemented
as explicit policies. Old defaults, accounting, objective formulas and Ridge
remain unchanged. This is a source/software qualification, not economic or
installed-final-source/public certification. No push, workflow, merge, tag or
publication was performed. Entry `ba61e63`; implementation commit `efe4359`.

Read [the runtime contract](CONDITIONAL_POLICIES.md),
[unified phase](../../upgrade/implement.md#qms-pre-e06-04),
[approved independent review](CONDITIONAL_GEOMETRY_REVIEW.md) and original
[guide section 4](../../upgrade/QUANTBT_1_1_1_META_SELECTION_AND_SAMPLER_MODULE_GUIDE_V1_1_VI.md#s4).

## Implementation

- Shared `SamplerConfig.sobol_policy`, existing Sobol factory/study, two separate
  startup/category streams and frozen numeric dimensions. Full numeric points
  are charged at ask, then masked. Terminal outcomes never reallocate points.
- Shared `flat_selector="feasible_support_projection_v1"`, retaining original
  cluster scores. Geometry has unique effective-point weights and total ties.
  Only an existing feasible candidate with its own exact IS witness executes.
- Own evaluation digest binds the complete observation, params, schema, strategy,
  window/cutoff, market/calendar, account/metric/objective and execution seed.
  No synthetic anchor, cluster-average measurement or auxiliary financial run.
- Existing C04 journal reconstructs warm queues, masks, categories, QMC index,
  reports, constraints and ordered terminal tells, including batch ask boundaries.
  Fresh-process and actual atomic-file resume match subsequent proposals exactly.
- Thirteen reviewed runtime files, two focused new modules; no Rust/accounting
  kernel, Ridge, parameter schema or new endpoint implementation. Exact source
  normalization preserves old guide/receipts rather than exempting whole files.

## Tests And Scope

**104 new-policy PASS**, **590 distinct old-regression PASS**, and **7 docs/example/
receipt-gate PASS**: **701 distinct scoped checks**, no skipped required cells.
Receipts overlap by identity; duplicate runs are not added to that total.

The policy corpus covers actual Optuna category/startup RNG and SciPy prefixes;
independent C05 numeric transforms; all-inactive coordinates; warm prefix;
failed/pruned/infeasible/duplicate attempts; batch ask/reverse-tell order; explicit
seed and settings guards; own-observation corruption, future/foreign/missing
witnesses; hand centers, vocabulary permutation and duplicate neutrality.

Actual public calls cover all eight existing scalar sampler mode/schedule cells;
five scalar Mode 4 projection targets; Mode 5 full-IS projection; sequential W3
with inprocess/process/shadow mixed branches; private global R3B sampler batching;
unsupported batch and noncausal/full-sample W3 projection rejected before
financial strategy, including omitted sampler configuration. Prepared Rust
and original scalar projection paths preserve candidates, selection and account
under their existing contract. Legacy pct-equity has no cost-column schema:
compare common equity/returns/positions directly, do not invent missing columns.
Existing repaired-native tests independently cover its cost/quantity accounting.

Old regression covers four recipes, actual W3 process/meta/batch/fixed replay,
C04 continuation/security, legacy medoid and numeric-centroid acquisition,
eight default route baselines, public meta and independent C05 review references.
Future-data mutation leaves earlier selection/proposal/witnesses unchanged.
This phase does not replace PRE02/PRE03's separate matured fit/rank corpus.

An initial regression chose archived QMS06 native `0.4.3.dev2` and **12 tests
failed** on the required G01 `legacy_zero_base_v1` capability. The unchanged
46-test QMS06 shard then **passed** with the retained qualified `0.4.3` provider.
All twelve exact failed identities have passing reruns. Both XMLs are retained;
no production guard was waived, tolerance relaxed or failed receipt overwritten.
Exploratory policy/test-fixture failures are also retained in the ignored lane.

Ruff passes for the new modules/tests/tools and reviewed supporting modules.
The five existing `E731` lambda-style findings in `walkforward.py` also occur
at entry `ba61e63`; they are not introduced or refactored by this policy phase.
Unused imports introduced by this phase are removed. No new lint suppression.

## Measured Software Cost

Three fresh-process observations per row, one numeric thread, seed 731, same
two-dimensional numeric schema and budget. Different policies intentionally
have different candidates; this is **not** a same-sequence speedup or economic
comparison. Startup includes Sobol initialization; do not compare proposal-only
time and hide startup. Times are medians in ms; RSS is process peak in MiB.

| Policy | Attempts | Prepare | Ask/tell | Encode midpoint checkpoint | Restore midpoint | Peak RSS |
|---|---:|---:|---:|---:|---:|---:|
| Legacy Sobol | 128 | 13.9 | 1129.6 | 22.3 | 141.9 | 213.5 |
| Conditional numeric V1 | 128 | 889.8 | 181.3 | 31.9 | 141.6 | 214.0 |
| Legacy Sobol | 600 | 13.5 | 1916.8 | 57.0 | 638.7 | 220.8 |
| Conditional numeric V1 | 600 | 956.2 | 862.5 | 168.5 | 573.2 | 225.5 |

New provenance adds checkpoint bytes: **69,343 -> 93,811** at 64 completed
attempts; **317,580 -> 431,811** at 300. RSS difference is about **+0.6 / +4.7 MiB**
for these runs. It is not per-fold model cost or a retention plateau certificate.
Restore redoes proposal work, with **zero** financial evaluations. QMC state and
category/mask provenance deliberately cost memory; they are not silently dropped.
Three repeats do not qualify p95 or whole-WFO +3%/+5% budgets. Whole-workload
profiling and controlled optimization remain PRE-E06-05. No decay gain is claimed.

## Evidence And Remaining Gates

- [Exact reviewed source](../../benchmarks/optimization/meta_selection/qms_pre_e06_04_reviewed_source.json).
- [Source-bound closure](../../benchmarks/optimization/meta_selection/qms_pre_e06_04_closure.json).
- [Measured cost](../../benchmarks/optimization/meta_selection/qms_pre_e06_04_cost.json).
- [Cleanup receipt](../maintenance/QMS_PRE_E06_04_CLEANUP.md).

Conditional Sobol does not activate a new meta route. Projection is initially
limited to five scalar Mode 4 causal/Mode 5 full-IS and sequential/process W3
Mode 4 causal own-window support. Other projection modes/domains, proxy/multiple
windows and R3B/fixed-matrix projection reject explicitly. Legacy `centroid`
guards remain. No arbitrary constrained optimizer or public meta batch claim.

Final-source wheel/sdist proof remains **PRE-E06-06**; later remote/public proof
needs separate approval. No automatic full-WFO/account recovery, W3 continuous
carry/shared multi-symbol, extra meta mode/domain or economic default promotion.
Those boundaries are not incomplete implementations hidden by this receipt.
