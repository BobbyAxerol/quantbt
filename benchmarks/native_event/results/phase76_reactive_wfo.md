# Phase 76 Reactive WFO Evidence

## Contract

- Public `prepare_reactive_walk_forward(...)` only; one symbol, Rust native event, Mode 1 global, reset-flat accounts.
- Each row is a warmed median over the declared repeats. Candidate-fold bar visits count scalar selection windows, not generic WFO bars.
- Sequential Optuna and R3B batch schedules are different sampling contracts. This table intentionally reports no speedup ratio between them.
- Repeated fixed-seed result fingerprints must match before timing. Focused tests carry exact scalar/batch selector and cold-audit parity.
- RSS/PSS values in JSON are process snapshots. The clean worker probe reports COW worker PSS separately from parent RSS.

## Recorded Result

| Strategy work | Schedule | Public W3 median | Candidate-fold visits/s | Callbacks | Score calls |
|---|---|---:|---:|---:|---:|
| lightweight | `certified_sequential_v1` | 224.935 ms | 96,517 | 21,710 | 66 |
| lightweight | `throughput_batch_v1` | 233.752 ms | 102,245 | 36 | 72 |
| Python-heavy | `certified_sequential_v1` | 464.960 ms | 46,692 | 21,710 | 66 |
| Python-heavy | `throughput_batch_v1` | 252.496 ms | 94,655 | 36 | 72 |

## Clean COW Worker Probe

- Transport: `fork_copy_on_write_v1`.
- Market IPC per task: `0` bytes.
- Completed scalar tasks: `66`.
- Worker memory: `{'private_bytes': 8724480, 'pss_bytes': 53408768, 'rss_bytes': 105058304, 'shared_bytes': 96333824}`.

## Scope

This is explicit W3 evidence. It does not promote arbitrary callback WFO, generic `walk_forward()`, portfolio/package WFO, or `backend="auto"`. The R3B batch route is measured as its own deterministic throughput contract, not as a sequential-TPE replacement.
