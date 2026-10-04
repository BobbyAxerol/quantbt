# Causal History Records

Feature branch QMS-03 only. These are **internal record/observation contracts**,
not a released meta-selector or a new endpoint. Core/native versions remain
`1.1.1`/`0.4.2`. Normal `QuantBTEndpoint.walk_forward(...)` calls do not load the
module, collect panels, open history, change the winner or add evaluations.

Read the [phase report](QMS03_REPORT.md), [unified plan](../../upgrade/implement.md#qms-03)
and [detailed guide](../../upgrade/QUANTBT_1_1_1_META_SELECTION_AND_SAMPLER_MODULE_GUIDE_V1_1_VI.md#s6).
Sampler proposals remain governed by [SAMPLERS.md](SAMPLERS.md).

## Ownership

```text
existing WFO IS search and native selection
    -> internal full-pool tap, before native compaction
    -> immutable candidate records and explicit native-anchor reference
    -> decision/panel frozen before forward economic action
    -> existing financial evaluator, fresh diagnostic account per candidate
    -> original result/report adapter, terminal dispositions
    -> sealed revision and bounded history
    -> authorized immutable as-of snapshot
```

No new accounting, Sharpe formula, Optuna objective, RNG stream, final WFO
position stitching or financial replay is introduced. Captured auxiliary
support is removed from stock native result tables after the tap.
The final stitched account remains distinct from these reset-account diagnostics.
The caller/route owns strategy spawning/reset, RNG scopes, input access and
actual publication/reconciliation timing; the observer does not run a service.

QMS-03 qualifies original financial-result evidence. The internal scorer opt-in
requires explicit `use_scalar_trial_scoring=False` and
`native_prepared_wfo="off"`; it does not silently reroute scalar/native work.
Scalar results without original sample/variance evidence are blocked.
Native scalar qualification and public integration remain QMS-06/QMS-05.
The tap itself is restricted to Mode 4 `per_fold_causal`, endpoint-backed scoring.

## Three Identities

| ID | Includes | Does not imply |
|---|---|---|
| `task_id` | Exact run/corpus/origin/windows, seed, eligible physical evaluations, anchor, sampler provenance | Permission to read other runs |
| `family_id` | Strategy/schema, instrument/venue/timeframe, nominal window policy, metrics/economics, scorer, account boundary, anchor and sampler policy | Every corpus is approved |
| `snapshot_id` | Explicit corpus/cohort/exposure permissions, cutoff/event order and exact task/revision/content references | Access to later revisions |

Actual dates, fold seeds and candidate IDs do not fragment the compatibility
family. Live, real-counterfactual and synthetic outcomes retain separate cohort
identities. Caller approval, not similar columns or matching dates, authorizes
corpus transfer. Duplicate same-origin tasks fail rather than inflate support.

## Anchor And Descriptors

`MetaTask.anchor_candidate_evaluation_id` is the single anchor authority.
`CandidateRoleRef` holds logical roles such as native anchor and STATIC; it
does not copy mutable `is_anchor` flags. Proven identical physical evaluations
may share role references. Same params alone never prove equivalent stochastic
evaluations; their evaluation IDs remain distinct.

`ISPoolCapture` retains the entire finite, feasible, nonpruned IS pool, including
requested/effective params, native trial IDs, raw metric evidence and output
references. It does not mistake the reduced `candidate_table` for the pool.
Existing trial retention remains the source of attempted/pruned diagnostics.
For a synthetic centroid, the exact selected params get a separately charged
same-IS evaluation while the scorer is owned. Cluster-average scores are not
anchor labels; stock native selection/provenance is left unchanged.

`DescriptorSchema` compiles the shared normalized parameter schema once:

- Numeric variables use declared range/log encoding.
- Unordered categories use frozen one-hot blocks, not ordinal distances.
- Inactive conditional parameters are neutral, with explicit activity masks.
- Fixed parameters affect identity, not variable-distance dimensions.
- Raw IS Sharpe and `log1p(IS activity_count)` complete the minimum profile.
- Optional temporal/plateau descriptors are not implicitly inferred or filled.

Activity is the original report's position-transition count, **not** exchange
fills, entries or round trips. Missing activity/invalid metric evidence produces
an invalid descriptor row, never a zero-filled valid observation.
Arrays are immutable, contiguous float64; schema, vocabulary, feature order
and backend resolution are frozen. Unknown categories/fields and shape changes
fail; there is no padding or dimension reset.

`OriginBalancedStandardizer` fits only permitted historical IS observations
from labeled origins in an immutable snapshot. Each origin has total weight
one across its valid candidates plus its anchor. Forward label magnitudes do
not fit scaling. Numeric features are standardized; categorical/activity blocks
are not inflated by inverse rare-category standard deviations. Constant or
unobserved numeric dimensions are marked; current out-of-support values produce
an explicit support-violation mask, not an epsilon-denominator score.

The descriptor runtime is a NumPy reference buffer boundary. Metadata reports
this resolution and absent QMS native-transform capability. `native_policy="require"`
raises; this phase does not advertise a Rust descriptor/learner implementation.
QMS-04 owns the versioned numeric addition, QMS-07 its optimization.

## Original Metrics And Labels

`ResultMetricAdapter` reads raw Sharpe/activity from the existing `full_report`
reducer. Sample support uses that reducer's existing array-first daily-preferred,
bar-fallback definition, **not** the alternate pandas daily-fill helper.
This matters on irregular calendars. Definition/source IDs, annualization,
zero risk-free convention, sample count/std and initial capital/first mark are
retained. Changing the supported metric definition requires a new contract.

Canonical one-way fees, slippage, leverage, sizing, funding-source convention,
execution policy and resolved quantity constraints belong to economics identity.
Actual funding samples belong to market witnesses, not date-fragmented families.
Market signatures bind the causal input prefix, columns/dtypes, volume and
aligned funding values. Output witnesses bind original equity/returns/positions,
metric/economics/input references and initial capital without storing paths per row.
Same declared capital and mark convention are required; actual first marks can
differ due to each candidate's accepted initial trades/costs and are recorded.

For candidate $\theta$ and the **same task's** anchor $a$:

$$
D_\theta = I_\theta-O_\theta,
\qquad Y_\theta=D_\theta-(I_a-O_a).
$$

$$
Q_\theta=(I_\theta-I_a)-Y_\theta=O_\theta-O_a.
$$

No objective/trade penalty, temporal score, cluster mean or stale IS record is
substituted for raw $I/O$. The observer validates task/window/metric/economics
and base-account compatibility before labels become training rows.
Forward work is evaluation, not another optimization trial or an Optuna `tell`.

| Status | Training behavior |
|---|---|
| `VALID` | Finite raw Sharpe, >=2 samples, positive sample std, verified original support |
| `NO_VARIANCE` / `INSUFFICIENT_SAMPLE` | Retained, excluded; original report may show Sharpe zero |
| `OUTCOME_FAILED` / `INCOMPLETE_WINDOW` / `CENSORED` | Retained terminal dispositions, excluded |
| `UNVERIFIED` | Retained, excluded until reviewed provenance exists |
| `PENDING` | Separate bounded retention, no actual availability yet, cannot seal |

A genuine finite Sharpe zero with positive variance is valid. Undefined Sharpe
is not converted into a training target. A failed anchor prevents the entire
origin from contributing relative labels. Missing/corrupt provenance/schema
raises, rather than disguising it as cold start or a failed financial outcome.

## Panels, Clocks And Revisions

The versioned acceptance base panel is cap16: 1 anchor + 5 top-native IS +
5 schema-diverse + 5 mid/lower controls, with deterministic dedup/refill.
Small pools exhaust available candidates. Required winner union is added
outside the base cap and separately counted, never clipped. Panel policy is
outcome-blind and does not reduce the full current eligible pool.

```text
IS input frontier <= data_cutoff
data_cutoff <= search_completed_at / anchor_selected_at <= decision_sealed_at
decision_sealed_at <= panel_sealed_at <= first_forward_action_at
forward_end + declared_lag <= actual label_available_at
actual label_available_at <= revision_available_at
revision_available_at < next information_as_of
```

Computation may finish after data cutoff. History arriving during computation
does not enter the previously frozen snapshot. Equality at availability/cutoff
requires explicit publication order before snapshot order, for both outcome and
revision; default equality is excluded. A PENDING outcome has
`label_available_at=None` and a computed `nominal_maturity_at`, not a fabricated
actual publication time.

`clock_mode` distinguishes `historical_replay` from `observed_live`;
`wall_generated_at` is separate. Today's retrospective replay of past-only
inputs is not evidence of a prediction actually published in the past.
The example uses declared logical replay clocks, not live-equivalence claims.

`SealedTaskRevision` requires all frozen panel members to have unique terminal
dispositions. Late corrections append a parent-linked immutable revision with
reason, availability and digest. They cannot rewrite sealed IS inputs/panel or
branch the revision chain. As-of lookup takes at most one eligible revision per
task; old snapshots keep their original objects/references.
With $M$ valid distinct non-anchor labels, each has weight $1/M$; the entire
origin contribution is replaced on correction. Anchors are not informative
zero rows and revisions do not add matured origins.

## Safe Retention And Reproduction

`MetaHistory(max_revisions=...)` provides bounded in-memory storage and exact
family/corpus/cohort/exposure buckets indexed by availability. Explicit
`snapshot(...)` permissions are mandatory; no unrestricted archive object is
passed to a learner. Capacity errors do not silently evict old evidence.

`dumps_revision`/`loads_revision` and `dumps_pending`/`loads_pending` use strict
JSON, exact schemas, finite payload rules and content digests. No pickle is
loaded. `retention_chunk`/`restore_chunk` reuse `ColumnarResearchTableV1`;
restoration recomputes logical content integrity, not just a stored hash field.
These chunks can be supplied to the existing research writer/export owner.
No database, worker, filesystem scan or new persistence service is introduced.

Import checksums establish content identity, not truth. Verified import requires
both owner-reviewed complete revision IDs and an independently retained map
`output_ref -> digest(original MetricObservation)`. Missing witnesses keep
the imported revision unverified and excluded; conflicting witnesses raise.
Never generate the review registry from the untrusted JSON being imported.

Run the public-SMA synthetic-market integration example from the repository:

```bash
.venv/bin/python -m examples.wfo_history_records
```

For recorded evidence and the actual executed receipt:

```bash
.venv/bin/python -m tools.qms03_history \
  --junit benchmarks/optimization/meta_selection/qms03_tests.xml
.venv/bin/python -m tools.qms03_history --check \
  --junit benchmarks/optimization/meta_selection/qms03_tests.xml
```

See the report for the exact pytest command. This does not resume a sampler,
load a Ridge model, enable active/shadow selection or alter a production endpoint.
