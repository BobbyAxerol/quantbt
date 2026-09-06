# Public Prepared-Native WFO Scoring

## Purpose

Phase 74 makes normal `QuantBTEndpoint.walk_forward()` and
`train_test_split()` eligible for a narrow Rust prepared-evaluation route. It
accelerates repeated **fresh-account candidate/fold/scored-shard** evaluation
only. It does not replace fold construction, Optuna, mode-specific selection,
parameter provenance, or the one final continuous stitched account backtest.

The route is opt-in. Existing notebooks keep their historical W0 pandas
callback and endpoint scorer unless `native_prepared_wfo` is explicitly set.

```python
bt = QuantBTEndpoint.walk_forward(
    strategy_class=my_strategy,
    target_mode="signal_notional",
    optimization_mode="mode_1_decay",
    optimization_config={
        "scoring_backend": "endpoint",
        "native_prepared_wfo": "require",  # off | auto | require
        "native_prepared_wfo_workers": 1,
        "scoring_trading_days": 365,
    },
    target_runtime="rust",
)
result = bt.backtest(data=bars, param_ranges=param_ranges)
```

`"auto"` records a fallback reason and uses the historical endpoint scorer if
the request is outside the certified matrix. `"require"` fails before scoring;
it never silently substitutes a target proxy, timing convention, or Numba
route.

## Certified Matrix

| Dimension | Public prepared-native scope |
|---|---|
| Market | One canonical finite UTC OHLCV `DataFrame`; volume and funding enter the prepared signature |
| Symbols | One scalar symbol only |
| Target modes | `signal_notional`, `single_signal`, `notional`, `unit`; plus explicit transition-sized `pct_equity` / `%_equity` |
| Target clock | Existing close-target direct execution; no generic signal lag is introduced |
| Candidate account | Fresh account per scored candidate/fold/shard |
| Final account | Existing endpoint stitched continuous account, with its declared boundary policy |
| Annualization | `scoring_trading_days=365` only |
| Output | Scalar `Series` for native score; ordinary final result/report is unchanged |

Transition-sized `pct_equity` is a narrow explicit exception: it requires
`target_runtime="rust"`, `native_prepared_wfo="require"`, one symbol, and an
exact legacy/V2 fee/slippage configuration. Its Rust request owns transition
sizing and accounting, while the public result still exposes processed signal
weights and keeps accepted units under
`metadata["pct_equity_transition"]["accepted_positions"]`. `"auto"` preserves
the legacy route. Portfolio, basket, package/arbitrage, DCA/grid, generic order
tapes, and reactive lifecycle strategies retain their dedicated certified
routes; they are not coerced into this scalar target scorer.

```python
bt = QuantBTEndpoint.walk_forward(
    strategy_class=my_strategy,
    target_mode="pct_equity",
    optimization_mode="mode_4_is_only_robust",
    optimization_config={
        "scoring_backend": "endpoint",
        "native_prepared_wfo": "require",
        "scoring_trading_days": 365,
    },
    target_runtime="rust",
    fee=0.0004,
    fee_rate=0.0002,
    slippage=0.0001,
)
```

## Mode And Schedule Semantics

| Optimization mode | Public native-scoring behavior |
|---|---|
| `mode_1_decay` | Rust scores existing IS/OOS tasks; the current decay formula, penalties, candidate admission, and selector stay unchanged. `global`, `per_fold_decay`, and nested `per_fold_causal` preserve their documented meaning. |
| `mode_2_sbb` | The bounded path-resampling proxy remains authoritative. `auto` records `proxy_preserved`; `require` raises. No scalar-Sharpe replacement occurs. |
| `mode_3_flat_minima` | Rust supplies existing scorer metrics; Python retains trial rank, plateau/cluster construction, ties, medoid/centroid selection, and rerun behavior. |
| `mode_4_is_only_robust` | Rust scores current IS/subperiod tasks. Under `per_fold_causal`, selection remains current-fold IS-only. |
| `mode_5_full_robust` | Rust scores declared full-sample IS calibration. It is not relabelled as chronological OOS validation. |

The final OOS target is stitched once and passed to the ordinary endpoint
account engine once. QuantBT does **not** concatenate independent candidate
equity curves, reset capital at each fold, or infer a boundary close/reopen
event from target arrays.

For the explicit `%_equity` route, the single final stitched account is Rust
`pct_equity_transition_v1`, not a per-bar `EquityFraction` approximation.
The default public route remains legacy for compatibility.

## Optional W1/W2 Strategy Preparation

W0 is the existing callable signature:

```python
def strategy(data, params, train_index, test_index, fold) -> pd.Series: ...
```

An advanced alpha can cache only parameter-independent causal work once:

```python
class PreparedAlpha:
    causal_cache_contract = "causal_parameter_independent_v1"

    def prepare_wfo(self, *, data, folds, static_config):
        return PreparedSignals(data.index)

class PreparedSignals:
    causal_cache_contract = "causal_parameter_independent_v1"

    def generate(self, *, params, fold_id):  # W1
        return {"signal": full_tape_signal}

    def generate_batch(self, *, params_matrix, fold_id):  # W2
        return {"signal": full_tape_signal_matrix}
```

Enable it deliberately:

```python
optimization_config={
    "scoring_backend": "endpoint",
    "native_prepared_wfo": "require",
    "prepared_wfo_strategy": "require",      # off | auto | require
    "prepared_wfo_strategy_adapter": "auto", # auto | w1 | w2
}
```

The adapter receives one isolated preparation lifetime and a deep-copied market
snapshot. It accepts finite full-tape scalar signals only and projects the
exact requested timestamp range without shifting it. For a per-fold schedule,
the prepared object must declare
`causal_cache_contract="causal_parameter_independent_v1"`; otherwise it fails
closed. This makes the strategy-owned cache assumption visible instead of
turning it into an unearned engine causality claim.

The public default keeps certified sequential Optuna ask/evaluate/tell. Thus a
W2 adapter is called with one candidate per fold in this facade; it proves the
same typed generation contract but does not claim candidate-matrix throughput.
The explicit `NativeWfoRuntimeV2` is the advanced route for opt-in
`throughput_batch_v1`, whose TPE sequence has a separately declared sampling
contract.

## Audit And Diagnostics

Inspect the normal result metadata:

```python
wf = result.metadata["walk_forward"]
wf["native_prepared_wfo"]
wf["prepared_scoring_cache"]["native_prepared_wfo"]
wf["prepared_wfo_strategy"]
```

The entries report requested/resolved policy, fallback reason, market/template
signatures, batch/row/scored-bar counters, Rust boundary calls, score time,
fresh/final account policy, cache/runtime diagnostics, adapter calls,
causal-cache declaration, and close state. Fold/trial/candidate tables,
selected-parameter provenance, `show_metrics()`, `quick_plot()`, and
`full_report()` keep the normal public result surfaces.

The Rust score boundary returns typed scalar columns (`scalar_columns_v1`);
the public callback scorer adapts only the compact metrics it needs for the
existing objective. It does not create a per-row Python dataclass or dictionary
before Optuna's current reducer.

## Reproducible Evidence

After building the local native extension, run:

```bash
PYTHONPATH=src .venv/bin/python -m pytest -q tests/test_phase74_public_wfo_native.py
PYTHONPATH=src .venv/bin/python benchmarks/native_event/benchmark_phase74_public_wfo.py \
  --bars 2048 --trials 16 --repeats 5

PYTHONPATH=src .venv/bin/python \
  benchmarks/native_event/benchmark_phase77_2_pct_equity_wfo.py --profile standard
```

The recorded benchmark is a post-warm W0 Mode 1 global fixture with 2,048 bars
and 16 sequential trials. It reports strategy/Optuna-inclusive facade time and
the isolated candidate-score stage separately. It is evidence for this matrix,
not a generic callback, reactive, portfolio, package, or all-WFO claim. See
the generated [Phase 74 artifact](../benchmarks/native_event/results/phase74_public_wfo.md)
and [benchmark governance](performance/benchmarking.md).
