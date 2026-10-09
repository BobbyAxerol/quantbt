# Diagnostic Planning And Reuse V1

M5-04 is opt-in research tooling in `tools/mode5_diagnostics`, not an endpoint,
sampler, financial runtime or package feature activation. Its authoritative
execution remains the existing QuantBT evaluator. Nothing imports private alpha
code into this tooling or into distributed artifacts.

## Boundaries

`DiagnosticNeeds` unions objective, constraints, axes, batteries and audit
inputs into `RequiredComputationPlanV1`. Compile before execution. The scorer
must satisfy the resulting required streams; richer diagnostics cannot be
invented from a scalar. Missing retained inputs raise `MissingInputs` with
`REPLAY_REQUIRED`; no implicit replay occurs. A separately registered replay
must use a fresh attempt and a richer retention request.

Three immutable keys separate financial and research work:

| Key | Required Identity | Invalidates |
|---|---|---|
| Execution | Alpha source, effective parameters, complete market snapshot, initial state, clock, instruments, costs, funding, account, terminal, warmup, scenario seed, source/backend | Simulation |
| Analysis | Execution, membership/view, metric/statistical contract, normalization/reference | Reduction |
| Selection | Ordered analyses, candidate universe, objective/selector/preferences, diagnostic/calibration plan, access scope | Decision revision |

Component strings are content digests or explicit frozen contract versions,
not display names. The binding adapter must derive them from complete inputs;
these tools do not infer alpha semantics or instrument equivalence. Scalar and
richer output refer to the same financial identity, but a scalar cache entry
does not satisfy a richer query. The analysis cache also checks retained-content
identity, preventing a replaced/expanded payload from inheriting old reductions.

## Permission And Ownership

`AccessWitness` comes from a reviewed manifest; `AccessPolicy` explicitly names
roles, manifests, cutoff and purpose. Request, stored-hit, analysis and selection
access are independently checked and logged. A cached holdout cannot be
relabelled development, selected by hash or read before maturity. This is a
scientific information boundary within trusted research Python code, not a
security sandbox against a caller forging its own manifests.
The role vocabulary is explicit in `access.py`; unknown roles fail closed.
All validation/holdout roles require independent-validation permission, which
itself cannot be used for selection. New environment-role semantics require
their own reviewed contract rather than a new label bypassing this boundary.

`DiagnosticReuse` wraps `PreparedObjectCache`, respecting its LRU byte/entry,
pin, clear and generation semantics. Retained numeric buffers own immutable
bytes, including after deepcopy/pickle. Analysis results use canonical JSON;
callers receive fresh decoded objects, not mutable cache ownership. Failures
and incomplete required outputs never enter the valid economic cache. Eviction
or a memory-budget bypass does not delete the scientific audit history.

Prepare immutable market and command inputs through the existing domain APIs.
Supply a fresh/reset qualified financial run and strategy/account/order/RNG
state for each independent candidate. This adapter serializes cache misses in
one owner; it does not introduce a worker pool, change adaptive ask/tell order,
parallelize account time or claim arbitrary Python callbacks are Rust-owned.
No alpha-feature cache is introduced without a complete feature identity.
Access logging also takes the owner's lock before invoking its single-producer
sink; concurrent callers cannot collide on durable chunk ordinals. Do not
share one non-thread-safe sink across several independent owners.
For caller-supplied commands/IR, include the complete tape/request fingerprint
in execution lineage, not only a strategy name and displayed parameters.

## Evidence And Recovery

`PanelRow` separates no-trade, adverse, unavailable and invalid-runtime states
and retains raw/effective/branch/trial/execution/environment identity, warmup,
cutoff/readiness, support, metric version and source/backend. Missing/runtime
invalid values are null, not a fabricated bad objective.

`DiagnosticAudit` uses `ResearchAuditWriterV1` and its existing immutable
columnar chunks. Its export hook uses the shared POSIX local checkpoint writer
for fsync/atomic publication of each append-only chunk. There is one synchronous
in-flight export with backpressure, explicit chunk/byte budgets and no unbounded
queue. A final completion marker requires the external scheduled trial IDs and
expected table counts, and is published only after required chunks flush;
cancellation is partial.
Recover validates chunk digests, the exact inventory and trial cardinality.
An absent completion marker stays `PARTIAL_INTERRUPTED`, even when chunks are
readable. Recovery is evidence inspection, not account/Optuna RNG continuation.

`recover_master_panels` reads every available baseline/T1/T2 comparison cell,
not only a winner. Historical summary rows retain their original labels and
missing full-trial/path status. Matching parameters alone never authorizes
financial reuse. Reanalysis/selection revisions do not rewrite adaptive history.

## Verification

Public tests are synthetic: `tests/mode5/test_diagnostic_*.py`. They cover guide
M5T-031..040, actual prepared Rust output versus Python/scalar accounting,
identity/permission negatives, immutable buffers and interrupted audit export.
Private alpha panels, paths, schemas and audit receipts remain ignored.

See the [phase plan](../../upgrade/implement.md#mode5-m5-04) and
[detailed guide](../../upgrade/QUANTBT_MODE5_UPGRADE_V1_DIAGNOSTICS_FIRST_GUIDE_VI.md#chapter-7).
Benchmark receipts measure matched work and simulation counts; they do not
certify economic superiority, a universal speedup or a new release artifact.
