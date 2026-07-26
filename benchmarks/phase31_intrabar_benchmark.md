# Phase 31 Intrabar Benchmark

- Rows: `25000`
- Repeats: `3`
- Seed: `31`

| Route | Runtime | Bars/s | Ratio vs close-target | Ratio vs intrabar minimal | Speedup vs Python oracle | Fills/orders | Parity | Notes |
|---|---:|---:|---:|---:|---:|---:|---|---|
| `close_target_v2_pure_kernel` | 0.011514s | 2,171,235 | 1.00x | - | - | 0 | baseline |  |
| `intrabar_bracket_v1_minimal` | 0.011829s | 2,113,511 | 1.03x | - | 23.32x | 2000 | oracle_checked_in_tests |  |
| `intrabar_bracket_v1_audit` | 0.052715s | 474,245 | 4.58x | 4.46x | 5.23x | 2000 | pass | two_pass_sparse_fills |
| `intrabar_reference_python` | 0.275860s | 90,626 | 23.96x | 23.32x | - | 2000 | truth_model |  |
| `fill_replay_v1_kernel` | 0.011065s | 2,259,396 | 0.96x | 0.94x | - | 2000 | accounting_only |  |
| `native_event_explicit_orders_facade` | 0.076147s | 328,311 | 6.61x | 6.44x | - | 2000 | speed_reference_not_semantic_claim | full_facade_order_replay |

## Summary

- Fast intrabar minimal vs Python oracle: `23.32x` faster.
- Fast intrabar audit vs minimal: `4.46x` runtime ratio.
- Fast intrabar minimal vs close-target pure kernel: `1.03x` runtime ratio.

Interpretation: close-target remains the fastest narrow contract. The new intrabar kernel is the fast path for alpha logic that needs next-open entry, intrabar SL/TP/trailing, and audit fills without falling back to Python event loops.
