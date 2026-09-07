# Phase 66 Rust Direct Target Benchmark

This is a same-fixture, warmed comparison of the narrow
`close_target_v2_same_close` target-units contract. It is not a
generic endpoint, callback, grid, portfolio, or full-report benchmark.

| Phase | Median seconds |
|---|---:|
| `rust_ingestion_market_template_request` | 0.014833 |
| `rust_prepared_score` | 0.001607 |
| `numba_warmed_kernel` | 0.000607 |
| `rust_public_compact` | 0.023432 |
| `numba_public_compact` | 0.058600 |

- Bars: `20000`
- Symbols: `1`
- Repeats: `9`
- Rust prepared score throughput: `12448451.7` bars/s
- Numba warmed kernel throughput: `32971101.1` bars/s
- Rust prepared / Numba kernel ratio: `0.378x`
- Rust public compact / Numba public compact ratio: `2.501x`
- Exact accounting parity: `True`
- Score retains path arrays: `False`
- Score native passes / boundary calls: `1` / `1`
- Generic order arena used: `False`
- Prepared market cache entries: `1`
- RSS process start / score-warm / score-timed: `150.75` / `210.27` / `213.28` MiB
- Score steady-state RSS delta: `3.01` MiB
- RSS after public compact benchmark: `225.73` MiB

`rust_prepared_score` times one typed Rust execution request after its
market/template/request ingestion. Its steady-state RSS delta is measured
only after native/Numba warm-up, so extension loading and public result
construction are not misreported as score-mode retention. `rust_public_compact`
includes pandas normalization and `BacktestResultV2` materialization, which
is why it must not be interpreted as a pure-kernel figure.
