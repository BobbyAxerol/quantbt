# Conditional Sobol And Evaluated-Support Projection

## Availability

PRE-E06-04 implements the owner-approved C05 policies on the feature branch.
They are opt-in, not a fifth recipe, a new endpoint or a released capability.
The [original review](CONDITIONAL_GEOMETRY_REVIEW.md) and its sealed receipts
remain historical. Current-source core 1.1.2/native 0.4.3 installed wheel/sdist
proof PASS locally in [PRE-E06-06](PRE_E06_06_REPORT.md), including the actual
conditional WFO example and exact fresh-process conditional continuation.
This is local CPython 3.12 evidence, not remote/public certification.

```python
from quantbt.optimization import SamplerConfig

optimization_config = {
    "scoring_backend": "endpoint",
    "sampler_config": SamplerConfig(
        name="sobol", sobol_policy="conditional_numeric_latent_v1",
    ),
    "flat_selector": "feasible_support_projection_v1",
}
```

Attach this fragment to the existing WFO call, with an explicit uint32
`random_seed`. Either policy can be used separately. Conditional parameters
use the existing `active_if` schema; parent keys precede children.
See [the runnable example](../../examples/wfo_conditional_policies.py).
Keep the original strategy, account, calendar, fees and financial backend.

## Numeric And Category Streams

Freeze numeric layout from normalized schema **before ask**. Every variable
numeric key owns one coordinate, including inactive children. Fixed/singleton
and category keys own no numeric coordinate. Require at least one coordinate.
Layout identity includes the schema, dimension order and versioned policy.

- Numeric QMC: SciPy Sobol, bits 30, scrambled, no optimization, resolved seed.
- Independent startup: pinned Optuna RandomSampler, resolved seed.
- Active categories: separate Optuna RandomSampler, seed XOR `0x9E3779B9`.
- Optuna must be **4.8.0**. SciPy version is recorded and pinned at resume.

Warm starts form a prefix, consuming neither startup nor QMC. Exactly one
independent attempt follows. Every subsequent ask charges one full point even
when all numeric keys are inactive, the attempt fails/is infeasible/is pruned,
or it duplicates an effective candidate. Batch asks charge in **ask order**,
not completion order. Early stopping does not spend unused budget. No retries,
padding, conditional numeric fallback or financial dummy calls are permitted.

Linear/log and integer/stepped transforms follow the approved C05 mapping.
Stepped endpoints use decimal lattice arithmetic matching Optuna's distribution:
`0.7000000000000001` must not exceed `0.7`. Bounds/accounting tolerances are not
relaxed. Cube values must be finite in `[0, 1)` with the exact frozen dimension.

Full decoded proposals stay in `requested_params`; only active effective params
go to the strategy. Categories are not ordinal QMC coordinates. Masking, rounding
and filtering imply no discrepancy guarantee or better forward performance.
`seed=None` remains valid for old recipes, not this deterministic policy.

## Own-Witness Representative

Original selectors still construct/score their clusters. Within the chosen
cluster, deduplicate admissible effective geometry points, calculate the center
and project to the nearest **existing evaluated point**. Never execute averaged
categories, a synthetic centroid or inactive values. Auxiliary financial calls:
**zero**. The center is diagnostic only; duplicate attempts remain in provenance.

Geometry reuses approved logical numeric/category/conditional blocks. Tie set:
squared distance at most minimum plus `1e-12`; total order uses semantic effective-
value digest, candidate ID and evaluation ID. Empty admissible support raises.

Selected metrics are the candidate's **own original current-IS observation**,
not cluster averages. Bind market/calendar/account/objective/metric/strategy/
schema/execution seed/window/cutoff. Evaluation identity seals the complete
observation and params/context. Foreign, changed, future, stale or missing
witnesses fail closed. Cluster robustness summaries remain separate diagnostics.

## Qualified Local Scope

| Surface | Conditional numeric Sobol | Support projection |
|---|---|---|
| Shared scalar optimizing studies | Explicit policy, existing schedules preserved | Five scalar targets, Mode 4/per_fold_causal; Mode 5 full-sample plateau/robust |
| Sequential W3, inprocess or safe Linux process | Existing ordered studies | Mode 4/per_fold_causal, original reset-flat single-symbol window |
| Private W3 R3B throughput batch | Existing **global** schedule only | Rejected before strategy; no qualified own-IS acquisition |
| Fixed candidate-matrix replay | Not a sampler; conflicting options rejected | Rejected; not converted into adaptive search |
| Other modes, multi-window/proxy/non-scalar projection | Existing sampler route rules | Rejected; no new scientific/domain admission |

Projection does not automatically enable meta; meta retains its separate
method/domain/history contract. This projection does not support nested Mode 1,
portfolio, package, callback, intent/session or delivery selection. Their default
medoid/meta contracts remain unchanged. Ordinary `centroid` keeps all guards.

## Audit And Continuation

Scalar: `result.metadata["walk_forward"]["sampler_studies"]`.
W3: `result.metadata["sampler_studies"]`. New metadata records layout, both seeds,
SciPy version, bits, whole-point indexes, masks, category draws, terminal states,
feasibility and duplicates. Representative metadata includes support/evaluation
IDs, center/distances, own observation and zero auxiliary IS evaluations.

The existing [owned exact-continuation session](EXACT_CONTINUATION.md) supports
this sampler. Journal reconstruction replays actual ask/suggest/report/tell,
warm queues, category RNG, QMC points, batch completion order and terminal states.
It does **not** replay the financial evaluator. Final witness and all source/
dependency/binding digests must match. No automatic whole-WFO/account/strategy
recovery or silent migration of an old-source checkpoint is claimed.

Read [PRE04 report](PRE_E06_04_REPORT.md). New-policy sequences intentionally
differ from legacy Sobol. Old-default baselines, four-recipe continuation and
off/shadow accounting have separate regression gates. Independent references
and hand cases qualify the new math; software PASS does not imply economic
promotion, public artifact certification or whole-WFO speed improvement.
