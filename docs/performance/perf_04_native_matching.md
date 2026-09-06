# PERF-04 Native Matching And Specialization

PERF-04 removes measured allocation and lookup work from the certified Rust
native lifecycle path without changing an economic transition. It does not add
a new order engine, change matching priority, or broaden venue simulation.

## Lifecycle Matching

`FullSession` remains the sole mutable owner of `OrderArena<OrderState>` and
the account. Its active-order source is `LifecycleIndexes.active_by_sequence`,
which is the exact active set in stable monotonic sequence order. The matcher
copies that ordered set into session-owned scratch once per bar, then processes
the same priority it did before the optimization.

There is deliberately no price-index route or unmeasured threshold. Small
shapes use the same exact active-index scan; this avoids a second matcher whose
selection could change order precedence. Parent activation appends a child to
the existing same-phase continuation queue. OCO, expiry, and cancel-all take a
reusable lifecycle snapshot before mutating indexes, so an index mutation cannot
invalidate the loop currently consuming it.

`validate_complete(...)` is a test/debug oracle: it compares the active index
with a full arena scan and rejects a missing candidate or changed priority. It
is not executed as a second production matching pass.

## Layout, Alias, And Reset Ownership

The hot `OrderState` is numeric: handle-relevant lifecycle state, quantities,
prices, relations, flags, and sequence. Public string identity and rich
provenance stay outside that arena in command/output adaptation. This keeps one
authoritative mutable order state rather than maintaining hot/cold copies.

`ExternalOrderAliases` is a bidirectional live-order index. It preserves the
public replacement-chain behavior while releasing only aliases owned by a
terminal order instead of scanning every live alias. Both matching and
lifecycle snapshots are retained reusable buffers. A completed runner may call
`reset("result_buffers", max_capacity=0)` to clear and release that transient
capacity; detached score/compact/audit results and economic state are not
modified.

## Certified Shapes

The registry at
[`perf_04_specialization_registry_v1.json`](../../benchmarks/native_event/registries/perf_04_specialization_registry_v1.json)
records the exact routes and their contracts:

- direct linear target scoring, with no synthetic order lifecycle;
- static command-tape score, compact, and audit execution;
- reactive compact execution, where Python retains decision ownership;
- shared-account portfolio target rebalance; and
- bounded package audit.

They share existing accounting primitives. Market mapping, fixed contracts, and
output profile may be prepared once; equity sizing, mark-sensitive collateral,
fees, funding, tradability, liquidity, and admission remain at their normal
runtime phase.

## Evidence And Scope

Run the scoped development fixture with:

```bash
PYTHONPATH=src .venv/bin/python \
  benchmarks/native_event/benchmark_perf04_native_matching.py \
  --bars 2000 --high-orders 64 --repeats 9
```

The committed [JSON evidence](../../benchmarks/native_event/results/perf_04_native_matching.json)
and [rendered evidence](../../benchmarks/native_event/results/perf_04_native_matching.md)
use passive `place -> amend -> replace -> cancel_all` cycles. They first require
score/audit terminal parity, then report active/relationship scans, scratch
capacity release, alias cleanup, and process RSS. This is not a public endpoint,
WFO, generic grid, L2/order-book, or venue-native latency claim.

The differential corpus covers gap/next-open behavior, competing orders,
stop-limit continuation, expiry, replacement, cancel-all, and prepared replay.
The target, portfolio, and package corpora separately lock direct accounting,
shared-account policies, atomic rollback, actual-fill hedge quantity, funding,
margin, liquidation, and unsupported-domain containment.

The certified rollback remains the existing generic lifecycle matcher and its
compatible output schema. No static matcher is promoted for an unsupported
order-book, queue-priority, cross-margin, or venue-native contract.
