# Dual Environment And Chronological Rights Contract V1

## Scope And Ownership

`tools/mode5_environments` is an opt-in research layer, not a new public
endpoint, financial simulator, regime-model project or deployment switch.
It consumes qualified existing provider features and actual retained QuantBT
account observations. Financial execution, fees, funding, timing, account state,
optimizer order, RNG and existing metric/objective contracts remain unchanged.

Read the [phase plan](../../upgrade/implement.md#mode5-m5-05) and
[detailed guide](../../upgrade/QUANTBT_MODE5_UPGRADE_V1_DIAGNOSTICS_FIRST_GUIDE_VI.md#46-trục-3--dual-perspective-environments-và-chronology).

## Manifests And Two Estimands

`AnchorManifest` preserves source digest/pointer, exact UTC preload/score/end,
role, lifecycle identity, boundary policy and evaluation mode. Naive dates in
the reviewed masters are explicitly interpreted as UTC, never host-local time.
An unverified historical right boundary stays `UNVERIFIED`; membership is
rejected until a verified revision is registered. A summary does not certify
the financial lifecycle of its original run. Registry IDs are append-only.

- `CONTINUOUS_PATH_ATTRIBUTION`: one actual chronological account path. Group
  daily account changes afterwards; never reset state at a regime boundary.
- `CONTIGUOUS_RESET_EPISODES`: independent counterfactual episodes with their
  own warmup, initial account and terminal contract. A reset result cannot be
  passed to the carried-path attribution reducer or assembled into live equity.

Scope-entry equity must be the actual recorded baseline; implicit deposits or
invented boundary marks are not supported. Money PnL sums and the product of
actual daily return factors reconcile with the qualified full path. Nonpositive
return bases carry explicit unavailable/bankruptcy status, not rescued returns.
Missing fees remain null with `REPLAY_REQUIRED`; they do not erase measured
account PnL and must never be replaced with zero costs.

## Provider And Decision Vintages

`FeatureTape` contains immutable closed-observation timestamps, finite masked
values, publication availability and quality (`valid`, `missing`, `stale`,
`warmup`). Bind provider source bytes, recipe/dependencies and market witness,
not merely a friendly name. The adapter trusts the reviewed provider's trailing
feature contract; this is not a security sandbox for arbitrary dishonest code.
Timestamp overflow and reserved `NaT` sentinels are rejected before signed
integer conversion; unavailable observations cannot wrap into historical rights.

`fit_partition` is the explicitly versioned `train_zscore_quantile_v1` research
adapter: population mean/std (`ddof=0`), linear quantile thresholds, strictly
train-scoped observations available by the fitting cutoff. Quantiles and minimum
support are explicit. Constant or insufficient features fail closed; no epsilon
creates a normal regime. This does not fit or duplicate an external lab model.
The qualified M5-05 proof reuses the existing lab trailing feature functions.
Its reviewed CSV has no certified raw bar-open/bar-close index witness, so the
feature binding uses a conservative one-prior-completed-bar policy with a new
provider identity/namespace. Saved account timestamps are not shifted. This is
a shared market-context partition, not every alpha's local-symbol regime proof.
More complex providers can supply their own qualified tapes; PCA/HMM or alternate
transform fitting is not automatically certified by this univariate contract.

Unavailable feature values cannot influence the fitted transform/content ID.
Historical application has two distinct purposes:

- `decision_vintage`: fit must be mature before a label can authorize a
  historical decision; future/unpublished observations remain masked.
- `asof_calibration_descriptive`: hindsight partition of known development.
  It cannot export decision labels or overwrite past decision vintages.

`VintageStore` seals namespace/purpose/vintage. Data, thresholds or provider
changes require new identities/revisions. M5-04 analysis identity must include
the exact membership/vintage and metric/reference policy. A cache hit is still
subject to its every-access rights check. Do not use today's revised labels to
reconstruct yesterday's allegedly live choices.

## Information Frontier

`ChronologyPlan` records mature train, inner-validation and outer intervals,
plus discovery cutoff. Training rights exclude inner and outer observations.
`KnownArtifact` describes an outcome-derived candidate/recipe result: outcome
maturity, discovery, selection time and permitted lineage are all checked.
Raw candidate generation before an outcome is not itself a matured outcome.

Leave-out checks using later environments are explicitly
`retrospective_transfer`, not historical forecasting. Actual leave-out selection
uses the later approved canonical selector; this phase records its permitted
scope, not a second selector. Full adaptive history absent from a summary cannot
be recreated from winner rows.

`ScopeUse` checks overlapping actual market dates, not only renamed manifest IDs.
Previously reviewed or selection-used 2024 data cannot become independent
holdout by relabelling. These declarations operate within trusted research
lineage; they cannot discover unrecorded human inspection of data.

## Attribution And Support

Daily account PnL uses actual consecutive account marks, including zero returns
and bad outcomes. Disjoint conditional groups have no artificial stitched price
series or annualized subset return. Whole-path Sharpe remains the existing
whole-calendar reducer; it is not the mean of episode Sharpes.

Campaign attribution is separately named:

- `entry_state`: all authoritative net campaign PnL assigned to its as-of entry
  state; never the next future observation's label.
- `duration_weighted`: distribute recorded net PnL by actual elapsed holding
  time in states. This is descriptive allocation, not mark-based state PnL.

Closed and censored-open campaigns remain distinct. A missing campaign ledger
is unavailable, never reconstructed from position regimes or fees alone.

Overlap uses unique UTC dates. Fixed family mass is divided within each family
per shared day; copied identical views do not increase influence. Missing family
mass is disclosed and not silently redistributed. Report overlaps, exposure
bars, campaigns, recurrence and missing/rare/no-trade states. Recurrence is not
IID sample size. Shared-date/block draws must be retained by later bootstrap
comparisons; this phase does not create a new bootstrap sampler.
Zero close-mark exposure is `NO_CLOSE_MARK_EXPOSURE`, not proof of no fills.
Support without exposure or closed campaigns is `NO_OBSERVED_ACTIVITY`; an
actual no-trade claim requires a complete activity ledger. Exit costs or
same-bar round trips are never erased merely because the closing position is flat.

`match_calendar` reports actual first/last bar, requested interval and candidate
readiness. It never silently shortens one candidate's score window. Explicit
preload missing or indicators not ready makes the common contract `NOT_READY`.
Do not infer private alpha lookbacks missing from original receipts.

## Evidence, Limits And Rollback

The [M5-05 report](M5_05_ENVIRONMENT_REPORT.md) and source-bound seal distinguish
technical mutation/account reconciliation from economics. The 91-day reviewed
pilot does not establish whole-development robustness, unseen transfer, decay
benefits, sufficient tail support or automatic live switching.

Disable these research views to roll back. Preserve original labels/manifests,
access logs and retained evidence; the qualified evaluator is unchanged. Public
facade/artifact integration requires its own later approval/gate.
