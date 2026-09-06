# Native WFO Runtime V2

`NativeWfoRuntimeV2` is an explicit prepared execution companion for bounded single-symbol `NativeStrategyIR` walk-forward workloads.

It moves repeated candidate-by-fold simulation into one persistent Rust worker pool while feature generation and Optuna control remain in Python. It remains the advanced static-IR route for explicit W1/W2 candidate matrices. Phase 74 separately adds a narrow prepared-native scorer beneath normal `QuantBTEndpoint.walk_forward()`; arbitrary pandas callbacks, portfolio targets, packages, and reactive state machines do not become generic Rust WFO routes.

## Certified Scope

| Property | Native WFO V2 contract |
|---|---|
| Workload | `strategy_ir_signal_target_v1` only |
| Symbols | one |
| Account per fold | fresh/reset-flat OOS account |
| Strategy input | finite full-tape signal matrix or fold-specific cube |
| Execution | prepared Rust static StrategyIR + event/account contract |
| Output | bounded scalar candidate/fold metric matrix; selected audit only |
| Optimizer | Python Optuna, explicit schedule ID |
| Market/folds | immutable content-fingerprinted plan |

Target-unit/notional/weight/equity targets are not coerced into this
signal-runtime. Phase 66 adds a separate `NativeTargetWfoRuntimeV2` companion
for explicitly prepared direct target matrices; Phase 67 adds an explicit
shared-account portfolio form of that companion. Static orders, package
targets, and generic reactive strategies remain outside both runtime contracts.

## Direct Target Companion V1

`NativeTargetWfoRuntimeV2` is a separate Rust owner for a
`(candidate, bars, symbols)` target tensor. It uses
`close_target_v2_same_close`, calculates direct position deltas without a
generic command arena, and starts a fresh account for every candidate/fold.
It accepts `target_kind="units" | "notional" | "weight" |
"equity_fraction"`. With no `admission_policy`, the historic contract stays
single-symbol. Passing an explicit portfolio admission policy enables a
multi-symbol target matrix evaluated against **one fresh shared account per
candidate/fold**, not a per-symbol account and not a stitched WFO account.
The certified first row is target units; other target kinds remain explicit
experimental resolvers.

```python
from quantbt.backends import NativeIRFold, NativeTargetWfoRuntimeV2

# `template` is created once from an immutable prepared market and account.
folds = (
    NativeIRFold(0, 0, 0, 1_000, 1_000, 1_500),
    NativeIRFold(1, 0, 0, 1_500, 1_500, 2_000),
)
runtime = NativeTargetWfoRuntimeV2(template, folds, target_kind="units")

prepared = runtime.prepare_shared(
    candidate_targets,  # (candidates, prepared_market_bars, 1)
    candidate_ids=candidate_ids,
)
score = runtime.score_prepared_batch(prepared)
audit = runtime.audit_prepared_batch(
    prepared,
    selected_candidate_ids=[best_candidate_id],
    expected_intent_fingerprint=score.intent_fingerprint,
)
audit.assert_audit_parity(score)
```

For a planned two-or-more symbol target matrix, opt in explicitly:

```python
portfolio_runtime = NativeTargetWfoRuntimeV2(
    template,
    folds,
    target_kind="units",
    admission_policy="reduce_first_then_increase",
)
portfolio_score = portfolio_runtime.score_shared(
    candidate_targets,  # (candidates, prepared_market_bars, symbols)
    candidate_ids=candidate_ids,
)
```

The admission policy is part of the immutable plan fingerprint. It is never
inferred from symbol count. `score` retains no paths or per-symbol attribution;
rerun only selected candidates in audit mode for bounded attribution evidence.

The target batch belongs to exactly one plan fingerprint. The immutable market
is not copied per candidate or fold. A local target/mask window is deliberately
copied for each execution because every OOS fold has a fresh direct-target
request; `candidate_execution_copy_bytes` reports those bytes honestly.

Read [V1.1 Direct Target Execution Clock](contracts/v1_1_target_execution_clock.md)
before using this route. `target_runtime="auto"` is unchanged: it does not
select this companion runtime.

## Strategy Boundary

| Level | Owner | Contract |
|---|---|---|
| W0 | Existing Python WFO | one pandas/callback invocation per trial/fold; compatibility oracle |
| W1 | Prepared Python strategy | `generate(params, fold_id)` returns one full-tape numeric signal row |
| W2 | Batched prepared strategy | `generate_batch(params_matrix, fold_id)` returns a candidate-by-bar signal matrix |

W1/W2 may cache only parameter-independent work built from the declared market tape. The strategy remains responsible for indicator causality. Rust executes only the declared OOS `test_start:test_end` range with a fresh account for each fold.

## Construct A Runtime

Prepare a market and static IR with the existing native-event API, then declare causal offsets over that immutable tape:

```python
from quantbt import NativeIRFold, NativeStrategyIR, NativeStrategyKind
from quantbt import NativeStrategyParameters, NativeWfoRuntimeV2

program = NativeStrategyIR(
    NativeStrategyKind.SIGNAL_TARGET,
    "BTC",
    parameters=NativeStrategyParameters(quantity=1.0),
)

# `full_runner` comes from NativeEventBackend.prepare_rust_batched_runner(...).
folds = (
    NativeIRFold(0, 0, 0, 1_000, 1_000, 1_500),
    NativeIRFold(1, 0, 0, 1_500, 1_500, 2_000),
)
runtime = NativeWfoRuntimeV2.from_full_runner(
    full_runner,
    program,
    folds,
    optimizer_schedule="certified_sequential_v1",
    workers=2,
)
```

The plan fingerprint includes prepared market, instrument/account/execution template, program fingerprint, fold table, schedule, and resource budget. A prepared signal buffer can only be consumed by a runtime with that plan.

## Fixed Candidate Matrix

`prepare_per_fold()` is the controlled Python-to-Rust ingestion boundary. Repeated score/audit calls reuse its Rust-owned buffer without another candidate-by-bar execution copy.

```python
candidate_ids = np.arange(signals_by_fold.shape[1], dtype=np.uint64)
batch = runtime.prepare_per_fold(
    signals_by_fold,  # (folds, candidates, prepared_market_bars)
    candidate_ids=candidate_ids,
)
score = runtime.score_prepared_batch(batch)

audit = runtime.audit_prepared_batch(
    batch,
    selected_candidate_ids=np.asarray([best_candidate_id], dtype=np.uint64),
    expected_intent_fingerprint=batch.intent_fingerprint,
)
audit.assert_audit_parity(score)
```

`score` exposes stable candidate/fold rows sorted by candidate then fold. It retains no full equity path, fill table, event table, DataFrame, or Python strategy object. `score.to_frame()` is an explicit cold-path conversion.

## W1/W2 Prepared Optimization

Use `score_prepared()` or `optimize_prepared()` for a prepared alpha object. W2 is automatic when `generate_batch` exists; use `adapter="w1"` or `adapter="w2"` to declare it explicitly.

```python
result = runtime.optimize_prepared(
    prepared_alpha,
    param_ranges={"threshold": (-0.5, 0.5, 0.05)},
    n_trials=200,
    seed=42,
    top_k_audit=3,
)

print(result.best_params, result.best_value)
result.audit_matrix.assert_audit_parity(result.score_matrix)
```

Top-K audit does not retain all trial signal matrices. It retains small candidate/parameter provenance, regenerates the original source batch, and requires its intent fingerprint to equal the score batch before audit begins. A non-deterministic prepared generator therefore fails instead of creating an untrustworthy audit.

## Optimizer Schedules

| Schedule | Behavior | Claim |
|---|---|---|
| `certified_sequential_v1` | ask one, prepare/evaluate one, tell one | same seed + same score contract yields the sequential lifecycle |
| `throughput_batch_v1` | ask `B`, evaluate `B`, then tell `B` | deterministic only for same seed, sampler, and batch size; never sequential-TPE equivalent |
| `fixed_matrix_v1` | no adaptive Optuna loop | use `score_prepared_batch()` directly |

For throughput, `metadata["candidate_sequence_equivalent_to_sequential"]` is always `False`. A quality regret appears only when the caller supplies an independent `reference_best_objective`; otherwise metadata records that no cross-sequence quality claim was evaluated.

Both schedules use `NopPruner`: a WFO candidate is reported only after its
complete fold matrix is available, so there is no valid intermediate
observation for a step-wise Optuna pruner. The declared
`pruner_contract="nop_pruner_complete_fold_scalar_v1"` is part of the
reproducible optimizer provenance.

## Metrics, Memory, And Recovery

Score/audit matrices contain contiguous candidate/fold IDs, status, final equity, returns, Sharpe/Sortino, drawdown, turnover, fees, funding, fill and rejection counts, liquidation, request fingerprint, and terminal fingerprint. Failed rows use a bounded error side table and typed status code.

`runtime.diagnostics()` records pool creation, score/audit batches, completed/canceled tasks, worker distribution, poison recovery, and plan metadata. One runtime creates one worker pool. `reset()` rebuilds scratch sessions while preserving the plan; `close()` tears down workers deterministically.

```text
market copies per candidate/fold/scenario:       0
prepared intent O(T) copies per execution:       0
controlled Python -> Rust ingest per score batch: 1
```

`intent_ingest_bytes` reports that controlled ingress; it is intentionally not reported as zero.

## Phase 71 Runtime Governance

`NativeWfoRuntimeV2` accepts `RuntimeBudgetV1` and an optional
`ParallelismPlanV1`. Budgets cover bars, workers, native bytes, metric/audit
rows, command/order/fill upper bounds, and candidate/fold safe-point wall
time. Prepared batches are bound to one runtime session, reject cross-runtime
reuse, and expose explicit `close()` semantics. Runtime `reset()` increments a
generation while retaining immutable same-session prepared inputs;
`cancel()`/`clear_cancellation()` produce typed canceled rows and clean
recovery.

The Phase 71 warm soak reused a 4,096-bar, 32-candidate, four-fold batch for 30
scores. Its preserved median runtime was 13.325 ms. The four causal OOS windows
totaled 3,414 test bars, so the corrected executor rate is 8.20M actual
candidate-test-bar visits/s; the former 39.35M value is preserved only as a
logical full-tape input-volume metric. All RSS samples were 162.98 MiB,
terminal fingerprints remained deterministic, and reset/cancel/recovery
passed. This warm pre-ingested measurement is distinct from the Phase 65
end-to-end preparation/ingest comparison. See the
[measurement contract](performance/measurement_contract_v1.md).

See [Native Runtime Governance](native_runtime_governance.md) for lifecycle,
budget, parallelism, and shadow-oracle contracts.

## Evidence And Limits

Phase 73 additionally provides the internal
[Shared Prepared Native Evaluation Runtime](native_prepared_evaluation.md) for
typed static, target, bounded portfolio/package, and intrabar request handles.
Phase 74 uses that substrate for compatible W0 scalar public WFO score tasks,
with exact mode/selection/final-account parity. The normal public matrix,
fallback policy, and optional W1/W2 strategy-preparation contract are described
in [Public prepared-native WFO scoring](native_prepared_wfo_public.md).

Run the reproducible local evidence:

```bash
MPLCONFIGDIR=/tmp poetry run python \
  benchmarks/native_event/benchmark_phase65_native_wfo.py
```

It compares every metric with the prior causal fold-batch oracle and reports strategy preparation/generation, intent ingestion, fused Rust score/metrics, cold report adaptation, optional Optuna lifecycle, worker use, copy counters, and RSS. Do not compare this to generic callback WFO: W0 includes arbitrary Python feature generation and pandas output contracts by design.

For chronology, anti-leakage claims, `optimization_mode`, and the public `optimization_schedule`, read [Causal Walk-Forward](walkforward_causal.md) and [Walk-Forward Methodology](walkforward_methodology_vi.md). Native WFO V2 does not change those selection semantics.
