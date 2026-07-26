# Phase 31 Intrabar Benchmark

- Rows: `25000`
- Repeats: `3`
- Seed: `31`

| Route | Runtime | Bars/s | Ratio vs close-target | Ratio vs intrabar minimal | Speedup vs Python oracle | Fills/orders | Parity | Notes |
|---|---:|---:|---:|---:|---:|---:|---|---|
| `close_target_v2_pure_kernel` | 0.008638s | 2,894,106 | 1.00x | - | - | 0 | baseline |  |
| `intrabar_bracket_v1_minimal` | 0.012390s | 2,017,811 | 1.43x | - | 18.89x | 2000 | oracle_checked_in_tests |  |
| `intrabar_bracket_v1_audit` | 0.054350s | 459,978 | 6.29x | 4.39x | 4.31x | 2000 | pass | two_pass_sparse_fills |
| `intrabar_reference_python` | 0.234048s | 106,816 | 27.09x | 18.89x | - | 2000 | truth_model |  |
| `fill_replay_v1_kernel` | 0.012282s | 2,035,552 | 1.42x | 0.99x | - | 2000 | accounting_only |  |
| `native_event_explicit_orders_facade` | 0.079248s | 315,465 | 9.17x | 6.40x | - | 2000 | speed_reference_not_semantic_claim | full_facade_order_replay |

## Summary

- Fast intrabar minimal vs Python oracle: `18.89x` faster.
- Fast intrabar audit vs minimal: `4.39x` runtime ratio.
- Fast intrabar minimal vs close-target pure kernel: `1.43x` runtime ratio.

Interpretation: close-target remains the fastest narrow contract. The new intrabar kernel is the fast path for alpha logic that needs next-open entry, intrabar SL/TP/trailing, and audit fills without falling back to Python event loops.
