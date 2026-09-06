# Phase 74 Public Walk-Forward Prepared-Native Benchmark

This artifact is a post-warmup full-facade comparison, not a kernel-only claim.
Both lanes execute the same W0 Python callback, Optuna lifecycle, Mode 1
selection, Rust final stitched account, and cold result adaptation. Only candidate/fold
fresh-account scoring uses the Phase 73 prepared-native runtime in the native lane.

| Lane | Median full WFO | Median scorer |
|---|---:|---:|
| Historical endpoint scorer | 1.053044 s | 0.800033 s |
| Prepared-native scorer | 0.431730 s | 0.166156 s |

| Measured phase | Historical endpoint | Prepared-native |
|---|---:|---:|
| Prepare + fold plan | 0.034850 s | 0.034288 s |
| Python strategy generation | 0.139506 s | 0.142608 s |
| Candidate/fold scorer | 0.800033 s | 0.166156 s |
| Rust prepared execute within scorer | 0.000000 s | 0.025927 s |
| Residual control/reconstruction/report | 0.084030 s | 0.088678 s |

- Full-facade speedup: `2.44x`
- Candidate-score speedup: `4.81x`
- Native candidate/fold score rows per run: `168`
- Native score batches per run: `17`
- WFO bars: `2048`; Optuna trials: `16`; repeats: `5`
- Full-facade scored candidate-bar visits/s: `127181.2`
- Process peak RSS: `221.984 MiB`; steady-tail median: `221.984 MiB`
- Native RSS tail spread: `0.008 MiB`
- Exact selection/final-account parity: `True`

The residual is deliberately not presented as a precise report-only timer: it includes
Optuna control, selection/reducers, final stitched reconstruction, and cold result/report
adaptation. The directly measured Rust time is the prepared execute portion inside score.

The prepared scorer remains opt-in. It does not alter default WFO behavior, candidate
selection, parameter sampling, strategy lifecycle, signal timing, or final account
reconstruction. See `docs/native_prepared_wfo_public.md` for the compatibility matrix.
