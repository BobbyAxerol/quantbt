# Mode 4 Meta-Learner Research Guide V1

**Date:** 2026-10-17, Asia/Saigon.
**Status:** owner approved sequential M4-ML-01/02 local execution and the finite
protocol on 2026-10-17. M4-ML-01 admission and M4-ML-02 finite replay are
complete locally; see the [comparison](../docs/meta_selection/M4_ML_02_CALIBRATION_REPORT.md).
KEEP_FROZEN_V1: P1 misses the registered improvement gate; P2 lacks complete
calibration blocks and falls back. Owner subsequently authorized sequential
ML-03 -> ML-04 -> ML-05; all are complete locally. Zero supported nominees
under the approved finite protocol means KEEP_FROZEN_V1, not a forced new-family
economic/adaptive rollout. Actual mature controls and exact retained P0/account
custody pass. See the [final decision](../docs/meta_selection/M4_ML_05_FINAL_DECISION.md)
and [family report](../docs/meta_selection/M4_ML_03_FAMILY_REPORT.md). The
[worksheet](../docs/meta_selection/M4_ML_03_PROTOCOL.md) records this boundary.
The Ridge baseline remains frozen. No production target,
hyperparameter/default policy or public activation changes are authorized.
**Sequence:** completed M4-ML-01 -> M4-ML-02 -> M4-ML-03 -> M4-ML-04 ->
M4-ML-05, [M4-ML-06](#mlr-s12) and [M4-ML-07](#mlr-s13) research follow-ups, then
separately approved M5-11.7 and M5-12. No automatic phase advance.
**Historical planning amendment (2026-10-17, Asia/Saigon):** section 12 was a new,
unexecuted protocol requested after the fixed-zero check. It proposes explicit
research-only guard/ranking changes and additional witness work for approval;
sections 1-11 and completed receipts retain their original scope and gates.
**Current section-12 disposition:** COMPLETE_LOCAL_REGISTERED_SCOPE; technical
PASS, exploratory heterogeneous outcomes, KEEP_FROZEN_V1. The approved protocol
bytes remain in the private registration and retained protocol archive. Only
current status/report pointers are updated here; no scientific gate is amended.
See the [report](../docs/meta_selection/M4_ML_06_DECISION_VALUE_REPORT.md) and
[closure](../benchmarks/optimization/meta_selection/model_research_v1/ml06_closure.json).

<a id="mlr-s1"></a>
## 1. Authority, Baseline And Problem

Read the original QMS [mathematics](QUANTBT_1_1_1_META_SELECTION_AND_SAMPLER_MODULE_GUIDE_V1_1_VI.md#s5),
[availability](QUANTBT_1_1_1_META_SELECTION_AND_SAMPLER_MODULE_GUIDE_V1_1_VI.md#s6),
[causal flow](QUANTBT_1_1_1_META_SELECTION_AND_SAMPLER_MODULE_GUIDE_V1_1_VI.md#s7),
[architecture/parity](QUANTBT_1_1_1_META_SELECTION_AND_SAMPLER_MODULE_GUIDE_V1_1_VI.md#s8),
[cost](QUANTBT_1_1_1_META_SELECTION_AND_SAMPLER_MODULE_GUIDE_V1_1_VI.md#s10),
[reporting](QUANTBT_1_1_1_META_SELECTION_AND_SAMPLER_MODULE_GUIDE_V1_1_VI.md#s12)
and [economic scope](QUANTBT_1_1_1_META_SELECTION_AND_SAMPLER_MODULE_GUIDE_V1_1_VI.md#s14).
This supplemental protocol cannot retrospectively change their estimators,
alpha/account semantics, receipt status or economic claims.

The task is candidate selection from a fixed valid IS pool, using historical
candidate outcomes mature at the decision cutoff. It is not forecasting prices,
learning broker actions, optimizing strategy signals or maximizing training fit.

For candidate theta and the origin's native anchor a:

```text
Y = (IS - FWD)theta - (IS - FWD)a = deltaIS - deltaFWD
R = decay_anchor - decay_selected
Q = FWD_selected - FWD_anchor
R = (IS_anchor - IS_selected) + Q
```

Lower predicted Y is useful only with its declared quality/support policy.
Training loss, genuine forward quality, reduced decay and account risk/cost are
separate measurements. Positive R produced only by lower IS cannot certify Q
improvement. A negative result does not automatically indicate an accounting bug.
On identical rows with the same known deltaIS, Q prediction error is the
negative of Y prediction error; their MAE/RMSE are identical, not independent
confirmations. Ranking by minimum Y still differs from ranking by maximum Q
because deltaIS varies across candidates. Preserve and test these identities.

The [frozen Ridge comparator](../docs/meta_selection/RIDGE_V1_FROZEN_BASELINE.md)
is immutable. Beta/scaler still refit causally; loss/weights/target/guard/ties
and mathematical units do not drift. V1 stays available even if a challenger
wins. The [freeze manifest](../benchmarks/optimization/meta_selection/model_research_v1/ridge_v1_freeze.json)
is a source/contract record, not an experiment PASS or artifact certificate.

<a id="mlr-s2"></a>
## 2. Generalization Without Alpha-Specific Hand Tuning

Generalize the calibration/initialization procedure, not a claim that every
alpha must have identical fitted coefficients or the same optimal scalar.
Do not encode alpha names, cherry-picked alpha-specific lambda values, or a
post-outcome model selector. A data-adaptive rule can vary its result if the
same predeclared algorithm and information rights apply to every case.

Primary design evaluates the hyperparameter procedure across held-out alpha/
related-strategy groups and chronological origins. Candidate rows within one
origin are dependent; overlapping rolling windows and shared market dates add
dependence. Labels per origin are not independent sample size. Macro summaries
give declared equal alpha-group weight, then origin weight, rather than allowing
label-rich families to dominate. They are summaries of separate qualified fits,
not permission to merge incompatible raw training rows.

Keep per-family coefficient fits on compatible histories. The held-out family's
own permitted past may train its coefficients, but its outcomes cannot choose
the cross-family hyperparameter recipe used to evaluate that family. Call this
procedure transfer, not zero-shot prediction on an unseen strategy. Raw parameter
names/coordinates from different schemas are not semantically interchangeable.

Existing five-alpha data is researcher-reviewed. Group holdouts and replay
can assess conditional procedure transfer and chronology, not restore untouched
external OOS. Related variants stay in one group. Monthly/730D, quarterly/365D
and the older RSI protocol remain separate strata; no convenient mixed result
is substituted for a matched comparison. Insufficient groups/origins means
limited scope or INCONCLUSIVE, not synthetic replication.

<a id="mlr-s3"></a>
## 3. Evidence Reuse And Bias Audit

Reuse existing original monthly 57-fold pools, corrected labels/history and
saved accounts for SC/HMA/HASH/VWAP; qualified RSI histories; and the 19-quarter
research variants as separately identified secondary evidence. Do not repeat
the completed strategy optimization or replace original feedback with a faster
variant while claiming a matched learner comparison.

Before outcomes, inventory per cell: family/schema/target/scaler versions,
K matured origins, label rows and dimensions, acquisition policy, valid/null/
no-variance counts, base-panel versus winner-union membership, cutoffs and
source hashes. The default 12-origin rule remains a guard, not adequate power
for all nonlinear learners or inner calibration.

Audit that the sealed base acquisition panel was chosen before forward. Its
feature-dependent selection need not be uniform or representative. Compare
base-panel-only and full registered union training as a bounded sensitivity
analysis; the union can oversample old policies' winners. An unchanged acquisition
rule does not make its labels an oracle for all 128 candidates. Do not claim
unbiased correction or fabricate inverse-propensity weights when probabilities
and positivity are unknown. Preserve all failures/undefined measurements.

Fit/rank replay uses the full authorized current IS pool. For evaluation, record
whether each new winner has an actual forward witness. Lack of a witness is
not a zero outcome and must not silently restrict selection to labeled candidates.
Bounded labeled-panel metrics are supplementary and explicitly conditional.

<a id="mlr-s4"></a>
## 4. Model Triage And Feasibility

These priorities are engineering/scientific assessments, not measured gains.
An expensive model must answer a specific baseline limitation before admission.

| Family | Potential role | Primary risk | Research disposition |
|---|---|---|---|
| Frozen weighted Ridge V1 | Auditable small-data comparator | Linear capacity, squared-loss sensitivity and changing lambda/K | Always retain |
| Normalized/calibrated Ridge | Test a common regularization procedure independently of model capacity | Hyperparameter-selection bias and few independent origins | First cheap experiment |
| Bayesian/empirical-Bayes linear | Estimate shrinkage/noise using a common training-only rule | Prior/noise assumptions; correlated rows do not yield calibrated posterior certainty | One fixed-prior cheap challenger |
| Huber plus L2 | Test whether extreme residuals dominate squared-loss decisions | Suppresses genuine tail information; introduces loss/scale parameters | At most two preregistered configurations |
| Shallow XGBoost regression | Test nonlinear threshold/interaction effects on the same target | Flexible trees overfit a small number of origins; extra dependency | Main nonlinear challenger, tightly capped |
| Pairwise/listwise ranker | Origin naturally forms a candidate query group | Rank scores lack calibrated Y/Q units; relevance construction can change the problem | Synthetic feasibility only in this tranche; no financial candidate promotion |
| ExtraTrees/RandomForest, LightGBM/CatBoost alternatives | Possible robustness/implementation alternative | More correlated model searches and dependencies | Reserve, not additional automatic arms |
| PCA/clustering/OOD diagnostics | Describe compression, support or distribution shift | High variance/clusters do not identify good params; fitted preprocessing can leak | Diagnostic feasibility only, no automatic candidate veto/selection |
| GP/kernel/deep models | Nonlinear effects or uncertainty under appropriate assumptions | Kernel memory/fit cost, task dependence and small-origin sample support | Defer without a demonstrated gap and separate budget |
| RL/bandit proposal/controller | Different adaptive acquisition/control problem | Changes policy/data acquisition and off-policy evaluation requirements | Out of scope, not a drop-in Ridge replacement |

Prioritize three non-baseline learner families at most: Bayesian linear, Huber,
and shallow XGBoost regression. Ranker/unsupervised probes are tiny synthetic
contract checks, not extra real-market arms. No GPU, distributed training,
neural architecture tournament, automatic feature explosion or per-alpha tuning.

For XGBoost propose `tree_method=hist`, CPU, depth in {2,3}, at most 128 rounds
and eight predeclared configurations total, not eight per alpha. Fix stochastic
settings and folds before results; early stopping may use only inner permitted
validation. Seal actual rounds and all failed/early-stopped attempts. Use the
official CPU-only wheel if a version/hash-compatible artifact is approved; do
not pull GPU/NCCL packages or replace the main environment. No package is
installed during planning. The current environment has sklearn 1.8.0, NumPy
2.2.6 and Optuna 4.8.0; XGBoost/LightGBM/CatBoost are absent.

Every learner must preserve an exact zero anchor and serve correctly defined
relative Y/Q. Setting a tree's `base_score=0` is insufficient. If predictions
are centered as `g(v)=f(v)-f(0)`, that transform is part of a new learner version;
measure training/validation loss on g as actually served. Plain uncentered
training is not claimed to optimize the centered loss. Reject or defer a
challenger whose coherent anchor/loss contract cannot be qualified cheaply;
do not silently overwrite only the anchor prediction after scoring.

Rankers require an origin/query group, explicit relevance units/order and a
separately validated magnitude/quality head to retain the existing Q guard.
Never plug an arbitrary relevance score into `Qhat=deltaIS-Yhat`. That extra
model/target/calibration complexity is why ranker financial activation is not
part of this small research tranche. Unsupervised states cannot select a good
candidate without a further supervised/economic decision contract.

<a id="mlr-s5"></a>
## 5. Hyperparameter Initialization And Adaptation

Separate three roles: initial hyperparameter recipe, refitting learned model
coefficients at each vintage, and changing the hyperparameter policy itself.
Only the last introduces an adaptive policy-selection process.

| Policy | Definition | Availability rule |
|---|---|---|
| P0 frozen baseline | Existing origin-sum lambda=10, min origins=12, Q floor=-0.10 | Unchanged comparator |
| P1 normalization-only control | Mean-origin alpha=10/12; equivalent sum lambda(K)=K*10/12 | New version, same fixed rule for all families; no outcome tuning |
| P2 chronological calibration | Common mean-origin alpha grid {0.1,0.3,10/12,1,3,10}, macro origin/group-balanced inner validation | Training groups and matured origins only; insufficient calibration support falls back to P0 |

The six-point grid is a proposed finite design, not an empirical optimum.
P1 deliberately matches P0's coefficient solution at K=12 under the same fit
basis; this is a testable normalization control, not a production patch.
P2 must first be evaluated as a frozen common policy across training alpha
groups. It is not allowed to save a separate winning grid value for each alpha
after inspecting that alpha's evaluation outcomes.

Initialization may use the fixed recipe or a common empirical-Bayes procedure.
Evidence-based shrinkage is still a model with assumptions, not tuning-free
proof of future performance. Audit its priors, noise scale, units and effective
degrees of freedom; never interpret candidate count as independent task count.

Compare two deployment schedules only for a shortlisted calibration procedure:
(A) choose a shared recipe using development training groups, then freeze it;
(B) update by a predeclared periodic rule using only newly matured allowed
history, never current forward. Cadence, minimum new support, rolling/expanding
calibration history, hysteresis and fallback are fixed before outcomes. A new
OOS result may influence later decisions only after its availability time.

Periodic adaptation is a conditional M4-ML-04 arm, not an unbounded trigger on
every loss/drawdown. Its primary comparison uses the same information frontier
and base model refit schedule; distinguish the hyperparameter-update effect
from having more history. Do not tune the Q floor, minimum origins, descriptors,
native anchor or strategy parameters at the same time.

The calibration criterion must be preregistered: primary macro origin-weighted
validation squared error of served Y predictions; Q prediction error/calibration,
rank stability and decision R/Q are mandatory secondary checks. Use a declared
chronological/group-block uncertainty rule and a simpler-within-uncertainty
tie preference, not thousands of row-level IID standard errors. No threshold
or selection criterion is changed to get a favorable decision after results.

<a id="mlr-s6"></a>
## 6. Chronological And Cross-Family Evaluation

At each outer evaluation origin, freeze all information rights first. Inner
fit/preprocessing/calibration/early stopping uses only observations whose
labels are mature by its own inner decision time. Enforce gaps/purge where
actual label horizons overlap; do not use an arbitrary gap as a substitute
for exact availability. Forward-shared-market data from another alpha is also
future information at the earlier timestamp, even if its strategy ID differs.

Leave-one-related-alpha-group-out evaluates the common calibration procedure.
All same-origin rows and declared sibling variants remain grouped. If different
economic/schema families cannot train one model, fit separate compatible models
under the same candidate recipe and aggregate their validation scores with
preregistered macro weights. No raw-row schema coercion, leaked whole-corpus
scaler, or pooled source/route parity claim is permitted.

Use synthetic independent expectations for linear recovery, contamination,
nonlinear interaction and pure-noise controls. Temporal target permutation may
be a sanity check only under a declared dependence-preserving construction;
it is not automatically an exact p-value. Larger trees must not be rewarded
merely for reducing training loss on these fixtures.

Data-driven model/recipe selection introduces multiplicity. List every proposed,
failed, rejected and executed configuration, seed and optional stopping. Select
on development only; reserved chronological blocks cannot be reused to choose
another model after inspection. Existing reviewed data is labeled exploratory.
No new independent generalization claim is made without a genuinely reserved
future period or strategy group that was not used in design.

<a id="mlr-s7"></a>
## 7. Metrics, Economic Decisions And Missing Outcomes

Required outputs, separately by alpha group/cohort, cold-start/mature and origin:

- Served-prediction train/validation loss, MAE/RMSE Y/Q, calibration slope/bias
  where supported, rank association/pair accuracy and explicit null reasons.
- Model complexity, K/N/d, effective degrees of freedom where defined, residual
  concentration, feature support/OOD, numerical failures and coefficient/model
  stability across neighboring hyperparameters and allowed time vintages.
- Native anchor, Ridge V1, challenger proposed/applied IDs; full-pool scores,
  Q guard decisions, ties/fallback and effective-parameter changes.
- Actual selected raw IS/FWD, signed D/R/Q and IS-versus-forward decomposition;
  predicted-Q pass with realized negative Q is retained, not erased by the guard.
- Regret only versus the finite set with observed qualified labels, never a
  full-pool oracle. Pairwise/ranking metrics retain origin/query support.
- Continuous original account only when a complete candidate schedule is
  admitted; account risk/cost/activity, not just final equity. Never concatenate
  reset diagnostic equities or reuse a different route's fills as parity.
- Model/observer/replay/report wall time, CPU/RSS, threads and retained bytes;
  supported macro summaries and declared dependence-aware uncertainty.

MLR-01 must seal numerical minimum support, validation blocks, alpha grouping,
missing-pattern policy, primary/secondary estimands, R/Q noninferiority margins
and family confidence before new model outcomes are opened. If prior evidence
cannot support meaningful acceptance, register a bounded feasibility study and
its limited conclusion rather than inventing powerful tests from candidate rows.
Production promotion cannot rest on training loss alone or an R increase caused
only by reduced IS. KEEP_V1 and INCONCLUSIVE are valid completed decisions.

<a id="mlr-s8"></a>
## 8. Architecture, Reuse And Runtime Controls

Keep source canonical under `src/quantbt`; use focused typed learner/calibration
adapters at existing history/transform/fit/rank/decision seams. V1 source and
version validation remain intact. Do not create a separate endpoint, strategy
optimizer, account engine, market cache, metrics implementation or FFI bridge.
Use the [shared diagnostics module](../docs/diagnostics/SHARED_ALPHA_DIAGNOSTICS.md)
for pre-search evidence/explanation, not as authority to alter live params.
Full-development Mode 5 dossiers cannot become features or hyperparameter
advice for earlier Mode 4 cutoffs; each optional diagnostic needs its own
permitted-prefix readiness witness.

Rust remains the existing baseline numeric owner where resolved. New native
library models may use their established CPU implementation with one batch
fit/predict boundary; do not port XGBoost to Rust or promise all model code is
Rust before demonstrating a need. Python orchestration stays off the per-bar
financial hot path. Optional research dependencies must not become mandatory
for ordinary QuantBT/meta-off/Ridge users.

Fit caches include source/model/loss/hyperparameter/feature-map versions,
snapshot, family, cutoff, weights and basis. Changed recipe/settings means a
new model identity, not stale beta reuse. When a fixed basis is reused for a
lambda grid, shared sufficient statistics are allowed only with exact witness
identity; changing the scaler invalidates them. No full-data preprocessing or
unqualified checkpoint/warm-start continuation is hidden as an optimization.

<a id="mlr-s9"></a>
## 9. Cost Envelope And Stop Rules

Proposed ceilings, not ETAs or permission to spend them before phase approval:

| Phase | Work ceiling | New financial work |
|---|---|---|
| M4-ML-01 | Cold inventory/design; <=15 CPU-minutes | 0 |
| M4-ML-02 | <=4,000 total small linear/calibration fits, <=1 CPU-hour | 0 |
| M4-ML-03 | <=2,000 total challenger fits, <=90 CPU-minutes; <=8 XGB, 2 Huber, 1 Bayesian settings | 0 |
| M4-ML-04 | Reuse all compatible witnesses; first <=8 missing-winner queries, hard <=64 queries total; <=2 CPU-hours | Targeted original-route executions only; 0 optimizer proposals |
| M4-ML-05 | Report/regression/handoff; no market reruns | 0 |

Fit counts include inner validation, early-stopping refits, controls and retries;
they are not per-alpha allowances. No 5-alpha x model x arbitrary Optuna-search
tournament. Pilot 12 representative fits before scaling; measure worst/median
cost and memory, project the remaining registered work, and stop at a guard
with partial evidence intact. If coverage cannot fit, report NOT_ADMITTED or
INCONCLUSIVE; do not shrink horizon/trials to make the scientific claim pass.

Prioritize original monthly pools for matured-history research. Quarterly
variants are secondary support/transport checks, not grounds to spend a second
full WFO budget. A full continuous account for an alternative policy is not
silently charged as one cheap segment query: record its bars/stages and admit
it only within a separately measured part of MLR-04's same resource ceiling.
If missing outcomes exceed 64, select the planned evaluation scope before
opening their outcomes or request an amendment. Do not validate only winners
that happen to have favorable or preexisting labels.

At most two independent one-thread workers; owned RSS <=1.5 GiB and at least
512 MiB host available RAM. Numeric/model threads explicitly one, CPU only.
Default artifact/scratch incremental cap 256 MiB and at least 5 GiB free disk
after projected peak. New CPU dependency footprint plus retained wheels must
be inventoried inside that cap or request approval; no duplicate full environments.
No per-bar JSON, dataset copy or O(N^2) candidate pair materialization. Reuse
existing read-only arrays, bounded summaries and shared numeric owners.

Every phase retains compact manifests/model settings/predictions and failures;
large snapshots/params stay private. Cleanup exact reviewed inactive scratch
after verifying evidence hashes. Use the [mandatory runbook](../docs/BUILD_TEST_CLEANUP.md).
No remote CI, merge, tag, PyPI upload or release build is in this tranche.

<a id="mlr-s10"></a>
## 10. Qualification And Final Decision

Required technical tests: frozen-source/settings integrity; weighted-loss and
normalization identities; exact anchor/guard/ties; actual served prediction
units; family/schema/constant/categorical/conditional handling; all learned
preprocessing/early stopping as-of; future market/label/calibration mutation;
delayed/corrected labels; group exclusion; deterministic order/RNG; copy/restore
and cache invalidation; fresh optional-dependency absence and bounded resource
failure; unchanged financial witnesses/off/shadow/Ridge decisions.

Loss or model changes get separate identities and numerical expected-value
tests. Numerical tolerances are not widened to make an economic comparator
agree. A source/recipe freeze is not a fitted-model qualification. No phase
passes with unresolved implementation defects inside its admitted scope.
Scientific support gaps can close with explicit limited dispositions, not fake
economic promotion or undocumented technical debt.

Final allowed dispositions: KEEP_FROZEN_V1; RESEARCH_OPT_IN_CANDIDATE with exact
scope and owner approval still required; INCONCLUSIVE; or DEFER_NEW_FAMILY.
Choose the simplest adequate recipe within preregistered uncertainty/cost
rules. Report loss, Q, R decomposition, generalization breadth, instability,
support/fallback and resource bill together. A complex model wins only if
its additional cost has supported decision-level value. No guaranteed decay
improvement or all-alpha generalization claim.

<a id="mlr-s11"></a>
## 11. Primary Sources And Version Notes

Consult docs matching the actual pinned dependency before execution. The latest
online XGBoost docs were reviewed for feasibility only; they do not pin or
authorize installation of the displayed latest release.

- [XGBoost parameters](https://xgboost.readthedocs.io/en/stable/parameter.html):
  histogram trees, depth/rounds/regularization and native CPU controls.
- [XGBoost learning to rank](https://xgboost.readthedocs.io/en/stable/tutorials/learning_to_rank.html):
  query grouping and relevance scores; not calibrated Sharpe predictions.
- [XGBoost CPU-only installation](https://xgboost.readthedocs.io/en/stable/install.html#minimal-installation-cpu-only):
  avoids the full GPU-enabled package footprint.
- [BayesianRidge, sklearn 1.8](https://scikit-learn.org/1.8/modules/generated/sklearn.linear_model.BayesianRidge.html):
  learned precision parameters and stated assumptions/algorithm limitations.
- [HuberRegressor, sklearn 1.8](https://scikit-learn.org/1.8/modules/generated/sklearn.linear_model.HuberRegressor.html):
  robust loss, scale and regularization; not drop-in proof of better decisions.
- [Cawley and Talbot, JMLR 2010](https://www.jmlr.org/papers/v11/cawley10a.html):
  overfitting model-selection criteria and subsequent evaluation bias.

<a id="mlr-s12"></a>
## 12. Decision-Value Follow-Up: M4-ML-06

**COMPLETE_LOCAL_REGISTERED_SCOPE (2026-10-17, Asia/Saigon).** The approved
bounded experiment passes local technical gates; its exploratory results retain
frozen V1 with no default activation. Read the
[report](../docs/meta_selection/M4_ML_06_DECISION_VALUE_REPORT.md),
[interpretation](../docs/meta_selection/M4_ML_06_INTERPRETATION.md) and
[closure](../benchmarks/optimization/meta_selection/model_research_v1/ml06_closure.json).
The registered 128 missing-winner calls and four original controls all finish;
26 lower-priority F queries remain outside the cap, not silently imputed.
This protocol supplements the completed studies;
it does not revise their conclusions or admit a model through a failed gate.
Read the [unified phase](implement.md#m4-ml-06). The question is which next
engineering/research action is justified by decision-level evidence, rather
than whether a larger learner can marginally lower one aggregate loss.

<a id="mlr-d1"></a>
### 12.1 Evidence, Roles And Counterfactual Limits

Use original monthly/730D SC/HMA/HASH/VWAP pools with 128 attempted trials,
all 57 origins, exact corrected histories and actual native/Ridge decisions.
Keep the original 13 acquisition + 12 development + 32 evaluation roles.
The primary decision comparison covers February 2024--September 2026; earlier
origins diagnose cold start and development separately. Reuse earlier RSI
evidence as a separate reference, without pretending the account/window matches.

Primary fitting history is the historical union actually available to V1 at
each cutoff. This matches actual Ridge decisions. Base-only development results
remain a separately labeled acquisition sensitivity; do not compare a base-only
new model with union-trained V1 and attribute the difference solely to the model.

This is **conditional replay on logged history**. Old winner-union acquisition
depends partly on the old policy. An X2/guard/ranking proposal using that history
is causal as of its cutoff but is not a self-consistent replacement-policy
rollout with its own newly acquired labels. New witness queries are evaluation
only: never append them to training, change later snapshots, or backdate their
availability. A complete adaptive policy replacement remains separate research.

Restore saved predictions only with matching pool/schema/source/feature/model/
history/clock identity. Compute missing X2 evaluation predictions with the
already frozen recipe, not renewed tuning. This opens a new descriptive view
of previously reviewed data; it is not untouched OOS. Choosing X2 after its
development result creates selection bias which the report must disclose.
No leave-group-out nomination or independent generalization claim is restored.

Each new decision is sealed before its current forward outcome is attached.
Full-development Mode 5 dossiers may explain today's research decisions, but
cannot supply a feature, threshold, shortlist or regime label at an earlier
Mode 4 vintage. Selection replay must use only prefix-authorized inputs.

<a id="mlr-d2"></a>
### 12.2 Five Fixed Policies And Zero-Score Control

All policies see the same original valid candidate pool and native anchor.
Existing feasibility, unsupported-metric handling and causal fallback apply.
The following research changes require approval of M4-ML-06; they do not modify
the production selector or its frozen mathematical identity.

| ID | Prediction and ranking | Isolated question |
|---|---|---|
| N | Always the original native anchor | What value is added beyond existing IS search and native robustness selection? |
| R | Actual union-trained Ridge V1, min Yhat with Qhat >= -0.10 | What did the existing learned decision actually add? |
| X | Existing X2 recipe with exactly R's history and selection policy | Does its predictive improvement translate into better winners? |
| G | R predictions; min Yhat with Qhat >= 0 | Does tolerating predicted forward deterioration explain avoidable harm? |
| F | R predictions; max Qhat under the existing Qhat >= -0.10 guard | Is relative-decay ranking the limiting decision rule? |

G changes only epsilon; F changes only ranking direction/score. Both reuse
R's predictions, target, fit and history. F still trains Y with Ridge; it is
not a new Q-trained model or a combined stricter-guard model. No G+F combined
arm, additional epsilon grid, confidence threshold or per-alpha rule is admitted.
Retain the two-pass tie tolerance, then distance and canonical keys; for F
construct the tie set within the unchanged score tolerance of maximum Qhat.

Test constant Yhat=0 separately on real/synthetic pools: Qhat=I-I_anchor.
All safe candidates tie in Yhat and closest-to-anchor geometry normally
retains the anchor. Verify canonical ID versus effective-parameter equivalence
and zero-distance aliases explicitly; do not silently force anchor ID or
describe the baseline as random. If non-equivalent aliases exist, report the
control discrepancy and keep N as the explicit incumbent arm. No random
financial selector or extra learner is needed for this question.

Common frozen policy rules apply to every alpha. These comparisons isolate
components under fixed logged information; they do not prove a threshold or
ranking rule should become a global default. Native search still uses TPE;
absence of a meta model does not mean the whole pipeline learned nothing.

<a id="mlr-d3"></a>
### 12.3 Prefix Diagnostic Explanations And Sampler Evidence

Reuse `quantbt.diagnostics` rather than add another profiler. On all monthly
IS pools, export attempted/complete/pruned counts, unique effective candidates,
conditional branches, active dimensions, inactivity/missing metrics, native
cluster/fallback and selected-versus-anchor coordinates. Distinguish nominal
dimension, observed variation and any qualified effective-dimension estimate.

Deep inspection uses each alpha's first actually mature origin, fold 40 and
fold 56, selected for chronology/support, not outcomes. Reuse only authorized
local probes and continuous-IS environment attribution. Report unavailable
probe/return-path/episode evidence explicitly instead of simulating new broad
panels or converting one aggregate Sharpe into a floor or fragility score.

For Ridge, report exact served prediction contributions in the model's own
scaled coordinates, including raw-IS/activity terms, coefficient stability,
historical constant/OOD features and current anchor distance. Separately show
Qhat=deltaIS-Yhat. Correlation or a large IS coefficient is not evidence of
leakage or causal feature importance; IS occurs algebraically in the target.
For X2 reuse existing diagnostics; no SHAP dependency or new feature tournament.

Adaptive TPE pools support observed coverage and score distributions, not
neutral-design Sobol indices, an independent plateau volume, or unbiased global
sensitivity. Respect the shared module's association suppression for adaptive/
reviewed rosters. Only existing structured, prefix-authorized probes can support
their named local assertions; missing probes become a bounded next-test request.

Cold-reconcile the completed 19-quarter/365D fast-variant factorial experiment:
sampler-only at fixed selector/meta-off, selector-only within a sampler's pool,
and their interaction. Keep original objective/budget/source identities. Compare
duplicates, actual sampler fallback, feasible support, native fallback and R/Q;
do not use final equity alone or conditional winners-only losses to rank samplers.

Output one advisory row per alpha: compatible sampler/selector, evidence basis,
observed strengths/weaknesses, competing explanation, missing proof and next
falsifiable test. Distinguish compatibility, measured variant response and
original-alpha evidence. A retrospectively reconstructed shortlist cannot be
called a successfully tested pre-search router. No new sampler study is run.

<a id="mlr-d4"></a>
### 12.4 Missing-Winner Inventory And Bounded Queries

First bind every sealed N/R/X/G/F winner to an existing raw IS observation and
qualified forward witness. Rank the full pool regardless of label membership.
Separate missing execution from existing NO_VARIANCE/invalid measurement: a
rerun does not cure an undefined Sharpe or supply a missing campaign contract.

Deduplicate a query by exact alpha/source, effective params, data snapshot,
preload/cutoff, forward window, account/initial-terminal state, constraints,
route/native and metric contract. Same params with a different account/state
or window do not authorize reuse. Protect model/history receipts as immutable.

Proposed additional budget: **128 distinct missing-winner forward executions
and four known-witness parity controls, at most 132 calls including retries**.
Register the exact queue after predictions are sealed and before new financial
outcomes are opened. Query choice may use missingness/contract and fixed policy
priority, never observed Q/R, attractive predicted gains, or economic results.

Priority is X evaluation winners across all 32 months/alpha, then G, then F.
Within each priority use fixed alpha round-robin and chronological origin order;
deduplicate common winners and skip already witnessed/undefined observations.
The X ceiling of 4 x 32 is before reuse; no unsupported promise is made that
all G/F winners will fit the remaining budget. First pilot <=8 calls includes
one retained-witness control per alpha and the first missing X winner per alpha
where available. Controls may be the only calls if nothing is missing.

Keep original full forward months and required indicator preload/actual
feedback. Use saved IS observations; no fresh 730D search/scoring pass to obtain
an existing metric. Match each control with original stored observations and
account quantities under existing tolerances before admitting that alpha's new
queries. Missing required warmup/state provenance fails admission rather than
approximating a faster route. Reuse immutable preparations but never account,
order, strategy, model or RNG state across independent candidates.

New witnesses cannot be acquired merely to discover a better unseen winner.
They evaluate decisions already selected without that outcome. If the query
cap or CPU guard prevents completion, preserve exact missing IDs/coverage and
bound the conclusion. Missing Sharpe values are unbounded without assumptions;
do not invent finite full-policy worst/best bounds. Remaining G/F evidence may
support mechanism checks while their economic effect stays unqualified.

<a id="mlr-d5"></a>
### 12.5 Required Measurements And Uncertainty

For each observed candidate s relative to anchor a, independently verify:

```text
D_s = I_s - O_s
R_s = D_a - D_s
Q_s = O_s - O_a
IS_contribution_s = I_a - I_s
R_s = IS_contribution_s + Q_s
deltaR_XR = R_X - R_R; deltaQ_XR = Q_X - Q_R
```

Report raw levels and differences, not division by near-zero signed IS or R.
Use raw Sharpe from the qualified metric contract, never the native clustering
objective. Account-return/day and costs/activity can supplement where original
raw paths exist; they do not fill undefined Sharpe or replace the target.

Five required tables:

1. **Decision value:** eligible/model-ready/same-ID/same-effective/changed/
   fallback counts, observed/null counts and dates, all-policy and changed-only
   mean/median R/Q/IS contribution. Help/harm/tie refers explicitly to realized
   Q sign, with R sign reported separately. Missing changed outcomes never count
   as losses, wins or zero. Same-action contrasts are zero only when their metric
   operands are defined; undefined flat Sharpe retains its disposition.
2. **Downside and guard reliability:** worst Q, mean negative Q, positive/negative
   magnitude totals per eligible month, loss concentration and mean worst 20% Q
   using fractional empirical mass when >=10 observed folds. Otherwise the tail
   summary is insufficient, with individual adverse cases retained. Show
   Qhat-pass but Q<0 and Q<-0.10 rates, signed calibration bias, their denominators
   and changes under G. A predicted guarantee is never inferred.
3. **Selection opportunity:** on the fixed preexisting observed base panel plus
   anchor, show whether an alternative has higher forward quality, and qualified
   finite-panel regret. Keep the full old winner union as sensitivity. Attribute
   missed observed opportunity to guard exclusion versus ordering. New winner
   queries are shown separately, not added to the old panel to inflate its
   apparent headroom. Failure to find a better observed candidate does not prove
   no better candidate exists elsewhere in the pool or search domain.
4. **Prefix explanation:** candidate geometry/activity/native fallback, actual
   feature support and prediction contribution, available local/environment
   evidence, selected versus full witnessed-label errors, limitations and rival
   explanations. Optional associations are descriptive, not learned routing.
5. **Quarterly sampler/selector response:** matched existing factorial contrasts,
   coverage/feasibility and R/Q, separate from original monthly policies.

Primary new uncertainty family, proposed before execution: N versus R and R
versus X, each R and Q on four alphas = **16 fixed coordinates**. Report each
alpha's points and support; equal-origin within alpha and equal-alpha macro only
on explicitly matched supported masks. Never silently drop an alpha, substitute
zero, pool candidate rows or let VWAP's tiny sample masquerade as precision.

For a coordinate's numerical interval require its complete 32-month paired
metric calendar, >=12 valid origins/365 days and at least four complete
three-month blocks. Use shared three-month moving-block indices, 16,384 draws,
seed 731 and family95% Bonferroni across all 16 reserved coordinates. Keep that
divisor even when other coordinates are unsupported. Missing coordinates get
no numerical interval; no calendar compression/interpolation. This is an
explicit new exploratory inference plan that lets supported coordinates be
described separately; it does not repair or rewrite the earlier all-family
INCONCLUSIVE receipt. Intervals condition on fixed reviewed recipes/logged
history and do not include full optimizer/model-selection uncertainty.

G/F, subgroup, tail and diagnostic associations are descriptive mechanism checks,
with support and observed consistency. They have no confirmatory CI or promotion
claim here. Prediction MSE remains a secondary matched-label table, not the
decision acceptance criterion. No threshold/rule is fitted from these outcomes.

<a id="mlr-d6"></a>
### 12.6 Concrete Research Decisions

Each alpha and the common-method card must select one leading next action or
NO_CLEAR_WINNER, cite measured quantities and explain the strongest competing
interpretation. These are directions for the next owner decision, not changes
to deployed defaults or an alpha-name policy router.

| Observed pattern | Proposed next action | Evidence needed before a later activation |
|---|---|---|
| R improves decay with nonnegative mean Q and supported uncertainty | KEEP_RIDGE_RESEARCH | Original R/Q support; breadth/limits and account scope remain explicit |
| R improves R mainly through lower IS, with negative Q concentrated in changed folds | ANCHOR_RETENTION_OR_GUARD_STUDY | G must avoid harm without an unreported loss of opportunity; test a fixed retention rule on fresh reserved chronology |
| F improves forward quality on matched observed decisions while R's low-Y winners are weak | RANKING_OBJECTIVE_STUDY | Independent protocol for Q-oriented decision semantics and decay trade-off; no claim training target was fixed by reranking |
| X improves MSE but not decision Q/R, or adds downside | DO_NOT_EXPAND_MODEL_SEARCH | Report prediction-versus-top-decision mismatch and missing support; keep V1 available |
| Better candidates already occur in the witnessed panel but predictions misorder them | TARGETED_DESCRIPTOR_OR_CALIBRATION_STUDY | Identify one causal feature/calibration hypothesis, available-prefix inputs and incremental cost |
| Observed support is thin, native falls back often, and matched quarterly sampler contrasts support a direction | TARGETED_SAMPLER_STUDY | Exact compatible sampler/space and original-route confirmation; no universal TPE failure claim |
| Undefined/sparse outcomes or conflicting groups/years prevent a conclusion | INCONCLUSIVE_WITH_EXACT_GAP | List absent witnesses/support, the smallest informative next test and its estimated cost |

For descriptive favorable decay call out R>0 and Q>=0 separately. A stronger
supported statement requires the new interval for R to exclude zero positively
and Q's lower bound >=-0.05 Sharpe, while point Q remains nonnegative. X's
incremental assessment uses deltaR_XR/deltaQ_XR under the same rule. This is a
proposed next-research interpretation, not a replacement for old nomination or
production gates. G/F cannot obtain that badge without a later registered test.

The final report must answer: how often learning helped/hurt, how badly it hurt,
whether positive decay is real forward retention, whether the guard was
miscalibrated, what witnessed candidate opportunity was missed, whether existing
sampler evidence supports a change, and which exact experiment deserves the
next unit of budget. Do not end only with "need more data" or a model ranking.

<a id="mlr-d7"></a>
### 12.7 Cost, Stop Rules And Deliverables

Proposed extra ceilings: <=160 learner fits total including controls/retries,
<=20 CPU-minutes cold/fit/analysis, <=132 original-route execution calls and
<=2 CPU-hours financial work. The financial cap includes all candidate setup,
preload/compilation, controls, retries and query execution, not just engine
timing. Count report/software tests separately with their actual work bill;
verification cannot hide a second research run. No optimizer, new broad probes,
fresh features/model families, full WFO or continuous challenger account.

Measure the <=8-call pilot and forecast the exact remaining roster before
launching it; report worker CPU versus elapsed wall separately. A hard ceiling
is not a promised ETA. Guard stops leave partial immutable receipts and require
an explicit reduced-scope disposition or later budget amendment; no silent
shortened windows, lower trials, changed routes or favorable query ordering.

Reuse the existing private CPU-only XGB wheel and native/environment. At most
two one-thread workers, total owned RSS <=1.5 GiB, host available >=512 MiB.
Incremental retained evidence <=128 MiB and scratch <=64 MiB; preserve >=5 GiB
free bytes after projected peak and check inodes. Reference existing paths by
hash; use compact predictions/daily witnesses, no full market copies or verbose
per-bar JSON. Pause between lanes to clean exact inactive fixture scratch.

Planned private root: `upgrade/private/meta_model_research_v1/ml06/attempt-01/`;
future attempts use new immutable directories. Only its registered `scratch/`
subdirectory is a cleanup candidate after host owner checks. Preserve private
strategy/params, originals, source/failed receipts, native/dependency artifacts.
Existing cleanup budgets/receipts are not retroactively changed.

Deliver `M4_ML_06_DECISION_VALUE_REPORT.md`, a sanitized JSON with the five
tables/action cards, private origin/witness ledgers, registration, focused
oracle/causality/control tests and terminal cost/privacy/cleanup receipts.
Source work belongs in small research/report adapters over existing shared
owners. No production source/default/ABI change, public learner switch, package
dependency, build, push, CI or release. M5-11.7/M5-12 remain separately approved.

<a id="mlr-s13"></a>
## 13. Structural Forward And Joint Decision Research: M4-ML-07

**COMPLETE_LOCAL_REGISTERED_RESEARCH / technical PASS:** the owner authorized continuing local research and
evidence, including sampler and selector effects, without deciding production
adoption. Read the [phase contract](implement.md#m4-ml-07). Register the finite
roster, policy definitions and budget before new outcomes. All old reviewed
results and earlier positive RSI evidence remain unchanged; this experiment is
exploratory, not untouched OOS or a new-family nomination.
The [completed report](../docs/meta_selection/M4_ML_07_FORWARD_DECISION_REPORT.md)
and [closure](../benchmarks/optimization/meta_selection/model_research_v1/ml07_closure.json)
retain mixed decision effects and all outside-budget/undefined cases. Approved
protocol bytes are preserved privately; no production target or default changes.

### 13.1 Why The Structural Baseline Differs

The existing target is Y=deltaIS-Q. Compare Yhat=0 (equal predicted decay) with
Yhat=deltaIS (equal predicted forward quality, Qhat=0) on identical label IDs,
origin weights and missingness. For every predictor, Y-error is negative
Q-error; squared/absolute errors must agree. Report per-origin/group MSE/MAE,
zero-reference skill and support; no whole-year or candidate-count reweighting.

The structural baseline does not necessarily retain the anchor: with min-Y it
prefers the lowest IS, since all candidates pass Qhat=0; with max-Q all tie and
the unchanged distance rule prefers the anchor. Test this on synthetic and
real scored pools. Do not run a special financial arm just to exploit low IS.

### 13.2 One Same-Family Target Experiment

On exactly the original monthly/730D as-of union and fitted scaler, estimate
Q directly by origin-sum Ridge with lambda10, no intercept and unchanged
features/weights. No new family or hyperparameter grid. A Q regression is not
identical to the original Y regression under regularization: shrinking Y toward
zero and shrinking Q toward zero impose different priors on the known IS term.
Use existing Rust numeric transform/solve plus independent reference parity;
never change the production target or masquerade the new fit as frozen V1.

At each original evaluation origin, score the entire source-valid IS pool.
Use the original whole-pool OOD fallback. Research QD ranks by implied
Yhat=deltaIS-Qhat; research QF ranks by max Qhat; both use Qhat>=-0.10 and
unchanged distance/canonical ties. Keep original N/R and ML06 X/F comparisons
separate and matched. Every new winner is sealed before additional witnesses.
Exact original snapshot/scaler/labels include only available historical records;
new ML06/07 queried outcomes never enter these fits.

### 13.3 Causal Retention Without A Confidence Claim

Gate only the original Ridge proposal. Use the latest published historical
month before the current month as window end, then its preceding11 consecutive
months. End-date eligibility uses only month and publication clock, never Q or
status; the original publication lag must not make every gate vacuous. Accept
when all12 decisions have valid raw Q, publication clocks<=cutoff and mean Q>0.
Otherwise retain the current native anchor.
Require all12 calendar months; no compressing around flat/undefined/missing
months. Never inspect current/future Q before the gate; no alpha-specific
threshold or outcomes-based tuning. This empirically tests abstention, not a
probabilistic lower confidence bound, market-stationarity or capital guarantee.
Measure all-policy/changed-policy value and selected support explicitly.

### 13.4 Sampler X Selector X Meta

Use all qualified19-quarter legacy/group-TPE x native/floor x off/active
arms, not only favorable quarters. Own-family history/anchor and original
raw metric witnesses must match. Show all-calendar, fitted and actually learned
subsets and fallback; cold-start identity must not dilute or manufacture learned
effect. Compute own-anchor meta effects, sampler/selector effects and matched
difference-in-differences on common valid quarter IDs. Missing metrics stay null.
Keep quarterly/365D fast variants separate from monthly/730D originals.
Additional existing Mode5 CMA/Sobol evidence may inform feasibility questions,
but does not certify a Mode4 prefix router or a new full-WFO result.

### 13.5 Queries, Verification And Resources

Reuse exact existing witnesses before querying. Fixed new priority QF then QD,
fold chronological then original group order; outcomes cannot change admission.
At most32 original-route financial calls including up to four parity controls,
<=15 CPU-minutes financial work. No search/IS repeat. Query observations are
evaluation-only, with original metric/account clocks and independent daily
oracle. Outside-cap candidates remain unqualified, not failures or zero Sharpe.

Cold work <=15 CPU-minutes and <=300 numeric/reference fit charges including
controls/qualification. At most128 primary fits, strict Rust/reference parity,
fresh future-mutation/past-positive controls and pure independent tests. No
new optimizer, bootstrap family/promotion inference, dependency/environment,
build, push, CI or release. Retain <=64MiB compact new evidence, scratch<=32MiB,
reserve>=5GiB; owned RSS<=1.5GiB and available RAM>=512MiB. Preserve old source,
account/model/failed evidence; remove only reviewed inactive exact scratch.

Deliver separate source-bound registration/seals, structured losses, retention
and factorial tables, target/ranking decisions with missingness, actual work,
technical qualification, cleanup and a concrete research recommendation.
Do not transfer an alternate winner's history into the old policy or call the
logged-history comparison a self-consistent deployment rollout.

### 13.6 Further Methods Remain Hypotheses

Conservative selection, learned pairwise ranking and off-policy/bandit methods
may be useful future directions, but require their own assumptions and support.
The [conservative-bandit paper](https://proceedings.mlr.press/v48/wu16.html)
does not make this empirical retention gate a theorem-backed safe algorithm.
[Counterfactual risk minimization](https://jmlr.csail.mit.edu/beta/papers/v16/swaminathan15a.html)
uses logged-feedback/importance-weighting assumptions; no propensities are
fabricated for deterministic acquired panels. Do not claim unbiased IPS/DR or
unobserved full-pool regret from the current partial witnesses. These references
motivate questions, not adoption or evidence of improved alpha returns.
