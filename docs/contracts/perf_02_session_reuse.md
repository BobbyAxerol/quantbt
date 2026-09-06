# PERF-02 Session Reuse Contract

This contract governs reuse of a native execution session for **independent** candidate evaluations. It does not authorize an implicit reset of a carried deployment account or a stateful strategy.

## Reset Manifest

| Class | Ownership and reset rule |
| --- | --- |
| Immutable shared input | Prepared market, instrument table, execution contract, and request schema are shared and never mutated by a run. |
| Run account state | Wallet, positions, marks, fees, funding, margin, liquidation, IDs, sequencing, liquidity, and error/poison state reset before every independent run. |
| Order lifecycle | Pending commands, active orders, OCO/parent links, expiry state, and matching scratch reset. Live orders are explicitly cancelled; a terminal-only high-water arena can clear without scanning inactive slots. |
| Worker scratch | Step buffers and matching candidates may retain capacity. `result_buffers` can explicitly release only resettable scratch. |
| Retained result | Score, compact, and audit buffers transfer owned storage into the Python result. A later reset or scratch release cannot mutate an earlier result. |
| Stateful/reactive data | Callback, wake, cancellation, and carried-account state are not silently reset. They require an explicit lifecycle contract. |

`FullSession` rejects sequence wrap with checked arithmetic. An order-arena slot whose generation reaches `u32::MAX` is retired rather than recycled, so a stale handle cannot become valid through generation wrap.

## Reset Scopes

| Scope | Permitted effect |
| --- | --- |
| `account_and_orders` | Reset a completed independent execution account and its order lifecycle. |
| `result_buffers` | Release resettable scratch capacity only; exported result arrays remain valid. |
| `full_rebuild` | Drop the worker/session so the next use constructs a fresh native runner. |

There is no `account_only` shortcut: clearing account balances while retaining orders, reservations, pending commands, or lifecycle IDs would violate the independent-trial contract.

## Derived Account Snapshot

`DerivedAccountSnapshotV1` is valid only for a completed post-execution bar. It records a phase-aware cache key over these mutations:

| Version | Invalidated by |
| --- | --- |
| `mark` | A new bar mark, including a mark with no position change. |
| `position` | A fill or liquidation that changes position. |
| `wallet` | Mark-to-market, fill cash flow, funding, fee, or liquidation cash flow. |
| `fee` / `funding` | Their corresponding accounting events. |
| `risk` | Liquidation or execution-account risk configuration changes. |
| `instrument` | Contract/model configuration changes. |
| `reservation` | Explicit in the key. The current single-session contract has no persistent reservation ledger, so it remains unchanged rather than inferred. |

The cache never answers a pre-command or intrabar accounting question from a post-execution value. A full recomputation remains the test oracle. Nonlinear future margin, tier, cross-margin, offset, and FX semantics must use a dedicated full-recompute contract rather than assuming additive cache updates are valid.

## Verification Evidence

`tests/test_perf_02_session_reuse.py` runs 128 independent prepared executions through one reused runner after a fresh reference, asserts exact output parity, then releases scratch and proves the original exported arrays are unchanged. Reactive numeric reset coverage extends the same assertion through repeated native session resets. Engine tests cover stale-handle retirement and snapshot-vs-recompute parity after mark, fill, fee, funding, liquidation, and reset.

The native release fixture is documented in [PERF-02 session-reuse evidence](../../benchmarks/native_event/results/perf_02_session_reuse.md). It distinguishes a cheap terminal-order reset from a correct live-order reset that must visit and cancel all active orders. It is not a generic endpoint or WFO throughput claim.

## Operational Rule

Use a prepared reused runner only for independent trials with an immutable, compatible market/template/request contract. Use a carried stateful runtime when the strategy intentionally carries account, position, or callback state; do not recover a poisoned Python strategy by retrying it without an explicit restore contract.
