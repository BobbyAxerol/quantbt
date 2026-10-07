# MET-01 Producer, Consumer And Raw Inventory

Source is bound by [baseline.json](evidence/met01/baseline.json); all existing
production Python/Rust/mirror/packaging bytes are protected. This is a source
inventory, not renewed certification of every execution route. The new
[reporting contract](REPORTING_CONTRACT_V1.md) does not replace current outputs.

## Producers And Consumers

| Source | Role / actual unit / protection |
|---|---|
| [performance.py](../../src/quantbt/metrics/performance.py) | Legacy pandas helpers, shared array reducer and `full_report`; daily account returns or intraday fallback, side masks and position-change counters; preserve all defaults/keys |
| [types.py](../../src/quantbt/core/types.py), [results.py](../../src/quantbt/core/results.py) | Raw legacy/V2/array/options containers, daily convenience methods and report entrypoints; `daily_equity` resampling can forward-fill unlike array observed-day selection |
| [scopes.py](../../src/quantbt/core/scopes.py) | Auto/full/OOS report slice; original initial capital and unsliced orders/fills/trades survive; scoped ledger/baseline is not yet normalized |
| [orders.py](../../src/quantbt/core/orders.py) | Fill/Trade shapes; optional trade_id, realized_pnl and fees do not declare universal net/allocation completeness |
| [accounting_contracts.py](../../src/quantbt/core/accounting_contracts.py) | Accounting identity and protected scientific/financial boundary |
| [metrics_v2.rs](../../rust/crates/quantbt-engine/src/metrics_v2.rs) | Online native scalar authority: initial baseline, elapsed CAGR, full-population downside, committed-fill counters, finite compatibility short/zero outputs |
| [reactive_score.rs](../../rust/native_event/src/reactive_score.rs) | Compatibility reactive score; not automatically the native V2 reporting convention |
| [native_result_v2.py](../../src/quantbt/core/native_result_v2.py) | Cold SoA/DataFrame adapter; score/compact/audit retention, capped/dropped audit rows; never replay |
| [native_event.py](../../src/quantbt/backends/native_event.py) | Python/reactive/prepared scores plus legacy report and native V2 metadata; fill/order/diagnostic retention depends on profile |
| [native_vectorized.py](../../src/quantbt/backends/native_vectorized.py), [native_portfolio.py](../../src/quantbt/backends/native_portfolio.py) | Array compatibility reports, symbol/cost/rebalance/package attribution; minimal omits heavy reports |
| [native_prepared_evaluation.py](../../src/quantbt/backends/native_prepared_evaluation.py), [native_metric_support.py](../../src/quantbt/backends/native_metric_support.py) | Score bindings/profile and prepared legacy metric support; no report path retention added |
| [intrabar_reference.py](../../src/quantbt/core/intrabar_reference.py), [intrabar_kernel.py](../../src/quantbt/core/intrabar_kernel.py), [intrabar_session.py](../../src/quantbt/core/intrabar_session.py) | Intent/session accounting plus optional audit/fill replay; scope includes actual current liquidation semantics unchanged |
| [native_portfolio_package.py](../../src/quantbt/backends/native_portfolio_package.py), [native_package_arbitrage.py](../../src/quantbt/backends/native_package_arbitrage.py) | Shared portfolio/package native request/account, instrument/admission identities; no new roll/settlement semantics |
| [ledger.py](../../src/quantbt/options/ledger.py), [options_analytics.py](../../src/quantbt/metrics/options_analytics.py) | Option execution/cash/settlement-currency PnL and package Greeks; currency/conversion/package closure coverage required |
| [endpoint.py](../../src/quantbt/endpoint.py) | Reports/show_metrics/plots and endpoint WFO scorer; report `num_trades` feeds both trade count and turnover proxy, not monetary turnover |
| [walkforward.py](../../src/quantbt/walkforward.py), [reactive_wfo_support.py](../../src/quantbt/backends/reactive_wfo_support.py) | Selection/objective/constraint scoring, fold/stitching and prepared evaluations; all five mode methods unchanged |
| [objectives.py](../../src/quantbt/optimization/objectives.py), [evaluators](../../src/quantbt/optimization/evaluators/) | Generic/signal/intrabar/portfolio/grid/arbitrage/options objective extraction and penalty populations; protected scientific consumers |
| [observer.py](../../src/quantbt/optimization/meta_selection/observer.py) | Source-hashed canonical metric contract, original IS/forward measurements, trade constraints and decay labels; must not see report V1 |
| [plots.py](../../src/quantbt/viz/plots.py), [portfolio_audit.py](../../src/quantbt/reporting/portfolio_audit.py), [arbitrage_audit.py](../../src/quantbt/reporting/arbitrage_audit.py) | Display strings vs numeric units; audited cost/PnL reconciliation does not imply closed-action classification |
| [nautilus_bundle.py](../../src/quantbt/reporting/nautilus_bundle.py) | Optional external QS daily report with explicit frequency/periods; not financial oracle |

Qualification includes a machine-discovered metric-reference census, not only
the manual table: metric/full-report/score/drawdown references are registered
per tracked source file. Tests verify unchanged producer/consumer source hashes.
The source census is retained with each receipt, alongside the immutable
baseline. Legacy WFO signal scoring also has its own nonzero-entry/
quantity-change count and absolute quantity turnover, unlike the endpoint
scorer's `num_trades` proxy; these contracts are not merged here.

Existing `quantbt.metrics` import reaches backend modules through
`performance -> core.types -> core.__init__`. MET-01 does not refactor that
historical import graph. Its schema body is standard-library-only; the normal
import adds no backend modules beyond the pre-existing graph and works without
QuantStats/matplotlib/native extension/Nautilus. Imports are not execution.

## Existing Metric Dictionary / Migration Proposal

| Current field | Actual legacy meaning | Disposition (no default change in MET-01) |
|---|---|---|
| `initial_capital/final_equity/liquidated` | Raw account fields | Keep; scope needs recorded entry baseline |
| `total_return_pct` | Final vs initial capital | Keep full scope; separate scoped baseline metric |
| `cagr_pct` | First retained mark growth, elapsed 365.25 days/year, <1 day uses total return, log clipped +/-50 | Identified compatibility output; separate elapsed/period-count report CAGR |
| `sharpe` | Sample SD, annualization daily or inferred intraday | Keep named legacy; new explicit sample policy |
| `sortino` | Negative-only RMS, numerator mean r, conditional denominator | Keep compatibility; add all/conditional MAR-correct alternatives |
| `calmar` | Legacy CAGR / observed-first-mark max DD, zero if no DD | Separate baseline/time/undefined convention |
| `omega/profit_factor` | Gain/loss account-period returns; zero loss => infinity even all flat | Keep period identity; distinguish all-flat undefined and closed-population PF |
| `avg_win_pct/avg_loss_pct` | Conditional account-period means, empty => zero | Keep period names; add currency closed-population means |
| `long_hitrate_pct/short_hitrate_pct` | Per-symbol side masks on whole-account bar returns, averaged with inactive symbols = 0 | Compatibility side-conditioned account-period statistic, **not** leg/trade/action win rate |
| `expectancy_pct` | Mean of side hit rates weights conditional period win/loss means | Do not label standard closed expectancy; preserve legacy alias for science |
| `num_trades` | Initial row per symbol + each quantity change (even all flat) | Preserve scientific alias; separately count fills/transitions/closed trades/actions |
| `max_drawdown_pct` | DD HWM starts at first mark (can miss initial fee) | Separate baseline-inclusive DD, do not change financial raw |
| `avg_drawdown_pct` | Mean positive DD observations, not episode troughs | Correct new label; separately mean episode trough depth |
| `max_dd_duration_days/avg_dd_duration_days` | Consecutive observed UTC day-end underwater counts, integer average | Separate counts from elapsed peak-to-recovery/censored/calendar/session time |

Native V2 metrics remain under their own metadata/contract. Shared equity
alone does not prove legacy/native numerical equality: denominator, baseline,
sampling and counter populations differ. Valid period metrics stay available.

## Route / Raw Capability Table

Availability is **per actual artifact**, not only endpoint name. Do not assume
every native backend implements every row/profile. Account paths support only
their recorded mark clock; action metrics require complete identity/net costs.

| Route | Existing usable raw | Closed-population disposition |
|---|---|---|
| Scalar/vectorized `% equity`, notional, units, leverage | Equity/returns/accepted positions; cost paths/diagnostics per backend | No universally complete closed trade/action ledger; snapshots are insufficient |
| Structural ladder/DCA/vectorized | Account paths, accepted quantity changes, specialized diagnostics | No inferred DCA campaign from transitions; recorded matching/IDs required |
| Portfolio/shared account | Equity, positions, per-symbol PnL/fees/slippage/funding, rebalance and reconciliation when retained | Per-symbol timestamp attribution != closed legs/actions; no action ID inference |
| Bounded basket/stat-arb/basis/index package | Equity, leg/package timestamp PnL, targets, hedge/residual and native package IDs/admission where retained | IDs alone insufficient for complete lifecycle/net attribution; profile-specific qualification needed |
| Intrabar intent/session | Account buffers, fills/audit/replay outputs when requested, reasons/costs | Audit available, but cannot infer universal matching/campaign closure; minimal omissions are unavailable |
| Generic event callback | Accepted fill/order/event data and continuous account; clock v2/v3 explicit | Trade/action coverage only if retained and net/identity/closure verified; no implicit replay |
| Command tape/orders | Committed fills/order/package metadata when retained | A fill is not a closed trade; Trade defaults alone are not proof |
| Numeric reactive/W3 | Score scalars or retained account/fill buffers, segment contract metadata | Reset-flat segment != continuous campaign; score has no full ledger |
| Native V2 score | Scalars, event/fill counts and terminal account fingerprint | Paths/ledger omitted; counts may be valid, closed-population statistics unavailable |
| Native V2 compact | Score plus dense account paths | Audit ledger omitted; DD at retained clock only |
| Native V2 audit | Account paths, bounded fill/event/admission SoA with retained/dropped counts | Truncation blocks complete population claims; complete audit still needs matching/cost/IDs |
| Options | Option cash/mark/position/fill/package/settlement reports, hedge reports, currency dictionaries | Must verify FX and fee/PnL currency plus package closure; no cross-currency sum/expiry expansion |
| Nautilus | Optional normalized fills/orders/account reports/certification bundles | Adapter/version-specific coverage; external tool agreement is not generic closed-action certification |
| Walk-forward scoped results | Stitched account paths and fold table, legacy retained unsliced ledger | Scope entry/carry/row filtering must be supplied; cannot treat unsliced ledger as OOS-only |

MFE/MAE, risk multiples, trading-session duration and missing net action cost
allocation are explicit raw-input dependencies, not metrics computed as zero.
Future MET-02 can certify a read-only adapter only from sufficient recorded
data; adding execution bookkeeping/matching requires separate financial scope.

## Independent Comparisons

Pinned [QuantStats statistics](https://github.com/ranaroussi/quantstats/blob/v0.0.81/quantstats/stats.py),
[reports](https://github.com/ranaroussi/quantstats/blob/v0.0.81/quantstats/reports.py),
[preparation](https://github.com/ranaroussi/quantstats/blob/v0.0.81/quantstats/utils.py)
are source-hashed in the baseline. Match prepared returns, ddof, RF/MAR,
annualization and sample population, not tool branding. Tests register
period-PF/conditional means/Sharpe/full-N Sortino/period-count CAGR matches,
and observed expected duration/baseline/first-loss/zero-population differences.

TradingView's [closed total trades](https://www.tradingview.com/support/solutions/43000681704-total-trades/),
[realized profit factor](https://www.tradingview.com/support/solutions/43000681698-profit-factor/)
and [expected payoff](https://www.tradingview.com/support/solutions/43000772770-expected-payoff/)
support closed-population interpretation. They do not certify QuantBT ledger
completeness, net-fee convention or multi-leg matching.
