# PRE-E06-05 Matched Cost And Shared Optimization

## Scope And Status

Measurement and the scoped runtime patch are complete locally on
`feat/meta-selection-samplers`, entry `d0cd95a`. Source software qualification
passes 2,346 distinct scoped checks; the cost exit gate is OPEN, not an accepted
full phase completion receipt. No release,
workflow, push, economic study or new route/method activation is authorized.

Read [the phase and registered budgets](../../upgrade/implement.md#qms-pre-e06-05),
[guide section 8](../../upgrade/QUANTBT_1_1_1_META_SELECTION_AND_SAMPLER_MODULE_GUIDE_V1_1_VI.md#s8),
[section 10](../../upgrade/QUANTBT_1_1_1_META_SELECTION_AND_SAMPLER_MODULE_GUIDE_V1_1_VI.md#s10)
and [report discipline](../../upgrade/QUANTBT_1_1_1_META_SELECTION_AND_SAMPLER_MODULE_GUIDE_V1_1_VI.md#s12).

## Actual Change

Only `meta_selection/common.py::wire` changes runtime execution: exact built-in
portable values use a shorter dispatch before generic dataclass/Mapping/NumPy
handling. Enum and other subclasses retain the old dispatch. Independent tests
lock canonical bytes, SHA, negative zero, UTC conversion, immutable containers
and exact error strings. No float precision or invalid-value coercion changes.

Witness source/mutation/calendar checks, cache limits and closure remain on the
qualified implementation. A faster unchecked prefix test was not introduced.
No additional account, strategy, model, RNG, report or evaluation cache exists.
There is no new Rust ABI/build. The existing qualified Rust transform/Gram-solve/
rank batch remains unchanged; portable JSON/hash dispatch is not a numeric batch
worth replacing with per-scalar FFI. NumPy scaler/diagnostics remain observable.

Exact source normalization accepts only the one reviewed file/hash. It does not
re-seal old receipts, exempt whole files or waive financial/scientific guards.

## Measurement Contract

- 76 registered public synthetic cells: eight legacy five-mode/schedule cases,
  thirteen Mode 4 domain/accounts with off/shadow/active, four scalar prepared
  targets with all three states, five nested Mode 1 scalar targets with all
  three states, and two same-policy conditional Sobol/projection cases.
- Six/eight original trials, seed 731, lambda 10, original labels/panels and
  all retained outputs. Enabled cells require actual fit/rank with at least
  twelve mature origins. These small fixtures are not an economic acceptance study.
- 21 paired warm samples per cell, alternating arm order, one fresh worker per
  cell, one numeric thread. The single first cold sample is reported explicitly;
  the other warmup arm shares that worker and is not independent cold evidence.
- Frozen synthetic history is loaded once outside timing, then each run owns
  an independent history container, endpoint, account and strategy state.
  History-load and fixture preparation are recorded separately, not hidden as
  financial speedups. No source-alpha or market file is copied into public evidence.
- Ordinary endpoint construction is outside the timer. For W3 the constructor
  also prepares native market ownership; its per-run fixture/constructor cost
  is retained separately. W3 timing is the complete prepared public `backtest`
  call, not a fresh-data constructor-plus-backtest throughput certificate.
- Backtest timer includes normal preparation/scoring/meta/observer/final account
  and adaptation. Profiles are separate instrumented runs, not latency gates.
  Legitimate additional C01 raw outer-IS evaluations are retained and charged.
- Both arms bind equivalent exact portable/witness blocks outside timing;
  only reviewed implementation bodies differ. Financial execution, strategy,
  Optuna and model/numerical code are never replaced by the benchmark harness.

Budgets were owner-approved before results: disabled p50 +3%, p95 +5%.
Point failures are NOT_MET; uncertain timing remains INCONCLUSIVE. No selection
of favorable seeds, repetitions, samples, confidence bounds or relaxed budgets.
Twenty-one samples per cell are not a platform-wide tail-latency guarantee.

## Correctness And Causal Evidence

Every paired run compares original equity/returns/positions/cost/margin buffers,
liquidation state, orders/fills/trades/diagnostics, detailed report shape/labels,
final metrics, trial ledger, sampler trace, candidates, historical revisions,
training membership, descriptors, coefficients, selection/guards/ties and panels.
Unavailable legacy buffers remain explicitly absent, never fabricated as zeros.

Today's observer completion clock necessarily varies with wall time. The harness
checks exactly `actual availability = nominal maturity + measured observer time`
before comparing logical work. It preserves every historical eligibility clock
and identity used by the model. Physical task generation vintages are not logical
information. Raw physical telemetry is retained, not changed in runtime.

Separate Mode 4 and nested Mode 1 tests replay twelve complete chronological
folds each, including actual matured fit/rank and new labels feeding later
folds. Artifact identities that bind physical vintages are resolved to complete
logical payloads; financial measurements, permitted membership, model math and
decisions remain exact. Final stitched account is independently rebuilt.
Existing future/foreign/late-label/near-Q/tie and prepared-account regressions
remain required, not substituted by one final-equity comparison.

## Retained Exploratory Failures

A/A preparation revealed nonportable integer-key tooling output and physical
observer-clock differences; those failures are retained and corrected in the
harness, not the financial runtime. An exploratory write failed on mappingproxy
telemetry; subsequent evidence serializes before creating a receipt file.
The first guarded test run had two tooling failures (incorrect historical path
and a missing predecessor guard amendment); both have exact passing reruns.

The interrupted `matched-v1` remains exploratory. Its baseline subprocess/alias
setup was asymmetric outside the timer. Balanced `matched-v2` was stopped for
a portable type-dispatch edge case: custom metaclass equality cannot be used
as a test for exact built-in identity. Final `matched-v3` uses identity checks
and the same fixtures/repeats/budgets with balanced setup. New negative fixtures
initially required explicit class hashing to reach the intended dispatch test;
both failed fixture receipts are retained. All original files remain retained.
No failed run is rewritten as PASS.

`matched-v3` stopped after 44 complete ordinary cells because its untimed W3
reader used an ordinary metadata key instead of the typed result attribute.
The failed log is retained. Actual off/shadow/active W3 reader tests pass after
the schema correction, including segmented reset-flat accounts, fold/candidate
tables, selected params and task/state/metric provenance. Resume uses separate
attempt logs and does not overwrite completed timing cells or alter execution.

The first conditional cell stopped after 74 complete cells because the sampler
bridge exposes `sampler_wall_seconds`. Exact diff shows only that elapsed value
changes, not RNG/proposals/selection/account. Both actual conditional routes
pass reader parity after excluding that one physical diagnostic from logical
identity; it remains in per-sample raw telemetry and full-call latency. Failed
expected/actual JSON and logs remain retained; completed samples are unchanged.

The first block-only timing overlapped the first post-matrix profile workers.
Both sets remain exploratory. The entire registered paired profile set was
repeated under `isolated-*`, followed by the same 21x50 block measurement after
the profiler exited. Only these later artifacts are primary; main-matrix timing
did not overlap the profiler or heavy financial/regression work. This is a
shared VPS, not a dedicated-machine or platform-wide latency experiment.

## Measured Costs

Read the [generated tables](../../benchmarks/optimization/meta_selection/qms_pre_e06_05_cost.md)
and [complete 76-cell aggregate](../../benchmarks/optimization/meta_selection/qms_pre_e06_05_cost.json).
Tables come from the retained raw samples, not manually selected medians.
All 3,192 warm executions and 152 warmups pass full semantic comparison.

The block-only portable check reduces its 50-call median from 926.42 to 724.85
ms (21.76%). It uses 26 actual frozen synthetic history revisions, with zero
financial calls. It is not an end-to-end WFO or private-alpha speed claim.
The source change is small relative to the legitimate scoring/observer work.

Matched active public-call p50 decreases 2.68% for ordinary pct-equity, 1.80%
for intrabar, 3.47% for W3 reset-flat, 2.06% for portfolio, 2.39% for delivery
roll, 3.02% for prepared pct-equity and 3.68% for nested pct-equity. Callback
event-driven decreases 0.33%; command-tape changes +0.06%, effectively unchanged
in this sample. The generated table includes every domain, prepared and nested
row, including off/shadow/on and original label/auxiliary-evaluation counts.
No superiority confidence interval or broad real-WFO speed guarantee is claimed.

Meta on/off is a different-work cost comparison. For example, ordinary
pct-equity p50 is 102.54 ms off versus 219.83 ms active; intrabar is 188.79
versus 334.32 ms. W3 prepared backtest is 72.32 versus 292.97 ms. Labels,
archives, fit/rank and requested panels are additional work, not unexplained
financial-engine slowdown. Nested Mode 1 also retains and charges the three
additional raw outer-IS evaluations in these fixtures.

### Disabled Latency Gate

25/32 disabled cells meet the registered point budgets. Seven are NOT_MET:
legacy Mode 1 per-fold decay and nested causal, legacy Mode 3/4 global, ordinary
unit, W3 reset-flat and nested pct-equity. The generated table gives every p50/
p95 pair and dispersion remains in the JSON. Six misses are p95-only; nested
pct-equity p50 is +3.36%, against the unchanged +3% threshold.

Both isolated full cProfiles show zero `wire` calls in all seven missed cells.
The changed block did not execute there; this is diagnostic evidence, not a
budget waiver. The measured point budgets remain NOT_MET and statistical
non-inferiority remains uncertified. Owner disposition is required before the
phase can satisfy its cost exit gate; no favorable-cell rerun or automatic
PRE-E06-06 start is allowed.

### Components, Native Resolution And Memory

Thirty primary instrumented profiles cover the eight registered representative
cells plus both arms of all seven disabled misses. They preserve exclusive and
inclusive preparation/witness, scoring, selection, observer, fit/rank, outer-IS,
account/report and unattributed spans. Exclusive spans plus residual reconcile
the instrumented call; adding inclusive nested spans would double-count work.
Zero hook coverage in a legacy report span is not proof of zero report cost.

The pct-equity active fixture records N=37, d=3, 15 origins, P=3. Its existing
Rust require path resolves transform/Gram-solve/rank to Rust, with NumPy
historical scaling/diagnostics and Python-schema/NumPy parameter encoding.
Telemetry records four numeric FFI calls, three qualification calls, 3,254
owned-input copy bytes, native 0.4.3/API 0.4, float64, fast-math false and no
fallback. All observed numeric pools are one-thread and report no thread
mismatch. Per-cell telemetry is retained; these figures are not universal.

Worker peaks are 220.41-306.29 MiB, including cold imports, both controls and
the measurement harness. The largest first-to-last retained drift is 19.08
MiB. Per-arm warm retained medians are reported, but independent arm peaks
are not certified. This patch does not establish an RSS reduction or zero
growth; chronological tests enforce bounded witness-cache retention and
independent candidate/account lifetimes, not a fabricated memory win.

## Source, Regression And Receipt

The final portable dispatch implementation is `0c46c3d`, sealed by
`qms_pre_e06_05_reviewed_source_v2.json`. Tooling corrections, primary matrix/
profiles and source-bound verifier are separately committed. Only this reviewed
runtime file differs from entry; Rust, accounting, metrics, Ridge, samplers,
endpoint signatures/configuration/defaults and scientific guide are unchanged.
The existing qualified native extension remains SHA
`e338a0f1549395211dc42332ed15eb43c0bb92f71728ca3181b0268f56a57aba`.

Scoped qualification requires fresh passing identities from the predecessor's
701-case gate plus all new semantic/type/clock/reader/receipt tests. Duplicate
JUnit identities, missing raw samples, changed budgets, incomplete paired
profiles and changed source/native/guide bytes fail the verifier. Exactly 30
registered scalar-scorer N/A cases are separate from PASS; their routes still
run through their original financial accounts. Private full-study replay is
not rerun: financial source is unchanged and no new alpha study is authorized.

Read the [source-bound receipt](../../benchmarks/optimization/meta_selection/qms_pre_e06_05_closure.json).
2,346 distinct scoped checks PASS, including 77 new phase checks and fresh
coverage of all 701 predecessor identities. Exactly 30 registered N/A cells
are excluded from PASS. The broad meta shard has 2,165 passing cases and four
guard/docs failures: the C05 predecessor guard lacked exact PRE05 normalization,
and current handoff wording omitted three required scope/lineage statements.
Each failure has a separately passing same-ID rerun; old XML is not edited.

Nine external sampler/WFO modules additionally expose two stale expectations:
the discovery table's additive meta columns and G01's already-approved
legacy-zero-base cache identity. Both tests now assert the current contract,
including unactivated-mode discovery and fresh-account/no-cross-run cache
ownership. Trial/params/equity comparisons still pass. Their first failed XML
is retained; the final numerical rerun passes all 162 applicable cases.

The plotting case initially lacked Matplotlib in the G01 consumer. It passes
separately in the existing `.venv` (CPython 3.12.13, NumPy 2.2.6, Matplotlib
3.10.9, Agg backend), with the same source and no dependency installation.
This is a plotting-only proof, not a substitute native/meta provider. The
existing `tight_layout` warning remains nonfinancial and outside this patch;
no chart-layout certification or rendering change is claimed.

The gate binds passing reruns, original failures, all raw samples, registration,
eighteen histories, thirty primary paired profiles/pstats, block cost, current
runtime/verification sources, guide and native bytes. Failure identities cannot
repair themselves, missing reruns fail, and unexpected skips are never waived.
All exploratory failures and current reruns remain separate immutable files.

## Reproduction And Resources

Use the current G01 consumer with `PYTHONPATH=src:.` and OMP/OpenBLAS/MKL/Numba
threads fixed to one. QMS06 historical tests also bind `QMS06_NATIVE_EXTENSION`
to that exact qualified provider and `QMS06_NATIVE_VERSION=0.4.3`; do not silently
load the archived dev2 fixture. The closure contains exact JUnit paths/hashes.
The main commands are:

```bash
python -m tools.qms_pre05_benchmark register
python -m tools.qms_pre05_benchmark matrix --label matched-v3
python -m tools.qms_pre05_profile_matrix --label isolated
python -m tools.qms_pre05_portable_cost --label isolated
pytest -q tests/meta_selection --ignore=tests/meta_selection/test_g01_study_replay.py
```

Evidence writers reject overwrites. These commands describe the registered
run; do not run them over sealed receipts. Registration predates the patch and
records entry bytes/threads/repeats/budgets. Interrupted attempts use separate
logs and only resume uncompleted cells, not retime selected successful cells.
For a new full study, register a fresh lane before observing outcomes.

[Cleanup](../maintenance/QMS_PRE_E06_05_CLEANUP.md) passes: 2,931 protected
file hashes agree before/after. Retained lane occupies 254,722,048 allocated
bytes before the cleanup JSON itself, below the 1 GiB ceiling; available disk
is 28,017,037,312 bytes, above 5 GiB safety. No environment/native build was
created. The only deletion is the inactive generated font cache (45,056
allocated bytes); the observed filesystem gain is 49,152 bytes, not a universal
or task-exclusive storage saving. All workers have exited and evidence remains.

## Remaining Gate And Decisions

| Dimension | Current disposition |
|---|---|
| Implementation | COMPLETE locally |
| Technical | PASS source-scoped parity/regression/cleanup |
| Performance | MEASURED; seven disabled budgets NOT_MET; overall gate NOT_PROMOTED |
| Empirical | NOT_ASSESSED; unchanged R/Q/decay in matched work |
| Owner review | PENDING cost disposition |
| Installed/remote/public | Separate, not certified by source receipts |

Implementation and measured speed are distinct from owner cost acceptance.
Seven disabled point-budget misses keep cost disposition OPEN.
No new economic study was run: exact matched decisions/measurements preserve
the original R/Q and decay, rather than demonstrating a new decay improvement.
Final-source installed wheel/sdist proof remains PRE-E06-06, with its own owner
approval. Economic/default and remote/public qualification remain separate.
