# M5-11.1 Economics And Frozen Checkpoint

Status: **OWNER_REVIEW / FINANCIAL_EXECUTION_STOPPED**. This is a descriptive
report of completed development measurements, not full M5-11.1 completion,
independent forward qualification, release approval or a new execution request.

Authority: [unified plan](../../upgrade/implement.md#mode5-m5-11-1),
[detailed guide](../../upgrade/QUANTBT_MODE5_UPGRADE_V1_DIAGNOSTICS_FIRST_GUIDE_VI.md#phase-m5-11--formal-calibration-pilot-independent-checks-và-economic-inference),
and [full execution report](M5_11_1_BROAD_DIAGNOSTICS.md). Historical receipts,
failures, censored attempts, source, candidates and scientific preferences remain
unchanged. All alpha parameters, source and financial paths remain private.

## Measurement Scope

- RSI: ETHUSDT 1h, original legacy `pct_equity` account route. SC, HMA, HASH
  and VWAP: BTCUSDT 1h, each original qualified alpha/account binding.
- Preload: 2020. Scored development: 2021-01-01 inclusive through 2024-01-01
  exclusive, 26,280 hourly bars and 1,095 complete UTC days per configuration.
- Every completed configuration runs one continuous account. Annual views
  use the same account path; no annual account reset or spliced yearly equity.
- Each alpha has 128 outcome-independent, unique effective configurations
  registered with seed 731 and branch-balanced scrambled Sobol proposals.
  These are diagnostic configurations, **not 128 adaptive Optuna trials**.
- Initial capital is 20,000 USDT. RSI retains its 50%-equity sizing, original
  funding/slippage and canonical one-way fee 0.00025, converted from legacy
  `fee=0.0005`. The supplied alpha bindings retain 2,000-USDT notional,
  one-way fee 0.0004, no funding and zero configured slippage. Do not infer
  a cross-alpha performance ranking from different allocation/contracts.
- Daily Sharpe is annualized with 365 periods. The frozen descriptive utility
  is `U = net account return - maximum drawdown - daily loss ES`, with both
  preference coefficients fixed at 1. This is the registered preference for
  this study, not a universal default or an annualized performance rate.
  Actual costs are already in net return; they are not deducted again.
- Forward 2024-2025 is **NOT_RUN in this stage**. Existing reviewed historical
  data would not become untouched OOS merely by being labeled forward.

## Completed Broad Panels

RSI and SC each completed all 128 registered configurations. Values below
describe alternative candidate accounts, not a combined portfolio. Individual
metric extrema can belong to different configurations.

| Whole development metric | RSI Minimum / Median / Maximum | SC Minimum / Median / Maximum |
| --- | --- | --- |
| Net return | -41.50% / +29.37% / +189.62% | -4.85% / +6.73% / +18.21% |
| Annualized growth | -16.37% / +8.96% / +42.54% | -1.64% / +2.19% / +5.74% |
| Daily Sharpe, annualized 365 | -0.737 / 0.559 / 1.708 | -0.427 / 0.537 / 1.142 |
| Maximum drawdown | 9.91% / 21.42% / 58.96% | 0% / 7.29% / 12.11% |
| Daily loss ES | 1.23% / 2.19% / 5.25% | 0% / 0.56% / 0.69% |
| Registered utility | -0.94162 / +0.07751 / +1.68481 | -0.15603 / -0.00842 / +0.12048 |

RSI: **108 profitable / 20 unprofitable**, no zero-exposure configurations.
SC: **122 profitable / 4 unprofitable / 2 valid no-trade**; Sharpe is undefined
for both no-trade accounts, not zero or a favorable sentinel. SC Sharpe's
descriptive median uses its 126 defined observations.

SC's panel retains 11,224 fills, 5,571 closed and 82 terminal-open campaigns
across alternative account runs. They are not independent trades or one
portfolio's inventory. Maximum independent equity residual is zero; campaign
versus account PnL residual is about 3.217e-10 USDT, below the unchanged 1e-8
absolute tolerance. RSI's legacy route did not retain accepted-fill, campaign
or cost-component ledgers; their support remains unavailable, not fabricated
from position-regime transitions.

### RSI Landscape And Cost Findings

1. The complete three-year panel contains materially positive outcomes, but
   different years rank parameters very differently. Annual utility-rank
   Spearman correlations are -0.025, +0.106 and -0.086; annual near-optimal
   sets have zero pairwise overlap under the registered definition.
2. Only three configurations pass all annual risk/quality/day gates. On the
   same finite panel, floor/Chebyshev select original index 56, with annual
   utilities +0.42478 / +0.28013 / +0.04836. Lower-tail selects index 49,
   with +0.18677 / +0.04767 / +0.12558. This is retrospective reranking,
   not the planned separate adaptive baseline/challenger study.
3. The same-panel raw-Sharpe control selects index 10, unlike the pooled
   utility winner. Do not describe the pooled utility winner as traditional
   raw-Sharpe optimization. All six kept-gate floor/lower-tail leave-one-year-
   out held utilities are negative, between -0.12561 and -0.30588. These
   omission diagnostics are not chronological forecasts, but they do not
   establish a transferable invariant parameter choice.
4. Two centers have 155 actual full-period neighborhood executions, covering
   all eight active axes and declared coupled directions. All 155 net returns
   are positive, but four role-specific rows have negative utility. Both
   centers remain `FRAGILE_CENTER` under the frozen all-probe quality policy.
   Selection-probe quality survival is 96.55% and 97.87%, not 100%.
5. Of 79 validation executions, 42 overlap selection effective coordinates.
   The 37 genuinely new held coordinates all have positive return and utility;
   their minimum utilities per center are +0.74822 and +0.45199. This is useful
   local development evidence, not independent temporal OOS. Reexecuting an
   overlapping adverse coordinate verifies repeatability, not a new adverse
   observation. Covariance proposals are not a Hessian or a global bound.
6. Actual **2x-fee reruns of all 128 original configurations** preserve source,
   signals, exposure, funding, slippage and sizing. The canonical one-way fee
   changes from 0.00025 to 0.0005; base accounts are identity-verified reuse.
   Median paired changes are -0.06836 Sharpe, -4.23519 percentage points net
   return, -0.05187 utility and +0.70362 percentage points drawdown. Stress
   medians are +24.34% return, 0.487 Sharpe and +0.01749 utility. Profitable
   configurations fall from 108 to 104; 62 stressed utilities are negative.
   Utility rank changes for 108/128 points, by at most 14 places. These are
   actual account reruns, not posthoc fee subtraction. A difference of medians
   is not the median paired change.

### SC Landscape And Weak-Environment Findings

1. Positive whole-period returns do not establish acceptable utility or
   stability: median return is +6.73%, but median utility is -0.00842.
2. In 2022, 119 configurations have negative marked account PnL and nine have
   no trades. None has positive annual utility, so the unchanged all-environment
   quality gate yields `NO_SELECTION`. Its eligible Pareto front is empty;
   agreement between two null choices is not a compromise-selector result.
3. Median 2022 marked PnL is -862.15 USDT. On the same actual fills, adding
   recorded fees back gives median -812.20 USDT; all 119 active paths remain
   negative before those fees, with zero fee-only sign flips. Median recorded
   fee is 16.91 USDT and funding is zero. Medians are not additive. This bridge
   holds execution prices fixed; it is not a frictionless strategy rerun or
   a complete market-versus-execution causal decomposition.
4. The same-panel raw-Sharpe control is index 33, Sharpe 1.14249. Omitting 2022
   also selects it under floor/lower-tail, but its held 2022 utility is -0.05401.
   This is development omission evidence, not independent forward failure.
5. All 58 registered local executions have positive returns (+0.87% to +19.99%),
   but utility ranges from -0.08621 to +0.15427. Both centers are
   `FRAGILE_CENTER`; validation quality survival is 78.57% and 86.67%.
   Each center has eight genuinely new held coordinates; overlaps remain
   dependent repeatability checks. The neighborhood ledger reconciles 3,928
   fills, 1,936 closures and 56 boundary-open campaigns across candidate runs.

## Partial Native Alpha Measurements

These are original ordinal discovery points, not selected winners or broad
panels. They cannot support statements about whole-space alpha quality.

| Completed configuration | Net return | Sharpe | Max DD | Utility | Fees, USDT | Fills | Closed / Open campaigns |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| HMA original 0 | +6.8794% | 0.44533 | 8.0695% | -0.01779 | 515.60 | 645 | 322 / 1 |
| HASH original 0 | +3.1210% | 0.37746 | 6.4124% | -0.03653 | 428.44 | 758 | 267 / 1 |
| HASH original 1 | +0.6202% | 0.07332 | 4.1921% | -0.03889 | 673.32 | 1,138 | 421 / 1 |
| VWAP original 0 | 0% | Undefined | 0% | 0 | 0 | 0 | 0 / 0 |

For example, HMA's +6.8794% net return minus 8.0695% drawdown minus 0.5892%
daily loss ES gives negative utility. This is the frozen risk preference,
not negative cash PnL or a proven absence of alpha edge. HASH rung/partial
fills are not independent campaigns; its second point has more activity and
fees but less net return. Two observations do not identify a causal relationship.

VWAP is the same original no-trade configuration after approved inactive-input
restoration and strict empty-ledger checker recovery. All 128 constructor
inputs/effective IDs verify, but **only one account configuration executed**.
Its undefined Sharpe/PSR does not imply zero statistical evidence from a traded
sample or absence of VWAP edge. No eventful VWAP runtime estimate is available.

### Work Bill And Stop

| Workstream | Supervisor or completed driver time | Actual account passes | Peak financial RSS |
| --- | ---: | ---: | ---: |
| RSI broad panel | Supervisor 112.13 s | 256, including reused pilot | 345.93 MiB |
| RSI neighborhood | Supervisor 155.72 s | 310 | 349.08 MiB |
| RSI 2x-fee scenario | Supervisor 125.09 s | 256 new stress passes | 342.84 MiB |
| SC broad panel | Supervisor 40.03 min | 128, including reused pilot | 611.83 MiB |
| SC neighborhood | Supervisor 18.42 min | 58 | 563.19 MiB |
| HMA original 0 | Driver 50.25 min | 647 native + 1 Python | 555.23 MiB |
| HASH original 0 | Driver 35.10 min | 538 native + 1 Python | 612.23 MiB |
| HASH original 1 | Driver 61.60 min | 845 native + 1 Python | 647.04 MiB |
| VWAP original 0 | Driver 17.94 s | 2 native + 1 Python | 563.54 MiB |

These clocks are explicitly different and cannot be added into one wall time;
some workstreams overlapped and original pilots are reused. Supplemental
terminal-owner audits add one Python account pass for each HMA/HASH pilot.

The expensive native stage is the existing offline **actual-fill-feedback
fixed-point compiler**, repeatedly executing full tapes to propagate strategy
feedback. HMA compiler alone takes 3,001.85 s; HASH original 1 takes 3,672.03 s,
versus 18.27 s for its final Python owner comparison and 4.26 s for reduction.
One native kernel pass does not take 35-62 minutes. Replacing the compiler
with guessed signals/fills would change the financial contract.

Owner-stopped HMA point 1 ran 122.89 minutes with at least 1,344 native passes;
HASH point 2 ran 53.47 minutes with at least 784. Neither produced a final
economic cell. They are censored, **not zero-return, failed economic or completed
runtime samples**. Exact incomplete work is unknown; historical capped attempts
also remain retained. No reliable full-panel ETA follows from these samples.

## Correctness And Qualification Limits

- Original ordered fills and retained cash-account arrays reconcile within
  their declared contracts. Supplementary HASH margin residuals are tiny and
  below the unchanged 1e-8 tolerance, not asserted bitwise zero.
- Independent annual monetary reconciliation is zero, with wealth residuals
  below 4.45e-16. The volatility attribution fits its provider on 2020 only,
  labels from previously available information and conserves actual account
  PnL/exposure/costs. It is retrospective attribution, not a vintage seal.
- There is a genuine HMA cold OCO outcome-projection defect: 249 actually
  filled winners appear `CANCELED`. Cancellation counting units also differ
  between event rows and cancelled order slots; some raw liquidity labels
  differ. Full native terminal working-state output is absent from the
  retained static surface. **Full lifecycle/terminal parity is not qualified**.
  These gaps are not evidence of differing measured cash PnL, nor permission
  to conceal them or claim full Rust/Python owner equivalence.
- The 61 ingestion/design controls, 12 volatility chronology/conservation
  controls and latest 36 cold analytic tests have retained PASS receipts.
  Earlier overlapping analytic suites must not be added to the latest count.
  Software/control tests do not replace five-alpha economic coverage.
- Trend/activity views, complete batteries/matrices/dossiers, actual matched
  adaptive baseline/challenger studies, inferential uncertainty and multi-origin
  chronological transfer are incomplete. No claim of selector superiority,
  improved forward decay, deployment readiness or alpha-wide lack of edge.

## Freeze And Approval Boundary

Completed registered coverage is RSI **128/128**, SC **128/128**, HMA **1/128**,
HASH **2/128**, VWAP **1/128**. The remaining panel requests are **127 HMA,
126 HASH and 127 VWAP**; their probes and dossiers also remain unfinished.
Completed RSI/SC work and native pilots should use verified reuse, not be
rerun merely because another tranche is authorized.

This report's cold review rechecked **2,813 unique files** against existing
retained-result manifests: zero size/hash failures and zero conflicting pins,
207,499,675 bytes read. No financial runtime, signal generator, optimizer,
build, install, source mutation or new financial worker was invoked. This is
present custody verification, not a retroactive execution seal.

Preserve all source/data/identity pins, complete/failed/censored outputs, logs,
original manifests and exact native artifacts. The owner-stop and
[cleanup receipt](../maintenance/M5_11_1_TRANCHE_CLEANUP.md) remain authoritative;
only an inactive reproducible cache was removed, recovering 1.40 MiB. No more
deletion is part of this review. The study is frozen at completed-candidate
granularity, not a read-only filesystem or certified mid-compiler checkpoint.

Next financial execution requires a new owner-approved scope. A stopped native
candidate requires a fresh registered attempt; exact mid-compiler continuation
is not implemented. Runtime/schema gap disposition precedes broader qualification.
M5-11.2 actual 256-trial studies and M5-11.3 forward studies remain **NOT_RUN**.
