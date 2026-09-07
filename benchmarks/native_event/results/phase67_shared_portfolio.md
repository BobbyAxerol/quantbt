# Phase 67 Rust Shared-Account Portfolio Benchmark

This evidence measures only the explicit linear gross-cross,
same-close portfolio-target contract. It does not benchmark generic
portfolio planning, pandas reports, risk parity, packages, or callbacks.

| Workload phase | Median seconds |
|---|---:|
| `request_preparation` | 0.025300 |
| `prepared_score` | 0.002390 |
| `prepared_compact` | 0.005394 |
| `prepared_wfo_score` | 0.028462 |

- Bars/symbols: `2000` / `20`
- Score throughput: `16735462.3` bar-symbols/s
- WFO throughput: `44972256.6` bar-symbol-candidate-folds/s
- WFO candidates/folds: `16` / `2`
- Score/compact terminal parity: `True`
- WFO prepared parity: `True`
- Shared-account policy: `reduce_first_then_increase`
- Generic order arena used: `False`
- RSS start / prepared / score / WFO: `151.30` / `155.39` / `158.41` / `173.18` MiB

`prepared_score` is a repeat execution of an immutable Rust request after
market/template/request preparation. `prepared_wfo_score` includes the
native candidate-fold execution and metric matrix, but not Python strategy
generation. Compact retention is intentionally listed separately from score.
