# M4-ML-07 - Structural Forecasts And Joint Decision Research

## Disposition

**Local technical scope complete; exploratory research only.** Keep frozen
Ridge V1 available. No learner, target, sampler, selector, endpoint, account
engine or default is changed in the package. Earlier positive RSI evidence and
all prior four-alpha receipts remain intact. No automatic alpha-name router,
universal replacement or live-performance guarantee follows.

Read the [approved research protocol](../../upgrade/implement.md#m4-ml-07),
[supplemental methodology](../../upgrade/QUANTBT_MODE4_META_LEARNER_RESEARCH_GUIDE_V1.md#mlr-s13),
[machine tables](../../benchmarks/optimization/meta_selection/model_research_v1/ml07_summary.json)
and [preceding decision-value report](M4_ML_06_DECISION_VALUE_REPORT.md).

## Scope And Fair Comparisons

The primary corpus is original SC/HMA/HASH/VWAP ETHUSDT1h, rolling730D,
57 monthly origins/alpha and previously executed128 attempts/origin. Evaluation
is the original32 months, February2024--September2026; the13 acquisition and12
development origins are not relabeled as independent test data. All new models
use the same qualified original as-of union, descriptor/scaler, origin-balanced
weights and lambda10. No new feature, model family, parameter range, optimizer
proposal, IS financial execution or hyperparameter search is introduced.

The separate quarterly/365D fast-variant experiment supplies19 quarters and
the complete legacy/group-TPE x native/floor x meta-off/active factorial. These
variants are not original-alpha route-equivalence proofs and are not pooled
with the monthly data. Their learned subset is at most six quarters: the other
quarters mainly document cold start. Sparse/undefined metrics stay null.

Every target-Q winner was sealed before new forward queries. Four fresh
original-route controls and28 missing-winner queries complete;45 further distinct
winner queries remain outside the32-call cap. Selection always ranks the full
eligible IS pool, never only candidates with existing forward labels. Query
priority is QF then QD, chronological fold then fixed group order, deduplicated
by the existing exact financial identity, without inspecting Q/R.

This is conditional replay on the original logged acquisition history. Queried
outcomes never train subsequent models. It is not a self-consistent alternate
label-acquisition rollout or a continuous account for a newly deployed policy.
All outcomes have been reviewed in research; no untouched OOS claim is made.

## Structural Forecasting Control

Let deltaIS=I_candidate-I_anchor and Q=O_candidate-O_anchor. Then
Y=deltaIS-Q, Qhat=deltaIS-Yhat and prediction errors obey eY=-eQ.

- Yhat=0 assumes equal decay; it does not mean equal forward quality.
- Yhat=deltaIS assumes Qhat=0, retaining the known IS component without learning
  the unknown forward component.
- With min-Y, the latter favors the lowest IS. On all169 scored original pools
  it selects a non-anchor ID. With max-Q, the unchanged ties retain the anchor
  ID on169/169. The59 unscored origins remain NOT_SCORED.
- This is a forecast-loss/control check, not a newly executed lowest-IS arm or
  a recommendation to select weak candidates to make signed decay attractive.

Matched acquired-label evaluation MSE, equal-origin within each alpha:

| Alpha | Origins / labels | Yhat=0 | Qhat=0 structural | Ridge V1 | X2 | Direct-Q Ridge |
|---|---:|---:|---:|---:|---:|---:|
| SC | 21 / 254 | 3.66528 | 3.74691 | 3.34782 | 3.52452 | 3.33916 |
| HMA | 32 / 496 | 18.08647 | 15.56192 | 17.35970 | 17.01322 | 16.97598 |
| HASH | 32 / 507 | 18.43588 | 18.73836 | 18.66410 | 18.43453 | 18.89770 |
| VWAP | 12 / 117 | 16.16333 | 14.35331 | 14.56986 | 15.16516 | 13.86884 |
| Equal-alpha descriptive macro | Four groups, own matched masks | 14.08774 | 13.10013 | 13.48537 | 13.53436 | 13.27042 |

These are exactly matched label masks across models within each group, not
selected-winner losses or candidate-count-weighted group averages. Each group's
support differs; macro is conditional on these four acquired panels, not a
population skill estimate. Y/Q MSE and MAE identities pass independent oracles.

Ridge skill versus the stronger Qhat=0 reference is +10.65% SC, -11.55% HMA,
+0.40% HASH and -1.51% VWAP. Direct-Q gives +10.88%, -9.09%, -0.85% and +3.38%.
The macro Direct-Q MSE is about1.59% below Ridge but remains worse than Qhat=0.
Thus some old loss gains primarily reflected the reference chosen; SC still
shows useful forward-prediction skill on this panel. Neither observation
erases existing RSI evidence or proves no potential in other schemas/regimes.

## Same-Family Target And Ranking

The new research model minimizes sum(w*(Q-V beta)^2)+10*||beta||^2 using the
same existing Rust numeric owner, independently checked against weighted solves.
QD ranks min impliedY=deltaIS-Qhat; QF ranks maxQhat. Both retain the original
Qhat>=-0.10 guard, geometry/ties and whole-pool OOD fallback. No fitted coefficient
or new target is installed into V1.

Changing target is not just renaming: on the same basis,
beta_Q=beta_deltaIS-beta_Y, whereas the original implied Qhat is
deltaIS-V beta_Y. Regularization shrinks the known IS term differently. This
is a prior/decision experiment, not new information about future prices.

Matched incremental QF versus original Ridge decisions:

| Alpha | Paired months /32 | Delta R | Delta Q | Help / harm / tie |
|---|---:|---:|---:|---:|
| SC | 20 | +0.15628 | +0.27265 | 3 / 4 / 13 |
| HMA | 30 | +0.76875 | +1.39576 | 13 / 4 / 13 |
| HASH | 30 | -1.76282 | -0.99972 | 11 / 12 / 7 |
| VWAP | 8 | -0.57293 | -0.16763 | 3 / 2 / 3 |

Raw monthly Sharpe-difference units, not account returns. These are each
contrast's paired months, not subtraction of unequal-mask full-policy means.
The remaining masks cannot be filled with zeros or extrapolated to full policy.

HMA is the clearest direction worth a separate study, but the target alone does
not explain all of it. QF versus old max-Q F isolates target change: DeltaQ is
+0.30478 on29 months. QF versus QD isolates ranking under the new predictions:
+1.37365 on23 months. These masks differ, so the numbers cannot be added to
decompose the30-month effect. HASH's QF-minus-Ridge DeltaQ is -0.99972; its
target-only QF-minus-F effect is -0.19926 on30 months. Do not promote one recipe
from HMA while ignoring the contradictory HASH cell.

## Causal Anchor Retention

The fixed empirical gate uses the latest published historical month and its
preceding11 consecutive months. All12 original Ridge Q observations must be
VALID, available before current cutoff and have positive mean. End-month choice
uses only clocks/months, not outcome values. No gap compression, alpha-specific
threshold or new query labels are allowed. Publication lag is respected.

| Alpha | Gate accepts /32 | Actual changed params /32 | Matched DeltaQ versus Ridge | Paired months |
|---|---:|---:|---:|---:|
| SC | 1 | 1 | +0.01178 | 20 |
| HMA | 4 | 4 | +0.52854 | 32 |
| HASH | 18 | 15 | -0.14360 | 32 |
| VWAP | 0 | 0 | +0.09980 | 11 |

Retention limits HMA's observed mean Q deficit versus native from -0.60748 to
-0.07895, but reduces mean R from+1.20754 to+0.22217. Its worst20% Q is -1.40297
versus Ridge -6.99688, partly because most decisions retain the anchor. This is
not proof of improved account drawdown or a statistical safety guarantee.
HASH loses both useful opportunity and some downside. VWAP's all-anchor result
comes from insufficient complete calendars, not evidence that meta lacks edge.
SC's near-neutral increment depends on one accepted changed decision.

## Sampler, Selector And Meta Together

The existing factorial supports a genuine new cold decomposition. Below,
group-TPE minus legacy-TPE uses the native selector, with off and active effects
reduced on the exact same valid quarters in each row:

| Alpha | Paired quarters /19 | Sampler effect Q, meta off | Sampler effect Q, meta active | Meta interaction |
|---|---:|---:|---:|---:|
| SC | 17 | +0.09355 | +0.60953 | +0.51598 |
| HMA | 16 | +0.54848 | +0.75386 | +0.20538 |
| HASH | 19 | -0.10235 | -0.39876 | -0.29641 |
| VWAP | 8 | -0.61534 | -0.65403 | -0.03869 |

This is not a universal group-TPE recommendation. Most early quarters are
cold-start; complete learned subsets have at most six pairs, with gaps. The
machine tables additionally separate fitted/actually-learned/fallback/change
cohorts and all selector and triple-interaction contrasts.

Own-anchor meta Q on actually learned, observed quarters demonstrates coupling:

| Alpha | Legacy/native | Group/native | Legacy/floor | Group/floor |
|---|---:|---:|---:|---:|
| SC | -1.15438 (5) | +0.98143 (4) | +0.09085 (5) | +0.54590 (5) |
| HMA | +0.07465 (5) | +0.91484 (4) | -0.53146 (6) | -0.25707 (6) |
| HASH | +0.80457 (6) | -0.13406 (6) | -0.61227 (6) | -0.61008 (6) |
| VWAP | +0.30954 (1) | N/A (0) | -0.02109 (4) | -1.29069 (6) |

Each number compares meta with its own sampler/selector anchor. Different
counts prohibit interpreting column subtraction as a matched treatment effect.
This evidence shows why sampler, anchor policy and meta history must be tested
together; one learner leaderboard cannot decide the full pipeline.

Other samplers were not silently excluded: the existing
[RSI matched sampler study](../mode5/M5_11_2_MATCHED_SAMPLER_REPORT.md) tests256
proposals each for legacy/group TPE, CMA-ES and Sobol. Legacy's development raw
Sharpe2.66281 exceeds group2.39967, CMA1.69246 and Sobol1.85112 on that one tape.
The separate [full-scope floor study](../mode5/M5_11_5_DECISION_QUALIFICATION_REPORT.md)
finds CMA's lower DD but TPE's better registered floor objective. These are
different domains/objectives, not a Mode4 CMA/Sobol qualification for all alphas.
No repeated optimizer or new sampler winner is invented here.

## Technical Qualification, Cost And Limits

52 focused source tests PASS, including independent target/weighted-loss
oracles, future-label/published-calendar mutation, ties, query priority/dedup,
factorial raw measurements/masks and existing R/Q reducers. Twelve actual fresh
target-Q controls at25/40/56 retain the exact original snapshot/predictions after
unavailable future corrections. The permitted-past HMA40 correction changes
served predictions by4.51764, proving the control is not a cached tautology.
Original source-bound route/market proofs are reused, not advertised as newly
rerun price-mutation or installed/public certification.

The work is141 logical fits /286 numeric-reference charges, zero optimizer
proposals, and32 original-route financial calls including four exact controls.
Primary and control fits use53.47 CPU seconds; factorial readback19.54 seconds.
Financial stages use178.30 CPU /179.42 wall seconds, roughly three minutes,
not the runtime of a new full WFO. Current analysis/report verification and
software tests are separate costs. The retained machine receipts bind exact
sources, old/new query identities and actual per-process peaks.

All initial failed test/setup receipts remain: an invalid-cutoff test fixture,
two delegated test oracles, a missing pytest scratch parent and an over-specific
fixture path assertion were corrected. No financial trial was rerun, threshold
relaxed, original outcome edited or private strategy published to make results
positive. See [cleanup](../maintenance/M4_ML_07_CLEANUP.md).

## Concrete Research Recommendation

1. **Keep frozen V1 available, do not globally replace it.** SC has forward
   prediction skill here; HASH's original learned decisions retain useful
   positive points that QF/blanket abstention can lose. Original RSI evidence
   remains an independent positive reference in its own contract.
2. **Prioritize decision-aligned target/ranking and support.** HMA's observed
   QF signal warrants a separately frozen original-route confirmation, with
   complete missing-witness inventory and downside. Do not call the current
   conditional partial-mask gain independent robust transfer.
3. **Research an evidence-aware accept/retain mechanism, not the12-month rule
   as a default.** The simple rule demonstrates the opportunity/downside
   trade-off, but sparse strategies need a meaningful support contract rather
   than mechanically forcing every month to have finite Sharpe.
4. **Keep diagnostics before recipe choice.** Use prefix-eligible geometry,
   conditional branches, activity, fallback and matched sampler response.
   HMA/group and HASH/legacy are research hypotheses, not name-based routes.
   Another sampler/space or anchor changes compatibility and must acquire its
   own causal history; do not reuse an incompatible trained model.
5. **Only then consider a pairwise ranker plus a calibrated magnitude head.**
   Ranking could align decision loss, but pairs within one origin are not
   independent evidence; it still needs forward-magnitude/guard calibration.
   Hierarchical transfer requires shared descriptors or explicit schema
   adapters, not forced common coefficients across different parameter spaces.

These are next-research choices, not applied changes. A bandit/conservative
policy is another direction, not an already certified guarantee: the
[Conservative Bandits paper](https://proceedings.mlr.press/v48/wu16.html) proves
results under its own assumptions. Similarly,
[counterfactual risk minimization](https://jmlr.csail.mit.edu/beta/papers/v16/swaminathan15a.html)
uses propensity-scored logged feedback. Current deterministic partial panels
do not supply those propensities; no unbiased IPS/DR or full-pool oracle claim
is made. M5-11.7/M5-12, production adoption, CI and release await owner approval.
