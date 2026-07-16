# Phase 9 Optimization Report

Status: Phase 9A and Phase 9B implemented with parity checks.

Commands:

```bash
MPLCONFIGDIR=/tmp PYTHONPATH=/root/bobby/pool_alpha poetry run python3 quantbt/benchmarks/compare_phase9_parity.py --json-out quantbt/benchmarks/out/phase9_parity.json --md-out quantbt/benchmarks/out/phase9_parity.md
MPLCONFIGDIR=/tmp PYTHONPATH=/root/bobby/pool_alpha poetry run python3 quantbt/benchmarks/profile_phase7.py --profile standard --repeats 2 --json-out quantbt/benchmarks/out/phase7_profile_standard_after_phase9.json --md-out quantbt/benchmarks/out/phase7_profile_standard_after_phase9.md
MPLCONFIGDIR=/tmp PYTHONPATH=/root/bobby/pool_alpha poetry run python3 quantbt/benchmarks/run_phase7.py --profile standard --repeats 1 --json-out quantbt/benchmarks/out/phase7_standard_after_phase9.json --md-out quantbt/benchmarks/out/phase7_standard_after_phase9.md
```

## What Changed

- Added ndarray/Numba `signal_notional` target sizing for the native vectorized
  backend.
- Added a native event `OrderIntent` compiler using vectorized timestamp
  mapping and contiguous kernel arrays.
- Left accounting, fill rules, margin logic, funding, liquidation, and result
  schema unchanged.

## Parity

| check | value |
| --- | ---: |
| `target_unit_max_abs_diff` | 0.0 |
| `vectorized_equity_max_abs_diff` | 0.0 |
| `vectorized_position_max_abs_diff` | 0.0 |
| `order_array_max_abs_diff` | 0.0 |
| `event_equity_max_abs_diff` | 0.0 |
| `event_order_report_max_abs_diff` | 0.0 |
| `event_fill_count_diff` | 0 |
| `event_fill_price_max_abs_diff` | 0.0 |

## Standard Profiling After Phase 9

| backend | stage | seconds | share |
| --- | --- | ---: | ---: |
| `native_vectorized` | `data_normalization` | 0.140976 | 43.1% |
| `native_vectorized` | `pandas_to_ndarray` | 0.155759 | 47.6% |
| `native_vectorized` | `target_sizing` | 0.004104 | 1.3% |
| `native_vectorized` | `pure_numba_kernel` | 0.006162 | 1.9% |
| `native_vectorized` | `result_report_construction` | 0.020172 | 6.2% |
| `native_event` | `data_normalization` | 0.138870 | 31.3% |
| `native_event` | `pandas_to_ndarray` | 0.104269 | 23.5% |
| `native_event` | `order_array_construction` | 0.172629 | 38.9% |
| `native_event` | `pure_numba_kernel` | 0.010368 | 2.3% |
| `native_event` | `result_report_construction` | 0.017463 | 3.9% |

## Standard Benchmark After Phase 9

| backend | runtime | threshold result |
| --- | ---: | --- |
| `native_vectorized` | 0.587020s | pass: 1.174040 sec/million bar-symbols <= 1.5 |
| `native_event` | 3.633349s | still fail: 14.533396 sec/100k orders > 1.25 |
| `portfolio_legacy` | 2.039291s | noisy fail on this run; not modified by Phase 9 |

## Interpretation

Phase 9A fixed the measured `native_vectorized` target-sizing bottleneck and
brings the standard benchmark back under threshold on this machine.

Phase 9B materially improved native event order-array construction, but the
event route still needs a second optimization pass. The next safe targets are:

- cache aligned market arrays for repeated order replay;
- support caller-supplied compiled order arrays for repeated event runs;
- separate runtime benchmarks from memory tracing;
- avoid repeated pandas zero-signal/funding construction in hot event paths.

Cython/C++ remains unjustified: pure Numba kernel time is still small compared
with Python/Pandas preparation layers.
