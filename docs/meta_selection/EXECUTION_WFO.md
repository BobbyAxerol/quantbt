# Execution WFO And Optional Meta

## Availability

Local feature-branch implementation for the prepared `1.1.2 / 0.4.3` pair.
Not published and not an economic/default promotion. The owner's
[execution-route amendment](../../upgrade/implement.md#qms-required-execution-routes)
extends the original QMS guide; its Ridge, maturity, labels, metrics and search
rules remain unchanged.

| `target_mode` | Financial endpoint | Strategy output |
|---|---|---|
| `intrabar` | Existing `intrabar_bracket`, reference or Rust endpoint | Exact intent frame and optional `IntrabarSessionTape` |
| `event_driven` | Existing `event_driven(input_mode="strategy")` | Fresh no-argument callback factory |
| `order_commands` | Existing `event_driven(input_mode="orders")` | Actual `OrderCommand` tuple |
| `delivery_arbitrage` | Existing orders endpoint plus explicit `DeliveryLifecycle` | Explicit leg/roll commands |

All four use the same `QuantBTEndpoint.walk_forward`, with an additive
`execution_endpoint` argument. Standalone backtest endpoints do not change.
There is no signal/position proxy, new learner or second financial account.

## Stable Call Pattern

Declare financial settings once on the original endpoint. The WFO wrapper owns
dates, study schedule and selection, not execution settings.

```python
from quantbt import QuantBTEndpoint
from quantbt.wfo_execution import WfoExecutionWindow

financial = QuantBTEndpoint.intrabar_bracket(
    symbols=["ETHUSDT"], initial_capital=20_000, leverage=3,
    fee_rate=0.0005, use_funding=False, close_on_last_bar=False,
    report_level="audit",
)

def strategy(data, params, train_index, test_index, fold):
    # Caller-owned causal indicators can use the supplied historical prefix.
    intent = build_intent(data, params).loc[test_index]
    return WfoExecutionWindow("intrabar", test_index, intent=intent)

bt = QuantBTEndpoint.walk_forward(
    strategy_class=strategy,
    execution_endpoint=financial,
    target_mode="intrabar",
    split_mode="2022-01-01", split_frequency="quarterly",
    window_mode="expanding",
    optimization_mode="mode_4_is_only_robust",
    optimization_schedule="per_fold_causal",
    optimization_config={
        "candidate_selection_metric": "is_only_robust",
        "scoring_backend": "endpoint",
        "use_scalar_trial_scoring": False,
        "native_prepared_wfo": "off",
        "meta_selection": {
            "mode": "shadow", "label_observer": True,
            "min_matured_origins": 12, "native_batch_policy": "auto",
        },
    },
    optuna_trials=128, random_seed=731,
)
# context is the caller's ordinary, explicitly bound MetaHistoryContext.
result = bt.backtest(data=data, param_ranges=param_ranges, meta_history=context)
bt.show_metrics(trading_days=365)
bt.quick_plot()
```

`build_intent` is the user's alpha, not a library helper. Intent columns follow
the [intrabar contract](../fast_intrabar.md); `entry_signal` is required.
Supply `session=` for session rules and declare the policy on `financial`.
Do not place duplicate account/fee/backend settings on the WFO wrapper.

For callbacks, return
`WfoExecutionWindow("event_driven", test_index, strategy_factory=factory)`.
Each factory must return a new alpha instance implementing the existing
`on_bar_close(context)` protocol; never return a shared mutable strategy.
For commands, return
`WfoExecutionWindow("order_commands", test_index, commands=tuple(commands))`.
Use unique order IDs across the final tape and the original command clock.

Runnable self-contained examples, no private alpha or downloader:

```bash
python -m examples.wfo_meta_execution --route intrabar --mode shadow
python -m examples.wfo_meta_execution --route event_driven --mode active
python -m examples.wfo_meta_execution --route order_commands --mode off
python -m examples.wfo_meta_execution --route delivery_arbitrage --mode shadow
```

## Account And Causality

IS and counterfactual forward diagnostics start fresh, flat accounts. They
produce original endpoint metrics, fees, funding, margin and witnesses. Meta
selection runs once at the existing fold boundary, not inside financial bars.
Only compatible past matured outcomes may enter the fit; current outer OOS is
not used for selection. Arbitrary user feature causality remains caller-owned.

Final output stitches **intents/commands/factories**, then executes them once
in one original continuous account. It does not concatenate fold equities.
Existing fills, pending orders, fees, funding, margin and liquidation remain
owned by the original engine. A held intrabar position retains its original
protection when the next fold chooses different parameters.

Callback alpha instances switch at the first close of each new fold; new commands
use original next-open behavior. The account and pending orders do not reset.
`initialize` runs for each new child; `finalize` runs only for the final child.
The final result's positions/fills are the authority. Boundary-table target
snapshots/counts are null because order intents are not held position targets.

Exact aware, unique calendars are required. The current bounded mapping route
requires one common calendar and fixed instrument universe; it does not invent
quotes for asynchronous markets. Session IDs must be stable absolute identities,
not reset-local counters at every fold. Warm-up supplies past feature history;
diagnostic accounts do not inherit warm-up positions.

## Quarterly Expiry And Roll

`DeliveryContract(symbol, expires_at, flatten_at, source_id)` explicitly supplies
aware authoritative events. `flatten_at` must precede expiry and be present on
the execution calendar. `DeliveryLifecycle` cancels the old leg's orders and
submits clamped reduce-only closes at that executable timestamp. Reconciliation
requires the old contract to be flat; an insufficient close cap fails.

Roll openings/hedges are explicit strategy commands against the new instrument's
own OHLC tape. They pay original one-way fees/slippage; delivery legs cannot
accrue perpetual funding. Funding on the paired perpetual must be supplied
separately. No expiry is inferred from names. Flatten timestamps mean **effective
order timestamps under the declared original execution contract**, not an
arbitrary exchange cash-settlement clock.

This is `pre_expiry_flatten_v1`, not hold-through-expiry cash settlement, automatic
venue delivery, an atomic all-or-none roll or a quarterly instrument provider.
Cash-settlement requests explicitly raise. Real quarterly-data/venue qualification
remains separate; synthetic calendars/prices do not certify production data.

## Method And Cost Limits

Meta admission is currently Mode 4 / `per_fold_causal`, opt-in off/shadow/active.
Insufficient compatible matured history falls back to the native selection;
active does not imply a fitted learner or changed params on every fold.
Mode 2 execution bootstrap and scalar prepared-target `require` are rejected.
Generic Python callbacks remain Python; Rust may own their financial runner,
not their indicator/decision code. Numeric meta backend is recorded separately.

No default is promoted and no gain is guaranteed. Signed point decay and forward
contribution are reported separately:

$$
R=(S_{IS,a}-S_{OOS,a})-(S_{IS,m}-S_{OOS,m}),
\qquad Q=S_{OOS,m}-S_{OOS,a}.
$$

Synthetic on/off receipts test software and expose actual costs; they are not
registered real-market R/Q confidence or deployment evidence. Read the
[current coverage](CURRENT_ROUTE_REVIEW.md) before choosing release scope.
