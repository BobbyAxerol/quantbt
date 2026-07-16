# Phase 9 Optimization Report

Status: Phase 9A, Phase 9B, Phase 9C, and the Phase 10A prepared native-event
replay follow-up are implemented with parity checks.

Commands:

```bash
MPLCONFIGDIR=/tmp PYTHONPATH=/root/bobby/pool_alpha poetry run python3 quantbt/benchmarks/compare_phase9_parity.py --json-out quantbt/benchmarks/out/phase9_parity.json --md-out quantbt/benchmarks/out/phase9_parity.md
MPLCONFIGDIR=/tmp PYTHONPATH=/root/bobby/pool_alpha poetry run python3 quantbt/benchmarks/profile_phase7.py --profile standard --repeats 2 --json-out quantbt/benchmarks/out/phase7_profile_standard_after_phase9c.json --md-out quantbt/benchmarks/out/phase7_profile_standard_after_phase9c.md
MPLCONFIGDIR=/tmp PYTHONPATH=/root/bobby/pool_alpha poetry run python3 quantbt/benchmarks/run_phase7.py --profile standard --repeats 1 --no-tracemalloc --json-out quantbt/benchmarks/out/phase7_standard_after_phase9c_runtime.json --md-out quantbt/benchmarks/out/phase7_standard_after_phase9c_runtime.md
```

## What Changed

- Added ndarray/Numba `signal_notional` target sizing for the native vectorized
  backend.
- Added a native event `OrderIntent` compiler using vectorized timestamp
  mapping and contiguous kernel arrays.
- Added safe prepared market arrays for native event runs, with explicit
  datetime/symbol signatures.
- Added optional compiled-order reuse with signature checks.
- Added `--no-tracemalloc` runtime benchmark mode so speed measurements can be
  separated from memory tracing.
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
| `prepared_event_equity_max_abs_diff` | 0.0 |
| `prepared_event_order_report_max_abs_diff` | 0.0 |
| `prepared_event_fill_count_diff` | 0 |

## Standard Profiling After Phase 9C

| backend | stage | seconds | share |
| --- | --- | ---: | ---: |
| `native_vectorized` | `data_normalization` | 0.139014 | 55.2% |
| `native_vectorized` | `pandas_to_ndarray` | 0.070291 | 27.9% |
| `native_vectorized` | `target_sizing` | 0.004345 | 1.7% |
| `native_vectorized` | `pure_numba_kernel` | 0.006089 | 2.4% |
| `native_vectorized` | `result_report_construction` | 0.032092 | 12.7% |
| `native_event` | `data_normalization` | 0.163836 | 45.8% |
| `native_event` | `pandas_to_ndarray` | 0.065011 | 18.2% |
| `native_event` | `order_array_construction` | 0.103095 | 28.8% |
| `native_event` | `pure_numba_kernel` | 0.008874 | 2.5% |
| `native_event` | `result_report_construction` | 0.016814 | 4.7% |

## Standard Runtime Benchmark After Phase 9C

| backend | runtime | threshold result |
| --- | ---: | --- |
| `native_vectorized` | 0.306991s | pass: 0.613982 sec/million bar-symbols <= 1.5 |
| `native_event` | 0.793388s | still fail: 3.173550 sec/100k orders > 1.25 |
| `portfolio_legacy` | 0.688006s | pass: 1.376012 sec/million bar-symbols <= 2.5 |

## Standard Runtime Benchmark After Phase 10A

Phase 10A adds a higher-level prepared replay path for WFO/service loops:
market arrays and explicit order arrays are prepared once, validated by
datetime/symbol signatures, then replayed through the unchanged event kernel.

| backend | runtime | threshold result |
| --- | ---: | --- |
| `native_vectorized` | 0.282944s | pass: 0.565889 sec/million bar-symbols <= 1.5 |
| `native_event` | 0.879406s | still fail: 3.517623 sec/100k orders > 1.25 |
| `native_event_prepared` | 0.346367s | pass: 1.385470 sec/100k orders <= 1.5 |
| `portfolio_legacy` | 0.692722s | pass: 1.385443 sec/million bar-symbols <= 2.5 |

## Interpretation

Phase 9A fixed the measured `native_vectorized` target-sizing bottleneck and
brings the standard benchmark back under threshold on this machine.

Phase 9B/9C materially improved native event order-array construction and
market-array preparation. Phase 10A exposes that optimization to higher-level
optimizer/WFO loops as `native_event_prepared`, which passes its prepared-replay
guardrail on this machine. The cold event route still intentionally fails the
strict order-count threshold because it includes full pandas normalization and
order compilation every run. The remaining safe targets are:

- reduce remaining cold-path pandas normalization overhead;
- revisit the event threshold after separating workload types.

Cython/C++ remains unjustified: pure Numba kernel time is still small compared
with Python/Pandas preparation layers.
