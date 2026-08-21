# ADR 0004: Generation-Safe Order Arena

## Context

Reusing native order slots can create stale-handle bugs after cancellation or
replacement.

## Decision

Use generation-aware identifiers for native order storage and reject stale
references before mutation.

## Alternatives

Raw vector index handles or perpetual allocation without reuse.

## Consequences

Memory can be reused while lifecycle conformance catches invalid references.

## Rollback

Fall back to the Python reference lifecycle if a native invariant fails; never
silently reinterpret a stale handle.
