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
| Stateful strategy callback | `event_driven(input_mode="strategy")` | Python native event | callback can react to account and lifecycle state |
| Pre-built canonical command tape | `event_driven(input_mode="orders")` | auto Rust/Python | typed lifecycle execution with capability-gated promotion |
| Existing `OrderIntent` replay | `orders()` | native event | compatibility route for explicit orders |
| Multi-symbol target matrix | `portfolio()` | native portfolio / Numba | portfolio sizing, margin, exposure, attribution |
| Pair, basket, or arbitrage package | `basket()` / `arbitrage()` | native event package | coordinated legs and package diagnostics |
| Option contract or strategy package | `options()` | native options | option marks, Greeks, legs, and hedge workflow |
| Parameter stability over time | `walk_forward()` | WFO orchestration | fold-local selection, OOS stitching, audit metadata |
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

- `auto`: Rust only for a certified workload at its release threshold;
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

## Nautilus Validation

Use Nautilus for representative execution validation, not broad optimizer
sweeps. It is most useful when instrument precision, venue-style order/fill
reports, and an independent event/accounting implementation are needed.

The adapter remains bar-data dependent. Market orders on hourly OHLC cannot
recover one-minute or L2 microstructure that was not supplied.

## Rust Promotion Is Workload-Scoped

For `quantbt-engine==1.1.0` and `quantbt-native==0.4.1`, `auto` can promote:

- static V2/V3 command tapes at 10,000+ bars;
- bounded Native Strategy IR and batch/fold workloads at 2,000+ bars.

Explicit bounded portfolio-target and atomic-package helpers are certified but
not auto-promoted through generic endpoints. Callback, reactive, generic
portfolio, basket, arbitrage, options, vectorized, and intrabar routes retain
their existing Python/Numba authority.

Always inspect:

```python
result.metadata.get("native_event_promotion_v1")
```

The generated [native compatibility matrix](contracts/generated_product_compatibility.md)
is the release-facing source of truth.
