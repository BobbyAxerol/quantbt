# ADR-RP-002: Strategy And Engine Boundary

**Status:** Accepted for the QuantBT Rust-Primary V1.1 program.

## Context

QuantBT is a simulation SDK, not an alpha-feature platform. Mixing feature
graphs, indicator state, parameter logic, and execution/accounting inside one
runtime obscures causality and makes an independent execution oracle harder to
maintain.

## Decision

Strategy/research code owns features, indicators, forecasts, signals, targets,
hedge ratios, risk-model estimates, alpha state, and package intent. QuantBT
owns typed-intent validation, causal timing, market/calendar mapping,
instrument constraints, order acceptance/lifecycle/matching, fees, funding,
accounting, margin, liquidation, portfolio admission, package execution,
metrics, and result provenance.

The boundary uses typed intents and prepared handles. QuantBT does not infer
whether an arbitrary `Series` is an already-effective position. Every adapter
must declare intent kind, observation phase, effective phase, and shift
semantics.

Reactive Python strategies remain first-class. Rust may own the outer timeline
and persistent numeric buffers, but QuantBT does not translate arbitrary
Python strategy logic into Rust automatically.

## Consequences

- No `quantbt-features` package is introduced in V1.1.
- WFO can optimize repeated execution without taking ownership of strategy
  feature computation.
- Portfolio risk-parity, covariance, beta estimation, and alpha combination
  remain planner/strategy responsibilities; the engine executes accepted
  targets on the declared shared account contract.

## Rejected Alternatives

- Moving user alpha code or indicator implementations into the native core.
- Treating generated signals as sufficient evidence of causal execution timing.
- Requiring reactive/Grid/DCA strategies to be rewritten in Rust.

## Rollback

The existing Python-facing endpoints remain stable. A typed adapter is added
beside a legacy adapter until its explicit contract and migration path are
certified.
