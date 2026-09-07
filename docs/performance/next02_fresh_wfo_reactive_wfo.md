# NEXT-02 Fresh WFO And Reactive-WFO Closure

## Scope

NEXT-02 measures public, cache-cold walk-forward studies after the NEXT-01
reactive runtime closure. It preserves fold construction, Optuna
ask/evaluate/tell order, mode-specific objective mathematics, candidate
selection, reset policy, fees, funding, margin, and final-result contracts.
It does not treat a cache hit, checkpoint resume, changed sampler, or a
different strategy protocol as a fresh-study speedup.

Two independently public routes are measured:

| Outcome | B1 comparator | B2 route | Primary contract |
| --- | --- | --- | --- |
| O-W1 | ordinary QuantBTEndpoint.walk_forward endpoint scorer | prepared native score route | Same callable strategy, candidates, seed, account, final stitched result, and wfo_execution_reuse="off" |
| O-W2 | prepare_reactive_walk_forward with preparation_policy="compatibility" | the same route with preparation_policy="prepared" | Same factory, callbacks, candidates, seed, fold accounts, selection, and reset-flat audit segments |

The primary acceptance target is paired median B2/B1 <= 0.70 on the Mode 4
causal workload below. The supported-mode matrix is also executed as a parity
and fresh-account smoke; it is not averaged into the primary acceptance row.
A p95 claim is deliberately withheld until at least 100 paired samples are
available.

## Qualified Mode 4 Causal Evidence

The primary fixture is a 2,000-bar deterministic single-symbol daily tape,
four candidate trials, rolling windows, quarterly outer folds, four IS shards,
and mode_4_is_only_robust with optimization_schedule="per_fold_causal".
Every timed repetition creates fresh public endpoint/runtime objects and
alternates comparator order. It therefore measures a new study rather than a
warm cache/resume path.

| Outcome | Samples | B1 median | B2 median | Paired B2/B1 p50 | Bootstrap CI95 | Result |
| --- | ---: | ---: | ---: | ---: | --- | --- |
| O-W1 ordinary WFO | 30 | 1.360 s | 0.672 s | 0.4997 | [0.4835, 0.5387] | MET, about 2.00x faster |
| O-W2 reactive WFO | 30 | 0.610 s | 0.423 s | 0.6961 | [0.6648, 0.7163] | MET, about 1.44x faster |

The ordinary B2 route makes 73 native score batches for 305 candidate/fold
rows and 43,620 scored bars. The reactive fixture makes 248 fresh scalar score
calls and 38,508 callback bars in both lanes. Prepared reactive execution
remains fresh-account per task; it reuses only immutable market/calendar/window
state.

Each paired row asserts selected parameters, params_by_fold, best-trial
provenance, trial/candidate/fold tables, OOS segment equity/returns/positions,
fees, funding, margins, and strategy fingerprints. The ordinary route retains
its final stitched account. Reactive WFO intentionally retains independent
reset-flat fold segments and never fabricates a compounded OOS curve.

Raw, reproducible evidence is committed with the source tree:

- [ordinary Mode 4 causal, 30 pairs](../../benchmarks/native_event/results/next02_mode4_causal_30.md)
- [reactive Mode 4 causal, 30 pairs](../../benchmarks/native_event/results/next02_reactive_mode4_causal_30.md)

These are source-tree measurements on the recorded Linux CPython environment,
not a published-wheel, multi-platform, generic callback, or arbitrary-alpha
claim.

## Public Configuration

Ordinary WFO keeps its normal endpoint API. The prepared native scorer remains
an explicit, narrow route; unsupported requests retain the historical scorer
under "auto" or fail closed under "require".

~~~python
endpoint = QuantBTEndpoint.walk_forward(
    strategy_class=my_strategy,
    target_mode="signal_notional",
    optimization_mode="mode_4_is_only_robust",
    optimization_config={
        "scoring_backend": "endpoint",
        "native_prepared_wfo": "require",
        "wfo_execution_reuse": "off",  # Fresh-study measurement or reproduction.
        "scoring_trading_days": 365,
    },
    target_runtime="rust",
)
~~~

For stateful reactive WFO, preparation is a public runtime policy rather than
an internal constructor toggle:

~~~python
runtime = endpoint.prepare_reactive_walk_forward(
    data=market_data,
    strategy_factory=my_factory,
    walkforward_config=walkforward_config,
    runtime_config=ReactiveWfoRuntimeConfigV1(
        preparation_policy="prepared",  # Default: immutable market/fold state once per run.
    ),
    symbols=["BTCUSDT"],
)
~~~

"compatibility" is retained as a diagnostic baseline. It preserves the same
selection and economics while intentionally skipping prepared calendar/window
reuse. Inspect result.metadata["runtime"]["preparation_policy"] and
result.metadata["wfo_preparation"] to see the resolved policy and counters.

## Mode And Boundary Matrix

| Route | Mode 1 | Mode 2 | Mode 3 | Mode 4 | Mode 5 |
| --- | --- | --- | --- | --- | --- |
| Ordinary prepared-native scorer | Existing exact mode semantics | Existing bounded path/bootstrap proxy; no scalar substitution | Existing landscape/plateau selection | Existing IS-only selector; causal schedule preserved | Existing full-IS selector |
| Reactive WFO W3 | Supported | Explicitly unsupported: no return-path proxy replacement | Supported | Supported | Supported |

per_fold_decay continues to use its declared outer-OOS decay behavior;
per_fold_causal keeps selection at the current fold's IS boundary. This phase
does not change either schedule or turn OOS into an optimization input for Mode
4 or Mode 5.

## Reproduce

Run from a checkout with the native extension installed:

~~~bash
MPLCONFIGDIR=/tmp PYTHONPATH=src poetry run python \
  benchmarks/native_event/benchmark_next02_fresh_wfo.py \
  --profile smoke --mode mode_4_is_only_robust \
  --schedule per_fold_causal --repeats 30 \
  --output /tmp/next02-mode4-ordinary.json

MPLCONFIGDIR=/tmp PYTHONPATH=src poetry run python \
  benchmarks/native_event/benchmark_next02_reactive_wfo.py \
  --profile smoke --mode mode_4_is_only_robust \
  --schedule per_fold_causal --repeats 30 \
  --output /tmp/next02-mode4-reactive.json
~~~

The benchmark exits non-zero on any public parity or fresh-account failure.
It emits a JSON artifact and a concise Markdown companion. CPU affinity,
background load, extension version, and source identity are recorded in the
artifact; do not compare raw milliseconds across a different machine as a
release-speed claim.

## Limits

- Mode 2 reactive WFO remains unsupported because its path/bootstrap proxy is
  not interchangeable with dynamic lifecycle accounting.
- Generic Python callback decision cost remains Python-owned; this evidence is
  for the documented numeric reactive W3 contract.
- The 30-pair evidence qualifies paired p50 only. It intentionally makes no
  p95/tail-latency claim.
- Full-sample Mode 5 reactive WFO has less reusable window setup: its 30-pair
  B2/B1 p50 is 0.8266 on this fixture while exact parity passes. Its 20 fresh
  scalar account windows remain governed by the same Python callback and Rust
  accounting contract in both lanes. It is reported as a supported-mode
  parity/gain measurement, not averaged into the Mode 4 acceptance result or
  misrepresented as a failed economic calculation.
- Prepared state is run-local and immutable. It never carries a strategy,
  account, order, random state, or completed trial result into another fresh
  candidate/fold execution.
