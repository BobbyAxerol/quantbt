# ADR-RP-004: Runtime Classes And Truthful Native Claims

**Status:** Accepted for the QuantBT Rust-Primary V1.1 program.

## Context

The number of public Python-to-Rust entries does not describe reactive cost.
A run may enter Rust once but still invoke Python on every bar and allocate
context/command objects repeatedly.

## Decision

Every event/WFO result records one declared runtime class:

```text
WholeRunNative
RustPrimaryPythonCallback
SparsePythonCallback
BlockIntentHybrid
PythonCompatibility
ExternalValidator
```

Observability keeps separate counters for native entries, Python callback
calls, GIL acquisitions, bars processed without callbacks, context projection
time/bytes, command ingestion time/bytes, native execution, native metrics,
and Python materialization.

For reactive V1.1 routes:

- R0 is the legacy object callback comparator.
- R1 uses persistent numeric context and command buffers but may still wake
  every declared bar.
- R2 sparse wake, R3 block intent, and R3B candidate batching require an
  every-bar shadow certification before promotion.

## Consequences

- A Python callback strategy remains Python-authoritative for decisions even
  when Rust owns execution/accounting.
- `auto` may select Python when the declared hybrid Rust route is slower
  end-to-end or lacks certified context/wake capability.
- Benchmark claims distinguish native entry count, callback count, and GIL
  behavior rather than collapsing them into a single "native" metric.

## Rejected Alternatives

- Calling a hybrid route fully native solely from an O(1) public entry count.
- Quietly skipping callbacks to improve performance.
- Building a Python dict/DataFrame command/context projection in the hot loop.

## Rollback

R0 and explicit Python remain supported comparators until each R1/R2/R3
capability reaches its own promotion and stable-soak gate.
