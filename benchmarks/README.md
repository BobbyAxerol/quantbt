# QuantBT Benchmarks

Phase 7 introduces a reproducible benchmark harness for the upgraded backtest
backends.

```bash
python3 benchmarks/run_phase7.py --profile smoke
python3 benchmarks/run_phase7.py --profile standard --repeats 5
python3 benchmarks/run_phase7.py --profile standard --repeats 5 --no-tracemalloc
python3 benchmarks/profile_phase7.py --profile standard --repeats 3
```

Profiles:

- `smoke`: quick local sanity check.
- `standard`: commit-to-commit comparison target.
- `large`: stress profile for optimization decisions.

The runner writes both JSON and Markdown into `benchmarks/out/` by default.
Nautilus is optional and skipped unless `--include-nautilus` is passed.

Backends currently measured:

- `native_vectorized`
- `native_event`
- `native_event_prepared`
- `portfolio_legacy`
- `native_portfolio`
- optional `nautilus`

The committed summary lives in `benchmarks/phase7_report.md`. Local JSON/MD
outputs under `benchmarks/out/` are git-ignored by design.

When a backend misses a runtime threshold, run `profile_phase7.py` before
considering Cython/C++. The committed profiling summary lives in
`benchmarks/phase7_profile_report.md`.

Phase 9 optimization follow-up:

- `benchmarks/compare_phase9_parity.py` checks that optimized sizing/order
  compilation does not change target units, equity, positions, order reports,
  or fills.
- `benchmarks/phase9_optimization_report.md` records the first post-profiling
  optimization pass and remaining bottlenecks.
- `native_event_prepared` measures the WFO/service pattern where market arrays
  and compiled order arrays are prepared once and replayed through the same
  event/accounting kernel.
- `--no-tracemalloc` is available when comparing runtime separately from memory
  instrumentation overhead. Use the default traced mode when peak memory is the
  metric under review.
