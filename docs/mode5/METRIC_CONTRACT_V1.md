# Mode 5 Research Metric Contract V1

## Authority And Boundary

Opt-in research primitives for [M5-03](../../upgrade/implement.md#mode5-m5-03),
following [guide Chapter 5](../../upgrade/QUANTBT_MODE5_UPGRADE_V1_DIAGNOSTICS_FIRST_GUIDE_VI.md#chapter-5).
This dictionary does not activate a selector or replace financial accounting,
ReportingContractV1, the QMS scientific MetricContract or legacy result fields.
Public integration is a separate M5-10/12 scope.

## Registry And Populations

| Derived field / formula ID | Input population | Unit and convention |
|---|---|---|
| `daily.mean_net_return` / `daily_account_simple_v1` | Qualified daily account path | Decimal simple return; zeros included |
| `daily.sharpe_period` / `period_sr_ddof1_v1` | Same daily excess returns | Original-period ratio, not annual |
| `daily.sharpe_annual` | Same series | Period SR times sqrt(365), independent of horizon length |
| `daily.skew`, `daily.kurtosis_ordinary` / `central_population_v1` | Same excess returns | Biased standardized central moments; kurtosis includes 3 |
| `daily.psr` / `classical_psr_plugin_v1` | Same N, SR, skew, kurtosis | Evidence probability under stated assumptions; not edge posterior or DSR |
| `daily.hac_evidence` / `sharpe_evidence_hac_v1` | Same ordered excess returns | Separate population-SR/HAC convention; not classical PSR with ESS |
| `daily.loss_es` / `upper_loss_mass_es_v1` | Loss = minus daily net return | Exact upper mass 1-q; fractional atom |
| `campaign.profit_factor` | Net closed position campaigns | Gains/losses in quote currency, costs allocated once |
| `campaign.net_pnl_tail` | Same closed campaigns | Quote-currency lower tail, not daily-return ES |
| `environment.lower_tail` / `lower_environment_mass_v1` | Explicit finite utility panel | Utility/evidence channel units, frozen weights |
| `environment.regret` / `frozen_reference_regret_v1` | Candidate/reference on same environment IDs | Components b-v, mean and max; reference revision explicit |
| `raw_sharpe`, `penalized_objective` | Qualified legacy scientific record | Preserve separate values, original formula IDs and penalty witness |

Execution fills, closed campaigns and daily observations have independent
support counts. A partial exit is not another completed campaign. Open/censored
campaigns remain part of account MTM but not closed-campaign PF. Return-step PF
from MET remains correctly labeled; it is not silently renamed campaign PF.

## Return And Account Policy

Reuse `quantbt.metrics.reporting.AccountObservations`, `ReportingContractV1`
and `reduce_account`; do not implement another account simulator. Caller must
provide authoritative equity before the first retained observation, UTC scope
times and partial-period witness. The first fee/loss is included. UTC bucket
closes use the existing observed-only reducer; no zero/forward-filled missing
day or removal of flat trading days. Sparse calendar gaps block daily inference
unless a separately explicit frequency contract is supplied.

Money-PnL blocks use the preceding equity, including the scope-entry mark;
money deltas add, simple returns compound. Initial equity is the first high
watermark. MDD is a positive magnitude, never the absolute value of an arbitrary
unknown legacy convention. CAGR uses actual elapsed days, with the declared
365.25-day reporting year, not number-of-bars annualization.

Nonpositive equity is a valid adverse path. Return ratios after a nonpositive
denominator and log/CAGR after nonpositive growth are unavailable; paths are not
dropped or clamped. External cashflow-adjusted returns need an authoritative
engine-defined witness; raw equity must not be treated as flow-adjusted PnL.
Cashflow support is not invented by this phase.

## Statistical Policy

- Period Sharpe: arithmetic excess mean / sample standard deviation, ddof=1.
  Risk-free per-period value is explicit; annual geometric RF converts through
  `expm1(log1p(rf_annual)/A)`, not an implicit divide or inferred source.
- Moments: central population second/third/fourth moments; ordinary kurtosis.
  No assumption-based Gaussian replacement of empirical moments.
- Classical PSR: guide formula with same-series N>=3, finite moments, positive
  variance and positive denominator. Annual SR/reference must be explicitly
  converted before this formula. Bad/insufficient inputs produce null + reason.
- HAC: centered influence function, population variance/SR, Bartlett lag weights
  and N divisor, no finite-sample multiplier. Registered bandwidth 5/minimum
  32/normal 95% interval. Expose SE, CI, z, evidence, lag-0 and long-run variance.
  Fixed bandwidth is not claimed optimal for every market. Stationarity and
  moment assumptions remain; negative dependence need not increase SE.
- Moment intervals: fixed-path circular blocks, length 7, 256 draws, seed 731,
  95% percentile intervals; preserve invalid-draw count. These do not cover
  candidate/recipe selection uncertainty or certify IID observations.
- Tails consume exactly the declared probability mass; zero-weight observations
  are excluded from support. Upper-loss ES can be negative when all returns
  gain; it is not clamped to a favorable zero. Tail support/concentration is
  retained, not interpreted as independent episode count.
- Weighted median/MAD: stable ordering, lower median at exact half-mass tie.
  References, channel units and environment identities are frozen before use.
  No new composite objective is activated here.

## Null And Availability Policy

Valid numeric outputs are finite and versioned. `INSUFFICIENT`, `UNDEFINED`,
`INVALID`, `UNAVAILABLE`, `REPLAY_REQUIRED`, `NO_LOSS` and `BANKRUPT` have null
values and explicit reasons. All-zero/no-trade series retains its zero account
return but has undefined Sharpe/PSR. PF with gains but no losses is `NO_LOSS`,
not an arbitrarily capped finite score; no closed campaigns has no PF.

Summary-only Sharpe/DD/fill counts cannot supply moments, serial structure,
campaigns or actual returns. A failed simulation is not a numerical summary
eligible for ranking. Reanalysis retains source hashes, raw records and all
unavailable components; it does not manufacture richer engine output.
