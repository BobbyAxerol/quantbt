# P1 Strategy Boundary, Rust Ownership, And Audit Contract

## Certified Scope

Phase 52B completes the P1 reactive strategy boundary for Native Event V2.
It preserves the existing `QuantBTEndpoint.native_event_strategy()` and
`QuantBTEndpoint.event_driven()` public APIs while giving declared numeric
strategies a lower-object callback path. The execution contract remains causal:
commands emitted after bar `t` become eligible from the configured next bar,
never inside the bar just observed by the strategy.

## Strategy Modes

| Mode | Public compatibility | Per-bar boundary |
| --- | --- | --- |
| Legacy callback | Returns `OrderCommand` objects from a materialized context | Python object path |
| Numeric callback | Receives `StrategyContextView`, writes `CommandWriter` rows | Primitive IDs/arrays where Rust is selected |
| Sparse numeric callback | Same numeric API plus `CallbackSchedule` | Only declared wake bars/events call Python |
| Static command tape | Existing order-command lifecycle route | One prepared execution call |

`StrategyContextRequirements` is a declaration, not a sizing or accounting
policy. It controls only what crosses into a callback: requested market fields,
account scalars, position view, new fills/events, active-order snapshot, and
the callback schedule. An undeclared legacy strategy resolves to the safe,
conservative compatibility context.

Numeric views have a generation guard. A view is valid only during its callback;
keeping it and reading it after the next callback raises a stale-context error.
Callback failures contain callback name, bar, timestamp, and strategy ID without
exposing mutable native internals.

## Ownership And Result Semantics

When `native_backend="rust"` is selected, Rust is the only mutable owner of
orders, scheduled state, positions, equity, fees, funding, margin, fills,
events, and requested accounting paths. Python owns the strategy object,
immutable metadata/interner, ephemeral callback adapter, and final public
`BacktestResultV2` adaptation. The Rust adapter has no Python shadow account,
position, pending-order, or lifecycle state.

Numeric commands remain struct-of-arrays data in the Rust full-contract session
for a `minimal` report. `standard`/`audit` materialize command objects only for
their requested public artifacts. Quantity rounding/drop behavior uses the same
canonical constraints as the legacy command path; metadata reports the same
`changed_count`, `dropped_count`, and dropped-order details.

Public results retain their historical accounting paths and diagnostics. The
metadata records `strategy_context_requirements`,
`reactive_retention_requirements`, `strategy_boundary`, and `observability` so
an audit can distinguish strategy projection cost from execution cost.

The public `NativeOrderEvent` convention is backend-neutral. For an OCO sibling
cancellation, `order_id` identifies the fill that initiated cancellation and
`target_order_id` identifies the canceled sibling. Rust may use the inverse
relationship internally for efficient mutation, but the adapter normalizes it
before building the public ledger and canonical trace.

## Audit Policies

`audit_mode="native_trace"` runs exactly one primary engine and builds its
report from that primary trace. `verify_against_oracle` runs an independent
Python static lifecycle oracle after the primary run and raises on a canonical
trace/accounting mismatch. `dual_run_sampled` makes that verifier deterministic
from the immutable plan fingerprint, sample rate, and seed. The oracle is never
used as a hidden replacement result.

`report_level="standard"` and `report_level="audit"` intentionally retain one
terminal active-order artifact, including for a numeric strategy that does not
require active orders during its callback. `minimal` omits it. Per-bar
active-order snapshots occur only when the declared strategy projection needs
them.

## Preparation, Cache, And Reset

Prepared strategy runners reuse immutable normalized market arrays and bounded,
content-addressed cache entries. Cache identity includes time, OHLC, volume,
funding, funding-event mask, symbols, and relevant constraint/contract input.
A mutation to volume or funding therefore cannot reuse a stale market context.
The cache is LRU bounded by entry count and bytes; a pinned entry cannot be
evicted until explicitly released. Mutable sessions are not shared across
workers.

`ResetScope.ACCOUNT_AND_ORDERS` is the supported replay reset. It clears mutable
execution state, increments generation, preserves immutable market/instrument
tables, and leaves already-returned result arrays owned by the result. The
Phase 52B evidence reruns a session thousands of times and asserts a bounded
RSS plateau plus exact fresh/replay accounting.

## Performance Interpretation

The phase records planning, market preparation, strategy preparation, command
compile, engine setup/run, result adaptation, report construction, and oracle
verification time separately. It also records Python callbacks, PyO3 calls,
primitive command rows, object materialization, projection bytes, and active
snapshot counts.

An arbitrary every-bar Python callback still requires one controlled
Python/Rust transition per bar. That is a correct hybrid workload, not a claim
of fully native execution. Static tapes and sparse schedules reduce that
boundary. Fully native strategy IR and batched/chunked execution remain P2
scope, where they can remove the callback-per-bar cost without changing the
P0/P1 lifecycle contract.

## Reproducible Evidence

Run the focused boundary suite:

```bash
MPLCONFIGDIR=/tmp PYTHONPATH=src:. poetry run pytest -q \
  tests/native_event/test_phase52b_strategy_boundary.py \
  tests/native_event/test_phase52b_ownership_cache_audit.py
```

Run the certification workload:

```bash
MPLCONFIGDIR=/tmp PYTHONPATH=src:. poetry run python tools/certify_phase52b.py \
  --output /tmp/phase52b.json
```

For an installed wheel, run from outside the repository and prepend the target
site directory to `PYTHONPATH`, then pass `--expected-site` to assert the
import source. The machine-readable result is archived as
[`phase52b_certification.json`](phase52b_certification.json).
