# ADR 0002: Immutable Planning And Backend SPI

## Context

Endpoints previously mixed validation, execution routing, and result assembly.
That makes Python/Rust differential testing and prepared-market reuse fragile.

## Decision

Use immutable execution plans, prepared markets, and typed backend results as
internal boundaries. Keep public endpoints compatible.

## Alternatives

Give each backend its own endpoint interpretation or expose Rust types directly
from public APIs.

## Consequences

Backend routing is inspectable and execution state is not mutated by reporting.

## Rollback

Route through the Python reference backend while preserving the plan record.
