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

New cross-layer behavior requires an ADR update or a new ADR before code is
promoted. Existing results retain their original contract identifiers.
