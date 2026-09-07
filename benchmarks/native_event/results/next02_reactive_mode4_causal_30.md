# NEXT-02 Fresh Public Reactive-WFO Evidence

Every timing pair uses the same public W3 scalar strategy, market, seed, account, folds, selection and audit.
B1 uses `preparation_policy="compatibility"`; B2 uses `preparation_policy="prepared"`.

| Mode | Schedule | B1 compatibility | B2 prepared | B2/B1 p50 [CI95] |
|---|---|---:|---:|---:|
| `mode_4_is_only_robust` | `per_fold_causal` | 0.6097 s | 0.4228 s | 0.696 [0.665, 0.716] |

- Fresh gates: `True`.
- Public result/account parity: `True`.
- Samples per pair: `30` (`paired_p50_qualified_no_p95`).
- Mode 2 remains explicitly unsupported for W3; R3B is a separately versioned batch protocol.
- This B1/B2 engineering comparison does not claim a legacy B0 product-alpha reproduction.
