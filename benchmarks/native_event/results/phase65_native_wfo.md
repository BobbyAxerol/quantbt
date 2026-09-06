# Phase 65 Native WFO Runtime Benchmark

The score route is bounded single-symbol StrategyIR only. Times are
median wall seconds on the local machine; they are not a generic WFO claim.

| Phase | Median seconds |
|---|---:|
| `runtime_prepare` | 0.039792 |
| `strategy_prepare` | 0.000113 |
| `strategy_generate` | 0.022473 |
| `intent_ingest` | 0.297496 |
| `native_score_and_metrics` | 0.232514 |
| `legacy_fold_oracle` | 0.319437 |
| `cold_report` | 0.000741 |
| `optimizer_end_to_end` | 0.385955 |

- Candidates: `64`
- Folds: `4`
- Bars: `4096`
- Native worker count: `2`
- Candidate-fold-bar throughput: `4509729.8`
- Persistent runtime / prior fold-oracle score ratio: `1.374x`
- Exact prior fold-batch oracle parity: `True`
- Score path market/candidate execution copies: `0` / `0` bytes

`intent_ingest` is the one controlled Python-to-Rust copy. `native_score_and_metrics`
keeps command compilation, execution, and scalar metric reduction fused in Rust;
`cold_report` is intentionally measured separately.
