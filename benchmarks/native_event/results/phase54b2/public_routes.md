# Phase 54B.2 Public Route Benchmark

Local Stage-B evidence only. Exact Python/Rust audit parity passed before timing.

| Workload | Bars | Rust median | Rust throughput | Python median | Python throughput | RSS peak |
|---|---:|---:|---:|---:|---:|---:|
| Static public audit | 10,000 | 6.024010s | 1,660 bars/s | 5.924252s | 1,688 bars/s | 572.0 MiB |
| Static public compact | 10,000 | 0.063612s | 157,203 bars/s | 0.053606s | 186,545 bars/s | 605.0 MiB |
| Native IR score | 2,000 | 0.000741s | 2,698,268 bars/s | 0.031565s | 63,361 bars/s | 605.2 MiB |
| Native IR cold audit adaptation | 2,000 | 1.268416s | 1,577 bars/s | - | - | 605.2 MiB |
| Native IR public audit | 2,000 | 1.141629s | 1,752 bars/s | - | - | 605.2 MiB |
| Native IR batch | 128,000 | 0.011379s | 11,249,284 bars/s | - | - | 605.3 MiB |
| Native IR causal fold | 64,000 | 0.007386s | 8,665,462 bars/s | - | - | 605.3 MiB |

Score is a typed scalar/compact path. Public audit includes cold Python result adaptation from Rust buffers; neither route replays Python execution.
Callbacks, reactive strategies, portfolio, and package/arbitrage are excluded and remain Python compatibility routes.
