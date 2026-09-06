# Native Runtime Governance V1

Phase 71 adds one bounded runtime contract for native-event and prepared WFO
service workloads. It changes no execution mathematics and is inert when all
limits are omitted.

## Public Contract

```python
from quantbt import QuantBTEndpoint, RuntimeBudgetV1

bt = QuantBTEndpoint.event_driven(
    input_mode="orders",
    profile="audit",
    backend="auto",
    runtime_budget=RuntimeBudgetV1(
        max_bars=100_000,
        max_commands=250_000,
        max_orders=100_000,
        max_fills=100_000,
        max_audit_rows=20_000,
        max_native_memory_bytes=512 * 1024 * 1024,
        max_wall_time_ms=60_000,
        max_workers=4,
    ),
)
```

Limits are admission or safe-point gates. A backend that cannot enforce a
requested limit rejects it; it must not silently ignore the value. Static
command tapes can preflight bars, commands, orders, fills, and prepared bytes.
Prepared WFO checks candidate/fold boundaries and returns typed
budget/cancellation statuses from Rust.

`RuntimeBudgetError.code` is stable and machine-readable. Current values
include `MAX_BARS`, `MAX_WORKERS`, `MAX_NATIVE_MEMORY`, `MAX_METRIC_ROWS`,
`MAX_AUDIT_ROWS`, `MAX_COMMANDS`, `MAX_ORDERS`, `MAX_FILLS`, and
`MAX_WALL_TIME`.

### Reactive Deadline And Cancellation Semantics

For the explicit Rust reactive R1/R2/R3 and W3 routes,
`max_wall_time_ms` is enforced inside active native execution. The timer starts
after a fresh account is initialized for each score/window. R1 checks at each
completed account-bar boundary. R2 sparse wake and R3 block gaps check at a
completed account-bar boundary at most every 64 bars, and once more before
returning at a wake, liquidation, or end boundary. This bound avoids an
asynchronous abort in the middle of an accounting step or Python callback.

`runtime.cancel()` follows the same rule: it signals the active native scalar
or candidate-batch runner, and a canceled score is discarded before Python
adapts it into a result or Optuna selector row. `reset()` clears the active
cancel/deadline state before an independent fresh-account run. A process W3
worker reports the typed failure and is discarded before another task can reuse
its account or strategy scratch.

## Ownership And Teardown

Prepared WFO runtimes and signal batches have explicit `close()` methods.
Use-after-close and cross-runtime handle reuse fail. `reset()` advances the
worker generation while preserving an immutable prepared batch in the same
session. `cancel()` marks queued candidate/fold rows with the typed canceled
status; `clear_cancellation()` permits an independent subsequent run.

`ParallelismPlanV1` coordinates Python processes, Rust workers, BLAS, OpenMP,
and Numba. A multi-process or multi-worker run defaults auxiliary thread pools
to one thread so nested pools do not oversubscribe the host.

## Audit And Shadow Safety

`BoundedAuditSinkV1` retains a declared row count, tracks dropped rows, and can
stream deterministic chunks through an export hook. Financial accounting is
never truncated with the audit detail.

Sampled reactive oracle comparisons record match/mismatch counters. A mismatch
writes a JSON evidence bundle under `shadow_evidence_dir`, or under the audit
artifact parent/default `.quantbt/shadow-mismatches` directory. It activates a
backend-instance kill switch: a later `auto` run falls back to Python and an
explicit Rust request fails closed. `QUANTBT_DISABLE_NATIVE=1` remains the
process-level emergency rollback.

Inspect `result.metadata["runtime_governance_v1"]` or
`backend.runtime_diagnostics` for budgets, cancellation state, fallback count,
shadow count, and the last mismatch bundle.

## Soak Evidence

The Phase 71 fixed workload uses 4,096 supplied bars, 32 candidates, four
folds, two workers, and 30 repeated warm scores on one prepared tape. It
measured a median 13.325 ms, 8.20 million actual candidate-test-bar visits/s,
and a flat 162.98 MiB RSS sample series with 0.0 MiB tail spread. The former
39.35M figure remains logical full-tape input-volume/s, not executor work.
Reset, cancellation, post-cancel recovery, terminal fingerprints, and zero
warm market/intent copy all passed.

This is a prepared static-IR WFO workload, not a claim for arbitrary Python
callbacks or end-to-end alpha feature generation.
