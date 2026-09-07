# Phase 77.2 Percent-Equity Public WFO Evidence

This is a paired legacy-versus-explicit-Rust `%_equity` transition contract measurement.
It is not a generic WFO, portfolio, reactive, or Mode 2 speed claim.

## Workload

- `10000` bars at `1h`, `quarterly` folds, `64` trials, and `5` alternating post-warm repeats.
- Reference: legacy transition-sized `pct_equity` engine.
- Native: `target_runtime='rust'` plus `native_prepared_wfo='require'`.
- Score adapter: `scalar_columns_v1`; no per-row Python score dataclass/dict is created inside the score boundary.

## Result

| Lane | Median | P95 | Native score rows |
|---|---:|---:|---:|
| legacy reference | 1.557729 s | 1.856350 s | 0 |
| explicit Rust transition | 0.698355 s | 0.790971 s | 48 |
- Paired speedup: `2.231x` (same named workload only).

## Contract

- Rust preserves first-bar snapshot, transition-only resize, no drift rebalance, funding on carried units, rejection-without-retry, and raw public signal positions.
- A conflicting legacy/V2 fee or slippage declaration fails closed rather than producing a falsely comparable run.
- Full parity includes selection, stitched output, equity, returns, raw positions, and public metrics before samples are recorded.
