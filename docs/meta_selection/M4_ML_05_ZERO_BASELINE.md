# ML-05 Supplement - Fixed-Zero Prediction Baseline

2026-10-17, Asia/Saigon. Owner approved a cold descriptive check, not new
calibration, nomination, model/default activation or a change to prior gates.
Read the [plan supplement](../../upgrade/implement.md#m4-ml-05),
[research metric contract](../../upgrade/QUANTBT_MODE4_META_LEARNER_RESEARCH_GUIDE_V1.md#mlr-s7)
and [machine summary](../../benchmarks/optimization/meta_selection/model_research_v1/ml05_zero_summary.json).
Historical ML-03..05 reports/closures remain unchanged.

## Matched Measurement

Predict Y=0 for every scored non-anchor candidate. Y is candidate decay minus
native-anchor decay: zero means equal relative decay, not zero absolute decay.
No mean, model, transform or hyperparameter is fitted for this baseline.

All six models use exactly the same qualified label IDs within each origin.
Their MSE is independently recomputed from saved predictions and matches the
previous table. Masks are checked, not silently intersected. Every origin gets
equal weight within its alpha, then each of four alphas gets equal macro weight.
Anchors do not dilute error; unsupported/no-prediction origins are not zeros.
Primary base panel: 33 supported origins, 451 labels; union sensitivity:
33 origins, 476 labels. Each panel excludes 15 unsupported origins explicitly.

## Primary Results

`zero-reference skill = 1 - macro_MSE_model / macro_MSE_zero`.
This is not classical mean-reference R-squared, nor a confidence/economic gate.

| Predictor | Macro MSE | Reduction versus zero |
|---|---:|---:|
| Constant Y=0 | 10.712354 | Reference |
| Ridge V1/P0 | 9.750550 | 8.98% |
| Bayesian B1 | 9.735193 | 9.12% |
| Huber 1.35 | 9.703855 | 9.41% |
| Huber 2.0 | 9.791370 | 8.60% |
| XGBoost depth 2 | 9.497639 | 11.34% |
| XGBoost depth 3 | 9.815357 | 8.37% |

| Alpha | Origins | Zero MSE | Ridge MSE | Ridge skill | X2 MSE | X2 skill |
|---|---:|---:|---:|---:|---:|---:|
| SC | 7 | 9.525720 | 8.686758 | 8.81% | 8.457787 | 11.21% |
| HMA | 12 | 13.031509 | 13.111602 | -0.61% | 14.446969 | -10.86% |
| HASH | 12 | 15.633563 | 13.502214 | 13.63% | 12.202530 | 21.95% |
| VWAP | 2 | 4.658622 | 3.701625 | 20.54% | 2.883272 | 38.11% |

Union sensitivity: zero 10.951997, Ridge 10.338150 (5.60% skill), X2 9.896349
(9.64% skill). The two panels are related, not independent confirmation. VWAP
has only two supported origins; its large point improvement is especially weak
evidence for generalization. HMA exposes a genuine predictive weakness here.

## Interpretation And Verification

The original absolute MSE now has a meaningful comparator: Ridge and the new
models reduce macro prediction error versus fixed zero, but gains are modest
and not universal. X2 adds about 2.36 percentage points of zero-reference skill
over Ridge; its relative MSE reduction versus Ridge remains 2.59%, not 11.34%.
Lower MSE does not establish better top-candidate R/Q, returns or decay.

This is reviewed development evidence on feature-dependent acquired labels,
not independent future OOS, a full-pool outcome oracle, a statistical significance
claim or proof against every stronger no-skill baseline. It does not change the
prior KEEP_V1 disposition or invalidate earlier RSI economic evidence.

Execution used 25.12 CPU seconds, 468.45 MiB peak RSS, zero fits, zero optimizer
proposals and zero financial calls. Six focused independent oracle/negative
tests PASS. Formatting after execution is AST-identical to archived registered
source; the result was not rerun or edited. Final source tests pass separately.
Exact scratch cleanup, protected hashes and source refs are bound in the
[supplement closure](../../benchmarks/optimization/meta_selection/model_research_v1/ml05_zero_closure.json).
No CI, push, build or release was initiated.
