# P0 Accounting, Numeric, Trace, And Package Contracts

Phase 51B freezes the financial meaning that later Python and Rust ownership
work must preserve. The contracts in this document are audit surfaces, not a
new execution mode and not a change to the public endpoint defaults.

## Accounting Ledger

Audit native-event runs emit `accounting_ledger_v1`,
`accounting_symbol_ledger_v1`, `accounting_policy_v1`, and
`accounting_invariants_v1`. The ledger is reconstructed independently from
fills and market marks. It checks every bar rather than accepting equal final
equity as sufficient evidence.

For the current linear quote-settled model:

```text
equity = initial_capital
       + cumulative_realized_pnl
       + unrealized_pnl
       - cumulative_fees
       - cumulative_funding
       - cumulative_borrow
       - cumulative_liquidation_cost
```

It also reconciles signed fill quantity with position, average entry across
scale/reduce/reversal transitions, gross/net/long/short notional, initial and
maintenance margin, and available equity. Fees are one-way per fill. The
legacy zero-equity liquidation model is explicitly identified; the auditable
forced-close helper emits per-symbol realized loss, liquidation fee, canceled
orders, and residual position attribution without silently replacing the
legacy default.

## Instrument And Numeric Policy

`compile_instrument_table` produces immutable contiguous arrays for tick size,
quantity step, min/max quantity, min notional, contract size, settlement, fee,
and margin identifiers. `quantize_order_value` applies deterministic integer
tick/lot arithmetic with side- and order-type-aware rounding. Minimums are
checked after quantization. Python and Rust use the same vectors and exact
discrete outputs.

Inverse, quanto, and option instruments fail fast until their dedicated
valuation models are certified. They are never routed through the linear
formula as an approximation.

## Canonical Trace And Replay

Audit native-event runs emit `canonical_trace_v1` and a SHA-256 fingerprint.
The trace records the bar, UTC timestamp, phase, sequence, command outcome,
order lifecycle state, fill accounting, position transition, costs, and
account snapshot. Canonical little-endian numeric bytes and normalized NaNs
make the fingerprint deterministic.

The hash-only sink has the same fingerprint as the materialized trace.
`TraceReplayer` reconstructs terminal positions and equity from the trace
without invoking the matcher. `compare_canonical_traces` reports the first
divergent bar, phase, event, and field.

## Portfolio And Package Reference Semantics

P0 freezes reference behavior without changing the production portfolio or
arbitrage defaults. Portfolio allocation policies cover sequential legacy,
pro-rata available margin, all-or-none target, and reduce-first-then-increase.
Their reports reconcile requested targets, accepted positions, delta quantity,
costs, margin, and deterministic rejection reasons.

Package execution covers planned, preflight, reservation, commit, abort,
compensate, and residual-exposure states for atomic, best-effort, sequential,
and hedge-after-primary policies. These are Python reference contracts for
future engine ownership; Phase 51B does not claim Rust portfolio/package
execution.

## Capability And Wheel Gate

Native API `0.4` exposes a structured semantic descriptor containing the core
protocol range, contract-registry fingerprint, trace schema, command ABI,
supported order semantics, and account model. Explicit Rust selection fails
before preparation when the descriptor differs. `auto` remains Python unless
the resolver intentionally probes and accepts a compatible native extension.

Run the isolated-wheel gate after installing both wheels into a clean target:

```bash
PYTHONPATH=/tmp/quantbt-wheel/site \
python tools/certify_phase51b_wheel.py \
  --expected-site /tmp/quantbt-wheel/site
```

The gate proves imports come from the installed wheels, validates the semantic
handshake, executes one tape through Python and Rust, checks accounting
invariants, exact canonical trace parity, and replay correctness.

## Certification Boundary

Phase 51B certifies the current linear quote-settled native-event P0 contract,
its audit ledger, deterministic numeric policy, trace/replay surface, and
reference portfolio/package semantics. It does not claim venue-exact partial
fills, L2 queue simulation, inverse/quanto/options valuation, Rust portfolio
execution, or the P1 ownership refactor.

## V1.1 Successor Foundation

Phase 57 retains this V1 audit surface for compatibility and adds a separate,
backend-neutral successor contract: [V1.1 linear accounting](v1_1_linear_accounting.md),
[V1.1 execution clock](v1_1_execution_clock.md), and [Canonical Trace V2](v1_1_canonical_trace_v2.md).
The V2 model is additive until a later route-specific migration has independent
oracle and canonical-trace evidence. It does not silently reinterpret this V1
ledger or change any existing endpoint default.
