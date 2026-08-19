# ADR 0007: Portfolio Target Contract

## Context

Portfolio sizing combines signals, quantity constraints, stale data, and margin
rules. A final position alone cannot explain a rejection.

## Decision

Represent requested, accepted, and rejected targets separately. Native support
is preflight-only until full execution parity is certified.

## Alternatives

Directly mutate quantities or label preflight as complete portfolio execution.

## Consequences

Accounting derives from accepted deltas and audit reports retain reasons.

## Rollback

Use the native portfolio Python reference route with identical target inputs.
