# ADR 0006: Deterministic Batch Execution

## Context

Optimization requires repeated scenarios on one market tape. Parallelism must
not alter accounting or selected parameters.

## Decision

Share immutable prepared market data, give each scenario independent state, and
require exact worker-count parity before exposing a batch route.

## Alternatives

Mutable shared account state or speed-only benchmarks without comparison.

## Consequences

Batch results can be rerun individually and audited deterministically.

## Rollback

Use single-scenario execution with the same contract and parameters.
