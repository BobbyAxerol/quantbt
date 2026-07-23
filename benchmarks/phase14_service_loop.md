# Phase 14B Real WFO And Service-Loop Benchmark

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
| single-symbol WFO | `0.948989` | `0.025587` | `37.088x` | `0.300` | `True` | prepared column reports metric/export cost only; single-symbol WFO cache is Phase 14C work |
| portfolio WFO | `0.448197` | `0.402629` | `1.113x` | `0.770` | `True` | compares uncached vs prepared portfolio WFO endpoint scoring |
| native-event replay | `0.009390` | `0.003640` | `2.580x` | `0.181` | `True` | prepared replay reuses market arrays and compiled order arrays |
| arbitrage sweep | `0.066270` | `0.072306` | `0.917x` | `0.949` | `True` | event seconds vs vectorized seconds for the same package accounting |
| report heavy vs light | `0.029557` | `0.000101` | `292.075x` | `0.030` | `True` | measures metrics/report export cost; lazy report controls are Phase 14C work |

## Stage Decomposition

| backend | stage | seconds | share |
| --- | --- | ---: | ---: |
| `native_vectorized` | `data_normalization` | `0.003683` | `54.04%` |
| `native_vectorized` | `pandas_to_ndarray` | `0.001808` | `26.53%` |
| `native_vectorized` | `target_sizing` | `0.000008` | `0.11%` |
| `native_vectorized` | `pure_numba_kernel` | `0.000032` | `0.47%` |
| `native_vectorized` | `result_report_construction` | `0.001285` | `18.85%` |
| `native_event` | `data_normalization` | `0.002709` | `38.32%` |
| `native_event` | `pandas_to_ndarray` | `0.001721` | `24.34%` |
| `native_event` | `order_array_construction` | `0.000872` | `12.33%` |
| `native_event` | `pure_numba_kernel` | `0.000055` | `0.78%` |
| `native_event` | `result_report_construction` | `0.001713` | `24.23%` |
| `native_portfolio` | `array_preparation` | `0.005511` | `20.29%` |
| `native_portfolio` | `pure_numba_kernel` | `0.000044` | `0.16%` |
| `native_portfolio` | `report_construction_estimate` | `0.021610` | `79.55%` |

## Parity Guards

- `single_symbol_wfo`: `True`
- `portfolio_wfo`: `True`
- `native_event_replay`: `True`
- `arbitrage_package_sweep`: `True`
- `report_heavy_vs_light`: `True`

## Next Optimization Targets

- native_vectorized: `data_normalization` (54.0%)
- native_event: `data_normalization` (38.3%)
- native_portfolio: `report_construction_estimate` (79.6%)
- Phase 14C should prioritize prepared-array reuse in single-symbol/event/arbitrage loops and optional lazy reports.

## Cython/C++ Decision

Cython/C++ is not justified yet. The measured bottleneck remains in facade/report/preparation layers, so Phase 14C should optimize cache threading and optional/lazy heavy reports first.

This report is a measurement artifact. It must not be used to justify changing accounting, fill policy, margin, or report semantics.
