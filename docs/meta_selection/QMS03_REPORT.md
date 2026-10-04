# QMS Phase Report - QMS-03

## Source And Scope

Date: 2026-10-04. Branch `feat/meta-selection-samplers`; entry `3ce42bf`.
Core/native remain `1.1.1`/`0.4.2`. Guide, financial kernels, metric formulas,
Rust/API/ABI, user alpha sources, sampler factory and package dependencies are
unchanged. Source ownership remains canonical `src/quantbt`.

Implemented only the approved [QMS-03 unified plan](../../upgrade/implement.md#qms-03)
and [detailed guide](../../upgrade/QUANTBT_1_1_1_META_SELECTION_AND_SAMPLER_MODULE_GUIDE_V1_1_VI.md#qms-03--historydescriptorslabels-đúng-task-và-thời-gian).
See [history methodology/contracts](HISTORY.md) for sections 5/6/7/10 coverage.
The original QMS-01/02 receipts/evidence are preserved as historical artifacts,
not regenerated with current source or fabricated owner acceptance.

## Delivered

- Focused `optimization/meta_selection` modules for typed immutable records,
  distinct task/family/snapshot identities, compiled descriptors, origin-balanced
  scaling, panels, indexed history/revisions, original-result observation and
  safe JSON/existing columnar-retention adaptation.
- Full finite/feasible IS pool captured before lossy native compaction. Explicit
  anchor reference and logical roles remain independent of candidate order.
  Same params do not collapse separate physical/stochastic evaluations.
- Centroid anchor receives its own same-IS result inside the evaluator lifetime,
  with auxiliary work charged separately. Native params/objective/tables and
  stitched signal remain exactly equal with observation enabled or omitted.
- Generic range/log/one-hot/conditional encoding; fixed parameters excluded from
  variable distance; actual raw IS Sharpe/activity included. Frozen schema and
  contiguous read-only float64 batches reject unknown categories/shape changes.
- Historical transforms fit only permitted past IS data from labeled origins;
  one origin cannot dominate by candidate count. No labels fit scaling, no rare
  category epsilon scaling, explicit constant/unobserved support violations.
- Cap16 acceptance panel with anchor/top/diversity/controls and separately
  charged required-winner union. The actual fixture freezes task/panel **inside
  the IS selection tap before the engine opens the outer forward strategy view**.
- Raw original financial reports and matching array-first sample support produce
  same-origin D/Y/Q labels. Account, first mark, constraints, canonical fees,
  metric definition, market/funding witnesses and output references are retained.
  No new financial reducer, simulation or accounting replay is used.
- Terminal failure/no-variance/censored/incomplete records remain visible but
  cannot train; genuine finite zero with positive variance is valid. PENDING has
  no invented actual availability and survives safe portable retention.
- Bounded family/corpus/cohort/exposure as-of index, immutable sealed revisions,
  strict cutoff/publication-order rules and full 1/M origin reweighting. Late
  corrections do not rewrite earlier snapshots or add fake support origins.
- Strict content/schema verification and provenance-reviewed import. Self-hashed
  JSON alone is unverified; original observation witnesses and a reviewed full
  revision are required. Rehashed metric/provenance tampering is tested.

## Test And Gate Evidence

[JUnit](../../benchmarks/optimization/meta_selection/qms03_tests.xml):
**311 passed, zero failures/errors/skips**, CLI 70.15 s (JUnit 69.980 s).
83 Q3 checks plus 228 prior/affected checks. Warnings are exposed Optuna
experimental-feature notices; no missing capability is hidden as a skip.

```bash
.venv/bin/python -m pytest -q tests/meta_selection \
  tests/test_optimization_core.py tests/test_optimization_samplers.py \
  tests/test_optimization_integration.py tests/test_optimization_phase33b.py \
  tests/test_phase49a_walkforward_schedules.py \
  tests/test_phase50_nested_mode1_causal.py \
  tests/test_phase74_public_wfo_native.py tests/test_perf_06_research_audit.py \
  --junitxml=benchmarks/optimization/meta_selection/qms03_tests.xml
```

| Gate | Actual evidence | Result |
|---|---|---|
| G3-TASK | Explicit anchor/STATIC/duplicates, exact identities, full pool and own centroid result | PASS |
| G3-CAUSALITY | Actual pre-forward panel seal, future market/history/order mutations, frozen cutoff and revision availability | PASS |
| G3-DESCRIPTORS | Generic HMA schema, category permutation, log/conditional masks, historical scaling/support/shape guards | PASS |
| G3-LABELS | Original engine-produced medoid/centroid labels, independent Y/Q reconciliation, genuine/undefined zero distinction | PASS |
| G3-PORTABLE_HISTORY | Reviewed JSON/columnar roundtrip, corruption checks, pending maturity and replacement weights | PASS |
| G3-OWNER | No acceptance decision invented | PENDING |

The [executed receipt](../../benchmarks/optimization/meta_selection/qms03_gate_receipt.json)
pins these eight groups and the [source/cost evidence](../../benchmarks/optimization/meta_selection/qms03_history_evidence.json).
Q3-T01..08 have 10/7/13/5/1/19/4/24 checks respectively.
All eight valid legacy mode/schedule routes retain frozen candidate pools,
objectives, selection, params, stitched positions, equity and reports exactly.
Affected prepared-native WFO, nested Mode 1, optimizer and retention tests pass.
An isolated omitted public call imports no meta package and emits no new meta
work/metadata. Canonical-source, import-boundary, lint and documentation gates
are checked independently.

No full-repository test, Rust rebuild, wheel install, remote CI or economic
certification is claimed. QMS-08 owns the final broad package/economic gate.

## Original Engine Fixture And Cost

Public SMA example on 547 synthetic daily OHLCV bars; two chronological quarterly
folds; rolling 180-day IS; six attempts per fold; seed 731; one worker; three
IS shards; existing NumPy/Numba financial execution and fresh diagnostic accounts.
Actual labels are engine-produced, but the market is **synthetic**, not real-alpha
edge evidence. Replay logical clocks and today's wall time are explicitly separate.

| Fixture | Full IS records | Reduced native table | Forward attempts | Valid non-anchor labels | Extra exact IS evaluations |
|---|---:|---:|---:|---:|---:|
| Medoid | 10, two 5x3 descriptor batches | 8 | 10 | 8 | 0 |
| Centroid | 12, two 6x3 descriptor batches | 8 | 12 | 10 | 2 |

Both have zero failed forward attempts and two usable matured origins.
This is below the future learner's 12-origin integration default; no model fit,
meta ranking or statistical superiority is claimed.

Observed costs in one process:

| Fixture | Calibration | Forward observer | Total fixture | Process peak RSS |
|---|---:|---:|---:|---:|
| Medoid, first/cold invocation | 2,045.227 ms | 131.726 ms | 2,325.046 ms | 286.762 MiB |
| Centroid, subsequent/warm invocation | 477.773 ms | 167.376 ms | 852.969 ms | 287.316 MiB |

Calibration includes the original WFO search/realization, IS support and panel
construction. Total includes retention/roundtrip, descriptor/scaler checks and
observer work. Cold versus warm rows are **not** a selector speed comparison.
Peak RSS includes cumulative imports/JIT and is not isolated history memory,
a native buffer budget, or RSS-plateau certification.

A separate omitted/default public fixture alternates parent `3ce42bf` versus
current changed class bodies, sharing byte-unchanged financial/helper code:
one warm-up then three recorded pairs. Median **169.327 ms -> 174.549 ms**
(+3.08% in this small noisy measurement). Both have exactly 12 strategy calls,
42 score calls and the same financial/search outcome digest. Previous probes
varied in direction; this is cost-only evidence, not a production overhead
threshold or a speedup claim. No new archive or auxiliary work runs when omitted.

Descriptor transform remains the explicitly reported NumPy reference; the
installed ABI has no qualified QMS transform. Native-require fails rather than
silently falling back. No per-candidate PyO3 bridge or N-by-N weight matrix was
introduced. QMS-04 owns the numeric native/learner addition.

## Handoff

Implementation COMPLETE; five technical gates PASS; performance MEASURED_COST_ONLY;
empirical NOT_ASSESSED; owner review PENDING. No open blocker remains in this
registered record/history/original-result phase.

Explicit next-phase boundaries: no Ridge model or learned selection (QMS-04),
no public off/shadow/active hook (QMS-05), no qualification of scalar/native
sample support or reactive W3 labels (QMS-06). This phase blocks missing support
instead of asserting validity or changing an old backend. Native transform
capability is intentionally not advertised as delivered.

Runnable repository example: `.venv/bin/python -m examples.wfo_history_records`.
Only local scoped commits are made. No push/merge/version/tag/release/deployment
or automatic QMS-04 advancement is authorized by this handoff.
