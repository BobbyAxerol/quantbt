# PERF-05 WFO Evaluation Reuse Benchmark

The cache is intentionally narrow: an adaptive Optuna objective always executes and
stores its completed terminal metrics; only later report-only candidate analysis may
reuse the exact same prepared-native economic execution. It is run-local and released
before the public result returns.

## Mode 1 Cache Economics

| Lane | Median public WFO | vs off | Median scorer | vs off | Hits | Reused score bars | Stores | Evictions |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| zero_hit_policy_off | 0.410082 s | +0.00% | 0.143177 s | +0.00% | 0 | 0 | 0 | 0 |
| mixed_bounded_lru | 0.426044 s | -3.89% | 0.157398 s | -9.93% | 0 | 0 | 168 | 167 |
| high_hit_run_local | 0.399369 s | +2.61% | 0.131516 s | +8.14% | 32 | 11680 | 136 | 0 |

The lanes share the same W0 callback, seed, Optuna interaction, selector, final
stitched account, and report adaptation. Timing is descriptive rather than a release
threshold: cache lookup hashes and repeated Python strategy generation remain real work.

## Five-Mode Contract Matrix

| Mode | Baseline / reuse parity | Reuse state | Hits | Notes |
|---|---|---|---:|---|
| mode_1_decay | True | enabled_then_released | 8 | run_local_pure_terminal_native_metrics |
| mode_2_sbb | True | disabled | 0 | scorer_has_no_pure_terminal_reuse_contract |
| mode_3_flat_minima | True | enabled_then_released | 8 | run_local_pure_terminal_native_metrics |
| mode_4_is_only_robust | True | enabled_then_released | 8 | run_local_pure_terminal_native_metrics |
| mode_5_full_robust | True | disabled | 0 | mode_5_has_no_post_study_exact_score_reuse |

Mode 2 remains the existing deterministic proxy/resampling authority; no native
terminal-score cache is enabled for it. Mode 5 can legitimately show zero hits because
its full-IS selector may not rerun an identical candidate execution after the study.

RSS peak: `226.105 MiB`; tail spread: `0.000 MiB`; released cache evidence: `True`.

This is not a generic WFO, reactive, portfolio, package, or Mode 2 throughput claim.
See `docs/performance/perf_05_wfo_evaluation_reuse.md` for eligibility and rollback.
