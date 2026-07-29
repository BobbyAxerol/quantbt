# Phase 31 Intrabar Benchmark

- Rows: `25000`
- Repeats: `3`
- Seed: `31`

| Route | Runtime | Bars/s | Ratio vs close-target | Ratio vs intrabar minimal | Speedup vs Python oracle | Fills/orders | Parity | Notes |
|---|---:|---:|---:|---:|---:|---:|---|---|
| `close_target_v2_pure_kernel` | 0.008683s | 2,879,313 | 1.00x | - | - | 0 | baseline |  |
| `intrabar_bracket_v1_minimal` | 0.011815s | 2,115,865 | 1.36x | - | 20.26x | 2000 | oracle_checked_in_tests |  |
| `intrabar_bracket_v1_audit` | 0.052695s | 474,427 | 6.07x | 4.46x | 4.54x | 2000 | pass | two_pass_sparse_fills |
| `intrabar_session_bracket_v1_minimal` | 0.011652s | 2,145,495 | 1.34x | 0.99x | 20.55x | 1836 | reference_checked_in_tests | session_state_kernel |
| `intrabar_session_bracket_v1_audit` | 0.049885s | 501,156 | 5.75x | 4.22x | 4.80x | 1836 | pass | session_two_pass_sparse_fills |
| `intrabar_reference_python` | 0.239421s | 104,419 | 27.57x | 20.26x | - | 2000 | truth_model |  |
| `fill_replay_v1_kernel` | 0.012415s | 2,013,664 | 1.43x | 1.05x | - | 2000 | accounting_only |  |
| `native_event_explicit_orders_facade` | 0.076076s | 328,618 | 8.76x | 6.44x | - | 2000 | speed_reference_not_semantic_claim | full_facade_order_replay |

## Summary

- Fast intrabar minimal vs Python oracle: `20.26x` faster.
- Fast intrabar audit vs minimal: `4.46x` runtime ratio.
- Fast intrabar minimal vs close-target pure kernel: `1.36x` runtime ratio.

Interpretation: close-target remains the fastest narrow contract. The new intrabar kernel is the fast path for alpha logic that needs next-open entry, intrabar SL/TP/trailing, and audit fills without falling back to Python event loops.
