# Phase 34A Native Event Artifact Memory Benchmark

| report_level | seconds | peak RSS MB | commands | fills | events | command rows | event rows | fills obj | orders obj |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| minimal | 0.334564 | 339.957 | 3100 | 3000 | 6100 | 0 | 0 | 0 | 0 |
| standard | 0.501138 | 344.855 | 3100 | 3000 | 6100 | 3100 | 0 | 3000 | 3000 |
| audit | 0.638208 | 348.371 | 3100 | 3000 | 6100 | 3100 | 6100 | 3000 | 3000 |

Notes:

- Each row runs in a fresh subprocess.
- Peak RSS includes Python import, pandas, and Numba/cache overhead; on small workloads it is not expected to be monotonic by artifact level.
- The artifact contract is verified by command/event row counts and materialized Python object counts; larger command-heavy runs are needed for stable RSS deltas.
