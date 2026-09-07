# ADR-RP-005: WFO Optimizer Schedules And Causal Provenance

**Status:** Accepted for the QuantBT Rust-Primary V1.1 program.

## Context

Walk-forward optimization combines strategy generation, candidate search,
fold timing, account boundaries, and repeated simulation. A schedule that
changes optimizer ask/tell behavior or uses later-fold observations can change
the mathematical experiment even when endpoint syntax stays unchanged.

## Decision

WFO metadata resolves every legacy shorthand into an explicit schedule and
causality claim:

```text
RetrospectiveGlobal
TrustedStrategyGlobal
EngineEnforcedPerFold
EngineEnforcedNested
```

Each fold records train/validation/test/warmup/purge/embargo ranges, causal
cutoff, strategy lifecycle fingerprint, intent timing contract, fold account
policy, candidate/proxy/native/audit scores, selected parameter reason, and
rejection/pruning reason.

Native WFO supports two distinct optimizer contracts:

- `certified_sequential_v1`: ask one, evaluate one, tell one; it must preserve
  seeded candidate and selection sequence where the legacy contract requires it.
- `throughput_batch_v1`: ask/evaluate/tell batches; deterministic by seed and
  batch size, but it must not claim sequential-TPE candidate parity.

Proxy scoring is screening only and must pass rank correlation, Top-K overlap,
winner-regret, and false-positive gates against the declared native scorer.

## Consequences

- Prepared market/intent reuse may improve runtime but cannot alter cutoff,
  timing, fold account state, or optimizer semantics.
- Mutable strategy instances are spawned/reset/fingerprinted per declared
  lifecycle contract; unsafe reuse across folds/workers is forbidden.
- Future data, altered test labels, calendar changes, or fold reordering are
  covered by causal mutation tests before native WFO promotion.

## Rejected Alternatives

- Treating batched adaptive optimization as sequential parity.
- Reusing a mutable strategy instance without reset/cutoff-safe cache key.
- Calling a proxy return formula a native execution score without ranking proof.

## Rollback

Existing schedule identifiers remain available as explicit compatibility
contracts. New native schedules are selected explicitly until capability,
causality, parity, and performance gates permit auto routing.
