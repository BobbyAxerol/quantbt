# Public Causal Meta-Selection

## Availability And Scope

Implemented in QMS-05 on `feat/meta-selection-samplers`, not yet published.
Released core/native remain `1.1.1` / `0.4.2`. The public entry remains
`QuantBTEndpoint.walk_forward`; meta is an optional selector, not a new
backtest endpoint, financial engine, WFO mode, or order dispatcher.

Supported opt-in route:

- `mode_4_is_only_robust` with `optimization_schedule="per_fold_causal"`.
- Scalar `signal_notional` or `pct_equity`, aware unique exact calendar.
- `scoring_backend="endpoint"`, `use_scalar_trial_scoring=False`.
- `native_prepared_wfo="off"`, `prepared_wfo_strategy="off"`.
- `strategy_lifecycle_policy="isolated_v1"`, final `carry_position` account.
- Optimizing `param_ranges`, not a fixed-params run.

The original-result scorer provides authoritative raw metric witnesses without
requiring full order-audit reports. Prepared/native scalar and reactive W3
qualification are explicitly QMS-06 work, not silently enabled here. Numeric
Rust dispatch is independent of financial backend/prepared-WFO selection.

## Call Contract

Static policy belongs in `optimization_config["meta_selection"]`. Bind the
runtime context through the **keyword-only** `backtest(meta_history=...)`.
Do not put mutable history, a provider, clock, database URI or native handle
inside serialized config. Existing calls without meta keep their old behavior.

```python
from quantbt import QuantBTEndpoint
from quantbt.optimization.meta_selection.config import MetaHistoryContext
from quantbt.optimization.meta_selection.history import MetaHistory

history = MetaHistory(max_revisions=256)
context = MetaHistoryContext(
    history=history,
    corpus_id="my-reviewed-corpus",
    instrument_id="ETHUSDT-linear-perpetual",
    timeframe="1h",
    run_id="research-run-001",
)

bt = QuantBTEndpoint.walk_forward(
    strategy_class=strategy,
    split_mode="2021-01-01",
    split_frequency="quarterly",
    window_mode="expanding",
    target_mode="pct_equity",
    optimization_mode="mode_4_is_only_robust",
    optimization_schedule="per_fold_causal",
    optimization_config={
        "scoring_backend": "endpoint",
        "use_scalar_trial_scoring": False,
        "native_prepared_wfo": "off",
        "meta_selection": {
            "mode": "shadow",
            "label_observer": True,
        },
    },
    optuna_trials=128,
    random_seed=42,
    initial_capital=20_000,
    alloc_per_trade=0.5,
    leverage=3,
    fee_rate=0.0005,  # canonical one-way
    use_funding=False,
)
result = bt.backtest(data=data, param_ranges=param_ranges, meta_history=context)
meta = result.metadata["walk_forward"]["meta_selection"]
records = meta["records"]
```

`data` and `strategy` are the caller's existing market tape and causal scalar
signal function. Specify execution timing and funding according to that alpha;
meta does not infer or override them. A context's instrument/timeframe/corpus
identities and permissions must be declared accurately by the caller.

Use the executable public SMA demonstration for a complete synthetic example:

```bash
.venv/bin/python -m examples.wfo_meta_selection --mode shadow
.venv/bin/python -m examples.wfo_meta_selection --mode active --demo-support
```

The first keeps the real twelve-origin default. `--demo-support` explicitly
reduces it to one for engineering smoke only, not statistical acceptance.

## Modes And Defaults

| Setting | Default | Meaning |
|---|---|---|
| `mode` | `off` | `off`, `shadow`, `active`; omitted/off has no history/observer/extra RNG work or meta sidecar |
| `learner` | `ridge_origin_sum_v1` | Exact implemented origin-sum Ridge, no intercept |
| `lambda_reg` | `10.0` | Ridge regularizer in the declared origin-sum units |
| `min_matured_origins` | `12` | Independent valid non-anchor support origins; explicit overrides retained |
| `q_hat_floor` | `-0.10` | Predicted relative Sharpe-quality floor, not statistical noninferiority |
| `tie_tolerance` | `1e-10` | Fixed-minimum tie set, then parameter distance and canonical identities |
| `native_batch_policy` | `auto` | `auto`, `require`, `reference`; missing baseline capability falls back observably |
| `label_observer` | `False` | Opt-in post-seal counterfactual label acquisition; adds financial work |
| `reporting_lag_seconds` | `1.0` | Nonnegative terminal publication lag; measured observer completion is added |
| `full_ranking` | `False` | Optional cold full ranking; all inference scores remain available |
| `max_folds` | `256` | Bounded retained fold decisions; does not silently truncate a run |
| `schema_version` | `qms-public-policy-v1` | Strict closed policy schema; unknown fields fail |

Shadow exports a learned proposal but executes the exact native anchor. Active
executes the proposed candidate, or native anchor on a documented fallback.
No downstream raw-IS floor restores a lower-IS winner to the native anchor.
Sampler configuration remains independent and uses the shared QMS-02 bridge.

The meta config has a separate digest. It is deliberately not inserted into the
legacy strategy execution seed hash: merely enabling shadow must not change
native stochastic search/strategy behavior. Native objectives and trial/candidate
tables are not rewritten with predicted scores.

## Selection And Information Boundary

For every fold:

1. Freeze an authorized, compatible history snapshot at the last IS observation
   **before** Optuna starts. A label published during search cannot enter it.
2. Run the unchanged native Mode-4 study/plateau selector. Capture all eligible
   current IS evaluations before compaction, not just replayed top candidates.
3. If a centroid anchor lacks its own IS witness, evaluate those exact params
   once on IS within the existing evaluator lifetime. Charge this extra work.
4. Fit on compatible past matured labels, predict/guard the whole current pool,
   then seal the actual decision and frozen observer panel before OOS action.
5. Put actual selected params in `params_by_fold`, generate that OOS signal and
   pass the stitched targets to the existing continuous account engine.
6. Only after seal, optional isolated counterfactual accounts observe forward
   outcomes. Append complete immutable terminal revisions with availability.

Compatibility includes strategy/schema, nominal windows, warmup/purge/embargo,
raw metric/economics, native anchor policy/constraints, sampler/seed/budget/
warm-start policy and diagnostic/final account policy. Changed contracts cannot
silently reuse an older family's labels. Strategy/policy code should declare a
version when captured configuration changes beyond the shared code fingerprint.

The model uses signed relative decay and predicted-Q guarding described in
[MODEL.md](MODEL.md). It does not promise improved future Sharpe.

## Observer And Clocks

`MetaHistoryContext` owns explicit corpus/cohort/exposure permissions. Public
replay writes `historical_counterfactual` / `research_only`; it never converts
them into observed-live outcomes. External reviewed imports retain their source
and review provenance. Self-hashed payloads do not authorize history or restore.

Counterfactual candidates start fresh reset-flat diagnostic accounts. Existing
strategy lifecycle makes independent strategy instances; NumPy/Python global
RNG streams are saved/restored around observer and centroid acquisition. User
callbacks must still obey the isolated-strategy contract: arbitrary hidden
mutable closures, external I/O or private RNG state are not made causal by a
config flag. Failures/no variance/censoring get terminal dispositions, not fake
zero Sharpe training labels. A full revision must be available before it enters
a later snapshot; observer completion plus declared lag are charged.

Consequently an immediately following quarterly cutoff may not yet see the
just-finished fold's label. This is deliberate, not an off-by-one workaround.
Earlier sealed decisions are never retrained retrospectively with these labels.

`information_as_of`, `search_completed_at`, `fit_completed_at`,
`decision_sealed_at`, `ready_at`, `effective_at` and `wall_generated_at` differ.
Default historical replay maps measured elapsed work from the IS cutoff and
records separate wall generation. An optional `clock(fold, stage, elapsed)`
declares explicit historical completion times; monotonicity and readiness before
the first OOS action are enforced. Completion that misses that action raises
`META_CLOCK_UNSUPPORTED`, without backdating or silently shifting targets.
Neither replay clock certifies historical live deployment or sends broker orders.

## Metadata And Accounting

Each sidecar record distinguishes raw-best, native-selected, meta-proposed and
actual-selected candidate/evaluation IDs, native params/objective/raw IS, actual
params/trial, exact snapshot/revision references, model/proposal and numeric backend.
Active `fold_selection_table` and `best_trial.selection_metadata` also retain
native causality separately from the actual final-policy/usage fields. Shadow
keeps those native tables intact; its learned proposal is sidecar-only.

- `current_outer_oos_used_for_selection=False` always on this qualified route.
- Active learned choice: `past_matured_forward_used_for_selection=True`, even
  if the model chooses the native anchor. Final policy is adaptive meta-selection,
  not a stock IS-only claim.
- Cold/OOD/invalid-metric fallback: actual final policy stays native and past
  forward usage for actual selection is false.
- Shadow: actual past-forward usage remains false; the proposal's historical
  usage is separately recorded as `meta_proposal_uses_past_matured_forward`.

`records`, `tasks`, `models`, `config_digest`, observer counters and timing belong
to the additive research sidecar. To export artifacts use the strict
[model/decision bundles](MODEL.md#artifacts-and-restore); metadata is not a
weights-only checkpoint or a live order instruction.

Financial authority remains `existing_continuous_stitched_target_account`:
stitch OOS targets, then run one account with existing timing, trade deltas,
fees, slippage, funding and boundary carry. Do not concatenate reset diagnostic
equities or treat their Sharpe as a stitched-account Sharpe. Existing metrics,
plots and report consumers continue to use the original result.

Unsupported routes/policies, missing typed history, changed schemas, invalid
clocks and `require` without qualified native blocks fail explicitly. The
published native 0.4.2 has no QMS numeric block. QMS-04's actual 0.4.3.dev1
candidate was tested via a private module handle; it is not a new public release.

See [QMS-05 certification](QMS05_REPORT.md) and the
[unified plan](../../upgrade/implement.md#qms-05). Prepared/portable-host gates,
numeric optimization and final economic/wheel qualification remain the separately
registered QMS-06/07/08 phases; this page does not advertise them as complete.
