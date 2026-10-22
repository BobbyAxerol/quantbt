# M4-ML-06 - Research Interpretation And Next Decisions

Read the [registered experiment](../../upgrade/implement.md#m4-ml-06),
[full tables](M4_ML_06_DECISION_VALUE_REPORT.md) and
[machine summary](../../benchmarks/optimization/meta_selection/model_research_v1/ml06_summary.json).
These are reviewed, conditional comparisons on original ETHUSDT1h monthly730D
histories. They preserve the earlier RSI evidence and do not choose a new public
default. Q is the difference in forward raw Sharpe for the same month; R is the
reduction in signed IS-minus-forward Sharpe. Neither is a return percentage or
whole-account Sharpe.

## What Learning Actually Added

| Alpha | Ridge R vs native | IS contribution | Ridge Q vs native | Valid months | Help / harm / tie |
|---|---:|---:|---:|---:|---|
| SC | +0.9643 | +0.5959 | +0.3684 | 20/32 | 12 / 8 / 0 |
| HMA | +1.2075 | +1.8150 | -0.6075 | 32/32 | 13 / 19 / 0 |
| HASH | +1.9284 | +1.6835 | +0.2449 | 32/32 | 14 / 14 / 4 |
| VWAP | +1.6476 | +1.7474 | -0.0998 | 11/32 | 5 / 5 / 1 |

Ridge changes effective params on124/128 evaluation origins. Native already
includes128-attempt IS search and robust native selection. It is a meaningful
incumbent, not random. On all169 scored real zero-prediction controls, Yhat=0
retains the same effective anchor;59 earlier unsupported controls remain explicit.

There are positive forward points for SC/HASH and negative ones for HMA/VWAP.
Lower IS explains more than the entire positive R for HMA/VWAP. This establishes
heterogeneity within these cells, not that historical learning never helps.
Numerical intervals for supported HMA/HASH coordinates include zero; SC/VWAP
lack a complete metric calendar. None establishes a universal replacement.

## The Fixed Ablations Gave Different Answers

All differences below are computed on each contrast's own paired months.

| Alpha | X2 minus Ridge Q | Guard0 minus Ridge Q | RankQ minus Ridge Q |
|---|---:|---:|---:|
| SC | -0.7224 (16) | +0.2587 (20) | -0.2522 (19) |
| HMA | +0.8410 (32) | +0.3738 (32) | +0.8736 (26) |
| HASH | -0.8320 (32) | -0.1224 (32) | -1.1708 (26) |
| VWAP | +1.4089 (9) | -0.5723 (11) | -1.5641 (5) |

HMA provides a useful research signal for a different decision rule or learner.
HASH shows why the same change cannot be made globally from that one result.
VWAP's nine/five paired months cannot support a strong model/ranking conclusion.
Twenty-six RankQ witnesses are outside the registered128-query budget. Their
missing outcomes are never replaced by zeros or selectively acquired afterward.

Average prediction loss also does not settle winner value: on HASH's matched
evaluation acquired-label panel, X2 MSE is18.4345 versus Ridge18.6641, while its
selected forward quality worsens by0.8320. Selection concentrates on a particular
part of the error distribution, and the min-Y decision includes an IS trade-off.
This is evidence to inspect decision calibration and ranking before buying a
larger model search, not proof that prediction quality is irrelevant.

## What Diagnostics Do And Do Not Explain

There is already observed candidate headroom in the feature-dependent base
panel:14/20 SC,31/32 HMA,29/32 HASH and9/11 VWAP supported Ridge decisions have
a witnessed base candidate with better forward Sharpe. Ex-post best candidates
are frequently excluded by the predicted guard or misordered within it. These
overlapping counts are explanatory; the future-best candidate was not known at
selection time, and a small acquired panel is not the full-pool oracle.

The median absolute contribution of the raw-IS descriptor to Ridge's selected
Yhat is about22.1% SC,25.2% HMA,41.5% HASH and37.5% VWAP. This does **not** support
claiming that one IS feature alone dominates every model. Contributions are
scaled-model arithmetic, not causal importance or general sensitivity.

Guard reliability matters beyond mean bias. HMA Ridge accepts19/32 defined
decisions with negative realized Q; Guard0 still accepts18/32. HASH Ridge's
average Q prediction bias is nearly zero, yet14/32 realized decisions are
negative. A zero mean error or stronger predicted threshold is not calibrated
decision confidence or an outcome guarantee.

Observed native fallback is21/57 HMA and39/57 HASH; SC uses the medoid on57/57.
These are concrete support/geometry observations. They do not prove TPE failed
to generate a usable candidate. Existing quarterly fast-variant contrasts help
separate hypotheses: group-TPE sampler-only Q is+0.5485 for HMA on16 quarters,
but -0.1023 for HASH on19. Floor selection is not uniformly helpful. Variant
response and prefix input eligibility do not certify an automatic original-alpha
sampler router. Structured original-prefix local probes/environment paths are
unavailable here; full-development Mode5 evidence cannot fill earlier inputs.

## Concrete Next Research Choice

Keep frozen Ridge V1 available and avoid another broad family tournament now.
The next useful common-procedure question is whether a policy should retain its
native anchor when historical evidence for a proposed change is weak. It needs
a separately frozen confidence/support rule and reserved chronology; these
outcomes cannot be used to tune a per-alpha deployment threshold.

An inexpensive preparatory test worth registering is the stronger structural
no-learning predictor **Yhat=deltaIS**, which implies **Qhat=0**. The previous
Yhat=0 comparator assumes equal decay; it does not remove the already known IS
component from the forecasting question. A matched-label loss/calibration
comparison could isolate how much the learner predicts unknown forward quality.
It needs no optimizer or financial executions; a proposed cap is120 CPU seconds
on retained predictions/labels, subject to separate approval. It was **not run**
inside the five-policy experiment and cannot be inserted retrospectively as an
extra winning arm.

For sampler research, prioritize a specific prefix coverage hypothesis only
when source-bound geometry and the existing matched response support it.
HMA's current declared space fails default CMA-ES preflight; HASH passes. Schema
compatibility is not measured superiority or dependency admission. A new space
helper/representation or acquisition recipe needs its own identity and test.

The current experiment conditions on old logged winner-union history. A future
replacement must distinguish that conditional analysis from acquisition history
that would evolve under the replacement's own decisions. No queried outcome
enters the original histories here. Software correctness/causality passes;
economic robustness and unseen-period confirmation remain separate questions.
