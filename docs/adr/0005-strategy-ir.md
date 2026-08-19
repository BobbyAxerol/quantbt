# ADR 0005: Bounded Native Strategy IR

## Context

Calling arbitrary Python strategy code for every bar limits batching and makes
native performance claims misleading.

## Decision

Provide a bounded IR v1 for documented templates only. Keep callbacks and
Python strategy logic supported as separate routes.

## Alternatives

Compile arbitrary Python or claim native speed for callback-heavy strategies.

## Consequences

IR validation is explicit, testable, and suitable for batch execution.

## Rollback

Run the same strategy through the Python callback/reference command path.
