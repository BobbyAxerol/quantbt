# Phase 62 Reactive Numeric Co-runtime Evidence

Python/R0 bridge/R1 held/R1 release four-way parity passes before timing. Numbers include Python strategy callbacks and public result adaptation; they are not comparable to static command-tape kernel figures.

## Sequential

| Workload | Route | Bars | Median | Throughput | RSS retained / released |
|---|---|---:|---:|---:|---:|
| lightweight | python_r0 | 10,000 | 0.232374s | 43,034 bars/s | 5.09 / 0.25 MiB |
| lightweight | rust_bridge_r0 | 10,000 | 1.455479s | 6,871 bars/s | 7.43 / 0.00 MiB |
| lightweight | rust_r1_held | 10,000 | 0.063434s | 157,644 bars/s | 6.92 / 0.00 MiB |
| lightweight | rust_r1_release | 10,000 | 0.069372s | 144,150 bars/s | 6.91 / 0.00 MiB |
| low_churn | python_r0 | 10,000 | 0.233335s | 42,857 bars/s | 5.11 / 0.00 MiB |
| low_churn | rust_bridge_r0 | 10,000 | 1.247289s | 8,017 bars/s | 7.57 / 0.00 MiB |
| low_churn | rust_r1_held | 10,000 | 0.074578s | 134,088 bars/s | 6.91 / 0.00 MiB |
| low_churn | rust_r1_release | 10,000 | 0.067006s | 149,240 bars/s | 6.91 / 0.00 MiB |
| high_churn | python_r0 | 10,000 | 0.561014s | 17,825 bars/s | 4.34 / 0.22 MiB |
| high_churn | rust_bridge_r0 | 10,000 | 1.706106s | 5,861 bars/s | 5.91 / 0.25 MiB |
| high_churn | rust_r1_held | 10,000 | 0.083060s | 120,396 bars/s | 6.09 / 3.70 MiB |
| high_churn | rust_r1_release | 10,000 | 0.088164s | 113,425 bars/s | 6.09 / 3.70 MiB |

## Concurrent R1 high-churn

| Route | Sessions | Aggregate bars | Median | Aggregate throughput | RSS retained / released |
|---|---:|---:|---:|---:|---:|
| rust_r1_held | 2 | 20,000 | 0.211799s | 94,429 bars/s | 5.58 / 4.60 MiB |
| rust_r1_release | 2 | 20,000 | 0.263237s | 75,977 bars/s | 0.84 / 0.00 MiB |

Low-churn held-GIL performance eligibility: `True`.
R1 remains explicit in Phase 62 regardless of this result: it is a Rust-led/Python-callback hybrid, and sparse/block routing is a later capability.
