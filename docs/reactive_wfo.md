# Reactive Walk-Forward (W3)

`QuantBTEndpoint.prepare_reactive_walk_forward(...)` is QuantBT's explicit walk-forward route for stateful event-driven strategies. It does not turn a strategy into a `pos_weight` series. Rust owns the prepared market clock, orders, fills, fees, funding, margin, liquidation, and scalar account score; Python owns only the declared strategy decision boundary.

Use ordinary `QuantBTEndpoint.walk_forward(...)` when a strategy can honestly return a causal target or signal series. Use W3 when strategy state, open orders, fills, sparse wakes, or block invalidation affect later commands.

## Certified Scope

| Property | Certified behavior |
|---|---|
| Market | One finite, UTC, contiguous OHLCV tape and one symbol |
| Backend | Explicit installed Rust native-event backend |
| Strategy | Numeric R1 every-bar, R2 sparse wake, R3 block, or opt-in R3B batch |
| WFO modes | `mode_1_decay`, `mode_3_flat_minima`, `mode_4_is_only_robust`, `mode_5_full_robust` |
| Account boundary | Fresh flat account for every candidate/fold score and outer OOS audit |
| Output | Per-fold OOS accounts and metrics, never a fabricated compounded OOS curve |
| Unsupported | `mode_2_sbb`, carry account/position, portfolio/package WFO, auto-routing |

Each score window uses absolute bar coordinates of the single prepared tape, but starts a new account at its first bar. This preserves callback time, scheduled orders, and causal feature alignment without carrying account or strategy state between folds.

`result.oos_output` is therefore always `None`. Inspect reset-flat OOS segments through `result.segmented_equity`, `result.fold_metrics()`, `result.fold_table`, and `result.fold_results`.

## Minimal Sequential Route

The factory prepares parameter-independent causal data once, then builds one fresh strategy for each candidate/fold/window task.

```python
from quantbt import ExecutionConfig, QuantBTEndpoint, RuntimeBudgetV1
from quantbt.backends import ReactiveWfoRuntimeConfigV1
from quantbt.strategies import STRICT_CAUSAL_CACHE_CONTRACT_V1
from quantbt.walkforward import WalkForwardConfig


class PreparedStrategy:
    causal_cache_contract = STRICT_CAUSAL_CACHE_CONTRACT_V1

    def __init__(self, close):
        self.close = close  # Parameter-independent and causal only.

    def build_strategy(self, *, params, task):
        return MyReactiveStrategy(close=self.close, params=dict(params), task=task)


class StrategyFactory:
    def prepare_reactive_wfo(self, *, data, folds, static_config):
        return PreparedStrategy(data["close"].to_numpy(copy=True))


endpoint = QuantBTEndpoint.native_event_strategy(
    initial_capital=20_000.0,
    leverage=3.0,
    fee_rate=0.0004,             # Canonical one-way fee.
    native_backend="rust",
    reactive_kernel_mode="single_pass",
    reactive_runtime="numeric_every_bar_v1",
    execution_contract="event_lifecycle_v3_next_open",
    execution=ExecutionConfig(slippage_bps=1.0),
)

config = WalkForwardConfig(
    split_mode="walk_forward_2022",
    split_frequency="quarterly",
    window_mode="rolling",
    train_window="365D",
    target_mode="signal_notional",
    optimization_mode="mode_1_decay",
    optimization_schedule="global",
    fold_boundary_position_policy="reset_flat",
    fold_account_policy="reset_flat",
    optuna_trials=200,
    random_seed=42,
)

runtime = endpoint.prepare_reactive_walk_forward(
    data=market_data,
    strategy_factory=StrategyFactory(),
    walkforward_config=config,
    runtime_config=ReactiveWfoRuntimeConfigV1(
        runtime_budget=RuntimeBudgetV1(max_wall_time_ms=60_000),
    ),
    symbols=["BTCUSDT"],
)
try:
    result = runtime.backtest(param_ranges={"lookback": (8, 48, 4)})
finally:
    runtime.close()

print(result.fold_metrics())
print(result.fold_table)
```

`MyReactiveStrategy` must meet the chosen R1/R2/R3 callback contract in the [Rust native-event contract](native_event_rust_full_contract.md). A mutable strategy instance is task-local: returning it for two tasks fails before scoring. It may expose `quantbt_state_fingerprint()` for audit provenance.

## Selection And Causality

The generic `WalkForwardEngine` remains authority for folds, parameter validation, Optuna ask/tell, and selection mathematics. W3 replaces only its target-series scorer with prepared reactive account scores.

- Modes 4 and 5 select from IS-only rows. Metadata records `oos_seen_by_optuna=False`; R3B does not score OOS for their selector.
- Modes 1 and 3 score all candidates on declared IS windows first. Only the IS shortlist receives OOS scoring for decay/selection.
- `certified_sequential_v1` is the default: one Optuna ask, score, and tell at a time. It supports the declared global and per-fold schedules.
- `throughput_batch_v1` is an explicit R3B ask-B/score-B/tell-B contract. It is deterministic for its seed and batch size, but is not sequential TPE and currently requires `optimization_schedule="global"`.

Fixed candidate matrices use the same IS formulas and OOS eligibility rules as scalar W3. Candidate identity is a stable canonical-parameter hash, independent of caller ordering.

## Sparse Candidate Batch (R3B)

R3B is opt-in. The prepared strategy implements `build_candidate_batch(params_matrix=..., tasks=...)`; the batch strategy implements `on_wake_batch(context_batch, out_batch)` and returns `CandidateWakePlansV1`. Rust still processes account, fill, funding, and margin state for every active candidate every bar. Only the Python decision callback is coalesced for candidate IDs with a declared wake.

```python
runtime_config = ReactiveWfoRuntimeConfigV1(
    optimizer_schedule="throughput_batch_v1",
    candidate_batch_size=16,  # 1..64
)

result = runtime.backtest(
    candidate_matrix=known_candidate_params,
    param_ranges=param_ranges,
)
```

With `candidate_matrix`, metadata declares `sampling_contract="fixed_candidate_matrix_r3b_v1"`; with `param_ranges`, it declares `adaptive_optuna_batch_r3b_v1`. Candidate-local native command or wake-plan errors become pruned candidate records and cannot affect the selector. A malformed shared Python batch callback fails the batch closed.

`reference_best_objective` and `max_quality_regret` are paired evidence gates for throughput experiments, not auto-promotion controls.

## Process Worker And Memory Contract

`worker_mode="process"` is available only for sequential scalar scoring on Linux/POSIX with `fork`. The parent must have exactly one kernel thread at fork time. This is intentional: a multi-threaded process can duplicate a locked runtime mutex into its child. Notebooks or services with BLAS/runtime threads should use `worker_mode="inprocess"` or launch a dedicated constrained worker.

The child inherits immutable prepared market data by copy-on-write and owns resettable native scalar sessions. IPC contains an opaque task marker and scalar row only, never a DataFrame or market tape. Runtime metadata reports worker/session reuse, task IPC bytes, RSS, PSS, shared pages, and private pages. Use PSS rather than summed parent/child RSS when reasoning about unique memory.

There is one in-flight native batch. Cancellation, worker error, or callback failure discards affected state before a later task can inherit orders, account, strategy, or RNG state. Close the runtime in `finally` when embedding it in a service.

## Audit Surface

```python
meta = result.metadata
meta["runtime"]                  # worker/session/resource ownership
meta["sampling_contract"]        # sequential or explicit batch schedule
meta["candidate_batch"]           # R3B telemetry, when used
meta["params_by_fold"]            # selected params by outer fold
result.best_trial                # selection provenance
result.trial_table               # candidate rows
result.candidate_table           # shortlist evidence
result.fold_table                # one reset-flat OOS account per fold
```

The selected cold OOS audit reruns each fold through the prepared Rust result route. Its equity, fees, and terminal account state are checked against the corresponding scalar score window. The optimization path deliberately retains no account paths, fill ledger, or callback trace by default.

## Active Work Limits

`ReactiveWfoRuntimeConfigV1(runtime_budget=RuntimeBudgetV1(...))` applies its
wall-time limit to each active native candidate/fold score, rather than merely
recording it in metadata. R1 checks after every completed account bar; sparse
R2 and block R3 native gaps check at most every 64 completed account bars and
at the wake/end boundary. The timer begins after the fresh fold account is
initialized. A deadline produces `RuntimeBudgetError(code="MAX_WALL_TIME")`;
a cancellation produces `RuntimeCanceledError`. Neither partial score can be
ranked, selected, or reused.

`runtime.cancel()` signals an active in-process scalar session or R3B candidate
batch. The sequential COW process worker retains its existing stronger
discard-and-recover boundary: a canceled or failed child is torn down before a
later task starts. `reset()`/the next session reset clears native interrupt
state, so a subsequent independent fresh-account task remains valid.

## Benchmark And Boundaries

```bash
PYTHONPATH=src poetry run python \
  benchmarks/native_event/benchmark_phase76_reactive_wfo.py \
  --bars 2000 --candidates 8 --repeats 3
```

Phase 77.3 adds a matched reactive closure artifact with active deadline and
cross-route regression evidence:

```bash
PYTHONPATH=src poetry run python \
  benchmarks/native_event/benchmark_phase77_3_reactive_closure.py \
  --profile standard
```

The artifact separates lightweight and Python-heavy strategies, sequential and R3B schedules, callback counts, candidate-fold bar visits, and process RSS/PSS where the COW worker is safe. It is not a claim that arbitrary callbacks, generic WFO, portfolio/package WFO, or `backend="auto"` are Rust-promoted.

For signal WFO, see [Public prepared-native WFO scoring](native_prepared_wfo_public.md). For runtime semantics, see [Rust native-event full contract](native_event_rust_full_contract.md).
