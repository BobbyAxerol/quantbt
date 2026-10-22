# M5-12 Requirement Traceability And Claim Inventory

## Scope And Authority

This is the bounded, read-only traceability sidecar for the owner-approved
M5-12 local qualification. It neither executes financial work nor certifies an
installed package. The main M5-12 runner owns final source/artifact/regression,
report reproduction, resource admission and cleanup receipts. No push, CI,
merge, tag, publication or live authority follows from this inventory.

The authoritative requirements are [Appendix B](../../upgrade/QUANTBT_MODE5_UPGRADE_V1_DIAGNOSTICS_FIRST_GUIDE_VI.md#appendix-b),
with [reporting rules](../../upgrade/QUANTBT_MODE5_UPGRADE_V1_DIAGNOSTICS_FIRST_GUIDE_VI.md#78-rules-báo-cáo-áp-dụng-cho-mọi-phase),
[product gates](../../upgrade/QUANTBT_MODE5_UPGRADE_V1_DIAGNOSTICS_FIRST_GUIDE_VI.md#79-acceptance-matrix-theo-sản-phẩm-không-chỉ-phase),
[Definition of Done](../../upgrade/QUANTBT_MODE5_UPGRADE_V1_DIAGNOSTICS_FIRST_GUIDE_VI.md#82-khi-nào-đủ-gọi-mode5-upgrade-v1-complete),
[report/handoff templates](../../upgrade/QUANTBT_MODE5_UPGRADE_V1_DIAGNOSTICS_FIRST_GUIDE_VI.md#appendix-d)
and [migration mapping](../../upgrade/QUANTBT_MODE5_UPGRADE_V1_DIAGNOSTICS_FIRST_GUIDE_VI.md#appendix-e).
Their guide hash remains pinned; no historical receipt is edited.

## Reusable Reader

[The tool](../../tools/m5_12_traceability.py) emits a JSON inventory containing
all 120 ordered requirement IDs, their original scenario/assertion text,
twelve phase report slots, source-specific receipts, ten product gate groups
and the accepted-scope/current-claim inventory. It uses only the standard
library. It does not import QuantBT, private alpha modules or old harnesses;
it does not spawn subprocesses, run tests, build, install, optimize or delete.

```bash
.venv/bin/python -B -m tools.m5_12_traceability
```

The main runner can retain stdout under its registered append-only evidence
lane. To reference its new canonical Appendix D.2 report pair, add both
`--current-report-md REPO_RELATIVE_MD` and
`--current-report-json REPO_RELATIVE_JSON`. Those arguments hash/reference the
files and validate the JSON report structure; they do not authenticate a
self-declared PASS or certify artifacts. Missing files remain missing.

The focused verification command, for the main runner to execute serially
under its resource registration, is:

```bash
.venv/bin/python -B -m pytest -q tests/test_m5_12_traceability.py -p no:cacheprovider
```

This sidecar implementation has not executed that command. Its tests cover
mapping, retained JUnit readback, immutable receipt mutations, missing evidence,
failed/skipped controls, path/byte/JSON/XML safety, private parameter suffix
redaction, report schema and unchanged original bytes. They are cold reader
tests, not 120 new financial experiments.

### Interpretation Of States

- `HISTORICAL_ASSERTIONS_RECORDED`: a named assertion actually occurs in the
  pinned historical JUnit, the pinned command has integer exit code zero, and
  the retained suite has no failure/error/skip. Its scope and source remain
  historical. It is not a claim that the requirement's broadest economic
  interpretation or a new artifact is certified.
- `RETAINED_REANALYSIS_NOT_NEW_EXECUTION`: the named HMA transfer observation
  for M5T-077 is retained under its original hash. It is not invented as a new
  pytest case or independent experiment.
- `INSUFFICIENT_RECORDED_ASSERTIONS`: missing command/XML or no applicable
  assertion; an unrelated successful test count cannot fill this gap.
- `MAIN_CURRENT_QUALIFICATION_REQUIRED`: M5T-111..120 remain the main runner's
  current-source gates. Historical controls are dependencies, not substitute
  final receipts.

The tool deliberately returns `all_120_pass=false` and `package_qualified=false`:
it issues neither certificate. These fields do not mean all requirements fail;
the final handoff must reconcile the separate axes using actual main receipts.
It never infers independent market validation from a unit test, local installed
proof, reused account path or report reconstruction.

Receipt XML and command hashes are fixed in the catalog. A byte change raises
an error; the reader does not update the pin to make it pass. Private parameter
suffixes, receipt payloads, logs and alpha source are not exported. Only named
assertions, paths, hashes, observed counts and published scope are returned.
Missing private receipts produce visible insufficiency in a public checkout.

## Twelve Reports And Source Boundaries

Each historical phase pairs the Markdown below with its published JSON seal in
`docs/mode5/evidence/`. The generated inventory includes both identities and
the exact private XML/command reference. These heterogeneous original seals
are historical summaries, not retroactively rewritten canonical D.2 reports.

| Phase | Markdown Report | Historical JSON | Recorded Scope And Qualification Boundary |
|---|---|---|---|
| M5-01 | [Baseline](M5_01_BASELINE_REPORT.md) | `m5-01.json` | Source/helper/artifact checks; original pending ZIP disposition preserved; [owner extracted-member acceptance](evidence/m5-01-exit-review.json) is separate |
| M5-02 | [Admission](M5_02_ADMISSION_REPORT.md) | `m5-02.json` | Five actual alpha bindings on the registered short reviewed window; not long-horizon economic transfer |
| M5-03 | [Statistics](M5_03_STATISTICS_REPORT.md) | `m5-03.json` | Numerical/measurement oracles and actual synthetic streams, not market superiority |
| M5-04 | [Reuse](M5_04_REUSE_REPORT.md) | `m5-04-final.json` | Final attempt-02 planner/cache/audit qualification; earlier attempt retained |
| M5-05 | [Environments](M5_05_ENVIRONMENT_REPORT.md) | `m5-05.json` | Calendar, attribution, maturity and information rights |
| M5-06 | [Geometry](M5_06_GEOMETRY_REPORT.md) | `m5-06.json` | Feasible geometry/local probes; global/whole-space coverage remains explicitly bounded |
| M5-07 | [Selection](M5_07_SELECTION_REPORT.md) | `m5-07.json` | Versioned objectives/selectors and mathematical reference controls |
| M5-08 | [Batteries](M5_08_BATTERY_REPORT.md) | `m5-08.json` | Targeted development diagnostics; later research has separate receipts |
| M5-09 | [Governance](M5_09_DOSSIER_REPORT.md) | `m5-09.json` | Dossier/plan/override governance; no universal automatic recipe router |
| M5-10 | [Public runtime](M5_10_PUBLIC_RUNTIME_REPORT.md) | `m5-10.json` | Actual historical public runtime and installed pair; not current ACC-repaired artifacts |
| M5-11 | [Original economics](M5_11_ECONOMIC_REPORT.md) and [accepted scope ledger](M5_11_RESEARCH_COVERAGE_DISPOSITION.md) | `m5-11.json` plus `m5-11-parent-disposition.json` | Original finite pilot and later registered research are distinct; parent accepted with retained limitations |
| M5-12 | Main runner's new local qualification Markdown | Main runner's new canonical D.2 JSON | Must be supplied from exact current source/artifacts; this sidecar does not fill its execution fields |

The [accepted parent disposition](evidence/m5-11-parent-disposition.json) is
`ACCEPT_COMPLETED_REGISTERED_SCOPES_WITH_LIMITATIONS`, not a waiver of final
package correctness. The old original M5-11 pilot does not describe all later
studies; the current coverage ledger and linked terminal receipts do.

## Requirement-To-Assertion Index

For IDs 001..090, except 077, actual retained test names embed their ID as
`test_m5t_001...` or `test_M5T081...`; the tool resolves the complete matching
names rather than treating a file-level test count as proof. The descriptions
below identify the assertion, not an unconditional PASS. Requirements marked
real-data also require their retained observation; a synthetic oracle alone
does not satisfy a real-alpha generalization claim.

| ID | Concrete Assertion Or Observation |
|---|---|
| M5T-001 | Archive traversal/link/collision rejection and manifest-before-copy |
| M5T-002 | Original bytes, independent copies, append-only receipts and observed archive presence |
| M5T-003 | Exact prose/JSON errata linkage; nonfinite/ambiguous records rejected |
| M5T-004 | Actual shared sampler resolution and independent fallback telemetry |
| M5T-005 | Exact scored duration and warmup, not a nominal full year |
| M5T-006 | Separate decisions for identical parameters; no extra independent execution |
| M5T-007 | Same version cannot override changed source/native/clock/economics identity |
| M5T-008 | Reviewed/full-set presets cannot regain untouched rights by renaming |
| M5T-009 | Missing return/campaign inputs cannot manufacture PSR/tail/support |
| M5T-010 | Reuse actual source bindings; proposed APIs not treated as implemented |
| M5T-011 | Private admission assertion: integer/effective-config collision |
| M5T-012 | Private admission assertion: SC long-flat, volume fallback and opposite-signal behavior |
| M5T-013 | Private admission assertion: four HMA modes, aliases and unknown rejection |
| M5T-014 | Private admission assertion: active lower clamp and ignored knobs |
| M5T-015 | Private source/actual-engine assertions: HTF prefix and matched score calendar |
| M5T-016 | Conditional time stop and actual amendment after observation |
| M5T-017 | Actual partial ladder and remaining-quantity fractions |
| M5T-018 | Remaining protective quantity, dust feasibility and flat-only cooldown |
| M5T-019 | Actual 2,000-quote notional one-way fee and MTM ledger |
| M5T-020 | Approximation/zero-fill/unsupported route cannot gain execution authority |
| M5T-021 | PSR uses original-period Sharpe; explicit annual conversion |
| M5T-022 | Ordinary/excess kurtosis conversion on the same series |
| M5T-023 | Typed undefined/invalid variance, sample, units and moment guards |
| M5T-024 | Actual account observation N, not fills/campaign counts |
| M5T-025 | HAC independent matrix oracle and same-marginal dependence controls |
| M5T-026 | First actual fee and pre-block watermark preserved by partition |
| M5T-027 | Actual campaign PF differs from partial-fill proxy |
| M5T-028 | Fractional-mass lower-tail mean, not interpolated quantile |
| M5T-029 | Unequal elapsed horizons, compounding, UTC boundaries and positive MDD |
| M5T-030 | Raw metric and penalized objective remain separate channels |
| M5T-031 | Cost/funding/instrument change invalidates execution; actual changed-cost replay |
| M5T-032 | Code/effective-parameter/market identity, not display name |
| M5T-033 | Clock/account/initial-state/warmup/terminal identity invalidation |
| M5T-034 | Objective-only revision reuses execution without rewriting adaptive history |
| M5T-035 | Reference revision changes selection/rescore, not old execution |
| M5T-036 | Cached holdout or later-mature data cannot bypass current permissions |
| M5T-037 | Every attempted trial state retained; effective IDs and execution counts separate |
| M5T-038 | Runtime FAIL cannot become COMPLETE sentinel or cached bad economics |
| M5T-039 | Prepared Rust/Python accounting and explicit richer-input insufficiency |
| M5T-040 | Backpressure/flush/cancel/crash/chunk/byte-budget/fsync controls |
| M5T-041 | Future mutations preserve past fitted thresholds and actual account prefix |
| M5T-042 | Retrospective labels do not overwrite original decision vintages |
| M5T-043 | Inner validation changes cannot alter inner-train transforms |
| M5T-044 | Continuous account marks, no price splicing across disjoint states |
| M5T-045 | Actual reset-flat and carried accounts have distinct contracts |
| M5T-046 | Overlapping state families do not double statistical evidence mass |
| M5T-047 | Rare/no-trade/missing/adverse cells retained with support |
| M5T-048 | Matched readiness/calendar control plus retained real readiness review |
| M5T-049 | Maturity, discovery, recipe clock and permitted lineage all required |
| M5T-050 | Reviewed stress dates cannot become independent holdout |
| M5T-051 | Fixed/inactive dimensions do not change active distances |
| M5T-052 | Schema scale fixed before sampled outliers |
| M5T-053 | Feasible log/integer/category/boundary geometry |
| M5T-054 | Coupled manifold rejects invalid points without silent sorting |
| M5T-055 | Effective probe collisions retain raw rows and distinct-count semantics |
| M5T-056 | Arbitrary panels rejected by Saltelli; actual structured work budget |
| M5T-057 | Constant output is undefined sensitivity, not dead parameters |
| M5T-058 | Multi-metric activity retained plus actual retained parameter-activity matrix |
| M5T-059 | Schema transverse probe catches covariance blind spot |
| M5T-060 | Bad feasible neighbors retained; insufficient probes cannot certify basin |
| M5T-061 | Average-regret algebra versus floor-plus-mean minus common constant |
| M5T-062 | Moving reference blocked; full completed panel revision explicit |
| M5T-063 | True maximum regret and minimum utility select differently |
| M5T-064 | Quantile versus true lower-tail mass, including fractional atom |
| M5T-065 | Gamma-one objective is minimum over center and observed neighbors |
| M5T-066 | Absolute downside/frozen scale invariant to common utility shift |
| M5T-067 | Same-channel composite, explicit units and no second fee deduction |
| M5T-068 | Fixed Pareto directions/references, null/zero-range/outlier behavior |
| M5T-069 | Pareto post-selection does not relabel candidate generation NSGA-II |
| M5T-070 | Medoid/nearest mean/unevaluated centroid distinction |
| M5T-071 | Same full panel compares selectors, not sampler skill |
| M5T-072 | Retained sampler work/fallback bill and comparison observation |
| M5T-073 | Same-front hypervolume cannot select a compromise winner |
| M5T-074 | Actual positive broad-region, null and bad QuantBT controls |
| M5T-075 | Frozen train risk scale plus actual risk controls; dynamic resimulation required |
| M5T-076 | Alpha label does not enter recommendation mathematics |
| M5T-077 | Hash-pinned `analysis-v1/hma_targeted_transfer.json`, retained T1/T2 reanalysis; no invented pytest ID |
| M5T-078 | Changed cohort/target cannot become comparable ablation |
| M5T-079 | New post-review recipe needs new registration; failed attempts retained |
| M5T-080 | One short seed cannot support universal superiority |
| M5T-081 | Unsealed/missing/deferred dossier and separate legacy route |
| M5T-082 | Human choice cannot certify technically invalid content |
| M5T-083 | Stable best candidate not excluded by low global rank correlation |
| M5T-084 | Sparse/negative findings distinguished from technical invalidity |
| M5T-085 | Missing adverse rows and changed registered roster rejected |
| M5T-086 | Null/reference/unit/rescaling checks, no neutral radar imputation |
| M5T-087 | Override preserves history, permissions, scope and budget |
| M5T-088 | Unqualified automatic router denied; explicit advisory retained |
| M5T-089 | Dependency-aware partial reuse after changed source/economics/roles |
| M5T-090 | Post-hoc profiling/backdated history denied diagnostics-first label |
| M5T-091 | Named legacy Modes 1..5/native-prepared regressions in `regression-final-08`, plus opt-in boundary in `mode5-final-14` |
| M5T-092 | `test_actual_inherited_sampler_and_no_meta` |
| M5T-093 | `test_tpe_conditional_categorical_actual_effective_rows` |
| M5T-094 | `test_cma_categorical_reject_and_explicit_fallback` |
| M5T-095 | `test_sobol_actual_sequence_projection_and_collision_ledger` |
| M5T-096 | `test_ask_tell_schedule_deterministic_and_distinct`; prepared/fresh score parity |
| M5T-097 | `test_old_objective_score_is_never_imported` |
| M5T-098 | Actual public selection/replay and explicit adaptive researcher choice |
| M5T-099 | `test_public_lifecycle_uses_original_fills_not_proxy` |
| M5T-100 | Actual execution-window selection/audit plus retained five-alpha certification |
| M5T-101 | Full-sample parent cannot acquire independent child validation claim |
| M5T-102 | Reviewed 2024 cannot become clean holdout by new label |
| M5T-103 | Future/immature prefix rejection; unit prefix proof is not whole-procedure qualification; broad deferred scope stays explicit |
| M5T-104 | Cached reviewed data cannot become post-freeze observation; independent claim remains pending |
| M5T-105 | Account-bps turnover/allocation MDE oracle |
| M5T-106 | Lower IS alone cannot pass joint forward-quality gate |
| M5T-107 | PF zero-denominator policy and matched-vector absolute decay decomposition |
| M5T-108 | Positive/harmful controls, intervals crossing hurdle, no retune |
| M5T-109 | Actual equity-dependent fee stress and retained original-engine stress record |
| M5T-110 | Missing ledger/origin support cannot be pooled away; accepted per-alpha scope ledger remains binding |
| M5T-111 | Main: final matched public/prepared cold/warm/output cost or explicitly bounded claim; old kernel timing is insufficient |
| M5T-112 | Main: final work/support bill with proposals, executions, effective IDs and dependent observations separated |
| M5T-113 | Main: fresh-process reconstruction and exact numeric/hash agreement |
| M5T-114 | Main: canonical metric/component/override and decision identity reconciliation |
| M5T-115 | Main: exact final wheel/sdist installed examples/resources/native provenance outside checkout |
| M5T-116 | Main: narrowed-rights reload on current report/cache/pack paths |
| M5T-117 | Main: current affected crash/cancel/partial/flush/stale-handle regression |
| M5T-118 | Main: current source/branch/private-input/artifact integrity and privacy, no release authority inferred |
| M5T-119 | New canonical report-schema negative controls in this sidecar; main must execute them and review final report substance |
| M5T-120 | This complete mapping plus main final source/claim/report reconciliation; no blanket 120-PASS from test totals |

## Final Claim And Coverage Inventory

| Capability / Finding | Evidence And Allowed Meaning | Limit Retained |
|---|---|---|
| Diagnostic admission and five-axis profiling | Original admission and [accepted research ledger](M5_11_RESEARCH_COVERAGE_DISPOSITION.md), raw-derived matrices, explicit status/support | Finite panel/local coverage is not global structured sensitivity on all alphas; overlap is not independent evidence |
| Versioned objective/selector kernels | [Selection report](M5_07_SELECTION_REPORT.md) and canonical oracle/units/reference controls | A fixed dict's annual/state robustness is finite-scope; floor utility is not raw return; advisory choice is not automatic optimal routing |
| Formal research on original/additional alphas | [Remaining-study closeout](M5_11_9_RESEARCH_STATUS.md) and accepted parent scope | HMA had no eligible formal cohort in its tested mandate. Do not call an unexecuted study a PASS or infer no possible edge |
| Independent forward validation | Data-role/maturity/prefix controls and recorded bounded forward evidence | Reviewed development and reused 2024 remain reviewed; whole learned-procedure independent qualification is not supplied by renaming data |
| Mode 4 diagnostics/meta/reporting | [Shared reporting coverage](../diagnostics/REPORTING_COVERAGE_AND_HANDOFF.md), original Mode 4/ML receipts | R/Q, IS contribution, paired masks and policy consistency are separate; positive decay change alone is not improved forward quality |
| Cross-mode research | [Chronological disposition](M5_11_13_CHRONOLOGICAL_DISPOSITION_REPORT.md) | KEEP_BASELINE remains; owner-approved deferred long whole-procedure experiments are NOT_EVALUATED, not negative proof or PASS |
| Cross-mode opt-in mechanics and winner explanation | [M5-11.15](../diagnostics/M5_11_15_IMPLEMENTATION_REPORT.md): explicit COMPLETE donors, source/rights checks, destination rescoring, exact winner/baseline/probe/state joins | Researcher chooses use. Synthetic execution proves operational mechanics, not universal economic superiority or automatic donor selection |
| Account and metrics corrections | [ACC-01](../portfolio_review/ACC01_REPORT.md), current-capability migration and reducer evidence | Current finance changed relative to old QMS. Gross-cross/netting and conservative OHLC liquidation are not isolated/hedge/venue-exact simulation |
| Current package/native artifacts | Main M5-12 exact source and installed receipts | Same version alone, historical source-only proof or old installed wheels cannot qualify current artifacts |
| Remote/public pair | Separate future matrix/public consumer receipts | Local CPython 3.12 proof does not certify Ubuntu 22.04/24.04 x CPython 3.11..3.13, public PyPI availability or release authority |

Appendix E's migration remains visible in this inventory: original/current
source mapping (001..020), financial stream and units (021..030), shared planner
(031..040), dual roles/overlap (041..050), effective geometry and feasible probes
(051..060), errata/versioned formulas/Pareto (061..070), five controlled
batteries (071..080), dossier/advisory/seal (081..090), registry/public runtime
(091..100), bounded calibration/economics (101..110), and final reproducibility
(111..120). Eight-chapter heritage does not authorize silently retaining a
mathematical naming error or upgrading discovery to untouched confirmation.

## Main Runner Completion Checklist

1. Execute the focused reader/schema tests under its registered serial lane;
   retain actual command, XML and exit status. This document is not that receipt.
2. Generate the full 120-row JSON from the retained local files, including gaps;
   missing private inputs must stay visible rather than filling from totals.
3. Bind M5T-111..120 to final operations/regression/reproduction/installed proofs,
   the final source and exact package/native identities. Reuse compatible
   historical evidence explicitly; do not rerun completed optimizers.
4. Supply the twelfth report pair. The schema gate applies to new canonical
   reports, not a demand to rewrite old published/private summary formats.
5. Reconcile all ten product groups from guide 7.9 and the accepted per-alpha
   ledger. Distinguish software, research scope, alpha coverage and independence.
6. Retain failed receipts, approved exclusions, immutable originals and all
   no-publish boundaries. Main owns the terminal resource/cleanup receipt.

No new financial gap is claimed discovered by this reader alone. The open
items here are current-qualification evidence owned by main, or already
accepted research limits. An actual hash/receipt/schema discrepancy must be
investigated; it must not be repaired by replacing historical pins silently.
