# Public Causal Meta-Selection

## Availability And Scope

Implemented through QMS-08 and local closure on `feat/meta-selection-samplers`, not yet published.
Released core/native remain `1.1.1` / `0.4.2`. The public entry remains
`QuantBTEndpoint.walk_forward`; meta is an optional selector, not a new
backtest endpoint, financial engine, WFO mode, or order dispatcher.

Next pair `1.1.2 / 0.4.3` is approved for preparation only, including the
compiled numeric/witness capabilities in ordinary builds. See the
[release handoff](RELEASE_HANDOFF.md); missing-capability behavior documented
for published 0.4.2 below is historical, not a limitation of the prepared wheel.

Supported opt-in route:

- `mode_4_is_only_robust` with `optimization_schedule="per_fold_causal"`.
- Scalar `signal_notional` or `pct_equity`, aware unique exact calendar.
- `scoring_backend="endpoint"`, authoritative original-result or prepared score witness.
- Reference: `use_scalar_trial_scoring=False`, `native_prepared_wfo="off"`.
- Prepared: `native_prepared_wfo="auto" | "require"` and qualified native witness;
  existing `prepared_wfo_strategy="off" | "auto" | "require"` stays independent.
- `strategy_lifecycle_policy="isolated_v1"`, final `carry_position` account.
- Optimizing `param_ranges`, not a fixed-params run.

The original-result scorer provides authoritative raw metric witnesses without
requiring full order-audit reports. QMS-06 qualifies prepared scalar W0/W1/W2
adapters, using the existing runtime/cache and the same selection hook. Numeric
Rust dispatch remains independent of financial backend/prepared-WFO selection.
The local debt-closure extension adds W3 sequential/reset-flat meta below.
Ordinary meta-off W3 remains unchanged; its account is not a scalar target proxy.

Other modes and schedules remain unsupported for meta. The owner-approved
[C01 methodology review](ADDITIONAL_METHODS_REVIEW.md) and
[spec/test report](QMSC01_REPORT.md) do not activate them. In particular, default
Mode 2 final robust_decay reranking uses real OOS despite its legacy top-level
false flag; the review records that provenance gap separately from its IS-only
synthetic adaptive objective.

## W3 Sequential Meta

Use the existing `prepare_reactive_walk_forward` boundary and pass typed
`meta_history` to its `.backtest(...)`, just as for scalar WFO. No sixth mode or
new financial engine is introduced. The factory follows the existing prepared
reactive strategy protocol, including fresh candidate/task state and fill feedback.

```python
from dataclasses import replace

# endpoint, data, strategy_factory, context and existing_config are caller-owned.
config = replace(
    existing_config,
    optimization_mode="mode_4_is_only_robust",
    optimization_schedule="per_fold_causal",
    candidate_selection_metric="is_only_robust",
    scoring_backend="endpoint",
    calendar_contract="exact_v2",
    strategy_lifecycle_policy="isolated_v1",
    fold_account_policy="reset_flat",
    fold_boundary_position_policy="reset_flat",
    meta_selection={"mode": "active", "label_observer": True},
)
runtime = endpoint.prepare_reactive_walk_forward(
    data=data, strategy_factory=strategy_factory,
    walkforward_config=config, symbols=["BTCUSDT"],
)
try:
    result = runtime.backtest(param_ranges=param_ranges, meta_history=context)
finally:
    runtime.close()
```

The endpoint must be `native_event_strategy`, `native_backend="rust"` and an
existing supported numeric reactive co-runtime. C02 locally qualifies
`worker_mode="inprocess"` or safe Linux fork/COW `"process"`, with
`optimizer_schedule="certified_sequential_v1"`. Original-result runs honor
native deadlines/cancellation at completed-account-bar safe points; a blocking
Python callback is not hard-preemptible by a native deadline. Fixed/adaptive
public meta batches remain rejected. Their original-pass witness primitive is
qualified separately, without enabling global meta or a new sampler schedule.
See [transport/account contracts](W3_TRANSPORT_AND_ACCOUNT_CONTRACTS.md) for
exact binding, ownership, failure and proposed carry/multi-symbol semantics.

One native execution retains minimal original equity/position/return buffers and
the existing streaming score in the same pass. Optuna receives the **unchanged
native scalar objective**, while meta receives authoritative original daily,
ddof=1 metric validity/witnesses. No replay, scalar-placeholder validity, shared
account or strategy state is used. The full valid IS pool is captured before
selection; the frozen panel is evaluated only after sealing. Each task has a
distinct reactive/reset-flat compatibility family, so scalar carry-position
archives cannot be substituted.

`result.fold_results`, `segmented_equity` and `fold_metrics()` remain reset-flat;
there is no compounded synthetic equity. Metadata describes actual selection,
history cutoffs, witnesses, original-result cost and separate account authority.
This is a local feature-branch qualification, not public wheel or live approval.
`meta_selection["witness_transport"]` records actual worker mode, verified packet
count/bytes, zero market IPC/replays and temporary original-window path retention.
Runtime worker telemetry retains actual generation, memory and cleanup.
Carry and shared-account multi-symbol meta W3 remain fail-closed before strategy
or financial execution; their proposal tests are not runtime certification.

## Witness Reuse And Numeric Dispatch

When original-result meta scoring uses the shared prepared WFO context, a bounded
run-owned witness cache reuses canonical calendar/header SHA state and prefix
market hashes. Actual financial buffers are still hashed every evaluation.
Funding Series, schema/dtypes, input signatures, capital and metric/economic
contracts remain bound. Unknown/copied frames use the uncached reference path;
source/funding mutation raises. Owners are validated and cleared on exit.
`use_prepared_meta_witness=False` in optimization metadata retains the reference
lane for differential tests; this is not an evaluation cache or RNG shortcut.

Meta numeric `auto` keeps qualified Rust for transforms/ranks and favorable fit
geometry. Only previously measured large/high-dimensional geometry classes are
probed; three parity/timing probes per bounded bucket may select NumPy/BLAS if
fit is more than 10% faster. Probe FFI/copy bytes/time and selected block/reason
are reported. `require` remains Rust-only; `reference` remains independent.
Existing whole-reference decision/floor/tie guards are preserved.
`thread_telemetry` separates configured caps, environment and actually loaded
BLAS/OpenMP/Numba pools; unknown native concurrency remains unknown. A reported
configuration is not proof that a loaded pool obeys it.

## Prepared Capability And Policy

| Financial policy with meta enabled | Behavior |
|---|---|
| `off` | Original-result endpoint scoring; no native witness request |
| `auto` | Compatible prepared witness when available; otherwise recorded fallback to original-result scoring, not a placeholder scalar |
| `require` | Qualified prepared witness or explicit failure before search; no timing/economic substitution |

For a prepared run, use `target_runtime="rust"`, one symbol, 365-day
annualization, at least three distinct UTC days per score window, and the
existing `close_target_v2_same_close` contract. Next-open, portfolio/package
and reactive-order execution are not coerced into this scalar path.
`pct_equity` keeps its existing stricter fee/slippage/require guards; see
[the prepared-native matrix](../native_prepared_wfo_public.md).

Published native 0.4.2 lacks the QMS prepared witness. QMS-06 executed a local
Linux x86_64 / CPython 3.12 candidate, **0.4.3.dev2**, with off-by-default
`qms-prepared-witness-candidate` and `qms-numeric-candidate` features.
No installed package, public version or global backend was replaced. The
candidate build/test injection is evidence tooling, not a new public override.
On the published wheel `auto` records `META_METRIC_SUPPORT_MISSING` and
falls back; `require` fails. QMS-08 owns public artifact/version qualification.

Witness ABI `same-pass-ddof1-daily-first-mark-v1` returns typed, detached,
read-only sample-count/variance/first-mark/liquidation/metric-version/annualization
columns from the **original native run**. It neither recomputes execution nor
uses the old placeholder `volatility=0` to declare validity. Invalid/censored
scores cannot become invented training labels. Reset/clear cannot make old
request bindings valid; already returned detached arrays remain safe to read.

W1/W2 must declare `causal_parameter_independent_v1` and keep the same full
candidate pool. Sequential TPE is unchanged: W2 preparation does not turn this
route into a fixed-candidate batch schedule. Boundary counters distinguish
`execute_score` batches, witness materializations and meta numeric calls.

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

`records`, `tasks`, `models`, `snapshots`, `config_digest`, observer counters and timing belong
to the additive research sidecar. To export artifacts use the strict
[model/decision bundles](MODEL.md#artifacts-and-restore) or the complete
[portable host handoff](HANDOFF.md); metadata is not a weights-only checkpoint
or a live order instruction. Handoff export does not fill an activation clock
from the backtest fold start and does not reset any state.

Financial authority remains `existing_continuous_stitched_target_account`:
stitch OOS targets, then run one account with existing timing, trade deltas,
fees, slippage, funding and boundary carry. Do not concatenate reset diagnostic
equities or treat their Sharpe as a stitched-account Sharpe. Existing metrics,
plots and report consumers continue to use the original result.

Unsupported routes/policies, missing typed history, changed schemas, invalid
clocks and `require` without qualified native blocks fail explicitly. The
published native 0.4.2 has no QMS numeric block. QMS-04's actual 0.4.3.dev1
candidate was tested via a private module handle; it is not a new public release.

See [QMS-05 historical certification](QMS05_REPORT.md),
[QMS-06 prepared/handoff report](QMS06_REPORT.md) and the
[unified plan](../../upgrade/implement.md#qms-06). Owner/W3-scope acceptance
is separate from technical parity. Numeric optimization and final
economic/public-wheel qualification remain QMS-07/08; no speed, edge or live
deployment promotion is implied.
