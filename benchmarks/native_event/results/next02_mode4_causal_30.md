# NEXT-02 Fresh Public WFO Evidence

All rows use the same public endpoint, candidate space, seed, calendar, account, retention and final stitched account.
`w0_native_prepared_score` changes only the compatible fresh-account scorer; `w1_*` is a separate opt-in
strategy-preparation protocol. Mode 2 retains its path/bootstrap proxy and has no scalar Rust row.

| Mode | Schedule | W0 endpoint | W0 native score | Native/W0 p50 [CI95] | W1 native score |
|---|---|---:|---:|---:|---:|
| `mode_4_is_only_robust` | `per_fold_causal` | 1.3603 s | 0.6723 s | 0.500 [0.484, 0.539] | 0.7223 s |

- Fresh cache/reused-prefix gates: `True`.
- Selection and final-account parity: `True`.
- Samples per paired lane: `30` (`paired_p50_qualified_no_p95`).
- This artifact reports Rust prepared scoring and W1 projection separately from arbitrary Python alpha computation.
  It does not claim a native speedup for user feature generation or Mode 2 bootstrap logic.
