# Phase 15B Synthetic Depth Evidence

Status: **pass**

- L2 replay provider available: `False`
- Claim scope: Level-2 synthetic stress only; not venue L2 replay.

| case | depth model | status | filled qty | fill price | levels | accepted | rejected |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: |
| `synthetic_market_vwap` | `synthetic_book` | `filled` | 2.00000000 | 100.10000000 | 2 | 1 | 0 |
| `synthetic_partial_queue` | `synthetic_book` | `partial` | 1.50000000 | 100.02333333 | 2 | 1 | 0 |
| `ohlcv_all_or_none_baseline` | `ohlcv_volume_cap` | `filled` | 1.00000000 | 100.00000000 | 1 | 1 | 0 |

## Interpretation

Synthetic depth proves deterministic queue, participation, spread and level-consumption behavior. It does not certify real exchange queue priority. Real L2 certification remains gated by venue snapshots, incremental updates and trade prints.
