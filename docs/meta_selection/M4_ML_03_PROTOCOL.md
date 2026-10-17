# M4-ML-03/04 Finite Family Protocol

## Authority And State

2026-10-17, Asia/Saigon. Owner authorized ML-03, then ML-04, then ML-05.
The [unified plan](../../upgrade/implement.md#m4-ml-03) and
[detailed guide](../../upgrade/QUANTBT_MODE4_META_LEARNER_RESEARCH_GUIDE_V1.md)
remain authoritative. Owner approved the finite roster and private CPU-only
dependency on question `call_9a8224a31af54e74aecaa659471bbdb5`. This worksheet is
**OWNER_APPROVED / DEPENDENCY_ADMISSION_PENDING**, not a completed screening.
Questions
`call_a5c21b3dcd9c40c58ab9e2232efe3cea` and
`call_82d98b76a45b4d4db4bfb80e7ebf18b1` retain the existing loss/R/Q and strict
complete-block contracts. The new roster/dependency approval is recorded before
new learner comparison outcomes; source/artifact admission and create-once
registration still precede execution.

ML-01/02 [retains frozen V1](M4_ML_02_CALIBRATION_REPORT.md). No public learner
registry, production default, financial engine, optimizer, alpha or prior receipt
is changed here. All proposed adapters are under `tools/meta_model_research`,
not published package code. Synthetic oracle work is not market economics.

## Shared Inputs And Proposed Roster

Reuse original ETHUSDT 1h monthly/730D SC/HMA/HASH/VWAP histories and the
13-acquisition / 12-development / 32-evaluation partition. Existing RSI and
quarterly variant evidence stay separate. Primary acquisition is base-only;
winner-union sensitivity and V1 reproduction are not another independent study.
The first frozen calibration frontier remains 2024-01-31 23:00 UTC, strictly
before late January labels. Every learned basis uses its own permitted prefix.

| ID | Proposed recipe | Training/served semantics |
|---|---|---|
| B1 | beta prior N(0,I), fixed sigma squared 1, mean-origin power likelihood | (X'WX+K I) beta=X'Wy; no intercept, fixed prior, not empirical Bayes or calibrated uncertainty |
| H135 | sklearn 1.8 Huber, epsilon 1.35, alpha K*10/12, max_iter 500, tol 1e-8 | concomitant scale, positive origin weights, no intercept; served X beta |
| H200 | same with epsilon 2.0 | separately versioned finite robustness control |
| X2 | xgboost-cpu 3.1.1, depth 2, 64 rounds | raw weighted square-error f; serve g(v)=f(v)-f(0) on every row |
| X3 | same with depth 3 | same anchored transform, not a claim raw training optimizes centered served loss |

XGBoost uses CPU histogram trees, eta .05, min_child_weight 1, lambda 1,
alpha 0, max_bin 64, full rows/columns, nthread 1, seed 731 and base_score 0.
Fixed rounds mean no early-stopping data access. No automatic dependency
installation, GPU/NCCL or mandatory package dependency is permitted. Proposed
CPU-only wheel must have version/hash/build/footprint admission before import.
Versions/recipes and UBJ/JSON payloads are validated; pickle is not used.
The [dependency proposal](../../benchmarks/optimization/meta_selection/model_research_v1/ml03_dependency_proposal.json)
records official PyPI metadata: the x86_64 wheel is 5,303,801 bytes. It has not
been downloaded/installed or build-qualified; a published hash is not yet a
verified local artifact.

X is the existing standardized candidate-minus-origin-anchor descriptor basis;
Y, origin replacement weights, Q floor -0.10, geometry/ties and whole-pool OOD
policy remain unchanged. All candidates are ranked, not just labeled ones.
Train loss is measured on actual served predictions; any library surrogate is
reported separately. B1 is mathematically a different shrinkage control, not a
nonlinear model or newly calibrated posterior guarantee.

## Screening And Conditional Adaptation

Seal source/dependency/corpus pins and the finite work table before new
comparisons. Pilot twelve representative permitted fits across four groups,
using first-mature/middle/final snapshots and B1/Huber/XGB families; then admit
the remaining work from actual timing/RSS and dependency/retention budget.
An absent optional dependency has an explicit DEFER disposition, not a PASS.

Compare the five fixed settings on causal development origins. A common
nomination procedure excludes the held-out group, needs at least three valid
origins in each training group and three complete three-month blocks/group;
duplicate/null/unavailable rows cannot inflate support. Equal group/origin
weights apply on the same complete-block roster used for uncertainty; partial
blocks cannot change nominations. Prefer simpler within one block standard error, nominate at most
two. A nomination is permission for bounded research, not economic promotion.
No supported nominee means KEEP_V1, not retrospective gate relaxation.

One **conditional, proposed** periodic recipe rule is defined for ML-04: update
only at a quarterly boundary, with at least three newly mature, matched-nominee
origins per training group and the same complete-block/calibration rights; keep the current
admitted nominee unless another has at least 2% lower calibration loss.
No update runs without an admitted nominee. This is distinct from causal beta
refitting at each origin. Synthetic tests exercise a real recipe change and
future-mutation invariance; they do not claim an actual market update occurred.
The periodic rule requires owner approval before any real-data use.

## Gates And Budget

Retain the approved loss gain >=2%, family 95% loss/Q/R intervals, Q/R
noninferiority -0.05 Sharpe, minimum paired support and complete-calendar policy.
Model-family multiplicity must include the full executed roster, not only
selected winners. Existing reviewed history remains exploratory, not untouched
external OOS. Missing new-winner outcomes are neither zero nor a reason to
restrict inference to conveniently known winners.

ML-03: <=2,000 challenger fits and <=90 CPU-minutes including retries/controls.
At most two one-thread workers, combined owned RSS <=1.5 GiB, available RAM
>=512 MiB, total incremental retained/scratch/dependency footprint <=256 MiB,
and 5 GiB free disk after projected peak. No optimizer or financial calls.
ML-04: reuse matching original-route witnesses; first <=8 missing-winner pilot
queries, hard <=64 total, <=2 CPU-hours including any admitted full account.
No shorter horizon, proxy endpoint or joined diagnostic equity is substituted.
No full alternative account is claimed without its complete schedule/support.

All models retain full-pool decisions, calibration/nulls, exact applied/proposed
IDs and per-origin predictions privately. Reports must distinguish served loss,
Q/R/IS decomposition, activity/account support and actual work. Keep negative
and failed receipts. Clean only exact inactive synthetic scratch after protected
hash and process review. No push, CI, merge, tag, install into the main
environment or publication is authorized.

## Primary Implementation References

- [sklearn 1.8 Huber contract](https://scikit-learn.org/1.8/modules/generated/sklearn.linear_model.HuberRegressor.html)
- [sklearn Huber implementation 1.8.0](https://github.com/scikit-learn/scikit-learn/blob/1.8.0/sklearn/linear_model/_huber.py)
- [XGBoost 3.1 CPU installation](https://xgboost.readthedocs.io/en/release_3.1.0/install.html)
- [XGBoost 3.1 parameters](https://xgboost.readthedocs.io/en/release_3.1.0/parameter.html)
- [XGBoost stable model IO](https://xgboost.readthedocs.io/en/release_3.1.0/tutorials/saving_model.html)

The 3.1 documentation branch currently displays patch 3.1.3. Execution, if
approved, is pinned to CPU wheel 3.1.1 and its actual library/build metadata;
documentation does not authorize substituting a different dependency version.
