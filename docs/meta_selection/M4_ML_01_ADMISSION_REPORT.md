# M4-ML-01 - Frozen Baseline And Study Admission

## Scope And Authority

Owner approved M4-ML-01 followed by M4-ML-02 on 2026-10-17. The supplemental
[research guide](../../upgrade/QUANTBT_MODE4_META_LEARNER_RESEARCH_GUIDE_V1.md)
and [unified plan](../../upgrade/implement.md#m4-ml-01) govern this local study.
The owner subsequently approved the finite protocol and conservative fallback
before new real-data learner results. No optimizer, financial engine, strategy,
scientific target, public default, dependency or native binary changes.

The [Ridge freeze](RIDGE_V1_FROZEN_BASELINE.md) verifies all 42 source hashes
and five prior receipts. It freezes the algorithm, not future-fitted coefficients.
Source imports resolve core 1.1.2; the reused environment's installed distribution
metadata still says 1.1.1. This is explicitly a source research environment, not
an installed-pair certificate. Existing private native 0.4.3 supplies numeric ABI
`qms-numeric-v1`; its extension SHA256 is
`2959f5388c6a8e57bdef5a6dafe76da3624ef57dba379f7ca686e9bf202ad26b`.
No installation or build was performed.

## Admitted Corpus

Original ETHUSDT 1h, rolling 730D/monthly, 57 origins per group; no faster
quarterly strategy variant is substituted. Custody uses repaired SC/HASH/HMA
history and original completed VWAP history. All 228 saved as-of snapshots
rebuild exactly. The terminal receipt and its cold readback are independently
SHA-pinned; group/root/family/schema substitution fails admission. Parsing uses
the same bounded bytes whose hashes were verified.

| Group | d | Pool memberships | Forward VALID / NO_VARIANCE | Base / extra union | Informative nonanchor rows |
|---|---:|---:|---:|---:|---:|
| SC | 7 | 7,296 | 621 / 320 | 912 / 29 | 495 |
| HMA | 17 | 7,151 | 930 / 15 | 912 / 33 | 873 |
| HASH | 12 | 7,028 | 948 / 0 | 912 / 36 | 891 |
| VWAP | 18 | 7,290 | 409 / 534 | 912 / 31 | 248 |

Counts are memberships, not independent observations. Only 3,777 forward
witnesses cover 28,765 recorded pool memberships. Raw-IS or forward undefined
metrics remain typed exclusions. An invalid forward anchor removes the whole
origin from informative training: 16 SC and 30 VWAP origins. No missing label is
replaced by zero, and the full pool is not restricted to candidates with labels.

Secondary strata are inventoried but not imported as extra primary groups:
quarterly 365D variants have different feature dimensions, samplers and only
19 quarters; historical RSI has 28 tasks, 3,531 pool memberships and 459 labels
under its older 365D/account protocol. Their reviewed evidence remains intact.
In particular, existing positive RSI evidence is not rerun or invalidated here.

## Bias And Information Rights

- Base16 acquisition depends on IS features/objective; it is not representative
  random sampling. The extra union oversamples previous-policy winners.
- Primary loss replay uses a separately identified base-only sensitivity view;
  full original union replay supplies matched V1 reproduction and acquisition
  sensitivity. Original revisions are never edited or re-certified as base-only.
- Propensities/positivity are unknown: no inverse-propensity or unbiased
  full-pool generalization claim. Loss is conditional on the registered panel.
- Anchor-dependent missingness, overlapping IS, common market dates and reviewed
  outcomes prevent IID-row or pristine external-OOS claims.
- Four related-alpha groups remain distinct. Coefficients fit compatible own
  history; a held-out group's outcomes cannot choose its calibration recipe.

## Frozen Protocol

The [machine registration](../../benchmarks/optimization/meta_selection/model_research_v1/ml01_registration_v2.json)
predates real-data P0/P1/P2 outcomes. Folds 0--12 acquire history, 13--24 are
development, and 25--56 are evaluation (February 2024--September 2026).
The common calibration frontier is **2024-01-31 23:00 UTC**, the first actual
evaluation information cutoff. January labels arrive 14--32 seconds later and
are unavailable, despite being before midnight February 1.

P0 retains origin-sum lambda 10. P1 uses mean-origin alpha 10/12, equivalent
sum lambda K*10/12. P2 selects from {0.1, 0.3, 10/12, 1, 3, 10} using only the
three other groups' mature development outcomes, equal group then origin weight.
It requires at least three valid inner origins per training group and three
supported intact three-month blocks; otherwise P0 is the explicit fallback.
Among near-minimum inner losses within one block standard error, select the
larger alpha. The algorithm is shared; it is not an alpha-name lambda lookup.

Actual usable pre-cutoff validation origins are SC/HMA/HASH/VWAP = 7/11/11/2.
Thus P2 must fallback whenever VWAP is a training group. This support limitation
was known and retained before fitting; no gate is lowered to make P2 run.

Shortlisting requires at least 2% served-loss improvement, family-95% upper
delta-loss bound <=0, lower delta-Q and delta-R bounds >=-0.05 Sharpe, at least
12 paired origins/365 days per group, and a complete calendar for numerical
CI. Shared three-month blocks, 16,384 draws, seed 731 and six-coordinate
Bonferroni control are fixed. Missing-calendar inference is INCONCLUSIVE; point
summaries remain explicitly conditional. No claim is made that these conservative
study rules prove adequate power or independent pipeline generalization.

## Gates, Resources And Handoff

The [final admission tests](../../benchmarks/optimization/meta_selection/model_research_v1/ml01_tests_sealed.xml)
cover source/settings mutation, wrong family/root, bounded verified bytes,
duplicate-origin support, strict availability, group exclusion, macro weights,
protocol restore and existing late/corrected-label contracts. Earlier setup
failure is retained separately, never rewritten as PASS.

Zero real-data model fits, optimizer proposals and financial calls in ML-01.
Cold admission is under the 15 CPU-minute cap; source, schemas and compact
metadata only are retained. ML-02 has a 4,000 total-fit ceiling including
controls/retries, one CPU-hour, one numeric thread, no new dependency or account.
The 12-fit pilot precedes scale. Both phases share the 256-MiB incremental cap,
1.5-GiB owned-RSS cap, 512-MiB available-RAM floor and 5-GiB disk reserve after
projected peak. Exact inactive fixture scratch is cleaned after tests, preserving
all input pins, failures and current tooling.

Technical admission is complete; economic superiority is NOT_ASSESSED in this
phase. ML-02 is the only authorized next phase. ML-03..05, M5-11.7/M5-12, remote
CI, merge, tag and publication remain unactivated. Read the
[admission/cleanup receipt](../../benchmarks/optimization/meta_selection/model_research_v1/ml01_closure.json)
for actual final work, hashes and resource values.
