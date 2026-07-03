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
| `QuantBTEndpoint.dca_ladder()` | `dca_ladder` | `legacy` | structural DCA/grid levels with high/low limit-touch simulation |
| `QuantBTEndpoint.orders()` | `orders` | `native_event` | explicit `OrderIntent` market/limit/stop simulation |
| `QuantBTEndpoint.basket()` | `basket` | `native_event` | pair/basket entry with frozen hedge-ratio units |
| `QuantBTEndpoint.portfolio()` | `portfolio` | `legacy_portfolio` | multi-symbol position matrix portfolio backtest |
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
    contract_size=1.0,
    use_pyramiding=True,
)
```

Important conventions:

- `initial_capital` is account equity / initial margin;
- buying power is `initial_capital * leverage`;
- `alloc_per_trade` is not multiplied by leverage by the endpoint;
- legacy `fee` is round-trip and is halved inside `BacktestEngine`;
- V2 `fee_rate` is one-way;
- legacy `slippage` is a decimal fraction, e.g. `0.0001` for 1 bp;
- V2 `slippage_bps` is basis points, e.g. `1.0` for 1 bp.

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

rpt = bt.full_report(trading_days=365)
rpt = bt.show_metrics(trading_days=365)

bt.quick_plot(theme="dark", figsize=(14, 6))
bt.tearsheet(theme="dark")

bt.export_orders("orders.csv")
bt.export_fills("fills.csv")
```

`show_metrics()` prints a stable legacy-style text report and returns the same
dictionary as `full_report()`:

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

fills = result.fills
orders = result.metadata["order_report"]
```

Input requirement is the same as vectorized signal-notional.

Routing:

- backend: `native_event`;
- generated market orders are emitted on signal transitions;
- `result.fills` and `result.metadata["order_report"]` are available.

For plain market rebalance signals, native vectorized and native event should
match equity closely. Use event mode when fill-level diagnostics matter.

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

Order fields:

- `timestamp`: bar timestamp;
- `symbol`: instrument name;
- `side`: `OrderSide.BUY` or `OrderSide.SELL`;
- `order_type`: `MARKET`, `LIMIT`, `STOP_MARKET`, or `STOP_LIMIT`;
- `qty`: positive quantity;
- `price`: required for limit orders;
- `trigger_price`: required for stop orders;
- `tif`: `GTC`, `IOC`, `FOK`, or `GTD`.

Execution rules:

- market orders fill on the bar close with slippage;
- limit orders fill at the order price when the bar high/low touches it;
- IOC cancels if the order is not touched on its eligible bar;
- GTC remains active until filled or simulation ends.

Routing:

- backend: `native_event`;
- engine: `BacktestEngineV2`.

## Basket / Pair

Use this for pair trades or frozen hedge-ratio baskets. The basket signal is a
scalar series; the engine expands it to per-leg orders using `BasketSpec`.

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
result.fills
```

Routing:

- backend: `native_event`;
- engine: `BacktestEngineV2`.

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

- backend: `legacy_portfolio`;
- engine: `PortfolioBacktestEngine`.

## Nautilus Validation

Use this for smaller high-fidelity validation runs through the optional
NautilusTrader adapter. It is not the fast path for broad parameter sweeps.

```python
from quantbt import QuantBTEndpoint
from quantbt.adapters.nautilus import NautilusBackendConfig

bt = QuantBTEndpoint.nautilus_validation(
    initial_capital=20_000,
    leverage=5,
    alloc_per_trade=10_000,
    fee_rate=0.0002,
    use_funding=False,
    nautilus_config=NautilusBackendConfig(
        timeframe="1h",
        starting_balance=20_000,
        trade_notional=10_000,
        force_flat_on_stop=False,
    ),
)

result = bt.simulate(
    data=df,
    signal_col="pos_weight",
    symbols=["BTCUSDT-PERP.BINANCE"],
)

fills = result.metadata["fills_report"]
```

Requirements:

- `nautilus-trader` installed in the active Poetry environment;
- current adapter supports the validation instrument
  `BTCUSDT-PERP.BINANCE`;
- OHLCV data is converted to Nautilus external bars;
- signal is a single-symbol target series.

Nautilus metadata:

```python
result.metadata["orders_report"]
result.metadata["fills_report"]
result.metadata["positions_report"]
result.metadata["orders_count"]
result.metadata["fills_count"]
result.metadata["positions_count"]
```

Routing:

- backend: `nautilus`;
- engine: `BacktestEngineV2` with Nautilus adapter.

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
