# M5-11.3 Frozen-Vector Forward Report

## Current Scope

Primary forward execution, both new-prefix studies and annual 2023/2024 are
complete within their declared bounded contracts. Annual 2025 is running
serially; full-procedure mutation and complete prefix diagnostics remain
unfinished gates. This report must not be read as completion of M5-11.3 or
M5-12. Historical checkpoint paragraphs below retain their original timing.

Both Source09 actual bounded prefix panels now complete 128 accounts each,
with 20/3 annual-eligible candidates at origins 2023/2025. The 2023 freeze
passes; the final 2025 JSON-reader failure is recovered cold without repeating
either panel. The old aggregate remains FAIL_RETAINED, never relabelled PASS.
The recovery passes 17 separate transport fixtures, preserves all 59 sealed
Python bodies and produces a byte-identical plan
(`b886d6ee1e9685d5e0f361ab1fc25c5cc9a2936db6f344523b91d422c112f93f`).
Actual original query/governance freeze: 228.527 seconds / 431.12 MiB peak RSS,
zero account/optimizer/RNG calls, all children reaped, no error/resource stop,
exact registered scratch removed. Recovery closure SHA256:
`d8198a54e316a6636cc0faea659561d3d5c1b80c95973c014e267b4b791ca89b`;
supervision/cleanup:
`00ac877b1774d93fbbcdd1a1d501ac396ecac5279eb8e39bf409862fb2e1080d`.
Observed free-space change is -24,576 bytes, not a claimed net cleanup saving.
New per-prefix studies/annual forward and full fit/search/rank mutation remain
separate work at that historical recovery checkpoint; bounded raw/floor
diagnostics are not complete geometry/probes.

The five effective vectors are the actual selected outputs of the registered
256-trial studies. They are frozen before opening forward outcomes. Scored
development is 2021--2023 (1,095 UTC days); scored forward is 2024--2025
(731 UTC days, including leap year). Indicator preload starts in 2020.
Each forward run uses the original QuantBT endpoint and a separate direct
accounting oracle. It starts one explicit fresh account at 20,000 and does not
reset at the 2024/2025 boundary. No new optimizer or account engine is used.

All dates have already been reviewed during research. These are retrospective
fixed-parameter forward diagnostics, not untouched or independent OOS.

## Primary Results

| Frozen Study | Development Sharpe | Forward Sharpe | Sharpe Decay (IS Minus Forward) | Forward Final Equity | Forward Return |
| --- | ---: | ---: | ---: | ---: | ---: |
| Raw whole-Sharpe / legacy TPE | 2.66281 | 0.05875 | 2.60406 | 19,894.62 | -0.53% |
| Annual-floor / legacy TPE | 2.01601 | 0.93789 | 1.07812 | 26,926.69 | +34.63% |
| Raw / multivariate-group TPE | 2.39967 | 1.90496 | 0.49471 | 38,705.41 | +93.53% |
| Raw / CMA-ES | 1.69246 | 0.73390 | 0.95856 | 25,479.53 | +27.40% |
| Raw / scrambled Sobol | 1.85112 | 0.37664 | 1.47449 | 22,171.56 | +10.86% |

Sharpe uses the same original daily measurement policy and 365 annual periods
for both windows. Decay is a difference, not a ratio. Final equity/return use
the actual cost-bearing account path; arithmetic mean daily returns are not
the compounded account return.

Annual-floor reduces measured Sharpe decay by 1.52593 versus raw control.
This comprises IS Sharpe lower by 0.64680 and forward Sharpe higher by 0.87914.
Approximately 42.4% of the measured difference comes from lower IS; the rest
comes from better measured forward quality. It is not merely a smaller IS
score making decay look better. This decomposition is descriptive, not a
causal attribution of the objective or sampler separately.

The new samplers' development winners are below the legacy control's IS
Sharpe, yet their frozen vectors have higher measured forward Sharpe here.
The registered multivariate/group vector is strongest on this forward tape.
It does not become the primary challenger or a new preferred recipe after
seeing forward outcomes; annual-floor remains the preregistered primary.

## Uncertainty And Evidence Limits

All comparisons use the original paired circular-block estimator, 7-day
blocks, seed 731, approved 16,384 draws, family size seven, 99% family
confidence and 0.5-bps net account/day business hurdle. The seven contrasts
include all three registered annual-origin comparisons. No family members
are removed after results. Confidence intervals below concern fixed paths,
not sampler/recipe-selection uncertainty or independent replications.

| Versus Raw Legacy Control | Mean Net Change (bps/day) | Family-Adjusted Fixed-Path Interval (bps/day) | Verdict |
| --- | ---: | --- | --- |
| Annual-floor | +4.23214 | [-8.07871, +17.45451] | INCONCLUSIVE |
| Multivariate/group TPE | +9.23885 | [-1.63048, +20.84947] | INCONCLUSIVE |
| CMA-ES | +3.54867 | [-8.61346, +16.04073] | INCONCLUSIVE |
| Sobol | +1.59237 | [-12.56542, +16.29256] | INCONCLUSIVE |

The annual-floor forward-Sharpe interval is [-1.84541, +3.51918]; its
decay-change interval is [-4.70574, +1.66542]. These intervals cross zero.
The family-adjusted extreme tail has approximately 11.7 expected Monte-Carlo
draws, better resolution than the historical 1,024 draws, not infinite
precision. The point estimates are encouraging; the registered uncertainty
gate does not yet establish a stable economically meaningful improvement.

Each pair is exactly one origin. Accepted-fill and closed-campaign support is
unavailable on this original legacy RSI route; position-regime counts are not
substituted. Closed-campaign profit-factor decay remains unavailable. These
support gaps stay explicit, even though account paths are valid and long.
No economic or deployment promotion is granted. Missing support is not
evidence that the alpha lacks an edge.

## Correctness, Resources And Cleanup

All five forward endpoint/direct comparisons match equity, returns, positions,
available fees/funding/margin streams and liquidation state exactly. The
ten actual accounts complete. Development populations match the retained
selected-account tapes. Mutating the 2025 OHLC suffix leaves every pre-2025
signal unchanged for each fixed vector. This proves the tested fixed-signal
boundary, not full diagnostics/fit/search/rank mutation of the entire procedure.

The new source-only harness passes 207 tests across 17 isolated serial suites,
including calendar completeness, leap years, initial-capital day-one costs,
bankruptcy policy, immutable fixture evidence and actual worker custody.
Earlier failed software attempts remain retained. No engine mathematics,
scientific threshold or financial source is changed by fixture corrections.

Primary supervisor: `PASS_PRIMARY_FORWARD_ONLY`, 118.312 s, 327.26 MiB peak
RSS, all children reaped, no resource stop, owned scratch removed and protected
source/input/output pins verified. Result SHA-256:
`069d45d40aa335d22d8a8086ae797ffe2728df981a74ca825e8ff32a634f158d`.
Supervisor SHA-256:
`d2f22b342972bc39204f09f853f973b93d962cc762143fedefc2f74b9df7ee4b`.
Software receipt SHA-256:
`02094bee6386ee0a1bfb2054a79bce0881c87b7a426c48eeff25912a7d964dce`;
software cleanup SHA-256:
`a2406f2fa1916151ff23d35d37d18db685543c4b8b6a07f7a251abc48c46d2db`.
Private vectors, alpha source, accounts and original receipts remain retained
and excluded from Git/package artifacts. No CI, push or release occurs.

## Remaining Registered Work

### Annual 2024 Integration

Annual 2024 is now technically closed using the exact original 2021--2023
selected vectors and development accounts. No calibration/search is repeated.
The scored window is [2024-01-01,2025-01-01), all 366 UTC days, with 2020
indicator preload and an explicit fresh 20,000 account for each vector.

| Frozen Arm | Development Sharpe | Annual Forward Sharpe | IS Minus Forward | Final Equity | Net Return |
| --- | ---: | ---: | ---: | ---: | ---: |
| Raw whole-Sharpe | 2.66281 | -0.12725 | 2.79006 | 19,291.31 | -3.54% |
| Annual-floor | 2.01601 | 1.96208 | 0.05394 | 27,696.76 | +38.48% |

Measured decay change is -2.73613: development Sharpe is lower by 0.64680
and forward Sharpe is higher by 2.08933. Mean net improvement is +9.89053
bps/day; the registered family-seven interval is [-6.89309,+29.21918]
bps/day. Forward-Sharpe change interval is [-1.32942,+5.61646]; decay-change
interval is [-6.61351,+0.99963]. Verdict remains INCONCLUSIVE, not a changed
recipe or threshold. This is one origin and overlaps the primary two-year
forward. Missing fill/campaign support remains explicit; dates already reviewed
do not become independent OOS.

Four actual original/direct accounts, source/input exit checks and fixed-signal
future perturbations pass. The new source-only harness passes 221 tests across
18 isolated suites. Source/transport fixture failures remain retained and have
zero finance. Supervisor closes PASS in 430.569 s at 1,427.05 MiB peak worker
RSS, including the full retained-lineage verification, not a kernel benchmark.
All children are reaped; only registered inactive scratch is removed. The
synthetic volume perturbation emits an existing pandas dtype FutureWarning;
it does not change original market/account inputs and tested prefix signals
still match. No full fit/search/rank mutation is certified by this run.

Annual result SHA-256:
`7f365290b3606d30f62c1bd8649093fa778b4a169932ae61327d4e56ae22ad37`;
supervision:
`21ca442dfcb5a70e47f9436b1538e9fd2a712a25350374d3a95a1e488fd9476a`;
cleanup:
`b7b7950c695340abebd13a01c8b1d524a70f1332d0231d8316df60d68c40e5b6`.
Current software receipt:
`b12643d1c41779b47659dc1e39a2c5163c13e0fc1d4518a6ec37aa076a4f2794`;
software cleanup:
`751edfae71c99acb64880a8ed296621256a7146cde8cd61812f7fba0be85acc0`.

### Pending Prefix Work

The actual 2023 bounded panel now closes 128 panel accounts, plus its original
qualification scorer and independent direct account. Exactly 20/128 candidates
meet the unchanged annual eligibility gate. Source/input entry and exit checks,
supervision and cleanup PASS in 2,491.243 s at 521.42 MiB peak worker RSS.
All owned children are reaped; no resource stop or cleanup error occurs; only
the registered inactive scratch is removed. Diagnostic SHA-256:
`f5dead544dbb3c7874b5ae5e9728b92f064c3983c8dfc159257abbf30abbf0f3`;
supervision and cleanup SHA-256:
`840c1599261199748641ed9e0823742e0731802f2bfbac93e8594b4620bf591d`.
This is bounded raw/annual-floor evidence, not full geometry/probe certification
or diagnostics-fit/search/rank mutation qualification.

The 2025 panel subsequently closes 128/128 accounts and 3/128 eligible, with
original-provider qualification and source/input entry/exit checks. Its stage
supervision and cleanup PASS; diagnostic SHA-256:
`6948a2b1ffe5596141d898e4cb7c455b1eb41336df9b2b5d77da448ee9234671`;
supervision/cleanup:
`e8c26a10025788c508ad73a700e5d16fd57fc071f94646b06e4b58feb33bcd2f`.
The 2023 freeze also passes, but the final 2025 freeze rejects its 12,945,373-byte
dossier at the default 8-MiB metadata-reader bound. The aggregate remains
FAIL_RETAINED; all owned workers are reaped and failed scratch is cleaned.
Aggregate SHA-256:
`6906dec1539473c6bf01202f4a8e3e844e9979664907e819a617097b536c0bc4`.
This is a transport failure, not missing financial accounts or an economic gate
failure. Register a cold-only, source-preserving recovery; do not repeat either
completed panel or relabel the failed aggregate as PASS.

- Recover the missing 2025 cold plan freeze from its actual closed panel;
  preserve the successful 2023 freeze and original Source09 hashes.
- Execute each actual 256-trial prefix raw study and eligible floor study;
  preserve real DEFER/NO_SELECTION if the unchanged gate fails.
- Run the remaining registered complete-year 2023/2025 fresh-account comparisons,
  keeping overlap/dependence and actual per-pair origin counts explicit.
- Keep full fit/search/rank future-mutation certification separate from the
  already-passing projection and fixed-signal mutation checks.
- Review scientific scope and incomplete proof limits before M5-12. No local
  receipt substitutes for later installed-artifact, remote or public gates.

### Current Prefix2023 Search Checkpoint

The new allowed-prefix2023 raw and annual-floor studies are now complete,
256 attempts each, with no old panel imported as trials or forward-driven
choice. Both selected vectors pass exact original/direct accounting. Measured
work is 514 original scorer invocations, two direct accounts and one final
endpoint account, 517 in total; this is a work count, not independent sample
support. Source, evidence and generated-artifact custody close at entry/exit.

Original supervision PASSes in 10,444.796 s at 974.22 MiB peak RSS; all owned
children are reaped, with no resource stop or cleanup error. Only the registered
inactive study scratch is removed, with +966,656 observed free bytes. Params,
typed accounts, logs, journals and failures remain retained privately. The
per-origin result remains bounded study evidence, not full diagnostics,
fit/search/rank future-mutation qualification or economic promotion.

Studies receipt SHA-256:
`bf3df9c1b479e93b9cc40564f7c3169b10bd8d4e10d784d4be2b78857d7b039a`;
supervisor:
`4b99b27db1a52103561ca79fa837132eacee5a813e93ed235e8f37823d7f00ee`;
cleanup:
`f6887ed1db7b512de7778807abad9ea4afcb477d221d1ebbec1ad55b3490150c`.
The serial prefix2025 studies and actual annual2023/2025 forward comparisons
remain pending at this checkpoint. The retained failed aggregate is unchanged.

### Current Prefix2025 / Serial Search Closure

Both 2025 original study arms subsequently close 256 attempts and exact
selected/direct accounting. Measured work is again 514 original scorer,
two direct and one final-endpoint accounts, 517 total. All four prefix arms
therefore execute 1,024 attempts and 1,034 account invocations. The actual
per-origin data/source/evidence and generated-artifact custody PASS; these
counts do not substitute for independent origins or missing campaign support.

Prefix2025 supervision PASSes in 11,222.656 s at 1,607.39 MiB peak RSS, all
children reaped, no resource stop/error. Exact inactive scratch cleanup has
+40,960 observed free bytes. Serial closure PASSes in 21,765.484 s, preserving
the earlier aggregate FAIL and all original finance. Full diagnostics and
fit/search/rank future-mutation qualification remain explicitly NOT_RUN.

2025 studies SHA-256:
`67222ba7e4fc6e7e2eca7799e552edd4d75f786e446cace73c0868df167ca796`;
supervisor:
`5cbbde401bffb970cf1508e8d9b9e70ceba14dbd43fb1e0deb19fe1e45f2e614`;
cleanup:
`b85acac1341782d39aeb674690655b665c542b470b0d37d514c0540d62f31e15`;
serial closure:
`ec82936ab7c05243154aefe49f093f4487745567c2aabbd6e65d902adce41fc3`.

### Annual 2023 Integration

The new prefix studies select only on complete 2021--2022 development;
forward is [2023-01-01,2024-01-01), all 365 UTC days. Original indicator
preload starts in 2020; each frozen vector opens a fresh 20,000 account.
Neither the later full-development winner nor an equity slice substitutes
for this actual new-prefix calibration and annual account.

| Frozen Arm | Development Sharpe | Annual Forward Sharpe | IS Minus Forward | Final Equity | Net Return | Max Drawdown |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Raw whole-Sharpe | 2.90069 | -0.13474 | 3.03543 | 19,481.58 | -2.59% | 10.81% |
| Annual-floor | 2.69713 | 0.97774 | 1.71940 | 22,922.12 | +14.61% | 13.73% |

Decay change is -1.31604: IS Sharpe falls by 0.20356 while measured forward
Sharpe rises by 1.11248. Lower IS contributes about 15.5% of this descriptive
decomposition, not the entire apparent improvement. Higher forward return
does not imply lower drawdown: annual-floor has greater measured drawdown here.

Paired net mean change is +4.53229 bps/day; family-seven 99% fixed-path
interval is [-2.92226,+15.45703] bps/day. Forward-Sharpe change interval is
[-0.75621,+3.66093] and decay-change interval is [-4.31159,+1.15589].
All 16,384 draws are valid. Economics remains INCONCLUSIVE; unavailable
fills/campaigns and per-pair one-origin support are not invented or pooled.
This reviewed historical year is not an independent untouched OOS.

Four actual original/direct accounts and every available financial array
match exactly. Mutating the July-and-later suffix leaves earlier fixed-vector
signals unchanged. Source and evidence entry/exit checks PASS. Separately
qualified metadata transport passes 11 zero-finance fixtures; all 59 original
financial bodies remain unchanged. The exact historical partial outer JSON
is byte/hash-protected but not traversed as successful metadata. Both failed
pre-launch admissions remain retained, with zero financial execution.

Original supervision: PASS, 692.353 s / 733.70 MiB worker peak RSS, all children
reaped, no error/resource stop. Only exact inactive registered scratch is
removed; immediate free-space increase is 258,048 bytes, not total retained
research size. Result SHA-256:
`57adfa88aaaff211817a16fccc8861ee429927f4257db9146910893fdd7d582e`;
supervisor:
`d5a35637dd42f5662e81786486b2189059e2ba8b37465f22a835e211767cda67`;
cleanup:
`f1f466e687ab560941c374cf2b6f95d5eb4d14b2a242026554b019a8e9d5314c`;
current separate metadata qualification:
`9f8c6a9e806e86f1a54144ef19392f908278bace20fa32f0166c7ca8b8c1b110`.

Annual 2025 follows serially through the same original financial owner.
Neither this account proof nor fixed-signal mutation certifies full
diagnostics/fit/search/rank future-mutation or complete geometry/probes.
