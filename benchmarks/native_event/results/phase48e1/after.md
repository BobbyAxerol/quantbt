# Phase 48E.1 Native Production Closure Benchmark

Contract: **2,000 bars**, one symbol, fresh process per route, `7` warm runs.
All runtime columns use seconds; RSS uses MB.

## Common Native Event / Event-Driven

| Workload | Route | Cold prepare s | Warm median s | P95 s | Bars/s | Peak RSS MB | Fills | Status |
|---|---|---:|---:|---:|---:|---:|---:|---|
| common_low_churn | `common_python_score` | 0.083326 | 0.079572 | 0.111996 | 25,134 | 181.9 | 30 | ok |
| common_low_churn | `common_rust_score` | 0.211246 | 0.203414 | 0.236553 | 9,832 | 183.5 | 30 | ok |
| common_low_churn | `common_python_audit` | 0.478913 | 0.092881 | 0.109723 | 21,533 | 239.5 | 30 | ok |
| common_low_churn | `common_rust_audit` | 0.601677 | 0.227207 | 0.276393 | 8,803 | 240.5 | 30 | ok |
| common_high_churn | `common_python_score` | 0.092785 | 0.090868 | 0.168074 | 22,010 | 181.9 | 98 | ok |
| common_high_churn | `common_rust_score` | 0.217262 | 0.210942 | 0.259573 | 9,481 | 184.0 | 98 | ok |
| common_high_churn | `common_python_audit` | 0.598122 | 0.108414 | 0.194069 | 18,448 | 239.8 | 98 | ok |
| common_high_churn | `common_rust_audit` | 0.752501 | 0.256986 | 0.346405 | 7,783 | 240.2 | 98 | ok |

## Explicit Native Event Lifecycle

| Workload | Route | Cold prepare s | Warm median s | P95 s | Bars/s | Peak RSS MB | Fills | Status |
|---|---|---:|---:|---:|---:|---:|---:|---|
| explicit_low_churn | `explicit_python_score` | 0.006189 | 0.019994 | 0.022042 | 100,031 | 180.0 | 32 | ok |
| explicit_low_churn | `explicit_rust_score` | 0.009213 | 0.000329 | 0.000340 | 6,088,007 | 181.9 | 32 | ok |
| explicit_low_churn | `explicit_python_audit` | 0.006030 | 0.007410 | 0.008034 | 269,903 | 237.3 | 32 | ok |
| explicit_low_churn | `explicit_rust_audit` | 0.010423 | 0.004529 | 0.005737 | 441,635 | 181.7 | 32 | ok |
| explicit_high_churn | `explicit_python_score` | 0.006485 | 0.024769 | 0.026184 | 80,745 | 179.6 | 100 | ok |
| explicit_high_churn | `explicit_rust_score` | 0.009838 | 0.000382 | 0.000399 | 5,236,015 | 181.3 | 100 | ok |
| explicit_high_churn | `explicit_python_audit` | 0.006740 | 0.013198 | 0.014097 | 151,544 | 236.9 | 100 | ok |
| explicit_high_churn | `explicit_rust_audit` | 0.011486 | 0.005063 | 0.006140 | 394,997 | 182.3 | 100 | ok |

## Contract

- Score and audit are never compared as the same artifact.
- Python/Rust parity groups: `{"common_high_churn:audit": true, "common_high_churn:score": true, "common_low_churn:audit": true, "common_low_churn:score": true, "explicit_high_churn:audit": true, "explicit_high_churn:score": true, "explicit_low_churn:audit": true, "explicit_low_churn:score": true}`.
- Python/Rust parity is exact on the supported full-contract fields; unavailable Rust capabilities are reported, not silently routed to Python.
- Reactive Grid is intentionally excluded from this common table and is recorded separately in `upgrade/implement.md`.
