# PERF-06 Columnar Research Audit Benchmark

This evidence uses the same public WFO request with the optional audit sidecar off and with
`research_retention=full_trial_ledger`. It proves final economic/selection parity first, then
reports the additional latency, owned bytes, chunks, lazy legacy-adaptation cost, and RSS.
A full ledger is a transparency product, so a positive retention overhead is not described as a regression.

| Mode | Public parity | Median no-sidecar | Median full ledger | Retention overhead | Ledger bytes | Chunks | Lazy export | Paired RSS delta |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| mode_1_decay | True | 0.334076 s | 0.424007 s | +26.92% | 356288 | 9 | 0.031196 s | +0.258 MiB |
| mode_2_sbb | True | 0.860088 s | 1.003048 s | +16.62% | 425533 | 9 | 0.041658 s | +0.000 MiB |
| mode_3_flat_minima | True | 0.375305 s | 0.499093 s | +32.98% | 362766 | 9 | 0.039963 s | +0.258 MiB |
| mode_4_is_only_robust | True | 0.646905 s | 0.768804 s | +18.84% | 436534 | 9 | 0.038589 s | +0.000 MiB |
| mode_5_full_robust | True | 0.147896 s | 0.212660 s | +43.79% | 89643 | 6 | 0.015057 s | +0.000 MiB |

RSS peak: `288.934 MiB`; tail spread: `0.523 MiB`.

The slow-sink probe is synchronous owned-chunk backpressure, not a claim of crash durability: `4` chunks, median hook time `0.001069 s`, crash durability `not_provided`.

Paired RSS deltas are same-process warm observations, not cold-process peak claims.
The normal legacy trial/candidate DataFrames remain compatible. The columnar artifact is only
created when a non-default research or financial retention level is explicitly requested.
