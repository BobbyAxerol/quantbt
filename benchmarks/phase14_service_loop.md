# Phase 14C Prepared Cache And Report-Level Benchmark

Status: **pass**

## Profile

- Rows: `360`
- Symbols: `4`
- Optuna trials: `4`
- Order count: `120`
- Repeats: `2`

## Service Loop Timings

| workload | cold/full seconds | prepared/light seconds | speedup | peak MB | parity | notes |
| --- | ---: | ---: | ---: | ---: | --- | --- |
| single-symbol WFO | `1.007189` | `0.883450` | `1.140x` | `0.427` | `True` | compares uncached vs prepared single-symbol native-vectorized WFO endpoint scoring |
| portfolio WFO | `0.439526` | `0.325665` | `1.350x` | `0.778` | `True` | compares uncached vs prepared portfolio WFO endpoint scoring |
| native-event replay | `0.009587` | `0.004569` | `2.098x` | `0.180` | `True` | prepared replay reuses market arrays and compiled order arrays |
| arbitrage sweep | `0.074623` | `0.066327` | `1.125x` | `0.949` | `True` | compares native-event arbitrage package cold vs prepared market-array replay; vectorized parity remains audited |
| portfolio report levels | `0.041000` | `0.023349` | `1.756x` | `0.916` | `True` | compares native-portfolio report_level='full' vs 'minimal' construction with core accounting parity |

## Stage Decomposition

| backend | stage | seconds | share |
| --- | --- | ---: | ---: |
| `native_vectorized` | `data_normalization` | `0.003493` | `51.87%` |
| `native_vectorized` | `pandas_to_ndarray` | `0.001979` | `29.39%` |
| `native_vectorized` | `target_sizing` | `0.000008` | `0.11%` |
| `native_vectorized` | `pure_numba_kernel` | `0.000031` | `0.46%` |
| `native_vectorized` | `result_report_construction` | `0.001223` | `18.16%` |
| `native_event` | `data_normalization` | `0.002687` | `39.88%` |
| `native_event` | `pandas_to_ndarray` | `0.001580` | `23.45%` |
| `native_event` | `order_array_construction` | `0.000745` | `11.06%` |
| `native_event` | `pure_numba_kernel` | `0.000058` | `0.86%` |
| `native_event` | `result_report_construction` | `0.001668` | `24.75%` |
| `native_portfolio` | `array_preparation` | `0.005382` | `21.03%` |
| `native_portfolio` | `pure_numba_kernel` | `0.000047` | `0.18%` |
| `native_portfolio` | `report_construction_estimate` | `0.020163` | `78.79%` |

## Parity Guards

- `single_symbol_wfo`: `True`
- `portfolio_wfo`: `True`
- `native_event_replay`: `True`
- `arbitrage_package_sweep`: `True`
- `report_heavy_vs_light`: `True`

## Next Optimization Targets

- native_vectorized: `data_normalization` (51.9%)
- native_event: `data_normalization` (39.9%)
- native_portfolio: `report_construction_estimate` (78.8%)
- Next step should be real workload profiling before considering Cython/C++; Phase 14C moved the main cache/report controls into opt-in APIs.

## Cython/C++ Decision

Cython/C++ is not justified yet. The measured bottleneck remains in facade/report/preparation layers. Phase 14C added opt-in cache threading and report-level controls; larger real service-loop profiles should come before any Cython/C++ decision.

This report is a measurement artifact. It must not be used to justify changing accounting, fill policy, margin, or report semantics.
