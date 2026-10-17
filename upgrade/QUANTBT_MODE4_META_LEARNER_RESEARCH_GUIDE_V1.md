# Mode 4 Meta-Learner Research Guide V1

**Date:** 2026-10-17, Asia/Saigon.
**Status:** owner approved sequential M4-ML-01/02 local execution and the finite
protocol on 2026-10-17. M4-ML-01 admission and M4-ML-02 finite replay are
complete locally; see the [comparison](../docs/meta_selection/M4_ML_02_CALIBRATION_REPORT.md).
KEEP_FROZEN_V1: P1 misses the registered improvement gate; P2 lacks complete
calibration blocks and falls back. Owner subsequently authorized sequential
ML-03 -> ML-04 -> ML-05; ML-03 is complete locally with zero supported nominees
under the approved finite protocol. See the
[family report](../docs/meta_selection/M4_ML_03_FAMILY_REPORT.md). The
[worksheet](../docs/meta_selection/M4_ML_03_PROTOCOL.md) records this boundary.
The Ridge baseline remains frozen. No target, production
hyperparameter/default policy or public activation changes are authorized.
**Sequence:** M4-ML-01 -> M4-ML-02 -> M4-ML-03 -> M4-ML-04 -> M4-ML-05,
then separately approved M5-11.7 and M5-12. No automatic phase advance.

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
