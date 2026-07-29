# Phase 16 Performance Debt Closure

Status: **pass**

## Prepared Service Context

| workload | normal seconds | prepared seconds | speedup | peak MB | parity |
| --- | ---: | ---: | ---: | ---: | --- |
| single signal_notional | `0.071100` | `0.039041` | `1.821x` | `1.227` | `True` |
| native portfolio | `0.311475` | `0.069483` | `4.483x` | `2.635` | `True` |

## Report Construction

| workload | full seconds | minimal seconds | speedup | parity |
| --- | ---: | ---: | ---: | --- |
| native portfolio reports | `0.075456` | `0.039363` | `1.917x` | `True` |

## Large WFO / Service Loop

- Status: `pass`
- Rows: `1440`
- Symbols: `6`
- Cython/C++ recommendation: not justified yet; facade/report overhead remains the larger measured bucket

## Closed Debt

- facade-level repeated pandas market normalization can now be avoided with endpoint.prepare_service_context(...)
- report construction has an explicit full/minimal benchmark and parity guard
- larger WFO/service-loop benchmark is archived before any Cython/C++ decision

## Remaining Notes

- normal endpoint.backtest(...) remains backward-compatible and still normalizes defensively per call
- prepared service context is opt-in and currently covers native_vectorized signal_notional plus native_portfolio
- Cython/C++ should wait until pure kernels, not pandas/report facades, dominate measured runtime
