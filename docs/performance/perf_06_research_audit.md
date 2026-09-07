# PERF-06 Columnar WFO Research Audit

## Purpose

`PERF-06` adds an opt-in, immutable research sidecar to public
`QuantBTEndpoint.walk_forward(...)` runs. It separates two questions that had
previously been easy to conflate:

1. What financial output is retained for the selected final execution?
2. How much optimizer/search/selection provenance is retained for research?

The sidecar is built **after** the authoritative optimization and selection
work. It never replays a strategy, changes Optuna ask/evaluate/tell order,
changes a candidate score, replaces an order/fill ledger, or changes the final
stitched account. The normal WFO result tables remain the compatible default.

## Retention Contract

The axes are independent:

| Control | Values | Meaning |
|---|---|---|
| `financial_retention` | `score`, `compact`, `audit` | Selected-final financial summary, path, or original execution audit. |
| `research_retention` | `none`, `selected_only`, `full_trial_ledger` | No research sidecar, selected candidate provenance, or every actual optimizer trial/evaluation retained before public compaction. |
| `financial_retention_scope` | `selected_final_execution`, `segmented_reset_flat_execution` | Continuous stitched endpoint account or honest independent reactive-fold segments. |

Defaults are `financial_retention="score"` and `research_retention="none"`.
They preserve legacy result tables and do not allocate a columnar sidecar.

```python
bt = QuantBTEndpoint.walk_forward(
    strategy_class=strategy,
    target_mode="signal_notional",
    optimization_mode="mode_1_decay",
    optimization_config={
        "scoring_backend": "endpoint",
        "research_retention": "full_trial_ledger",
        "financial_retention": "compact",
        "financial_retention_scope": "selected_final_execution",
        "research_audit_chunk_rows": 256,
        "research_audit_max_chunks": 4096,
        "research_audit_max_materialized_frames": 3,
    },
)
result = bt.backtest(data=data, param_ranges=param_ranges)
audit = bt.research_audit
```

`compact` retains the original selected account equity/return path. `audit`
also requests original fills, orders, trades, diagnostics, margin, and
positions from the selected execution. QuantBT does **not** synthesize fills
from a target, position, equity, or fee path. If an active route exposes an
empty generic `fills` field but no original fill ledger, an `audit` request
raises; choose an audit-capable event route or request `compact` instead.

Reactive WFO has independent reset-flat fold accounts. Its runtime resolves the
only honest scope, `segmented_reset_flat_execution`, and retains per-fold paths
without fabricating one compounded equity curve.

## Artifact Surface

The artifact is available from either surface:

```python
audit = bt.research_audit
# Equivalent after an endpoint result is available:
audit = result.metadata["walk_forward"]["research_audit"]

metadata = audit.metadata()
trials = audit.to_pandas("trials")
evaluations = audit.to_pandas("evaluations")
selection = audit.to_pandas("selection")
deployments = audit.to_pandas("deployment")
legacy = audit.legacy_exports()
```

`to_pandas(...)` is a cold-path, lazy compatibility export. It is held in a
bounded local LRU and returns a defensive copy; a consumer cannot mutate the
artifact by changing a returned frame. `clear_materialized()` releases those
cold DataFrame caches. The typed chunks themselves are immutable NumPy
structure-of-arrays buffers with dictionary-encoded string columns and an
exact, versioned logical codec for timestamps, floats, tuples, mappings and
other supported values.

`legacy_exports()` provides `trial_table`, `trial_table_full`,
`candidate_table`, `candidate_table_full`, `evaluation_table`,
`selection_table`, `deployment_table`, `replay_table`, `performance_table`,
and `financial_table`. The ordinary public `trial_table` and `candidate_table`
are not replaced. Full-ledger records retain actual params, objective inputs,
statuses, fold metrics, study/fold IDs and selection metadata before the public
compact ledger discards optional detail.

## Provenance And Completeness

Each sidecar stores immutable, content-addressed manifests once:

```text
run_manifest -> search_space_manifest
             -> instrument_manifest
trial/evaluation -> analysis -> selection -> deployment -> replay/performance
```

The instrument manifest records the WFO target, calendar and intent contracts,
fold-account policy, prepared-market identity, and any declared symbol or
execution constraints. It intentionally stores no market tape; the prepared
context's content identity refers to the authoritative execution input.

Declared search spaces preserve numeric bounds/steps and categorical order.
When a conditional/dynamic parameter branch is observed but was not declared,
the manifest says `space_completeness="observed_only"`; QuantBT never invents
a search-space declaration or uses an arbitrary Python `repr` as identity.

The writer is a bounded, synchronous owned-chunk sink. A full queue means
backpressure; capacity exhaustion or export failure raises an explicit error.
Chunk retry is idempotent only when the same logical chunk digest is submitted.
Metadata distinguishes `memory_result_complete`, process completion flush, and
`crash_durable="not_provided"`; an ordinary in-memory flush is never advertised
as crash durability. Canceled writers retain their committed prefix, missing
range, and reason rather than pretending the research record is complete.

## Performance Evidence

Run the paired five-mode measurement after a clean source/build identity is
available:

```bash
PYTHONPATH=src .venv/bin/python \
  benchmarks/native_event/benchmark_perf06_research_audit.py \
  --bars 2048 --trials 16 --repeats 5
```

The benchmark compares the same public WFO request with the sidecar off and
with `full_trial_ledger`, verifies selected parameters, public tables, stitched
positions, and equity first, then reports the **cost** of complete research
retention: elapsed time, owned physical bytes, chunks, lazy legacy-export time,
and RSS. It does not claim a speedup for retaining fewer records.

The included slow-sink probe demonstrates owned synchronous backpressure only;
it deliberately makes no crash-durable claim. Generated candidate evidence is
written to `benchmarks/native_event/results/perf_06_research_audit.{json,md}`.

## Rollback

Set `research_retention="none"` and `financial_retention="score"` to return to
the legacy no-sidecar memory profile. This does not alter WFO mode, split,
schedule, strategy lifecycle, Optuna seed/order, selection, OOS stitching, or
financial accounting. It is not valid to roll back an explicitly requested
full financial audit by silently dropping audit data.
