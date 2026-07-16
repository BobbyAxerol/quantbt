# Phase 7 Profiling Follow-Up

Status: standard profile decomposed into backend timing buckets.

Generated on the current research environment with:

```bash
MPLCONFIGDIR=/tmp PYTHONPATH=/root/bobby/pool_alpha poetry run python3 quantbt/benchmarks/profile_phase7.py --profile standard --repeats 2 --json-out quantbt/benchmarks/out/phase7_profile_standard.json --md-out quantbt/benchmarks/out/phase7_profile_standard.md
```

The profiler intentionally measures the core backend layers without
`tracemalloc` runtime tracing so it can identify optimization targets with less
measurement distortion. It is a diagnostic complement to
`benchmarks/run_phase7.py`, not a replacement for the full benchmark harness.

## Standard Profile Breakdown

Profile: 25,000 bars, 20 symbols, 25,000 explicit orders, 2 repeats.

| backend | stage | seconds | share | notes |
| --- | --- | ---: | ---: | --- |
| `native_vectorized` | `data_normalization` | 0.122720 | 26.3% | validate_datetime + align OHLC/signals/funding |
| `native_vectorized` | `target_sizing` | 0.249551 | 53.6% | compute signal_notional target units |
| `native_vectorized` | `pandas_to_ndarray` | 0.072099 | 15.5% | build contiguous kernel arrays |
| `native_vectorized` | `pure_numba_kernel` | 0.006030 | 1.3% | compiled _engine_units_v2 only |
| `native_vectorized` | `result_report_construction` | 0.015537 | 3.3% | Series/DataFrame/BacktestResultV2 construction |
| `native_event` | `data_normalization` | 0.110676 | 16.2% | validate_datetime + align OHLC/funding |
| `native_event` | `pandas_to_ndarray` | 0.069493 | 10.1% | build contiguous market arrays |
| `native_event` | `order_array_construction` | 0.477603 | 69.7% | sort orders, map enums, build order_ptr |
| `native_event` | `pure_numba_kernel` | 0.009015 | 1.3% | compiled _engine_event_v1 only |
| `native_event` | `result_report_construction` | 0.018268 | 2.7% | order report + Series/DataFrame/BacktestResultV2 |

## Interpretation

The current evidence does **not** justify Cython/C++ kernel work.

The pure Numba kernels are about 1.3% of the measured backend-layer runtime for
both `native_vectorized` and `native_event`. The misses in the full Phase 7
standard benchmark are therefore most likely dominated by Python/Pandas facade
work and benchmark instrumentation overhead, not by the simulation kernels.

## Optimization Priority

1. `native_event`: optimize order-array construction.
   - Avoid repeated `pd.Timestamp` conversion per order.
   - Pre-map enum codes before repeated runs.
   - Use vectorized/searchsorted timestamp mapping where possible.
   - Cache reusable order arrays when orders are unchanged across optimizer
     runs.

2. `native_vectorized`: optimize target sizing and alignment.
   - Move `signal_notional` target sizing to an ndarray/Numba path.
   - Avoid per-symbol `pd.Series` construction in hot scoring loops.
   - Add reusable aligned-array cache for WFO/grid-search runs.

3. Shared data path: reduce repeated pandas normalization.
   - Cache validated UTC index and aligned OHLC arrays per dataset.
   - Separate immutable market-data preparation from per-parameter target
     generation.

4. Benchmark harness: keep memory tracing separate from runtime thresholds.
   - Continue collecting peak memory with `tracemalloc`.
   - For runtime thresholds, prefer a no-tracemalloc path or clearly label the
     current numbers as traced-runtime measurements.

## Decision

Stay with Python/Numba. Do not start Cython/C++ until profiling after the
facade/cache work still shows a pure kernel hotspot.
