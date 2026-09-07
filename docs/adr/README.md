# Architecture Decision Records

These ADRs freeze the decisions that shape QuantBT's execution boundary. They
are concise on purpose: implementation detail belongs in code and contract
registries; an ADR records why the boundary exists, what was rejected, and how
to roll it back.

| ADR | Decision |
|---|---|
| [0001](0001-versioned-event-clock.md) | Version event-clock semantics |
| [0002](0002-backend-spi.md) | Use immutable planning and backend SPI |
| [0003](0003-rust-workspace.md) | Keep Rust as layered workspace crates |
| [0004](0004-generational-order-arena.md) | Use generation-safe native order handles |
| [0005](0005-strategy-ir.md) | Bound native strategy IR v1 |
| [0006](0006-batch-determinism.md) | Require deterministic batch results |
| [0007](0007-portfolio-target-contract.md) | Separate target preflight from full portfolio execution |
| [0008](0008-package-atomicity.md) | Model package policy explicitly |
| [0009](0009-native-wheel-compatibility.md) | Require exact core/native package pairing |
| [RP-001](ADR-RP-001-rust-primary-authority.md) | Define Rust-primary authority and A0-A5 promotion |
| [RP-002](ADR-RP-002-strategy-engine-boundary.md) | Keep research/strategy outside QuantBT simulation authority |
| [RP-003](ADR-RP-003-correctness-before-performance.md) | Require specification, oracle, trace, and parity before promotion |
| [RP-004](ADR-RP-004-runtime-classes.md) | Report reactive/native authority and boundary cost truthfully |
| [RP-005](ADR-RP-005-wfo-optimizer-schedules.md) | Version WFO causality and optimizer schedule semantics |

New cross-layer behavior requires an ADR update or a new ADR before code is
promoted. Existing results retain their original contract identifiers.
