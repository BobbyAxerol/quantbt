# ADR 0008: Explicit Package Atomicity

## Context

Basis, basket, and hedge workflows use multiple legs with materially different
acceptance behavior.

## Decision

Declare package policy (`all_or_none`, `best_effort`, `sequential`, or
`hedge_after_primary`) in the plan and preserve outcomes in the audit trace.

## Alternatives

Implicit sibling order or an unsupported claim of exchange-native atomicity.

## Consequences

Users can distinguish a simulated policy from venue matching semantics.

## Rollback

Run leg-level Python reference execution with the same declared policy.
