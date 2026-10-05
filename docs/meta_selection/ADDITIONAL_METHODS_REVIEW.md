# QMS-C01: Additional Methods And Schedules

## Decision And Scope

Review version: **qms-c01-methodology-amendment-v1-proposed**.
The owner explicitly chose **spec and tests first; activation separately** on
2026-10-05 (Asia/Saigon). This document does not enable a mode, change Ridge,
replace the registered scientific study or authorize a package release.

Source baseline: `b5563de495263d4b5fb8a9953e727c25c90cc441`.
Read the [C01 unified plan](../../upgrade/implement.md#qms-c01---additional-meta-modes-and-schedules)
and detailed guide sections
[3](../../upgrade/QUANTBT_1_1_1_META_SELECTION_AND_SAMPLER_MODULE_GUIDE_V1_1_VI.md#s3),
[5-6](../../upgrade/QUANTBT_1_1_1_META_SELECTION_AND_SAMPLER_MODULE_GUIDE_V1_1_VI.md#s5),
[7](../../upgrade/QUANTBT_1_1_1_META_SELECTION_AND_SAMPLER_MODULE_GUIDE_V1_1_VI.md#s7)
and [8](../../upgrade/QUANTBT_1_1_1_META_SELECTION_AND_SAMPLER_MODULE_GUIDE_V1_1_VI.md#s8).
The original guide remains unchanged. This is a proposed extension to its
methodology matrix, not a claim that the V1 wheel supports every proposal.

## Actual Native Matrix

The rows below are the eight existing native combinations. The audit uses the
default selector resolved for each row, not every optional selector recipe.
"Search" means adaptive Optuna ask/tell; "selection" means the final native
winner, which can be a different stage with additional data access.

| Mode / schedule | Adaptive search | Final native selection | Current meta |
|---|---|---|---|
| 1 / global | Mean penalized IS over all train folds | Real OOS decay rerank of shortlist | Reject |
| 1 / per_fold_decay | Current outer IS | Current outer OOS decay rerank | Reject |
| 1 / per_fold_causal | Inner-train folds inside outer IS | Inner-validation decay inside outer IS | Reject; first extension proposal |
| 2 / global | Synthetic IS-return proxy robustness | Default robust_decay reranks on real OOS | Reject |
| 3 / global | Mean penalized IS, flat-minima shortlist | Default robust_decay reranks on real OOS | Reject |
| 4 / global | All train folds, IS shards/plateau | IS robustness; OOS scoring is diagnostic | Reject; retrospective multi-fold |
| 4 / per_fold_causal | Current outer IS, shards/plateau | Current IS-only robustness | Existing supported route |
| 5 / global | Entire declared sample | Full-sample best/temporal/plateau/robust selector | Reject; calibration only |

Mode 2's adaptive objective never reads real current OOS. That is **not** a
proof that its default final shortlist selection is OOS-free. Likewise, Mode 3's
first plateau record is not necessarily its final anchor after decay reranking.
Optional IS-only selectors must be classified separately from robust_decay;
do not infer their data role from the mode name alone.

Mode 4 global can score OOS without using it to rank. Its later train folds
nevertheless include observations after earlier test starts; one global winner
replayed on every fold is not a chronological decision made at each fold.
Mode 5 has `train_index == test_index`: that replay is not a forward label.

## Native Objectives Are Not Raw Sharpe

For a scored window, the native objective may first apply a trade-frequency
penalty. Write that penalized score as S; it is distinct from raw SR and from
a QMS observation's validity/sample evidence.

Native decay selection currently maximizes:

\[
J_{\mathrm{decay}}=
\overline{S}_{\mathrm{validation}}
-\lambda_{\mathrm{decay}}\operatorname{std}
 (S_{\mathrm{train}}-S_{\mathrm{validation}})
-\gamma_{\mathrm{decay}}\max
 (0,\overline{S}_{\mathrm{train}}-\overline{S}_{\mathrm{validation}}).
\]

For nested Mode 1, validation is inner validation, not outer OOS. The existing
standard-deviation convention is ddof=1 for multiple folds and zero for one.
Candidate-specific lambda/gamma overrides remain authoritative.

The Mode 2 adaptive objective currently maximizes:

\[
J_{\mathrm{SBB}}=
\overline{S}_{\mathrm{synthetic}}
-\lambda_{\mathrm{SBB}}\max
 (0,\overline{S}_{\mathrm{IS}}-\overline{S}_{\mathrm{synthetic}})
-\eta_{\mathrm{SBB}}\overline{\sigma}_{\mathrm{synthetic}}.
\]

Its synthetic paths come from IS return proxies, not new market observations
or an independent original-account forward run. Tests independently reconcile
both formulas with actual native records. No objective is relabelled raw SR.

## Proposal A: Nested Mode 1

This is the closest additional causal route, but is **not activated by C01**.
Proposed cohort: `nested_anchor_outer_IS_real_forward_v1`.

1. Keep the original inner search, shortlist, decay selector, seeds and winner.
   The native anchor is the final inner-decay winner, not the highest-IS trial.
2. Freeze permitted history at the outer IS frontier before the inner study.
3. Materialize one authoritative **full outer-IS** witness for every feasible
   completed trial and the exact final anchor. Use the existing endpoint or
   qualified prepared scorer. Do not average inner Sharpe/variance and call it
   an outer-IS original-result observation.
4. Preserve requested/effective params, trial IDs, raw validity, native search
   and inner-validation diagnostics. A centroid anchor requires its own exact
   evaluation. Top-X candidates alone are not the full meta candidate pool.
5. Fit/rank using the unchanged origin-sum Ridge and predicted-quality guard.
   Meta off/shadow cannot alter native ask/tell, pools or actual accounting.
6. Seal the proposal and frozen label panel before current outer OOS opens.
   Active selection goes through the existing params-by-fold and account path.
7. Observe genuine outer-forward outcomes only after seal, using the existing
   isolated observer and publication/maturity clocks. Imported labels require
   compatible economics, permissions, availability and research-exposure role.

For this proposed cohort, the guide's unchanged target uses **raw outer-IS**:

\[
I_{k\theta}=SR_{\mathrm{outer\ IS},k}(\theta),\qquad
O_{k\theta}=SR_{\mathrm{outer\ forward},k}(\theta),
\]
\[
Y_{k\theta}=(I_{k\theta}-O_{k\theta})
 -(I_{ka_k}-O_{ka_k}),\qquad
\widehat{Q}_{k\theta}=I_{k\theta}-I_{ka_k}-\widehat{Y}_{k\theta}.
\]

That choice must be approved before implementation. An aggregated-inner-IS
target is a different cohort and must not silently share this family's records.
Raw Sharpe, penalized search score, inner candidate-decay objective and meta
predicted score stay separate in the final selected-record metadata. A full-pool
meta winner may never have been in the inner-validation shortlist; its inner
validation score must remain unavailable unless genuinely evaluated.

The compatibility family must bind the new cohort, mode/schedule, all inner
split/window/min-fold policies and relevant decay/selector settings. Do not
alter existing Mode 4 family hashes or mix Mode 4 anchor tasks into this family.
Existing Rust numeric transforms/solve/rank are reusable; no new account engine
or per-candidate model FFI is necessary. The extra original IS evaluations must
be counted and benchmarked, not hidden as a free descriptor cache.

## Proposal B: Selection-Adjusted Decay

Mode 1 / per_fold_decay observes current outer OOS during native selection.
Calling a post-selection meta hook causal would not undo that exposure.
A native anchor chosen using the target forward period also violates the current
QMS task ordering: anchor/panel seal must precede the first forward action.

If requested later, define a distinct retrospective research/calibration task
and explicit selection-adjusted evaluation role. It needs its own target and
information permissions; do not backdate the seal or import it as a causal task.
An untouched later holdout would be a separate evaluation, not the same OOS.

## Proposal C: Global Calibration

For global modes, the decision frontier is the last observation actually used
by the chosen native selector, not each replayed fold's IS end. The study has
one final decision; its component folds are not independent meta origins.

- Mode 1/3 default decay, and Mode 2 default final rerank, include real test
  observations in that decision frontier.
- Mode 4 global uses all permitted train folds. Removing OOS from ranking does
  not remove later train observations from an earlier replayed fold.
- Mode 5 uses the complete declared calibration sample. Require genuine later
  forward observations if constructing a future-target historical task.

Any later global adapter must expose retrospective calibration provenance,
separate full-pool aggregate features from original single-window observations,
and obtain a new versioned task/cohort contract. The current `MetaTask` clock
cannot be populated with early fold dates to manufacture causal provenance.

Mode 2 also needs separate `outcome_origin` cohorts for bootstrap/stress and
real-forward outcomes. Synthetic draws must not increase the count of matured
real origins. Mode 3 needs the exact final selector/anchor policy, not an
unconditional plateau anchor. Do not silently create per-fold causal Mode 2,
3 or 5: those native schedules do not currently exist.

## Source Seams And Activation Gates

| Responsibility | Existing seam | Required extension review |
|---|---|---|
| Native stages | `WalkForwardEngine.optimize_params` | Preserve adaptive objective versus final shortlist selection |
| Fold boundary | `_run_per_fold_schedule` | Nested selection uses inner folds; meta task would use outer fold |
| Full pool | `ISPoolCapture.capture` | Currently requires one Mode 4 causal fold and original witness |
| Family | `PublicMetaRuntime.compatibility_family` | Add inner/cohort identity without changing old Mode 4 families |
| Final record | `PublicMetaRuntime.select` | Do not label a nested objective as outer raw IS; bind actual params |
| Labels | `PublicMetaRuntime.observe`, `PostDecisionObserver` | Preserve seal, availability, maturity and distinct cohorts |
| Public guards | `validate_meta_route` | Remain closed until semantics and actual route are qualified |

Before any activation, require: owner choice of target/cohort; source-grounded
full pool and exact anchor; raw MetricObservation validity; off/shadow account
and RNG parity; active lineage to the actual stitched account; first-fold future
market/labels/archive mutation; family isolation and near-floor/tie chronology;
prepared/reference/Rust parity; exact installed-wheel consumers; end-to-end
cost/RSS/callback/FFI counts for the same methodology. Synthetic integration
PASS does not establish a new economic edge.

## Confirmed Metadata Gap

**C01-D01:** default Mode 2 / global final robust_decay uses real current OOS,
but its top-level legacy `oos_used_for_selection` flag is false. The source
excludes Mode 2 from that flag even though the final rerank calls the real
IS/OOS evaluator. The C01 trace and last-forward-only mutation test verify the
full IS pool is unchanged while real candidate-rerank metrics change.

C01 reports the discrepancy; it does not edit the protected native runtime.
Correct this metadata under a separately approved metadata-only change before
opening Mode 2 meta. Preserve params, objectives, RNG, costs and account arrays;
classify the actual selector rather than hardcoding every Mode 2 route as OOS-
using. A synthetic adaptive objective and a real-OOS final selector are separate
facts. Current global chronology already remains retrospective, not causal.

## Reproduction And Interpretation

The read-only audit reuses the public SMA example and deterministic 547 daily
bars, six attempted trials per study, seed 731, eight native routes. It runs
omitted and explicit meta-off arms, including full-pool/account/RNG equality.
Spies delegate every call; no production sampler/selector/scorer is replaced.
The tool's methodology map is **not** a runtime capability registry.

```bash
PYTHONPATH=src:. .venv/bin/python -m tools.qms_c01_audit \
  --output .maturin/qms08/c01-review/contract-review-v1.json
```

Use a fresh output path; sealed receipts are never overwritten. This discovery
run is not a speed benchmark, a real-alpha study or a new release gate. It
creates no training labels; native scalar Sharpe alone cannot certify raw
variance/metric validity. Existing Mode 4 raw-validity and prepared/active
integration regressions supply their own qualified evidence.

Read the [phase report](QMSC01_REPORT.md) for actual commands/counts, source
digests and remaining activation decisions. W3 process/batch/deadline/carry,
cross-scheduler samplers, persisted RNG and mixed-space geometry remain C02-C05,
not implementation work performed by this review.
