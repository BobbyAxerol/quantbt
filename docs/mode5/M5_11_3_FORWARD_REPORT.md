# M5-11.3 Frozen-Vector Forward Report

## Current Scope

Primary forward execution is complete and technically qualified. New-prefix
diagnostics/search and annual-origin forward work remain separate, unfinished
gates. This report must not be read as completion of M5-11.3 or M5-12.

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
include the still-pending three annual-origin comparisons. No family members
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
