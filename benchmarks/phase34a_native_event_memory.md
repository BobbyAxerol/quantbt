# Phase 34A Native Event Artifact Memory Benchmark

| report_level | seconds | peak RSS MB | commands | fills | events | command rows | event rows | fills obj | orders obj |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| minimal | 1.225103 | 333.090 | 1575 | 1500 | 3075 | 0 | 0 | 0 | 0 |
| standard | 1.045849 | 336.641 | 1575 | 1500 | 3075 | 1575 | 0 | 1500 | 1500 |
| audit | 1.009143 | 292.090 | 1575 | 1500 | 3075 | 1575 | 3075 | 1500 | 1500 |

Notes:

- Each row runs in a fresh subprocess.
- Peak RSS includes Python import, pandas, and Numba/cache overhead; on small workloads it is not expected to be monotonic by artifact level.
- The artifact contract is verified by command/event row counts and materialized Python object counts; larger command-heavy runs are needed for stable RSS deltas.
