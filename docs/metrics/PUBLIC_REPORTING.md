# Reporting V1

Reporting observes a **completed result**. It does not rerun execution, change
account state, allocate guessed trades or alter WFO/meta scoring. The optional
`reporting=` keyword is available on endpoint/result `full_report()`,
`show_metrics()` and `quick_plot()`. Existing calls and dictionaries are unchanged.
`tearsheet()` and `quantbt.metrics.full_report()` retain their legacy contract.

## Account Report

```python
from quantbt import ReportingContractV1, ReportingRequest, ReportingCache

# Use the recorded execution clock, not an inferred prior candle.
index = result.equity.index
contract = ReportingContractV1(
    scope="full", unit="account_period", currency="USDT",
    baseline_equity=result.initial_capital,
    baseline_time_ns=int(index[0].value), scope_end_ns=int(index[-1].value),
    sampling="observed_bar", annual_periods=365 * 24, equity_clock="bar_close",
)
request = ReportingRequest(
    account=contract, result_identity="my-completed-run",
    partial_mask=(False,) * len(index),
    return_witness="complete recorded hourly bars in this run",
    retain_episodes=True,
)
report = bt.full_report(reporting=request)   # or result.full_report(...)
bt.show_metrics(reporting=request)
fig = bt.quick_plot(reporting=request, theme="light")
episodes = report["groups"]["account_period"]["drawdown_episodes"]
```

Declare the true frequency: hourly uses `365 * 24`, daily uses `365`, not an
automatic assumption from `trading_days`. `observed_daily_utc` selects the last
recorded mark per UTC day without filling missing days. Its partial mask has
one flag per selected daily observation, not one per original bar. Without a
return/partial-period witness, equity metrics remain available but period metrics
are N/A. Producer-supplied explicit returns can be reduced through the typed
`AccountObservations` API; the convenience equity adapter cannot invent that
witness. Naive DatetimeIndex requires `naive_timezone="UTC"` explicitly.
Second/millisecond/microsecond indices normalize to UTC nanoseconds without
changing the completed result. Missing `NaT` clocks fail closed.

The full baseline is the starting equity at the declared instant, before initial
costs. For a middle/OOS slice, declare `scope="scoped"`, **scope-entry equity**
and the exact start/end timestamps. Do not reuse original capital or manufacture
a prior candle. `scope="auto"` in an opt-in call defers to the explicit contract,
not the legacy automatic OOS mask. `scope="oos"` alongside `reporting=` is
rejected. Disjoint reset accounts require separate reports with their own
baselines; use `reduce_independent_segments` for the typed API. Never concatenate
reset-flat W3 equity and advertise continuous CAGR. External-flow adjustments
remain unsupported and fail closed.

## Populations And Coverage

`report["groups"]` separates `account_period`, `execution`, `closed_trade` and
`closed_action`. Each metric has its own namespaced ID, contract identity, unit,
sample count, validity, source/profile/coverage and unavailable reason. JSON has
no Infinity/NaN; no-loss ratios have `status="no_loss"` and a null numeric value.
Formatting does not change numeric values or contract hashes.

Account returns are not closed trades. A fill is not a closed action. An action
can combine simultaneous opposite-side legs; all recorded obligations must close.
No action ID is manufactured from a timestamp or position transition.

Closed populations need immutable `LedgerObservations`, complete recorded
`RecordedOutcome` net/gross cost attribution, matching policy and, for actions,
an `ActionRoster` with shared cost adjustment exactly once. Supply them through
`ReportingRequest(ledger=..., ledger_contracts=(trade_contract, action_contract), ...)`.
Contracts must share the account scope/baseline/currency, and coverage identities
must refer to the same completed result. Use `trades_from_completed()` only when
you can explicitly witness completeness, cost basis and close event sequences.
`result.trades=[]` does not prove a complete empty ledger.

Open-population PnL needs a complete roster valued exactly at the report end,
even if all retained outcomes look closed. Without that witness it is N/A,
not a certified zero. For an unfinished action, `open_realized_net_pnl`
includes the realized PnL of **all its members**, including closed legs, plus
its recorded shared adjustment once. `open_unrealized_pnl` includes only
still-open legs. These controls never change closed-action win/loss counts;
trade-level and action-level PnL must not be summed together. Average holding
bars retain fractional values in formatted reports.

`ExecutionObservations` accepts exact recorded aggregate counters/costs and
retained fee/funding/exposure/margin paths. `execution_from_native()` reads V2
counters without reinterpreting native scientific ratios. Scope mismatches,
truncated ledgers and absent attribution produce metric-specific N/A. Do not
convert audit row counts into full counters or charge embedded slippage twice.

| Completed surface | Account coverage | Closed populations |
|---|---|---|
| Legacy vectorized, pct-equity, portfolio, basket/package | Retained equity | Explicit recorded attribution required |
| Intrabar, command/event, numeric W3 segment | Retained recorded equity | Explicit recorded attribution required |
| Options/Nautilus-compatible result with equity | Recorded equity only; no new domain certification | Do not reinterpret package/settlement tables implicitly |
| Native V2 compact/audit | Explicit native index; truncated detail disclosed | Never infer completeness from profile name |
| Scalar/native V2 score | N/A if paths omitted; no rerun | N/A unless separate authoritative ledger supplied |

Software reporting coverage is not new exchange/expiry/accounting certification.
Cash settlement, risk/MFE/MAE/percentage denominators are not guessed.

## Drawdown And Methodology

Drawdown uses the declared baseline and observed equity; initial-bar fees are
included. Episode rows distinguish `recovered=True` and open/right-censored.
Open `recovery_time_ns` is null; `end_time_ns` is the observation end. Elapsed
nanoseconds are formatted as hours and fractional days without a one-day floor.
The deepest episode, longest episode, longest recovered and current underwater
are distinct. Plots show observed equity/drawdown only, not unseen intrabar extrema.

The [contract/dictionary](REPORTING_CONTRACT_V1.md) defines variance, MAR,
Sortino, win/loss/breakeven, PF and expectancy denominators. QuantStats 0.0.81
comparisons apply only when conventions match: inclusive daily underwater duration
is not peak-to-recovery elapsed duration; neither should be renamed to match the
other. TradingView-style closed-trade statistics require an executed, matched,
net-PnL population. Legacy `Number of Trades`, PF and period-win aliases remain
unchanged for compatibility, **not** automatically certified closed-action metrics.
See [legacy inventory](INVENTORY.md) for every existing key.

## Retention And Migration

Python is the reporting reducer default. `backend="numba"` is explicit and has
first-call compilation/import RSS costs; it is not automatically faster for small
ledgers. Rust native metric V2 is preserved, not claimed as a Reporting V1 reducer.
No optional matplotlib/QuantStats import is added to ordinary backtest/report calls.

Cache ownership is explicit:

```python
from dataclasses import replace
with ReportingCache(max_entries=4, max_bytes=4 * 1024**2) as cache:
    cached_request = replace(request, cache=cache)
    first = result.full_report(reporting=cached_request)
    second = result.full_report(reporting=cached_request)
```

The cache retains bounded reduction results, not markets/accounts/trials. The
public call still snapshots/hashes mutable completed input and serializes output
on cache hits; direct reducer hits are a different workload. `release(identity)`,
`clear()` and `close()` provide explicit disposal. Requested episode detail can
exceed the byte cap and bypass cache, never silently disappear.

The immutable request prepares its boolean partial mask once (one extra byte
per observed return). Reuse a request for repeated reports rather than rebuild
it each call. Completed mutable equity is still freshly snapshotted and SHA256
hashed on every public call, including cache hits; object identity/length alone
never permits reuse. Only contiguous arrays with an immutable `bytes` owner
can share snapshot storage. Read-only views of writable arrays/memoryviews are
copied, so later source changes cannot corrupt a report or its cached identity.
Reports and plots use the same local snapshot within a plot call; that snapshot
is not retained by the reduction cache. No output detail or validity test is
omitted to obtain the measured gain. Request preparation, reducer, warm full
report and cache-hit costs are measured separately, including request+report.

Migration is opt-in. Keep scientific/WFO calls without `reporting=`. Don't replace
their objective/selection dictionary with the grouped report. Full runnable public
synthetic example: [reporting_metrics_v1.py](../../examples/reporting_metrics_v1.py).
Local certification does not authorize CI, publication or qualify other Python/OS
matrices. See [MET-03 report](MET03_REPORT.md) for source/artifact/cost evidence.
