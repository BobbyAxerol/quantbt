# Backend Selection

Choose a QuantBT backend from the execution behavior the strategy requires.
The public endpoint is stable; implementation language is a governed runtime
decision beneath it.

## Decision Table

| Requirement | Preferred endpoint | Engine | Why |
|---|---|---|---|
| Fast target-signal research | `signal_notional()` | native vectorized / Numba | fixed units between target transitions, low orchestration cost |
| Live-equity signal sizing | `pct_equity()` | compatibility engine | preserves established `%_equity` behavior |
| Causal next-open entry plus SL/TP/trailing | `intrabar_bracket()` | native intrabar / Numba | explicit OHLC path policy and Python oracle parity |
| Explicit typed Rust intrabar run | `intrabar_bracket_rust()` | Rust intrabar | bounded one-symbol OHLC contract; explicit-only, no auto promotion |
| Stateful strategy callback | `event_driven(input_mode="strategy")` | Python native event | callback can react to account and lifecycle state |
| Pre-built canonical command tape | `event_driven(input_mode="orders")` | Python auto / explicit Rust | typed lifecycle execution with capability-gated Rust request |
| Existing `OrderIntent` replay | `orders()` | native event | compatibility route for explicit orders |
| Multi-symbol target matrix | `portfolio()` | native portfolio / Numba | portfolio sizing, margin, exposure, attribution |
| Pair, basket, or arbitrage package | `basket()` / `arbitrage()` | Python package planner/executor | coordinated legs and package diagnostics |
| Option contract or strategy package | `options()` | native options | option marks, Greeks, legs, and hedge workflow |
| Parameter stability over time | `walk_forward()` | WFO orchestration; optional prepared Rust scorer for certified scalar targets | fold-local selection, OOS stitching, audit metadata |
| Independent execution validation | `nautilus_validation()` | NautilusTrader | third-party event/accounting evidence |

## Vectorized Research

Use `signal_notional()` when a strategy has already produced a target signal
and order lifecycle is not part of the alpha.

Best fit:

- many bars, symbols, or parameter combinations;
- target exposure changes are sufficient to describe execution;
- close-target or documented OHLC rules are acceptable;
- optimizer throughput matters.

Do not use it to claim limit-order waiting, TIF, OCO, stop-gap, or queue
semantics. Use an event or intrabar contract instead.

## Fast Intrabar

Use `intrabar_bracket()` for single-symbol strategies where entry timing,
stop-loss, take-profit, trailing updates, gap handling, reversal costs, and
same-bar ambiguity matter, but a general order book is unnecessary.

The fast Numba kernel and readable Python reference share one execution
contract. This route is not a generic portfolio, grid, DCA, or L2 simulator.

`intrabar_bracket_rust()` is the matching explicit Rust authority for the
frozen bounded contract. It is appropriate when a matching native extension is
installed and the run is exactly one strict OHLC symbol with an
`IntrabarIntentTape`; Rust then owns the full tape, bracket/account/funding/
liquidation loop, and bounded audit buffers. It does not alter
`intrabar_bracket()` or `backend="auto"`. Unsupported ambiguity policies
(`reject_ambiguous`, `lower_timeframe_required`) fail closed; use the Python
reference route to inspect the rejection or provide a lower-timeframe tape.

## Native Event

Use `event_driven()` when orders and lifecycle transitions are part of the
strategy definition.

```python
bt = QuantBTEndpoint.event_driven(
    input_mode="orders",
    profile="audit",
    backend="auto",
    execution_contract="event_lifecycle_v3_next_open",
)
result = bt.simulate(data=df, order_commands=commands, symbols=["BTCUSDT"])
```

`profile` controls retention:

- `optimize`: scalar/compact output;
- `research`: ordinary result and metrics;
- `audit`: full lifecycle and accounting evidence.

`backend` controls implementation:

- `auto`: Python until fresh exact route evidence enables a generated Rust rule;
- `python`: portable canonical implementation;
- `rust`: explicit capability-gated request; incompatible requests fail fast.

An arbitrary callback is always Python-authoritative. Static command tapes and
bounded Native Strategy IR can be Rust-authoritative because they cross the
Python/Rust boundary once and carry a complete typed execution request.

## Native Portfolio

Use `portfolio()` for target matrices and portfolio-level accounting. The
generic route supports long/short, market-neutral, directional, equal-weight,
risk-parity, beta-neutral, target-weight, target-notional, target-units, and
gross/net exposure contracts.

The generic portfolio endpoint is Python/Numba. The Rust companion currently
has a separate explicit bounded helper for linear quote-settled `target_units`
market execution; installing it does not silently replace the generic route.

## Bounded Rust Packages

`run_bounded_package_market(...)` is an explicit companion for a fully typed
same-account linear package, not another spelling of `arbitrage()`. It supports
`atomic_bar_simulation`, `sequential`, `best_effort`, and
`hedge_after_primary` under `event_lifecycle_v2_next_bar_close`. In the latter
policy, dependent hedge quantity is computed from the actual simulated primary
fill and then quantized by the hedge instrument. Residual exposure,
reservation movement, fee, and terminal state are emitted instead of being
silently netted away.

`run_bounded_package_market_scenarios(...)` is score-only for many pre-built,
independent package scenarios over one prepared tape. It makes one native
boundary call and reset-flats the account per scenario; rerun a selected row
through `run_bounded_package_market(..., report_level="audit")` for leg-level
audit data. Basis, stat-pair, calendar, and index-basket plans can be lowered
explicitly when their contract is same-account and linear. Triangular and
cross-exchange plans fail closed. Generic `basket()` and `arbitrage()` retain
their Python authority and are never silently promoted.

## Nautilus Validation

Use Nautilus for representative execution validation, not broad optimizer
sweeps. It is most useful when instrument precision, venue-style order/fill
reports, and an independent event/accounting implementation are needed.

The adapter remains bar-data dependent. Market orders on hourly OHLC cannot
recover one-minute or L2 microstructure that was not supplied.

## Rust Promotion Is Workload-Scoped

For `quantbt-engine==1.1.0` and `quantbt-native==0.4.1`, the static V2/V3 and
bounded Native Strategy IR routes remain explicit certified Rust workloads.
Their former auto-promotion evidence is historical scope-only, so `auto` stays
Python until a fresh route/profile/data/intent matched measurement passes.

Explicit bounded portfolio-target and Package V2 helpers are certified but not
auto-promoted through generic endpoints. Callback, reactive, generic
portfolio, basket, arbitrage, options, vectorized, and intrabar routes retain
their existing Python/Numba authority.

Always inspect:

```python
result.metadata.get("native_event_promotion_v1")
```

The generated [native compatibility matrix](contracts/generated_product_compatibility.md)
and [measurement contract](performance/measurement_contract_v1.md) are the
release-facing source of truth.
