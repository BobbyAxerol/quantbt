# Reporting Contract V1

**MET-01:** proposed definitions, independently tested; owner acceptance pending.
This document does not activate new production metrics. The internal
[schema](../../src/quantbt/metrics/report_contracts.py) is not imported by an
endpoint, scorer or native adapter. Read the [phase guide](../../upgrade/implement.md#metrics-met-01)
and [inventory](INVENTORY.md) before MET-02.

## Identity And Boundary

`quantbt.reporting.v1` is separate from legacy `full_report()`, native
`MetricContractV2` and the QMS scientific contract. Stable `reporting.*` metric
IDs, contract SHA256, result identity, producer, profile, currency/unit,
coverage and sample count accompany every value. Policy changes change the
hash. All nested policy/coverage objects are immutable; JSON round trips
preserve every field and reject unknown/version-mismatched fields.

No constructor/backtest/result shape or existing key/default is changed here.
MET-02 may implement additive read-only reducers after acceptance; MET-03 may
integrate opt-in reporting after its separate approval. Neither may change an
optimizer's scientific contract just by replacing a report dictionary.

## Baseline And Samples

- Full scope uses recorded account starting equity and its real instant, not
  the first retained post-cost mark. Baseline may share that timestamp: a
  first-mark fee is a return/DD observation, not an invented earlier bar.
- Scoped baseline is account equity at scope entry before included mutations.
  Example: original capital 100, scope entry 120, final 132 means scope return
  10%, not 32%. Opening trade history and carried account state stay intact.
- Equity timestamps normalize to UTC epoch nanoseconds, strictly increasing
  after the declared producer's consolidation. Naive timestamps require an
  explicit upstream timezone. Reject unordered/duplicate/non-finite input;
  the oracle never silently sorts, drops NaNs, clips or fills calendar gaps.
- Positive baseline is required; later zero/negative equity is valid raw data.
  Total return is `final / baseline - 1`, including bankruptcy. Fractional
  CAGR is undefined when terminal growth is nonpositive, not `abs(growth)`.
- External cashflows are unsupported by V1: even a recorded deposit amount
  cannot identify TWR without pre/post-flow valuation. Reject flow-adjusted
  claims rather than subtracting a deposit and calling the result TWR.
- Sampling is explicitly `observed_bar`, `observed_daily_utc`, or
  `explicit_period_returns`; annual periods are declared, not guessed.
  Daily reduction uses observed UTC day-end marks and a recorded boundary
  mark for the first included return. Missing days are not synthetic zeros.
  Label gap-spanning returns and partial first/last intervals. `include_disclosed`
  and `exclude_disclosed` are different policy identities; no distribution
  statistic compares unmatched samples. A daily path cannot certify intraday DD.
- Disjoint OOS windows default to reject for one CAGR/DD path. With
  `independent_segments`, each segment has its own recorded baseline/high-water
  mark and result identity; do not annualize a concatenation or count gaps as
  simulated exposure. A genuinely continuous account retains gap observations.

## Account-Period Dictionary

All ratios/returns below are numeric fractions; percentages are display-only.
Periods include recorded zero returns in the population unless explicitly
declared otherwise. RF, MAR and Omega threshold are **per-period simple rates**.
Annual RF must first be converted using an explicit convention outside this
schema; it is not silently divided by 365.

| Metric ID suffix (`reporting.account.*`) | Definition / undefined policy |
|---|---|
| `total_return` | `E_end / E_baseline - 1`; no external flows |
| `cagr_elapsed` | `expm1(log(E_end/E_baseline) / elapsed_years)`, years = exact elapsed UTC days / declared year days (proposed 365.25); less than declared minimum days (proposed 1) is insufficient, not Total Return |
| `cagr_period_count` | growth raised to `annual_periods / actual_return_count` minus 1; separately labeled, QS-comparable only with the identical boundary returns |
| `sharpe` | mean `(r-RF)` / sample SD `(r-RF, ddof)` times sqrt(annual periods); insufficient N or zero SD is undefined |
| `sortino_all` | mean `(r-MAR)` / sqrt(sum(min(r-MAR,0)^2) / N), annualized; no downside + positive excess is `no_loss`, zero/negative numerator with zero denominator is undefined |
| `sortino_conditional` | same numerator, denominator N_negative; explicitly selected convention, not legacy's nonzero-MAR numerator bug |
| `omega` | sum positive `(r-threshold)` / absolute sum negative `(r-threshold)`; no losses and positive gains is `no_loss`, all zero is undefined |
| `period_profit_factor` | same ratio at zero threshold; not closed-trade PF |
| `period_avg_win/loss` | conditional mean positive/negative r; absent bucket unavailable |
| `period_win_rate` | N_positive / N including zeros; QS excludes zeros, so that comparison must be named `nonzero_period_win_rate` |
| `period_mean_arithmetic/geometric` | mean r / compounded growth^(1/N)-1; geometric unavailable for any r <= -1 |
| `calmar` | declared CAGR / max observed DD; undefined for zero DD or unavailable CAGR |
| `ulcer_index` | sqrt(mean(D^2)) across all observed equity marks, fraction units |

No exponent clamp or manufactured finite ratio. Overflow is an explicit
invalid/non-finite result, not silent clipping. Short-sample policies and
undefined statuses are independent of legacy/native compatibility zeros.

## Drawdown Episodes

`H_t=max(baseline,E_s through t)`, `D_t=1-E_t/H_t`. Positive baseline makes
H positive; negative equity may produce DD above 100%. Use the actual
`bar_close`, `daily_close` or `recorded_event` clock, never claim unseen extrema.
Episode fields: peak/start-underwater/trough/end timestamps and values,
recovery timestamp (nullable), recovered/open state, deepest depth, observed
underwater mark/day counts, inclusive underwater calendar days, and exact
elapsed nanoseconds. Session counts require a supplied trading calendar.

Repeated equal highs use the **latest** peak time. Equal-depth troughs use the
earliest trough. Episode ordering, deepest/longest ties use earliest episode
start. Recovery equals/exceeds H, with optional explicit relative tolerance
(proposed 0). Tolerance affects episode classification only, not equity/DD/costs.
Elapsed duration is peak -> recovery; open is peak -> final observation and
right-censored. Inclusive underwater days are first -> last underwater UTC
date plus 1, not peak -> recovery. Two underwater observations separated by
three missing days remain two observations, not two elapsed days.

`max_depth`, `deepest_duration`, `longest_duration`, `longest_recovered_duration`,
`current_open_duration`, `episode_count`, `mean_episode_depth`,
`mean_underwater_observation_depth`, `mean_recovered_duration` are separate
fields. Mean episode depth includes open episode troughs; recovered-duration
mean excludes open episodes. No episode means depth/count/duration-zero is
valid, but a mean over an empty recovered population is unavailable.

## Closed Trades And Actions

Accepted executed ledger is authority, not signals, targets or snapshots.
Declare existing matching: position episode / average cost / recorded lot.
Do not choose a new matching or cost-allocation algorithm in reporting.
Partial exits, scale-in/out, reversals, rejection and forced closure require
existing completed identities/cost allocation; insufficient inputs yield N/A.

An action is an authoritative action/campaign/package ID. All its obligations
must be closed/settled; unrelated open account positions do not block closure.
Opposite-side legs aggregate net PnL **before** action win/loss classification.
Timestamp/symbol equality alone is not an action ID. Existing bounded roll/
pre-expiry flatten retains recorded IDs; do not invent hold-through-expiry or
chain unrelated roll packages into one campaign.

For complete closed outcomes `x_i` in one currency, G=sum positive x,
L=absolute sum negative x, N=closed_count:

| Metric (`reporting.trade.*` / `reporting.action.*`) | Definition |
|---|---|
| `closed_count/win_count/loss_count/breakeven_count` | closed population only; win/loss compare explicit currency tolerance (proposed 0); breakeven remains in N |
| `win_rate` | win_count/N, including breakeven |
| `avg_profit/avg_loss` | G/N_win, signed -L/N_loss; absent bucket unavailable |
| `avg_pnl/expected_payoff` | (G-L)/N, same population; not a return-per-bar expectancy |
| `profit_factor/payoff_ratio` | G/L / avg_profit divided by absolute avg_loss |
| `largest_win/loss/median_pnl` | population net currency PnL, signed losses; absent bucket unavailable |
| `top_profit_concentration` | largest positive outcome / G, only G>0 |
| `max_win/loss_streak` | close timestamp then authoritative event sequence; breakeven breaks both streaks |
| `holding_time/bars` | recorded opening/closing boundaries and coverage; no inferred bar count from elapsed duration |

Tolerance classifies outcomes only: sums/averages keep all exact net PnL; tiny
residuals are not erased. With nonzero tolerance, bucket sums for conditional
averages use those classified buckets; expose total net PnL separately.
N=0 has valid zero count but unavailable sample statistics. G>0,L=0 is
`no_loss` (presentation may show infinity); G=L=0 is undefined. No nonstandard
NaN/Infinity JSON: `value:null`, explicit status/reason and population count.

Net ledger already includes recorded costs: do not subtract them again.
Gross ledger may become net only with complete authoritative, allocated fee/
funding/cost data; funding credits retain sign. Slippage embedded in fill
prices is not subtracted twice. Separately recorded slippage costs are a
different policy. Cross-currency outcomes cannot be added without recorded
conversions and timestamps. Trade percentages need recorded entry gross
notional/risk/margin; never divide hedged PnL by near-zero net notional.
MFE/MAE require a sufficient synchronized mark path, R requires initial risk.

Scoped ledger policies are distinct: `closed_in_scope_lifetime` includes the
whole PnL of a carried trade closed inside the scope; `in_scope_attribution`
requires recorded boundary valuation/cost attribution. Closed lifetime PnL
does not generally equal scope equity change. Open PnL, costs and cashflows
reconcile only under a matched valuation boundary; no report-induced close.

## Coverage And Review

`complete` with zero rows means an actually empty ledger; `omitted`,
`truncated` (retained/dropped counts) and `unsupported` need explicit reasons.
Dataclass fields defaulting to empty do **not** certify completeness. Scope
filtering of rows must be independently verified. No ledger inference/replay.

Owner review before MET-02: approve these report-only defaults/definitions,
optional convention choices, source/capability limitations, separate namespace
and no scientific migration. Public API wiring is deferred to MET-03; its
exact additive syntax needs review, not silent replacement of `full_report()`.
No performance result, economic claim or release qualification is asserted.
