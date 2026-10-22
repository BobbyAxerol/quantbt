# M5-10 Public Runtime Qualification

## Disposition

**COMPLETE_LOCAL_PUBLIC_OPT_IN / TECHNICALLY_VALID**, 2026-10-10.
This qualifies the approved integration scope, not a release, automatic recipe
router, independent OOS result or economic improvement. M5-11 and M5-12 remain
separately approved phases. The five real M5-09 plans remain sealed
`DEFER_CALIBRATION`; fixed-coordinate controls below do not authorize their search.

Authority: [unified plan](../../upgrade/implement.md#mode5-m5-10),
[detailed work packages](../../upgrade/QUANTBT_MODE5_UPGRADE_V1_DIAGNOSTICS_FIRST_GUIDE_VI.md#phase-m5-10--public-mode5-binding-inherited-samplers-và-prepared-runtime),
[requirements](../../upgrade/QUANTBT_MODE5_UPGRADE_V1_DIAGNOSTICS_FIRST_GUIDE_VI.md#m5-10--mode5-integration-và-kế-thừa-mode4).
Read the [usage and limits](PUBLIC_CALIBRATION_V1.md),
[machine-readable evidence](evidence/m5-10.json) and
[cleanup receipt](../maintenance/M5_10_CLEANUP.md).

## What Changed

| Work package | Implemented boundary |
|---|---|
| M510.01 | Optional `optimization_config.mode5_calibration` on existing `QuantBTEndpoint.walk_forward`; Mode 5/global only. Verified dossier, plan, rights, full input/economics/schema, source dependencies and chronology are checked before execution. Legacy calls retain their defaults/hash. |
| M510.02 | Shared `SamplerConfig` and WFO sampler registry, portable typed ranges, exact seed/startup/warm-start configuration, effective conditional dimensions and observable fallback/duplicate provenance. Changing only the sampler does not activate meta or new selection. |
| M510.03 | Original endpoint equity and retained accounting, canonical UTC daily account reduction, utility/raw Sharpe/PSR with distinct fields, support/undefined/bankruptcy policies and the existing versioned M5-07 selectors. |
| M510.04 | Shared ordered ask/tell scheduler. Sequential and fixed-batch semantics are explicit; cancellation, deadline, pruned/failed/unexecuted asks and duplicate evaluation references are retained. No fabricated complete trial or exact parallel trajectory. |
| M510.05 | Existing prepared market/calendar and original financial execution cache; required paths retained, no heavy report per trial. Canonical numeric reduction uses Numba; eligible original Rust financial endpoints remain usable. No second simulator, sampler registry or cache. |
| M510.06 | Selected fixed-vector audit through the original endpoint; account components, fills/feedback and objective reconciliation. Fresh installed wheel and sdist-rebuilt consumers run outside the checkout with private adapters supplied externally. |

Canonical scientific/governance implementations now live in focused
`src/quantbt/mode5` modules. Historical `tools/mode5_*` imports are compatibility
aliases, not copied formula implementations. Thin WFO/endpoint hooks declare
retention and delegate selection; no financial Rust source or account engine
was rewritten. Historical protected source checks accept only exact reviewed
additions and still reject an unreviewed byte change.

The returned full-development account may execute only registered development
witnesses. Each calibration environment is explicitly an
`independent_reset_flat_v1` observation; the final account is a separate
`original_endpoint_full_development_v1` run. Reset observations are not relabeled
as continuous calendar attribution or spliced into a best equity curve.

## Requirement Traceability

Fixture families: `public_setup` creates sealed, public synthetic diagnostic
inputs; the execution fixture uses original intrabar, callback and command
endpoints. `test_public_lifecycle.py` uses real OCO protection, amend/cancel,
margin rejection and position-based fill feedback, independently replayed on
Python and Rust. These are software tests, not market-economics studies.

| Requirement | Actual assertions and final receipt |
|---|---|
| M5T-091 | Frozen legacy Modes 1..5, shared QMS/meta, preparation and metrics regression: `regression-final-08`, `meta-regression-10`; sampler-only legacy tests in `mode5-final-14`. |
| M5T-092 | Four `test_sampler_only_legacy_mode5_does_not_activate_opt_in` cases and inherited sampler cases assert no meta/new-selection activation: `mode5-final-14`. |
| M5T-093 | Actual TPE independent/grouped registry settings, conditional boolean/categorical rows and portable distribution identities: `mode5-final-14`, shared QMS sampler regression. |
| M5T-094 | Actual CMA categorical rejection and explicitly independent fallback with recorded calls: `mode5-final-14`. No full mixed-space covariance claim. |
| M5T-095 | Actual 128/256 Sobol asks, startup, sequence position, projection and collision references: `mode5-final-14`. Mixed panels are not called balanced Sobol designs. |
| M5T-096 | Repeatable ordered ask/tell for batch size 1/3, matched prepared/fresh objectives; unsupported multiple workers denied before alpha; cancellation/failure/deadline terminal states: `mode5-final-14`. |
| M5T-097 | Warm starts with foreign objective scores denied; stale data/economics/schema/seed/budget, changed evidence and deferred/unsealed plans denied: `mode5-final-14`. |
| M5T-098 | Actual public selected recipe, three resolved selectors and explicit researcher-choice fourth slot; selected audit, returned output and no-selection exception metadata verified: `mode5-final-14`. |
| M5T-099 | Actual financial endpoint protection/OCO, amend/cancel, rejected oversized order and feedback-derived exit match independent replay: `lifecycle-final-13`, `mode5-final-14`, installed consumers. |
| M5T-100 | Public execution/audit on Python and Rust plus externally supplied actual-owner private controls; exact account/fill replay and source/wheel/sdist parity: `mode5-final-14`, `source-five-03`, `v2-wheel-reviewed-five`, `v2-sdist-five`. |

Final source panels: **1,608**, **265**, and **485** tests PASS, zero failures
or skips in those runs. They overlap; the certification union contains
**1,876 distinct source cases**, not their sum. The lifecycle/rights reruns are
also overlapping. Optuna experimental warnings are retained, not suppressed as
errors or counted as failed financial execution.

Four additional metadata-only report tests PASS; the final documentation
reconciliation checks full-precision benchmark values, retained artifact hashes,
current canonical module bytes and all 2,757 protected hashes. Local Markdown
links/anchors pass. This final check creates no scratch or financial rerun.

Both installed consumers pass **50 public cases** each. One Git-history-only
source-amendment assertion is intentionally deselected outside the checkout;
it passes in the source suite. Installed cases cover calibration, boundaries,
the documented example and lifecycle. All loaded `quantbt*` and native module
origins are asserted inside the consumer, with no checkout import fallback.

The append-only private lane is
`upgrade/private/mode5_upgrade_v1/m5-10/attempt-01`. Each command JSON has the
exact argv, elapsed time and log/XML references. Failed attempts remain there;
their later repairs did not rewrite them. Representative source reproduction:

```bash
python -m pytest -q tests/mode5 \
  tests/test_walkforward_phase1.py \
  tests/test_phase49a_walkforward_schedules.py \
  tests/test_phase49b_wfo_performance.py \
  tests/test_phase64_wfo_correctness.py \
  tests/test_phase74_public_wfo_native.py \
  tests/test_perf_05_wfo_evaluation_reuse.py \
  tests/test_perf_08_wfo_preparation.py \
  tests/meta_selection/test_qms02_samplers.py \
  tests/meta_selection/test_qms06_prepared.py \
  tests/meta_selection/test_c04_continuation.py \
  tests/meta_selection/test_execution_window_public.py \
  tests/meta_selection/test_e07_lifecycle.py tests/metrics
```

Use the compatible native pair and optional test/report dependencies for that
command. The exact local receipts used CPython 3.12, NumPy 2.2.6, Optuna 4.8,
CMA-ES 0.12, one Numba/BLAS thread and the controlled current test environment.
Public case commands and all additional regression argv are retained in the
certification lane. Cleaned installed environments require fresh installation.

## Five Actual Alpha Integration Controls

Each private alpha uses its original qualified adapter, actual market witness
marked `DEVELOPMENT_REVIEWED`, one fixed coordinate, 2,184 hourly scoring bars
in the registered 2023 development window, and 365-day preload. This is a
91-day binding/accounting control, not adequate independent transfer evidence
or a formal real search. No private source, presets, vectors or returns are
published or packaged.

| Alias | Original financial scope | Accepted fill evidence |
|---|---|---|
| A-RSI | Legacy `%_equity` account | Accepted-fill ledger unavailable; not a zero-fill claim |
| A-SC | Feedback callback, Python | 18 |
| A-HMA | Actual-feedback command tape, Rust | 229 |
| A-HASH | Original command contract, Rust | 118 |
| A-VWAP | Original command contract, Rust | 62 |

Selected-coordinate identity, final equity and available fills agree exactly
between source, fresh wheel and sdist-rebuilt wheel. Available original account
components reconcile with **maximum absolute difference zero**. The three
static command controls additionally reconcile original Python reference
order/fill/protection traces. No generic callback is advertised as Rust-owned.
Synthetic diagnostic fixtures authorize only software controls; the final
real market roles and unchanged deferred real plans remain explicit.

## Matched Public Performance

Three registered repeats per case, fresh process per repeat, same 8,760 bars,
16 fixed unique warm-start coordinates, seed 731, one worker/numeric thread,
same diagnostics, selection and selected audit. Timing includes the full
public backtest and final result adaptation, excludes separately registered
warmup, and is not an isolated kernel number. Candidate/objective trajectory,
selected vector, selected audit and final equity identities match in all cells.

| Panel | Prepared off median | Prepared on median | Off RSS median / max | On RSS median / max |
|---|---:|---:|---:|---:|
| Cache-start, financial kernel warm; reporting compilation included | 5.335503 s | 4.995516 s | 268.391 / 269.625 MiB | 267.664 / 268.277 MiB |
| Fully warm financial and reporting kernels | 910.998 ms | 903.934 ms | 266.547 / 266.633 MiB | 266.031 / 267.461 MiB |

Fully warm median time is **0.78% lower**, too small and noisy for a meaningful
speedup claim; no RSS reduction is established. The cache-start/fully-warm
difference is primarily warmup/compilation, not a new algorithm speedup.
Prepared off/on share the M5-10 methodology; neither is compared to a cheaper
legacy scalar-Sharpe contract. This panel uses the original legacy Numba
`pct_equity` account, not Rust, and does not rank adaptive sampler quality.

Each study bills 16 query attempts, 16 effective candidates and 17 original
account observations (candidate observations plus selected audit), with zero
heavy per-trial reports. The final returned account execution is separate from
those 17 observations. Required equity/daily/component evidence remains
retained; terminal-only native scalar scoring is correctly ineligible.
Failed work remains inside elapsed billing. Actual BLAS/Numba thread telemetry
is one. The historical benchmark's `market_reuse` field is null, so it does not
support a claim about cache-hit counts; reuse correctness is tested separately.

## Artifact, Privacy And Resource Gate

Local pair **1.1.2 / 0.4.3**, no version bump or publication. Wheel and
sdist-rebuilt wheel contain **308 canonical Python modules**, byte-exact to
the qualified source. Artifact allowlists exclude private alpha/data/evidence
and loaders. Exact SHA-256 values are in the public evidence JSON.

An older same-version native wheel lacked the already implemented G01
`metric_zero_base_policies` capability. That wheel was not reused as qualified
merely because its version matched. A registered offline, locked release build
of unchanged current Rust source produced a new exact native wheel; installed
capability, accounting and consumers pass. Build time was 65.276 s. The failed
receipt and old wheels remain preserved. This closes the local artifact issue;
it is not a financial/scientific repair or a new Rust implementation.

Native wheel scope is **CPython 3.12 / Linux x86_64 / manylinux_2_34** locally.
Fresh consumers install exact artifacts outside checkout but borrow the pinned
controlled dependency set offline. This is not clean internet dependency
resolution, Ubuntu/CPython remote matrix or public PyPI consumer qualification.
Final product/platform/publication gates remain M5-12 and separate approval.

Host audit: 162 processes, no scratch references/FD/maps or inspection errors.
Only exact registered ignored inactive scratch was removed. **2,757 protected
hashes**, 491 retained files and 317 source/harness hashes verify unchanged.
Observed filesystem recovery: **386.48 MiB**; retained lane payload: 43.14 MiB.
Current tooling, offline dependencies, private evidence and exact artifacts
remain. See the [cleanup receipt](../maintenance/M5_10_CLEANUP.md).

## Limits And Next Approval

No remaining in-scope local implementation/artifact/cleanup blocker is known
under the tested contracts. Unsupported capability is explicit: other M5
schedules, multiple callback workers, arbitrary unsealed policy callbacks,
automatic advisory routing, partial-path pruning and automatic exact run resume
are not silently enabled. Required path retention prevents claiming a cheaper
terminal-score workload as equivalent. Optional original Rust execution is not
ownership of Python strategy decisions.

M5-11 must register/approve actual recipes, sufficient horizons/events/support
and forward data rights before formal calibration/economic inference. These
tests do not weaken earlier NO_SELECTION or economic support gates. M5-12
performs final whole-program qualification; no remote CI, push, merge, tag,
release, PyPI upload or live deployment was performed in M5-10.
