# M5-11.2 Matched Sampler Comparison

## Scope And Measurement

This is the registered RSI development experiment, not a forward-performance
claim or a universal sampler recommendation. All four arms use the original
continuous account over 2021--2023, 2020 indicator preload, the same static
eight-dimensional numeric domain, seed 731, 256 proposals and original
whole-account Sharpe selection. There is no warm start or performance-based
early stopping. Private alpha, vectors, market data and full ledgers are not
published here.

The legacy univariate-TPE control is reused from its completed, independently
audited study. The other three arms are newly executed studies. Their source
generation, provider qualification and context/recipe freeze precede finance.
Sampler-only comparison does not include the annual-floor study, whose
objective and adaptive search trajectory differ.

## Actual Results

| Arm | Complete Trials | Selected Trial | Development Raw Sharpe | Annual-Eligible Trials | Parent Wall Time | Peak RSS |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Legacy univariate TPE | 256 | 174 | 2.66281 | 125 | Historical, not matched fresh timing | Historical |
| Multivariate/group TPE | 256 | 35 | 2.39967 | 25 | 5,950.33 s | 527.16 MiB |
| CMA-ES | 256 | 201 | 1.69246 | 9 | 6,367.37 s | 567.80 MiB |
| Scrambled Sobol | 256 | 252 | 1.85112 | 5 | 6,326.62 s | 563.86 MiB |

Each new arm executes 257 original scorer accounts (256 search plus selected
audit) and one independent direct account. Selected/direct paths have exact
parity. Counts describe original account invocations, not inferred internal
Rust passes. Financial accounting, scientific gates and previous receipts are
unchanged. Annual eligibility is diagnostic; the raw objective does not filter
on it. Do not compare the annual-floor objective's value to this raw Sharpe.

Sampler work itself takes 3.043 s, 2.225 s and 2.110 s respectively; the much
larger full-run times include financial evaluation and custody. TPE has ten
startup-independent trials and 246 relative proposals; CMA-ES and Sobol each
have one independent startup and 255 relative proposals. Independent startup
is not a sampler failure. The Sobol stream has 255 QMC points, not a balanced
256-point QMC net. CMA generation counts unavailable in the original ledger
remain unknown.

## Interpretation

On this one development tape and seed, none of the new samplers improves the
selected raw Sharpe over the retained legacy control. This is a measured
negative result, not evidence that the other samplers are generally worse.
There are no new seeds, ranges, gates or forward-driven recipe choices.
Equal proposal budgets do not establish equal effective search coverage or
matched fresh wall time for the historical control.

The separate primary challenger remains the preregistered annual-floor recipe.
Its forward assessment, and the secondary raw-objective sampler contrasts,
must use frozen vectors and the approved family of seven comparisons. Forward
execution and economic qualification are separate gates; this report cannot
close M5-11.3 or certify independent OOS.

## Custody And Cleanup

The cold comparison rereads the four complete ledgers, actual selected-vector
tie-breaks, selected/direct account paths and closed sampler owners. It creates
no new financial account. Receipt: `MATCHED_PROPOSAL_BUDGET_COMPLETE`, SHA-256
`282fcbeb2c1f31f42776b2587cffc2d0e6a9a7522a7f8ad2ad8866dcdcd21f85`.
The cohort close receipt SHA-256 is
`65c3f893a0c555eedd46888865cb40f07a9403bc6715c4abc1a831e68b8e0e05`.

All three owners have reaped their children and closed their registered scratch
cleanup. All trial/account artifacts, failed receipts and source generations
remain retained. The cold comparison has no scratch to remove and its cleanup
receipt SHA-256 is
`d48c1083e8e2e66b2c68381a8e0913648c800674e20e689e427207a80b13af96`.
Cold readback takes 0.340 s and peaks at 30.65 MiB. This receipt is separate
from scientific qualification. No CI, remote publication,
deployment or release ran.
