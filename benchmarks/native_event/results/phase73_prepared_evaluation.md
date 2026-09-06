# Phase 73 Shared Prepared Evaluation Benchmark

This artifact measures a warm generic prepared target-unit batch. It excludes
Python strategy generation, Optuna, endpoint/report adaptation, and WFO selection.
It must not be used as a generic `walk_forward()` performance claim.

| Phase | Median seconds |
|---|---:|
| `market_template_prepare` | 0.004472 |
| `intent_ingest` | 0.033687 |
| `binding` | 0.004573 |
| `native_execution_and_scalar_adaptation` | 0.016956 |

- Bars: `4096`
- Candidate rows: `64`
- Workers: `2`
- Warm prepared candidate-bar visits/s: `15460558.6`
- RSS tail spread: `0.000 MiB`
- RSS plateau passed: `True`
- Exact repeated terminal rows: `True`

The batch creates one persistent Rust worker pool, crosses the Python/Rust boundary
once per score batch, shares market/template ownership, and returns scalar rows only.
