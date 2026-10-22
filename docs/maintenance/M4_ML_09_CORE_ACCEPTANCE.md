# M4-ML-09 Narrow Reduce-Only Acceptance Qualification

## Scope

The owner separately approved this correctness fix after the original private
admission stopped. A solvent account could not close a losing short because
the fee was tested against negative free margin before collateral release.
Parity between the original implementations did not establish domain
correctness: both rejected the same valid reduction.

Only flagged, purely reducing, non-reversing lifecycle fills now test fees
against equity adjusted to the actual fill price. Entries, increases,
unflagged orders and reversals retain their existing gate. Quantity clipping,
liquidation, fees, clocks and maintenance rules are unchanged. No alpha,
sampler, Ridge, metric or scientific threshold changes accompany this fix.

## Independent Expected Value

With20,000 capital, leverage1, fee0.0004, sell190 at100, then buy190
reduce-only at110: equity before close is18,092.40, initial margin20,900,
maintenance margin104.50. A permitted close costs8.36 and leaves a flat
position with equity18,084.04. Python reactive, Numba command replay and
Rust match this hand-accounted result. The unchanged exposure-increase and
reversal rejection cases pass too.

## Local Evidence

- 64 Rust engine unit tests pass, including the new collateral-release test.
- 18 Python/Numba checks pass before the native build.
- 83 focused checks pass against the exact new native artifact: accounting,
  lifecycle, margin, Rust R1, private multi-child execution and report/calendar
  controls. The83 include the18 checks; they are not101 distinct tests.
- The previously blocked real private account completes with190 fills and
  a flat terminal position. Native/static-oracle differences are0 for equity,
  positions, fees and funding; maximum margin difference is1.4211e-14,
  within the existing1e-8 path tolerance. An independent fixed-fill ledger
  also reconciles. No tolerance was increased.
- Fill identities, times, quantities, prices and fees match exactly after
  viewing static-oracle fills in execution order. Its legacy result lists
  fills by submission order; both original outputs remain unchanged. This
  view normalization must not be described as identical raw list ordering.
- The unchanged legacy `OrderIntent` kernel has an identical AST. Two real
  early/late controls plus the saved first-origin native winner's IS/forward
  observations retain their complete original observation hashes. This permits
  explicit reuse of that completed origin, not incomplete optimizer recovery.
- Frozen Ridge V1 still verifies42 source files and5 receipts.

The exact local CPython3.12 wheel SHA256 is
`74c64f3d72b530d527ed7b4ff7df36ccfdb51e93952b76ca275228f416919d05`;
the loaded extension SHA256 is
`9a254821755099eb3ee0213bb47632982d00d3b4fc40b7258776bbb62ff4ad39`.
The existing environment/native binary was not replaced. This is a focused
source/native-artifact proof, not remote, clean installed-core, public-index
or all-platform release qualification.

## Custody And Continuation

Original failed receipts remain under the ignored ML09 `attempt-01` lane.
The corrected native artifact, logs, failed verification attempts and passing
qualification are in the separate ignored `attempt-02/core` lane. The old
incomplete second-alpha observations do not cross the corrected acceptance
contract. Its next optimizer starts fresh with the same registered seed and
budget, not a forced replay of stale adaptive observations.

The qualified build does not complete the57-origin research phase. It admits
the bounded corrected tranche; mature model/chronology, sampler screens and
full economic readback remain separate. Cleanup/resource custody must precede
the approved one-financial-worker background queue. No push, CI, release,
publication or later phase is activated.
