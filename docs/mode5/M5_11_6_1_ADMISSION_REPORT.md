# M5-11.6.1 Quarterly Research Admission

## Status

Date: 2026-10-16 UTC. Owner approved implementation of
[M5-11.6.1](../../upgrade/implement.md#mode5-m5-11-6-1).
**IN_PROGRESS / Q03_NOT_ADMITTED / FAST_VARIANT_DESIGN_FOR_REVIEW**.
This is an admission/implementation report, not the final quarterly economic
decision report. No optimizer, new learned model, quarterly R/Q comparison or
background research queue has run. M5-11.7, packaging and release are not started.
The owner subsequently requests resource cleanup and option 2, a fast intrabar
variant design for approval before implementation/finance. The
[proposed variant contract](M5_11_6_1_FAST_VARIANT_DESIGN.md) makes each semantic
change explicit; the original-route non-admission and evidence are unchanged.

Authorities: QMS [mathematics](../../upgrade/QUANTBT_1_1_1_META_SELECTION_AND_SAMPLER_MODULE_GUIDE_V1_1_VI.md#s5),
[history/availability](../../upgrade/QUANTBT_1_1_1_META_SELECTION_AND_SAMPLER_MODULE_GUIDE_V1_1_VI.md#s6),
[causal execution](../../upgrade/QUANTBT_1_1_1_META_SELECTION_AND_SAMPLER_MODULE_GUIDE_V1_1_VI.md#s7)
and [economic scope](../../upgrade/QUANTBT_1_1_1_META_SELECTION_AND_SAMPLER_MODULE_GUIDE_V1_1_VI.md#s14);
Mode 5 [geometry](../../upgrade/QUANTBT_MODE5_UPGRADE_V1_DIAGNOSTICS_FIRST_GUIDE_VI.md#45-trục-2--parameter-geometry-và-landscape)
and [separated experiments](../../upgrade/QUANTBT_MODE5_UPGRADE_V1_DIAGNOSTICS_FIRST_GUIDE_VI.md#49-multi-hypothesis-empirical-battery-giữ-năm-chiều-làm-rõ-mỗi-phép-thử).
Machine-readable measured data: [admission readback](M5_11_6_1_ADMISSION.json).

## Implemented Contracts

- Nineteen complete UTC quarters, 2022-Q1--2026-Q3; 1,734 forward calendar days.
  Every IS is exactly 365D, with permitted indicator preload from 2020. A later
  snapshot cannot add partial October. Preload is not scored account history.
- One-account attribution into 91/91/91/92-day segments, without position resets.
  The research selector uses ddof=1 daily-account Sharpe annualized by sqrt(365),
  at least 60 available valid daily observations and nonzero variance per segment.
  Score is `min(S_e) + 0.25 * day_weighted_mean(S_e)`. This is not Mode 5 utility
  or a replacement for the existing raw IS/FWD metric used in meta labels.
- Explicit null/missing/bankruptcy dispositions, fixed calendar weights,
  deterministic candidate-ID ties, no all-segments-positive gate and no fake
  zero Sharpe. This pure selector does not certify its financial producer.
- Whole-work budget arithmetic, preparation-inclusive control validation and
  fail-closed timing admission. A timing PASS alone never permits launch;
  measured resources and the remaining gates still need admission.
- Cold control readback with a public allowlist; private parameters, market
  rows, alpha sources and raw account outcomes are not exported.

The implementation is isolated under `tools/mode4_quarterly/`. Public endpoints,
Mode 1--5 defaults, alpha sources and financial engines are unchanged.

## Prefix Diagnostic Reuse

The first-origin records precede 2022. No 2022+ forward outcome was used in this
cold geometric screen. Original adaptive TPE pools are not neutral QMC designs,
independent Sobol sensitivity samples or evidence of causal parameter effects.

| Alpha | Recorded Candidates | Matching Current Geometry | Distinct Matching Points | Source Scope |
|---|---:|---:|---:|---|
| SC | 128 | 128 | 128 | Original ETH 730D first-origin IS |
| HMA | 127 | 127 | 127 | Original ETH 730D first-origin IS |
| HASH | 119 | 119 | 119 | Original ETH 730D first-origin IS |
| VWAP | 127 | 127 | 127 | Original ETH 730D first-origin IS |
| RSI | 128 | 48 | 48 | Earlier RSI pct-equity first-origin study |

These are captured eligible/recorded candidates, not a claim of 128 valid unique
points in every pool. Missing/pruned slots remain part of attempted-work counts.
The RSI source ranges differ from the current Mode 5 schema: 80 records fail
that schema. Exclusions are retained; no values are clipped or silently recoded.
The matching 48 do not satisfy a new 128-point diagnostic design. Earlier RSI
evidence is not invalidated by its incompatibility with this new schema/account.

The worksheets retain active dimensions, inactive source knobs, conditional
branches, coupled constraints, nearest-neighbor geometry and descriptive rank
associations. Prefix-authorized independent local probes and new 365D account
environment observations are still missing. Whole-period Mode 5 probes are not
relabelled as these prefix observations. Multivariate/group TPE is recorded only
as a provisional compatible joint-search hypothesis, not an empirically selected
winner, frozen search recipe or validated automatic router.

## Measured HMA Admission

Eight fixed original-route controls use saved low/high-activity first-origin
parameters, two early/late cutoffs and two repeats. Each scores 365D / 8,760
hourly bars on ETHUSDT with the original fixed-notional account and costs.
No new candidate was proposed and no alpha feedback/ladder was simplified.

The existing qualified candidate extension and delta-feedback provider are
reused, not rebuilt. Timers include preparation, command/actual-feedback native
execution and the bounded daily reduction. Imports/context loading are retained
separately and excluded from these spans. Process CPU time was not retained;
projected work is **elapsed worker-seconds**, not measured CPU-seconds.

| Control Group | Repeats | Minimum | Median | Maximum |
|---|---:|---:|---:|---:|
| Early, lower activity | 2 | 3.419 s | 3.635 s | 3.850 s |
| Late, lower activity | 2 | 4.376 s | 4.408 s | 4.441 s |
| Early, higher activity | 2 | 7.236 s | 7.939 s | 8.641 s |
| Late, higher activity | 2 | 7.095 s | 7.250 s | 7.406 s |

All-eight median is **5.768 s**; maximum process peak RSS is **307.24 MiB**.
The seven-control parallel tranche takes 19.896 s; the first completed control
is reused rather than executed again. Worker contention and small fixed samples
preclude a p95, adaptive-study runtime distribution or universal speed claim.

Each control already has **one Rust session and zero full-tape executions**.
The sampled lower/higher-activity controls make 26,427--26,740 native boundary
calls across 8,760 committed bars, including 147--460 same-bar steps. The
prepare/compiler span dominates these controls; this does not partition Python
versus Rust CPU time. Merely renaming the endpoint or removing an already absent
full-tape replay would not remove this strategy/feedback work.

## Budget Decision

The proposal has 19,456 primary plus 2,432 RSI slots: **21,888 total** before
observer, diagnostic, control and final-account work. Two native anchors have
two anchor-first base panels; their physical union is deduplicated, not assumed
to be one shared sixteen-member panel. The conservative forecast reserves up
to 36 forward candidates per primary sampler pool and 18 for the RSI reference.

HMA alone has 4,864 search slots. Using its observed maximum and ideal division
across four workers gives **2.919 hours** for that search component. Substituting
the observed median gives **1.948 hours**. Both exclude all other alphas,
observers, final accounts and unmeasured roles; they are conditional models, not
hard physical lower bounds or ETAs. Root-owned preparation reuse and a different
future candidate distribution could change actual cost, but are not measured
full-study acceleration here.

Result: **REJECT_PARTIAL_SEARCH_FORECAST_EXCEEDS_CAP** against the approved
90-minute queue target. The planned first-tranche early-exit avoids spending
more finance on SC/HASH/VWAP/RSI before this gate is resolved. Their missing
timings are explicit, not zero. No reduced-trial/shortened-calendar substitute
was launched, and no quarterly economic superiority is inferred.

## Independent Review And Tests

The first review fixes two defects before any study consumes the new helpers:

1. Pandas nanosecond day labels could inflate support: four actual calendar
   days were synthetically accepted as 240 observations. The reproduction and
   pre-fix source copies remain private; submicrosecond day labels now fail.
2. Timing-only admission previously exposed a launch permission. It now reports
   `timing_admitted` separately and always leaves `launch_allowed=false` until
   an independent resource/whole-work gate has been applied.

Neither issue affected a financial decision: actual optimizer calls/meta fits
are zero. Contract/admission tests before independent review passed 95 nodes;
that earlier receipt is retained and is not presented as coverage of the fixes.
Final regression adds explicit nanosecond, launch-gate and readback tests; its
**104 tests pass in 2.16 seconds**, with the retained receipt
`attempt-03/pytest-final.xml` and source hashes in cleanup custody. These are
pure-tool contract tests, not full quarterly WFO/accounting qualification.

Pilot attempts 01/02 retain three pre-execution plumbing failures: source import
path, OHLCV dtype normalization and an old artifact missing feedback-session
capability. Attempt 03 reuses the established context/qualified-artifact loader;
it supplies all eight successful financial controls. Failed receipts remain
failed, setup work is not erased and no new native build was needed.

## Remaining Work And Decision

Q01/Q02 are reconciled but not a complete new financial diagnostic dossier or
sealed calibration recipe; Q03 has a measured non-admission. Q04 supplies only
pure contracts/reducers/admission/readback, not the full factorial WFO hook.
Q05 search, Q06 actual quarterly selection/meta/accounting/causality, and Q07
quarterly R/Q/economics have **NOT_RUN** status. Q08 remains an owner route/scope
decision, not a completed upgrade certification.

Current recommendation is **KEEP_DEFAULT_UNTIL_MATCHED_RESEARCH_IS_ADMITTED**.
This is not evidence that diagnostics, another sampler or meta cannot help.
The owner chooses designing an explicitly scoped fast research variant for
review, alongside completed resource cleanup. Variant adapters/studies remain
unimplemented and unlaunched; no original-route budget increase or endpoint
promotion is inferred. The nineteen-quarter calendar
still allows at most about six actually learned decisions under current label
publication semantics; no twelve-mature-evaluation-quarter claim is possible.

Private retained root: `upgrade/private/mode5_upgrade_v1/m5-11-6-1/`.
The [cleanup receipt](../maintenance/M5_11_6_1_ADMISSION_CLEANUP.md) covers only
reviewed phase scratch, preserved source/evidence hashes and reaped workers.
No source, market, financial evidence, package environment or service is deleted.
The public JSON is the immutable measured admission snapshot written before the
owner's variant-design choice; this report and the plan carry the current scope.
