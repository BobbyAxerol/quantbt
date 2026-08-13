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

Phase 14/16 service-loop follow-up:

```bash
python3 benchmarks/run_phase14_service_loop.py --rows 1440 --symbols 6 --trials 8 --repeats 2
python3 benchmarks/run_phase16_performance_debt.py --rows 1440 --symbols 6 --replays 8 --repeats 2
```

- `phase14_service_loop.*` decomposes WFO, native-event, arbitrage and report
  workload costs.
- `phase16_performance_debt.*` compares normal endpoint replays with
  `endpoint.prepare_service_context(...)` and records the current Cython/C++
  decision.

Phase 49B WFO prepared/scalar certification:

```bash
python3 benchmarks/run_phase49b_wfo_performance.py --rows 1000 --trials 16
```

- compares Phase 49A reference retention with Phase 49B prepared context,
  scalar trial scoring and compact ledgers using identical mathematical work;
- checks exact equity, positions, selected params, objectives, trial order and
  candidate order;
- separates warm runtime from isolated child-process RSS and records strategy,
  scorer, market preparation, signal packing and metric-report timing;
- does not cache arbitrary strategy indicators or signal output.

Options Phase 10:

```bash
python3 benchmarks/run_options_engine.py --snapshots 96 --contracts 48 --packages 96 --repeats 3
python3 benchmarks/gamma_scalping_backtestsample.py --snapshots 90 --seed 42
python3 benchmarks/gamma_scalping_backtestsample.py \
  --real-options-csv /root/bobby/pool_alpha/alphas_storage/option_based/options_full_history.csv.gz \
  --underlying-source spot \
  --hedge-timeframe 1h
```

- `options_phase10_baseline.*` records prepared-tape and compiled-package cache
  parity for the native option backend.
- The benchmark reports snapshots, contracts, quotes, packages, fills, hedges,
  memory, uncached runtime, cached runtime, and run-manifest hashes.
- `gamma_scalping_backtestsample.py` is a runnable long-straddle gamma-scalping
  smoke sample. It keeps the original research helpers, then runs the public
  `QuantBTEndpoint.options(...)` path through
  `build_gamma_scalping_strategy_run(...)`, `strategy_run`, `underlying`, and
  prepared-cache parity.
- The real-data mode converts legacy Binance options CSV history into QuantBT's
  canonical option-chain schema, selects an ATM call/put pair with entry/exit
  quotes, and loads BTCUSDT spot or USD-M perpetual candles from `_get_data` for
  first-class delta-hedged combined-equity accounting.
- Cython/C++ should only be considered after a larger profile shows pure
  kernels, not pandas/tape/report facade work, dominating runtime.

Phase 31 intrabar execution:

```bash
python3 benchmarks/run_phase31_intrabar.py --rows 25000 --repeats 3
python3 benchmarks/run_phase31_intrabar.py --rows 512 --repeats 1
```

- `phase31_intrabar_benchmark.*` compares the new fast
  `intrabar_bracket_v1` kernel against the close-target pure kernel, the Python
  intrabar oracle, fill replay, and the native-event explicit-order facade.
- Use the fast intrabar route for single-symbol next-open SL/TP/trailing
  research. Use `report_level="audit"` for fill-ledger certification and
  `report_level="minimal"` for WFO/optimizer loops.
