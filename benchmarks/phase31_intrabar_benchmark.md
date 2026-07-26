# Phase 31 Intrabar Benchmark

- Rows: `25000`
- Repeats: `3`
- Seed: `31`

| Route | Runtime | Bars/s | Ratio vs close-target | Ratio vs intrabar minimal | Speedup vs Python oracle | Fills/orders | Parity | Notes |
|---|---:|---:|---:|---:|---:|---:|---|---|
| `close_target_v2_pure_kernel` | 0.008153s | 3,066,338 | 1.00x | - | - | 0 | baseline |  |
| `intrabar_bracket_v1_minimal` | 0.011811s | 2,116,601 | 1.45x | - | 19.13x | 2000 | oracle_checked_in_tests |  |
| `intrabar_bracket_v1_audit` | 0.051050s | 489,716 | 6.26x | 4.32x | 4.43x | 2000 | pass | two_pass_sparse_fills |
| `intrabar_reference_python` | 0.225907s | 110,665 | 27.71x | 19.13x | - | 2000 | truth_model |  |
| `fill_replay_v1_kernel` | 0.012107s | 2,064,903 | 1.48x | 1.03x | - | 2000 | accounting_only |  |
| `native_event_explicit_orders_facade` | 0.083749s | 298,512 | 10.27x | 7.09x | - | 2000 | speed_reference_not_semantic_claim | full_facade_order_replay |

## Summary

- Fast intrabar minimal vs Python oracle: `19.13x` faster.
- Fast intrabar audit vs minimal: `4.32x` runtime ratio.
- Fast intrabar minimal vs close-target pure kernel: `1.45x` runtime ratio.

Interpretation: close-target remains the fastest narrow contract. The new intrabar kernel is the fast path for alpha logic that needs next-open entry, intrabar SL/TP/trailing, and audit fills without falling back to Python event loops.
