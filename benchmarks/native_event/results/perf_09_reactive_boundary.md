# PERF-09 Reactive Boundary Closure

## Contract

- Same public Rust reactive WFO strategy, parameter candidates, callback work, tape, reset-flat accounts and deterministic seed on both sides.
- Mode 4 uses `per_fold_causal`; R3B is reported separately under its declared global fixed-matrix throughput contract.
- The baseline only disables private run-local calendar/task preparation. It does not alter strategy behavior, account lifecycle, task count or Optuna/R3B sampling contract.
- JSON RSS/PSS is an in-process plateau diagnostic, not isolated memory attribution.

## Result

| Workload | Baseline | PERF-09 | Speedup | Score bars | Task fast hits |
|---|---:|---:|---:|---:|---:|
| `mode_4_is_only_robust` / `certified_sequential_v1` | 624.709 ms | 316.975 ms | 1.97x | 32,390 | 378 |
| `mode_1_decay` / `throughput_batch_v1` | 315.865 ms | 129.568 ms | 2.44x | 43,040 | 294 |
