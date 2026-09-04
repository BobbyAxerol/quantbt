# ADR-RP-001: Rust-Primary Authority

**Status:** Accepted for the QuantBT Rust-Primary V1.1 program.

## Context

QuantBT currently contains Python/Numba reference routes, bounded Rust routes,
and Python-facing adapters. A Rust module existing in the workspace does not
by itself establish who owns simulation state or whether a route is safe for
automatic backend selection.

## Decision

For a promoted linear simulation capability, Rust is the authority for mutable
simulation state, execution control flow, market/instrument data prepared for
the run, orders/fills, account state, fees, funding, margin, liquidation,
standard metrics, and native result buffers. Python owns public ergonomics,
strategy/research logic, optimizer control, lazy result/report adaptation, and
the independent test oracle.

Rust-primary promotion uses the A0-A5 maturity ladder:

```text
A0 module/substrate exists
A1 differential parity
A2 specification/oracle/trace/invariant certification
A3 explicit Rust capability
A4 auto eligible after installed-wheel, RSS, and end-to-end gates
A5 stable soak/shadow evidence; old production duplicate may retire
```

`backend="rust"` must fail closed outside the exact certified capability.
`backend="auto"` uses workload-aware routing and records requested/resolved
backend, authority, runtime class, and fallback reason.

## Consequences

- A hybrid Python callback route is not described as fully native merely
  because its outer public call enters Rust once.
- Python must not replay Rust execution to construct normal result/account
  state.
- Capability promotion is granular by endpoint, input mode, timing contract,
  account contract, execution model, and result profile.

## Rejected Alternatives

- Treating wheel availability as blanket Rust promotion.
- Replacing every endpoint with one universal event loop.
- Deleting Python/Numba production paths when a Rust implementation first
  reaches final-equity parity.

## Rollback

Keep the previous explicit backend route and package version until the A5 gate.
`backend="python"`, declared legacy contracts, and documented environment
rollback controls remain valid compatibility boundaries.
