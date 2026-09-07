# Phase 77.1 Public Workload Baseline

This is a non-promotional baseline captured before Phase 77.2 changes dispatch or accounting.
Each requested/resolved route is explicit. A fallback is evidence of an authority boundary, not a zero-speed native result.

## Profile

- Profile: `smoke`; bars: `720` at `1D`; split: `quarterly` after `180D` training; trials: `4`; repeats: `1`.
- Status: `baseline_only_not_promotion_eligible`.

## Public Matrix

| Workload | Lane / resolution | Median | Native score rows | Selection contract |
|---|---|---:|---:|---|
| `mode1_global_w0_native_eligible` | prepared-native / `native_prepared` | 0.096664 s vs 0.200921 s reference | 24 | one retrospective study; declared fold OOS participates in decay selection |
| `mode1_per_fold_decay_w0_native_eligible` | prepared-native / `native_prepared` | 0.156990 s vs 0.265881 s reference | 30 | one independent study per outer fold; same-fold OOS selects among top-IS candidates |
| `mode1_per_fold_causal_w0_native_eligible` | prepared-native / `native_prepared` | 0.367088 s vs 0.820960 s reference | 126 | one study per outer fold; nested inner IS/OOS only, outer OOS remains untouched |
| `mode1_train_test_w0_native_eligible` | prepared-native / `native_prepared` | 0.048617 s vs 0.066555 s reference | 4 | single declared train/test fold; OOS contributes to Mode 1 decay selection |
| `mode2_global_proxy_preserved` | authoritative route / `proxy_preserved` | 0.212643 s | 0 | bounded path-resampling proxy; stationary-bootstrap path construction remains authoritative |
| `mode2_train_test_proxy_preserved` | authoritative route / `proxy_preserved` | 0.067242 s | 0 | single declared train/test with the same bounded path-resampling proxy |
| `mode3_global_w0_native_eligible` | prepared-native / `native_prepared` | 0.096102 s vs 0.200213 s reference | 24 | one retrospective study; cluster/plateau selection after endpoint scoring |
| `mode3_train_test_w0_native_eligible` | prepared-native / `native_prepared` | 0.048792 s vs 0.068353 s reference | 4 | single declared train/test with flat-minima selection |
| `mode4_global_w0_native_eligible` | prepared-native / `native_prepared` | 0.156968 s vs 0.348896 s reference | 48 | one retrospective study; IS-only temporal and plateau robustness |
| `mode4_per_fold_causal_w0_native_eligible` | prepared-native / `native_prepared` | 0.213031 s vs 0.414226 s reference | 48 | one IS-only study per outer fold; strict outer OOS after frozen selection |
| `mode4_train_test_w0_native_eligible` | prepared-native / `native_prepared` | 0.061755 s vs 0.101395 s reference | 8 | single declared train/test; IS-only robust selection |
| `mode5_full_sample_w0_native_eligible` | prepared-native / `native_prepared` | 0.060653 s vs 0.081109 s reference | 4 | full declared sample calibration; no fabricated OOS validation claim |
| `pct_equity_auto_fallback` | authoritative route / `fallback` | 0.600795 s | 0 | legacy transition-sized percent-equity scorer remains authoritative |

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
