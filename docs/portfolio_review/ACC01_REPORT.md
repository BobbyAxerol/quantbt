# ACC-01 Current-Capability Closure

Local corrective scope approved on 2026-10-22 (Asia/Saigon).
Status: **COMPLETE_LOCAL_CURRENT_CAPABILITY_CLOSURE**. All eighteen findings and
the two same-responsibility sibling admission gaps are closed within the
declared capability. No new simulation model or package release is certified.

## Scope And Source

The [approved contract](CURRENT_CAPABILITY_REPAIR_GUIDE.md) covers F01-F18 from
the [follow-up](../PORTFOLIO_ACCOUNT_FOLLOWUP_2026-10-21.md) and
[expanded review](EXPANDED_REVIEW_2026-10-22.md). Runtime baseline is the
previous repair `9c2bfd9`; admission HEAD was `8f7df9d`. Corrected runtime is
`70fe9f7c9b14469e6ea935e75f180f26ca1c175e` (including the final sibling-admission
addendum). Source reconciliation uses the
[final exact amendment](evidence/acc01-final-source-amendment.json), while retaining
the [initial amendment](evidence/acc01-source-amendment.json), not a replacement of
historical financial or scientific evidence.

No objective, sampler, Ridge model, selector, alpha or scientific gate changed.
No long optimizer/economic study was repeated. Incorrect earlier execution or
report values are intentionally corrected rather than forced into old parity.

## Finding Closure Map

All expectations below are independent arithmetic/rejection controls asserted
by the linked tests. They are software/accounting evidence, not strategy returns.

| Finding | Corrected result and scope | Regression owner |
|---|---|---|
| F01 | Zero/nonfinite contract size or leverage rejects on order, command and callback boundaries; valid multiplier1 entry costs1 and locks100 IM. | [event/vectorized tests](../../tests/test_acc01_event_vectorized.py) T01 |
| F02 | Liquidating package equity `[100,98,0,0]`: fee2, funding0, liquidation loss98, leg net-100. No invented exit cost/funding or omitted liquidation row. | [event/vectorized tests](../../tests/test_acc01_event_vectorized.py) T02; Rust target unit test |
| F03 | Matching opening wallet1000/capital1000 returns0%; conflicting wallet1000/capital20000 rejects before execution. Converted signed wallets use explicit FX and declared tolerance. | [option reporting tests](../../tests/options/test_acc01_reporting.py) F03 |
| F04 | Fee0.0000021BTC at100000USD/BTC becomes0.21USD at the effective event; original currency and conversion witness remain. | [option reporting tests](../../tests/options/test_acc01_reporting.py) F04 |
| F05 | Fresh100-notional order is rejected at minimum200 and accepted at100; effective minimum is the maximum of generic/instrument/run lower bounds. Legal reduce-only closes remain exempt and cannot reverse. | [event/vectorized tests](../../tests/test_acc01_event_vectorized.py) T05 |
| F06 | Unsupported option generic account/execution nondefaults reject. Option-specific snapshot, margin-buffer and execution settings keep their own contract. | [option configuration tests](../../tests/options/test_acc01_configuration.py) F06 |
| F07 | Nonfinite margin scenarios/config/external requirements reject before mutating the ledger; valid standard/scenario approximation stays unchanged. | [option configuration tests](../../tests/options/test_acc01_configuration.py) F07 |
| F08 | Proportional slippage at/above10000bps rejects; valid100bps short costs0.99 and ends998.01 from1000. | [event/vectorized tests](../../tests/test_acc01_event_vectorized.py) T08 |
| F09 | Result ns/us/ms/s representations preserve physical UTC instants and172800-second horizon; undeclared naive timezone and invalid clocks reject. | [clock/funding tests](../../tests/test_acc01_clocks_funding.py) F09 |
| F10 | Leverages1/10 and100-notional per leg require IM110; scalar buying power is unavailable, with allocation-dependent reason and per-symbol leverage. | [event/vectorized tests](../../tests/test_acc01_event_vectorized.py) T10 |
| F11 | Changed dtype/shape/strides cannot reuse a stale immutable cache identity; deepcopy/pickle retain read-only bytes and header validation. | [snapshot tests](../../tests/metrics/test_acc01_snapshot_headers.py) F11 |
| F12 | Extreme finite ledger inputs emit explicit invalid/null overflow metrics and safe provenance, while valid counts/representable averages survive. | [overflow tests](../../tests/metrics/test_acc01_ledger_overflow.py) F12 |
| F13 | Inverse long entry0.02/payoff0.20BTC realizes0.18BTC; short-0.18, OTM long-0.02. Cash remains1.18/0.82/0.98; mixed-currency components are never arithmetically summed. | [option lifecycle tests](../../tests/options/test_acc01_lifecycle.py) F13 |
| F14 | Nonfinite cash/FX/fees/settlement and invalid external requirements reject before financial mutation; valid debit cash and signed funding remain permitted. | [option configuration](../../tests/options/test_acc01_configuration.py) and [lifecycle tests](../../tests/options/test_acc01_lifecycle.py) F14 |
| F15 | Quote00:00 used at decision00:30 retains source time00:00 but fill/ledger/common fee occur00:30. No fake pre-event or post-event nanosecond rows; hedge inputs cannot backfill future prices. | [option reporting](../../tests/options/test_acc01_reporting.py) and [lifecycle tests](../../tests/options/test_acc01_lifecycle.py) F15 |
| F16 | Intrabar clocks normalize before event alignment, signatures and preparation; ns/us describe the same2024/7200-second tape. Obsolete market certificates fail reuse. | [clock/funding tests](../../tests/test_acc01_clocks_funding.py) F16 |
| F17 | Valid long1 at100 with rate0.01 pays1, equity999; negative finite rate credits correctly. NaN/Inf fails before a finite certificate. | [clock/funding tests](../../tests/test_acc01_clocks_funding.py) F17 |
| F18 | `[100,0,0]` keeps return-100%, DD100%, final equity0 and independent ledger/execution groups; affected period statistics become undefined with a reason. | [bankruptcy tests](../../tests/metrics/test_acc01_bankruptcy_reporting.py) F18 |

Two further same-responsibility admission gaps found in documentation review
were fixed before closure, not deferred: event generic clock/partial-fill/
same-bar/margin-rejection nondefaults now reject rather than doing nothing;
option generic multiplier/quantity/funding/clock controls reject when unsupported,
and a complete option config cannot silently discard facade financial overrides.
[Targeted controls](../../tests/options/test_acc01_endpoint_admission.py) retain
valid named V2/V3 event clocks and the option instrument/config authorities.

## Architectural Changes

Boundary validation runs before execution and preserves domain-specific options
semantics. Clock normalization is shared preparation, not a per-bar callback.
Snapshot validation checks a constant number of array headers, not full data
hashes on every cache hit.

Package attribution uses actual executed fee/slippage/funding/liquidation
buffers from the original financial pass. Rust's typed audit output supplies
four numeric values per bar/symbol only when requested. Score/compact retain
no such buffer. Package reports consume the private buffer and check every
bar against account equity, then release it; there is no execution replay or
unexplained last-row residual adjustment. Liquidation debit is allocated using
the existing declared close-exposure convention, not venue-exact settlement.

## Compatibility And Limits

The [configuration/migration matrix](ACC01_CONFIGURATION_AND_MIGRATION.md)
documents effective settings and intentional new errors. Default scientific
metrics keep their existing populations; closed trade/action statistics still
require authoritative complete ledgers. Undefined/unavailable is not zero.

Linear account scope remains gross-cross/netting with the declared conservative
OHLC/zero-equity liquidation convention. Isolated collateral, dual hedge
inventory, venue tiers/mark-price/partial liquidation and order-book simulation
are not added. Options keep their existing separate wallet, snapshot and margin
approximation. No ownership/backend promotion follows from this repair.

## Verification And Handoff

Incremental qualification contains **2,609 distinct latest passing Python test
IDs**, not a sum of overlapping runs, and **26 Rust execution unit passes**.
Six optional Nautilus integrations are skipped because the dependency is not
installed; these are not PASS or external validation. All earlier failed
receipts remain retained. The [terminal qualification](evidence/acc01-qualification.json)
records distinct test IDs, receipt hashes, source/native identities and scope.
Final source checks cover464files and435unchanged
registered source/evidence inputs;34source files have explicit reviewed
amendments, with independent negative-tamper tests.

Focused coverage includes options direct/prepared/hedge/settlement, account and
ledger/JSON/cache, clocks/funding, legacy/native portfolio, Numba/Rust targets,
packages, event orders/commands/callbacks, reactive/W3 and intrabar/session.
Mature E06/E07 and generic V3 regression verifies measurement, independent
accounting, applied parameters, off/shadow RNG and future-mutation isolation.
History-dependent output tests now build current-contract synthetic histories,
not silently reuse old frozen ones. The old source-invariance AST tests admit
only exact reviewed repair blobs; they still reject arbitrary drift. The W3
subprocess preserves the explicitly selected native extraction path.

The exact local native wheel SHA256 is
`d41555ce914b4d46e611913bd4b9a1a5daeae7acb25b69532260a24dd8f5805f`;
loaded extension SHA256 is
`52e1c92ac98faff5da1728f46b1d8d8c74fb7513f0285c89c13d0e4380474461`.
The final Python-only sibling-admission addendum does not change those Rust
bytes. [Performance disclosure](ACC01_PERFORMANCE.md) retains both adverse
initial observations and paired investigations. There is no universal speedup
or regression-free claim.

[Terminal cleanup](../maintenance/ACC01_CLEANUP.md) reclaimed an observed
30.35MiB from only the exact owned scratch root;106retained hashes and464source
files were rechecked. Failed receipts, old/new wheels, owner work, environments,
shared caches and historical scientific evidence remain.

The retained wheel is a local CPython3.12 exact-binding proof, not a core
wheel/sdist clean-install or remote/public certification. Primary environment
native0.4.2 and published artifacts remain unchanged. M5-12 remains separate;
there is no version bump, push, CI, merge, tag or publication in ACC-01.
