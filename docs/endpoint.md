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
| `QuantBTEndpoint.arbitrage()` | `arbitrage` | `native_event` | package-style arbitrage specs and validation |
| `QuantBTEndpoint.walk_forward()` | `walk_forward` | `auto` | split/stitch OOS signals then route into existing endpoints |
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

bt.latest_orders
bt.fills
bt.order_report
bt.fills_report

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

The latest result object also exposes the same convenience methods:

```python
result.full_report()
result.show_metrics()
result.quick_plot()
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
result.metadata["beta_drift_report"]
```

Supported executable specs:

| Spec | Native event | Native vectorized | Nautilus | Notes |
|---|---:|---:|---:|---|
| `BasisArbitrageSpec` | yes | yes | package validation | linear USDM-style legs only today |
| `StatArbPairSpec` | yes | yes | package validation | frozen hedge-ratio pair; dynamic `hedge_ratios` supported |
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

- backend: `legacy_portfolio`;
- engine: `PortfolioBacktestEngine`.

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
  and optional QuantStats daily HTML.

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
- outputs are sliced to `test_index` before stitching;
- strategy outputs must be timestamp-indexed `pd.Series`, `pd.DataFrame`, or
  `{symbol: pd.Series}` and cover every timestamp in the requested fold;
  missing fold timestamps are rejected to avoid silent all-zero OOS stitching;
- values outside OOS windows are filled with `0.0`;
- fixed-parameter runs pass `params=...`;
- `split_frequency` supports `yearly`, `semi_yearly`, `quarterly`, `monthly`,
  and `weekly`; choose shorter splits for short-horizon/intraday strategies
  only when each train/OOS fold still has enough bars;
- optimization modes are `mode_1_decay`, `mode_2_sbb`, and
  `mode_3_flat_minima`;
- for all optimization modes, Optuna receives only in-sample or synthetic
  in-sample objectives; OOS scoring is delayed until after the top IS candidate
  set is frozen, reducing indirect look-ahead bias;
- candidate selection is controlled by `top_is_fraction` or `top_is_k`; OOS
  candidate ranking uses `candidate_selection_metric`, defaulting to
  `robust_decay`;
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
