# Pre-48E Native Event Performance Pass

Contract: **2,000 bars**, one symbol, fresh process per route, `7` warm runs.
All runtime columns use seconds; RSS uses MB.

## Common Native Event / Event-Driven

| Workload | Route | Cold prepare s | Warm median s | P95 s | Bars/s | Peak RSS MB | Fills | Status |
|---|---|---:|---:|---:|---:|---:|---:|---|
| common_low_churn | `common_python_score` | 0.155789 | 0.148483 | 0.178355 | 13,470 | 191.7 | 30 | ok |
| common_low_churn | `common_rust_score` | 0.243247 | 0.232064 | 0.273768 | 8,618 | 185.5 | 30 | ok |
| common_low_churn | `common_python_audit` | 10.033179 | 0.166945 | 0.290534 | 11,980 | 316.3 | 30 | ok |
| common_low_churn | `common_rust_audit` | 0.766556 | 0.250250 | 0.311978 | 7,992 | 244.1 | 30 | ok |
| common_high_churn | `common_python_score` | 0.161803 | 0.165390 | 0.199771 | 12,093 | 182.4 | 98 | ok |
| common_high_churn | `common_rust_score` | 0.257076 | 0.246971 | 0.273962 | 8,098 | 185.9 | 98 | ok |
| common_high_churn | `common_python_audit` | 0.565547 | 0.167247 | 0.214455 | 11,958 | 241.6 | 98 | ok |
| common_high_churn | `common_rust_audit` | 0.768561 | 0.254275 | 0.319207 | 7,866 | 243.4 | 98 | ok |

## Explicit Native Event Lifecycle

| Workload | Route | Cold prepare s | Warm median s | P95 s | Bars/s | Peak RSS MB | Fills | Status |
|---|---|---:|---:|---:|---:|---:|---:|---|
| explicit_low_churn | `explicit_python_score` | 0.006925 | 0.020644 | 0.026682 | 96,882 | 181.3 | 32 | ok |
| explicit_low_churn | `explicit_rust_score` | 0.009175 | 0.001032 | 0.001999 | 1,937,178 | 182.5 | 32 | ok |
| explicit_low_churn | `explicit_python_audit` | 0.006763 | 0.009188 | 0.009675 | 217,680 | 239.6 | 32 | ok |
| explicit_low_churn | `explicit_rust_audit` | 0.008255 | 0.002404 | 0.003944 | 832,012 | 183.0 | 32 | ok |
| explicit_high_churn | `explicit_python_score` | 0.006610 | 0.021454 | 0.041569 | 93,224 | 180.6 | 100 | ok |
| explicit_high_churn | `explicit_rust_score` | 0.011422 | 0.001358 | 0.002529 | 1,472,565 | 183.0 | 100 | ok |
| explicit_high_churn | `explicit_python_audit` | 0.007423 | 0.015307 | 0.016908 | 130,662 | 239.6 | 100 | ok |
| explicit_high_churn | `explicit_rust_audit` | 0.009577 | 0.002879 | 0.003904 | 694,585 | 182.5 | 100 | ok |

## Contract

- Score and audit are never compared as the same artifact.
- Python/Rust parity groups: `{"common_high_churn:audit": true, "common_high_churn:score": true, "common_low_churn:audit": true, "common_low_churn:score": true, "explicit_high_churn:audit": true, "explicit_high_churn:score": true, "explicit_low_churn:audit": true, "explicit_low_churn:score": true}`.
- Python/Rust parity is exact on the supported full-contract fields; unavailable Rust capabilities are reported, not silently routed to Python.
- Reactive Grid is intentionally excluded from this common table and is recorded separately in `upgrade/implement.md`.
