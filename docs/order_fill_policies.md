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

Phase 30 adds `OrderCommand` as the lifecycle-v2 contract. `OrderIntent`
remains the stable immediate-place shorthand used by existing endpoints.
`OrderCommand` can express place/cancel/replace/amend/cancel-all, parent-child
activation, OCO groups, stop trigger fields, reduce-only flags, and GTD expiry.
Use `NativeEventBackend.run_order_commands(...)` or
`QuantBTEndpoint.native_event_lifecycle(...)` for the opt-in v2 lifecycle route.

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
- the default endpoint route executes v1 market and limit orders;
- stop and linked lifecycle commands require the opt-in v2 lifecycle route.

Lifecycle-v2 rules:

- place activates an order immediately unless a parent activation policy is set;
- cancel cancels a pending active or waiting order by `target_order_id`;
- replace cancels the target slot and creates a new executable slot;
- amend updates working quantity, limit price, or trigger price;
- GTD expiry cancels active orders before the expiry bar is matched;
- reduce-only exits are clipped to the current opposite position and canceled
  as no-op when no opposite position exists;
- OCO siblings sharing `oco_group_id` are canceled after the first sibling fill;
- stop-market orders trigger from high/low and fill at trigger price plus
  slippage;
- stop-limit orders require both trigger touch and limit touch in the bar.

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
