# QuantBT Endpoint Contract

`QuantBTEndpoint` is the public integration layer for notebooks, alpha services,
and research jobs. Other services should import this class instead of choosing
internal engines directly.

```python
from quantbt import QuantBTEndpoint
```

The endpoint separates two responsibilities:

- factory/constructor: declares account, backend, sizing, execution, and strategy
  mode;
- `backtest()` / `simulate()`: receives market data, signals, positions, orders,
  or basket objects for one concrete run.

This lets QuantBT upgrade the internal engine while service code keeps a stable
call contract.

## Lifecycle

```python
bt = QuantBTEndpoint.signal_notional(
    backend="native_vectorized",
    initial_capital=20_000,
    leverage=5,
    alloc_per_trade=10_000,
    fee_rate=0.0002,
    slippage_bps=1.0,
    use_funding=False,
)

result = bt.backtest(
    data=df,
    signal_col="pos_weight",
    symbols=["ETHUSDT"],
)

report = bt.show_metrics()
```

The latest artifacts are stored on the endpoint:

```python
bt.result       # latest BacktestResult / BacktestResultV2
bt.engine       # latest internal engine instance
bt.metrics      # alias for bt.full_report()
```

## Factories And Routes

| Factory | Mode | Default backend | Main use case |
|---|---|---|---|
| `QuantBTEndpoint.pct_equity()` | `pct_equity` | `legacy` | legacy `%_equity` signal where notional is recomputed from live equity |
| `QuantBTEndpoint.signal_notional()` | `signal_notional` | `native_vectorized` | fast single-symbol signal research with fixed units between signal changes |
| `QuantBTEndpoint.intrabar_bracket()` | `intrabar_bracket` | `native_intrabar` | fast Phase 31C Numba kernel for next-open SL/TP/trailing/reversal semantics |
| `QuantBTEndpoint.intrabar_bracket_reference()` | `intrabar_bracket_reference` | `intrabar_reference` | readable Phase 31B oracle for next-open SL/TP/trailing/reversal semantics |
| `QuantBTEndpoint.fill_replay()` | `fill_replay` | `native_intrabar` | fast accounting replay from explicit fills |
| `QuantBTEndpoint.dca_ladder()` | `dca_ladder` | `legacy` | structural DCA/grid levels with high/low limit-touch simulation |
| `QuantBTEndpoint.orders()` | `orders` | `native_event` | explicit `OrderIntent` market/limit/stop simulation |
| `QuantBTEndpoint.event_driven()` | `native_event_strategy` or `orders` | `auto` | stable facade for reactive strategies or explicit lifecycle commands |
| `QuantBTEndpoint.basket()` | `basket` | `native_event` | pair/basket entry with frozen hedge-ratio units |
| `QuantBTEndpoint.arbitrage()` | `arbitrage` | `native_event` | package-style arbitrage specs and validation |
| `QuantBTEndpoint.walk_forward()` | `walk_forward` | `auto` | split/stitch OOS signals then route into existing endpoints |
| `QuantBTEndpoint.train_test_split()` | `walk_forward` | `auto` | single train/test holdout using the same WFO optimization modes |
| `QuantBTEndpoint.portfolio()` | `portfolio` | `native_portfolio` | multi-symbol position matrix portfolio backtest |
| `QuantBTEndpoint.nautilus_validation()` | `nautilus_validation` | `nautilus` | optional NautilusTrader validation for smaller runs |

Manual construction is also supported:

```python
bt = QuantBTEndpoint(
    mode="single_signal",
    backend="native_event",
    sizing="signal_notional",
    initial_capital=100_000,
    leverage=3,
)
```

Use `backend="auto"` when service code wants QuantBT to choose the safest route:

- `%_equity` and `dca_ladder` route to legacy;
- `orders` and `basket` route to native event;
- `nautilus_validation` routes to Nautilus;
- other signal modes route to native vectorized.

## Stable Event-Driven Facade

`QuantBTEndpoint.event_driven()` is the recommended public entry point for new
event-driven integrations. It keeps the common declaration small while leaving
the existing lifecycle engine, matching rules, accounting, and audit artifacts
unchanged underneath.

```python
from quantbt import QuantBTEndpoint

bt = QuantBTEndpoint.event_driven(
    input_mode="strategy",
    profile="research",
    backend="auto",
    initial_capital=20_000,
    leverage=5,
    fee_rate=0.0005,       # canonical one-way fee
    slippage_bps=2.0,
    use_funding=False,
)

result = bt.simulate(
    data=df,
    strategy=strategy,
    symbols=["BTCUSDT"],
)
bt.show_metrics()
```

### Profiles

The profile is an explicit retention and execution policy. It does not change
fill or accounting semantics:

| Profile | Execution | Kernel | Result/report retention | Audit sink |
|---|---|---|---|---|
| `research` | `fast` | `single_pass` | `minimal` | `none` |
| `optimize` | `fast` | `single_pass` | `score` | `none` |
| `audit` | `audit` | `replay_certified` | `audit` | `memory` |

Use `research` for ordinary notebook/service runs, `optimize` for parameter
search, and `audit` when fills, order events, replay evidence, and detailed
accounting must be retained. `backend="auto"` follows the package release
policy. `backend="python"` selects the canonical portable implementation;
`backend="rust"` is an explicit capability-gated request for the optional
native wheel and never silently changes to Rust.

### Input modes

`input_mode="strategy"` accepts a stateful callback object. The strategy owns
signal generation and look-ahead control; the engine owns market processing,
order lifecycle, fills, fees, slippage, margin, funding, and PnL.

```python
class MyStrategy:
    def initialize(self, context):
        return ()

    def on_bar_close(self, context):
        # Return OrderCommand objects for the next causal bar.
        return ()

    def finalize(self, context):
        return ()

bt = QuantBTEndpoint.event_driven(profile="audit", backend="python")
result = bt.simulate(data=df, strategy=MyStrategy(), symbols=["BTCUSDT"])
```

`initialize` and `finalize` may return an empty tuple. A strategy may subclass
`NativeEventStrategyProtocol`, or simply satisfy the public structural
`NativeEventStrategy` protocol by duck typing. The optional
`native_context_requirements` declaration can reduce context materialization
for specialized optimization runs. Commands emitted at bar close are handled
according to the native-event lifecycle and do not become an implicit
same-bar fill.

`input_mode="orders"` is for an already-created execution tape. Use it when
the alpha or an upstream planner owns order generation but still needs the
native lifecycle to process placement, cancellation, replacement, OCO links,
trigger rules, fees, margin, and fills:

```python
bt = QuantBTEndpoint.event_driven(
    input_mode="orders",
    profile="audit",
    backend="python",
    initial_capital=20_000,
)
result = bt.simulate(data=df, order_commands=commands, symbols=["BTCUSDT"])
fills = result.fills
events = result.metadata.get("order_events")
```

Legacy `OrderIntent` inputs remain supported through the existing
`QuantBTEndpoint.orders(...)` route. The new facade accepts the canonical
`OrderCommand` lifecycle tape and delegates to
`native_event_lifecycle(...)`; it does not introduce a second order engine.

### Advanced controls and compatibility

The facade owns the four low-level values in its selected profile. Passing a
conflicting `reactive_execution_mode`, `reactive_kernel_mode`, `report_level`,
or `audit_sink` raises a clear `ValueError` instead of silently overriding the
user's configuration. Use `native_event_strategy(...)` or
`native_event_lifecycle(...)` directly when an advanced, non-profile
combination is required. Existing endpoint constructors and notebook snippets
remain valid.

For the recommended stable path, users need only choose `input_mode`,
`profile`, and `backend`; account, instrument, quantity, and execution fields
remain available as normal shared endpoint parameters. See
[`execution_contracts.md`](execution_contracts.md) for exact fill policy and
[`release_packaging.md`](release_packaging.md) for backend capability and
wheel-release policy.

`native_vectorized` is explicitly the `close_target_v2` execution contract:
signals are interpreted as target exposure at the same bar close, with no
engine-owned intrabar SL/TP/trailing path. Results include contract metadata
such as `engine_id`, `signal_phase`, `fill_phase`, `intrabar_exit_model`,
`kernel_version`, and `data_signature`. If a close-target run receives columns
that look like intrabar execution artifacts (`exit_price`, `stop_loss`,
`take_profit`, `trailing`, etc.), QuantBT marks the run as uncertified for those
intrabar semantics instead of silently implying correctness.

`intrabar_bracket` is the Phase 31C fast Numba implementation of
`intrabar_bracket_v1`; `intrabar_bracket_reference` is the readable Python
oracle for the same semantics. Both use strict market tape validation. They
model: signal at bar close, entry at next bar open, gap-aware stop-loss,
limit-style take-profit, same-bar SL/TP ambiguity, trailing-stop updates that
only become effective on the next bar, technical exits, reversals as two
fee/slippage legs, initial-margin rejection, simple single-symbol liquidation,
and optional final close.

Session-aware intrabar execution is opt-in on the reference route:
`QuantBTEndpoint.intrabar_bracket_reference(session_policy=...)` plus
`backtest(..., session_tape=...)`. It supports entry windows, per-session entry
quota, flat-only/no-reversal, force-flat at open, stale-signal cancellation, and
protective-exit re-entry suppression. Phase 31I adds the matching fast Numba
route on `QuantBTEndpoint.intrabar_bracket(session_policy=...)`; the non-session
kernel remains a separate path and is selected when no session policy is
supplied.

For the full contract taxonomy and certification workflow, read
[`execution_contracts.md`](execution_contracts.md),
[`fast_intrabar.md`](fast_intrabar.md), and
[`alpha_certification.md`](alpha_certification.md).

## Nautilus Support Matrix

Services can inspect current Nautilus adapter coverage before constructing a
run:

```python
matrix = QuantBTEndpoint.nautilus_support_matrix()
```

Current executable routes:

| Route | Status | Endpoint | Scope |
|---|---|---|---|
| Signal series | supported | `QuantBTEndpoint.nautilus_validation(...)` | single-symbol target signal replay |
| Explicit orders | supported | `QuantBTEndpoint.orders(backend="nautilus", ...)` | single-symbol `OrderIntent` replay |
| Parity audit | supported | `build_native_nautilus_parity_report(...)` | native-vs-Nautilus order/fill/equity comparison |
| DCA/grid validation | experimental | `QuantBTEndpoint.nautilus_dca_grid(...)` | base order, safety limits, TP/SL package compiled to explicit orders |
| Bracket/OCO | experimental | `QuantBTEndpoint.nautilus_bracket_orders(...)` | entry plus linked stop-loss/take-profit exits |
| Arbitrage packages | experimental | `QuantBTEndpoint.arbitrage(..., backend="nautilus")` | selected basis/stat-arb package validation |
| Basket/pair packages | experimental | `QuantBTEndpoint.basket(backend="nautilus", ...)` | frozen hedge-ratio multi-leg packages |
| Multi-symbol portfolio packages | experimental | `QuantBTEndpoint.portfolio(backend="nautilus", ...)` | position matrix transitions in one Nautilus venue/account |

Experimental Nautilus routes are intended for controlled validation and audit,
not broad optimizer sweeps.

## Shared Configuration

All factories accept the common account and execution fields below.

```python
bt = QuantBTEndpoint.signal_notional(
    initial_capital=100_000,       # equity / initial margin
    leverage=5,                    # buying power = equity * leverage
    maintenance_ratio=0.005,
    alloc_per_trade=10_000,        # notional for notional modes
    fee_rate=0.0002,               # V2 one-way fee
    fee=0.0004,                    # legacy round-trip fee
    slippage_bps=1.0,              # V2 bps
    slippage=0.0001,               # legacy fraction
    use_funding=False,
    funding_rate=0.0001,
    contract_size=1.0,             # PnL/notional multiplier, not lot size
    qty_step=0.001,                # exchange quantity increment
    min_qty=0.001,
    min_notional=10.0,
    use_pyramiding=True,
)
```

Important conventions:

- `initial_capital` is account equity / initial margin;
- buying power is `initial_capital * leverage`;
- `alloc_per_trade` is not multiplied by leverage by the endpoint;
- legacy `fee` is round-trip and is converted to canonical one-way fee at the
  compatibility boundary;
- `fee_rate` is canonical one-way everywhere. If both are present,
  explicit `fee_rate` is the source of truth for native endpoints;
- legacy `slippage` is a decimal fraction, e.g. `0.0001` for 1 bp;
- V2 `slippage_bps` is basis points, e.g. `1.0` for 1 bp.
- exchange quantity constraints are shared across native legacy, native
  vectorized, native event/order, native portfolio, and Nautilus validation
  routes. Use `qty_step` or `lot_size` for the venue step, `slot_size` as a
  compatibility alias, and `min_qty`/`min_notional` for exchange minima.
  QuantBT rounds target/order quantity down conservatively. `contract_size`
  remains the contract multiplier.

## Data Contract

Single-symbol endpoints accept one pandas DataFrame:

```python
df.index                 # DatetimeIndex preferred
df["open"]               # optional, falls back to close
df["high"]               # recommended, required for intrabar logic quality
df["low"]                # recommended, required for intrabar logic quality
df["close"]              # required
df["volume"]             # optional, defaults to 0
df["pos_weight"]         # optional signal column
```

The endpoint normalizes common title-case columns:

```text
Open -> open
High -> high
Low -> low
Close -> close
Volume -> volume
Date/Datetime/Timestamp -> timestamp
```

Signal can be supplied as a series:

```python
bt.backtest(data=df, signal=df["pos_weight"])
```

Or by column name:

```python
bt.backtest(data=df, signal_col="pos_weight")
```

Multi-symbol endpoints accept either:

```python
data = {
    "BTCUSDT": btc_df,
    "ETHUSDT": eth_df,
}
```

Or explicit maps:

```python
closes = {"BTCUSDT": btc_close, "ETHUSDT": eth_close}
highs = {"BTCUSDT": btc_high, "ETHUSDT": eth_high}
lows = {"BTCUSDT": btc_low, "ETHUSDT": eth_low}
```

All time indexes are normalized to UTC and aligned to the run index.

## Helper Methods

```python
result = bt.backtest(...)
result = bt.simulate(...)

rpt = bt.full_report(trading_days=365, scope="auto")
rpt = bt.show_metrics(trading_days=365, scope="auto")

bt.quick_plot(theme="dark", figsize=(14, 6), scope="auto")
bt.tearsheet(theme="dark", scope="auto")

bt.latest_orders
bt.fills
bt.order_report
bt.fills_report

bt.export_orders("orders.csv")
bt.export_fills("fills.csv")
```

`show_metrics()` prints a stable legacy-style text report and returns the same
dictionary as `full_report()`:

`scope="auto"` reports the natural tested window for endpoint and result helper
methods. Normal endpoints use the full result; `walk_forward()` and
`train_test_split()` report/plot OOS-test bars only so CAGR, Sharpe, Sortino,
and Calmar are annualized on the period actually traded. Pass `scope="full"` to
audit the complete stitched timeline with flat train bars included.

```text
  Initial Capital   $        20,000
  Final Equity      $    106,884.96
  Total Return            +434.42%
  CAGR                     +33.54%
  Sharpe Ratio               1.981
  Sortino Ratio              0.875
  Calmar Ratio               2.885
  Omega Ratio                2.190
  Max Drawdown              11.63%
  Avg Drawdown               2.91%
  Max DD Duration           308 days
  Profit Factor              2.190
  Long Hit Rate             48.71%
  Short Hit Rate            49.75%
  Avg Win                  +1.444%
  Avg Loss                 -1.273%
```

The latest result object also exposes the same convenience methods:

```python
result.full_report(scope="auto")
result.show_metrics(scope="auto")
result.quick_plot(scope="auto")
result.tearsheet()
```

Use `backtest()` for signal/portfolio research. Use `simulate()` when the input
is closer to an execution simulation, such as orders, baskets, or Nautilus
validation. Internally both methods use the same router.

## `%_equity` Single Signal

Use this for legacy strategies where the signal is a direction/weight and the
entry notional should be recomputed from live equity when the signal changes.

```python
bt = QuantBTEndpoint.pct_equity(
    initial_capital=20_000,
    leverage=5,
    maintenance_ratio=0.005,
    contract_size=1.0,
    use_funding=True,
    funding_rate=0.0001,
    alloc_per_trade=0.5,       # 50% of current equity in legacy %_equity
    fee=0.0004,                # round-trip, legacy convention
    slippage=0.0001,
    use_pyramiding=False,
)

result = bt.backtest(
    data=df_result,
    signal_col="pos_weight",
)

bt.show_metrics()
```

Input requirement:

- `data`: one OHLCV DataFrame;
- `signal` or `signal_col`: numeric series such as `1.0`, `-0.5`, `0.0`;
- `high` and `low`: strongly recommended for liquidation checks.

Routing:

- backend: `legacy`;
- engine: `BacktestEngine`;
- sizing: `%_equity`.

## Signal Notional, Vectorized

Use this for fast research when each signal value maps to structural notional
exposure and units should stay fixed until the next signal transition.

```python
bt = QuantBTEndpoint.signal_notional(
    backend="native_vectorized",
    initial_capital=20_000,
    leverage=5,
    alloc_per_trade=10_000,
    fee_rate=0.0002,
    slippage_bps=1.0,
    use_funding=False,
)

result = bt.backtest(
    data=df,
    signal_col="pos_weight",
    symbols=["ETHUSDT"],
)
```

Input requirement:

- `data`: one OHLCV DataFrame;
- `signal` or `signal_col`: target signal series;
- `symbols`: optional single-symbol list, defaults to `["DEFAULT"]`.

Routing:

- backend: `native_vectorized`;
- engine: `BacktestEngineV2`;
- fastest path for large alpha sweeps.

## Signal Notional, Native Event

Use this when you want the same signal contract as vectorized mode, but also
want generated market rebalance orders and fill records.

```python
bt = QuantBTEndpoint.signal_notional(
    backend="native_event",
    initial_capital=20_000,
    leverage=5,
    alloc_per_trade=10_000,
    fee_rate=0.0002,
    slippage_bps=1.0,
    use_funding=False,
)

result = bt.simulate(
    data=df,
    signal=df["pos_weight"],
    symbols=["ETHUSDT"],
)

fills = bt.fills
orders = bt.order_report
```

Input requirement is the same as vectorized signal-notional.

Routing:

- backend: `native_event`;
- generated market orders are emitted on signal transitions;
- `bt.fills` and `bt.order_report` are available.
- `result.fills` and `result.metadata["order_report"]` are also normalized by
  the endpoint for notebook compatibility.

For plain market rebalance signals, native vectorized and native event should
match equity closely. Use event mode when fill-level diagnostics matter.

## Intrabar Bracket, Fast And Reference

Use this for execution-certified alpha logic that depends on SL/TP/trailing
behavior inside the bar. `intrabar_bracket(...)` is the Phase 31C fast Numba
kernel. `intrabar_bracket_reference(...)` keeps the readable Phase 31B Python
oracle for debugging and parity checks.

```python
bt = QuantBTEndpoint.intrabar_bracket(
    initial_capital=20_000,
    leverage=5,
    fee_rate=0.0002,     # one-way fee
    slippage_bps=1.0,    # source of truth for intrabar slippage
    tick_size=0.01,      # optional conservative price quantization
    use_funding=False,
    close_on_last_bar=True,
    report_level="standard",
)

result = bt.backtest(
    data=df,
    signal_col="entry_signal",       # signed qty: +1.0 long, -1.0 short, 0 no new entry
    symbols=["ETHUSDT"],
    intent_cols={
        "stop_value": "sl_pct",
        "take_profit_value": "tp_pct",
        "trailing_value": "trail_pct",
        "exit_long": "exit_long",
        "exit_short": "exit_short",
    },
)

bt.show_metrics()
fills = bt.fills_report
```

Input contract:

- `data`: strict single-symbol OHLCV DataFrame with timezone-aware
  `DatetimeIndex` or timestamp column;
- required market columns: `open`, `high`, `low`, `close`;
- no sorting, deduplication, forward-fill, or high/low fallback is performed;
- `signal` or `signal_col`: compact signed entry size, where the sign is side
  and absolute value is quantity;
- optional `intent_cols`: map strategy column names into `stop_value`,
  `take_profit_value`, `trailing_value`, `exit_long`, and `exit_short`;
- legacy `technical_exit` is still accepted and maps to both long/short exits,
  but new alphas should use side-specific exits;
- intrabar slippage uses `slippage_bps`; legacy `slippage` is converted with a
  deprecation warning, and passing both raises;
- `tick_size` is optional and quantizes entry, stop, take-profit, and trailing
  prices conservatively;
- default `level_mode="percent_distance"` interprets `0.05` as 5 percent from
  fill price. Use `level_mode="price_distance"` or `"absolute_price"` when
  supplying distance/level values in price units.

Execution contract:

- signal at close of bar `t`;
- entry/technical exit/reversal at open of bar `t + 1`;
- stop gaps fill at the open when the open is worse than trigger;
- take-profit is limit-conservative by default;
- same-bar SL/TP conflict is flagged and resolved conservatively;
- trailing stop is updated after the bar close and only applies from the next
  bar;
- reversal pays two legs: close old position and open new position;
- result metadata contains `validation_certificate`, `data_signature`,
  `execution_contract`, `fills_report`, `kernel_version`, and report-level
  details.

Report levels:

- `minimal`: optimizer/WFO path. Keeps equity, position, fees/funding, counters,
  and event flags; no fill ledger materialization.
- `standard`: default notebook/service path. Adds diagnostics such as active
  stop/TP and margin series; still no fill DataFrame.
- `audit`: runs a deterministic second pass, allocates sparse fill arrays sized
  exactly to real `fill_count`, materializes `result.fills` and
  `bt.fills_report`, and asserts parity against pass 1.

Use the reference endpoint for differential debugging:

```python
ref = QuantBTEndpoint.intrabar_bracket_reference(
    initial_capital=20_000,
    leverage=5,
    fee_rate=0.0002,
    slippage_bps=1.0,
    use_funding=False,
)

ref_result = ref.backtest(
    data=df,
    signal_col="entry_signal",
    symbols=["ETHUSDT"],
    intent_cols={"stop_value": "sl_pct", "take_profit_value": "tp_pct"},
)
```

Prepared runner for optimizers:

```python
bt = QuantBTEndpoint.intrabar_bracket(
    initial_capital=20_000,
    leverage=5,
    fee_rate=0.0002,
    slippage_bps=1.0,
    use_funding=False,
    report_level="minimal",
)

runner = bt.prepare_intrabar(data=df, symbols=["ETHUSDT"])
intent = alpha.generate(runner.market, params)
result = runner.run(intent, report_level="minimal")
audit = runner.run(intent, report_level="audit")
```

Funding for intrabar routes is event-causal only when the funding timestamp
matches an exact market bar timestamp. Mid-bar funding events are rejected and
require a smaller timeframe. Use `use_funding=False` when no funding is part of
the test, pass an aligned funding Series with non-zero values only on funding
bars, or pass exact-boundary `funding_event_timestamps` plus
`funding_event_rates` to `backtest(...)` / `prepare_intrabar(...)`.

Also declare the bar timestamp convention when funding is enabled:
`bar_timestamp_semantics="close"` is the default and applies funding after the
bar's intrabar path on the remaining close position. Use
`bar_timestamp_semantics="open"` for bar-open timestamped crypto feeds; funding
then applies before pending exit/entry orders at `open[t]`.

Custom execution contracts can be passed directly and are preserved in
metadata:

```python
from quantbt import ExecutionContract, IntrabarSameBarPolicy

contract = ExecutionContract.intrabar_bracket(
    same_bar_policy=IntrabarSameBarPolicy.TP_FIRST,
    close_on_last_bar=False,
)

bt = QuantBTEndpoint.intrabar_bracket(execution_contract=contract)
```

Unsupported contract fields raise `NotImplementedError`; they are not silently
reset to defaults.

## Fill Replay

Use this when an old alpha already emitted explicit fills and QuantBT should
only validate/account them. This route certifies accounting, not fill
generation.

```python
bt = QuantBTEndpoint.fill_replay(
    initial_capital=20_000,
    leverage=5,
    contract_size=1.0,
)

result = bt.backtest(
    data=df,
    symbols=["ETHUSDT"],
    fill_replay=fills_df,
)
```

`fills_df` must be sorted by `bar_index`, then `sequence`, and contain:

```text
bar_index
side       # +1 buy, -1 sell
qty
price
```

This route is Level 1 certification by design: QuantBT certifies accounting from
the supplied fills, while the alpha or external system remains responsible for
causal fill generation.

## Alpha Execution Audit

Use the scanner before migrating old alpha directories:

```bash
PYTHONPATH=/root/bobby/pool_alpha \
python3 quantbt/tools/audit_alpha_execution_contracts.py \
  /root/bobby/pool_alpha/alphas_storage/TA \
  --json-out /tmp/alpha_contracts.json \
  --md-out /tmp/alpha_contracts.md
```

Or from Python:

```python
from quantbt import (
    scan_alpha_directory,
    build_alpha_certification_report,
    alpha_report_markdown,
)

items = scan_alpha_directory("/root/bobby/pool_alpha/alphas_storage/TA")
report = build_alpha_certification_report(items)
print(alpha_report_markdown(report))
```

Certification levels:

| Level | Meaning |
|---:|---|
| 0 | legacy or unspecified execution contract |
| 1 | explicit-fill accounting replay |
| 2 | engine-causal QuantBT execution |
| 3 | native cross-backend parity |
| 4 | external validation, usually Nautilus/lower-timeframe route |

Optional columns:

```text
sequence
fee
reason
```

If `fee` is omitted, `fee_rate` is used to compute one-way fees from notional.
Result metadata declares:

```text
accounting_certified = true
execution_generation_certified = false
```

## DCA / Grid Ladder

Use this when `signal` is a structural ladder level, not a dynamic position
weight.

```python
bt = QuantBTEndpoint.dca_ladder(
    initial_capital=20_000,
    leverage=5,
    alloc_per_trade=1_000,
    fee=0.0004,
    slippage=0.0001,
    use_funding=False,
    dca_step_pct=0.01,
    dca_step_scale=1.2,
    dca_volume_scale=1.5,
    dca_max_safety_orders=5,
    dca_take_profit_pct=0.006,
    dca_allow_same_bar_exit=False,
)

result = bt.backtest(
    data=df,
    signal_col="grid_level",
)
```

Signal meaning:

- `0`: flat;
- `1`: base order active;
- `2`: base plus first safety order allowed;
- `3`: base plus second safety order allowed;
- `6`: base plus five safety orders allowed;
- negative levels model short ladders.

Input requirement:

- `data`: one OHLCV DataFrame;
- `signal` or `signal_col`: integer-like structural levels;
- real `high` and `low` are required for correct limit-touch simulation.

Execution logic:

- base order fills when signal transitions from flat to level one;
- safety orders are activated by level transitions;
- each safety order fills at its trigger/grid price if `high/low` touches it;
- fills do not use close price unless the grid trigger is the close price.

Routing:

- backend: `legacy`;
- engine: `BacktestEngine`;
- sizing: `dca_ladder`.

Optional Nautilus structured DCA/grid validation:

```python
from quantbt import DcaGridSpec, OrderSide, QuantBTEndpoint
from quantbt.adapters.nautilus import NautilusBackendConfig

symbol = "ETHUSDT-PERP.BINANCE"

bt = QuantBTEndpoint.nautilus_dca_grid(
    spec=DcaGridSpec(
        symbol=symbol,
        entry_timestamp=df.index[10],
        exit_timestamp=df.index[11],  # often next bar for bar-based contingent exits
        side=OrderSide.BUY,
        base_notional=1_000,
        safety_notional=500,
        safety_order_count=2,
        step_pct=0.01,
        step_scale=1.2,
        volume_scale=1.5,
        take_profit_pct=0.01,
        stop_loss_pct=0.05,
    ),
    initial_capital=20_000,
    use_funding=False,
    nautilus_config=NautilusBackendConfig(
        instrument_id=symbol,
        timeframe="1h",
        starting_balance=20_000,
        bypass_risk=True,
    ),
)

result = bt.simulate(data=df)
result.metadata["package_order_map"]
result.metadata["oco_cancellations"]
```

This route compiles a deterministic package into explicit orders. Nautilus
handles bar high/low touch behavior, order lifecycle, fills and sibling
cancellation. TP/SL exits are reduce-only and sized to the maximum planned
ladder quantity for conservative validation.

## Explicit Orders

Use this when the strategy already produces orders instead of target positions.

```python
from quantbt import OrderIntent, OrderSide, OrderType, QuantBTEndpoint, TimeInForce

orders = [
    OrderIntent(
        timestamp=df.index[10],
        symbol="ETHUSDT",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        qty=3.0,
        price=1800.0,
        tif=TimeInForce.GTC,
        tag="entry-1",
    )
]

bt = QuantBTEndpoint.orders(
    backend="native_event",
    initial_capital=100_000,
    leverage=5,
    fee_rate=0.0002,
    slippage_bps=1.0,
    use_funding=False,
)

result = bt.simulate(
    data=df,
    orders=orders,
    symbols=["ETHUSDT"],
)

bt.export_orders("orders.csv")
bt.export_fills("fills.csv")
```

Input requirement:

- `data`: one OHLCV DataFrame for the symbol stream;
- `orders`: list of `OrderIntent`;
- `symbols`: should contain the symbols used by the orders.

`OrderIntent` fields:

- `timestamp`: bar timestamp;
- `symbol`: instrument name;
- `side`: `OrderSide.BUY` or `OrderSide.SELL`;
- `order_type`: `MARKET` or `LIMIT` on the current native-event v1 route;
- `qty`: positive quantity;
- `price`: required for limit orders;
- `tif`: `GTC`, `IOC`, `FOK`, or `GTD`.

Lifecycle-v2 contract:

```python
from quantbt import OrderAction, OrderCommand

commands = [
    OrderCommand(
        timestamp=df.index[10],
        action=OrderAction.PLACE,
        symbol="ETHUSDT",
        side=OrderSide.BUY,
        order_type=OrderType.STOP_LIMIT,
        qty=3.0,
        price=1795.0,
        trigger_price=1800.0,
        order_id="entry-stop-limit",
        oco_group_id="eth-grid-1",
    ),
    OrderCommand(
        timestamp=df.index[12],
        action=OrderAction.CANCEL,
        target_order_id="entry-stop-limit",
    ),
]
```

Phase 30C exposes this through `QuantBTEndpoint.native_event_lifecycle(...)`
and through `QuantBTEndpoint.orders(..., event_engine_version="v2")`. Existing
`QuantBTEndpoint.orders(...)` calls still default to the v1 `OrderIntent`
route.

```python
from quantbt import AccountConfig, NativeEventBackend, NativeEventConfig

backend = NativeEventBackend(
    NativeEventConfig(account=AccountConfig(initial_capital=100_000, leverage=5))
)

result = backend.run_order_commands(
    datetime_index=df.index,
    commands=commands,
    closes={"ETHUSDT": df["close"]},
    highs={"ETHUSDT": df["high"]},
    lows={"ETHUSDT": df["low"]},
    symbols=["ETHUSDT"],
)

result.metadata["command_report"]
result.metadata["order_events"]
result.metadata["active_orders"]
```

Endpoint equivalent:

```python
bt = QuantBTEndpoint.native_event_lifecycle(
    initial_capital=100_000,
    leverage=5,
    fee_rate=0.0002,
    use_funding=False,
)

result = bt.simulate(
    data=df,
    order_commands=commands,
    symbols=["ETHUSDT"],
)
```

Native-event artifact policy:

```python
bt = QuantBTEndpoint.native_event_lifecycle(
    initial_capital=100_000,
    leverage=5,
    report_level="minimal",   # minimal | standard | audit | full
    audit_sink="none",        # none | memory | jsonl | parquet
)
```

`report_level` changes only artifact retention. It must not change equity,
positions, fees, funding, margin, liquidation, or lifecycle counters.

| Level | Intended use | Retained artifacts |
|---|---|---|
| `minimal` | WFO/service loops | accounting paths, diagnostics, compact fill/command ledgers, no Python fills/orders, no event DataFrame |
| `standard` | research | minimal artifacts plus Python fills and command terminal report |
| `audit` / `full` | certification | full command report, event report, active-order report, Python fills/orders, compact ledgers |

For long audits, use a disk sink:

```python
bt = QuantBTEndpoint.native_event_lifecycle(
    report_level="audit",
    audit_sink="jsonl",
    audit_sink_path="/tmp/quantbt_native_event_audit",
)
```

`jsonl` and `parquet` sinks require an explicit `audit_sink_path`; QuantBT does
not silently create long-lived audit bundles in arbitrary project folders.

Execution rules:

- market orders fill on the bar close with slippage;
- limit orders fill at the order price when the bar high/low touches it;
- IOC cancels if the order is not touched on its eligible bar;
- GTC remains active until filled or simulation ends.

Routing:

- backend: `native_event` by default;
- engine: `BacktestEngineV2`.

Optional Nautilus explicit-order replay:

```python
from quantbt.adapters.nautilus import NautilusBackendConfig

bt = QuantBTEndpoint.orders(
    backend="nautilus",
    initial_capital=100_000,
    use_funding=False,
    nautilus_config=NautilusBackendConfig(
        instrument_id="ETHUSDT-PERP.BINANCE",
        timeframe="1h",
        starting_balance=100_000,
        bypass_risk=True,
    ),
)

result = bt.simulate(
    data=df,
    orders=[
        OrderIntent(
            timestamp=df.index[10],
            symbol="ETHUSDT-PERP.BINANCE",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            qty=0.5,
            price=1800.0,
            tif=TimeInForce.GTC,
            tag="entry-limit",
        )
    ],
    symbols=["ETHUSDT-PERP.BINANCE"],
)
```

Phase 5.2A Nautilus order replay supports single-symbol market, limit,
stop-market, and stop-limit order factory mapping when Nautilus exposes the
route cleanly. It preserves TIF, reduce-only, and tags in the Nautilus order
reports. DCA/grid, bracket/OCO, basket, portfolio and arbitrage packages remain
higher-level adapters that compile into this explicit-order replay path.

Lifecycle commands with Nautilus:

- `QuantBTEndpoint.orders(backend="nautilus")` accepts `order_commands`;
- executable `PLACE` and `REPLACE` commands are converted to Nautilus package
  `OrderIntent` payloads;
- native lifecycle-only actions such as `CANCEL` and `AMEND` remain audited by
  native-event v2 and are not exchange-native Nautilus command objects yet.

Native structured lifecycle endpoints:

```python
bt = QuantBTEndpoint.native_event_bracket_orders(
    spec=bracket_spec,
    initial_capital=100_000,
    leverage=5,
)
result = bt.simulate(data=df)
result.metadata["command_report"]
result.metadata["order_events"]

grid_bt = QuantBTEndpoint.native_event_dca_grid(spec=dca_grid_spec)
grid_result = grid_bt.simulate(data=df)
```

Reactive native-event strategy:

```python
from quantbt import OrderAction, OrderCommand, OrderSide, OrderType, QuantBTEndpoint, TimeInForce

class DynamicGridStrategy:
    def initialize(self, context):
        return []

    def on_bar_close(self, context):
        # Context is post-bar and read-only. Fills, positions and active orders
        # come from QuantBT, not from strategy-side fill simulation.
        if context.bar_index == 0:
            qty = context.size_order("ETHUSDT", notional=1_000, price=context.close[0] * 0.99)
            return [
                OrderCommand(
                    timestamp=context.timestamp,
                    symbol="ETHUSDT",
                    side=OrderSide.BUY,
                    order_type=OrderType.LIMIT,
                    qty=qty,
                    price=context.close[0] * 0.99,
                    tif=TimeInForce.GTC,
                    order_id="grid-c1-l1",
                    metadata={"campaign_id": "c1", "level_id": "l1"},
                )
            ]
        return []

bt = QuantBTEndpoint.native_event_strategy(
    initial_capital=20_000,
    leverage=5,
    fee_rate=0.0005,
    reactive_execution_mode="fast",
    reactive_kernel_mode="replay_certified",  # replay_certified | single_pass
)

result = bt.simulate(
    data=df,
    strategy=DynamicGridStrategy(),
    symbols=["ETHUSDT"],
)

tape = result.metadata["emitted_command_tape"]
replay = QuantBTEndpoint.native_event_lifecycle(
    initial_capital=20_000,
    leverage=5,
    fee_rate=0.0005,
).simulate(data=df, order_commands=tape, symbols=["ETHUSDT"])
```

Reactive timing is causal: commands returned by `on_bar_close(context_t)` are
retimed to bar `t+1`, so they cannot fill inside the same OHLC bar that the
strategy just observed.

`reactive_kernel_mode="replay_certified"` is the conservative default. It uses
the incremental callback session to build state and then runs one certified
static event-v2 replay for the final public result. Use it for stakeholder
reports, debugging, and migration validation.

`reactive_kernel_mode="single_pass"` materializes accounting directly from the
incremental reactive session for `report_level="minimal"` and score paths,
skipping the final static replay. For `report_level="standard"`,
`report_level="audit"`, or `reactive_execution_mode="audit"`, QuantBT still
runs the replay oracle and asserts accounting parity before returning the
single-pass result.

Reactive metadata:

```python
result.metadata["reactive_context_builder"]       # "incremental_session_v1"
result.metadata["reactive_incremental_compile_replays"]  # 0
result.metadata["reactive_static_replay_count"]   # 0 for single_pass minimal/score
result.metadata["emitted_command_tape"]           # replayable OrderCommand tape
```

### Native-event backend selector (Phase 46E)

Native-event endpoints accept the optional `native_backend` selector:

```python
bt = QuantBTEndpoint.orders(
    backend="native_event",
    native_backend="python",  # python | rust | auto | replay_certified
    initial_capital=20_000,
    leverage=5,
    maintenance_ratio=0.0,
    use_funding=False,
)
```

`python` is the full-featured canonical reactive backend. `rust` is explicit
and fail-fast: with the installed API `0.4` full-contract wheel it supports
the same Native Event V2 lifecycle surface used by this endpoint, including
multi-symbol tapes, funding, maintenance/liquidation, quantity preflight,
MARKET/LIMIT/STOP orders, GTC/GTD/IOC/FOK, amend/replace/cancel-all, and
parent/group/OCO relationships. A wheel without the required capability keys
raises a capability error; it is never silently downgraded to Python.
`auto` remains Python for the release policy and does not activate Rust yet.
`replay_certified` is the deterministic audit oracle. Rust audit results are
adapted to `BacktestResultV2`, so the normal `show_metrics()`, `full_report()`,
`quick_plot()`, and `tearsheet()` helpers remain available. The score path
crosses the PyO3 boundary with typed arrays and does not build pandas report
frames; rerun the selected tape at audit level when full evidence is required.

The complete Phase 47B contract and conformance evidence are documented in
[`native_event_rust_full_contract.md`](native_event_rust_full_contract.md).
The external Grid 2,000-bar parity, scalar-score retention contract, backend
policy, and isolated RSS benchmark are documented in
[`grid_native_event_phase47c.md`](grid_native_event_phase47c.md).

The Grid optimizer-safe Phase 47D policy is documented in the same guide. The
public/audit default keeps `collect_diagnostics=True`; the external Grid
`score_grid_params(...)` helper overrides only that artifact policy to
`False`, derives the minimal context contract from the strategy, and keeps
the prepared runner scalar-only. This does not alter order generation,
matching, fees, funding, margin, liquidation, or terminal accounting. A
diagnostics-off strategy cannot build the stakeholder audit frame; rerun the
candidate with the default audit policy for `build_output_frame()`, plots, and
full reports.

For reactive strategies, `report_level="minimal"` intentionally omits
`emitted_command_tape` from metadata while preserving
`emitted_command_count`. Use `report_level="audit"` when a replayable command
tape is required for certification.

Prepared native-event scoring:

```python
bt = QuantBTEndpoint.native_event_strategy(
    initial_capital=20_000,
    leverage=5,
    fee_rate=0.0005,
    report_level="audit",
    reactive_kernel_mode="replay_certified",
)

prepared = bt.prepare_native_event_strategy(
    data=df,
    symbols=["ETHUSDT"],
)

score = prepared.score(
    strategy=DynamicGridStrategy(params),
    trading_days=365,
)

audit = prepared.run(
    strategy=DynamicGridStrategy(params),
    report_level="audit",
)
```

`prepared.score(...)` returns `NativeEventScoreResult`: ndarray accounting
paths plus metrics, not a public `BacktestResultV2`. It does not update
`bt.result`, so Optuna/WFO loops do not retain the previous trial's full
artifact bundle. Phase 34C makes `prepared.score(...)` use the single-pass
reactive session accounting path and skip the final replay while maintaining
parity with `prepared.run(..., report_level="audit")`. `prepared.run(...)`
returns the normal public
`BacktestResultV2` and should be used for final audit/replay exports.

For high-volume prepared optimization, use the zero-retention score contract:

```python
from quantbt import NativeEventScoreRequirements

score = prepared.score(
    DynamicGridStrategy(params),
    trading_days=365,
    score_requirements=NativeEventScoreRequirements.scalar_score_contract(),
)
report = score.full_report()
```

This returns `NativeEventScalarScoreResult`. It keeps scalar online metrics,
live order state, counters, and final positions; it does not allocate full
equity/position/fee/funding/margin paths, pandas reports, or a command tape.
Its metrics are parity-locked to the same array-first report implementation.
The compatibility call without `score_requirements` keeps the ndarray
`NativeEventScoreResult` contract for existing callers that inspect paths.

Strategies may opt out of callback payload objects when they do not consume
them:

```python
class GridStrategy:
    native_context_requirements = {
        "fills": False,
        "events": False,
        "active_orders": False,
        "positions": False,
        "margin": False,
    }
```

The declaration only changes context materialization. It never changes order
timing, matching, fees, funding, margin, liquidation, or accounting formulas.
`PreparedNativeEventStrategyEvaluator` uses the scalar contract by default and
still accepts legacy list/tuple callback returns. Strategies that want an
explicit immutable callback batch may return
`NativeCommandBatch.from_commands(commands)`.

Scoped cancel-all:

```python
OrderCommand(
    timestamp=context.timestamp,
    action=OrderAction.CANCEL_ALL,
    symbol="ETHUSDT",
    tag_prefix="GRID-C12",
)
```

Static lifecycle replay supports scoped `CANCEL_ALL` by symbol, side,
order type, parent order id, group id and OCO group id. Reactive strategies can
also scope by exact tag, tag prefix, campaign id, cycle id and level id; the
runner expands those string scopes into target `CANCEL` commands before final
kernel replay.

Package execution-depth preflight:

```python
from quantbt import NautilusExecutionDepthConfig, simulate_nautilus_order_package_depth

preflight = simulate_nautilus_order_package_depth(
    orders=plan.orders,
    data={
        "BTCUSDT-PERP.BINANCE": btc_ohlcv,
        "ETHUSDT-PERP.BINANCE": eth_ohlcv,
    },
    config=NautilusExecutionDepthConfig(
        all_or_none_packages=True,
        allow_partial_fills=True,
        max_participation_rate=0.05,
        queue_ahead_qty=10.0,
        latency_bars=1,
    ),
)

accepted_orders = preflight.orders
order_audit = preflight.order_report
package_audit = preflight.package_report
```

This helper is opt-in and does not change default endpoint behavior. It checks
high/low touch eligibility, latency bars, queue-ahead, volume participation,
reduce-only capping, OCO sibling cancellation, and all-or-none package
rejection before accepted orders are submitted through Nautilus routes.

Synthetic book depth stress:

```python
from quantbt import NautilusExecutionDepthConfig, simulate_nautilus_order_package_depth

preflight = simulate_nautilus_order_package_depth(
    orders=plan.orders,
    data={"BTCUSDT-PERP.BINANCE": df},
    config=NautilusExecutionDepthConfig(
        depth_model="synthetic_book",
        allow_partial_fills=True,
        max_participation_rate=0.05,
        queue_ahead_qty=0.25,
        synthetic_spread_bps=2.0,
        synthetic_level_spacing_bps=2.0,
        synthetic_levels=8,
        synthetic_base_depth_notional=50_000,
        synthetic_depth_slope=0.05,
    ),
)

preflight.order_report
```

Use `ohlcv_volume_cap` for fast Level-1 package checks, `synthetic_book` for
deterministic Level-2 execution stress, and reserve `l2_replay` for future real
venue book replay. `l2_replay` intentionally refuses to run without a provider
containing snapshots, incremental book updates, and trade prints.

Depth helper surface:

```python
from quantbt import SUPPORTED_DEPTH_MODELS, l2_replay_available

SUPPORTED_DEPTH_MODELS
# ("ohlcv_volume_cap", "synthetic_book", "l2_replay")

if l2_replay_available(provider):
    ...
```

`l2_replay_available(...)` is a guardrail helper. It only returns true when a
provider exposes `snapshots`, `updates`, and `trades`; otherwise services should
use `ohlcv_volume_cap` or `synthetic_book` and label reports accordingly.

Structured bracket/OCO validation:

```python
from quantbt import BracketOrderSpec, OrderSide, QuantBTEndpoint

bt = QuantBTEndpoint.nautilus_bracket_orders(
    spec=BracketOrderSpec(
        symbol="ETHUSDT-PERP.BINANCE",
        entry_timestamp=df.index[10],
        exit_timestamp=df.index[11],
        side=OrderSide.BUY,
        qty=0.25,
        take_profit_price=2_100,
        stop_loss_price=1_950,
    ),
    initial_capital=20_000,
    use_funding=False,
)

result = bt.simulate(data=df)
result.metadata["package_order_map"]
result.metadata["oco_cancellations"]
```

Bracket/OCO exits preserve `oco_group_id`, `parent_tag`, `leg_role` and tags in
the package map. When an exit fills, the Nautilus package strategy cancels the
sibling exit order.

Native-vs-Nautilus parity audit:

```python
from quantbt import QuantBTEndpoint, build_native_nautilus_parity_report

native_bt = QuantBTEndpoint.orders(backend="native_event", initial_capital=100_000)
nautilus_bt = QuantBTEndpoint.orders(
    backend="nautilus",
    initial_capital=100_000,
    nautilus_config=NautilusBackendConfig(
        instrument_id="ETHUSDT-PERP.BINANCE",
        timeframe="1h",
        starting_balance=100_000,
    ),
)

native = native_bt.simulate(
    data=df,
    orders=orders,
    symbols=["ETHUSDT-PERP.BINANCE"],
)
nautilus = nautilus_bt.simulate(
    data=df,
    orders=orders,
    symbols=["ETHUSDT-PERP.BINANCE"],
)

parity = build_native_nautilus_parity_report(native, nautilus)
```

The parity table includes requested quantity/price, native and Nautilus fill
prices, fees, positions, equity, and diffs. It is designed as an audit artifact;
known intentional differences should be documented rather than hidden.

`summarize_native_nautilus_parity_report(parity)` returns a compact pass/fail
summary with max absolute fill-price, fee, position, and equity differences.

## Basket / Pair

Use this for pair trades or frozen hedge-ratio baskets. The basket signal is a
scalar series; the engine expands it to per-leg orders using `BasketSpec`.

Nautilus basket validation is available as an experimental package-order route:

```python
result = QuantBTEndpoint.basket(
    basket=basket,
    backend="nautilus",
    initial_capital=100_000,
).simulate(data=data_dict, signal=basket_signal)
```

The route compiles `BasketSpec` into explicit per-leg market `OrderIntent`
packages, preserving `basket_id`, target units, and package metadata for audit.
Native basket remains the faster research path.

```python
from quantbt import BasketLegSpec, BasketSpec, QuantBTEndpoint

basket = BasketSpec(
    basket_id="PAIR-001",
    legs=(
        BasketLegSpec(symbol="BASE", ratio=1.0),
        BasketLegSpec(symbol="HEDGE", ratio=-0.5),
    ),
    gross_notional=100_000,
)

bt = QuantBTEndpoint.basket(
    basket=basket,
    initial_capital=1_000_000,
    leverage=5,
    fee_rate=0.0002,
    use_funding=False,
)

result = bt.simulate(
    data={"BASE": base_df, "HEDGE": hedge_df},
    signal=pair_signal,
)
```

Input requirement:

- `basket`: `BasketSpec` passed to the factory or to `simulate()`;
- `data`: `{symbol: DataFrame}` for all basket legs;
- `signal` or `signal_col`: scalar on/off or signed basket series;
- each leg DataFrame requires `close`; real `high/low` are recommended.

Diagnostics:

```python
result.metadata["basket_plan"]
result.metadata["basket_target_units"]
bt.fills
```

Routing:

- backend: `native_event`;
- engine: `BacktestEngineV2`.

## Arbitrage

Use this for package-style arbitrage where one scalar signal expands into
multiple legs that should be sized together.

```python
from quantbt import (
    ArbitrageLeg,
    ContractType,
    HedgePolicy,
    HedgePolicyKind,
    QuantBTEndpoint,
    SizingPolicy,
    SizingPolicyKind,
    StatArbPairSpec,
)

spec = StatArbPairSpec(
    arb_id="ETH_SOL_STAT_ARB",
    legs=(
        ArbitrageLeg("ETHUSDT-PERP.BINANCE", ratio=1.0, role="base", contract_type=ContractType.LINEAR),
        ArbitrageLeg("SOLUSDT-PERP.BINANCE", ratio=-1.0, role="hedge", contract_type=ContractType.LINEAR),
    ),
    hedge_policy=HedgePolicy(HedgePolicyKind.DELTA_NEUTRAL, freeze_on_entry=True),
    sizing_policy=SizingPolicy(SizingPolicyKind.TARGET_GROSS_NOTIONAL, notional=50_000),
)

bt = QuantBTEndpoint.arbitrage(
    arb_type="stat_arb_pair",
    spec=spec,
    backend="native_vectorized",
    initial_capital=100_000,
    leverage=5,
    fee_rate=0.0002,
    use_funding=False,
)

result = bt.backtest(
    data={
        "ETHUSDT-PERP.BINANCE": eth_df,
        "SOLUSDT-PERP.BINANCE": sol_df,
    },
    signal=entry_exit_signal,
    hedge_ratios={
        "ETHUSDT-PERP.BINANCE": eth_beta,
        "SOLUSDT-PERP.BINANCE": -sol_beta,
    },
)

bt.show_metrics()
result.metadata["package_target_units"]
result.metadata["leg_pnl_report"]
result.metadata["package_pnl_report"]
result.metadata["beta_drift_report"]
```

Supported executable specs:

| Spec | Native event | Native vectorized | Nautilus | Notes |
|---|---:|---:|---:|---|
| `BasisArbitrageSpec` | yes | yes | package validation | linear USDM-style legs only today |
| `StatArbPairSpec` | yes | yes | package validation | frozen or rebalance-threshold hedge-ratio pair; dynamic `hedge_ratios` supported |
| `CalendarSpreadSpec` | yes | yes | no | package-style futures spread |
| `FundingArbitrageSpec` | yes | yes | no | funding-enabled leg required |
| `SpotPerpCashCarrySpec` | yes | yes | no | spot plus funding-enabled derivative |
| `IndexBasketArbSpec` | yes | yes | no | requires `target_gross_notional` sizing |

Schema-only specs that must not be routed through generic package execution yet:

| Spec | Why it is not executable yet |
|---|---|
| `CrossExchangeArbSpec` | needs venue/account split, transfer state, borrow constraints, and venue-specific margin |
| `TriangularArbSpec` | needs sequenced path execution, latency, partial-fill propagation, and path PnL |
| `OptionsVolArbSpec` | needs option instruments, Greeks, IV surface, expiry, assignment, and hedge behavior |

You can inspect the live matrix from Python:

```python
matrix = QuantBTEndpoint.arbitrage_support_matrix()
matrix["StatArbPairSpec"]
```

Input requirement:

- `spec`: one supported arbitrage spec passed to `QuantBTEndpoint.arbitrage()`;
- `data`: `{symbol: DataFrame}` for all spec legs, or explicit `closes/highs/lows`;
- `signal`: scalar entry/exit series where `0` means flat and sign controls
  package direction;
- `hedge_ratios`: optional per-leg ratio series for dynamic beta/hedge models;
- each price series must be finite and strictly positive after UTC alignment.

Package execution policy:

- `PackageExecutionKind.ATOMIC_ALL_OR_NONE`: the package is preflighted as a
  whole. If margin is insufficient, no leg order is generated and
  `package_rejection_report` records `insufficient_margin_atomic`;
- `PackageExecutionKind.BEST_EFFORT`: legs are preflighted sequentially. Legs
  with enough margin can open, rejected legs are recorded as
  `insufficient_margin_best_effort`, and only actual open legs are later closed.

Stat-arb reporting:

- `leg_pnl_report`: row-level per-symbol PnL with `role`, `price_pnl`,
  `fill_pnl`, `fee`, `funding_pnl`, `total_pnl`, and `cumulative_pnl`;
- `package_pnl_report`: timestamp-level reconciliation with `leg_pnl`,
  `hedge_pnl`, `spread_pnl`, `fees`, `funding_pnl`, `package_pnl`,
  `equity_delta`, and `pnl_residual`;
- `spread_report`: pair spread/residual computed from the frozen or current
  hedge ratio used by the package planner;
- `beta_drift_report`: hedge-ratio drift diagnostics and threshold breaches;
- funding is charged only to legs marked `funding_enabled=True`, matching the
  rest of the arbitrage package routes.

Current hard guards:

- inverse and quanto contract sizing raises `NotImplementedError` until proper
  contract-value formulas are implemented;
- `BasisArbitrageSpec` remains linear-only;
- missing, NaN, infinite, or non-positive close data raises `ValueError`.

Basis example:

```python
from quantbt import BasisArbitrageSpec

spec = BasisArbitrageSpec(
    arb_id="BTC_PERP_QUARTERLY_BASIS",
    legs=(
        ArbitrageLeg("BTCUSDT-PERP.BINANCE", ratio=-1.0, role="perp", contract_type=ContractType.LINEAR),
        ArbitrageLeg("BTCUSDT-QUARTERLY.BINANCE", ratio=1.0, role="quarterly", contract_type=ContractType.LINEAR),
    ),
    hedge_policy=HedgePolicy(HedgePolicyKind.BASE_QTY_EQUAL, freeze_on_entry=True),
    sizing_policy=SizingPolicy(
        SizingPolicyKind.TARGET_NOTIONAL_TO_BASE_QTY,
        notional=100_000,
        reference_symbol="BTCUSDT-PERP.BINANCE",
    ),
)

bt = QuantBTEndpoint.arbitrage(
    arb_type="basis",
    spec=spec,
    backend="native_event",
    initial_capital=50_000,
    leverage=5,
    fee_rate=0.0002,
)

result = bt.simulate(data=data_by_symbol, signal=basis_signal)
result.metadata["spread_report"]
result.metadata["package_rejection_report"]
```

Routing:

- `native_vectorized`: fastest path for supported package specs;
- `native_event`: fill/order diagnostics, package rejection reports, and
  native event margin/liquidation lifecycle;
- `nautilus`: validation adapter for `BasisArbitrageSpec` and
  `StatArbPairSpec` package orders only.

## Multi-Symbol Portfolio

Use this for a position matrix across many symbols.

```python
bt = QuantBTEndpoint.portfolio(
    portfolio_mode="longshort",
    initial_capital=1_000_000,
    leverage=1,
    alloc_per_trade=50_000,
    asset_type="crypto",
    use_funding=False,
    fee=0.001,
)

result = bt.backtest(
    positions=positions_df,       # columns are symbols
    data=data_dict,               # {symbol: OHLCV DataFrame}
)
```

Input requirement:

- `positions`: DataFrame with DatetimeIndex and symbol columns, or
  `{symbol: Series}`;
- `data`: `{symbol: OHLCV DataFrame}`;
- all symbols in `positions` should exist in `data`.

Supported portfolio modes:

- `longshort`: use positive and negative signals;
- `market_neutral`: balance long and short books where supported;
- `directional`: directional allocation workflow;
- `equal_weight`: equalize active symbols.

Alternative explicit price maps:

```python
result = bt.backtest(
    positions=positions_df,
    closes=closes,
    highs=highs,
    lows=lows,
    datetime_index=positions_df.index,
)
```

Routing:

- backend: `native_portfolio` by default;
- backend: `legacy_portfolio` for historical compatibility/reproduction;
- engine: `PortfolioBacktestEngine`.

Native portfolio route:

```python
result = QuantBTEndpoint.portfolio(
    portfolio_mode="market_neutral",
    backend="native_portfolio",
    hedge_type="signal_notional",
    alloc_per_trade={"BTC": 50_000, "ETH": 50_000},
    initial_capital=1_000_000,
    leverage=3,
    slippage_bps=2.0,
).backtest(
    positions=positions_df,
    data=data_dict,
)
```

Native portfolio supports modes `longshort`, `market_neutral`, `directional`,
`equal_weight`, `risk_parity`, and `beta_neutral`.

Supported sizing modes are `signal_notional`, `signal`, `notional`, `unit`,
`%_equity`, `target_weight`, `target_units`, `target_notional`,
`fixed_notional`, `gross_exposure`, and `net_exposure`.

Sizing semantics:

- `%_equity`: signal times `alloc_per_trade` fraction of live equity;
- `target_weight`: signal is direct portfolio weight per symbol;
- `gross_exposure`: raw signed signal is normalized to target gross exposure
  `equity * alloc_per_trade`;
- `net_exposure`: raw signed signal is normalized to target net exposure
  `equity * alloc_per_trade`;
- `target_notional`: input matrix is signed notional;
- `target_units`: input matrix is explicit contracts/units.

`risk_parity` uses inverse rolling volatility from close returns
(`risk_lookback`, default `60`). `beta_neutral` uses optional
`betas={symbol: beta}`; if omitted, beta defaults to `1.0`, making it a basic
dollar-neutral beta constraint.

`dca_ladder` remains on the DCA/grid engine because it requires intrabar
grid-trigger fills.

Execution and accounting semantics:

- portfolio is a vectorized close-to-close engine; it does not claim intrabar
  portfolio fills;
- QuantBT does not shift the signal matrix. Strategies must pass already-causal
  targets;
- `fee_rate` is canonical one-way. Legacy `fee` is round-trip and is converted
  at the endpoint boundary only;
- metadata records `canonical_one_way_fee_rate`;
- `slippage_bps` is the source of truth for native portfolio slippage;
- legacy `slippage` is accepted for compatibility and converted to
  `slippage_bps`, but new code should prefer `slippage_bps`;
- turnover is based on accepted traded delta:

```text
delta_qty = accepted_target_qty - previous_qty
turnover_notional = abs(delta_qty) * execution_price * contract_size
```

- reversal `+1 -> -1` therefore records two units of traded turnover;
- fees, slippage, turnover, symbol PnL, and rebalance reports are all derived
  from the same accepted `delta_qty`;
- buying-power checks use post-fee/post-slippage equity, including gross-neutral
  reversals.

Tradability and missing-data policy:

- leading missing prices are not tradable;
- non-tradable/stale symbols cannot be rebalanced on that bar;
- existing positions may still mark to the last valid close when available;
- `market_neutral` requires both long and short sides. If one side is missing,
  the target is zeroed instead of becoming accidental directional exposure;
- `risk_parity` is causal: rolling volatility uses only past/current close
  returns and warm-up bars with insufficient observations target zero exposure.

Native portfolio metadata includes:

```python
result.metadata["slippage_series"]
result.metadata["slippage_total"]
result.metadata["slippage_bps"]
result.metadata["canonical_one_way_fee_rate"]
result.metadata["rebalance_report"]
result.metadata["symbol_pnl_report"]
result.metadata["portfolio_reconciliation_report"]
result.metadata["run_config"]["fees"]["applied_fee_source"]
```

Native portfolio report levels:

```python
result = QuantBTEndpoint.portfolio(
    portfolio_mode="longshort",
    backend="native_portfolio",
    report_level="full",      # full | standard | minimal
).backtest(
    positions=positions_df,
    data=data_dict,
)
```

- `full`: default and backward compatible. Keeps all stakeholder/audit tables,
  including target/accepted notional, exposure, symbol PnL, risk reports, kernel
  symbol PnL, and rebalance report.
- `standard`: keeps core audit tables such as target/accepted notional,
  exposure, funding-rate report, and symbol PnL, but omits selected expansion
  tables.
- `minimal`: keeps accounting-critical result surfaces only: equity, returns,
  positions, closes, fees, funding, margin, diagnostics, target/accepted units,
  totals, and config metadata. Use it inside optimizers or service loops, then
  rerun the chosen portfolio with `report_level="full"` for final audit.

Core accounting is identical across report levels; only metadata artifact
construction changes.

Prepared service context for repeated portfolio replays:

```python
endpoint = QuantBTEndpoint.portfolio(
    portfolio_mode="market_neutral",
    backend="native_portfolio",
    hedge_type="signal_notional",
    report_level="minimal",
)

ctx = endpoint.prepare_service_context(data=data_dict, symbols=["BTC", "ETH"])

for positions in candidate_position_matrices:
    result = ctx.backtest(positions=positions)
```

This opt-in helper normalizes and packs the market tape once, then reuses
validated prepared arrays for repeated service/WFO-style runs. It does not alter
normal `.backtest(...)` behavior. Use it when the OHLC/funding tape is fixed
and many candidate position matrices are replayed. Rerun the selected candidate
with `report_level="full"` for stakeholder audit artifacts.

Experimental Nautilus portfolio validation:

```python
result = QuantBTEndpoint.portfolio(
    backend="nautilus",
    hedge_type="signal_notional",
    alloc_per_trade={"BTCUSDT-PERP.BINANCE": 50_000, "ETHUSDT-PERP.BINANCE": 50_000},
    initial_capital=1_000_000,
).simulate(
    positions=positions_df,
    data=data_dict,
    symbols=["BTCUSDT-PERP.BINANCE", "ETHUSDT-PERP.BINANCE"],
)
```

This route compiles position-matrix transitions into per-symbol market delta
orders and replays them in one Nautilus venue/account. Phase 11D compiles
Nautilus orders from the native portfolio `target_units_report`, so portfolio
mode transforms such as `market_neutral`, `directional`, and `equal_weight` are
included before validation. The run attaches
`result.metadata["portfolio_nautilus_validation_report"]`.

Supported sizing modes follow `native_portfolio`: `signal_notional`, `signal`,
`notional`, `unit`, `%_equity`, `target_weight`, `target_units`,
`target_notional`, `fixed_notional`, `gross_exposure`, and `net_exposure`.
`dca_ladder` remains on the DCA/grid endpoint.

## Nautilus Validation

Use this for smaller high-fidelity validation runs through the optional
NautilusTrader adapter. It is not the fast path for broad parameter sweeps.

```python
from quantbt import QuantBTEndpoint, export_nautilus_report_bundle
from quantbt.adapters.nautilus import NautilusBackendConfig

bt = QuantBTEndpoint.nautilus_validation(
    initial_capital=20_000,
    leverage=5,
    alloc_per_trade=10_000,
    hedge_type="signal_notional",
    use_pyramiding=True,
    fee_rate=0.0002,
    use_funding=False,
    nautilus_config=NautilusBackendConfig(
        timeframe="1h",
        starting_balance=20_000,
        trade_notional=10_000,
        close_positions_on_stop=False,
    ),
)

result = bt.simulate(
    data=df,
    signal_col="pos_weight",
    symbols=["ETHUSDT-PERP.BINANCE"],
    show_order_logs=True,
    order_log_mode="fills_only",
    order_log_limit=300,
)

fills = bt.fills_report
result.show_metrics()

report_dir = export_nautilus_report_bundle(
    result=result,
    output_dir="reports",
    strategy_id="eth_validation",
    make_quantstats=True,
    quantstats_periods_per_year=365,
    print_fills=False,
)
```

Requirements:

- `nautilus-trader` installed in the active Poetry environment;
- current adapter supports Binance USDT perpetual validation instruments:
  `BTCUSDT-PERP.BINANCE`, `ETHUSDT-PERP.BINANCE`, `BNBUSDT-PERP.BINANCE`,
  `SOLUSDT-PERP.BINANCE`, `DOGEUSDT-PERP.BINANCE`, `ARBUSDT-PERP.BINANCE`,
  and `LINKUSDT-PERP.BINANCE`;
- shorthand symbols such as `ETHUSDT`, `SOL`, and `ARP` are normalized where
  possible;
- single-symbol sizing modes supported today: `signal_notional`, `notional`,
  `unit`, and `%_equity`; pass either `hedge_type=` or `sizing=` to the
  endpoint factory;
- `use_pyramiding` is controlled at the endpoint level and forwarded into the
  Nautilus strategy adapter. `False` snaps raw signals to `-1/0/1`; `True`
  preserves fractional scales such as `1.4` in `%_equity` sizing;
- `%_equity` native-vs-Nautilus comparisons must align semantics before
  interpreting performance differences. Native legacy `fee=` is round-trip and
  is halved internally, while Nautilus `fee_rate=` is currently metadata for
  reporting and the signal adapter uses the Nautilus instrument fee model.
  Custom endpoint slippage and funding are also not applied by the current
  Nautilus signal-series adapter.
- for crypto fractional trading, use the same shared venue quantity constraints
  as native backends: `qty_step`/`lot_size`/`slot_size`/`min_qty`/
  `min_notional`. `contract_size` is a PnL and notional multiplier, not the
  Binance lot size. Do not set `contract_size=0.001` just to allow fractional
  ETH/BTC orders.
- DCA/grid, explicit order replay, pair trading, and multi-symbol portfolio
  validation remain on native QuantBT backends until their Nautilus event
  adapters are added;
- OHLCV data is converted to Nautilus external bars;
- signal is a single-symbol target series.
- `simulate(show_order_logs=True, order_log_mode="fills_only")` prints a
  bounded execution trace from Nautilus fills/orders. Supported modes are
  `fills_only`, `order_events`, and `bars_debug`; use `order_log_limit` to cap
  output for long multi-year intraday runs.
- `export_nautilus_report_bundle(...)` writes raw Nautilus account/order/fill/
  position reports, normalized trade logs, a run manifest, equity/returns CSVs,
  `config.json`, and optional QuantStats daily HTML. `config.json` is filled
  from endpoint/result metadata even when no explicit `config=` is passed. The
  report config uses grouped fields such as `effective_account`,
  `effective_sizing`, `effective_fees`, and `effective_execution` so there is
  one clear effective view; extra `config={...}` values are saved under
  `annotations` and do not override execution metadata. QuantStats uses daily
  equity returns by default with
  `quantstats_periods_per_year=365` for crypto.

Diagnostic helper for `%_equity` comparisons:

```python
diag = bt.nautilus_pct_equity_diagnostic(
    data=df_result,
    signal_col="pos_weight",
    native_fee_round_trip=0.0005,
    native_use_funding=True,
    native_slippage=0.0002,
)

display(diag["checks"])
display(diag["signal"]["transition_report"].head())
```

Use this before comparing `QuantBTEndpoint.pct_equity(...)` with
`QuantBTEndpoint.nautilus_validation(hedge_type="%_equity", ...)`; it reports
signal transition count, Nautilus order/fill count, fee/slippage/funding
semantic differences, and Binance quantity-step constraints.

Nautilus metadata:

```python
result.metadata["orders_report"]
result.metadata["fills_report"]
result.metadata["positions_report"]
result.metadata["use_pyramiding"]
result.metadata["orders_count"]
result.metadata["fills_count"]
result.metadata["positions_count"]
```

Routing:

- backend: `nautilus`;
- engine: `BacktestEngineV2` with Nautilus adapter.

## Walk-Forward

Use this to generate OOS signals/positions fold by fold, stitch them into one
continuous timeline, and run one final QuantBT backtest. The final simulation
uses the same engines as normal research, so fold-boundary trades are charged
with normal fees/slippage/margin behavior.

```python
from quantbt import QuantBTEndpoint

def strategy(data, params, train_index, test_index, fold):
    # Phase 1 contract: return OOS output only, indexed by test_index.
    return data["close"].reindex(test_index).gt(data["close"].rolling(params["window"]).mean()).astype(float)

wfo = QuantBTEndpoint.walk_forward(
    strategy_class=strategy,
    split_mode="walk_forward_2022",
    split_frequency="quarterly",  # yearly | semi_yearly | quarterly | monthly | weekly
    target_mode="signal_notional",
    optimization_mode="mode_1_decay",
    optimization_schedule="global",  # existing one-study lifecycle
    optimization_config={
        "decay_lambda": 0.5,
        "decay_gamma": 0.5,
        # anti-leakage candidate selection after IS-only Optuna search
        "top_is_fraction": 0.10,
        "top_is_k": None,
        "candidate_selection_metric": "robust_decay",
        "candidate_decay_lambda": None,
        "candidate_decay_gamma": None,
        # mode_2_sbb:
        "sbb_samples": 256,
        "sbb_block_length": 20,
        "sbb_decay_lambda": 0.5,
        "sbb_std_penalty": 0.1,
        "sbb_simulation": "stationary",  # stationary | regime | stress | garch
        "regime_count": 3,
        "regime_lookback": 20,
        "regime_weights": None,          # e.g. {"high": 0.6, "low": 0.4}
        "stress_vol_multiplier": 1.0,
        "garch_p": 1,
        "garch_q": 1,
        "garch_dist": "t",
        "garch_vol_multiplier": 1.0,
        # mode_3_flat_minima: "flat_top_fraction", "flat_eps",
        #                     "flat_min_samples", "flat_selector"
        # train-only selector for strict train/test split:
        # "candidate_selection_metric": "is_plateau_robust",
        # "scoring_backend": "endpoint",   # endpoint | proxy
        # "use_prepared_scoring_cache": True,
        # "prepared_scoring_report_level": "minimal",
        # "plateau_quantile": 0.25,
        # "plateau_median_weight": 0.25,
        # "plateau_std_penalty": 0.50,
        # "plateau_size_bonus": 0.01,
        # mode_4_is_only_robust:
        # "candidate_selection_metric": "is_only_robust",
        # "is_subperiods": 6,
        # "q25_weight": 0.30,
        # "dispersion_penalty": 0.50,
        # "temporal_weight": 0.65,
        # "plateau_weight": 0.35,
        # mode_5_full_robust:
        # "candidate_selection_metric": "full_robust",
        # alternatives: full_plateau_robust | full_temporal_robust | full_best
        # crypto default annualization: 365; equities often use 252
        "scoring_trading_days": 365,
        # optional under-trading penalty; None disables it
        "min_trades_per_year": None,
        "trade_penalty_factor": None,
        "use_numba": True,
    },
    optuna_trials=100,
    optuna_early_stopping=25,
    random_seed=42,
    initial_capital=20_000,
    leverage=5,
    alloc_per_trade=10_000,
    fee_rate=0.0002,
    use_funding=False,
)

result = wfo.backtest(
    data=df,
    symbols=["BTCUSDT"],
    param_ranges={"window": (10, 100, 5)},
)

result.metadata["walk_forward"]["fold_table"]
result.metadata["walk_forward"]["trial_table"]
result.metadata["walk_forward"]["candidate_table"]
result.metadata["walk_forward"]["best_trial"]
```

### Optimization schedules

`optimization_mode` defines how candidates are scored. The optional
`optimization_schedule` defines when QuantBT creates a new Optuna study:

| Schedule | Certified mode | Study lifecycle | Selection claim |
|---|---|---|---|
| `global` | Existing modes | One study over all configured folds; one final params set | Retrospective global calibration |
| `per_fold_decay` | `mode_1_decay` | One independent study per outer fold | Same-fold OOS is used to select among frozen top-IS candidates; selection-adjusted OOS |
| `per_fold_causal` | `mode_4_is_only_robust` | One independent study per outer fold | Params are selected from that fold's IS only; outer OOS is evaluated after selection |

Mode 1 fold-local decay calibration:

```python
wfo = QuantBTEndpoint.walk_forward(
    strategy_class=strategy,
    split_mode="walk_forward_2022",
    split_frequency="quarterly",
    window_mode="rolling",
    train_window="365D",
    target_mode="pct_equity",
    optimization_mode="mode_1_decay",
    optimization_schedule="per_fold_decay",
    fold_boundary_position_policy="carry",
    optimization_config={
        "candidate_selection_metric": "robust_decay",
        "top_is_fraction": 0.10,
        "scoring_backend": "endpoint",
    },
    optuna_trials=400,  # per fold for a per-fold schedule
    optuna_early_stopping=200,
    random_seed=42,
    initial_capital=20_000,
    leverage=5,
    alloc_per_trade=0.5,
    fee_rate=0.0005,
)
```

Strict fold-local IS-only retraining:

```python
wfo = QuantBTEndpoint.walk_forward(
    strategy_class=strategy,
    split_mode="walk_forward_2022",
    split_frequency="quarterly",
    window_mode="rolling",
    train_window="365D",
    target_mode="pct_equity",
    optimization_mode="mode_4_is_only_robust",
    optimization_schedule="per_fold_causal",
    optimization_config={
        "candidate_selection_metric": "is_only_robust",
        "top_is_fraction": 0.10,
        "scoring_backend": "endpoint",
    },
    optuna_trials=400,
    random_seed=42,
    initial_capital=20_000,
    leverage=5,
    alloc_per_trade=0.5,
    fee_rate=0.0005,
)
```

For both per-fold schedules, `optuna_trials`, early stopping, duplicate state,
and the deterministic seed belong to each fold's independent study. The fold
seed is derived from `random_seed` and `fold_id`. QuantBT returns the latest
completed fold's params through the backward-compatible `params` field and
stores the full parameter history in:

```python
wf = result.metadata["walk_forward"]
wf["params_by_fold"]
wf["fold_selection_table"]
wf["fold_boundary_table"]
wf["optimization_schedule"]
wf["causality_claim"]
wf["oos_used_for_selection"]
```

`fold_boundary_position_policy="carry"` is the only Phase 49A policy. QuantBT
stitches targets first and runs the account engine once. Equal targets across
a boundary do not create a synthetic close/reopen, reset equity, or duplicate
fees. Unsupported schedule/mode combinations raise; they never fall back to
`global`. Strict causal Mode 1 requires a future nested-validation contract and
is therefore not exposed by `per_fold_causal` today.

Prepared service context for repeated single-symbol runs:

```python
endpoint = QuantBTEndpoint.signal_notional(
    initial_capital=20_000,
    leverage=5,
    alloc_per_trade=10_000,
    fee_rate=0.0002,
    use_funding=False,
)

ctx = endpoint.prepare_service_context(data=df, symbols=["BTC"])

for signal in candidate_signals:
    result = ctx.backtest(signal=signal)
```

Supported prepared-context routes are intentionally narrow:

- `QuantBTEndpoint.signal_notional(..., backend="native_vectorized")`;
- `QuantBTEndpoint.portfolio(..., backend="native_portfolio")`.

Unsupported legacy/event/Nautilus modes raise `NotImplementedError` and should
continue using normal `.backtest(...)` or existing backend prepared APIs. The
context is caller-owned, run-local, and signature-validated by the backend; it
does not use a mutable global cache.

Prepared endpoint scoring:

- `optimization_config["use_prepared_scoring_cache"]` defaults to `True`.
- Supported prepared scoring routes currently include single-symbol
  `target_mode="signal_notional"` with `backend="native_vectorized"` and
  portfolio `target_mode="portfolio"` with `backend="native_portfolio"`.
- The cache is run-local to one `.backtest(...)` call and is guarded by
  datetime/symbol signatures. It avoids repeated pandas OHLC/funding packing
  during Optuna/WFO scoring.
- `prepared_scoring_report_level` defaults to `"minimal"` for portfolio scoring
  so trial objective calculation does not build heavy stakeholder reports for
  every candidate. Final stitched backtests still use the endpoint
  `report_level`, which defaults to `"full"`.

Single train/test holdout:

```python
tts = QuantBTEndpoint.train_test_split(
    strategy_class=strategy,
    test_start="2024-01-01",
    target_mode="pct_equity",
    optimization_mode="mode_2_sbb",  # none | mode_1_decay | mode_2_sbb | mode_3_flat_minima | mode_4_is_only_robust
    optimization_config={
        "sbb_samples": 256,
        "sbb_block_length": 24,
        "scoring_trading_days": 365,
        "min_trades_per_year": 20,
        "trade_penalty_factor": 0.5,
    },
    optuna_trials=100,
    initial_capital=20_000,
    leverage=5,
    alloc_per_trade=0.5,
    fee=0.0004,
)

result = tts.backtest(data=df, param_ranges=param_ranges)
result.metadata["walk_forward"]["split_frequency"]  # "single"
```

Preflight helpers:

```python
from quantbt import (
    benchmark_walkforward_kernels,
    validate_param_ranges,
    walkforward_support_matrix,
)

walkforward_support_matrix()
validate_param_ranges({"window": (10, 100, 5)})
benchmark_walkforward_kernels(n_obs=2_000, n_samples=128).to_dict()
```

Supported target routes:

- `signal_notional`, `notional`, and `unit`: strategy returns one scalar
  `pd.Series`; final run uses native vectorized/event according to backend.
- `pct_equity` / `%_equity`: strategy returns one scalar `pd.Series`; final run
  uses the legacy `%_equity` engine.
- `dca_ladder`: strategy returns structural ladder levels; final run uses the
  legacy DCA engine and requires `high/low`.
- `portfolio`: strategy returns a `DataFrame` or `{symbol: Series}`; final run
  uses `PortfolioBacktestEngine`.
- `basket`: strategy returns one scalar basket signal; final run uses the
  configured `BasketSpec`.
- `arbitrage`: strategy returns one scalar package signal; final run uses the
  configured arbitrage spec. Supported arbitrage specs follow
  `QuantBTEndpoint.arbitrage_support_matrix()`.

Strategy adapter contract:

```python
def strategy(data, params, train_index, test_index, fold):
    return oos_signal_or_positions
```

Classes/objects can expose either `build_signal(...)` or `generate_signal(...)`
with the same arguments.

Important rules:

- train data is always strictly before the OOS test window;
- data passed into the strategy is aligned to the UTC fold index, so tz-naive
  research frames can safely use `series.reindex(test_index)`;
- under either per-fold schedule, strategy data is physically truncated at
  `train_end` for IS calls and at `test_end` for OOS calls; the default
  `global` schedule retains its historical data-passing behavior for exact
  compatibility;
- outputs are sliced to `test_index` before stitching;
- strategy outputs must be timestamp-indexed `pd.Series`, `pd.DataFrame`, or
  `{symbol: pd.Series}` and cover every timestamp in the requested fold;
  missing fold timestamps are rejected to avoid silent all-zero OOS stitching;
- values outside OOS windows are filled with `0.0`;
- fixed-parameter runs pass `params=...`;
- `split_frequency` supports `single`, `yearly`, `semi_yearly`, `quarterly`,
  `monthly`, and `weekly`; `single` is used by
  `QuantBTEndpoint.train_test_split(...)` for one holdout fold;
- optimization modes are `mode_1_decay`, `mode_2_sbb`,
  `mode_3_flat_minima`, `mode_4_is_only_robust`, and
  `mode_5_full_robust`;
- raw Optuna trials receive only in-sample or synthetic in-sample objectives;
  OOS scoring is delayed until the top IS candidate set is frozen. With
  `per_fold_decay`, that same-fold OOS score deliberately selects the final
  candidate and is reported as selection-adjusted OOS. With
  `per_fold_causal`, Mode 4 selection never receives outer OOS metrics;
- candidate selection is controlled by `top_is_fraction` or `top_is_k`;
  `candidate_selection_metric` defaults to `robust_decay`. For strict
  train/test split validation, use `candidate_selection_metric="is_plateau_robust"`
  to select final params from the dense train-only plateau; OOS is then used
  only for final reporting/audit, not for parameter selection;
- endpoint-created WFO for single-symbol routes defaults to
  `scoring_backend="endpoint"` for `mode_1_decay` and `mode_3_flat_minima`.
  This means Optuna scores the train fold with the same selected QuantBT route
  (`pct_equity`, `signal_notional`, or `dca_ladder`) instead of the fast proxy.
  Set `scoring_backend="proxy"` when you explicitly want approximate scoring;
  `mode_2_sbb` always uses proxy return paths because it needs synthetic
  bootstrap/GARCH simulations. Proxy scoring uses the signal exactly as emitted
  by the strategy adapter; execution lag, if desired, belongs in the strategy
  layer;
- optimization-time scoring uses a transparent return proxy on strategy output;
  final accounting still comes from the stitched QuantBT backtest;
- optimization Sharpe annualization uses `scoring_trading_days` from
  `optimization_config` (`365` for always-on crypto by default, often `252` for
  equities);
- optional trade-frequency penalization can be enabled with
  `min_trades_per_year` and `trade_penalty_factor` to avoid low-trade Sharpe
  overfitting; leaving either unset keeps existing behavior unchanged;
- `mode_2_sbb` uses seeded train-fold synthetic simulation on strategy returns
  to estimate synthetic OOS robustness. Default `sbb_simulation="stationary"`
  preserves legacy stationary block bootstrap behavior;
- `mode_3_flat_minima` runs Optuna trials, clusters the top trial region, and
  selects the medoid or snapped centroid of the densest stable cluster instead
  of a sharp isolated peak;
- `mode_4_is_only_robust` is strict train-only selection. It optimizes IS,
  splits each IS fold into subperiod shards, scores temporal robustness from
  shard Sharpe stability, combines that with the existing plateau cluster
  score, and selects the medoid/centroid before any OOS scoring. OOS is only
  used afterward for reporting and final stitched validation;
- `mode_5_full_robust` is full-sample robust calibration, not WFO/OOS
  validation. QuantBT treats the whole supplied history as one calibration
  fold, uses Optuna plus robust selection across the full sample, and labels
  metadata with `validation_claim="none_full_sample_calibration"`. Use this
  after a strategy already passed separate validation, when the goal is to
  choose one production parameter set that survived all available regimes.
  Supported selectors are:
  `full_robust` (default temporal plus plateau),
  `full_plateau_robust` (dense parameter plateau only),
  `full_temporal_robust` (best subperiod stability among top trials), and
  `full_best` (best full-sample objective, highest overfit risk);
- numba accelerates repeated scoring/bootstrap loops when installed; Python /
  NumPy fallback remains available for debug and equivalence tests.

Mode 1 objective:

```text
Stage 1 Optuna objective = mean(IS_sharpe_after_penalties)

Stage 2 candidate objective = mean_oos_sharpe
                            - candidate_decay_lambda * std(IS - OOS)
                            - candidate_decay_gamma * max(0, mean(IS - OOS))
```

Mode 2 SBB objective:

```text
synthetic = mode_2_simulation(train_return_proxy)
objective = mean(synthetic_sharpe)
            - sbb_decay_lambda * max(0, IS_sharpe - mean(synthetic_sharpe))
            - sbb_std_penalty * std(synthetic_sharpe)
```

Mode 2 simulation choices:

- `stationary`: seeded stationary block bootstrap over IS strategy-return
  proxy. This is the default and fastest option.
- `regime`: trailing-volatility regimes are estimated on IS returns only, then
  blocks are sampled from selected regimes. Use `regime_weights` to stress the
  synthetic OOS mix, for example `{"high": 0.7, "low": 0.3}`.
- `stress`: demeaned IS returns are scaled by `stress_vol_multiplier` before
  SBB. This is useful for fast 1.5x/2x volatility stress tests.
- `garch`: fits `arch` GARCH(p, q) on IS returns only and simulates
  volatility-clustered paths. It is optional, slower than SBB, and should be
  used with enough train bars.

Regime-conditioned example:

```python
wfo = QuantBTEndpoint.walk_forward(
    strategy_class=strategy,
    split_mode="2022-01-01",
    split_frequency="monthly",
    target_mode="signal_notional",
    optimization_mode="mode_2_sbb",
    optimization_config={
        "sbb_simulation": "regime",
        "sbb_samples": 512,
        "sbb_block_length": 24,
        "regime_count": 3,
        "regime_lookback": 48,
        "regime_weights": {"high": 0.6, "normal": 0.3, "low": 0.1},
        "scoring_trading_days": 365,
        "use_numba": True,
    },
    optuna_trials=150,
    initial_capital=20_000,
    leverage=5,
    alloc_per_trade=10_000,
)
```

GARCH stress example:

```python
wfo = QuantBTEndpoint.walk_forward(
    strategy_class=strategy,
    split_mode=2022,
    split_frequency="quarterly",
    target_mode="signal_notional",
    optimization_mode="mode_2_sbb",
    optimization_config={
        "sbb_simulation": "garch",
        "sbb_samples": 128,
        "garch_p": 1,
        "garch_q": 1,
        "garch_dist": "t",
        "garch_vol_multiplier": 1.5,
    },
    optuna_trials=80,
)
```

Mode 3 flat-minima selector:

```text
1. score trials with the same IS-only objective as mode_1_decay;
2. take the top flat_top_fraction trials;
3. normalize numeric/categorical params into [0, 1];
4. density-cluster the top region with flat_eps and flat_min_samples;
5. select `flat_selector="medoid"` or `flat_selector="centroid"`;
6. if centroid is selected, snap it back to the declared param grid and
   include it in the frozen OOS candidate set.
```

Mode 4 IS-only robust selector:

```text
1. Optuna objective = IS score only.
2. Freeze top candidates with top_is_fraction or top_is_k.
3. Split each train fold into is_subperiods shards.
4. For each candidate, compute shard Sharpe values on IS only.
5. Temporal score:
   temporal = median(shard_sharpe)
            + q25_weight * q25(shard_sharpe)
            - dispersion_penalty * MAD(shard_sharpe)
6. Cluster top candidates in parameter space using flat_eps/flat_min_samples.
7. Plateau score reuses the existing plateau lower-tail/median/std logic.
8. Final train-only score:
   final = temporal_weight * temporal
         + plateau_weight * plateau_score
         - optional_bootstrap_penalty
         - optional_complexity_penalty
9. Select flat_selector="medoid" or "centroid"; then evaluate OOS only for
   reporting/audit.
```

Example:

```python
wfo = QuantBTEndpoint.walk_forward(
    strategy_class=strategy,
    split_mode="walk_forward_2022",
    split_frequency="quarterly",
    target_mode="pct_equity",
    optimization_mode="mode_4_is_only_robust",
    optimization_config={
        "top_is_fraction": 0.10,
        "is_subperiods": 6,
        "q25_weight": 0.30,
        "dispersion_penalty": 0.50,
        "temporal_weight": 0.65,
        "plateau_weight": 0.35,
        "flat_eps": 0.12,
        "flat_min_samples": 5,
        "flat_selector": "medoid",
        "scoring_backend": "endpoint",
        "scoring_trading_days": 365,
        "min_trades_per_year": 100,
        "trade_penalty_factor": 0.5,
        "use_numba": True,
    },
    optuna_trials=600,
    optuna_early_stopping=250,
    random_seed=42,
    initial_capital=20_000,
    leverage=5,
    alloc_per_trade=0.5,
    fee=0.0005,
)
```

Full-sample robust calibration example:

```python
cal = QuantBTEndpoint.walk_forward(
    strategy_class=strategy,
    target_mode="pct_equity",
    optimization_mode="mode_5_full_robust",
    optimization_config={
        "candidate_selection_metric": "full_robust",
        "top_is_fraction": 0.10,
        "is_subperiods": 8,
        "flat_eps": 0.12,
        "flat_min_samples": 5,
        "temporal_weight": 0.65,
        "plateau_weight": 0.35,
        "scoring_backend": "endpoint",
        "scoring_trading_days": 365,
        "min_trades_per_year": 100,
        "trade_penalty_factor": 0.5,
    },
    optuna_trials=600,
    random_seed=42,
    initial_capital=20_000,
    leverage=5,
    alloc_per_trade=0.5,
    fee=0.0005,
)
result = cal.backtest(data=df, param_ranges=param_ranges)
production_params = result.metadata["walk_forward"]["best_trial"]["params"]
```

Optional trade-frequency penalty:

```text
required_trades = min_trades_per_year * fold_duration_days / 365
penalty = trade_penalty_factor * max(0, 1 - actual_trade_count / required_trades)
penalized_sharpe = raw_sharpe - penalty
```

`actual_trade_count` is the number of initial non-zero fold positions plus
timestamp-to-timestamp position changes, not the notional size of those changes.
This keeps the penalty focused on under-trading rather than allocation
magnitude.

## Domain-Agnostic Optimization Adapters

Use standalone optimization adapters when you want Optuna tuning without WFO
fold stitching:

```python
from quantbt import (
    OptimizationConfig,
    SamplerConfig,
    OptunaOptimizer,
    PreparedSignalEvaluator,
    SharpeObjective,
)

endpoint = QuantBTEndpoint.signal_notional(
    backend="native_vectorized",
    initial_capital=20_000,
    leverage=5,
    alloc_per_trade=10_000,
    fee_rate=0.0002,
    use_funding=False,
)

prepared = endpoint.prepare_service_context(
    data=df,
    symbols=["BTCUSDT"],
)

evaluator = PreparedSignalEvaluator(
    prepared_context=prepared,
    strategy_func=lambda params: build_signal(df, params),
    objective_builder=SharpeObjective(),
)

study = OptunaOptimizer(
    evaluator=evaluator,
    config=OptimizationConfig(
        study_name="signal_search",
        n_trials=200,
        show_progress_bar=False,
    ),
    sampler_config=SamplerConfig(name="tpe"),
)

result = study.optimize(param_ranges=param_ranges)
```

Routes:

- `PreparedSignalEvaluator`: repeated single-symbol native-vectorized signal
  replays.
- `PreparedIntrabarEvaluator`: compact entry/SL/TP/trailing frames through
  `QuantBTEndpoint.intrabar_bracket(...).prepare_intrabar(...)`.
- `PreparedPortfolioEvaluator`: repeated native-portfolio position matrices.
- `GenericEndpointEvaluator`: arbitrage, grid/DCA, options, or any endpoint
  where `build_run_inputs(params)` can call `run_func(**inputs)`.

The optimizer core does not shift signals and does not own look-ahead
prevention. Strategy/research code owns feature causality; QuantBT endpoints
own execution simulation, fills, PnL, fee, funding, margin, and liquidation.
See [Domain-agnostic optimization](optimization.md) for full examples.

## Service Integration Pattern

Recommended shape for alpha services:

```python
def run_alpha_backtest(df, cfg):
    bt = QuantBTEndpoint.signal_notional(
        backend=cfg.get("backend", "native_vectorized"),
        initial_capital=cfg["initial_capital"],
        leverage=cfg["leverage"],
        alloc_per_trade=cfg["alloc_per_trade"],
        fee_rate=cfg.get("fee_rate", 0.0002),
        slippage_bps=cfg.get("slippage_bps", 0.0),
        use_funding=cfg.get("use_funding", False),
    )
    result = bt.backtest(
        data=df,
        signal_col=cfg.get("signal_col", "position"),
        symbols=[cfg.get("symbol", "DEFAULT")],
    )
    return {
        "result": result,
        "metrics": bt.full_report(),
        "metadata": result.metadata,
    }
```

Rules for services:

- construct a new endpoint per run configuration;
- pass data and signal only to `backtest()` / `simulate()`;
- store `result.metadata` with run artifacts;
- use factory defaults unless the strategy requires a specific backend;
- use `native_vectorized` for broad sweeps and `native_event` or `nautilus` for
  fill-level validation.

## Options Endpoint

`QuantBTEndpoint.options(...)` is the Phase 7 public route for native option
research. It is intentionally separate from `native_event` and generic
arbitrage because options require quote-side execution, premium-currency
cashflows, expiry/settlement, Greeks, and option margin.

Minimal call:

```python
from quantbt import (
    OptionPackageIntent,
    OptionPackageLeg,
    OrderSide,
    QuantBTEndpoint,
)

bt = QuantBTEndpoint.options(
    initial_capital=20_000,
    reporting_currency="USD",
    initial_balances={"USD": 20_000},
    conversion_rates={"BTC": 100_000},
    fee_rate=0.0001,
)

package = OptionPackageIntent(
    timestamp_ns=int(chain["timestamp_ns"].min()),
    package_id="long-call",
    legs=(
        OptionPackageLeg(
            instrument_id="BTC-01FEB26-100000-C.DERIBIT",
            side=OrderSide.BUY,
            ratio=1.0,
        ),
    ),
    quantity=1.0,
)

result = bt.backtest(
    chain=chain,
    instruments=option_registry,
    packages=[package],
)

bt.show_metrics()
fills = result.fills_report
greeks = result.greeks_report
margin = result.margin_report
manifest = result.run_manifest
```

Required data:

- `chain`: canonical long-form option chain with `timestamp_ns`,
  `instrument_id`, venue/static fields, bid/ask/mark prices, bid/ask size,
  index/forward price, IV and Greeks columns where available.
- `instruments`: `OptionInstrumentRegistry`, list, or mapping of
  `OptionInstrumentSpec`.
- `packages`: optional sequence of `OptionPackageIntent`. Strategy/template
  code owns signal generation and package construction; the backend owns
  execution, ledger, margin, settlement, and reports.
- `strategy_run`: optional `OptionStrategyRun` produced by an adapter such as
  `build_gamma_scalping_strategy_run(...)`. When supplied, the endpoint reads
  `strategy_run.packages`, stores `selected_contracts`, and carries strategy
  metadata into the run manifest.
- `underlying`: optional underlying price tape as `Series` or `DataFrame`
  (`timestamp_ns`/`time` plus `close` or `price`). Required for first-class
  delta-hedged option results.

Useful config:

- `reporting_currency`: reporting/account currency, default `USD`.
- `initial_balances`: multi-currency starting balances. If omitted, QuantBT
  starts with `initial_capital` in the reporting currency.
- `conversion_rates`: required whenever premium/settlement currency differs
  from reporting currency, for example inverse BTC options reported in USD.
- `fee_schedule`: optional venue-like `OptionFeeSchedule`; otherwise the
  endpoint fee rate is applied as a simple execution fee.
- `option_execution`: optional `OptionExecutionConfig` for quote age, partial
  fill, limit fidelity, and depth fidelity settings.
- `option_margin`: optional `OptionMarginConfig`. Current margin is an explicit
  approximation unless an external validator is provided in later phases.
- `settlement_events`: optional expiry settlement events passed to
  `backtest(...)`.
- `prepared_cache`: optional `OptionPreparedRunCache` passed to `backtest(...)`
  when replaying many package sets over the same option chain.
- `hedge_policy`: optional `OptionHedgeConfig`. If omitted, the endpoint uses
  `strategy_run.hedge_policy` when available.
- `net_option_delta`: optional externally supplied net-delta series. If omitted
  during a hedged run, QuantBT computes the path from executed option positions
  and observable chain Greeks.

Prepared cache pattern:

```python
from quantbt import OptionPreparedRunCache

cache = OptionPreparedRunCache.from_chain(chain, option_registry)

result = bt.backtest(
    chain=chain,
    instruments=option_registry,
    packages=packages,
    prepared_cache=cache,
)
```

Gamma-scalping adapter pattern:

```python
from quantbt import (
    GammaScalpingConfig,
    OptionHedgeConfig,
    OptionHedgePolicyType,
    QuantBTEndpoint,
    build_gamma_scalping_strategy_run,
)

strategy_run = build_gamma_scalping_strategy_run(
    chain,
    option_registry,
    GammaScalpingConfig(
        side="long",
        quantity=1.0,
        min_dte_days=10,
        max_dte_days=21,
        roll_dte_days=2,
        max_spread_bps=2_000,
        hedge_policy=OptionHedgeConfig(
            policy=OptionHedgePolicyType.FIXED_THRESHOLD,
            threshold=0.05,
        ),
    ),
)

bt = QuantBTEndpoint.options(
    initial_capital=100_000,
    reporting_currency="USD",
    initial_balances={"USD": 100_000},
    fee_rate=0.0002,
)

result = bt.backtest(
    chain=chain,
    instruments=option_registry,
    strategy_run=strategy_run,
    underlying=btc_spot_or_perp,
)

combined_equity = result.equity
option_only_equity = result.option_equity
hedge_log = result.hedge_report
selected = result.metadata["selected_contracts"]
```

For delta-hedged runs, `result.equity` is the combined option-plus-hedge
equity curve. The option-only curve remains available as `result.option_equity`.
QuantBT adds a pre-trade row at `first_timestamp - 1ns` so metrics begin from
the declared initial capital before the first option fill.

Returned result:

- `OptionBacktestResult`, compatible with `BacktestResultV2`.
- Standard helpers: `.show_metrics()`, `.full_report()`, `.quick_plot()`,
  `.tearsheet()`.
- Option audit tables: `fills_report`, `packages_report`, `cash_report`,
  `marks_report`, `greeks_report`, `settlements_report`, `margin_report`,
  `attribution_report`, `hedge_report`, `option_equity`, `combined_equity`,
  `combined_returns`, and `run_manifest`.

Support discovery:

```python
QuantBTEndpoint.options_support_matrix()
QuantBTEndpoint.arbitrage_support_matrix()["OptionsVolArbSpec"]
```

`OptionsVolArbSpec` is routed to the specialized option route only. It should
not be executed through generic arbitrage package backends.

### Option Strategy Templates

Phase 8 adds package builders under `quantbt.options.templates` and re-exports
them from top-level `quantbt`:

```python
from quantbt import long_call, vertical, butterfly, calendar

pkg = vertical(
    timestamp_ns,
    long_option_id="BTC-C100",
    short_option_id="BTC-C110",
    quantity=1.0,
)
```

Supported V1 builders:

- `long_call`, `short_call`, `long_put`, `short_put`;
- `straddle`, `strangle`;
- `vertical`, `butterfly`, `condor`, `calendar`;
- `covered_call`, `collar`, `risk_reversal`.

The builders only emit `OptionPackageIntent`. They do not compute payoff, PnL,
margin, or Greeks. Covered-call and collar templates include an explicit
underlying leg for domain clarity; the Phase 7 native option endpoint executes
option-chain legs only, so mixed underlying+option execution remains a later
adapter/engine fidelity item.

## Common Errors

`single-symbol endpoint requires data DataFrame`

- Pass `data=df` to `%_equity`, `signal_notional`, `dca_ladder`, `orders`, or
  `nautilus_validation`.

`single-symbol endpoint requires signal or signal_col`

- Pass `signal=series` or `signal_col="column_name"`.

`signal_col='x' not found in data`

- Make sure the signal column is present after DataFrame construction.

`multi-symbol endpoint requires data dict or explicit closes`

- Portfolio and basket modes need `{symbol: DataFrame}` or explicit
  `closes/highs/lows`.

`orders endpoint requires orders=[OrderIntent(...), ...]`

- `QuantBTEndpoint.orders()` must be called with explicit orders in
  `simulate()`.

`basket endpoint requires a BasketSpec`

- Pass `basket=BasketSpec(...)` either to the factory or to `simulate()`.

`arbitrage endpoint requires an arbitrage spec`

- Build a spec such as `BasisArbitrageSpec` or `StatArbPairSpec`, then pass it
  to `QuantBTEndpoint.arbitrage(arb_type="...", spec=spec, ...)`.

`inverse/quanto contract sizing is not implemented`

- Generic arbitrage execution currently supports spot and linear contracts.
  Inverse/quanto legs are guarded until exchange-specific sizing formulas are
  implemented.

`is schema-validated but requires a specialized arbitrage engine`

- The spec exists, but should not be run through generic package execution.
  Check `QuantBTEndpoint.arbitrage_support_matrix()` for the supported route.
