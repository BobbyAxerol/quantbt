# Shared Prepared Native Evaluation Runtime

## Scope

`NativePreparedEvaluationRuntimeV1` is the internal Rust-owned scheduler for a
batch of already prepared native requests. It is a building block, not a new
public endpoint. Phase 74 now uses it beneath the normal WFO/train-test scorer
for a narrow single-symbol target matrix, while preserving each mode's existing
selection mathematics and final account reconstruction.

The runtime has exactly one job: run independent candidate/fold/scenario
evaluations over immutable typed request handles without rebuilding a worker
pool, copying a market tape, or replaying execution in Python.

## Certified Request Families

| Prepared workload | Accepted request contract | Execution authority |
|---|---|---|
| `static_command_tape` | `command_tape_v5` | Rust static lifecycle/accounting |
| `strategy_ir` | `strategy_ir_v1` | Rust bounded IR |
| `target_units` | `direct_target_v1` units | Rust direct-target engine |
| `target_notional` | `direct_target_v1` notional | Rust direct-target engine |
| `target_weight` | `direct_target_v1` weight | Rust direct-target engine |
| `target_equity_fraction` | `direct_target_v1` equity fraction | Rust direct-target engine |
| `pct_equity_transition` | `direct_target_v1` transition-sized `%_equity` | Rust transition-sized compatibility engine |
| `shared_portfolio_target` | `shared_portfolio_target_v1` or `portfolio_target_market_v1` | Rust shared-account target engine |
| `bounded_same_account_package` | `package_atomic_market_v1` or `package_market_v2` | Rust bounded package engine |
| `single_symbol_intrabar` | `intrabar_bracket_v1` | Rust intrabar engine |

An unsupported workload, request type, nonlocal range, metric convention, or
account-continuity policy fails before execution. The scheduler never guesses a
target proxy or silently changes an execution clock.

## Ownership And Batch Boundary

Preparation owns three content-addressed immutable tiers:

```text
market -> template -> typed request -> runtime binding -> scalar row
```

The market signature includes timestamps, symbols, OHLCV, funding, and the
funding mask. Template/request signatures include instrument constraints,
account/execution settings, output profile, and request tape values. Changing
any of those values makes a different cache key. Rust takes owned copies at
controlled ingress; later mutation of the caller's NumPy arrays cannot change
an existing prepared request.

The runtime binds `Arc`-backed request handles. A score batch makes one
Python-to-Rust call, dispatches cost-ranked candidate tasks through one
persistent Rust worker pool, and returns scalar Structure-of-Arrays output.
Market/template/request payloads are shared by reference during execution:

```text
market copies per candidate/fold/scenario = 0
prepared intent O(T) copies per execution = 0
worker-pool creations per runtime = 1
worker-pool creations per score batch = 0
```

The initial Python-to-Rust ingress of a new market or intent is intentionally
measured separately as both facade normalization bytes and Rust-owned request
bytes. It is not relabelled as a zero-copy execution.

## Accounting, Metrics, And Audit

Every row carries candidate/fold/scenario identity, terminal/accounting
fingerprints, fees, funding, turnover, fills, rejections, liquidation state,
and MetricContractV2 score fields. The current certified metric policy is
crypto daily annualization (`365`) only. Requesting `252` raises rather than
silently relabelling Sharpe/Sortino.

Score output retains bounded scalar rows only. It does not construct a
DataFrame, full equity paths, Python report objects, or a replayed account
engine. A selected audit request is rerun from the same immutable tape and its
terminal fingerprint/accounting fields must match the score run. Cold-path
`to_frame()` is available only for inspection or reporting.

`evaluate_score_columns()` is the lower-allocation score boundary used by the
public WFO adapter. It returns typed NumPy columns for identity/status, total
return, Sharpe, drawdown, profit factor and report trade count. It does not call
the compatibility `as_dict()` API or create one Python row object per native
score. Call `evaluate()` only where a cold/audit consumer needs the complete
row schema and fingerprints.

## Lifecycle And Resource Rules

Each row has `fresh_account_per_evaluation` semantics. The cache shares only
immutable data; no account, open order, lifecycle, reducer, or scratch state
can leak from one candidate to another. Chronological account continuity is an
explicit execution contract and is not inferred by this generic evaluator.

`RuntimeBudgetV1` gates bars, workers, native memory, scalar metric rows,
audit rows, and other declared resource limits before a batch begins.
`cancel()` marks queued work canceled at candidate-task boundaries; it never
returns a canceled result as success. `reset()` advances the runtime generation
and invalidates old bindings while retaining its worker pool. `close()` joins
the workers deterministically; cross-runtime, stale-generation, stale-cache,
and use-after-close bindings fail closed.

An internal worker panic marks the batch row failed with bounded error detail,
then rebuilds the entire worker pool before a later batch can reuse it. Recovery
failure closes the runtime rather than reusing potentially corrupted scratch.

## Explicit Limits

- It does not execute arbitrary Python callbacks or reactive strategies.
- It does not accept partial ranges against a full tape. Build a zero-copy
  `cache.window_template(...)` for each declared causal fold.
- It does not create public WFO mode/schedule semantics, stitch OOS accounts,
  or select parameters. The Phase 74 adapter supplies already-generated WFO
  score tasks; `WalkForwardEngine` remains the owner of those policies.
- It does not make a generic portfolio, package, or arbitrage endpoint claim;
  only the bounded typed request contracts in the table are admitted.

## Evidence

Run the narrow reproducible benchmark:

```bash
PYTHONPATH=src .venv/bin/python \
  benchmarks/native_event/benchmark_phase73_prepared_evaluation.py
```

It reports preparation, intent ingestion, binding, warm batch execution plus
scalar adaptation, RSS samples, copy counters, one-pool/one-boundary evidence,
and deterministic terminal rows. It is deliberately not an end-to-end WFO or
Optuna speed claim.

For the specialized static-IR WFO primitive, see
[Native WFO Runtime V2](native_wfo_runtime.md). For the public Phase 74 routing
matrix and W0/W1/W2 contracts, see
[Public prepared-native WFO scoring](native_prepared_wfo_public.md). For WFO
causality and selection semantics, see [Causal Walk-Forward](walkforward_causal.md).
