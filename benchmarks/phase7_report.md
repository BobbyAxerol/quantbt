# Phase 7 Benchmark Report

Status: benchmark harness implemented and smoke/standard profiles measured.

Generated on the current research environment with:

```bash
MPLCONFIGDIR=/tmp PYTHONPATH=/root/bobby/pool_alpha poetry run python3 quantbt/benchmarks/run_phase7.py --profile smoke --repeats 2 --json-out quantbt/benchmarks/out/phase7_smoke_results.json --md-out quantbt/benchmarks/out/phase7_smoke_results.md
MPLCONFIGDIR=/tmp PYTHONPATH=/root/bobby/pool_alpha poetry run python3 quantbt/benchmarks/run_phase7.py --profile standard --repeats 1 --json-out quantbt/benchmarks/out/phase7_standard_results.json --md-out quantbt/benchmarks/out/phase7_standard_results.md
```

Default output artifacts:

- `benchmarks/out/phase7_smoke_results.json`
- `benchmarks/out/phase7_smoke_results.md`
- `benchmarks/out/phase7_standard_results.json`
- `benchmarks/out/phase7_standard_results.md`

The `benchmarks/out/` directory is intentionally git-ignored so each machine can
produce local measurements without polluting commits.

## Metrics Captured

- bars x symbols;
- generated signal transition count;
- explicit order count;
- event count;
- first-run warmup time, including Numba compilation where applicable;
- repeated runtime after warmup;
- Python peak memory via `tracemalloc`;
- process RSS delta via `resource.ru_maxrss` where available;
- throughput in bar-symbols per second;
- threshold metric and pass/fail state.

## Smoke Profile

Profile: 1,000 bars, 4 symbols, 500 explicit orders, 2 runtime repeats.

| backend | status | warmup s | runtime s | peak MB | threshold |
| --- | --- | ---: | ---: | ---: | --- |
| native_vectorized | passed | 1.026547 | 0.075053 | 15.938005 | pass |
| native_event | passed | 0.159764 | 0.137429 | 1.813715 | pass |
| portfolio_legacy | passed | 0.212302 | 0.187615 | 2.227262 | pass |
| nautilus | skipped | - | - | - | optional; run with `--include-nautilus` |

Smoke conclusion: the benchmark harness and all native paths execute correctly.

## Standard Profile

Profile: 25,000 bars, 20 symbols, 25,000 explicit orders, 1 runtime repeat.

| backend | status | warmup s | runtime s | peak MB | threshold |
| --- | --- | ---: | ---: | ---: | --- |
| native_vectorized | passed | 5.461958 | 3.874463 | 180.848133 | fail |
| native_event | passed | 4.952707 | 5.038631 | 133.992422 | fail |
| portfolio_legacy | passed | 1.193074 | 1.183435 | 206.536880 | pass |
| nautilus | skipped | - | - | - | optional; run with `--include-nautilus` |

Standard profile threshold details:

- `native_vectorized`: 7.748926 seconds per million bar-symbols vs threshold 1.5.
- `native_event`: 20.154525 seconds per 100k orders vs threshold 1.25.
- `portfolio_legacy`: 2.366871 seconds per million bar-symbols vs threshold 2.5.

## Interpretation

The failures do not mean Cython/C++ should be started immediately.

They mean the next optimization work should profile where time is spent:

- public facade and data normalization;
- pandas-to-ndarray conversion;
- result/report construction;
- order array construction;
- Numba kernel runtime after warmup.

Only if profiling shows a hot loop that Numba cannot optimize should Cython/C++
be considered. The current evidence points first to measuring facade/conversion
overhead and separating pure-kernel benchmarks from full endpoint benchmarks.

Follow-up profiling is now captured in
`benchmarks/phase7_profile_report.md`. The standard profile shows pure Numba
kernels at about 1.3% of measured backend-layer runtime for both
`native_vectorized` and `native_event`, so the first optimization targets are
target sizing, pandas alignment/packing, order-array construction, and benchmark
instrumentation separation.

## Backend Guidance

- `native_vectorized`: still the intended optimizer/research fast path, but
  standard full-facade benchmark needs profiling before performance claims.
- `native_event`: correct order/fill lifecycle path, but standard explicit
  order benchmark needs profiling before large sweeps.
- `portfolio_legacy`: currently passes the standard matrix benchmark threshold.
- `nautilus`: remains optional validation oracle, not optimizer hot path.

## Thresholds

Thresholds live in `benchmarks/phase7_thresholds.json`.

Decision rule:

- Stay with Numba while pure-kernel time is not the measured bottleneck.
- Do not change public API for speed.
- Move only proven hot loops to Cython/C++.
- Keep benchmark JSON/Markdown artifacts for commit-to-commit comparison.
