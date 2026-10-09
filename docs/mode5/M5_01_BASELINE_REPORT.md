# M5-01 - Baseline, Errata, Isolation And Research Contract Freeze

**Current disposition (2026-10-09):** M5-01 COMPLETE_LOCAL_BASELINE; reviewed
exit PASS_OWNER_DISPOSITION. The owner confirmed the guide's ZIP-derived
provenance and accepted following the guide/hash-verified extracted inputs.
Read the [exit review](M5_01_EXIT_REVIEW.md) and
[new seal](evidence/m5-01-exit-review.json). The attempt-04 report below retains
its original historical input-pending disposition; original receipts are not
rewritten. M5-02 remains NOT_STARTED pending its separate phase approval.

## 1. Objective And Scope

Owner approved M5-01 on 2026-10-09. Follow the
[phase plan](../../upgrade/implement.md#mode5-m5-01),
[detailed work packages](../../upgrade/QUANTBT_MODE5_UPGRADE_V1_DIAGNOSTICS_FIRST_GUIDE_VI.md#phase-m5-01--baseline-errata-và-research-contract-freeze)
and [M5T-001..010](../../upgrade/QUANTBT_MODE5_UPGRADE_V1_DIAGNOSTICS_FIRST_GUIDE_VI.md#m5-01--baseline-evidence-và-isolation).
This is a source/evidence baseline, not a new calibration or market benchmark.
No financial source, alpha original, metric formula, endpoint default, RNG
schedule or selection method changed. No push, build or publication occurred.

**Technical checks:** TECHNICALLY_VALID_LOCAL. **Scientific status:**
DESCRIPTIVE_ONLY. **Whole-phase exit:** INPUT_EXIT_PENDING, because the original
two ZIPs are unavailable at the registered paths and extracted-member scope
has not yet received a separate owner disposition.

## 2. Identity And Contracts

New branch: `feat/mode5-diagnostics-first`, preserving the current QMS/MET
source at planning parent `bb0072a`, rather than replacing it with stale dev.
Implementation commits: `d3645c3`, `14dd9b8`. Attempt-04 ran before the second
commit; its parent SHA, dirty state and exact phase-source hashes are retained.
The tested code was committed without alteration.

Guide SHA-256:
`661a2a3d83eed2b2592bfb98e3b4f8e3aa34bcd9740ec6b50c812f73753b99fe`.
The original Spec, three master JSON files, four main alpha sources and golden
helper match Appendix A's exact bytes/hashes. All 24 supplied Python files were
AST parsed, not imported. The existing private RSI source completes the roster.
Four main alpha files also match the historical lab's main files. This does
not prove helper, clock, sizing or financial execution equivalence.

Source imports resolve to `src/quantbt`; loaded core/native are **1.1.2 / 0.4.3**.
The native extension SHA-256 is
`ae43be6e2187e57fcd6a8e8f59e0689172ca24ca5efed27651894c1e7ab1b56a`.
Python 3.12.13, Optuna 4.8.0, dependency locks, import origins and Rust toolchain
versions are pinned privately. Under source imports, distribution metadata
reports core **1.1.1** while the loaded module reports **1.1.2**. Neither the
source egg-info nor the older primary environment was rewritten. Actual module
and binary hashes, not version strings alone, control this receipt's identity.
This is not a new installed-wheel certificate.

## 3. Changes And Reuse

| Work package | Implemented disposition |
|---|---|
| M501.01 | Exact identities, protected before/after hashes, safe archive inspection and isolated non-hardlinked editable copies; original ZIP identity remains pending |
| M501.02 | Strict JSON reconstruction, source-linked errata, decision deduplication and scoped cache/recovery inventory; originals preserved |
| M501.03 | 15 actual shared source symbols, existing tests and hashed AST consumer references; proposed selectors explicitly unimplemented |
| M501.04 | Five-alpha roster and data-role registry; reviewed 2024 exploratory, full-set presets reference-only, unknown contamination not called untouched |
| M501.05 | EH-01..12, primary estimands/rivals, baseline/mandate policy and resource bounds registered; scientific choices explicitly unresolved and market locked |
| M501.06 | Current-interpreter CLI, schema/archive/math-syntax tests, Git/artifact privacy and append-only reports, including safe failure/timeout cleanup |

Developer tools are split between isolation, evidence, inventory, registration,
cleanup and orchestration. Existing `NormalizedSearchSpace`, sampler factory,
`ObservedSampler`, prepared WFO/domain evaluators, metric/report contracts,
trial/history stores and output planner remain the shared integration points.
An AST/test-reference inventory is not a claim that future Mode 5 consumers
already execute through all those components. No second financial runtime,
scientific reducer or public endpoint is introduced.

Privacy protection adds `prune upgrade/alphas` to `MANIFEST.in` and private-path
denial to the existing artifact checker. Its optional local exact-payload
denylist detects renamed copies of private files without printing their code.
Synthetic core/native wheel and sdist canaries pass. This is bounded exact-byte
protection, not a guarantee of detecting arbitrarily transformed fragments,
nor qualification of a newly built artifact.

## 4. Test Plan And Execution

Attempt-04: **76 passed, 0 failures, 0 skips**, with Optuna experimental warnings
retained rather than hidden. JUnit XML, argv, exits, stdout/stderr and timings
remain private. Actual pytest sources:

```text
tests/mode5/test_baseline.py
tests/test_phase48b_release_hygiene.py
tests/test_phase48f_release_gate.py
tests/test_optimization_samplers.py
```

| Acceptance | Actual exercised proof |
|---|---|
| M5T-001 | Traversal, drive/absolute paths, symlinks, collisions, reserved manifest names and archive-budget rejection; manifest-first bytecode-free copying |
| M5T-002 | Original SHA preservation, independent copied inodes, append-only writes, actual archive presence/hash observation and guide identity |
| M5T-003 | Synthetic prose/JSON discrepancy with exact source pointers; duplicate/nonfinite JSON rejection; actual historical reanalysis |
| M5T-004 | Four real shared factory resolutions and actual CMA independent-fallback telemetry on a toy mixed-space study |
| M5T-005 | Exactly 43 elapsed scored days and eight warmup days, without inventing bars or end inclusivity |
| M5T-006 | Same parameters retain separate decision records; deduplication is per-alpha and does not grant execution reuse |
| M5T-007 | Source/native/origin/data/clock/economics/alpha/terminal/warmup witness changes invalidate identity despite equal versions |
| M5T-008 | Reviewed-data/preset permissions and registration digest mutation rejection |
| M5T-009 | Missing raw returns/campaigns/contracts yield MISSING_REQUIRED_INPUT, never fabricated PSR/tail/sample N |
| M5T-010 | Actual source/test/consumer bindings, accepted legacy selectors and rejected unimplemented proposed selectors |

Additional tests cover all five support registrations, renamed private payloads
in both distributions, registered calendar adequacy, guide oracle Python syntax,
failure/timeout receipts, and owned cleanup. Syntax checks do not execute or
certify M5-03 mathematics. No alpha market test is implied by these counts.

Ruff, documentation links/anchors, tracked secret scan, canonical source-layout
check and staged/working diff checks pass. The initial standalone pytest command
had 20 passes and 18 setup errors because its basetemp parent did not exist.
The harness now creates it. That failed setup remains a failed, transcribed
execution note; later successful attempts do not replace it or pretend to be
the original missing stdout log.

## 5. Numeric Results And Matrices

| Historical artifact | Reconstructed observations |
|---|---:|
| Baseline score records | 80 |
| T1 winners | 12 |
| T1 stress records | 60 |
| T2 decision records | 16 |
| T2 distinct per-alpha raw parameter vectors | 11 |
| Numeric prose/master discrepancies | 18 |
| Additional scope/source corrections | 4 |

T1's recorded sampler labels are TPE, QMC and CMA-ES, not the original prose's
Random/TPE/QMC. Current factory recipes resolve to two TPE configurations,
CMA-ES and scrambled Sobol/QMC; constructor resolution alone does not certify
draw-level purity of historical runs. Original signed drawdown values remain
unchanged. T2 duplicate decisions are not independent economic observations.
T1's reviewed holdout is February 1 to March 15, 2024: 43 elapsed scored days;
Baseline's February 4 to March 15 interval is different, so a direct matched
comparison is not certified. Exact tables and private parameters stay local.

## 6. Economic Interpretation

Historical observations are preserved as HISTORICAL_REPORTED. M5-01 neither
retracts earlier valid scoped evidence nor proves a new economic improvement.
Short reviewed intervals do not establish year-long robustness. Winner-only
Sharpe/drawdown/fill summaries cannot reconstruct return moments, serial
dependence, PSR or campaign tails. Main-file equality is not financial parity.
The three inspected historical evidence lanes lack those full-path witnesses;
this is a scoped inventory, not a server-wide absence claim.

## 7. Proof Capability

Positive controls use the real shared factories and source interfaces. Negative
controls actually reject unsafe outputs, forged identities, silent fallback
purity claims, missing raw inputs, zero/placeholder support and altered data
permissions. The toy sampler study has three trials and no market simulator.
All M5T-001..010 have executed assertion mappings. There is no vacuous market
PASS, invented fill count or profitable-result requirement.

## 8. Potential And Next Falsifiable Actions

First resolve the original ZIP/extracted-member input disposition. Following
separate M5-02 approval, qualify actual alpha routes/helpers, clock/sizing,
warmup, lifecycle and permitted snapshot identity. Retrieve original retained
panels/paths before proposing bounded missing-probe replay. Register adequate
IS/forward duration, actual orders/fills/closed campaigns, opportunity/tail
support, effect and uncertainty policy before market economics. These are
explicit future-phase preconditions, not silently accepted zero defaults.

## 9. Performance And Resource Bill

Attempt-04 harness: **14.156 s**. Parent peak RSS **176.25 MiB**; child maximum
**238.73 MiB**, reported separately rather than summed into a fabricated peak.
Planned/actual new market evaluations: **0 / 0**. Historical reruns avoided are
not quantified from summary record counts. No throughput or trading speedup is
claimed for this inventory phase. No environment or dependency was installed.

Budget was registered before execution: 64 MiB incremental disk, one worker
and one configured compute thread, ten-minute per-check timeout, >=5 GiB reserve.
Attempt-04 retained 677,818 payload bytes before final report creation; 50
retained receipts/copies and 427 protected hashes were checked. Only its owned
pytest scratch was deleted: 9,523 ordinary-file bytes and 21 synthetic symlinks
unlinked without following them. Filesystem available changed
26,791,239,680 -> 26,790,359,040 bytes, a net **-880,640** including retained
outputs/concurrent activity, not a claim of positive disk-space reclamation.
All attempt lanes, originals, evidence and the existing tooling environment
remain. No broad cache cleanup or service termination.

## 10. Validity, Contamination And Review

The original bundle and alpha ZIP identities are expected, not observed.
Verified extracted members do not prove the full original archive, including
all helpers/raw members. Owner must either supply the two originals or accept
that narrower baseline explicitly. The registered support/effect/seed/mandate
choices are still unresolved; no formal CalibrationPlan is sealed in M5-01.
Data-role changes cannot make a previously reviewed interval untouched.

## 11. Exit And Handoff

Technical implementation and applicable local tests pass; **do not label the
whole phase COMPLETE until its mandatory input disposition is reviewed**.
M5-02..M5-12 remain NOT_STARTED. No financial implementation debt was introduced;
archive disposition and future scientific permissions remain visible conditions.

[Sanitized source-bound seal](evidence/m5-01.json) records hashes only.
Full append-only receipt set remains ignored/local at
`upgrade/private/mode5_upgrade_v1/m5-01/attempt-04/`; editable copies at
`upgrade/local/mode5_upgrade_v1/m5-01/attempt-04/`. Older attempts and the
initial failure note are preserved. Reproduce into a **new** output lane with
an interpreter that loads the registered source/native pair:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src \
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 NUMBA_NUM_THREADS=1 \
python tools/run_mode5_baseline.py \
  --bundle /path/to/verified/extracted/bundle \
  --rsi /path/to/private/rsi.py \
  --output upgrade/private/mode5_upgrade_v1/m5-01/new-attempt
```

The runner uses its invoking interpreter, refuses protected/existing/symlink
outputs, retains failed receipts and does not authorize market, CI or release.
