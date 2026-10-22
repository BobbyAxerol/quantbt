# M5-11.11 Stable Regions And Temporal Regret Research

**Status:** completed local registered research scope, 2026-10-20 Asia/Saigon.
**Production authority:** none. No `src/quantbt` changes, public selector,
default, Ridge update, optimizer study, release or later-phase activation.

Authority: [unified phase](../../upgrade/implement.md#mode5-m5-11-11),
[detailed protocol](../../upgrade/QUANTBT_MODE4_MODE5_CROSS_MODE_RESEARCH_GUIDE_V1.md#xm-02),
[baseline/information rights](M5_11_10_ARCHIVE_BASELINE_REPORT.md).
Private registration, matrices, actual account receipts, decisions and summaries:
`upgrade/private/mode5_upgrade_v1/m5-11-11/attempt-01/`.
Private research code stays under ignored `upgrade/local/`; no alpha source,
parameter dictionary or raw market path is exported in this report/package.

## 1. What Was Actually Compared

- Two compatible ETHUSDT 1h cells, A-N1 and A-N2; 2020-01-01 inclusive
  through 2026-10-01 exclusive: 59,160 original marks, 2,465 complete UTC days.
- One fixed dictionary per account, original continuous carry/feedback,
  sizing, costs and terminal mechanics. Capital 20,000, leverage 1,
  one-way fee 0.0004, slippage zero, funding off. N1 retains its close-fill
  source route; N2 retains four reduce-only targets and next-open/risk-at-fill.
- The same original 128-point neutral panel per cell, not a new search.
  Exactly 128 distinct effective points, zero aliases/infeasible points per
  declared schema. This is finite coverage, not global intrinsic dimension.
- Baseline N1: original annual `environment_floor_mean_v1`, mean weight 0.25.
  Baseline N2: original annual frozen-reference `pareto_chebyshev_v1`, rho 0.01.
  Actual shared selector scores, masks and choices are reproduced.
- Challenger: minimize the upper 20% **probability mass** of quarterly regret,
  including fractional boundary mass, with weights proportional to actual
  quarter days. Tie tolerance 1e-10, then effective-ID order.
- All 27 complete calendar quarters are present. Each quarter's baseline
  is the preceding actual account mark, or original capital at the first bar.
  Quarter utility is net return minus within-quarter MDD minus daily-loss ES95.
  Carried-watermark drawdown is reported separately. Utilities are not additive.
- Original whole-account eligibility remains: finite whole Sharpe, whole U>=0,
  whole/annual risk DD<=50%, annual support >=180 days. Annual utility need not
  be positive. There are 46/128 eligible N1 points and 95/128 N2 points.
  No candidate-specific calendar masks or missing-outcome imputation.

The reference roster is 32 calendar-spaced/deduplicated actual Mode 4 native
anchors per cell, chosen without their forward outcomes. All 64 dictionaries
are newly executed as matched **static continuous accounts** before reference
ranking. Reset Mode 4 labels never stand in for these utilities.
For each quarter, b is the maximum measured reference utility; regret is b-U.
This is a hindsight finite reference benchmark, not a deployable switching
account, global optimum or equity splice. Valid negative regret is preserved.

Primary comparison changes **both** annual-versus-quarter temporal views and
selection policy. It does not identify a pure regret-algebra treatment effect.
Region evidence never changes rank, admission or ties. An additional frozen
32-point neutral reference provides a descriptive reference-choice control.

## 2. Main Results: One Static Dictionary, Not Terminal Equity Alone

| Measured quantity | N1 baseline | N1 regret | N2 baseline | N2 regret |
|---|---:|---:|---:|---:|
| Upper-20% quarterly regret, lower better | 0.445501 | 0.312004 | 0.292298 | 0.150083 |
| Maximum single-quarter regret, a different statistic | 0.535696 | 0.470231 | 0.361280 | 0.179258 |
| Worst quarter U | -0.353742 | -0.203059 | -0.211764 | -0.057403 |
| Lower-20% quarterly U | -0.258002 | -0.140657 | -0.184508 | -0.043377 |
| Positive-return quarters / 27 | 19 | 12 | 15 | 18 |
| Positive-U quarters / 27 | 9 | 5 | 5 | 6 |
| Positive-return calendar years / 7 | 7 | 4 | 5 | 7 |
| Positive-U calendar years / 7 | 4 | 1 | 1 | 3 |
| Whole return | 337.16% | 26.47% | 46.24% | 33.55% |
| Whole Sharpe | 1.0363 | 0.3650 | 0.4628 | 0.9209 |
| Whole MDD | 30.34% | 19.77% | 19.87% | 4.75% |
| Whole U | 3.041188 | 0.054172 | 0.244919 | 0.282446 |
| Final equity, from 20,000 | 87,432.47 | 25,293.50 | 29,247.25 | 26,709.95 |
| Close-mark exposure | 98.37% | 27.22% | 91.55% | 83.55% |
| Mean gross notional / equity | 0.29993 | 0.08174 | 0.19173 | 0.05603 |
| Actual fills | 235 | 3,036 | 2,753 | 574 |
| Total actual fees | 1,534.82 | 9,546.05 | 7,002.95 | 369.41 |
| Longest peak-to-end/recovery interval, days | 1,000.62 | 758.83 | 1,472.71 | 423.38 |
| Current unrecovered interval, days | 9.12 | 758.83 | 1,472.71 | 19.42 |

DD duration uses the existing actual-mark reporting contract. A duration can
be long despite positive calendar-year returns; these are different questions.
Seven years include partial 2026 (273 days), not seven complete independent years.
Exposure means any nonzero close-mark position; it is not capital at risk.
Fills are not closed campaigns/actions. Their original distinct counts remain
available in private account cards, not silently relabeled.

### N1: A Clear Counterexample To Automatic Replacement

Upper-20% mean quarterly regret falls about30.0%, but participation, Sharpe and time consistency
deteriorate. Positive quarters fall 19 to12, positive years7 to4, and the
current underwater episode becomes about759 days. There are many more fills
and much higher total fees despite lower average exposure. This is not no-trade
cash, but a materially more defensive/churn-heavy point. Better tail metrics
do not make it a better overall robust static dictionary for this baseline.
**Disposition: KEEP_BASELINE.**

### N2: A Useful Defensive/Consistency Trade-Off, Not Yet Promotion

Upper-20% mean quarterly regret falls about48.7%; positive quarters rise15 to18 and positive
years5 to7. Worst-quarter utility improves from -0.2118 to -0.0574,
whole U and Sharpe improve, and MDD falls about76.1%. However average gross
notional/equity falls about70.8%, and whole return declines12.69 percentage
points. Some improvement is plainly lower risk allocation; this experiment
does not identify a risk-matched timing/edge improvement.
**Disposition: INCONCLUSIVE for the full registered economic gate;
interesting CANDIDATE_FOR_PREFIX_TEST, with separate approval required.**

### Why The Objective Can Behave This Way

Two actual quarter decompositions illustrate the registered utility, not a new
preference fitted after outcomes:

| Cell/quarter/arm | Net return | MDD | Daily-loss ES95 | U |
|---|---:|---:|---:|---:|
| N1 2021Q1 baseline | 9.19% | 22.04% | 4.64% | -0.174959 |
| N1 2021Q1 regret | 1.45% | 10.88% | 1.51% | -0.109494 |
| N2 2021Q3 baseline | -7.48% | 11.40% | 1.97% | -0.208500 |
| N2 2021Q3 regret | 2.61% | 1.75% | 0.67% | 0.001935 |

N1 improves this penalized utility while sacrificing return: the reduction in
DD/tail penalties is larger than the lost return. Tail-regret optimization
does not compensate for every lost gain outside its worst probability mass.
This explains a defensive result without invoking a broken scorer or model.
N2's illustrated quarter improves both return sign and penalties. That is
more interesting than lower exposure alone, but not proof of a risk-matched
causal improvement: the actual parameter-dependent trading paths differ.

## 3. Calendar Readback

Annual net returns of the actual continuous paths; no reset or annual reselection:

| Year | N1 baseline | N1 regret | N2 baseline | N2 regret |
|---|---:|---:|---:|---:|
| 2020 | 60.08% | 3.20% | 43.06% | 5.91% |
| 2021 | 44.52% | 30.98% | 1.01% | 13.46% |
| 2022 | 13.73% | 6.37% | 11.61% | 4.09% |
| 2023 | 5.42% | -3.56% | -7.72% | 0.50% |
| 2024 | 7.50% | 7.34% | 4.35% | 1.59% |
| 2025 | 25.63% | -11.60% | 1.32% | 1.50% |
| 2026, Jan-Sep | 16.71% | -3.89% | -7.07% | 3.04% |

Positive return is not positive U: utility subtracts the registered DD and
daily-loss-tail preferences. A positive-return quarter may still have negative
U. No new every-quarter/year-positive requirement was introduced.

## 4. What The Archive And Regions Actually Add

The neutral-reference control selects the **same N1** regret point. Therefore
simply replacing the archive reference with a neutral one does not rescue
N1's observed defensive outcome in this panel.

N2's neutral-reference control selects a different point: final22,572.61,
Sharpe0.9006, MDD2.28%, whole U0.10342, seven positive years. The archive-reference
point has final26,709.95, Sharpe0.9209, MDD4.75%, U0.28245 and the same positive-year
count. Under the primary archive reference, neutral's J is0.154160 versus
archive's0.150083. Reference choice demonstrably changes the risk/return
compromise. It is not an alpha-independent proof that archived anchors are
always a better reference; this secondary control has no new significance claim.

Near-optimal tolerance remains0.5bps times actual calendar days. With finite
risk-qualified quarterly membership:

| Region fact | N1 | N2 |
|---|---:|---:|
| Quarters with no observed near-optimal neutral point | 11/27 | 8/27 |
| Distinct panel points ever in a quarterly region | 41/128 | 66/128 |
| Intersection across all quarterly regions | 0 | 0 |
| Maximum day-weighted membership of any panel point | 7.42% | 14.89% |
| Selected baseline membership | 7.38% | 0% |
| Selected challenger membership | 0% | 0% |

These are observed support facts relative to a fixed reference, not geometric
volume or proof that a robust dictionary cannot exist. A regret compromise
need never be within a tight near-best tolerance in any individual quarter.
Mode 4 anchors come from overlapping IS windows; neither their recurrence nor
neutral-panel density provides independent market replications.

Nearest five schema-Gower panel neighbors are explanatory observations,
**not held local probes**. N1 regret's five observed neighbors all have negative
whole U, at distances approximately0.152..0.307. This warrants caution, but
does not certify an isolated peak without radius/branch coverage. N2 regret's
five include four positive-U points and one negative, at approximately0.196..0.222;
that too is finite, relatively sparse support, not a basin PASS.
No new held/fee-stress accounts were authorized (registered cap0). Missing
actual-winner radii/stress remain explicitly UNKNOWN, not passed by proximity.

## 5. Market-State And Transition Views

Reuse the existing 168-hour prior-close feature provider: volatility, trend
and market activity, with .25/.75 quantiles. State at each UTC day open labels
that day's **actual account marks**. Unknown early states are retained.
Thresholds fit the full permitted development period; they are descriptive,
NOT_BACKDATABLE and never ranking inputs. Calendar quarters are not assumed
market regimes. Conditional state statistics do not splice prices or create
a state-only account/Sharpe.

For N1, the regret point loses2,322.66 in the middle-trend state and722.50 in
middle-volatility, where baseline gains20,647.84 and20,088.72. N1's smaller
aggregate loss tail therefore does not mean state-wide improvement.
For N2, baseline loses3,542.84 in the low-trend state,5,971.95 in high activity
and1,542.63 in high volatility. The regret point is positive in all three
known states of each feature family, with lower conditional daily-loss ES.
Different gross exposure and capital paths remain part of this comparison.
State-family PnL sums reconcile separately; families overlap and cannot be added.

There are619 trend,242 volatility and159 activity state changes. Registered
pre3/post3-day masks use unions, counting each calendar day once per reported
section; before and after sections may overlap and must not be added together.
Event rows are dependent, not iid experiments. N1 post-volatility-transition
mean daily return falls from +7.15bps to -0.17bps; N2 changes -0.49bps to +0.51bps.
These are descriptive adaptation clues, not proof that transitions cause losses
or a tested transition-penalty selection rule.

## 6. Uncertainty And Economic Dispositions

16,384 paired draws, seed731, complete three-calendar-month blocks, shared
market-date draws across arms/cells. Four declared primary contrasts use
simultaneous percentile tails0.00625/0.99375; expected102.4 draws per tail.

| Conditional fixed-path contrast | N1 | N2 |
|---|---:|---:|
| Challenger minus baseline J | -0.133496 | -0.142215 |
| Conditional simultaneous interval for delta J | [-0.230892,-0.013604] | [-0.198476,-0.066222] |
| Mean net daily return difference, bps/day | -5.635 | -0.622 |
| Conditional interval, bps/day | [-10.887,-0.485] | [-3.402,+2.274] |
| Registered daily-quality NI, lower bound >=-0.5bps | FAIL | NOT_ESTABLISHED |

Both show lower realized upper-20% mean quarterly regret, but neither clears the complete
regret-plus-quality condition. These intervals condition on already selected
full-development paths and a fixed measured reference. They do not estimate
search/selection uncertainty, independent future edge, a full-procedure
confidence guarantee or probability of live robustness. Multiple independent
prefix origins belong to M5-11.13, not to27 quarters of one reviewed path.
No threshold, exposure floor, seed, reference or objective was changed after
these results. Static regret is **not** Mode 4 R/Q or IS-minus-forward decay;
there is no new Ridge/meta-learning improvement measurement here.

## 7. Correctness, Work And Operational Scope

- 256 original account paths reused. Whole and all seven annual metric views
  reconcile to original shared owners, including shape-bound stream hashes.
- 64 new matched reference accounts; four actual selected replays. Each passes
  independent fill-ledger equity/positions/fees/funding/margin checks. Selected
  equity/position/fee/funding and margin hashes reproduce exactly; no reset
  labels, interpolated Ridge predictions or synthetic financial paths used.
- 8,640 final quarterly views over320 distinct primary/reference accounts;
  source-bound monetary and fee/funding conservation. Repeated failed cold
  wrapper attempts are not additional independent accounts or new finance.
- Zero optimizer proposals, ML fits, new held/stress accounts, builds,
  dependency changes or modifications to production source.
- XMR-011..020 research checks cover independent tail/region identities,
  synthetic stable/moving/losing/flat cases, missingness, conditional geometry,
  ties, original selectors, actual account reconciliation, state conservation,
  rights and work/privacy boundaries. See terminal qualification receipt.
- Final proof: **383 tests PASS**, comprising147 current research checks and236
  unchanged-source scoped regression checks. Independent review additionally
  binds exact registered32 reference membership/source/data identities and
  preserves the original baseline's exact tie/Pareto-front semantics. Replaying
  that hardened cold policy reproduces all observed scores and both choices;
  it adds no financial calls or new scientific treatment.
- Initial wrapper failures are retained: missing test source path, absent
  fixture parent, flattened positions, heterogeneous metadata comparison,
  relative output path and nonportable transition integer. Recovery changes
  only cold IO/rendering. Final summary recovery reads saved matrices; no
  account, optimizer or financial result is overwritten or rerun to improve it.
- Reference lanes elapsed71.67s N1 /107.66s N2; selected audit lanes11.78s /
  21.01s. Final successful cold matrix reductions54.50s /54.20s, renderer
  recovery5.87s /5.60s. These are measured lane times, not a public speedup or
  total phase wall time. Work runs within the registered research budgets.

See [cleanup](../maintenance/M5_11_11_CLEANUP.md). Exact prior/current source,
native artifact, input and output pins remain available locally. Historical
failed-reader source copies match the original failure hashes.

## 8. Research Conclusion And Next Review

1. Keep the original selectors/defaults. A single regret objective is not a
   universal substitute for the current alpha-sensitive preferences.
2. N1 is a useful negative control: relative tail robustness can select
   a lower-activity, high-turnover point with materially worse consistency.
   Adding a new anti-inactivity gate after seeing this result would be retuning.
3. N2 provides a concrete candidate for chronological investigation: smoother
   year/state outcomes and improved tail at lower risk/return. Separate
   risk-allocation, cost efficiency and predictive/selection claims before
   calling this stronger edge. No universal upgrade is justified by two cells.
4. Mode 4 archive information can change a static compromise without changing
   a sampler or training a model. It does not remove reference dependence or
   the need for actual matched account observations.
5. Any Mode 5 -> Mode 4 assistance must rebuild its full dependency graph at
   each lawful prefix. Truncating this dossier does not make it causal.

M5-11.12 sampler assistance and M5-11.13 whole-procedure/prefix experiments
still require separate approval. This research closes neither M5-11.9's
remaining obligations, the parent Mode 5 scope, M5-12 nor release.
