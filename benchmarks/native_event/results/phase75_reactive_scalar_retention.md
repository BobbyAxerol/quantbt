# Phase 75 Reactive Scalar Retention

## Measurement Contract

- **Workload:** one prepared 10,000-bar, one-symbol Rust reactive session.
- **Compared surfaces:** public `minimal` result versus explicit prepared
  `scalar_score_contract()` for the same R1/R2/R3 strategy and account.
- **Timing:** median of three warmed repeats; includes Python callbacks and the
  selected result adaptation for each surface.
- **Parity gate:** exact final equity before timing; focused tests also compare
  every published metric, final positions, fees, funding, liquidation and both
  GIL policies.
- **Retention gate:** score retains no equity/account path, command rows,
  callback trace, or terminal active-order artifact.
- **RSS:** `VmRSS` deltas are same-process warm incremental allocations. They
  are not cold peak-RSS or cross-process memory claims.

## Recorded Result

| Runtime | Public minimal | Scalar score | Score throughput | Speedup | Score retention |
|---|---:|---:|---:|---:|---|
| R1 every bar | 38.001 ms | 18.222 ms | 548,774 bars/s | 2.09x | no paths/trace/commands/orders |
| R2 sparse wake | 30.294 ms | 15.109 ms | 661,848 bars/s | 2.00x | no paths/trace/commands/orders |
| R3 block intent | 38.288 ms | 19.598 ms | 510,268 bars/s | 1.95x | no paths/trace/commands/orders |

The corresponding public-minimal throughputs were `263,148`, `330,099`, and
`261,177 bars/s`. Both surfaces produced identical final equities: `19,989.45`
for R1/R3 and `19,998.53` for R2 on this fixture. The JSON artifact carries
per-row callbacks, p95 timing, and RSS fields.

## Scope

This is an explicit prepared optimization surface. It does not make arbitrary
Python callbacks Rust-native, does not construct plots or audit reports from a
score result, and does not alter `backend="auto"`. Public report consumers must
rerun their chosen candidate through `minimal`, `standard`, or `audit`.
