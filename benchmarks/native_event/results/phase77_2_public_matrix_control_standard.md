# Phase 77.1 Public Workload Baseline

This is a non-promotional baseline captured before Phase 77.2 changes dispatch or accounting.
Each requested/resolved route is explicit. A fallback is evidence of an authority boundary, not a zero-speed native result.

## Profile

- Profile: `standard`; bars: `10000` at `1h`; split: `quarterly` after `180D` training; trials: `64`; repeats: `5`.
- Status: `baseline_only_not_promotion_eligible`.

## Public Matrix

| Workload | Lane / resolution | Median | Native score rows | Selection contract |
|---|---|---:|---:|---|
| `mode1_global_w0_native_eligible` | prepared-native / `native_prepared` | 0.402158 s vs 0.846064 s reference | 24 | one retrospective study; declared fold OOS participates in decay selection |

## Legacy `%_equity` Contract

- First bar is a snapshot: `True`.
- Funding is charged to the carried position: `True`.
- An unchanged signal after margin rejection is not retried: `True`.
- Fraction and percentage allocation aliases agree: `True`.
- Public position output remains raw signal weights: `True`.

See `docs/contracts/pct_equity_transition_v1.md` and `docs/performance/public_wfo_baseline_v1.md` for the executable scope, work-count definitions, and Phase 77.2/77.3 gates.

## Separate Scope Evidence

The rows above are W0 public callback evidence only. The following routes retain their own comparator and are not included in a W0 speed ratio:

| Route | Evidence | Boundary |
|---|---|---|
| `reactive_w3` | `benchmarks/native_event/results/phase76_reactive_wfo.json` | No W0 comparator or generic walk_forward speedup claim. |
| `direct_target_vectorized` | `benchmarks/native_event/results/phase66_rust_target_vectorized.json` | Not generic callback WFO or legacy pct_equity. |
| `shared_account_portfolio` | `benchmarks/native_event/results/phase67_shared_portfolio.json` | Not a single-symbol public WFO score route. |
| `bounded_package` | `benchmarks/native_event/results/phase68_bounded_package.json` | Not a generic package/arbitrage WFO promotion claim. |
