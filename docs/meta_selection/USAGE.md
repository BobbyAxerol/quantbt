# Meta-Selection User Guide

## Availability

QMS is an **opt-in feature-branch candidate**, not part of the already published
`quantbt-engine==1.1.1` / `quantbt-native==0.4.2` pair. QMS-08 qualifies private
build-only `1.1.1+qms08` / `0.4.3.dev4` artifacts; these are not public release
numbers. No feature becomes default and no release is authorized by testing.
The owner approved preparation of `1.1.2 / 0.4.3`, which builds those exports
by default but does not activate meta or publish them. See the
[release handoff](RELEASE_HANDOFF.md) and [qualification boundary](QUALIFICATION.md).

Use the same public `QuantBTEndpoint.walk_forward(...)` and `.backtest(...)`.
There is no new WFO endpoint, sixth mode, account engine, broker or live service.
Installing a native wheel does not make arbitrary Python strategies Rust-owned.

## Choose A Capability

| Request | What changes | Information used for actual selection |
|---|---|---|
| Existing call; meta omitted/off | Nothing; no archive, observer or meta sidecar | Existing mode/schedule |
| Sampler-only | Explicit shared search recipe | Existing objective/mode/schedule |
| Mode 4 causal + shadow | Proposal/diagnostics, native winner still executes | Stock native IS-only; proposal has distinct past-history scope |
| Mode 4 causal + active | Learned proposal or documented native fallback executes | Current IS and permitted matured historical forward labels when learned |

Meta supports **Mode 4 / `per_fold_causal`**, scalar `signal_notional`,
`pct_equity` and E03 software opt-ins `notional`, `unit`, `dca_ladder`, exact
aware calendar, isolated strategy lifecycle and final
carry-position account. A separate W3 sequential adapter supports reactive native
reset-flat windows; see [its exact contract](INTEGRATION.md#w3-sequential-meta).
E04 also admits bounded portfolio shared-account research opt-ins, described
in the [portfolio contract](DOMAIN_ADAPTER_CONTRACT.md#e04-portfolio-amendment).
Other modes/schedules and package/order target meta remain unsupported.
They keep their old behavior when meta is off. No request is silently converted.

Existing `walkforward_support_matrix()` now reports additive meta domain/ABI,
method/schedule, software/empirical status and pending gate columns. A financial
OOS route does not imply meta support. Read the [shared adapter contract](DOMAIN_ADAPTER_CONTRACT.md)
and [E02 local report](QMSE02_REPORT.md); no extra arguments are required on
already qualified routes, and pending domains still fail before search.

For new scalar sizing use the [E03 contract](DOMAIN_ADAPTER_CONTRACT.md#e03-scalar-amendment)
and [self-contained example](../../examples/wfo_meta_scalar.py). `single_signal`
and `%_equity` are canonical aliases with meta. Set endpoint scoring explicitly;
notional/unit meta-off defaults remain proxy. Legacy fee/slippage overrides must
agree (`fee_rate == fee / 2`). Structural ladder expects signed integer caps and
actual high/low, not units, execution orders or a dynamic grid. Software
validation is not an assertion that meta improves this alpha's forward returns.

For portfolio use the same constructor with `target_mode="portfolio"`,
`backend="native_portfolio"`, an explicit ordered `symbols` list and the
original `portfolio_mode`/`sizing` settings. Market input is `{symbol: OHLCFrame}`
on one aware exact calendar; strategy output is a position DataFrame with those
ordered columns, or an ordered `{symbol: Series}` mapping on the evaluation
index. Align asynchronous calendars yourself; preserve missing observations
as `NaN` under your existing price policy. Raw unaligned calendars are rejected,
not resampled. Keep `scoring_backend="endpoint"`,
`use_scalar_trial_scoring=False`, `native_prepared_wfo="off"`.
Prepared portfolio arrays are independent of scalar prepared Rust scoring.
See [the runnable example](../../examples/wfo_meta_portfolio.py) and
[E04 local qualification](QMSE04_REPORT.md). This is not empirical promotion.

Conditional Sobol and mixed/constrained representatives are under
[C05 methodology review](CONDITIONAL_GEOMETRY_REVIEW.md), not available public
capabilities. Keep using qualified sampler geometries and `flat_selector="medoid"`
where required; the review does not enable new config values or relax guards.

## Minimal Call

Keep your strategy, data, dates, parameter space and account contract. A strategy
returns the causal scalar signal expected by the existing target endpoint.

```python
from quantbt import QuantBTEndpoint
from quantbt.optimization.meta_selection.config import MetaHistoryContext
from quantbt.optimization.meta_selection.history import MetaHistory

history = MetaHistory(max_revisions=256)
context = MetaHistoryContext(
    history=history,
    corpus_id="reviewed-local-corpus",
    instrument_id="BTCUSDT-linear-perpetual",
    timeframe="1h",
    run_id="my-research-run",
)
bt = QuantBTEndpoint.walk_forward(
    strategy_class=strategy,
    split_mode="2021-01-01",
    split_frequency="quarterly",
    window_mode="expanding",
    target_mode="signal_notional",
    optimization_mode="mode_4_is_only_robust",
    optimization_schedule="per_fold_causal",
    optimization_config={
        "sampler_config": {"name": "tpe_legacy"},
        "scoring_backend": "endpoint",
        "use_scalar_trial_scoring": False,
        "native_prepared_wfo": "off",
        "meta_selection": {
            "mode": "shadow",
            "label_observer": True,
            "min_matured_origins": 12,
            "native_batch_policy": "auto",
        },
    },
    optuna_trials=128,
    optuna_early_stopping=None,
    random_seed=42,
    target_runtime="numba",
    initial_capital=20_000,
    alloc_per_trade=1_000,
    leverage=3,
    fee_rate=0.0005,  # one-way; preserve your own execution economics
    use_funding=False,
)
result = bt.backtest(data=data, param_ranges=param_ranges, meta_history=context)
bt.show_metrics(trading_days=365)
bt.quick_plot()
```

`strategy`, `data` and `param_ranges` are caller inputs; they are not fabricated
by the library. The complete runnable synthetic cases below exercise this
contract. `meta_history` is keyword-only runtime state, not serialized static
configuration. Do not put a database URI, mutable history or callback in
`optimization_config`.

Start with shadow to review histories, scores and proposed decisions. Change
only `meta_selection.mode` to active after your own research approval. Active
is not stock IS-only: permitted **past** matured forward outcomes inform the
model. The **current outer OOS is never** an input to current fit/rank.

## Independent Runtime Policies

| Policy | Control |
|---|---|
| `target_runtime` | Existing financial execution authority |
| `native_prepared_wfo` | Financial prepared scorer: off/auto/require |
| `prepared_wfo_strategy` | Existing W0/W1/W2 strategy preparation policy |
| `meta_selection.native_batch_policy` | Meta numerics: auto/require/reference |

Reference scoring uses `use_scalar_trial_scoring=False` and
`native_prepared_wfo="off"`. Prepared meta needs the original-pass metric witness,
not an old placeholder volatility scalar. Use qualified candidate pair,
`target_runtime="rust"`, one symbol, 365-day annualization, at least three distinct
UTC days per score window, and the existing `close_target_v2_same_close` contract.
Do not relabel this as next-open. `pct_equity` retains its separate cost/quantity
guards. See the [full prepared matrix](../native_prepared_wfo_public.md).

**Current candidate limitation:** the [E03 real study](QMSE03_REPORT.md#prepared-study-and-parity-blocker)
finds objective/selection drift after liquidation: native daily reduction skips
zero-base samples that the legacy metric retains. Full prepared notional matches
in that study; prepared unit does not. Other liquidation-capable requests may be
affected. Use original endpoint scoring with `native_prepared_wfo="off"` until
the bounded compatibility repair is approved and qualified. Current auto/require
does not detect this new mismatch. Installing the candidate or passing a small
consumer does not certify every bankrupt-tail trajectory.

Meta `auto` selects qualified native numeric batches when available, otherwise
records a NumPy fallback reason. `require` fails if capability/parity is missing;
`reference` explicitly selects the qualified NumPy path. On published native
0.4.2, meta numeric auto falls back and prepared meta auto uses original-result
scoring; corresponding require requests fail. The private candidate has both
capabilities. Mixed/high-dimensional fits can still favor BLAS; Rust-first is
not a promise that every matrix is faster. See [matched costs](QMS07_REPORT.md).

## Search Recipes

Use `optimization_config["sampler_config"]` without enabling meta:

```python
optimization_config = {
    "sampler_config": {"name": "tpe_multivariate_group"},
    # Keep your existing objective, schedule, scoring and account settings.
}
```

Recipes: `tpe_legacy`, `tpe_multivariate_group`, `cmaes`, `sobol`.
Omitted configuration preserves the historical sampler defaults. Multivariate
TPE is not inherently a better trading optimizer. CMA-ES mixed categorical
space requires explicit independent policy; otherwise preflight rejects it.
Conditional/boolean/fixed/integer/log-float fields retain exact effective
identities. Valid native kwargs and shared constraints/warm-start rules are in
[SAMPLERS.md](SAMPLERS.md). No adaptive sequential ask/tell is changed to a batch.
For prepared reactive strategies, C03 also qualifies these recipes through the
existing `WalkForwardConfig.sampler_config`; see the [W3/R3B scheduler matrix](W3_SAMPLER_SCHEDULES.md)
and [runnable example](../../examples/wfo_reactive_samplers.py). Batch proposals
require an explicit versioned contract; meta still requires Mode 4 causal
sequential reset-flat execution. This local addition is not yet published.

## Inspect The Decision

```python
wf = result.metadata["walk_forward"]
meta = wf["meta_selection"]
record = meta["records"][-1]
print(record["native_selected_params"], record["selected_params"])
print(record["final_selection_reason"], record["numeric_backend"])
assert record["selected_params"] == wf["params_by_fold"][record["fold_id"]]
```

Trace raw-best/native-anchor/meta-proposed/actual-selected IDs separately.
Do not assume native anchor is raw Sharpe maximum or that a same-anchor learned
decision did not use history. Review full eligible IS pool, exact snapshot/task
revision/model IDs, per-origin support/weights, and predicted guard/tie reasons.
Unknown config fields and incompatible history fail; they are not discarded.

The twelve-origin default counts independently valid **origins**, not seeds or
candidate rows. Cold start/native fallback is legitimate and explicitly marked.
`--demo-support` in examples reduces support to one only for engineering tests.
It does not provide economic acceptance or justify lower production support.

## Time And Account Boundaries

Snapshot information cutoff precedes search. Computation completion, decision
seal/readiness and first effective action have separate clocks. A label published
during search cannot enter that snapshot. Counterfactual observers run only after
seal in independent reset-flat diagnostic accounts and publish complete terminal
revisions after forward end plus lag/completion. Late revisions replace the
whole origin; earlier decisions remain immutable.

One existing account executes stitched actual OOS signals with its declared
position carry, fees, slippage, funding and margin. Diagnostic fold equity is
not concatenated into a new curve. Last-fold params are the last selected
deployment candidate, not evidence of a future return. Metrics/chart/report
methods still consume the original result.

For reviewed history import and host handoff, complete metric witnesses and
externally reviewed IDs are required. A hash detects corruption, not permission.
Export/restore does not place an order, reset a strategy, activate a controller
or certify live readiness. See [HANDOFF.md](HANDOFF.md).

## Runnable Cases

From a feature-branch checkout with its environment:

```bash
.venv/bin/python -m examples.wfo_meta_contract --case off
.venv/bin/python -m examples.wfo_meta_contract --case sampler
.venv/bin/python -m examples.wfo_meta_contract --case history
.venv/bin/python -m examples.wfo_meta_contract --case unsupported
.venv/bin/python -m examples.wfo_meta_selection --mode shadow
.venv/bin/python -m examples.wfo_meta_selection --mode active --demo-support
.venv/bin/python -m examples.wfo_meta_handoff --demo-support
```

`history` demonstrates strict reviewed JSON reconstruction with identical
snapshots; its explicit self-review is only for these synthetic records, not
an authorization pattern for an untrusted external archive. Native require and
missing-capability behavior are also exercised by the isolated installed consumer
in `tools/qms08_consumer.py`. Pure report regeneration is distinct from a host
selection revalidation: regeneration does not execute a model or account.

## Migration And Research Acceptance

No change is needed for existing alpha calls. New options are explicit; removing
`sampler_config`, `meta_selection` and `meta_history` restores the old path.
Never blindly load a new family's history after changing strategy, economics,
schema, nominal windows, sampler budget or label policy. Histories/artifacts
retain their actual versions and scoped permissions.

Software qualification is not a promise of economic gain. A separate registered
study needs >=128 attempted trials/cutoff, >=12 matured origins before assessment
and >=12 paired-valid locked evaluation folds; development folds are separate
if selecting recipes. Native and meta must use the same current pool. Signed
decay improvement must be decomposed into IS difference and actual forward
difference; lower IS alone is not forward retention. Preserve failed/undefined
folds and negative outcomes. See [methodology](../../methodology/walk_forward.md#17-qms-05-causal-meta-selection-feature-branch)
and [qualification](QUALIFICATION.md).
