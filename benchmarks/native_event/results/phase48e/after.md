# Pre-48E Native Event Performance Pass

Contract: **2,000 bars**, one symbol, fresh process per route, `7` warm runs.
All runtime columns use seconds; RSS uses MB.

## Common Native Event / Event-Driven

| Workload | Route | Cold prepare s | Warm median s | P95 s | Bars/s | Peak RSS MB | Fills | Status |
|---|---|---:|---:|---:|---:|---:|---:|---|
| common_low_churn | `common_python_score` | 0.086664 | 0.094448 | 0.128841 | 21,176 | 182.0 | 30 | ok |
| common_low_churn | `common_rust_score` | 0.226733 | 0.179506 | 0.213566 | 11,142 | 183.9 | 30 | ok |
| common_low_churn | `common_python_audit` | 0.834296 | 0.093893 | 0.118999 | 21,301 | 239.0 | 30 | ok |
| common_low_churn | `common_rust_audit` | 0.607834 | 0.178550 | 0.183053 | 11,201 | 242.6 | 30 | ok |
| common_high_churn | `common_python_score` | 0.113353 | 0.107369 | 0.136062 | 18,627 | 183.5 | 98 | ok |
| common_high_churn | `common_rust_score` | 0.190791 | 0.188549 | 0.230557 | 10,607 | 185.2 | 98 | ok |
| common_high_churn | `common_python_audit` | 0.519198 | 0.106375 | 0.161571 | 18,801 | 241.1 | 98 | ok |
| common_high_churn | `common_rust_audit` | 0.632091 | 0.208654 | 0.289846 | 9,585 | 241.3 | 98 | ok |

## Explicit Native Event Lifecycle

| Workload | Route | Cold prepare s | Warm median s | P95 s | Bars/s | Peak RSS MB | Fills | Status |
|---|---|---:|---:|---:|---:|---:|---:|---|
| explicit_low_churn | `explicit_python_score` | 0.005948 | 0.019206 | 0.020712 | 104,132 | 180.4 | 32 | ok |
| explicit_low_churn | `explicit_rust_score` | 0.009929 | 0.000302 | 0.000319 | 6,614,704 | 180.6 | 32 | ok |
| explicit_low_churn | `explicit_python_audit` | 0.007894 | 0.010003 | 0.012452 | 199,947 | 237.8 | 32 | ok |
| explicit_low_churn | `explicit_rust_audit` | 0.009916 | 0.002505 | 0.003445 | 798,411 | 182.2 | 32 | ok |
| explicit_high_churn | `explicit_python_score` | 0.006085 | 0.021114 | 0.022085 | 94,726 | 180.4 | 100 | ok |
| explicit_high_churn | `explicit_rust_score` | 0.009843 | 0.000392 | 0.000426 | 5,103,342 | 180.8 | 100 | ok |
| explicit_high_churn | `explicit_python_audit` | 0.006447 | 0.012488 | 0.013142 | 160,157 | 238.6 | 100 | ok |
| explicit_high_churn | `explicit_rust_audit` | 0.010717 | 0.003233 | 0.004208 | 618,555 | 183.0 | 100 | ok |

## Contract

- Score and audit are never compared as the same artifact.
- Python/Rust parity groups: `{"common_high_churn:audit": true, "common_high_churn:score": true, "common_low_churn:audit": true, "common_low_churn:score": true, "explicit_high_churn:audit": true, "explicit_high_churn:score": true, "explicit_low_churn:audit": true, "explicit_low_churn:score": true}`.
- Python/Rust parity is exact on the supported full-contract fields; unavailable Rust capabilities are reported, not silently routed to Python.
- Reactive Grid is intentionally excluded from this common table and is recorded separately in `upgrade/implement.md`.
