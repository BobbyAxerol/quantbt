# Causal Walk-Forward Guide

This guide explains how to choose a QuantBT walk-forward schedule when the
question is not just "which parameters score best?", but "were the reported
outer OOS results genuinely unavailable when those parameters were chosen?"

It complements the full [methodology](walkforward_methodology_vi.md) and the
complete [endpoint reference](endpoint.md#walk-forward). Start here when
selecting a schedule for a notebook, service, or stakeholder report.

## Install

The base package can run ordinary backtests. Parameter search requires the
declared optional dependency group:

```bash
pip install "quantbt-engine[optimization]==1.0.8"
```

The public import remains unchanged:

```python
from quantbt import QuantBTEndpoint
```

## Terms

- **Outer IS**: the history available when a fold makes a decision.
- **Outer OOS**: the next unseen interval used to evaluate that decision.
- **Inner IS/OOS**: historical sub-folds created *inside* one outer IS window.
- **Selection-adjusted OOS**: OOS whose metrics helped choose a candidate. It
  is useful research evidence but is not an untouched validation result.

The strategy remains responsible for causal features and signal construction.
QuantBT bounds the data supplied to a fold, but it cannot infer whether an
arbitrary indicator implementation itself uses future values.

## Choose The Schedule

`optimization_mode` defines the scoring and candidate-selection mathematics.
`optimization_schedule` defines when a new Optuna study is created.

| Mode and schedule | Parameter lifecycle | What the reported outer OOS means |
|---|---|---|
| Any supported mode + `global` | One retrospective study across all folds | Compatible legacy calibration. Do not present early folds as strict chronological validation. |
| `mode_1_decay` + `per_fold_decay` | One study per outer fold; same-fold OOS ranks frozen top-IS candidates by decay | Deliberately **selection-adjusted** OOS. |
| `mode_4_is_only_robust` + `per_fold_causal` | One study per outer fold; temporal and plateau evidence comes only from that fold's IS | Strict outer OOS, provided the strategy is causal. |
| `mode_1_decay` + `per_fold_causal` | One outer study per fold; decay is measured on explicit nested inner folds contained in outer IS | Strict outer OOS after parameters freeze. |

`mode_2_sbb`, `mode_3_flat_minima`, and `mode_5_full_robust` retain the
existing `global` lifecycle. In particular, Mode 5 is full-sample calibration,
not an OOS validation protocol.

## Recommended Strict Mode 1 Configuration

Use nested causal Mode 1 when decay is part of the research thesis but the
outer OOS must remain untouched. It costs more than global WFO: each outer fold
gets its own Optuna study, and every trial is evaluated over inner folds.

```python
from quantbt import QuantBTEndpoint


def strategy(data, params, train_index, test_index, fold):
    # `data` is bounded by QuantBT to the active scoring horizon. Keep all
    # feature construction causal and return only the requested target interval.
    signal = build_signal(data, params)
    return signal.reindex(test_index).fillna(0.0)


wfo = QuantBTEndpoint.walk_forward(
    strategy_class=strategy,
    split_mode="walk_forward_2022",
    split_frequency="quarterly",
    window_mode="rolling",
    train_window="365D",
    target_mode="pct_equity",
    optimization_mode="mode_1_decay",
    optimization_schedule="per_fold_causal",
    optimization_config={
        "scoring_backend": "endpoint",
        "candidate_selection_metric": "robust_decay",
        "top_is_fraction": 0.10,
        "inner_split_frequency": "quarterly",
        "inner_window_mode": "rolling",
        "inner_train_window": "180D",
        "inner_min_folds": 2,
        "scoring_trading_days": 365,
        "min_trades_per_year": 100,
        "trade_penalty_factor": 0.5,
        "use_numba": True,
    },
    optuna_trials=300,
    random_seed=42,
    initial_capital=20_000,
    leverage=5,
    alloc_per_trade=0.5,
    fee=0.0005,
    slippage=0.0001,
    use_pyramiding=False,
)

result = wfo.backtest(data=df, param_ranges=param_ranges)
```

For outer fold $i$, the engine creates inner folds $(d_{ij}, t_{ij})$ that
satisfy:

$$
t_{ij} \subset D_i, \qquad \max(t_{ij}) < \min(T_i),
$$

where $D_i$ is outer IS and $T_i$ is outer OOS. Optuna and
`robust_decay` use only these inner intervals. The selected parameters are
frozen before QuantBT emits the outer OOS target exactly once.

The four `inner_*` settings are mandatory for this route. QuantBT raises when
the outer IS cannot create at least `inner_min_folds`; it never silently falls
back to `per_fold_decay`.

## Strict Mode 4 Configuration

Use Mode 4 when selection must use IS evidence only. The selector combines
subperiod stability with a high-scoring parameter plateau and does not need
inner OOS decay:

```python
wfo = QuantBTEndpoint.walk_forward(
    strategy_class=strategy,
    split_mode="walk_forward_2022",
    split_frequency="quarterly",
    window_mode="rolling",
    train_window="365D",
    target_mode="pct_equity",
    optimization_mode="mode_4_is_only_robust",
    optimization_schedule="per_fold_causal",
    optimization_config={
        "scoring_backend": "endpoint",
        "candidate_selection_metric": "is_only_robust",
        "top_is_fraction": 0.10,
        "is_subperiods": 6,
        "scoring_trading_days": 365,
        "use_numba": True,
    },
    optuna_trials=300,
    initial_capital=20_000,
    leverage=5,
    alloc_per_trade=0.5,
    fee=0.0005,
)
```

## Read The Audit Metadata

Always archive the WFO metadata with the equity report:

```python
wf = result.metadata["walk_forward"]

display(wf["fold_table"])
display(wf["fold_selection_table"])
display(wf["best_trial"])
print(wf["validation_claim"])
print(wf["causality_claim"])
print(wf["chronological_validation_claim"])

# Available for Mode 1 + per_fold_causal.
display(wf["inner_fold_table"])
display(wf["inner_validation"])
```

For strict nested Mode 1, expect:

```text
validation_claim: strict_nested_fold_local_retraining
chronological_validation_claim: strict_outer_oos_after_frozen_selection
oos_used_for_selection: false
```

For `per_fold_decay`, expect
`chronological_validation_claim: selection_adjusted_outer_oos`; do not call
that OOS an untouched holdout. For `global`, the compatibility field
`validation_claim="walk_forward_oos"` remains, but
`chronological_validation_claim` explicitly records that the multi-fold
calibration is retrospective.

QuantBT stitches outer OOS targets chronologically and runs account accounting
once. The only supported boundary policy is
`fold_boundary_position_policy="carry"`: equity and positions continue through
the boundary, so the engine does not invent a reset, close/reopen, or extra fee.

## External Holdout And Live Evaluation

Strict causal WFO protects each outer OOS fold from parameter selection. It is
still good research practice to reserve a final external holdout that is never
passed to `.backtest(..., param_ranges=...)`. Freeze the latest completed-fold
parameters, build a causal signal on the holdout, and run a normal endpoint on
that separate period. This answers a different question: whether a policy that
survived WFO still behaves sensibly on data withheld from the entire WFO run.

## Repository Certification Gate

Maintainers can run the deterministic Phase 50 audit from a source checkout:

```bash
poetry run python tools/audit_phase50_wfo_causal.py \
  --output /tmp/quantbt-phase50-wfo-causal-audit.json
```

It verifies nested interval containment, untouched outer OOS, completed-prefix
invariance, fail-closed inner-history validation, and prepared/reference
account parity. It is a repository release tool, not an installed PyPI command.
