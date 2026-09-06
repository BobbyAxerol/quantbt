# PERF-01 Computation And Observer Contract

`PERF-01` adds planning and measurement metadata to the public walk-forward
engine. It does not replace an accounting engine, a metric reducer, a selector,
or an execution clock.

## Scope

`RequiredComputationPlanV1` is compiled once when `WalkForwardEngine.run()`
prepares a run. It currently governs all five WFO modes plus fixed/no-Optuna
replay. The wider public-route ownership map is generated in
[PERF-01 traceability](../performance/perf_01_traceability.md); later PERF
phases own route-specific runtime changes outside WFO.

The plan records:

- optimization mode, schedule and scoring backend;
- financial and research retention contracts;
- observation kinds, required intermediate paths and reducers;
- required public output sinks and pruning-checkpoint intent; and
- whether a scalar-only native score route is eligible.

`OnlineMetricReducerV2` and the existing backend-specific accounting paths
remain authoritative for financial calculations. The plan is a compatibility
guard around those paths, not a second metric implementation.

## Observation Identity

An `ObservationIdV1` has a stream, kind, ordinal and optional subsequence.
`ObservationLedgerV1` lets each named reducer claim an observation once. A
return sample and a fill on the same bar are distinct observation kinds. This
prevents a later consumer from accidentally updating the same reducer twice
while preserving independent reads by different reducers.

## Conservative Custom Metrics

An opaque `metadata["custom_metric_requirements"]` declaration means QuantBT
cannot prove which execution observations the metric needs. The computation
plan therefore retains `full_execution_observation_stream` and marks
`native_score_eligible=False`. A requested scalar-only prepared-native route
raises; `auto` records a clear fallback rather than discarding unknown inputs.

## Opt-In Observer

Set this in `optimization_config` for diagnostic runs:

```python
"perf_01_profile": True
```

The resulting `result.metadata["walk_forward"]["perf_01_profile"]` uses five
exclusive timing buckets:

1. `prepare_validate_ingest`
2. `advance_match_account_wake`
3. `projection_python_decision_command_write_ingest`
4. `metrics_analysis_audit_encode_flush_public_adapt`
5. `reset_cache_lookup_queue_wait`

Nested buckets are rejected, so one wall-time sample cannot enter two stages.
Counters distinguish native outer entries, strategy/callback entries,
getter/writer crossings, command-ingest batches, observation passes, audit
work, cache events and reset/worker events. A counter of `null` means that this
route did not instrument that boundary; a measured zero is `0`.

When disabled, the observer does not run on strategy/scoring hot calls. It
does not alter Optuna seed/order, pruning, selection, target stitching, or the
final endpoint account reconstruction.

## Ownership And Reproducibility

Prepared WFO contexts are run-local. Their content signatures protect all
timestamped strategy columns, and strategy-visible causal slices are isolated.
Financial retention and research/audit retention are independent requirements.
No fast-math, RNG substitution, tie-break change, audit elision, or cache reuse
across a changed economic identity is authorized by this contract.

The committed traceability artifact is content-addressed using source hashes.
Machine-local commit, dirty state, package/module origin, toolchain and typed
market/intent hashes are captured separately with:

```bash
PYTHONPATH=src .venv/bin/python tools/generate_perf01_traceability.py \
  --runtime-identity /tmp/perf01-runtime-identity.json
```

That temporary identity is input to a workload-specific benchmark record. It
must not contain credentials, private market data, or private strategy paths.
The public observer artifact retains native extension version/API/content hashes
but redacts machine-local extension paths before it is committed.

## Baseline Interpretation

The checked-in [observer baseline]
(../../benchmarks/native_event/results/perf_01_observer_baseline_v1.json)
uses alternating observer-off/on samples. Its p50 and p95 budget comparisons
are ratios of the corresponding latency quantiles from each condition. The
per-pair delta distribution is a separate order and scheduler-noise diagnostic;
it must not be misreported as the p95 latency regression. A source candidate
must be clean when the artifact is generated, and its commit/data/intent hashes
must match the artifact provenance. The local PERF-01 record is deliberately
non-promotional: it establishes a regression baseline for later phases rather
than authorizing a backend or release decision.
