# Phase 48E.1 Native Production Closure Benchmark

Contract: **2,000 bars**, one symbol, fresh process per route, `7` warm runs.
All runtime columns use seconds; RSS uses MB.

## Common Native Event / Event-Driven

| Workload | Route | Cold prepare s | Warm median s | P95 s | Bars/s | Peak RSS MB | Fills | Status |
|---|---|---:|---:|---:|---:|---:|---:|---|
| common_low_churn | `common_python_score` | 0.092669 | 0.085853 | 0.124378 | 23,296 | 182.2 | 30 | ok |
| common_low_churn | `common_rust_score` | 0.224590 | 0.218293 | 0.267495 | 9,162 | 185.7 | 30 | ok |
| common_low_churn | `common_python_audit` | 0.507892 | 0.095110 | 0.096007 | 21,028 | 239.4 | 30 | ok |
| common_low_churn | `common_rust_audit` | 0.624691 | 0.230769 | 0.247618 | 8,667 | 242.1 | 30 | ok |
| common_high_churn | `common_python_score` | 0.099162 | 0.091562 | 0.121379 | 21,843 | 182.1 | 98 | ok |
| common_high_churn | `common_rust_score` | 0.265705 | 0.222166 | 0.288145 | 9,002 | 185.1 | 98 | ok |
| common_high_churn | `common_python_audit` | 0.513898 | 0.104712 | 0.166593 | 19,100 | 239.6 | 98 | ok |
| common_high_churn | `common_rust_audit` | 0.625303 | 0.237654 | 0.280276 | 8,416 | 241.4 | 98 | ok |

## Explicit Native Event Lifecycle

| Workload | Route | Cold prepare s | Warm median s | P95 s | Bars/s | Peak RSS MB | Fills | Status |
|---|---|---:|---:|---:|---:|---:|---:|---|
| explicit_low_churn | `explicit_python_score` | 0.007029 | 0.023777 | 0.024740 | 84,114 | 180.4 | 32 | ok |
| explicit_low_churn | `explicit_rust_score` | 0.008598 | 0.000289 | 0.000323 | 6,921,851 | 181.6 | 32 | ok |
| explicit_low_churn | `explicit_python_audit` | 0.005986 | 0.007385 | 0.008217 | 270,814 | 237.7 | 32 | ok |
| explicit_low_churn | `explicit_rust_audit` | 0.008947 | 0.004357 | 0.005949 | 459,060 | 182.0 | 32 | ok |
| explicit_high_churn | `explicit_python_score` | 0.006964 | 0.021689 | 0.022251 | 92,214 | 180.2 | 100 | ok |
| explicit_high_churn | `explicit_rust_score` | 0.009407 | 0.000366 | 0.000378 | 5,461,021 | 181.9 | 100 | ok |
| explicit_high_churn | `explicit_python_audit` | 0.006354 | 0.013703 | 0.014699 | 145,952 | 239.6 | 100 | ok |
| explicit_high_churn | `explicit_rust_audit` | 0.011131 | 0.006469 | 0.008694 | 309,174 | 183.1 | 100 | ok |

## Contract

- Score and audit are never compared as the same artifact.
- Python/Rust parity groups: `{"common_high_churn:audit": true, "common_high_churn:score": true, "common_low_churn:audit": true, "common_low_churn:score": true, "explicit_high_churn:audit": true, "explicit_high_churn:score": true, "explicit_low_churn:audit": true, "explicit_low_churn:score": true}`.
- Python/Rust parity is exact on the supported full-contract fields; unavailable Rust capabilities are reported, not silently routed to Python.
- Reactive Grid is intentionally excluded from this common table and is recorded separately in `upgrade/implement.md`.
