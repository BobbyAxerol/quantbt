# Options V1.2 Rust Authority Handoff

This document defines the work that must be complete before an option route can
be promoted from the V1.1 Python-primary, correctness-contained backend to a
Rust-primary production authority.

## Required Domain Scope

The Rust options program must own one typed run from market input to terminal
financial state:

- multi-currency premium, collateral, fee, settlement, and realized-PnL ledger;
- European expiry plus observed American exercise and assignment events;
- linear, inverse, and explicitly specified Quanto payoff/conversion contracts;
- cash, future-then-cash, and physical-delivery lifecycle state machines;
- option package admission, reservations, partial fills, and compensation;
- pre-fill initial margin, timeline maintenance, liquidation, and bankruptcy;
- underlying hedge orders and combined option/hedge account state;
- immutable score, compact, and audit output buffers.

Python must remain the public facade and independent oracle. It may adapt typed
Rust output on the cold path, but must not replay execution to reconstruct
cash, positions, fees, margin, settlement, or liquidation.

## Capability And Venue Requirements

Promotion is contract-specific. Each exercise/premium/settlement/margin/
execution tuple needs its own capability row and evidence. A generic `options`
flag is insufficient.

Venue-exact portfolio margin requires versioned venue fixtures or an external
validator corpus. The following must be explicit:

- collateral currencies and conversion timestamps;
- cross-product offsets and concentration add-ons;
- short-option floors and maintenance transitions;
- liquidation ordering and fee schedule;
- delivery instrument and assignment creation;
- settlement source, publication time, and correction policy.

## Differential Corpus

At minimum, Rust and the independent Python oracle must match for:

- European linear and inverse ITM/ATM/OTM settlement;
- long/short open, add, reduce, close, and reversal accounting;
- maker/taker/capped/per-contract fees in their actual currencies;
- package max-debit/min-credit and post-cost margin rejection;
- partial and all-or-none package execution;
- maintenance breach and adverse-BBO liquidation;
- hedge rebalance timing and combined account equity;
- duplicate/corrected settlement events;
- American exercise and assignment fixtures when that capability is added;
- Quanto and physical delivery only after their ledgers exist.

Every accepted fill, ledger event, position, cash balance, fee, margin state,
settlement cashflow, liquidation state, and terminal fingerprint must match.

## Promotion Gate

An option subtype may become Rust-primary only after:

1. typed contract and result ABI are versioned;
2. source and clean installed-wheel parity pass;
3. canonical traces match the Python oracle;
4. repeated service and calibration runs show bounded RSS;
5. end-to-end performance is no worse than the intended Python workload;
6. shadow-oracle runs produce no unexplained mismatch;
7. rollback package versions and kill-switch behavior are documented;
8. one stable release cycle completes before any production duplicate removal.

Until those gates pass, V1.1 `QuantBTEndpoint.options(...)` remains the
authoritative public route and reports `backend="native_option"`, with no
Rust-primary claim.
