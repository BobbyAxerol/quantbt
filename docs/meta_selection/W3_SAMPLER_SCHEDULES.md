# W3 Samplers And R3B Proposal Schedules

## Availability

C03 is a locally qualified feature-branch addition, prepared for core **1.1.2** /
native **0.4.3**. It has not been published or remotely qualified on these bytes.
It reuses the [shared sampler contract](SAMPLERS.md), pinned Optuna 4.8.0 and
cmaes 0.12.0. No Rust financial code, Ridge formula or sampler implementation
changes. Existing endpoints and omitted-config behavior remain stable.

Detailed authority: [guide section 4](../../upgrade/QUANTBT_1_1_1_META_SELECTION_AND_SAMPLER_MODULE_GUIDE_V1_1_VI.md#s4),
[information-preserving execution section 10](../../upgrade/QUANTBT_1_1_1_META_SELECTION_AND_SAMPLER_MODULE_GUIDE_V1_1_VI.md#s10),
and [unified C03 plan](../../upgrade/implement.md#qms-c03---four-samplers-on-w3-and-fixed-batch-schedulers).

## Actual Capability Matrix

| Recipe | Sequential W3 | Safe Linux fork process | Opt-in R3B | Main geometry guard |
|---|---|---|---|---|
| `tpe_legacy` | Qualified | Qualified | Qualified v2 | Shared normalized space |
| `tpe_multivariate_group` | Qualified | Qualified | Qualified v2 | Conditional activity is explicit |
| `cmaes` | Qualified | Qualified | Qualified v2 | Static numeric; mixed requires `explicit_independent` |
| `sobol` | Qualified | Qualified | Qualified v2 | Static relative space; conditional rejected |

This is a bounded software matrix, not a certification of every strategy,
context projection, alpha or exchange. Financial execution remains original
Rust native-event execution with segmented `reset_flat` accounts. There is no
continuous compounded equity reconstruction in W3.

W3 retains Modes 1, 3, 4 and 5 and their existing allowed schedules. Sequential
Mode 1 `per_fold_causal` uses explicitly configured **inner** folds; the sampler
cutoff is the maximum inner train-end, not outer OOS. Fold seeds are independent
and derived by the existing seed policy. Mode 4 `per_fold_causal` sees current
IS only; a global study is not a historical per-fold causal validation merely
because its search objective uses IS. Mode 2 remains unsupported on W3.

Meta remains only Mode 4 / `per_fold_causal` / certified sequential, locally
inprocess or safe process. Public meta batching, carry and multi-symbol remain
closed. The four sampler recipes do not expand this methodology scope.

## Stable Invocation

Set the existing `WalkForwardConfig` field; no new endpoint or sampler class:

```python
from quantbt.optimization import SamplerConfig

config = WalkForwardConfig(
    # Existing strategy, split, scoring and reset-flat account fields.
    sampler_config=SamplerConfig(name="sobol"),
    # ...
)
```

The complete, self-contained [example](../../examples/wfo_reactive_samplers.py)
also declares real account costs, strategy reset and candidate wake behavior:

```bash
python examples/wfo_reactive_samplers.py --sampler sobol
python examples/wfo_reactive_samplers.py --sampler cmaes --scheduler throughput_batch_v1
```

Configuration is validated before strategy preparation/workers. Warm seeds use
the **real factory** fingerprint, not an internal scorer-marker function. They
are params-only, available before every participating cutoff and rescored
inside the attempted budget. Constraints, geometry and seed errors fail closed.

## Proposal Ordering Is An Algorithm Contract

Default `certified_sequential_v1`: ask, suggest, evaluate, tell one trial, then
ask the next. Upstream observation order and RNG draws are preserved.

Opt-in `shared_sampler_batch_r3b_v2`, under `throughput_batch_v1`:

1. Ask the complete batch, up to remaining attempted budget.
2. Suggest all params before any tells.
3. Prune effective duplicates and parameter violations without native scoring.
4. Score remaining candidates through the existing R3B scheduler.
5. Tell every trial in original trial-number order.

Only global, inprocess R3B is supported. Batch size is part of algorithm
identity. Early stopping finishes the already asked batch; final budget may
produce a smaller last batch. Abort/cancel marks pending trials `FAIL`, releases
native runners and never leaves a hidden RUNNING observation.

Parameter-invalid/duplicate/native-failed attempts are `PRUNED` with no fake
COMPLETE objective. Result-infeasible candidates retain their real COMPLETE IS
score and constraint vector but cannot be selected. TPE formal constraints and
explicit CMA/Sobol `post_filter` use the existing nonpositive-feasible convention.

**B > 1 is not sequential sampling.** First-batch proposals have no completed
observations. In the tested 16-attempt Sobol fixture, sequential consumes 15
relative proposals, batch size 4 consumes 12. Total attempts are not QMC points;
Optuna startup/enqueues, pruning and mapping must be read from real telemetry.
Do not add trials or alter RNG to make budgets aesthetically power-of-two.
See upstream [ask/tell](https://optuna.readthedocs.io/en/v4.8.0/tutorial/20_recipes/009_ask_and_tell.html)
and [QMC semantics](https://optuna.readthedocs.io/en/v4.8.0/reference/samplers/generated/optuna.samplers.QMCSampler.html).

Omitted sampler policy with legacy ranges stays on
`adaptive_optuna_batch_r3b_v1`. Explicit sampler policy **or mapped schema**
selects v2; never relabel an old receipt as the new algorithm.

## Fixed Matrices And Telemetry

`candidate_matrix` replays a frozen pool; it does not invoke a sampler. Metadata
remains `fixed_candidate_matrix_r3b_v1`. Sampler, warm-start or constraint policy
with a fixed matrix raises `SAMPLER_ROUTE_UNSUPPORTED` instead of being ignored.
Keep selector ranges, but prefilter/validate a frozen pool at its original source.

Read `result.metadata["sampler_studies"]` directly on W3 (ordinary WFO nests this
under `"walk_forward"`). It records class/version/kwargs, cutoff/fold seed,
actual relative/independent dimensions, warm/source identity, states, objectives,
constraints and ask/tell digest. Batch studies additionally record contract,
batch membership/size and explicit `sequential_equivalent=False`.

Frozen valid-pool replay and batch-size-one parity check proposals, native
scores, selection and original equity/positions/fees/funding/margin. They do
not imply equal decisions across distinct sampler pools or arbitrary batches.
No persisted exact RNG checkpoint, conditional Sobol, categorical/conditional/
constrained centroid or extra meta mode is introduced by C03.

See [C03 report](QMSC03_REPORT.md) for measured costs, test/artifact references,
software qualification and remaining remote/public gates.
