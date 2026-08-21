# ADR 0003: Layered Rust Workspace

## Context

A single PyO3 crate would quickly mix domain semantics, engine state, portfolio
logic, and bindings into another monolith.

## Decision

Use shared domain, engine, strategy IR, batch, portfolio, package, and thin
PyO3 crates. Keep public visibility narrow.

## Alternatives

One extension crate or a premature crate per strategy.

## Consequences

Domain contracts can be tested without Python bindings and dependencies remain
directional.

## Rollback

Keep the Python oracle as the executable fallback; no public endpoint depends
on a particular Rust crate layout.
