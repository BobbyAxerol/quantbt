# Vectorized Vs Event-Driven

Both upgraded backends return `BacktestResultV2`, but they answer different
questions.

## Vectorized

Question:

What would the account curve look like if these target exposures were applied
deterministically over this market matrix?

Use it for:

- grid search;
- daily/intraday alpha research;
- many symbols and many parameter combinations;
- portfolio-level diagnostics;
- simple target-position strategies.

Primary input:

- raw signals or target units.

Primary output:

- equity, returns, positions, fees, funding, margin diagnostics.

## Event-Driven

Question:

What happens to these specific orders as the bar stream evolves?

Use it for:

- limit orders;
- single-order studies;
- DCA/grid ladders;
- pair/basket entry and exit;
- order status reports.

Primary input:

- explicit `OrderIntent` records or a `BasketSpec` plus signal.

Primary output:

- same `BacktestResultV2` contract, plus fills and order reports.

## Practical Rule

Start with `native_vectorized`. Move to `native_event` only when execution
details can change the alpha result. Use `nautilus` to validate a smaller set of
important cases against a production-grade event engine.
