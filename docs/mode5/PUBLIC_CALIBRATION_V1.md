# Public Diagnostics-First Mode 5

## Entry And Scope

This is an **opt-in full-development calibration**, not independent OOS proof
or deployment permission. Existing `QuantBTEndpoint.walk_forward(...)` calls,
Modes 1..4/meta and legacy Mode 5 retain their defaults. Changing a sampler
alone does not activate diagnostics-first selection or meta learning.

Use `optimization_config={"mode5_calibration": calibration, ...}` where
`calibration` is a `quantbt.mode5.Mode5Calibration`. The implementation is
canonical inside the installed package; `tools/mode5_*` research imports are
compatibility aliases, not a second implementation of the science.

The source-local [qualification report](M5_10_PUBLIC_RUNTIME_REPORT.md) separates
public synthetic search, five real fixed-coordinate integration controls and
future economic studies. See the
[detailed guide](../../upgrade/QUANTBT_MODE5_UPGRADE_V1_DIAGNOSTICS_FIRST_GUIDE_VI.md#phase-m5-10--public-mode5-binding-inherited-samplers-và-prepared-runtime).

## Freeze Before Search

1. Supply original data/strategy/account or an existing financial endpoint.
   Diagnose that exact alpha, data, economics and effective parameter schema.
   Do not convert old Mode 4 scalar objectives into new Mode 5 observations.
2. Register development environment windows with `CalibrationWindow` and
   `AccessWitness`. Pin the UTC bar duration, account currency, 365/252-day
   convention, return/tail/drawdown preferences and quality/support thresholds.
3. Use `calibration_binding(...)` to freeze windows, `FrozenReference`, shared
   `SamplerConfig`, metrics, selection preferences, local numeric probes,
   batch size and any **coordinate-only** warm starts. Use
   `calibration_context(...)` to bind the strategy, full market/funding content,
   economics, schema, roles, metrics, reference and binding identity.
4. Verify diagnostic evidence using `EvidenceCatalog`; create/review a `Dossier`
   and eligible `CalibrationPlan.search(...)`. Write the binding identity into
   `recipe.retention.runtime_binding_identity` **before** the plan is sealed.
   `GovernanceLog.seal_dossier(...)` must precede `seal_plan(...)` and search.
5. Pass the typed `Mode5Calibration(dossier, plan, catalog, journal, binding)`
   into the existing WFO endpoint. Runtime preflight rechecks bytes, rights,
   maturity, plan chronology and exact data/economics/schema/RNG configuration.
   A `DEFER_CALIBRATION` plan grants zero search authority.

Diagnostic evidence/approvals are inputs, not created by the runtime helper.
The five M5-09 real plans remain deferred; synthetic software fixtures do not
change them. JSON recipes should use
`NormalizedSearchSpace(ranges).portable_ranges()` **before sealing** to retain
numeric distribution kinds and conditional/fixed coordinates. A JSON numeric
list is not silently reinterpreted as a `(low, high, step)` distribution.

The runtime currently recognizes `contract_id` provenance in support,
constraints, incumbent and failure sections; their quantitative policies are
frozen in the binding. Extra unsupported policy fields fail explicitly rather
than being ignored. Probe design is `no_local_probes_v1` or
`schema_numeric_offsets_v1`; required probes consume a separately recorded
budget and execute the same original financial endpoint.

## Stable Call

With an already verified `calibration` and matching strategy/account/data:

```python
from quantbt import QuantBTEndpoint
from quantbt.optimization import SamplerConfig

recipe = calibration.plan.record.data["recipe"]
binding = calibration.binding.data
endpoint = QuantBTEndpoint.walk_forward(
    strategy_class=strategy,
    target_mode="pct_equity",  # or a supported existing execution endpoint
    optimization_mode="mode_5_full_robust",
    optimization_schedule="global",
    split_frequency="single",
    optuna_trials=calibration.plan.record.data["search_budget"],
    random_seed=recipe["sampler"]["seeds"][0],
    optimization_config={
        "scoring_backend": "endpoint",
        "native_prepared_wfo": "off",
        "is_subperiods": 1,
        "use_prepared_scoring_cache": True,
        "sampler_config": SamplerConfig(**binding["sampler"]),
        "sampler_warm_start": binding["warm_start"],
        "mode5_calibration": calibration,
    },
    **account_kwargs,
)
result = endpoint.backtest(data=development, param_ranges=param_ranges)
audit = result.metadata["walk_forward"]["mode5_diagnostics_first"]
```

For typed event/command/intrabar output, retain the existing WFO strategy
adapter and pass `execution_endpoint=original_endpoint`. Its timing, sizing,
protection and accounting contract still owns execution. No new simulator is
introduced. The optional
[example](../../examples/mode5_calibration_optin.py) accepts an external
`build_calibration_inputs()` adapter and returns the endpoint, result and audit:

```bash
python examples/mode5_calibration_optin.py --adapter /path/to/reviewed_inputs.py
```

Private sources, market data, diagnostic files and journals remain external.
The example cannot grant evidence quality or auto-select a recipe.

## Selection And Samplers

Three explicit resolved selectors reuse the registered M5-07 formulas:
`full_dro_cvar`, `full_sam_basin`, `full_pareto_chebyshev`.
`full_alpha_adaptive_invariant` retains advisory evidence but requires an
explicit eligible researcher choice; it is not an automatic router.
SAM requires registered observed local probes; Pareto requires frozen typed
preferences. Every selected fixed vector is audited through the original
endpoint and compared to its search observations before use in the result.
`Mode5NoSelectionError.mode5_metadata` retains reasons/ledgers if no candidate
passes; no arbitrary best trial substitutes for `NO_SELECTION`.

Samplers use the shared WFO registry: `tpe_legacy`,
`tpe_multivariate_group`, supported `cmaes` and `sobol`. CMA mixed spaces must
reject or explicitly use independent fallback. Sobol reports actual startup,
QMC position, projection and duplicate references; a mixed panel is not claimed
to be an untouched balanced Sobol design. Conditional TPE respects active
dimensions. Configuration, seed and warm starts must match the sealed recipe.

`sequential_exact` asks/tells in order with batch size one. `fixed_batch` asks
the whole batch before ordered feedback, so its adaptive trajectory can differ.
Strategy callbacks remain serial; worker counts above one fail preflight.
The completed full-candidate objective is reported at step zero with
`NopPruner`; no adaptive partial-path pruning is implied. Failed/canceled batch
asks are terminated observably, not marked `COMPLETE` with a fabricated score.
This API does not claim resumable exact continuation of a partially completed
M5-10 run merely because the shared sampler has other continuation facilities.

## Measurement, Ownership And Audit

Account equity comes from the original endpoint. UTC daily account-return
inputs include explicit initial-capital baseline and partial-bucket coverage.
Utility, annualized daily Sharpe and PSR have separate typed units/fields;
utility is never substituted into `mean_is_sharpe`. Exact tail reduction and
frozen reference math reuse canonical M5 reducers. Bankruptcy, incomplete
support and undefined metrics retain invalid/pruned states, not epsilon scores.

Closed engine trade records are not closed multi-leg campaigns. Unsupported
campaign support is not inferred from exposure regimes or fake fills. The
legacy RSI route has no audited accepted-fill ledger; its unavailable counts
are not zero-fill claims.

Prepared market/calendar and original execution caches are reused within their
existing lifetime; independent candidates reset financial/strategy state.
Each calibration environment is an explicitly independent reset-flat observation;
the returned full-development account is a separate original-endpoint run. Do
not relabel reset observations as continuous calendar attribution or splice
their best equity paths. All returned input bars must fall within authorized
development witnesses, including explicitly authorized warmup history.
Terminal-only native scalar scoring is ineligible for this path because full
equity/daily/component/probe evidence is required. This does not disable an
eligible original Rust financial endpoint; arbitrary user callbacks remain
Python-owned. No per-trial `full_report()` is built. Required paths are retained
and canonical account reduction can use Numba. Selected replay asks for audit
on the original endpoint; unavailable ledger capability is reported honestly.

Read `status`, `decision`, `selected_params_digest`, `selected_audit`,
`trial_ledger`, `sampler`, `optimizer_schedule`, `batch_size`,
`candidate_sequence_equivalent_to_sequential`, `compute_bill`,
`validation_claim`, `meta_learning_activated` and `deployment_authorized`.
Elapsed billing includes failed work; actual observations, query attempts,
effective unique candidates and local probes are not independent sample size.
The runtime releases prepared/internal state on success and failure while
preserving cold result metadata. Data permissions are revalidated on reload.

## Migration And Limits

Without `mode5_calibration`, existing behavior and hashes remain unchanged.
To roll back, remove this optional entry; retain previous compatible artifacts
and the sealed audit. Formal scoped economics follow the
[M5-11 contract](ECONOMIC_CONTRACT_V1.md); read the
[approved finite-pilot findings](M5_11_ECONOMIC_REPORT.md) separately from
independent validation. Remote
matrix, final product qualification and any publication require later approval.
