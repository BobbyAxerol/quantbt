# QMS-C05: Conditional Sampling And Admissible Representatives

## Decision And Scope

Status: **PROPOSED_SPEC_AND_TESTS_ONLY**. Activation requires separate owner
approval. This review does not add a public option or change the four recipes,
medoid, Ridge, descriptor schema, financial runtime or registered economic study.
Entry source: `681cb00`. Pair remains **1.1.2 / 0.4.3**, unpublished.

Read the [C05 plan](../../upgrade/implement.md#qms-c05---conditional-sobol-and-admissible-mixed-space-representatives)
and the unchanged detailed guide:
[4.3-4.7](../../upgrade/QUANTBT_1_1_1_META_SELECTION_AND_SAMPLER_MODULE_GUIDE_V1_1_VI.md#s4),
[5.2-5.6](../../upgrade/QUANTBT_1_1_1_META_SELECTION_AND_SAMPLER_MODULE_GUIDE_V1_1_VI.md#s5).
The executable references live under `tools/qms_c05_*`, **not** `src/quantbt`.
They are review instruments, not runnable WFO samplers or installed capabilities.

## Current Source And Capability Boundary

| Responsibility | Current authority | This review |
|---|---|---|
| Ranges, activity, effective identity | `NormalizedSearchSpace` | Reuse; no inferred conditions |
| Four samplers | `optimization.samplers.build_sampler` | Keep current factory and errors |
| Study constraints and duplicate attempts | `WfoSamplerStudy` | Specify consumption; no runtime changes |
| Mixed geometry | `DescriptorSchema.parameter_geometry` | Compare independent logical-block calculation |
| Numeric centroid | `walkforward._centroid_params` | Existing numeric behavior unchanged |
| Exact IS anchor | `ISPoolCapture.capture` | Existing original-result acquisition unchanged |
| Public mixed centroid | `prepare_wfo_studies` | Remains unsupported |
| Exact persisted continuation | C04 owned session | Existing codecs/source pin unchanged |

Optuna 4.8 freezes QMC relative space from an initial trial. A conditional child
absent then cannot be safely treated as a later joint dimension. Its categories
use independent sampling; it is not a joint categorical Sobol method.
[Optuna 4.8 QMCSampler documentation](https://optuna.readthedocs.io/en/v4.8.0/reference/samplers/generated/optuna.samplers.QMCSampler.html).

## Proposed Frozen Numeric Latent Contract

Proposed ID: **qms-conditional-numeric-latent-v1-proposed**.
This would be an explicit policy of the existing `sobol` recipe after approval,
not replacement of Sobol V1 or a fifth recipe. No config spelling is activated.

1. Compile the existing topologically ordered schema before asking any trial.
2. Reserve one latent coordinate for every variable **numeric** parameter,
   including conditional and permanently inactive numeric parameters.
3. Do not allocate numeric coordinates to fixed/singleton or category parameters.
   No variable numeric dimensions is unsupported; dimension order is schema order.
4. Freeze the schema/layout identity for the study. A different order, condition,
   category vocabulary, fixed value, bound or transform requires a new identity.
5. Use a fixed-dimensional scrambled SciPy Sobol stream, bits=30, no optimization.
   Record SciPy/version, dimension order, bits, scramble seed and actual indexes.
   Require an explicit uint32 seed for this deterministic proposed policy.
   This does not remove `seed=None` from any existing sampler.
6. Sample active categories independently with the existing pinned Optuna random
   sampler, using a separate declared stream and schema-order calls. Categories
   are never ordinal codes in QMC space. Do not draw a category for inactive nodes.
7. Decode the whole numeric point before applying branch masks. Walk parents in
   schema order; missing/inactive parents make dependent branches inactive.
8. Retain the full decoded numeric proposal as provenance, but pass only effective
   active parameters and active fixed values to the strategy. An inactive numeric
   coordinate remains consumed; it cannot move a later active coordinate.

The review reference accepts independent category outcomes as inputs. It does
**not** simulate their RNG or claim a qualified Optuna adapter. An approved future
adapter must test actual category draw order and startup stream against witnesses.

### Numeric Transforms

The proposed mapping uses the pinned Optuna numeric-transform convention,
implemented independently in the reference; no private Optuna imports.
For an unstepped linear float on bounds L,H, a point u in [0,1) maps to:

\[
x=L+u(H-L).
\]

For an unstepped log float:

\[
x=\exp\bigl(\log L+u(\log H-\log L)\bigr).
\]

For linear integer/stepped float, let s be the declared step (integer default 1)
and H* the largest valid lattice endpoint. Map across extended bounds and round
to the lattice with round-half-to-even, then clamp to [L,H*]:

\[
r=L-\frac{s}{2}+u(H^*-L+s),\qquad
x=\operatorname{clip}\left(L+s\operatorname{round}_{even}
 \left(\frac{r-L}{s}\right),L,H^*\right).
\]

For log integer with step=1 only:

\[
r=\exp\bigl(\log(L-1/2)+u(\log(H+1/2)-\log(L-1/2))\bigr),\qquad
x=\operatorname{clip}(\operatorname{round}_{even}(r),L,H).
\]

The upper continuous endpoint uses the pinned convention's representable
predecessor when rounding would produce H. `u=1`, NaN, infinity, wrong dimensions,
unknown categories, unsupported log/step combinations or invalid active values
fail rather than changing the search. Bounds/step membership is checked again by
the existing effective-parameter builder.

### Attempt Budget And Sequence Consumption

Proposed first independently generated attempt: **one**, after any caller-supplied
warm-start prefix. Warm starts do not define the latent layout and all are rescored
on current IS; they stay inside the caller's attempted budget.
This differs from allowing a warm seed to infer Optuna's relative space and must
be versioned explicitly, not sold as exact legacy proposal parity.

| Attempt source/outcome | Attempt charged | QMC point charged |
|---|---:|---:|
| Warm seed, including failed/rejected seed | 1 | 0 |
| First independent, including failed/rejected startup | 1 | 0 |
| QMC COMPLETE, result-infeasible COMPLETE | 1 | 1 |
| QMC parameter rejection/PRUNED | 1 | 1 |
| QMC effective duplicate/PRUNED | 1 | 1 |
| QMC evaluation FAIL | 1 | 1 |
| Unspent budget after early stop | 0 | 0 |

Point indexes are zero-based and contiguous. No retry-until-feasible, index reuse,
thinning, power-of-two padding, hidden dummy objective, extra alpha evaluation or
independent fallback for a conditional numeric coordinate. Running states are not
reported as terminal observations. A budget of 128 with two warm seeds and one
independent attempt has at most **125** QMC points, not 128.

SciPy documents balance restrictions for unthinned power-of-two Sobol prefixes.
Masking, categorical draws, lattice rounding, duplicates and constraint filtering
do not inherit a proven discrepancy bound for the resulting feasible strategy
pool. Report both the cube prefix and transformed unique/feasible counts.
[SciPy Sobol documentation](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.qmc.Sobol.html).

## Proposed Finite-Support Representative

Proposed ID: **qms-feasible-support-projection-v1-proposed**.
This is a new, opt-in selector proposal, **not the existing medoid** and not a
synthetic constrained centroid solver. The cluster's construction/scoring remains
owned by the original selector; this review starts with an already declared
cluster and immutable current-IS witness bindings.

### Eligible Support And Geometry

Use only schema-valid, feasible, finite-original-result candidates in the current
cluster with their own exact IS evaluation under identical bindings. Feasibility
is from actual existing parameter/result constraints; the reference consumes an
explicit boolean witness, not an arbitrary new constraint DSL.

Deduplicate **effective geometry points**, not trial observations: identical
effective candidates count once in the proposed geometric center. Keep every
attempt and evaluation ID in provenance; do not merge Optuna ask/tell records.
This weighting choice is new proposed math, not a change to legacy medoid weights.

Let z(theta) be the current fixed-schema parameter geometry. For the unique
admissible support S, form a diagnostic center and project **only onto S**:

\[
c=\frac{1}{|S|}\sum_{\theta\in S}z(\theta),\qquad
d_{\min}=\min_{\theta\in S}\|z(\theta)-c\|_2^2.
\]

Each logical parameter block contributes at most one squared distance unit:

| Block | Encoding / squared distance |
|---|---|
| Unconditional numeric | Linear/log normalized value; squared difference |
| Unconditional category | One-hot divided by sqrt(2); mismatch 1 |
| Conditional numeric | `(active * normalized / sqrt(2), active / sqrt(2))` |
| Conditional category | One-hot/sqrt(2) plus active/sqrt(2) |
| Fixed/singleton | Retained in identity; no geometry dimension |

Two inactive conditional blocks contribute zero. Active versus inactive numeric
contributes `(1 + normalized^2)/2`; inactive is not an observed zero. Category
vocabulary permutation changes columns, not distances. No raw-IS/activity metric
or historical standardizer enters this parameter-only projection.

### Total Tie Order And Category Relabelling

Make one tie set `distance_squared <= d_min + 1e-12`; no chained approximate
comparator. Within it order by (canonical effective-value digest, candidate ID,
evaluation ID). The first digest pins actual semantic values and strategy identity,
not category vocabulary order. Candidate IDs still include the actual schema.
This preserves tied semantic ranking when a vocabulary is permuted with its
schema mapping; relabelling the semantic values themselves is not that operation.
Use the same semantic order for center accumulation; the reference uses an
accurate sum of squared coordinate differences to avoid category-column ordering
as an accidental tie-break. The declared tolerance is not a scientific margin.

An empty admissible support raises, not a fallback to an infeasible center. A
singleton returns that exact point. The geometric center is never converted into
enums, inactive values or executable params. The result is an existing real point;
in particular, it need not equal the medoid that minimizes summed distances.

### Exact Anchor Witness

Require the selected point's own original IS observation and evaluation ID, bound
to effective candidate, strategy/schema, market/calendar, account/economics,
objective/metric, execution seed and IS information cutoff. Do not accept a
forward witness, stale historical score, another tape/seed/account or averaged
cluster metrics. Unknown or mismatching bindings fail closed.

Projection over evaluated support adds **zero** financial calls. It cannot invent
a synthetic candidate. If a later proposal projects outside that support, it is
a different version: exact same-IS evaluation, budget/cost accounting, feasibility
checks and RNG isolation are mandatory before using it as a native/meta anchor.
Existing numeric centroid acquisition still does this on the current route.

## Integration Gates After Approval

1. Owner accepts or changes the transforms, startup/category streams, support
   weighting, tie order and metadata IDs above. Record the decision; this doc is
   not the approval itself.
2. Add explicit opt-in policies through the existing shared factory, normalized
   space, WFO study and selector seams. Preserve all old defaults and guards for
   every remaining unsupported contract; do not introduce another engine/bridge.
3. Verify actual proposal/category RNG, full pool/order/constraint witnesses,
   original-result anchors and off/shadow accounting across applicable schedules.
4. Extend C04 codec/source/binding identities for the new policies and qualify
   fresh-process continuation. Existing continuation receipts remain historical.
5. Qualify all four recipes on claimed W3/R3B routes and wheel/sdist consumers,
   then run the approved economic study. No assertion that coverage implies lower
   OOS decay, future robustness or sampler superiority.
6. Measure public workloads, retention/RSS and boundary budgets only after
   domain/RNG gates. The reference here is not a performance benchmark.

No Rust sampler is added: Optuna owns the search. If approved geometry workloads
justify native batching, reuse the existing numeric boundary and certify it
against these expected values; language choice cannot change the methodology.
