# Mode 5 Remaining Research Coverage

Status: **IN_PROGRESS**, not parent acceptance or package/release approval.
The [registered work](../../upgrade/implement.md#mode5-m5-11-9) completes
missing evidence without repeating the completed RSI or two additional-alpha
optimizers. Private sources, parameter vectors, fills and account buffers remain
ignored and excluded from distributions.

## What Raw/TPE Means

The sampler is the shared `tpe_legacy` recipe. Its feedback/objective is the
original whole-account daily Sharpe. Final selection takes the highest-Sharpe
candidate passing the same registered final eligibility as the challengers,
with the registered candidate-ID tie break. This is **not** the legacy Mode 5
plateau selector. Utility is not the Raw/TPE sampler's objective.

For challengers, `U = net_return - drawdown - daily_loss_ES95`, all in decimal
return units. Fees are already included in returns, not subtracted twice.
Whole-account U must be nonnegative with finite whole Sharpe; risk/support gates
remain unchanged. Annual U is a ranking coordinate, not an every-year-positive
gate. A positive calendar-year return can therefore coexist with negative U.

## Completed Additional-Alpha Evidence

Both original ETHUSDT 1h accounts retain 2020-01-01 through 2026-10-01 exclusive:
59,160 bars, 2,465 days, and an explicitly partial 273-day 2026. Each reported
dictionary is fixed for the entire account, not switched per regime.

The cold readback covers **856 private N1 accounts and 878 private N2 accounts**,
including the original 128-point diagnostic panel and actual formal winners.
It reuses the registered prior-closed-bar 168-hour trend, volatility and activity
features and two separate threshold-fit namespaces. Each family's attributed
PnL reconciles to the original continuous account. These feature buckets are
not independent trials or a fitted bull/bear classifier; annual views and
day-sign views remain distinct.

### Private Alpha N1

| Measure | Raw/TPE | Floor/TPE | Floor/Group TPE |
|---|---:|---:|---:|
| Whole Sharpe | 1.411 | 0.641 | 0.359 |
| Whole max DD | 12.81% | 25.99% | 7.82% |
| Positive calendar views | 7/7 | 6/7 | 5/7 |
| Weakest annual net return | +4.64% | -2.14% | -2.55% |
| Weakest annual U | -0.09284 | -0.17073 | -0.08564 |
| Fills / closed campaigns | 1,042 / 328 | 715 / 357 | 1,652 / 826 |
| Feasible held neighbors measured | 41 | 43 | 41 |
| Held neighbors still passing the full mandate | 95.12% | 93.02% | 31.71% |
| Actual double-fee final equity, from 20,000 | 55,303.09 | 40,154.50 | 18,478.72 |

Raw has positive PnL in every measured trend/volatility/activity bucket.
Floor/TPE loses money in the middle trend bucket; Floor/Group loses 844.82
in the high-volatility bucket. Group TPE's lower whole DD is not a certificate
of robust economics: its selected point is more cost-sensitive and has much
weaker measured neighborhood survival. This is a counterexample to upgrading
all alphas to the same recipe, not a claim TPE is universally best.

### Private Alpha N2

| Measure | Raw/TPE | Pareto/TPE | Pareto/Sobol |
|---|---:|---:|---:|
| Whole Sharpe | 1.649 | 0.872 | 1.392 |
| Whole max DD | 2.95% | 23.49% | 19.44% |
| Positive calendar views | 7/7 | 5/7 | 7/7 |
| Weakest annual net return | +1.13% | -6.76% | +12.85% |
| Weakest annual U | -0.02313 | -0.27783 | -0.02995 |
| Fills / closed campaigns | 395 / 91 | 341 / 73 | 362 / 83 |
| Feasible held neighbors measured | 40 | 39 | 41 |
| Held neighbors still passing the full mandate | 100% | 97.44% | 100% |
| Actual double-fee final equity, from 20,000 | 28,579.19 | 48,292.74 | 118,964.95 |

Pareto/Sobol has positive PnL in all measured trend/volatility/activity buckets
and retains seven positive calendar views. Its weakest annual return is stronger
than Raw's, but DD/tail risk is larger and its weakest U is slightly worse.
Previously measured exposure is about 23.60% versus Raw's 3.49%; the return
increase must not be attributed solely to better parameter precision or an
exposure-matched edge. All arms retain their original, source-specific sizing.

### Held-Probe Interpretation

The 6 actual winners have **245 distinct feasible held-neighbor observations**
across their separate neighborhoods; aliases are retained explicitly. The
original dictionaries were independently rerun, and six actual double-fee
accounts regenerated strategy/execution feedback. Equity, positions and fees
reconcile to an independent fill ledger; baseline center replays match their
original saved paths. No winner is changed using these held outcomes.

The complete registered feasible rosters have run, but the existing geometry
owner reports `INSUFFICIENT_COVERAGE` at the requested radius 0.12: source
quantization, boundaries and coupled joint directions prevent some required
distances. Survival percentages describe **tested feasible points**, not a
full-dimensional or radius-wide basin certificate. No threshold is lowered
after seeing these results. Checks use whole U and the complete mandate, not
a fictitious requirement that every annual U be nonnegative.

## Remaining Original-Alpha Formal Arms

SC, HASH and VWAP passed full-history research/audit path parity against the
original financial evidence, including selected audit fill reconciliation.
Their original **BTCUSDT** 1h scope ends 2026-10-06 exclusive. N1/N2 use ETHUSDT
and end five days earlier; there is no matched cross-symbol performance race.

Three separate 256-attempt studies per admitted alpha are source/dossier sealed:

| Alpha | Baseline | Recipe/TPE | Same Recipe / Sampler Challenger |
|---|---|---|---|
| SC | Raw/TPE | Floor/mean | Multivariate/group TPE |
| HASH | Raw/TPE | Lower-environment-tail | Sobol |
| VWAP | Raw/TPE | Pareto/Chebyshev | Conditional latent Sobol |

These are registered research hypotheses grounded in the existing dossiers,
not inferred sampler superiority. HMA remains NO_ELIGIBLE_COHORT; its mandate
is not relaxed. The local supervised formal queue permits at most two financial workers,
one numeric thread each, an owner-amended 2 GiB owned-RSS and 1 GiB retained-output ceiling,
512 MiB available RAM and 5 GiB free-disk reserves. It retains the shared exact
Optuna continuation journal; completed observations and trials are reused.

The initial two-worker queue reached its resource guard and retained 63 SC and
4 HASH terminal trials. The first operational retry used **one worker** and
collects unreachable objects only after the original account observation returns.
It resumes the same sealed typed sampler session, not a new seeded study. The
stopped attempt and uncommitted buffers remain separate; a missing observation
is never fabricated from an incomplete receipt. No resource ceiling is raised.
The later admitted parallel lease below restores at most two workers without
changing that account observation or continuation contract.

Operational admission exposed repeated per-bar resource-directory scans.
One-second operational sampling, with mandatory per-account checks, preserved
bitwise financial paths and original annual/whole metrics. Fixed controls were
SC 8.13 s, HASH 24.22 s and VWAP 12.77 s. These are controls, **not whole-study
ETAs or a universal speedup benchmark**. Failed transport-witness admission
attempts and superseded pre-search seals remain retained. Their initial small
engineering-control estimate was exceeded; it is not hidden in accepted search
work. No financial estimator or tolerance was changed to pass admission.

Raw/TPE versus recipe/TPE is not by itself a pure selector-only test: changed
feedback changes TPE's later proposals. Reuse the fixed-panel comparisons for
selector-only attribution. Recipe/TPE versus its matched challenger tests a
sampler policy under the same objective/budget; one seed does not establish
universal superiority.

## Exit Still Pending

All of the following are already authorized under M5-11.9, including background
execution. They are not separate approval requests. The existing formal queue
retains its exact source/checkpoint identity; a guarded successor waits for its
exclusive lock and nine complete256-attempt receipts, then runs the missing
RSI/original-alpha held and actual-fee checks, original-panel regime readbacks,
seven-alpha synthesis and terminal research qualification. It inherits the
original24-hour deadline and unchanged resource limits. A technical/resource
failure remains a retained failure, never an automatic phase PASS.

The final private outputs are `C05/report.json.gz`, `C05/report.md` and
`C06/complete.json`, with pinned inputs and a separate stage work ledger. Their
existence/status must be checked before calling this scope complete; wiring
the successor is not evidence that its financial work has already finished.

### Successor Attached

The source-pinned successor is running (owner PID2383312), waiting on the
original supervisor's financial lock; it does not start a second financial
worker. At the attachment check, **all three SC arms are complete at256attempts
each** and HASH Raw/TPE has resumed its original checkpoint. HASH's other arms
and all VWAP formal arms remain scheduled, not completed. No finished optimizer
is restarted and no staged admission is substituted for a market result.

The tail reuses the exact active `release-regression-v1` environment and pins its
prefix/config and numeric package versions. Foreground verification includes
53queue/readback tests and23synthesis tests; the31held/synthesis checks also pass
in that exact queue environment (overlapping tests are not extra scientific
samples). Ruff passes. Actual cold admission covers the old RSI inputs, six
N1/N2 formal/winner/state joins and HMA's128-point matrix with no financial runs.
The original five-panel regime and missing actual-winner financial checks still
must finish through the registered tail before its terminal certificate exists.

### Parallel Formal Scheduling

The latest owner instruction permits VWAP alongside HASH after current RSS/RAM
admission. A separate controller delegates scheduling without editing the
source-pinned serial runner or interrupting its current financial HASH child.
At most one study per alpha runs at once; trial order/RNG remains sequential
within each study. The original scheduler is paused while this lease is active,
then resumes to skip completed studies and release the existing tail lock.

The same aggregate memory, disk, retention and absolute deadline limits apply;
only the formal-study worker count returns to at most two. Resource pressure
can retain/interrupt the new VWAP attempt and fall back to serial execution;
uncommitted work is reported separately, not counted as another successful
trial. The later winner/reporting tail remains serial. Earlier serial ETA is
not a matched measurement of Mode5 overhead and must be re-estimated from the
actual parallel alpha work; a single expensive initial trial is not a stable
whole-study timing estimate.

Live verification at **2026-10-19 17:38 UTC** (20 October 00:38 in Vietnam):

| Alpha | Raw/TPE Attempts | Recipe/TPE | Recipe/Challenger |
|---|---:|---:|---:|
| SC | 256, complete | 256, complete | 256, complete |
| HASH | 175/256, running | pending | pending |
| VWAP | 174/256, running | pending | pending |

The original HASH PID2383609 remains uninterrupted; VWAP PID2398754 is active
alongside it. The paused serial scheduler is an intentional scheduling lease,
not a paused financial account. Combined owned RSS is about 1.03 GiB, available
RAM about 2.75 GiB, and free disk about 6.45 GiB; retained phase output is about 322 MiB.
Both financial processes have one OS thread in this readback. The adopted HASH
owner declares its original three numeric-thread environment controls; the new
controller declares six. An initial verifier incorrectly required all six on
the old worker; that read-only failure is retained, and the corrected check
records declared controls separately from observed threads without changing
either live process.

The final mocked-controller regression passes **28 tests**; Ruff passes for
the controller, its tests and the read-only attachment verifier. The attachment
receipt rechecks **36 distinct protected source/artifact/evidence files** and
confirms no completed optimizer restart or scientific-contract change. These
are operational checks, not new market evidence or a finished phase. Private
`parallel-attachment-verification.json`, `parallel-progress/` and the cleanup
receipts retain the exact snapshot. All remaining arms and the registered
winner/regime/qualification successor remain scheduled automatically; final
`C06/complete.json` and `end-to-end-complete.json` do not yet exist.

### Two-GiB Continuation Lease

After the first parallel controller reached its 1.25-GiB aggregate RSS guard
during VWAP's final audit, the owner explicitly approved **2 GiB aggregate RSS**
for the formal queue. The failed/interrupted audit remains retained; its 256
committed trials are not rerun. Available-RAM, retention, disk and absolute
deadline guards remain unchanged. The later research tail stays serial with
its original limits. This is not an increase in trials or a methodology change.

At 2026-10-19 18:39 UTC, the new source-pinned controller PID2431430 delegates
scheduling from its predecessor, which is intentionally paused. HASH recipe/TPE
keeps its original live PID2418621; VWAP PID2431449 resumes Raw/TPE audit from
the exact 256-attempt checkpoint. SC's three studies and HASH Raw/TPE are
complete; HASH recipe/TPE has 67 recorded attempts in this snapshot. Remaining
per-alpha arms are scheduled automatically, with no concurrent workers on the
same alpha. Completed studies are skipped, not restarted.

The latest live telemetry is **`parallel-v2-progress/`**, not the intentionally
paused predecessor's `parallel-progress/`. On completion, the new controller
resumes its predecessor, whose existing checks cascade to the original
financial-lock handoff and registered winner/regime/report successor. Unknown
financial/source errors still fail closed; a new resource pressure event can
retain VWAP's checkpoint and fall back serially under the approved limits.

The focused new mocked ownership/guard regression passes **20 tests** in
0.43 seconds; Ruff passes. These tests cover the lease, original-child custody,
completed-study skipping, checkpoint routing, 2-GiB/startup/RAM/disk/deadline
guards, PID/source failure and cleanup. They do not replace actual-account
oracles or certify unfinished financial outcomes. Earlier fixture/setup
failures remain separate XML receipts. Exact inactive fixture cleanup preserves
23 protected files and all live/financial evidence; no environment or service
is stopped. The new registration, launch, lease and cleanup receipts use the
`parallel-v2-` prefix under the same private attempt directory. No end-to-end
speedup is claimed before its full workload finishes.

The read-only attachment receipt at **18:41 UTC** confirms 26 distinct source
pins unchanged and one observed OS thread per financial worker. VWAP Raw/TPE
has now completed its missing audit; the controller automatically starts VWAP
recipe/TPE PID2431813. Both recipe studies are live: HASH69/256 and VWAP16/256
at this snapshot, with both challenger arms still pending. Combined owned RSS
is about 1.20 GiB, available RAM about 2.49 GiB, free disk about 6.37 GiB and
retained phase output about 394 MiB. The original HASH PID remains unchanged.
`parallel-v2-attachment-verification.json` records actual process/receipt
identities, not a forecast or completed research certificate.

- Complete the nine formal arms or obtain an explicit owner disposition.
- Qualify the newly selected original-alpha winners and remaining RSI held
  checks; old diagnostic-center probes cannot replace them.
- Join all seven-alpha state/local/stress/search findings and reconcile the
  parent coverage ledger for owner review.
- Final-source reporting regression, privacy, work accounting and exact scratch
  cleanup; M5-12, CI and release remain separately authorized later work.

Current affected source regression: **529 passed**. It covers environment
rights/attribution, geometry, eligibility, original event producer, objectives,
Pareto, dossier governance and the new cold readbacks. A pre-existing binary
hash test now verifies the exact loaded binary against the producer witness,
rather than requiring an obsolete build hash. Earlier setup failures are
retained separately; the final run uses a prepared absolute fixture root.
This does not certify unfinished financial studies.

[Cleanup](../maintenance/M5_11_9_CLEANUP.md) removed only reviewed superseded
consumers and terminal fixture scratch. Old evidence and exact artifacts remain;
there is no environment rebuild, service shutdown, source-alpha or core change.

Authoritative private receipts are under
`upgrade/private/mode5_upgrade_v1/m5-11-9/attempt-01`: `C01` admission,
`C02/*-states.json.gz`, `C02/*-panel-qualification.json.gz`, actual-market
`C02/future-mutation.json`, `C03/*/qualification.json.gz`, source-frozen
`C04-v2` plans/studies and `queue-progress`. The historical rights mutation
proof concerns frozen environment thresholds/labels, not an automatic
whole-procedure recipe-routing claim. Development results remain reviewed,
not independent OOS.
