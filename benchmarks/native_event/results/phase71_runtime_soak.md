# Phase 71 Native Runtime Soak

| Measure | Result |
|---|---:|
| Bars | 4,096 |
| Candidates x folds | 32 x 4 |
| Repeated warm scores | 30 |
| Rust workers | 2 |
| Median warm score | 13.325 ms |
| Throughput | 39.35M candidate-fold-bars/s |
| Steady RSS | 162.98 MiB |
| RSS tail spread | 0.00 MiB |

Terminal fingerprints were deterministic across every warm run. Runtime reset
incremented the worker generation without changing results. Typed cancellation
and post-cancel recovery passed. The prepared batch reported zero market and
intent copy bytes per warm score.

This benchmark covers prepared single-symbol static StrategyIR WFO execution.
It excludes alpha feature generation, Optuna sampler time, and public report
construction.
