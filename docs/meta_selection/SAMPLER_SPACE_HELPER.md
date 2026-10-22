# Optional Sampler-Space Helper

## Availability And Purpose

`prepare_sampler_space` is opt-in on the QMS feature branch, prepared for core
1.1.2. Neither WFO nor meta calls it automatically or requires it. No new
endpoint, sampler recipe or native dependency is introduced. Read the
[registered scope](../../upgrade/implement.md#qms-sh01) and
[shared sampler contract](SAMPLERS.md).

It assesses **declared schema compatibility**, not objective smoothness or
profitability. Numeric params can still produce discontinuous signals, fills
and Sharpe. It never executes an alpha, reads data or uses OOS outcomes to choose
a sampler. It is not a learned auto-sampler.

## One Reusable Plan

```python
from quantbt.optimization import prepare_sampler_space

space = prepare_sampler_space(
    param_ranges,
    preferred_sampler="cmaes",
    # Declare only genuine numerical distance/order, not integer mode IDs.
    numeric_parameters=("window", "rsi_length"),
)
display(space.assessment.metadata())

endpoint = QuantBTEndpoint.walk_forward(
    strategy_class=strategy,
    optimization_config=space.optimization_config(existing_optimization_config),
    **existing_wfo_account_and_split_kwargs,
)
result = endpoint.backtest(data=data, param_ranges=space.param_ranges)
```

Keep the actual account, split, mode/schedule, financial backend and strategy
wrapper. Run the complete [public example](../../examples/wfo_sampler_space.py):

```bash
python -m examples.wfo_sampler_space --sampler cmaes --trials 128
```

`optimization_config(base)` explicitly replaces only `sampler_config`, copying
the base mapping. It preserves supplied meta off/shadow/active settings and does
not create a meta policy. Separate experiments can prepare separate plans.
Every ordinary helper-free config remains valid.

## Conversion Rules

| Input | Default | Explicit numeric declaration |
|---|---|---|
| Numeric tuple or numeric schema | Existing numeric semantics | Same semantics |
| Uniformly spaced integer list/range | Categorical | Exact same integer low/high/step support |
| Irregular integer choices | Categorical | Reject; no added intermediate values |
| Float choices | Categorical | Require a numeric schema override; no guessed rounding |
| String/boolean choices | Original categories | Reject numeric declaration |
| Fixed numeric | Fixed, not a search dimension | Remains fixed |
| Fixed string/boolean | Fixed, not a search dimension | Reject numeric declaration |
| Conditional schema | Explicit `active_if` | Condition retained, never inferred |

Declared `[4, 8, 12]` becomes `low=4, high=12, step=4`, not a dense interval
including 5 or 6. `[4, 8, 13]` cannot be converted losslessly this way. Integer
strategy-mode IDs must not be declared numeric just because they are integers.

Support-preserving conversion **changes proposal geometry** relative to
categorical sampling. It is a caller-declared research choice, not a lossless
sampler-trajectory/performance optimization. Float overrides are deliberate
schema choices, not a promise to preserve arbitrary enumeration bit patterns.
Existing log/linear/step rules remain owned by the original schema and Optuna.

## Customize And Override

```python
space = prepare_sampler_space(
    param_ranges,
    parameter_overrides={
        "rate": {"kind": "float", "low": 0.001, "high": 0.1, "log": True},
    },
    fixed_params={"degree": 2},
    active_if={"atr_length": {"use_atr": True}},
    sampler_config={
        "name": "cmaes",
        "mixed_space_policy": "explicit_independent",
    },
)
```

Numeric/schema/condition override keys must exist in the actual ranges. Fixed
params follow existing precedence and may add constants. Parents must precede
conditional children. A condition override replaces the field's condition; an
empty mapping explicitly removes it. No flag-name convention/source inspection
is used. The helper cannot decide which structural params should be fixed.

`sampler_config` overrides the preferred recipe using existing policies/kwargs.
CMA `explicit_independent` does not jointly covariance-optimize categorical
and all conditional dimensions. Inspect actual relative/independent calls in
`result.metadata["walk_forward"]["sampler_studies"]`. One static numeric
dimension is flagged for this inspection, not labelled a guaranteed joint run.
Conditional Sobol accepts the existing explicit
`sobol_policy="conditional_numeric_latent_v1"`; no new conditional CMA engine
is added. See [conditional policies](CONDITIONAL_POLICIES.md).

Default `on_incompatible="raise"` rejects incompatible geometry without strategy
or financial work. To explicitly permit a compatible legacy-TPE alternative:

```python
space = prepare_sampler_space(
    param_ranges, preferred_sampler="cmaes", on_incompatible="recommend",
)
print(space.assessment.resolved_sampler)
print(space.assessment.requested_issue)
```

This is a compatibility alternative, not evidence of superior search. Invalid
explicit `sampler_config` still raises with `recommend`; caller overrides are
never silently replaced. Constructor kwargs/dependencies/fold seeds/constraints
remain checked by the original factory/WFO preflight, not by this helper.

## Output And Provenance

- `param_ranges` and `sampler_config`: defensive copies of prepared config.
- `assessment.metadata()`: requested/resolved recipe and reason; numeric,
  conditional, categorical/fixed blocks; explicit overrides; input/effective
  schema identities. No market or winning params are read.
- `decode(requested)`: existing effective-param validation/type normalization
  and omission of inactive values. Optional: WFO already sends effective params
  to the strategy, so no new wrapper is normally needed.

Integer schemas still reject `8.0`; no silent truncation is introduced. Labels
remain original strings/booleans. Use the **effective** schema identity for
warm-start/continuation; a changed numeric geometry cannot exactly resume the
old categorical study. Runtime history objects do not belong in static config.

## Validation And Evidence

Helper/manual configuration tests compare actual factory proposals and public
WFO/accounting, including meta off/shadow/active. Instrumentation clocks are
frozen only in unit fixtures for exact provenance comparison; financial engines
and learners are real. The helper adds no trial, archive I/O or RNG draw.

The registered diagnostic uses unchanged private Delta RSI/ETHUSDT 1h and the
public moving-average example on synthetic data. Three predeclared seeds, four
quarterly 2022 forward folds and 128 attempts/fold are retained without warm
start, early stopping or retune. Equivalent numeric CMA is a parity comparison;
CMA versus TPE/mixed-independent CMA is a different-search comparison. Actual
selected-candidate raw IS/forward metrics use original `pct_equity` accounting;
stitched account has an independent replay. Private code/data/ranges/winners
never enter Git or package artifacts.

Four folds are a bounded diagnostic, not the twelve-fold promotion study or a
test of meta edge. Correct already-numeric manual CMA has identical results
with the helper. See the [phase report](QMS_SAMPLER_HELPER_REPORT.md) for all
outcomes, including the public-alpha mixed-CMA comparison that does not favor
the helper uniformly. No helper can guarantee better future performance.
