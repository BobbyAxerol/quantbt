# Phase 77.3 Reactive Closure Evidence

This is current-candidate development evidence for the explicitly certified Rust reactive
R1/R2/R3/W3 routes. It does not promote arbitrary Python callbacks, generic `walk_forward()`,
Mode 2, portfolio/package WFO, or `backend="auto"`.

## Named Workloads

- Scalar retention: `10,000` bars, `5` warm repeats.
- Reactive W3: `2,000` bars, `8` candidates, `5` warm repeats.
- R3B is a distinct fixed/adaptive batch schedule. Its throughput is never compared to sequential TPE as if it sampled the same search sequence.

### Prepared Reactive R1/R2/R3

| Runtime | Surface | Median | Bars/s | Python callbacks |
|---|---|---:|---:|---:|
| `numeric_every_bar_v1` | `prepared_public_minimal` | 37.001 ms | 270,261 | 10000 |
| `numeric_every_bar_v1` | `prepared_scalar_score` | 20.077 ms | 498,086 | 10000 |
| `numeric_sparse_wake_v1` | `prepared_public_minimal` | 27.413 ms | 364,792 | 313 |
| `numeric_sparse_wake_v1` | `prepared_scalar_score` | 13.588 ms | 735,954 | 313 |
| `numeric_block_intent_v1` | `prepared_public_minimal` | 33.503 ms | 298,479 | 1 |
| `numeric_block_intent_v1` | `prepared_scalar_score` | 20.949 ms | 477,346 | 1 |

### Reactive W3

| Schedule | Python work/callback | Median | Candidate-fold bar visits/s | Callbacks |
|---|---:|---:|---:|---:|
| `certified_sequential_v1` | 0 | 196.556 ms | 110,452 | 21710 |
| `throughput_batch_v1` | 0 | 226.748 ms | 105,404 | 36 |
| `certified_sequential_v1` | 96 | 453.217 ms | 47,902 | 21710 |
| `throughput_batch_v1` | 96 | 237.254 ms | 100,736 | 36 |

## Safety And Retention

- Wake observations use two symbol-sized mutable buffers per run and refresh in place; the typed `WakePlanV1` wire avoids a dict conversion on the optimized R2/R3 path. Legacy payload-only plans remain adapter-compatible.
- Cancellation and `RuntimeBudgetV1(max_wall_time_ms=...)` are enforced while Rust advances active work. Sparse/block gaps check at completed account-bar boundaries at most every 64 bars and again at a wake/end boundary. No partial score is adapted or admitted to selection.
- The deadline starts after fresh-account initialization for each score. `reset()` clears active deadline/cancellation state before an independent next score; result/account paths are never retained on scalar failure.
- Focused active-work proof: `tests/test_phase77_3_reactive_parity.py` covers native cancellation, deadline propagation through scalar WFO and R3B, and reset recovery. It is not a metadata-only test.

## Cross-Route Controls

- `public_wfo`: `True`
- `shared_portfolio`: `True`
- `bounded_package`: `True`
- `intrabar`: `True`

The controls rerun small public-WFO, shared-portfolio, bounded-package and intrabar requests from their own contract-specific harnesses. They are regression sentinels, not a combined speed score.

## Interpretation

Historical Phase 75/76 artifacts remain immutable scope records and use different source identities/repeat counts. This artifact intentionally does not publish a before/after percentage from those records. Compare only same-profile current-candidate runs with identical workload and retention definitions.
