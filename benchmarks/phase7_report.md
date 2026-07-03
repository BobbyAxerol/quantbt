# Phase 7 Benchmark Report

Status: benchmark harness added.

This report is intentionally versioned in the repo so performance comparisons
have a stable place to land. The current shell only exposes `/usr/bin/python3`
without `numpy`, `pandas`, or `pytest`, so measured benchmark numbers must be
generated from the research environment.

## How To Run

From the package directory:

```bash
python3 benchmarks/run_phase7.py --profile smoke
python3 benchmarks/run_phase7.py --profile standard --repeats 5
python3 benchmarks/run_phase7.py --profile standard --include-nautilus
```

Default outputs:

- JSON: `benchmarks/out/phase7_results.json`
- Markdown: `benchmarks/out/phase7_results.md`

## Metrics Captured

- bars x symbols;
- generated signal transition count;
- explicit order count;
- event count;
- first-run warmup time, including Numba compilation where applicable;
- repeated runtime after warmup;
- Python peak memory via `tracemalloc`;
- process RSS delta via `resource.ru_maxrss` where available;
- backend status: passed, failed, or skipped.

## Thresholds

Thresholds live in `benchmarks/phase7_thresholds.json`.

Decision rule:

- Stay with Numba while standard profile remains within thresholds.
- Profile before considering Cython/C++.
- Move only proven hot loops, not public API wrappers.
- Keep `BacktestResultV2` and engine facade contracts stable.

## Backends

- `native_vectorized`: optimizer/research fast path.
- `native_event`: order/fill lifecycle and intrabar touch simulation.
- `nautilus`: optional high-fidelity validation oracle.
