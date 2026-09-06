# PERF-03 Reactive Boundary Contract

PERF-03 reduces avoidable work at the **Python strategy / Rust execution**
boundary. It does not turn an arbitrary Python callback into native code: Rust
still owns the market clock, order lifecycle, fill, fee, funding, margin, and
liquidation state; Python still owns the declared reactive decision and any
private state it changes.

## Callback Binding

The compatible default is dynamic lookup at each lifecycle boundary. It is the
right route for research strategies which intentionally replace a callback
method while running.

An immutable strategy may declare the narrower contract:

```python
quantbt_reactive_callback_binding_v1 = "run_stable"
```

This pins the available `initialize`, `on_bar_close`, `on_wake`, `next_block`,
and `finalize` bound methods for one native session only. It never shares a
strategy object, callback, account, order state, RNG, or writer across a reset,
candidate, fold, or WFO task. Do not use it if the strategy monkey-patches a
lifecycle method during that run.

`run_stable` is an access-plan optimization, not a different execution model.
Callback ordering, causal availability, effective command times, fills, fees,
funding, margin, liquidation, and public result semantics remain identical.

## Context And Command Rules

The numeric context is projected only after Rust has confirmed that a live
callback exists. Missing optional hooks do not allocate an unused snapshot.
Every-bar callbacks are always invoked: a callback with no orders can still
advance private state or a random-number generator.

Each callback receives one bounded primitive command staging region. On a
normal return, Rust validates the command envelope then admits/rejects each row
through its ordinary quantity, notional, timing, and margin rules. A rejected
business order therefore does not roll back another valid row.

If the callback raises, returns an invalid value, or emits a structurally
invalid timing envelope, all rows not yet admitted to Rust are discarded. The
reusable session is marked dirty/poisoned and must be explicitly reset before a
new independent run. QuantBT never retries a potentially mutated Python
strategy implicitly.

## Observability

Read `result.metadata["reactive_numeric_observability"]` for:

- `callback_binding_mode` and callback-plan/lookup time;
- dynamic lookup, context-projection, getter, and writer-call counts;
- completed command callbacks and discarded staged rows; and
- existing callback, engine, ingest, retention, and GIL-policy counters.

These are telemetry only. They cannot alter strategy decisions or accounting.

## Evidence And Reproduction

The small-corpus A/B/C/D parity lock is
[`tests/test_perf_03_reactive_boundary.py`](../../tests/test_perf_03_reactive_boundary.py):
Python oracle, existing Rust bridge, dynamic numeric co-runtime, pinned numeric
co-runtime, and captured-command static replay preserve financial/accounting
state. It also covers callback mutation compatibility, R2/R3 pinned access,
callback failure, invalid return/envelope, and ordinary per-command rejection.

Reproduce the public-facade development benchmark with:

```bash
PYTHONPATH=src .venv/bin/python \
  benchmarks/native_event/benchmark_perf03_reactive_boundary.py \
  --bars 2000 --repeats 9
```

The committed [JSON artifact](../../benchmarks/native_event/results/perf_03_reactive_boundary.json)
and [rendered table](../../benchmarks/native_event/results/perf_03_reactive_boundary.md)
cover a no-op control plus registered B-02 through B-06 workloads. They report
full facade time, public boundary counters, pair-order alternation, and process
RSS. They are machine-local development evidence, not a generic speed claim or
a promotion of all reactive routes.

For public API examples see the [endpoint contract](../endpoint.md#callback-binding-and-staged-command-boundary),
[Reactive WFO](../reactive_wfo.md), and the [Rust native-event contract](../native_event_rust_full_contract.md#perf-03-callback-boundary-contract).
