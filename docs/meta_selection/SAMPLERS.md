# Shared WFO Samplers And Search Space

## Availability And Scope

QMS-02 adds sampler-only configuration on `feat/meta-selection-samplers`.
It is not yet published: released core 1.1.1/native 0.4.2 are unchanged.
This feature uses the same `SamplerConfig`/`build_sampler` as the generic
optimizer. It does not enable meta-selection, change the financial backend,
modify objectives or create a new endpoint. Optional meta is now integrated by
QMS-05 through [a separate policy/history binding](INTEGRATION.md); sampler-only
still does no meta work.

Read the [unified phase](../../upgrade/implement.md#qms-02),
[detailed specification sections 3-4](../../upgrade/QUANTBT_1_1_1_META_SELECTION_AND_SAMPLER_MODULE_GUIDE_V1_1_VI.md#s4),
[source map](SOURCE_AND_SEAM_MAP.md), and [causal schedule guide](../walkforward_causal.md).

## One Configuration Route

Add one nested field to an existing optimizing WFO call:

```python
from quantbt.optimization import SamplerConfig

optimization_config = {
    "scoring_backend": "endpoint",
    "sampler_config": SamplerConfig(name="tpe_multivariate_group",
                                   kwargs={"n_startup_trials": 30}),
}
```

A mapping is equivalent:

```python
optimization_config = {
    "scoring_backend": "endpoint",
    "sampler_config": {
        "name": "tpe_multivariate_group",
        "kwargs": {"n_startup_trials": 30},
    },
}
```

These are fragments, not a substitute for the existing account/split/strategy
configuration. See the integration-tested complete
[runnable example](../../examples/wfo_samplers.py):

```bash
python examples/wfo_samplers.py --sampler sobol
python examples/wfo_samplers.py --sampler cmaes --warm-start
```

The example uses synthetic OHLC and is not economic validation.

## Recipes And Capability Errors

| WFO name | Implementation | Qualified geometry |
|---|---|---|
| omitted, `tpe`, `tpe_legacy` | `TPESampler` | Legacy defaults; default startup is 10 in pinned Optuna 4.8.0 |
| `tpe_multivariate_group` | `TPESampler(multivariate=True, group=True)` | Numeric, categorical and explicitly conditional parameters |
| `cmaes` | `CmaEsSampler`, cmaes 0.12.0 | Single objective with static variable numeric dimensions; categorical/dynamic geometry rejected by default |
| `sobol` | `QMCSampler(qmc_type="sobol", scramble=True)` | Static numeric relative space; categorical dimensions sampled independently; conditional ranges rejected |

Optuna remains pinned at 4.8.x, with local evidence on 4.8.0. `cmaes==0.12.0`
is included in the `optimization` and `all` extras, not core-only imports.
Missing dependency, unknown recipe/kwargs, group without multivariate,
incompatible geometry, and seed overrides fail before financial evaluation.
Existing generic random/grid/NSGA-II choices remain available in their original
optimizer scope, not as additional WFO research recipes.

Opt-in mixed CMA example:

```python
sampler = SamplerConfig(name="cmaes", mixed_space_policy="explicit_independent")
```

At least one static variable numeric dimension is required. Actual joint
proposal dimensions and independent calls are retained; categorical values
are never relabeled integers and advertised as covariance-optimized.
Independent-sampling warnings cannot be suppressed for this policy. The
`with_margin=True` variant has a bounded integer/step capability test; it is
not a promise that every mixed/discrete strategy is supported.

The default path omits all new fields. No warm-start, archive read, additional
evaluation, observation or sampler RNG draw is added. Omitted-config tests
compare exact recorded proposals/objectives/anchors/signals/account results
across all eight valid legacy mode/schedule combinations. A separate 40-attempt
test exercises TPE beyond startup and proves delegate/observer trajectory parity.

## Range Syntax And Effective Identity

Legacy syntax retains its meaning and ordering:

```python
param_ranges = {"window": (3, 31, 2), "kind": ["fast", "slow"], "degree": 2}
```

Numeric tuples describe bounds; numeric lists and `range` remain discrete
categorical choices. Fixed scalar values remain in candidate identity but do
not add optimized geometry dimensions. Generic `fixed_params` still overrides
ranges; the WFO equivalent is a scalar/fixed spec in `param_ranges`.

Additive explicit schema:

```python
param_ranges = {
    "use_filter": {"kind": "boolean"},
    "length": {"kind": "integer", "low": 4, "high": 40, "step": 2,
               "active_if": {"use_filter": True}},
    "rate": {"kind": "float", "low": 0.001, "high": 0.1, "log": True},
    "kind": {"kind": "categorical", "choices": ["fast", "slow"]},
    "degree": {"kind": "fixed", "value": 2},
}
```

Parents must occur earlier in mapping order. Conditions are explicit equality
membership rules over prior parents; QuantBT never infers alpha dependencies
from flag names. Inactive parameters are not suggested or passed to the strategy.
Strategies consuming this opt-in schema must tolerate their declared absence.
Log bounds must be positive; float log+step and integer log+step other than 1
are rejected. Bounds/steps must be finite and valid. No dynamic provider/constraint
DSL is added.

`NormalizedSearchSpace(param_ranges).metadata()` exposes the typed/versioned
view and `.identity` pins geometry/order/conditions/fixed values. Trial provenance
keeps requested and effective params separate. Warm-start can retain an inactive
requested value, but it does not change the effective candidate. Candidate IDs
include effective params, schema identity and the existing strategy fingerprint.
Effective numeric/fixed values use the schema's canonical scalar types; a warm
seed written as `2` versus `2.0` cannot create a false numeric candidate identity.
Duplicates consume attempted budget, retain their trial IDs and are pruned before
evaluation, not merged into a different Optuna observation.

New mapped numeric geometry honors log scale; mapped categorical geometry is
unordered one-hot with per-category mismatch norm one; inactive numeric values
have a neutral value plus an activity dimension. Legacy selector geometry is
unchanged. Categorical/conditional/constrained opt-in centroid selection is
explicitly unsupported: use a medoid. This prevents inventing an inadmissible
anchor from averaged branch values. Meta descriptors remain QMS-03 scope.
For medoids, a noninvertible mapped diagnostic centroid has
`centroid_params=None`; it is not advertised as an executable parameter vector.

## Constraints

Two optional runtime callbacks in `optimization_config` use the existing
nonpositive-feasible convention:

```python
optimization_config = {
    "sampler_config": SamplerConfig(name="sobol", constraint_mode="post_filter"),
    "parameter_constraints": lambda params: (params["fast"] - params["slow"],),
    "result_constraints": lambda is_record: (is_record.fold_metrics[0]["is_trade_count"] - 500,),
}
```

Declare constraints before the search. Parameter-only violations are `PRUNED`
without financial work. Result constraints consume the real IS evaluation and
retain its actual `COMPLETE` objective; infeasible candidates are excluded from
native selection. They are not fake successful zero/-1e9 outcomes. TPE can also
feed formal result constraints to Optuna; CMA/Sobol require explicit `post_filter`
for either constraint callback, including early parameter rejection.
All values must be finite. No feasible candidate causes an explicit run error.

`result_constraints` receives the authoritative IS trial record, not arbitrary
OOS results; Mode 1's subsequent candidate-decay stage remains unchanged.
Callbacks must not read undeclared future data from closures. Runtime callables
are not portable JSON configuration/checkpoint objects.

## Params-Only Warm Start

Default is off. The caller supplies a canonical arm-independent seed list:

```python
from quantbt.core.wfo_contracts import strategy_fingerprint
from quantbt.optimization import NormalizedSearchSpace

seed_record = {
    "params": historical_params,
    "available_at": historical_available_at,
    "space_identity": NormalizedSearchSpace(param_ranges).identity,
    "strategy_identity": strategy_fingerprint(strategy),
}
optimization_config["sampler_warm_start"] = [seed_record]
```

Availability must be strictly before each study's train-end information cutoff,
using compatible naive/aware clock declarations. Equal-time ordering is not
guessed. Future availability, wrong strategy/schema, missing active fields,
out-of-range/off-step values, duplicate effective seeds, old scores or a seed
count exceeding the attempted budget fail preflight.

Every enqueued seed is rescored on current IS; attempts remain inside
`optuna_trials`. The same configured list applies to each study, so all records
must already be available before the earliest participating cutoff. There is
no automatic history lookup or hidden extra seeds. Two selector comparison arms
must share the same list; per-arm previous winners would change the candidate
pool and are not same-pool evidence.

## Study Seeds, Telemetry And Resume

Global runs keep one study. Per-fold runs keep the existing independent derived
fold seeds; nested Mode 1 still searches inner folds. Mode 2 keeps its proxy,
bootstrap and evaluation seeds. A sampler changes proposals only, not schedule,
objective, native selection stage or final continuous-account stitching.

After a run:

```python
studies = result.metadata["walk_forward"]["sampler_studies"]
```

Each study contains resolved class/version/kwargs/seed/stage, schema identity,
requested/actual attempts, COMPLETE/PRUNED/FAIL counts, feasible/unique/duplicate
counts, warm-start attempts, requested/effective params, objective/constraint
reasons, actual relative dimensions and independent calls, method wall time and
an ask/tell digest. No diagnostic RNG draws are made.

Sobol records the observed dimension order and actual consumed relative proposals.
Its independent first trial and enqueue behavior mean total attempts are not
necessarily pure Sobol points. No trials are added to round the budget to a
power of two. Public APIs do not expose authoritative CMA generation counts,
TPE group decomposition or exact startup/adaptive counters; those fields say
`not_exposed`, not estimates inferred from private internals.

The existing endpoint loops still provide only owned in-process continuation;
generic optimizer storage is not an exact RNG resume promise. QMS-C04 adds a
separate opt-in [owned persisted journal session](EXACT_CONTINUATION.md), with
version-pinned ask/suggest/report/tell reconstruction and exact proposal/state
validation. It imports neither pickle nor storage system attributes and does
not add a public WFO resume endpoint. Seed reset or database reload alone is
still not exact continuation.

C03 now qualifies these same four recipes on W3 sequential/safe process and
opt-in R3B through the shared bridge. See [the actual scheduler matrix and
versioned proposal order](W3_SAMPLER_SCHEDULES.md). Fixed `candidate_matrix` is
replay, not a sampler, and rejects conflicting sampler/warm/constraint options.
Omitted legacy scheduling is preserved. Batch size greater than one is not
sequential TPE/QMC equivalence. W3 metadata is directly under
`result.metadata["sampler_studies"]`, not ordinary WFO's nested `walk_forward`.

## Evidence And Limits

Engineering tests cover Q2-T01 through Q2-T08 and the installed native oracle
comparison: **228 passes, zero skips/failures**, including 96 QMS-02 checks.
See the [phase report](QMS02_REPORT.md) and
[gate receipt](../../benchmarks/optimization/meta_selection/qms02_gate_receipt.json).
The [cost evidence](../../benchmarks/optimization/meta_selection/qms02_sampler_evidence.json)
uses four recipes on the same public example, 547 daily bars, 12 attempts per
study, two folds, seed 731, one worker, one warm-up and three retained timings.
Different recipes have different pools: absolute costs are not a sampler
superiority or speedup claim. Process-wide RSS includes cumulative imports/JIT.
Economic acceptance, meta activation and final installed-wheel/CI release
qualification remain in their approved phases. No published version is changed.
