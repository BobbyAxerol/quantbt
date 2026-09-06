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

PERF-05 WFO terminal-score reuse evidence:

```bash
PYTHONPATH=src .venv/bin/python \
  benchmarks/native_event/benchmark_perf05_wfo_evaluation_reuse.py \
  --bars 2048 --trials 16 --repeats 15
```

- compares real public prepared-native Mode 1 cache-off, bounded-LRU/mixed,
  and high-hit lanes with identical strategy, seed, selector, and final account;
- checks public parity and cache release, then records one fixed small matrix
  across all five modes;
- reports full-facade and isolated scorer medians against cache-off; the
  committed fifteen-repeat high-hit fixture avoided `11,680` terminal-score
  bars, reduced scorer time by `8.14%` and full public time by `2.61%`, with a
  `0.000 MiB` RSS tail spread;
- keeps Mode 2 on its proxy/resampling authority and does not present the
  result as a generic callback, reactive, portfolio, package, or all-WFO claim.

Phase 60 native result/RSS closure:

```bash
PYTHONPATH=src poetry run python benchmarks/native_event/benchmark_phase60_result_rss.py \
  --bars 2000 --iterations 250
```

- runs the public typed prepared static-score route repeatedly through one
  Rust-owned runner;
- asserts that the score profile does not retain compact paths or audit arrays;
- records current/peak/final RSS and applies a bounded allocator-plateau gate;
- is a retention diagnostic, not a Python-vs-Rust throughput comparison.

Phase 61 static Rust-primary command-tape gate:

```bash
PYTHONPATH=src poetry run python \
  benchmarks/native_event/benchmark_phase61_static_rust_primary.py \
  --bars 10000 --repeats 5
```

- measures direct ABI-0.5 typed execution, cold compact adaptation, and the
  prepared score route independently;
- checks terminal accounting parity, one native boundary, no score audit
  retention, typed prepared-request reuse, and a bounded score RSS plateau;
- on the recorded local 10,000-bar V3 fixture, prepared Rust score ran at
  `1.34M bars/s` versus Python's `56.5k bars/s` (`23.74x`). This is a
  machine-specific prepared-score result, not a claim about callback,
  portfolio, grid, WFO, or full report performance.

Phase 62 reactive numeric co-runtime evidence:

```bash
PYTHONPATH=src poetry run python \
  benchmarks/native_event/benchmark_phase62_reactive_coruntime.py \
  --bars 10000 --repeats 3 --concurrent-sessions 2
```

- runs A/B/C/D parity before timing: Python R0, legacy Rust bridge, R1
  held-GIL, R1 release-between-callbacks, and captured static Rust replay;
- measures full public end-to-end runtime for lightweight, low-churn,
  high-churn, and two-session reactive workloads;
- records current RSS with one result retained and after output release; and
- does not alter `backend="auto"`: R1 is an explicit hybrid runtime, not a
  callback-free Rust benchmark or automatic promotion claim.

Phase 63 sparse wake, block intent, and candidate-batch evidence:

```bash
PYTHONPATH=src poetry run python \
  benchmarks/native_event/benchmark_phase63_sparse_block_batch.py \
  --bars 10000 --cadence 32 --candidates 16 --repeats 3
```

- verifies R1 every-bar, R2 sparse wake, and R3 block accounting/canonical
  trace parity on the same deterministic transition schedule before timing;
- records callbacks, skipped decisions, wake ratio, context/command bytes,
  GIL acquisitions, end-to-end speed, and current RSS;
- reports R3B separately as a prepared shared-market candidate-batch primitive;
  and
- leaves `backend="auto"` unchanged: R2/R3/R3B remain explicit certified
  contracts.

Phase 75 reactive scalar-retention evidence:

```bash
PYTHONPATH=src poetry run python \
  benchmarks/native_event/benchmark_phase75_reactive_scalar_retention.py \
  --bars 10000 --repeats 3
```

- runs the same prepared Rust account/lifecycle session through public-minimal
  and score-only R1/R2/R3 surfaces;
- asserts exact terminal-equity parity before recording time;
- verifies that score-only output retains no account path, command rows,
  callback trace, or terminal active-order artifact; and
- reports same-process warm allocation deltas separately from speed. It does
  not claim a cold-process RSS reduction or change `backend="auto"`.

Phase 76 public reactive WFO evidence:

```bash
PYTHONPATH=src poetry run python \
  benchmarks/native_event/benchmark_phase76_reactive_wfo.py \
  --bars 2000 --candidates 8 --repeats 3
```

- measures `prepare_reactive_walk_forward(...)`, not an internal helper, on
  one native-event symbol with reset-flat candidate/fold accounts;
- reports sequential Optuna and R3B throughput schedules separately because
  ask/tell candidate sequences are intentionally different;
- separates lightweight from Python-heavy callback work, records actual scalar
  candidate-fold visits, callback/GIL counters, deterministic repeats, and
  zero market-copy/IPC evidence for R3B; and
- launches a clean single-thread subprocess for the Linux COW worker probe so
  worker PSS/RSS and shared mappings are not misreported as unique tape memory.

Phase 77.3 reactive resource/performance closure:

```bash
PYTHONPATH=src poetry run python \
  benchmarks/native_event/benchmark_phase77_3_reactive_closure.py \
  --profile standard
```

- measures prepared R1/R2/R3 public-minimal and scalar-score retention as
  separate surfaces, and measures sequential W3/R3B schedules separately;
- reruns small public-WFO, shared-portfolio, bounded-package and intrabar
  parity controls without converting them into one synthetic speed number;
- captures current source/native identity, RSS/PSS deltas, work counters and
  focused active cancellation/deadline coverage; and
- treats historical Phase 75/76 results as immutable scope records rather than
  promotion-eligible before/after comparators.

Phase 66 direct target/vectorized authority:

```bash
PYTHONPATH=src MPLCONFIGDIR=/tmp poetry run python \
  benchmarks/native_event/benchmark_phase66_rust_target_vectorized.py \
  --bars 20000 --repeats 9
```

- compares the frozen `close_target_v2_same_close` target-units contract only;
- separately times Python-to-Rust ingestion, typed prepared score, warmed
  Numba kernel, and public compact adaptation;
- asserts exact accounting/position parity, one native execution pass and
  boundary call, no generic order arena, and no retained score paths; and
- records warm steady-state score RSS separately from public compact result
  retention. It is not a generic vectorized, portfolio, grid, callback, or
  automatic-routing benchmark.

Phase 67 shared-account portfolio target authority:

```bash
PYTHONPATH=src MPLCONFIGDIR=/tmp poetry run python \
  benchmarks/native_event/benchmark_phase67_shared_portfolio.py \
  --bars 2000 --symbols 20 --candidates 16 --repeats 2
```

- measures only the explicit same-close, linear gross-cross shared-account
  target route, with one declared admission policy;
- reports preparation, score, compact, and prepared candidate-fold execution
  separately, along with process RSS; and
- asserts score/compact terminal parity, prepared-WFO parity, zero market-copy
  bytes inside the WFO runner, and no generic order arena. It is not a generic
  `portfolio(...)`, risk-parity, package, or automatic-routing benchmark.

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

Phase 47C Grid 2,000-bar parity and RSS:

```bash
MPLCONFIGDIR=/tmp PYTHONPATH=/root/bobby/pool_alpha \
poetry run python benchmarks/native_event/benchmark_grid_2000.py \
  --grid-module-dir /root/bobby/pool_alpha/alphas_storage/TA \
  --backend python --mode scalar --grid-mode long_only --bars 2000

MPLCONFIGDIR=/tmp PYTHONPATH=/root/bobby/pool_alpha \
poetry run python benchmarks/native_event/benchmark_grid_2000.py \
  --grid-module-dir /root/bobby/pool_alpha/alphas_storage/TA \
  --backend rust --mode audit --grid-mode long_short --bars 2000
```

The runner uses one warm-up and five measured runs in a backend-isolated
process and writes JSON with command/audit fingerprint, terminal accounting,
runtime, CPU time, peak/post RSS, and repeated-run RSS slope. See
[`docs/grid_native_event_phase47c.md`](../docs/grid_native_event_phase47c.md)
for the parity contract and backend policy.

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

Phase 71 prepared WFO runtime soak:

```bash
MPLCONFIGDIR=/tmp PYTHONPATH=src poetry run python \
  benchmarks/native_event/benchmark_phase71_runtime_soak.py \
  --bars 4096 --candidates 32 --repeats 30 --workers 2
```

- reuses one Rust-owned market and intent tape across warm score runs;
- verifies terminal determinism, reset generation, typed cancellation,
  post-cancel recovery, deterministic close, and zero per-run tape copies;
- records median/min/max warm time plus repeated current-RSS samples; and
- is scoped to prepared single-symbol static StrategyIR WFO, excluding feature
  generation, Optuna sampling, and report construction.

Phase 72 measurement and evidence governance:

```bash
PYTHONPATH=src poetry run python tools/check_benchmark_governance.py
PYTHONPATH=src poetry run python benchmarks/native_event/benchmark_phase65_native_wfo.py \
  --bars 4096 --candidates 64 --folds 4 --workers 2 --repeats 3 \
  --output /tmp/phase72_wfo.json
PYTHONPATH=src poetry run python benchmarks/native_event/benchmark_phase71_runtime_soak.py \
  --bars 4096 --candidates 32 --repeats 30 --workers 2 \
  --output /tmp/phase72_soak.json
```

- uses versioned actual executor counters rather than full-tape volume as the
  throughput denominator;
- records separate supplied/warmup/test-window work, candidates, folds,
  scenarios, early exits, skipped tasks, data/intent hashes, source/wheel
  identity, and output-retention profile;
- keeps original historical artifacts immutable but marks them scope-only, so
  they cannot enable automatic Rust promotion; and
- requires score/score, compact/compact, or audit/audit comparator pairing.

Read [Native Measurement Contract V1](../docs/performance/measurement_contract_v1.md)
before interpreting or publishing a native benchmark.

Phase 73 shared prepared-native evaluation runtime:

```bash
PYTHONPATH=src poetry run python \
  benchmarks/native_event/benchmark_phase73_prepared_evaluation.py \
  --bars 4096 --candidates 64 --repeats 30 --workers 2
```

- measures one immutable market/template and a batch of typed Rust target
  requests through a persistent generic worker pool;
- reports one-time Python normalization and Rust-owned ingress separately from
  zero market/intent copies in each warm execution;
- validates one native boundary per batch, deterministic terminal rows, bounded
  scalar output, and an RSS plateau; and
- is not an Optuna, callback, endpoint report, or public `walk_forward()`
  speed claim. Public five-mode WFO integration is Phase 74 work.

Phase 77.1 public workload baseline and `%_equity` compatibility lock:

```bash
PYTHONPATH=src poetry run python \
  benchmarks/native_event/benchmark_phase77_1_public_matrix.py --profile smoke

PYTHONPATH=src poetry run python \
  benchmarks/native_event/benchmark_phase77_1_public_matrix.py --profile standard
```

- `smoke` runs every declared W0 public mode/schedule route and records whether
  it used prepared-native scoring, deliberately preserved Mode 2 proxy scoring,
  or a legacy fallback;
- `standard` runs five alternating reference/native repetitions of the declared
  10,000-bar `1h`, three-calendar-fold, 64-trial Mode 1 global public comparator;
- the script refuses the 100,000-bar `long` stress profile unless
  `--allow-long` is explicit; and
- `%_equity` is tested as a separate transition-sizing financial contract, not
  conflated with a direct target-weight or per-bar equity-fraction benchmark.
