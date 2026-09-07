# PERF-08 WFO Preparation

## Purpose

PERF-08 removes parameter-independent allocation and calendar work from the
normal public `QuantBTEndpoint.walk_forward(...)` path. It applies to Modes
1-4 automatically when `use_prepared_wfo_context=True` (the compatible
default), and keeps Mode 5 on the same prepared calendar/shard code where its
full-IS contract uses it.

This is not a new optimizer or a shortcut around evaluation. QuantBT still
executes every strategy call, Optuna trial, IS/OOS score, bootstrap draw, and
final stitched account required by the selected mode and schedule.

## What Is Prepared

One WFO invocation owns an immutable positional registry over its validated
canonical clock. It prepares only facts that cannot depend on candidate
parameters:

- contiguous train/test bounds for every fold;
- exact temporal IS shard boundaries using the historical NumPy
  quotient/remainder allocation rule;
- Mode 1 `per_fold_causal` inner-fold calendars;
- annualized trade-frequency requirements; and
- for eligible single-symbol endpoint scoring, one immutable OHLC/funding tape
  plus read-only contiguous views for certified score windows.

The registry is scoped by exact `DatetimeIndex` identity and the market view is
validated against the parent clock before use. A recreated or inconsistent
index uses the existing normalization/packing path. Nothing is cached across
WFO calls, no signal/strategy output is cached, and no result is reused during
adaptive Optuna sampling.

## Semantics That Remain Fixed

| Area | PERF-08 contract |
|---|---|
| Mode 1 | Global, `per_fold_decay`, and nested `per_fold_causal` study/order/decay semantics are unchanged. |
| Mode 2 | The existing NumPy stationary-bootstrap RNG, draw order, replicates, reduction order, and proxy boundary remain authoritative. |
| Mode 3 | Plateau, cluster, medoid/centroid, and tie-break behavior is unchanged. |
| Mode 4 | IS-only temporal/plateau selection remains isolated from outer OOS. `per_fold_causal` retains one independent study per outer fold. |
| Mode 5 | Full-sample calibration remains full-IS only; preparation does not invent chronological OOS semantics. |
| Accounting | Fees, funding, slippage, margin, liquidation, final continuous OOS stitch, and public reports retain the previous route. |

For the generic endpoint scorer, a prepared score window passes a private
run-local certificate to the backend. Legacy scorers without `score_batch()`
receive their historical keyword surface unchanged. The signal matrix can be a
read-only view only when its output index is the exact prepared score index;
otherwise QuantBT retains defensive reindexing and copying.

## Diagnostics

```python
wf = result.metadata["walk_forward"]

wf["prepared_wfo_context"]["window_preparation"]
wf["prepared_scoring_cache"]
```

Useful counters include `canonical_windows`, `prepared_shard_sets`,
`window_lookup_hits`, `shard_lookup_hits`, `full_market_cache_misses`,
`prepared_window_view_hits`, `signal_no_copy_hits`, and
`released_after_run`. They describe run-local preparation, not optimization
quality or a cross-run result cache.

## Measured Evidence

Run the reproducible paired public benchmark:

```bash
PYTHONPATH=src poetry run python \
  benchmarks/native_event/benchmark_perf08_public_wfo.py \
  --profile smoke

PYTHONPATH=src poetry run python \
  benchmarks/native_event/benchmark_perf08_public_wfo.py \
  --profile standard --mode mode_4_is_only_robust
```

The checked-in evidence is [smoke JSON](../../benchmarks/native_event/results/perf_08_public_wfo.json),
[smoke summary](../../benchmarks/native_event/results/perf_08_public_wfo.md),
and [Mode 4 standard JSON](../../benchmarks/native_event/results/perf_08_public_wfo_standard.json).
The exploratory broad evidence is [available separately](../../benchmarks/native_event/results/perf_08_public_wfo_broad.json).
On the recorded Linux/CPython 3.12 candidate, the 10k-hourly, three-fold,
48-trial-per-fold causal Mode 4 workload fell from `6.723 s` to `3.703 s`
(`1.82x`) with exact public selection and final-account parity. The smoke
matrix records Mode 1-4 separately; Mode 2 improves less because its fixed
bootstrap/resampling work remains intentionally unchanged.

The benchmark alternates reference/prepared runs with the same strategy,
calendar, parameter space, seed, account and retention. Its `memory_samples`
are same-process RSS/PSS plateau diagnostics; they are not presented as an
isolated private-memory comparison because allocator state is shared.

The `broad` profile is a one-pair, 50k-hourly expanding/semiannual Mode 4
exploratory workload. The recorded seven-fold, 100-trial-per-fold pair fell
from `58.420 s` to `21.119 s` (`2.77x`) with exact parity; it is deliberately
not a p95 claim:

```bash
PYTHONPATH=src poetry run python \
  benchmarks/native_event/benchmark_perf08_public_wfo.py \
  --profile broad --mode mode_4_is_only_robust
```

## Rollback

Set `"use_prepared_wfo_context": False` in `optimization_config` to restore
the prior WFO preparation path. This keeps the public endpoint, parameter
range, mode, strategy callback, selector, schedule, and account behavior
unchanged.
