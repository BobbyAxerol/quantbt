# PERF-05 WFO Evaluation Reuse

## Purpose

PERF-05 removes one narrow source of repeated work in ordinary
`QuantBTEndpoint.walk_forward(...)`: an exact, already-complete prepared-native
candidate/fold score may be needed again during **report-only candidate
analysis** after Optuna has finished sampling. The runtime can reuse that
terminal metric mapping within the same WFO invocation instead of replaying the
same fresh-account execution.

This is not a new optimizer, selector, account model, or timing model. The
existing WFO engine remains authoritative for fold construction, strategy
lifecycle, Optuna ask/evaluate/tell order, mode-specific analysis, selection,
and the final stitched endpoint account.

## Eligibility

The cache is deliberately fail-closed. It is eligible only when all of the
following are true:

1. The request uses `scoring_backend="endpoint"`.
2. A run-local `PreparedWalkForwardContext` exists.
3. The endpoint scorer exposes the certified
   `run_local_terminal_metrics_v1` contract.
4. That contract declares a deterministic, fresh-account, prepared-native
   terminal score with no cross-run reuse and explicitly declares whether the
   diagnostic `context` label can affect terminal metrics.
5. The strategy lifecycle policy is `isolated_v1`.
6. The result is complete terminal metrics, not a partial, cancelled, pruned,
   transient-failure, or full-audit substitute.

Today this means the bounded public prepared-native scalar scorer beneath an
eligible single-symbol WFO route. Ordinary callback scoring, custom opaque
objectives, portfolio/package routes, generic order tapes, and reactive
strategies retain their existing authority. `wfo_execution_reuse="require"`
raises rather than silently widening the certified surface.

## Configuration

```python
endpoint = QuantBTEndpoint.walk_forward(
    strategy_class=my_strategy,
    target_mode="signal_notional",
    optimization_mode="mode_1_decay",
    optimization_config={
        "scoring_backend": "endpoint",
        "native_prepared_wfo": "require",
        "native_prepared_wfo_workers": 1,
        # PERF-05 controls. "auto" is the compatible default.
        "wfo_execution_reuse": "auto",       # off | auto | require
        "wfo_execution_reuse_max_entries": 4096,
        "wfo_execution_reuse_trace_limit": 2048,
    },
    target_runtime="rust",
)
```

`off` preserves the baseline scorer exactly. `auto` uses the cache only when
the narrow contract is available and otherwise records why it did not activate.
`require` is useful in a certified benchmark or release gate: it fails before
scoring if the route cannot meet the contract. Capacity and trace-limit changes
affect resource retention only; they never change candidate ordering, seeds,
selection mathematics, or final account construction.

## Execution And Analysis Graph

Each lookup records a versioned relationship:

```text
run_id -> trial_id -> candidate_id -> execution_id
                                  -> execution_attempt_id
execution_id -> analysis_id -> selection_id -> deployment_id
```

`execution_id` identifies the exact economic request. `execution_attempt_id`
is new for every caller, including a cache hit, so two duplicate Optuna trials
remain distinct auditable attempts. The semantic key includes the prepared
market/context and template identities, engine/numeric contract, strategy
fingerprint and params, signal digest, fold/time window/account policy, actual
study ID, actual study seed, trial/replicate ID, and completed terminal status.
It is run-local and is cleared before `.backtest()` returns.

The cache retains only a compact `str -> float` terminal metric mapping. It
does not retain strategy objects, pandas market frames, intent arrays,
order/fill ledgers, full paths, or a result that could impersonate an audit.

## Optuna And Causality

Adaptive Optuna evaluation is always **store-only**. The current public
terminal objective does not emit intermediate reports, but PERF-05 still never
reads a cache during adaptive sampling. Therefore it cannot skip a callback,
change a pruner decision, alter ask/tell order, or make a result from another
trial appear as a current trial.

After a trial completes, later candidate analysis can hit only the same
completed execution key. Per-fold studies carry their own `study_id` and
derived study seed in the key. This prevents a repeated trial number in a
different chronological study from becoming an accidental cross-study reuse.

The final stitched OOS result is still reconstructed by the established WFO
route. PERF-05 never concatenates fresh candidate equity curves and never turns
reset-flat candidate scores into a carried-account deployment claim.

## Mode Matrix

| Mode | Retained analysis inputs | PERF-05 behavior |
|---|---|---|
| `mode_1_decay` | IS/OOS metrics and decay components | Exact completed native scores may be reused during candidate analysis. |
| `mode_2_sbb` | IS path, deterministic bootstrap indices, replicate statistics | Existing proxy/resampling path remains authoritative; no native score cache. |
| `mode_3_flat_minima` | Candidate metrics and plateau coordinates | Exact completed native scores may be reused; plateau/selector logic is unchanged. |
| `mode_4_is_only_robust` | IS and subperiod metrics plus plateau data | Global selection can reuse exact completed native scores; strict `per_fold_causal` has no post-study exact replay, so `auto` disables it. Held-out OOS remains excluded from selection. |
| `mode_5_full_robust` | Full-IS robust components and plateau data | Current full-IS selector has no exact post-study replay, so `auto` disables the cache instead of paying lookup/store overhead. |

Mode 2 already keeps one candidate/fold return path and a replicate-level
vector; it does not construct a `replicates x bars x candidates` tensor merely
to calculate replicate statistics. Its bootstrap block rule, indices, RNG,
quantiles, NaN treatment, and reduction order are unchanged by PERF-05.

Reactive WFO keeps its dedicated prepared R1/R2/R3/R3B strategy contracts.
Replaying a captured command tape under changed fills is counterfactual
execution, not an automatic new reactive strategy result, so PERF-05 does not
apply this terminal-score cache to reactive decision state.

## Diagnostics

Inspect the normal public result:

```python
wf = result.metadata["walk_forward"]
runtime = wf["wfo_evaluation_runtime"]

runtime["resolved_policy"]
runtime["reason"]
runtime["cache_hits"]
runtime["cache_stores"]
runtime["terminal_score_bars_reused"]
runtime["adaptive_read_bypasses"]
runtime["attempt_ledger"]
```

The returned metadata is detached provenance. `cache_entries` is zero and
`cache_entries_released` is true after run teardown. The bounded
`attempt_ledger` preserves identities, stage, study/seed, hit/miss status and
reuse source while avoiding retention of terminal metric payloads themselves.

## Evidence And Rollback

```bash
PYTHONPATH=src .venv/bin/python -m pytest -q \
  tests/test_perf_05_wfo_evaluation_reuse.py \
  tests/test_phase49a_walkforward_schedules.py \
  tests/test_phase74_public_wfo_native.py

PYTHONPATH=src .venv/bin/python \
  benchmarks/native_event/benchmark_perf05_wfo_evaluation_reuse.py \
  --bars 2048 --trials 16 --repeats 15
```

The benchmark records zero-hit, bounded-LRU/mixed, and high-hit real public
Mode 1 lanes plus cache-off/on parity across all five WFO modes. It reports
full-facade timing separately from scorer timing and does not claim a generic
WFO speedup: Python strategy generation, Optuna control, selectors, final
reconstruction, and cold report adaptation remain real workload.

To roll back, set `wfo_execution_reuse="off"`. This keeps the same public
arguments, WFO modes, strategies, selectors, final account behavior, and trial
records while returning to the baseline scorer path.
