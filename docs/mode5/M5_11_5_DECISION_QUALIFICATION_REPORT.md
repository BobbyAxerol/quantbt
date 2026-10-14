# M5-11.5 Diagnostic-Guided Decision Qualification

Date: October 14, 2026 (Asia/Saigon).
Status: **REGISTERED FULL-DEVELOPMENT STUDIES COMPLETE; FINAL C07/C08 REVIEW OPEN**.
No release, installed-current-source package certification or independent OOS
claim follows from this report.

Authority: [unified work packages C01--C08](../../upgrade/implement.md#mode5-m5-11-5),
guide [separate comparisons](../../upgrade/QUANTBT_MODE5_UPGRADE_V1_DIAGNOSTICS_FIRST_GUIDE_VI.md#49-multi-hypothesis-empirical-battery-giữ-năm-chiều-làm-rõ-mỗi-phép-thử),
[scientific interpretation](../../upgrade/QUANTBT_MODE5_UPGRADE_V1_DIAGNOSTICS_FIRST_GUIDE_VI.md#58-statistical-inference-và-phép-kiểm-có-ý-nghĩa-kinh-tế-không)
and [freezing points](../../upgrade/QUANTBT_MODE5_UPGRADE_V1_DIAGNOSTICS_FIRST_GUIDE_VI.md#67-exact-freezing-points).

## Scope And Prospective Preferences

Reuse all five [M5-11.4 diagnostic dossiers](M5_11_4_FULL_DEVELOPMENT_REPORT.md).
Their 128 discovery points per alpha, private source, original financial routes,
parameter ranges and negative observations remain unchanged. New RSI studies use
January 1, 2020 through October 6, 2026 exclusive: **59,280 hourly bars / 2,470
complete UTC days**. Indicator readiness remains flat in the original strategy;
2026 has 278 complete days. Annual environments are views of one continuous
account, not independent account resets or independent statistical samples.

The owner-approved versioned mandate requires whole-account U >= 0 and finite
whole-account Sharpe, DD <= 50% for whole and annual paths, and at least 180 daily
observations in every annual environment. Annual U may be negative and remains
in floor/tail ranking. The earlier all-year-positive mandate and cash-dominated
outcomes remain immutable; they are not retrospectively relabelled as successes.
Metric estimators are unchanged. Original bar-count metadata and runtime daily
support counts are distinguished and their numeric measurements reconciled.

## Five-Alpha Selector-Only Readback

| Alpha ID | Discovery Points | Common Eligible | Current Outcome |
| --- | ---: | ---: | --- |
| A-RSI | 128 | 100 | Supported panel comparisons and three formal RSI arms |
| A-SC | 128 | 124 | Supported panel comparisons; no new formal study claim |
| A-HMA | 128 | 0 | NO_SELECTION on this panel under this mandate |
| A-HASH | 128 | 15 | Supported panel comparisons; no new formal study claim |
| A-VWAP | 128 | 9 | Supported panel comparisons; no new formal study claim |

Independent readback covers **640 configurations, 7,065 component rows and 80
decisions**; 127 worksheet/readback tests pass. Support, risk, quality, weighting,
actual selected dictionaries and registered coefficient perturbations are
verified without another financial account or sampler draw. SAM comparisons
have one authorized selection center; held local probes do not acquire selection
rights. That cohort cannot establish SAM superiority over the full panel.

The worksheets separate schema compatibility, measured local/regime effects,
missing evidence, researcher preferences and actual study outcomes. Compatible
CMA-ES is not a sampler recommendation by alpha name. HMA's bounded NO_SELECTION
does not establish absence of edge outside the registered candidate panel.

## Actual Matched Studies

Before search, source-qualified dossiers and explicit plans were sealed for
three separate RSI studies: raw-whole-Sharpe/TPE control, floor-mean/TPE primary
challenger, and floor-mean/CMA-ES sampler challenger. Each uses **256 proposals,
seed 731, sequential exact scheduling, no early stopping**, unchanged ranges and
the same declared final eligibility. All three deliver 256 complete, unique
executed candidates. The other alphas' panel evidence is not presented as formal
sampler or full-pipeline economic qualification.

The floor objective is `min(annual U) + 0.25 * day-weighted mean(annual U)`.
The same common eligibility is applied to the raw control's final choice. Raw
Sharpe feedback remains raw Sharpe; it is not silently changed to annual mean
Sharpe or the challenger's utility score.

| Realized Full-Development Result | Raw/TPE | Floor/TPE | Floor/CMA-ES |
| --- | ---: | ---: | ---: |
| Initial capital | 20,000 | 20,000 | 20,000 |
| Final equity | 253,606.82 | 126,069.53 | 117,754.75 |
| Net return | 1,168.03% | 530.35% | 488.77% |
| Whole-account Sharpe | 1.83494 | 1.33306 | 1.46129 |
| Whole-account maximum drawdown | 19.23% | 22.20% | 16.66% |
| Annual utility floor | -0.078908 | 0.060312 | 0.007975 |
| Day-weighted annual utility mean | 0.327235 | 0.133905 | 0.162611 |
| Comparable floor/mean score | 0.002901 | 0.093788 | 0.048628 |

These results show a real trade-off, not universal improvement. Floor/TPE
improves the selected worst annual utility while sacrificing total return and
whole Sharpe; its whole drawdown is not better than raw/TPE. CMA-ES has smaller
whole drawdown than both TPE choices but does not beat floor/TPE on the declared
floor/mean objective in this single-seed experiment. No sampler superiority,
automatic routing, future decay reduction or independent forward inference is
established by these full-development selected paths.

Original/direct controls reconcile all available returned streams, liquidation
state, whole measurements and seven annual return/DD/U views. Every selected
dictionary is frozen before selected replay/direct audit. Selected path equity
matches the retained original candidate and direct account exactly. Three arms
execute 768 proposals, 771 original scorer accounts including selected audits,
two final public endpoint accounts and three direct accounts: **776 completed
account invocations**, not internal native passes or independent observations.

## Cost And Recovery

| Work | Observed Time | Peak Process RSS |
| --- | ---: | ---: |
| Provider original/direct qualification | 11.36 s | 511.24 MiB |
| Raw/TPE original 256-proposal attempt | 237.27 s | Final peak not retained |
| Raw cold receipt recovery and selected audits | 24.87 s | Not separately retained |
| Floor/TPE study, selected controls and reporting | 261.97 s | 2,137.30 MiB |
| Floor/CMA-ES study, selected controls and reporting | 292.58 s | 2,130.77 MiB |

These are measured controller costs, not an apples-to-apples runtime speedup
claim. The original raw wrapper failed after all 256 terminal trials because it
subscripted a `Record`; cold recovery reuses every saved account/trial and
executes **zero replacement proposals**. Lost sampler internal wall telemetry
remains null, and exact persisted sampler continuation is not invented.

A source-qualified research callable initially had an unstable cross-process
fingerprint because code-constant representation contained a process address.
A separately pinned delegating wrapper preserves original strategy execution
and makes this provider's callable identity portable. Prior failed seals and
preflight receipts remain; no financial trial ran under that failed launch.

The [cold decision reader](DECISION_QUALIFICATION_V1.md) preserves actual trial,
gate, component, sampler and selected-audit provenance. Current-source p50 costs
on the frozen six-proposal fixture versus an actual 256-proposal report are:

| Operation | Six Proposals | 256 Proposals |
| --- | ---: | ---: |
| Verify/read metadata | 5.31 ms | 854.51 ms |
| Public JSON | 1.94 ms | 228.77 ms |
| Private JSON | 3.04 ms | 302.09 ms |
| Public Markdown | 4.07 ms | 199.85 ms |
| Private Markdown | 2.54 ms | 155.81 ms |

Sixteen repeats and two warmups retain all durations; percentiles are descriptive,
not a release latency threshold. No finance, search, reduction or RNG draw is in
these timers. No claim of equal reporting cost at different retained ledger
sizes is made. Default public exports redact private vectors and source prose.

## Qualification Boundaries

- The retained legacy broad test failures were traced to an older installed
  native policy/pair and stale source-guard ancestry. With the already qualified
  native artifact and matching retained tooling environment, the 140-test legacy
  shard passes without exclusions or a native rebuild. Guards validate exact
  committed amendments; arbitrary additional bytes still reject.
- The expanded single-process suite retains 1,223 passes and its failed cold
  import assertion. It was interrupted after test scratch exceeded its original
  estimate. Its resource gate is **FAIL_RETAINED**, not retroactively PASS.
  Remaining nodes are qualified in bounded fresh workers with fixture cleanup.
- The cold-import assertion now measures reducer import attempts, including
  attempts to use already-loaded financial dependencies, instead of confusing
  SDK initialization with the reducer. It is not disabled and does not certify
  the entire SDK's import footprint as zero.
- The current-prefix procedural test rebuilds verified matrices/reference,
  selector advice, dossier/plan and an actual adaptive TPE study while a forbidden
  suffix changes. It is distinct from a historical-2023 procedure and the
  256-proposal economic studies. Broader historical fit/search/probe proof must
  be measured or explicitly disposed, not replaced by a fixed-signal assertion.
- Preserve the seven old forward contrasts, 16,384-draw inference and adverse
  results under their original registrations. Reviewed 2020--2026 selection does
  not become independent OOS. New economic forward authority needs a valid
  timeline, not reuse of the calibration period under a new label.

## Evidence And Next Gate

Private append-only root:
`upgrade/private/mode5_upgrade_v1/m5-11-5/attempt-01/`.
Key receipts: `selector-comparison03/receipt.json`, `worksheets05/receipt.json`,
`original-qualification05.json`, `formal-freeze02/`,
`formal-studies02/floor-tpe/result.json`, `formal-studies02/floor-cma/result.json`,
`raw-recovery01/result.json`, `closure-analysis01.json`,
`render-benchmark03.json` and `legacy-closure02.xml`.
Private strategy sources, parameter dictionaries and observations are not
published or package resources. Final C07/C08 receipts and cleanup are required
before a whole-phase exit claim. M5-12 remains the separate installed-current-
source wheel/sdist, regression, privacy and package handoff gate. No CI, push,
merge, tag, version bump or publication is performed here.
