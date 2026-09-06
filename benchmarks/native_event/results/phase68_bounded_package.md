# Phase 68 Bounded Rust Package Benchmark

The evidence covers only explicit same-account linear package intents under
`event_lifecycle_v2_next_bar_close`. Each fixture uses a partial primary
fill with post-actual-fill hedge sizing. It is not a generic arbitrage,
callback WFO, pandas-report, L2, cross-currency, or cross-venue benchmark.

| Prepared one-package workload | Score s | Compact s | Audit s | Score bar-symbols/s |
|---|---:|---:|---:|---:|
| `2 legs` | 0.000413 | 0.000891 | 0.000882 | 9684670.4 |
| `4 legs` | 0.000465 | 0.000977 | 0.001055 | 17219232.3 |
| `20 legs` | 0.000873 | 0.002230 | 0.002218 | 45819289.2 |

- Tape: `2000` bars; one package per declared bar; leg counts `[2, 4, 20]`.
- Scenario score batch: `16` isolated `20`-leg scenarios in `0.013114` s (`48801663.4` bar-symbols/s).
- Scenario native entries / market copies / workers: `1` / `0` B / `1`.
- Profile terminal parity: `True`.
- Batch-vs-selected-single score parity: `True`.
- RSS start / profiles / batch: `149.84` / `168.07` / `170.91` MiB.

`score` retains scalar accounting only. `compact` and `audit` are listed
separately because they materialize progressively more cold-path result
data. The batch resets account, positions, orders, and reservations before
each independent scenario; a selected candidate must be rerun in audit
profile for leg-level provenance.
