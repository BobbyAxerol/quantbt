# Nested Mode 1 Meta

## Availability

PRE-E06-03 enables only the owner-approved cohort
`nested_anchor_outer_IS_real_forward_v1` in local source. This is not in the
published 1.1.1/0.4.2 pair. Current-source core 1.1.2/native 0.4.3 wheel and sdist
installed parity PASS locally in [PRE-E06-06](PRE_E06_06_REPORT.md), including
all five nested targets and actual matured fit/rank;
remote and public release require separate approval. Meta remains off by default.

Supported targets: `signal_notional` (`single_signal`), `notional`, `unit`,
`pct_equity` (`%_equity`) and signed structural `dca_ladder`.
Mode 1 meta on portfolio, package, intrabar, callback, command and W3 routes
remains rejected. Their existing Mode 4 meta scope is unchanged.

## Stable Call

Use the existing `QuantBTEndpoint.walk_forward(...)` and
`.backtest(..., meta_history=context)`; no new endpoint or account engine.
The strategy still returns the original target Series on `test_index`.
The [runnable synthetic example](../../examples/wfo_meta_nested.py) supplies
an isolated strategy, aware calendar and explicit historical-replay clock.

```python
endpoint = QuantBTEndpoint.walk_forward(
    strategy_class=strategy,
    target_mode="pct_equity",
    split_mode="2022-01-01",
    split_frequency="quarterly",
    window_mode="rolling",
    train_window="365D",
    optimization_mode="mode_1_decay",
    optimization_schedule="per_fold_causal",
    optuna_trials=128,
    random_seed=731,
    optimization_config={
        "candidate_selection_metric": "robust_decay",
        "inner_split_frequency": "monthly",
        "inner_window_mode": "expanding",
        "inner_train_window": "180D",
        "inner_min_folds": 2,
        "scoring_backend": "endpoint",
        "use_scalar_trial_scoring": False,
        "native_prepared_wfo": "off",
        "meta_selection": {
            "mode": "shadow",
            "label_observer": True,
            "lambda_reg": 10.0,
            "min_matured_origins": 12,
            "q_hat_floor": -0.10,
        },
    },
    **account_kwargs,
)
result = endpoint.backtest(data=data, param_ranges=param_ranges, meta_history=context)
```

`account_kwargs`, strategy, data, ranges and `MetaHistoryContext` are caller-owned;
retain the [original information/accounting rules](INTEGRATION.md).
Too few inner folds, unsupported account/scoring contracts or late computation
fail explicitly; the module never shifts targets or backdates a seal.
Prepared scoring is optional and still needs the original scalar capability,
runtime, fee/slippage and strategy constraints. Ladder has no scalar-prepared
authority. Numeric Ridge Rust dispatch is independent of financial dispatch.

## What Runs

1. At each outer IS frontier, freeze the permitted compatible history snapshot.
2. Inside that IS, run the original adaptive inner-IS search. Evaluate the native
   shortlist on genuine inner validation and retain its exact decay winner.
3. Run one original full outer-IS evaluation per feasible completed trial and
   any separately evaluated exact anchor. These are auxiliary observations,
   not new Optuna trials/tells. Isolate their RNG and fresh strategy/account state.
4. Fit the unchanged origin-sum Ridge from past matured real-forward tasks.
   Rank the entire current eligible pool, apply predicted-Q guard and tie rule,
   then seal before the first outer-forward action.
5. Off executes the original native route without capture; shadow executes
   the native inner-decay winner; active executes the actual meta choice or
   documented fallback. Each uses the existing params-by-fold account path.
6. After sealing, the independent observer can acquire original real-forward
   labels. Labels published during search cannot enter its frozen snapshot.

The native objective is penalized inner-validation decay, not raw outer Sharpe.
The cohort's unchanged target is:

\[
Y_{k\theta}=(SR_{\mathrm{outer\ IS},k}(\theta)
-SR_{\mathrm{outer\ forward},k}(\theta))
-(SR_{\mathrm{outer\ IS},k}(a_k)-SR_{\mathrm{outer\ forward},k}(a_k)).
\]

The native anchor is the exact inner-decay winner, not the best raw-IS trial.
Mode 4 origins and different inner/decay policies belong to different families.

## Audit And Costs

Read `result.metadata["walk_forward"]["meta_selection"]`. Each record includes
cohort/family/snapshot, native inner objective and diagnostics, selected raw
outer-IS observation, prediction/guard, applied params, clocks, observer and
`auxiliary_outer_is_evaluations` / `auxiliary_outer_is_seconds`.

For a meta winner outside the actually scored inner shortlist,
`selected_inner_validation_evaluated=False` and its inner-validation values
are `None`; required legacy floating fields use `NaN`. No anchor metric is
copied onto that trial. `native_inner_diagnostics` retains trial/params/metrics
for the actual original shortlist.

Active `fold_selection_table` adds explicit raw outer-IS and inner columns.
Legacy `candidate_is_metric` remains an inner-train aggregate;
`candidate_oos_metric` is post-selection outer-forward penalized performance.
They are not the raw meta target. Independent observer reset accounts are
diagnostics, not equities concatenated into the final continuous account.

Full outer-IS observations cost extra financial evaluations. No purity shortcut
or cached stochastic strategy reuse is inferred. Shadow therefore is not free;
off incurs no such work. Existing prepared immutable market/calendar ownership
and batched Ridge numeric runtime are reused. See [the local report](PRE_E06_03_REPORT.md)
for measured software scope; neither conformance nor a predicted score guarantees
lower realized decay or better returns.

## References

- [Approved nested specification](ADDITIONAL_METHODS_REVIEW.md#proposal-a-nested-mode-1).
- [Phase plan](../../upgrade/implement.md#qms-pre-e06-03).
- [Unchanged math](../../upgrade/QUANTBT_1_1_1_META_SELECTION_AND_SAMPLER_MODULE_GUIDE_V1_1_VI.md#s5),
  [availability clocks](../../upgrade/QUANTBT_1_1_1_META_SELECTION_AND_SAMPLER_MODULE_GUIDE_V1_1_VI.md#s6)
  and [prepared ownership](../../upgrade/QUANTBT_1_1_1_META_SELECTION_AND_SAMPLER_MODULE_GUIDE_V1_1_VI.md#s8).
