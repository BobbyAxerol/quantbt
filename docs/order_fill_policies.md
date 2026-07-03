# Order Fill Policies

QuantBT separates signal sizing from order execution.

## Legacy Single-Symbol Engine

`BacktestEngine` converts `Position` into target units according to
`hedge_type`, then executes target-unit changes at close.

Sizing modes:

- `signal_notional`: freeze units on signal transitions;
- `%_equity`: dynamic target from live equity, allocation percentage, and signal;
- `notional`: rebalance to the same notional each bar;
- `unit`: fixed unit count from the first bar;
- `dca_ladder`: structural grid levels with High/Low limit simulation.

## Native Event Backend

`NativeEventBackend` and `BacktestEngineV2(backend="native_event")` consume
explicit `OrderIntent` records.

Rules:

- market orders fill at current close;
- buy market price includes positive slippage, sell market price includes
  negative slippage;
- buy limits fill when `Low <= limit_price`;
- sell limits fill when `High >= limit_price`;
- fill price is the limit price, not close;
- IOC orders cancel if not filled on the order bar;
- GTC orders stay active until touched;
- orders above buying power are rejected.

Current limitation:

- partial fills are not yet modeled; fills are full-size or rejected/canceled.

## DCA Ladder

Use `hedge_type="dca_ladder"` when `Position` is a structural level, not a
target weight.

Example level semantics:

- `0`: flat;
- `1`: base order active;
- `2`: base + first safety order allowed;
- `6`: base + five safety orders allowed;
- negative values represent short ladders.

Safety orders are detected from `High`/`Low` and filled at their grid trigger
price. Multiple levels can fill in the same bar.
