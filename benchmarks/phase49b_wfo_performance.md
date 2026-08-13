# Phase 49B WFO Prepared Context And Scalar Scoring

Status: **pass**

All comparisons use identical bars, folds, trials, strategy, seed, account, and accounting kernels.
Warm runtime excludes explicit warm-up; peak RSS is measured in isolated child processes.

| Scenario | Bars | Studies x trials | Reference | Optimized | Speedup | Reference RSS | Optimized RSS |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `portfolio_global` | 1000 | 1 x 16 | 0.3857s | 0.3295s | 1.17x | 247.6 MB | 247.7 MB |
| `single_per_fold_causal` | 1000 | 6 x 16 | 4.0513s | 1.7808s | 2.27x | 308.8 MB | 308.4 MB |

## Parity

- `portfolio_global`: pass=`True`, equity diff=`0.0`, position diff=`0.0`, params/trial/candidate order unchanged.
- `single_per_fold_causal`: pass=`True`, equity diff=`0.0`, position diff=`0.0`, params/trial/candidate order unchanged.

The reference is the Phase 49A prepared-market path with public result/report construction and full Optuna user attrs.
The optimized path adds run-local prepared WFO slicing, array-first scalar reports, and compact post-selection ledgers.
Strategy code is still executed for every trial; QuantBT does not cache arbitrary user indicators or signals.
