# Benchmarking Governance

Run a benchmark only after the corresponding parity gate is green. The release
question is not “which implementation is faster?” but “which implementation
produces the same declared accounting and trace under a declared workload?”.

## Current Release Evidence

The governed pair is `quantbt-engine==1.1.0` and
`quantbt-native==0.4.1`. The current committed evidence reports:

| Workload | Rust median | Throughput | Compatibility comparator | Parity gate |
|---|---:|---:|---:|---|
| Native Strategy IR score, 2,000 bars | 0.741 ms | 2.70M bars/s | 31.565 ms | exact trace/accounting |
| Native Strategy IR batch, 64 x 2,000 bars | 11.379 ms | 11.25M bars/s | n/a | exact serial/batch |
| Native Strategy IR causal fold, 64,000 bars | 7.386 ms | 8.67M bars/s | n/a | exact fold isolation |
| Native WFO V2, 64 candidates x 4 folds x 4,096 supplied bars | 232.514 ms | 0.94M actual candidate-test-bar visits/s | 319.437 ms prior fold oracle | exact metrics/counts |
| Public prepared-native WFO, Mode 1 global W0, 2,048 bars x 16 trials | 166.156 ms scorer; 431.730 ms full facade | 127,181 candidate-bar visits/s | 800.033 ms scorer; 1.053 s full facade | exact selection/final account |
| Portfolio target-units score, 2,000 bars x 8 symbols | 3.594 ms | 556,551 bars/s | 33.493 ms | exact at `1e-12` |
| Atomic package score, 2,000 bars x 8 symbols | 3.512 ms | 569,514 bars/s | 19.735 ms | exact at `1e-12` |
| Direct target-units prepared score, 20,000 bars x 1 symbol | 1.607 ms | 12.45M bars/s | Numba warmed kernel: 0.607 ms | exact accounting/positions |
| Direct target-units public compact, 20,000 bars x 1 symbol | 23.432 ms | 853,549 bars/s | Numba compact: 58.600 ms | exact accounting/positions |
| Bounded package V2 prepared score, 2,000 bars x 20 legs | 0.873 ms | 45.82M bar-symbols/s | n/a | score/compact/audit terminal parity |
| Bounded package V2 scenario batch, 16 x 2,000 bars x 20 legs | 13.114 ms | 48.80M bar-symbols/s | one Rust boundary | isolated-account / selected-single parity |
| Rust intrabar prepared score, 2,000 bars x 1 symbol | 0.096 ms | 20.90M bars/s | Numba standard/path: 2.053 ms | exact terminal/path |
| Rust intrabar prepared compact, 2,000 bars x 1 symbol | 0.159 ms | 12.60M bars/s | Numba standard/path: 2.053 ms | exact terminal/path |
| Rust intrabar public compact adapter, 2,000 bars x 1 symbol | 2.538 ms | 788,099 bars/s | Numba standard/path: 2.053 ms | exact terminal/path |
| Rust intrabar prepared public runner, 20,000 bars x 1 symbol | 10.233 ms | 1.95M bars/s | matching Numba prepared runner: 13.884 ms | exact path/fill/accounting; 1.36x |

The IR score is 42.6x faster than its Python oracle on this fixture. The
bounded portfolio and package score paths are 9.3x and 5.6x faster. These
ratios are derived from same-fixture medians; they are not comparisons with
external frameworks or guarantees for a full report facade.

Native WFO V2 is a separate prepared single-symbol static-IR score contract.
Its measured persistent-runtime versus prior fold-oracle ratio is 1.37x with
exact scalar metrics and counts. Its corrected execution denominator is 0.94M
actual candidate-test-bar visits/s, not generic WFO bars/s. The earlier 4.51M
number is preserved only as logical input-volume/s. W1/W2 signal generation
and one explicit 8.00 MiB Python-to-Rust intent ingest (297.496 ms on the
fixture) are reported separately in the artifact.

Phase 74 measures the normal public `QuantBTEndpoint.walk_forward()` facade,
not the specialized static-IR runtime. The fixture fixes a one-symbol W0
callback, Mode 1 global selection, 2,048 daily bars, 16 sequential trials,
one Rust scorer worker, and five post-warm repeats. Native scorer time was
`166.156 ms` versus `800.033 ms` (`4.81x`); end-to-end public facade time was
`431.730 ms` versus `1.053 s` (`2.44x`). The native work counter was `54,908`
actual candidate-bar visits (`127,181` visits/s). Exact candidate ranking,
winner, stitched output, fees, funding, and final account parity passed. RSS
samples plateaued with a `0.008 MiB` tail spread. The artifact also separates
prepare/fold planning, Python strategy generation, candidate scoring, Rust
prepared execution, and the explicit residual control/reconstruction/report
bucket. This does not claim a speedup for
Mode 2 SBB, unsupported target modes, reactive WFO, portfolio/package WFO, or
an arbitrary user callback. See [`phase74_public_wfo.md`](../../benchmarks/native_event/results/phase74_public_wfo.md)
and [`phase74_public_wfo.json`](../../benchmarks/native_event/results/phase74_public_wfo.json).

Phase 76 measures the separate public Reactive WFO (W3) facade on one 2,000-bar
market, eight candidates, six reset-flat folds, and Mode 1 global selection.
The lightweight sequential schedule recorded `224.935 ms` and `96,517` actual
candidate-fold visits/s; the fixed R3B matrix recorded `233.752 ms` and
`102,245` visits/s. These are not a TPE speedup comparison: sequential Optuna
and ask-B/score-B/tell-B have intentionally different sampling contracts. The
Python-heavy fixture shows why this distinction matters: sequential runtime was
`464.960 ms`, while R3B reduced `21,710` per-candidate callback calls to `36`
shared batch callbacks and completed in `252.496 ms`; Rust still processed every
candidate account on every bar. Fixed-seed repeats, selector/cold-audit parity,
zero R3B market copy/IPC, and a clean Linux COW worker probe passed. The probe
reported `53.4 MiB` worker PSS and `105.1 MiB` RSS with `0` market IPC bytes per
task; its shared mappings are not counted as private tape retention. See
[`phase76_reactive_wfo.md`](../../benchmarks/native_event/results/phase76_reactive_wfo.md)
and [Reactive WFO (W3)](../reactive_wfo.md).

The Phase 66 direct-target results deliberately report two different layers.
The scalar typed Rust request is slower than the frozen Numba pure kernel on
this one-symbol fixture (`0.38x`), while the explicit Rust public compact
route is `2.50x` faster because it owns target resolution and avoids repeating
the compatibility facade's preparation work. Neither number is a generic
vectorized, portfolio, grid, or callback claim. The score path retains no
equity/position arrays, makes one native boundary call, uses no generic order
arena, and its warm steady-state RSS increased by 3.01 MiB across the timed
sample. Process-level RSS after public compact materialization is reported
separately in the evidence artifact.

The Phase 68 package rows are a separate same-account linear contract. Each
fixture includes a partial primary fill and post-actual-fill hedge sizing, so
the measurements cover the dependency/residual path rather than an empty
all-fill tape. Score retains scalar accounting; compact/audit materialize more
cold-path data. The 16-scenario batch shares immutable market/template state,
makes one native entry, and reset-flats the account for each scenario. It is
not generic arbitrage planning, callback WFO, L2 matching, venue-native
atomicity, cross-currency, or cross-exchange evidence.

Phase 69 measures a separate explicit bounded `intrabar_bracket_v1` route:
one strict OHLC symbol, next-open intent, SL/TP/trailing, technical exits,
close-timestamp funding, margin, and liquidation. Its `score` row is a direct
typed Rust primitive with no dense paths. Its `compact` row transfers typed
SoA; the public adapter row also builds pandas-facing result objects. Therefore
the adapter is honestly slower than the warm Numba standard/path comparator on
this 2,000-bar fixture, even though the native kernel is faster. No generic
intrabar endpoint is auto-promoted. The benchmark records process RSS snapshots
only; its profiles share one process and must not be read as a Rust-only RSS
delta. See [`phase69_rust_intrabar.md`](../../benchmarks/native_event/results/phase69_rust_intrabar.md)
and its [manifest](../../benchmarks/native_event/manifests/phase69_rust_intrabar_v1.json).

Phase 77 closes the prior raw-kernel versus public-adapter comparison gap for
the same bounded intrabar contract. Its 20,000-bar fixture measures both
one-shot endpoints and both `prepare_intrabar(...).run(...)` public runners at
the `standard` result level. Rust's prepared runner took `10.233 ms` versus
`13.884 ms` for the matching Numba prepared runner (`1.36x`) while preserving
equity, positions, fills, fees, funding, margin, rejections and liquidation.
The one-shot endpoints were effectively tied (`72.241 ms` Rust; `72.906 ms`
Numba). The prepared runner avoids re-hashing or retaining a mutable candidate
intent, but still validates it and Rust still emits an authoritative request
fingerprint. After 96 extra prepared runs, RSS plateaued after the initial
adapter allocation; the final-half change was `-0.305 MiB`. This is a
same-process retention probe, not a standalone Rust-memory claim. Direct target
RSS remains governed by its independent Phase 66 process artifact.

Primary evidence:

- [`phase54b2/public_routes.json`](../../benchmarks/native_event/results/phase54b2/public_routes.json)
- [`phase54b2/public_routes.md`](../../benchmarks/native_event/results/phase54b2/public_routes.md)
- [`phase54b3/portfolio_package.json`](../../benchmarks/native_event/results/phase54b3/portfolio_package.json)
- [`phase65_native_wfo.md`](../../benchmarks/native_event/results/phase65_native_wfo.md)
- [`phase65_native_wfo.json`](../../benchmarks/native_event/results/phase65_native_wfo.json)
- [`phase74_public_wfo.md`](../../benchmarks/native_event/results/phase74_public_wfo.md)
- [`phase74_public_wfo.json`](../../benchmarks/native_event/results/phase74_public_wfo.json)
- [`phase66_rust_target_vectorized.md`](../../benchmarks/native_event/results/phase66_rust_target_vectorized.md)
- [`phase66_rust_target_vectorized.json`](../../benchmarks/native_event/results/phase66_rust_target_vectorized.json)
- [`phase68_bounded_package.md`](../../benchmarks/native_event/results/phase68_bounded_package.md)
- [`phase68_bounded_package.json`](../../benchmarks/native_event/results/phase68_bounded_package.json)
- [`phase69_rust_intrabar.md`](../../benchmarks/native_event/results/phase69_rust_intrabar.md)
- [`phase69_rust_intrabar.json`](../../benchmarks/native_event/results/phase69_rust_intrabar.json)
- [`phase77_native_performance_closure.md`](../../benchmarks/native_event/results/phase77_native_performance_closure.md)
- [`phase77_native_performance_closure.json`](../../benchmarks/native_event/results/phase77_native_performance_closure.json)
- [`phase77_1_public_matrix.md`](../../benchmarks/native_event/results/phase77_1_public_matrix.md)
- [`phase77_1_public_matrix.json`](../../benchmarks/native_event/results/phase77_1_public_matrix.json)
- [`phase77_2_pct_equity_wfo.md`](../../benchmarks/native_event/results/phase77_2_pct_equity_wfo.md)
- [`phase77_2_pct_equity_wfo_standard.md`](../../benchmarks/native_event/results/phase77_2_pct_equity_wfo_standard.md)
- [`phase77_2_pct_equity_wfo_v1.json`](../../benchmarks/native_event/manifests/phase77_2_pct_equity_wfo_v1.json)

Static public compact and audit routes are reported even when Rust is not
faster. Their shared Python preparation/report work can dominate sparse command
tapes. This is why backend promotion is a capability and correctness decision,
not a blanket speed promise.

Phase 77.1 adds the public five-mode WFO baseline before further migration. It
records `global`, eligible per-fold schedules, train/test, Mode 2's preserved
proxy path, Mode 5 full-sample calibration, requested/resolved scorer policy,
actual native score rows, and legacy `%_equity` fallback separately. It does
not advertise a W0 prepared scorer result as a reactive, bootstrap, portfolio,
package, or generic `%_equity` speedup. Read
[Public WFO Baseline V1](public_wfo_baseline_v1.md) and the
[percent-equity transition contract](../contracts/pct_equity_transition_v1.md)
with its generated artifact.

Phase 77.2 adds one explicit, paired `%_equity` workload only:
`target_runtime="rust"` plus `native_prepared_wfo="require"`. On its matched
10,000-bar, 64-trial, five-repeat standard fixture, the Rust transition route
has a `0.698 s` median versus `1.558 s` legacy (`2.231x`) while preserving the
public selection/accounting fingerprint. This is not a default-route, reactive,
portfolio, generic callback, or Mode 2 sampling speed claim.

## Required controls

1. Use the same deterministic fixture for compared routes.
2. Record event-clock contract, profile, warm/cold separation, and worker count.
3. Require exact accounting/trace parity before comparing throughput.
4. Record median and robust spread, not only a best sample.
5. Capture peak/incremental RSS using a documented method.
6. Version the baseline with its source commit, lockfile, Python/Rust toolchain,
   CPU/OS metadata, and fixture fingerprint.

The [Native Measurement Contract V1](measurement_contract_v1.md) defines the
versioned actual-work counters, source/wheel/data/intent identity, profile
matching, and the rule that historical evidence cannot auto-promote a route.

## Commands

```bash
make bench-smoke
make bench-native
make bench-facade
```

The committed E0/E3/E6 evidence is historical and workload-scoped. It does not
authorize backend promotion. Promotion requires clean staged wheels, compatible
native package evidence, a threshold owned by the workload manifest, and an
emergency Python rollback route.

The scheduled `Native Nightly Regression Evidence` workflow regenerates E0,
E3, E6, and prepared-score RSS artifacts on one declared CI host. It is an
observability tier, not a hardware-normalized release threshold: its artifacts
can detect a material regression, but they cannot promote `backend="auto"`.
