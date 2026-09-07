# Phase 63 Sparse Wake, Block Intent, And Candidate-Batch Evidence

R1/R2/R3 use the same deterministic transition schedule and pass exact accounting/canonical-trace parity before timing. R3B is a prepared low-level shared-market primitive, reported separately rather than being presented as a public WFO route.

## Public Routes

| Route | Bars | Median | Throughput | Decision callbacks | Wake ratio | Context / command copies | RSS delta |
|---|---:|---:|---:|---:|---:|---:|---:|
| r1_every_bar | 10,000 | 0.070017s | 142,823 bars/s | 10,000 | 1.0000 | 125,088 / 50,080 B | 2.80 MiB |
| r2_sparse | 10,000 | 0.067087s | 149,060 bars/s | 313 | 0.0313 | 2,520 / 50,080 B | 5.37 MiB |
| r3_block | 10,000 | 0.058470s | 171,027 bars/s | 1 | 0.0001 | 24 / 50,080 B | 0.00 MiB |

## Prepared Candidate Batch R3B

| Candidates | Candidate bars | Median | Throughput | Batch callbacks | Candidate callbacks | Wake ratio | RSS delta |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 16 | 160,000 | 0.134109s | 1,193,059 candidate-bars/s | 313 | 5,008 | 0.0313 | 14.18 MiB |

All routes remain explicit-only. Timing is workload- and machine-specific; it cannot change `backend="auto"` or certify a strategy that has not passed an every-bar shadow comparison.
