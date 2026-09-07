# NEXT-01 Reactive Public Runtime Closure

## Scope And Status

This document records a source-tree B1-to-B2 comparison for the ordinary
Python compatibility callback route. It is not a Rust callback promotion, a
generic WFO result, or a comparison with a published package.

- **B1:** clean worktree at `bcacb48`, before the NEXT-01 runtime changes.
- **B2:** clean worktree at `fe7ebfd`, with the exact runtime-file SHA-256
  digests recorded in each raw artifact.
- **Environment:** Linux x86_64, CPython 3.12.13, NumPy 2.2.6, pandas 2.3.3;
  one isolated CPython child at a time and alternating ABBA comparator order.
- **Retention:** the public complete-audit result remains retained. Timing does
  not switch to `minimal` or scalar-score retention.
- **B0:** `INCONCLUSIVE`. This machine has no separately pinned installed
  historical core/native product artifact under the same corrected contract.
  B1 is the reproducible local comparator for this phase; it does not replace
  a product-release comparison.

The gate is intentionally evidence-only. It verifies timing shape, fresh-cache
properties, and supplied parity flags; the benchmark independently asserts
financial and audit equality before it emits a raw artifact.

## Public Route

The tested public route is unchanged:

```text
QuantBTEndpoint.native_event_strategy(...).simulate(strategy=...)
  -> QuantBTEndpoint._run_native_event_strategy
  -> NativeEventBackend.run_strategy
  -> PreparedStrategyAdapter
  -> NativeEventReactiveSession
  -> NativeEventBackend._reactive_session_result
  -> canonical accounting trace / result adapter
```

`NativeEventBackend.run_strategy` retains the event-lifecycle simulation owner:
matching, fee, funding, margin, liquidation, order lifecycle, and account
state are still processed on every bar. The callback remains Python decision
authority for an arbitrary object strategy.

## Changes

| Area | Implementation | Contract kept |
| --- | --- | --- |
| Callback plan | `PreparedStrategyAdapter` compiles schedule/callback availability once. | Dynamic callback replacement remains the default. |
| Sparse wake | A declared sparse schedule is checked before context construction or callback lookup. | Every financial bar still advances; only permitted callback work is skipped. |
| Compatibility context | `NativeStrategyContext.timestamp` materializes a pandas timestamp only when read. | A public read still returns the same UTC `pd.Timestamp`; retained contexts remain snapshots. |
| Context construction | The session directly constructs the public dataclass without an intermediate kwargs factory. | Field values, causal availability, and exception context are unchanged. |
| Audit replay | Canonical trace columns replay directly from typed retained columns when available. | Fingerprint, row count, replay, ledger, and legacy DataFrame fallback remain exact. |
| Binding opt-in | `quantbt_reactive_callback_binding_v1 = "run_stable"` pins callbacks for one run only. | Omit it, or use `"dynamic"`, to preserve mutation-aware legacy behavior. |

No fee, slippage, funding, timing, lot, margin, matching, or result-schema
policy changes are in this phase.

## Paired Results

Median public wall time and isolated-process peak RSS. `B2/B1` is calculated
pairwise, not from independent best samples.

| Workload | Samples | B1 | B2 | B1 -> B2 throughput | B2/B1 median | Peak RSS B1 / B2 | Gate |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| Every-bar compatibility callback, 100k bars, low orders | 100 | 6.075 s | 4.233 s | 16,461 -> 23,625 bars/s | 0.7079 | 305.631 / 305.654 MiB | O-R1 MET |
| Declared sparse compatibility callback, 100k bars | 100 | 5.477 s | 2.430 s | 18,259 -> 41,145 bars/s | 0.4473 | 305.389 / 305.480 MiB | O-R2 MET |
| Every-bar compatibility callback, 100k bars, high churn | 3 | 6.880 s | 4.951 s | 14,535 -> 20,196 bars/s | 0.7411 | 310.434 / 309.973 MiB | parity smoke only |
| Parent/OCO lifecycle, 25k bars | 3 | 1.769 s | 1.286 s | 14,129 -> 19,440 bars/s | 0.7208 | 196.645 / 196.625 MiB | parity smoke only |
| GTD lifecycle, 25k bars | 3 | 1.921 s | 1.287 s | 13,016 -> 19,420 bars/s | 0.6702 | 195.535 / 195.527 MiB | parity smoke only |

For O-R1, the 100-pair bootstrap CI95 for the median ratio is
`[0.6848, 0.7176]`; observed p95 ratio is `0.6933` against the `1.05` budget.
For O-R2, the CI95 is `[0.4411, 0.4622]`; observed p95 ratio is `0.4773`.
The three-pair lifecycle rows confirm exact behavior on a final candidate, but
are intentionally not presented as tail-latency certification.

## Correctness Evidence

Every paired raw row must agree on:

- final equity, fill, command, and event counts;
- full equity, return, position, fee, funding, and margin array hash;
- canonical trace fingerprint, row count, and replay result;
- accounting-ledger fingerprint.

The focused contract corpus covers dynamic versus run-stable binding, sparse
wake behavior, retained timestamp snapshots, direct-column replay, callback
errors, staged commands, lifecycle, audit, and prepared/reactive boundaries.
It is complemented by existing native-event contract, ownership, sparse,
coroutine, and audit tests. Rust per-bar callback bridging was profiled and is
not promoted: the object boundary is slower than the optimized Python
compatibility route on this workload.

## Reproduce

Create the B1 worktree at the recorded commit, then run each comparison from a
clean B2 checkout:

```bash
git worktree add --detach /tmp/quantbt-next01-b1 bcacb48

PYTHONPATH=src poetry run python benchmarks/native_event/benchmark_generic_callback_audit.py \
  --baseline-source /tmp/quantbt-next01-b1 \
  --candidate-source . \
  --paired-order abba \
  --repeats 100 \
  --cases 100k_low_orders \
  --output /tmp/next01-everybar.json

PYTHONPATH=src poetry run python tools/materialize_generic_callback_pairs.py \
  /tmp/next01-everybar.json \
  --case 100k_low_orders \
  --output /tmp/next01-everybar.pairs.json

PYTHONPATH=src poetry run python tools/gate_paired_timings.py \
  /tmp/next01-everybar.pairs.json \
  --target-ratio 0.80 --p95-budget 1.05
```

The sparse run uses `100k_declared_sparse` and `--target-ratio 0.70`. Raw and
materialized artifacts for this candidate are committed at:

- [`quantbt-next01-final-everybar-100.json`](../../benchmarks/native_event/results/quantbt-next01-final-everybar-100.json)
- [`quantbt-next01-final-everybar-100.pairs.json`](../../benchmarks/native_event/results/quantbt-next01-final-everybar-100.pairs.json)
- [`quantbt-next01-final-sparse-100.json`](../../benchmarks/native_event/results/quantbt-next01-final-sparse-100.json)
- [`quantbt-next01-final-sparse-100.pairs.json`](../../benchmarks/native_event/results/quantbt-next01-final-sparse-100.pairs.json)
- [`quantbt-next01-final-lifecycle-3.json`](../../benchmarks/native_event/results/quantbt-next01-final-lifecycle-3.json)

## Boundaries And Rollback

This phase does not accelerate generic fresh WFO or reactive-WFO studies; that
is NEXT-02. It also does not claim a fully native route for arbitrary Python
callbacks. The independent numeric R1/R2/R3 routes remain separately documented
and benchmarked.

Rollback is limited to reverting the NEXT-01 runtime commits while retaining
the same economic contract. Do not substitute a different account, timing, or
audit policy merely to compare timing.
