# ADR 0009: Exact Native Wheel Compatibility

## Context

Core package version, native package version, protocol, command ABI, result
ABI, trace schema, and IR evolve independently.

## Decision

Generate an exact compatibility matrix from the product registry. Verify the
pair before native execution and keep `auto` Python-first until promotion.

## Alternatives

Broad version ranges, import-success-only checks, or implicit auto promotion.

## Consequences

Mismatches fail before market preparation; staged wheels can be tested in clean
environments without source-tree leakage.

## Rollback

Use core-only Python execution. A native mismatch never silently reruns an
explicit Rust request through Python.
