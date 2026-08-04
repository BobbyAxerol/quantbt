# Phase 48C Event-Driven Facade Benchmark

Workload: **2,000 bars**, one symbol, fresh process per route.
The common table is the release baseline; the Grid table is a separate reactive workload.

## Common 2,000-Bar Baseline

| Route | Median s | P95 s | Bars/s | Peak RSS MB | Final Equity | Fills |
|---|---:|---:|---:|---:|---:|---:|
| `native_event_strategy` | 0.161195 | 0.197100 | 12,407 | 184.2 | 19,998.269072 | 109 |
| `event_driven_facade` | 0.154537 | 0.209075 | 12,942 | 183.4 | 19,998.269072 | 109 |

Accounting parity: **PASS**.
Facade runtime overhead versus direct constructor: **-4.13%**.
The facade is a resolver/delegator; it is not expected to speed up the accounting kernel.

## Reactive Grid 2,000-Bar Workload

| Route | Median s | P95 s | Bars/s | Peak RSS MB | Final Equity | Fills | Trades |
|---|---:|---:|---:|---:|---:|---:|---:|
| `grid_native_event_strategy` | 1.418658 | 1.499553 | 1,410 | 274.5 | 28,972.788456 | 839 | 839 |
| `grid_event_driven_facade` | 1.398576 | 1.435288 | 1,430 | 274.5 | 28,972.788456 | 839 | 839 |

Grid accounting parity: **PASS**.
Grid runtime includes external indicator preparation and the reactive callback; it is intentionally not merged into the common baseline.

## Interpretation

- The new facade changes endpoint declaration and profile resolution only.
- Equal fingerprints, equity, fees, funding, positions, margin, and fill counts are the domain gate.
- `backend=auto` remains governed by the package release policy; this benchmark explicitly uses Python.
