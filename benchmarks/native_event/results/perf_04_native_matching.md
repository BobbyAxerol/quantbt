# PERF-04 Native Matching Evidence

This is a development-only prepared Rust lifecycle benchmark. It measures passive
limit place/amend/replace/cancel-all cycles over one symbol; it is not a public
endpoint, generic grid, L2/order-book, or WFO throughput claim.

| Workload | Live orders/cycle | Commands | Median ms | Commands/s | Active scans | Relationship scans |
|---|---:|---:|---:|---:|---:|---:|
| small_exact_scan | 1 | 1996 | 1.013 | 1,969,522 | 1,497 | 499 |
| high_churn_indexed | 64 | 96307 | 48.348 | 1,991,954 | 95,808 | 31,936 |

## Contract Evidence

- Score and audit terminal account values are equal before timing.
- Exact active-order priority remains sequence ordered. The index validator compares
  the active index with a full arena scan in debug/test paths.
- Parent/OCO/expiry/cancel-all snapshots use reusable scratch, so no candidate is
  dropped during same-phase continuation. The generic index scan remains the fallback.
- Alias cleanup is bounded by aliases for the terminal order and reports zero active
  aliases after every cancel-all cycle.
- `reset(result_buffers, max_capacity=0)` clears both matcher scratch capacities;
  it does not alter account/order semantics or prior detached results.

## RSS

- Process RSS tail spread: `0.000 MiB`.
- These process samples include Python, NumPy and extension mappings; they are not
  Rust-only allocation claims.
