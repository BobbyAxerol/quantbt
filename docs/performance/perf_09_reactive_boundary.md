# PERF-09 Reactive Boundary Closure

PERF-09 closes the reactive complement to PERF-08. It optimizes only
engine-owned preparation and the Python/Rust callback bridge for the explicit
Reactive WFO (W3) route. It does not cache a user strategy decision, replay a
command tape in place of a callback, change an Optuna ask/tell sequence, or
change reset-flat account semantics.

## Scope

Reactive WFO is a separate stateful contract from ordinary target-series WFO:

| Area | PERF-09 behavior |
|---|---|
| Supported modes | `mode_1_decay`, `mode_3_flat_minima`, `mode_4_is_only_robust`, `mode_5_full_robust` |
| Unsupported mode | `mode_2_sbb`; its return-path proxy is not a reactive lifecycle contract |
| Accounts | Every candidate/fold and selected OOS segment starts flat |
| Strategy state | One fresh Python strategy per task; no cross-task reuse |
| Calendar work | Run-local, identity-validated positional windows, IS shards, annualized trade requirements, and Mode 1 causal inner folds |
| Market core | One immutable Rust prepared tape, with a backend-owned precomputed content key for repeated prepared runs |
| Callback binding | Dynamic lookup remains the default; `run_stable` is an explicit opt-in only |
| Public API | No endpoint, strategy-factory, config, schedule, output, or retention contract changed |

The calendar registry admits a positional fast path only when the runtime,
strategy adapter, `DatetimeIndex`, and prepared window are exactly the same
objects. An equivalent reconstructed index falls back to the original checked
indexer path. The market binding is similarly private to one backend instance
and exact read-only arrays. A foreign backend or a mismatched tape cannot reuse
its content key.

## Correctness Controls

`tests/test_perf_09_reactive_boundary.py` compares the pre-preparation path
against the optimized path for Mode 1 per-fold causal, Mode 3 global, Mode 4
per-fold causal, and Mode 5 global. It locks:

- selected params, per-fold params, trial/candidate/fold tables and selection;
- task coordinates, causal strategy fingerprints and fresh-account boundaries;
- equity, positions, fees and funding for every selected OOS segment;
- Mode 4 shard and Mode 1 nested-fold preparation use;
- dynamic R3B callback mutation versus explicit `run_stable` pinning; and
- scalar score parity with and without the prepared market binding, plus
  fail-closed rejection of a binding from another backend.

Existing Phase 76, Phase 77.3 and PERF-03 reactive regressions remain part of
the affected-suite gate. The feature has no route that silently promotes an
unsupported Mode 2, carries a fold account, or converts a reactive result into
a fabricated compounded equity curve.

## Measured Evidence

The paired benchmark is
[`benchmark_perf09_reactive_boundary.py`](../../benchmarks/native_event/benchmark_perf09_reactive_boundary.py).
It uses one Rust W3 strategy, the same candidate space, deterministic seed,
market tape, reset-flat accounts and retention on both sides. The only toggle
is private run-local preparation. Results are written to the checked-in
[JSON](../../benchmarks/native_event/results/perf_09_reactive_boundary.json)
and [summary](../../benchmarks/native_event/results/perf_09_reactive_boundary.md).

On the current Linux / CPython 3.12 source-tree candidate, 2,000 daily bars,
eight candidates and five alternating repeats measured:

| Workload | Baseline median | PERF-09 median | Gain | Actual score bars |
|---|---:|---:|---:|---:|
| Mode 4 / `per_fold_causal` sequential | 624.709 ms | 316.975 ms | 1.97x | 32,390 |
| Mode 1 / fixed-matrix R3B throughput | 315.865 ms | 129.568 ms | 2.44x | 43,040 |

The R3B row is not a sequential-TPE comparison: it keeps its explicit global
fixed-matrix sampling contract on both sides. The JSON records source/build,
typed tape and intent identity, exact result fingerprints, task-window fast-path
counts, baseline fallback counts, Mode 4 shard use and same-process RSS/PSS
deltas. RSS/PSS is a plateau diagnostic, not isolated memory attribution.

The matching local Linux CPython candidate pair passed source-hash parity,
isolated core/native installation, direct native-target smoke, and source-tree
import blocking. This is local artifact evidence, not a substitute for the
published-wheel matrix and release admission owned by Phase 78.

## Operational Notes

There is no new user flag for this work. Normal W3 callers continue using
`QuantBTEndpoint.prepare_reactive_walk_forward(...)`. The implementation is
automatic for valid prepared W3 inputs and preserves a checked fallback for
every nonmatching private identity. Call `runtime.close()` as before to release
the prepared strategy, scalar session pool and run-local preparation metadata.

PERF-09 performance is bounded by user Python callback computation. Rust owns
market traversal, orders, fills, fees, funding, margin, liquidation and scalar
account state, but it intentionally cannot optimize an arbitrary alpha's
decision code without changing the strategy contract.
