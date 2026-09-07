# Phase 69 Rust Intrabar Benchmark

This evidence measures the explicit single-symbol `intrabar_bracket_v1`
OHLC path contract only. It is not evidence for L2 matching, generic event
callbacks, grid/DCA state machines, or shared portfolio margin.

| Workload | Median seconds | Bars/s |
|---|---:|---:|
| Warm Numba standard/path comparator | 0.002053 | 974,199 |
| Rust prepared score kernel | 0.000096 | 20,904,764 |
| Rust prepared compact kernel | 0.000159 | 12,596,246 |
| Rust full adapter, compact result | 0.002538 | 788,099 |
| Rust cold prepare + score request | 0.001006 | 1,987,434 |

- Fixture: `2000` one-hour bars, deterministic long/short entries, SL/TP/trailing, technical exits, fee/slippage, and close-timestamp funding.
- Parity: `True`; score keeps no dense paths: `True`.
- Rust boundary calls: `1`; Python callbacks: `0`.
- RSS start / prepared / profiles: `150.13` / `153.85` / `211.50` MiB.

`score` is a typed native request with scalar output only. `compact` is shown
separately because SoA transfer and pandas result adaptation are cold-path work.
The public route remains explicit; Numba remains the version-pinned rollback
comparator for at least one stable release.
