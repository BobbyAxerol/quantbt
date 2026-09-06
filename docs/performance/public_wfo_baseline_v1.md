# Public WFO Baseline V1

Phase 77.1 establishes the public-workload reference for a Rust-primary WFO
upgrade. It records behavior first, then performance. The benchmark is
non-promotional and cannot change `backend="auto"` or route authority.

## What Is Measured

The runner uses a deterministic W0 Python callback and records the entire
public `QuantBTEndpoint.walk_forward()` or `train_test_split()` call. Every row
contains requested and resolved prepared-native policy, actual native score
rows/batches, final backend, selection/causality claim, output fingerprint,
outer-test work count, full timing, measured fold/strategy/score timings and
same-process RSS/PSS snapshots.

The five optimization modes remain distinct:

| Mode | Public schedules in the baseline | Authority boundary |
|---|---|---|
| `mode_1_decay` | global, per-fold decay, nested per-fold causal, train/test | Endpoint scorer can use the bounded prepared-native scalar route for eligible W0/W1/W2 signal targets. |
| `mode_2_sbb` | global, train/test | Python/NumPy path-resampling proxy stays authoritative; it is recorded as `proxy_preserved`, not compared as a Rust scorer. |
| `mode_3_flat_minima` | global, train/test | Endpoint scorer parity is required before timing the prepared-native lane. |
| `mode_4_is_only_robust` | global, per-fold causal, train/test | Strict per-fold causal selection remains IS-only; public scorer parity is required before timing. |
| `mode_5_full_robust` | full declared sample | Full-sample calibration only; it is never relabelled as an OOS protocol. |

Legacy `%_equity` is separately exercised through its transition-sized
reference contract. The baseline `auto` row deliberately remains legacy. Phase
77.2 adds a separate explicit Rust opt-in, not an automatic promotion; see
[Percent-Equity Transition Contract V1](../contracts/pct_equity_transition_v1.md).
Its historical `fee` compatibility input is reconciled to canonical one-way
`fee_rate` before the explicit route is admitted, so a benchmark never compares
different cost models.

## Profiles

The matrix has bounded, named profiles rather than an uncontrolled product of
bars, candidates, folds and symbols:

| Profile | Bars / bar interval | Calendar folds | Trials | Repeats | Purpose |
|---|---:|---:|---:|---:|---|
| `smoke` | 720 / `1D` | quarterly after 180D training | 4 | 1 | Run every required public mode/schedule and prove requested/resolved routing. |
| `standard` | 10,000 / `1h` | three quarterly folds after 180D training | 64 | 5 | Alternating paired W0 Mode 1 global headline comparator after warm-up. |
| `long` | 100,000 / `1h` | approximately twelve yearly folds after 30D training | 256 | 1 | Explicit resource/stability probe only; never run by accident. |

The W3 reactive runner is intentionally separate because it has a Python
strategy callback, a wake scheduler and a candidate-batch contract. Its
existing timing evidence remains [Phase 76](../../benchmarks/native_event/results/phase76_reactive_wfo.md), not a generic W0 WFO speedup claim. Phase 76
also locks fixed-candidate selector parity for Modes 1, 3, 4 and 5; it does
not advertise a Mode 3/4/5 timing result that was never measured. Direct
target, [shared portfolio](../../benchmarks/native_event/results/phase67_shared_portfolio.md),
and [bounded package](../../benchmarks/native_event/results/phase68_bounded_package.md)
routes likewise remain separately labelled bounded products rather than being
presented as generic callback WFO.

## Running The Evidence

```bash
# Complete routing/selection matrix.
PYTHONPATH=src .venv/bin/python benchmarks/native_event/benchmark_phase77_1_public_matrix.py \
  --profile smoke

# Five warm paired repetitions of the declared standard route.
PYTHONPATH=src .venv/bin/python benchmarks/native_event/benchmark_phase77_1_public_matrix.py \
  --profile standard

# Deliberate stress run only.
PYTHONPATH=src .venv/bin/python benchmarks/native_event/benchmark_phase77_1_public_matrix.py \
  --profile long --allow-long
```

The smoke profile writes `phase77_1_public_matrix.json`; standard and long use
their own `phase77_1_public_standard.json` and
`phase77_1_public_long.json` names so evidence is not overwritten. Markdown is
written beside each JSON artifact. A paired row first warms both lanes and
requires exact public result fingerprints before alternating timing order. It
reports median and p95 only within the same profile; component timers are not
summed and advertised as an exact decomposition of a full run.

## Reading The Result

`native_prepared` means only bounded fresh candidate/fold scalar scoring ran
through the prepared-native scorer. It does not mean Optuna, callback strategy
generation, mode-specific selection, the final stitched account, or reports
became Rust-owned. `fallback` and `proxy_preserved` are success states when
they match the declared authority boundary. A fallback has no Rust speed ratio.

Candidate/fold visits use outer declared test windows as a transparent lower
bound. Native score rows/bars are reported separately because Mode 1 inner
folds, Mode 2 paths and mode-specific shard evaluations are not interchangeable
units of work.

## PERF-05 Exact Evaluation Reuse

The public baseline remains valid with PERF-05 enabled because cache reuse is
not permitted during adaptive Optuna evaluation. It can only return an exact
completed prepared-native terminal metric later during report-only candidate
analysis in the same run. The cache is bounded and released at teardown;
duplicate trials, separate per-fold studies, and stochastic identities retain
their own execution-attempt provenance.

Its evidence is deliberately separate from this Phase 77 baseline:
[PERF-05 WFO evaluation reuse](perf_05_wfo_evaluation_reuse.md). It records
policy-off, bounded-LRU, and high-hit Mode 1 lanes plus cache-off/on parity for
all five modes. Mode 2 remains proxy-preserved; current Mode 5 has no identical
post-study execution, so `auto` disables the cache rather than retaining dead
entries.

## Phase 77.2 Evidence And Phase 77.3 Boundary

Phase 77.2 is complete for the explicit transition-sized `%_equity` route.
It matches the legacy financial fixture, accepted units, public raw-signal
surface, candidate selection, trial table, stitched output, equity/returns and
public report for Modes 1, 3, 4, and 5. Mode 2 remains
`proxy_preserved`: its stationary/regime/stress/GARCH path sampler has a
different RNG/proxy contract and is not relabelled as Rust execution.

The paired Phase 77.2 standard workload is 10,000 `1h` bars, three quarterly
folds after 180D training, 64 trials, and five alternating post-warm repeats:

| Lane | Median | P95 | Result |
|---|---:|---:|---|
| legacy `%_equity` reference | 1.558 s | 1.856 s | oracle |
| explicit Rust transition | 0.698 s | 0.791 s | exact public parity |

That is `2.231x` paired speedup for this named opt-in workload only. The
corresponding smoke result is `3.806x`; neither number is a generic WFO,
portfolio, reactive, or Mode 2 claim. Artifacts are
`benchmarks/native_event/results/phase77_2_pct_equity_wfo*.{json,md}` and the
measurement manifest is
`benchmarks/native_event/manifests/phase77_2_pct_equity_wfo_v1.json`.

Phase 77.3 owns reactive sparse state, batch semantics, cancellation and any
Mode 2 work. It may not reuse a W0 score speedup claim to promote a callback or
bootstrap route. Both phases require their own parity, resource and public
measurement evidence before promotion is considered.

## Phase 77.3 Reactive Closure Evidence

Phase 77.3 is a separate R1/R2/R3/W3 runtime closure, not an extension of the
W0 WFO speed claim above. It uses reusable symbol-sized wake observations,
typed wake-plan wires on the optimized R2/R3 path, bounded active-work
cancellation/deadlines, reset-safe scalar sessions, and cold-path-only result
adaptation. A legacy payload-only wake plan remains supported through its
adapter.

Run the current-candidate evidence as its own named workload:

```bash
PYTHONPATH=src .venv/bin/python \
  benchmarks/native_event/benchmark_phase77_3_reactive_closure.py \
  --profile standard
```

The artifact reports R1/R2/R3 public-minimal and scalar lanes separately, then
reports W3 sequential and R3B work separately. It also reruns small
public-WFO, shared-portfolio, bounded-package and intrabar parity controls.
Historical Phase 75/76 artifacts are immutable scope records with different
source identities and repeat counts, so they are not converted into a
promotion-eligible before/after percentage. Active interrupt behavior is
proved independently by the Phase 77.3 resource tests: a sparse/block native
gap checks at most every 64 completed account bars and again at its wake/end
boundary; a canceled or timed-out scalar result cannot become a selector row.
