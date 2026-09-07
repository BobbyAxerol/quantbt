# ADR-RP-003: Correctness Before Performance

**Status:** Accepted for the QuantBT Rust-Primary V1.1 program.

## Context

Two implementations can agree on final equity while sharing a timing,
funding, fee, rounding, or lifecycle defect. A faster kernel is therefore not
evidence of a correct financial simulation.

## Decision

Every promoted domain change follows this sequence:

```text
written domain specification
-> independent executable Python oracle
-> canonical backend-neutral trace
-> examples, invariants, differential/property/fuzz/mutation evidence
-> end-to-end performance and RSS evidence
-> explicit promotion, then optional auto promotion
```

Canonical trace and terminal fingerprint compare more than final equity. The
trace records event ordering, identifiers, timestamps, reason codes, quantity,
price, fee, cash, position, realized PnL, margin, and state transitions under
field-specific tolerance policy. The test oracle must not import production
Python, Rust, or Numba paths.

## Consequences

- Performance PRs cannot change timing/accounting semantics to win a benchmark.
- Score, compact, and audit profiles must share terminal financial fingerprint.
- Unsupported semantics fail before simulation instead of producing an
  unqualified result.
- Benchmarks report end-to-end phase timing, copy counters, and RSS rather than
  only a pure kernel number.

## Rejected Alternatives

- Old production Python as the only specification.
- One global floating tolerance for IDs, prices, quantities, cash, and metrics.
- Deleting the independent oracle after a Rust parity result.

## Rollback

An explicit legacy contract/backend remains available until the new route
passes its stable-soak A5 review. Any unexplained trace mismatch blocks auto
promotion and activates the documented fallback.
