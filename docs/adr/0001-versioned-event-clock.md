# ADR 0001: Versioned Event Clock

## Context

“Next bar” is ambiguous unless it names a price phase. Historical behavior used
next-close while causal strategies often require next-open.

## Decision

Expose versioned contracts `event_lifecycle_v2_next_bar_close` and
`event_lifecycle_v3_next_open`; store the selected contract in execution
metadata and generate its identifiers from the lifecycle registry.

## Alternatives

One mutable default contract, or a user flag without a versioned result record.

## Consequences

Parity tests compare the same contract only. New timing behavior cannot silently
change old research results.

## Rollback

Use the prior explicit contract. Do not retarget its alias to new semantics.
