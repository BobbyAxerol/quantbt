# QuantBT Endpoint Contract

`QuantBTEndpoint` is the main integration class for notebooks, alpha services,
and research scripts.

Import:

```python
from quantbt import QuantBTEndpoint
```

The endpoint separates two concerns:

- constructor/factory: declares how the backtest should run;
- `backtest()` / `simulate()`: receives data, signals, orders, and baskets.

This keeps service code stable while QuantBT routes to the correct internal
engine.

## Quick Start

```python
bt = QuantBTEndpoint.signal_notional(
    backend="native_vectorized",
    initial_capital=20_000,
    leverage=5,
    alloc_per_trade=10_000,
    fee_rate=0.0002,
    use_funding=False,
)

result = bt.backtest(
    data=df,
    signal_col="pos_weight",
    symbols=["ETHUSDT"],
)

bt.show_metrics()
bt.quick_plot()
```

## Supported Modes

| Factory | Mode | Default backend | Strategy type |
|---|---|---|---|
| `QuantBTEndpoint.pct_equity()` | `%_equity` | `legacy` | equity-fraction single signal |
| `QuantBTEndpoint.signal_notional()` | `signal_notional` | `native_vectorized` | systematic target signal |
| `QuantBTEndpoint.dca_ladder()` | `dca_ladder` | `legacy` | DCA/grid structural levels |
| `QuantBTEndpoint.orders()` | `orders` | `native_event` | explicit order simulation |
| `QuantBTEndpoint.basket()` | `basket` | `native_event` | pair/basket frozen hedge |
| `QuantBTEndpoint.portfolio()` | `portfolio` | `legacy_portfolio` | multi-symbol portfolio |
| `QuantBTEndpoint.nautilus_validation()` | `nautilus_validation` | `nautilus` | high-fidelity validation |

You can also construct manually:

```python
bt = QuantBTEndpoint(
    mode="single_signal",
    backend="native_event",
    sizing="signal_notional",
    initial_capital=100_000,
    leverage=3,
)
```

## Common Helpers

Every endpoint instance stores the latest result:

```python
result = bt.result
engine = bt.engine
```

Helpers:

```python
bt.backtest(...)
bt.simulate(...)       # alias for backtest()
bt.full_report()
bt.show_metrics()
bt.quick_plot()
bt.tearsheet()
bt.export_orders("orders.csv")
bt.export_fills("fills.csv")
bt.metrics            # property alias for full_report()
```

`simulate()` is provided for event-style workflows, but it routes exactly like
`backtest()`.

## Single-Symbol Data Requirement

Single-symbol modes accept one pandas DataFrame.

Required:

- DatetimeIndex, or `Date` / `Datetime` / `Timestamp` column;
- `close` or `Close`.

Recommended:

- `open`;
- `high`;
- `low`;
- `volume`.

Column names are normalized from common title-case names:

```text
Open -> open
High -> high
Low -> low
Close -> close
Volume -> volume
Date/Datetime/Timestamp -> timestamp
```

If `high` or `low` are missing, they fall back to `close`. For crypto futures
and any intrabar liquidation/order-touch logic, always pass real `high` and
`low`.

Signal can be passed as a series:

```python
bt.backtest(data=df, signal=df["pos_weight"])
```

Or as a column name:

```python
bt.backtest(data=df, signal_col="pos_weight")
```

## `%_equity` Endpoint

Use this when `alloc_per_trade` is an equity fraction and signal changes should
resize from live equity.

```python
bt = QuantBTEndpoint.pct_equity(
    initial_capital=20_000,
    leverage=5,
    alloc_per_trade=0.5,
    fee=0.0004,          # round-trip fee, legacy convention
    slippage=0.0001,     # fraction, 1 bp
    use_pyramiding=False,
    use_funding=True,
    funding_rate=0.0001,
)

result = bt.backtest(data=df_result, signal_col="pos_weight")
```

Routing:

- backend: `legacy`;
- engine: `BacktestEngine`;
- reason: V2 parity for `%_equity` is not enabled yet.

## Signal-Notional Endpoint

Use this for most single-symbol systematic alphas.

```python
bt = QuantBTEndpoint.signal_notional(
    backend="native_vectorized",
    initial_capital=20_000,
    leverage=5,
    alloc_per_trade=10_000,
    fee_rate=0.0002,     # one-way fee, V2 convention
    slippage_bps=1.0,
    use_funding=False,
)

result = bt.backtest(data=df, signal_col="pos_weight", symbols=["ETHUSDT"])
```

Backends:

- `native_vectorized`: fastest research path;
- `native_event`: generates market rebalance orders and fills from the same
  signal contract.

Example event simulation:

```python
bt = QuantBTEndpoint.signal_notional(
    backend="native_event",
    initial_capital=20_000,
    leverage=5,
    alloc_per_trade=10_000,
)

result = bt.simulate(data=df, signal=df["pos_weight"], symbols=["ETHUSDT"])
fills = result.fills
```

For the same `signal_notional` contract, native vectorized and native event
should match on equity when using market rebalance orders.

## DCA/Grid Ladder Endpoint

Use when `signal` is a structural ladder level.

```python
bt = QuantBTEndpoint.dca_ladder(
    initial_capital=20_000,
    leverage=5,
    alloc_per_trade=1_000,
    dca_step_pct=0.01,
    dca_step_scale=1.2,
    dca_volume_scale=1.5,
    dca_max_safety_orders=5,
    dca_take_profit_pct=0.006,
)

result = bt.backtest(data=df, signal_col="grid_level")
```

Signal meaning:

- `0`: flat;
- `1`: base order active;
- `2`: base plus first safety order allowed;
- `6`: base plus five safety orders allowed;
- negative values represent short ladders.

Requirements:

- `high` and `low` are required for correct limit-touch simulation;
- safety orders fill at trigger/grid price, not close.

Routing:

- backend: `legacy`;
- engine: `BacktestEngine`;
- reason: this mode has a dedicated Numba DCA ladder kernel today.

## Explicit Orders Endpoint

Use when the strategy produces orders instead of target signals.

```python
from quantbt import OrderIntent, OrderSide, OrderType, TimeInForce

orders = [
    OrderIntent(
        timestamp=df.index[10],
        symbol="ETHUSDT",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        qty=3.0,
        price=1800.0,
        tif=TimeInForce.GTC,
    )
]

bt = QuantBTEndpoint.orders(
    initial_capital=100_000,
    leverage=5,
    fee_rate=0.0002,
    slippage_bps=1.0,
    use_funding=False,
)

result = bt.simulate(data=df, orders=orders, symbols=["ETHUSDT"])
bt.export_orders("orders.csv")
bt.export_fills("fills.csv")
```

Data requirement:

- one OHLCV DataFrame for the instrument stream;
- `symbols` should match `OrderIntent.symbol`.

Execution rules:

- market orders fill at close with slippage;
- limit orders fill at touched price when high/low crosses;
- IOC cancels if not touched on the order bar;
- GTC remains active until touched.

## Basket / Pair Endpoint

Use when a pair or basket needs frozen hedge-ratio entry and exact-unit exit.

```python
from quantbt import BasketLegSpec, BasketSpec

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
    use_funding=False,
)

result = bt.simulate(
    data={"BASE": base_df, "HEDGE": hedge_df},
    signal=pair_signal,
)
```

Data requirement:

- `data` as `{symbol: DataFrame}`;
- every leg symbol in `BasketSpec` must exist in data;
- each DataFrame needs at least `close`, recommended `high` and `low`;
- signal is a scalar series for basket on/off.

Diagnostics:

```python
result.metadata["basket_plan"]
result.metadata["basket_target_units"]
```

## Portfolio Endpoint

Use for multi-symbol position matrix backtests.

```python
bt = QuantBTEndpoint.portfolio(
    portfolio_mode="market_neutral",
    initial_capital=1_000_000,
    leverage=1,
    alloc_per_trade=50_000,
    asset_type="crypto",
    use_funding=False,
)

result = bt.backtest(
    positions=positions_df,       # columns are symbols
    data=data_dict,               # {symbol: OHLCV DataFrame}
)
```

`positions` can also be a `{symbol: Series}` mapping.

Supported portfolio modes:

- `longshort`;
- `market_neutral`;
- `directional`;
- `equal_weight`.

## Nautilus Validation Endpoint

Use for smaller high-fidelity validation runs.

```python
bt = QuantBTEndpoint.nautilus_validation(
    initial_capital=20_000,
    leverage=5,
    alloc_per_trade=10_000,
    use_funding=False,
)

result = bt.simulate(
    data=df,
    signal_col="pos_weight",
    symbols=["BTCUSDT-PERP.BINANCE"],
)
```

Requirements:

- `nautilus_trader` installed in the active environment;
- current adapter supports the test instrument `BTCUSDT-PERP.BINANCE`;
- OHLCV data is converted into Nautilus external bars.

Nautilus result metadata includes:

```python
result.metadata["orders_report"]
result.metadata["fills_report"]
result.metadata["positions_report"]
result.metadata["orders_count"]
result.metadata["fills_count"]
result.metadata["positions_count"]
```

## Service Integration Pattern

Recommended service code shape:

```python
def run_alpha_backtest(df, config):
    endpoint = QuantBTEndpoint.signal_notional(
        backend=config.get("backend", "native_vectorized"),
        initial_capital=config["initial_capital"],
        leverage=config["leverage"],
        alloc_per_trade=config["alloc_per_trade"],
        fee_rate=config.get("fee_rate", 0.0002),
        use_funding=config.get("use_funding", False),
    )
    result = endpoint.backtest(
        data=df,
        signal_col=config.get("signal_col", "position"),
        symbols=[config["symbol"]],
    )
    return {
        "result": result,
        "metrics": endpoint.full_report(),
    }
```

Service rules:

- construct endpoint once per run configuration;
- pass data/signals only to `backtest()` or `simulate()`;
- store `result.metadata` with run artifacts;
- use explicit backend only when the strategy requires it;
- prefer `backend="auto"` or the factory default for notebooks.

## Fee And Slippage Conventions

Legacy endpoints:

- `fee` is round-trip;
- `slippage` is a fraction.

V2 endpoints:

- `fee_rate` is one-way;
- `slippage_bps` is basis points.

The endpoint accepts both styles and forwards the correct values to the selected
engine.
